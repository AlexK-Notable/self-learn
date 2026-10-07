"""U4-harness · the session miner's output contract (``self_learn.mining.contract``).

K1-K4 of the U4 spec's section 7.9, plus K5 for ``load_run`` (the folder-level
agreement the spec's section 6.5 asks for). Synthetic documents only; no model,
no network, nothing outside ``tmp_path``.

On master every test here fails at import (the module does not exist); each is
also mutation-checked by breaking the rule it covers (the lane's report lists
the runs).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from self_learn import records, refs
from self_learn.mining import contract as c
from self_learn.scan import redact

# ------------------------------------------------------------------ examples

#: The spec's synthetic example (section 6.1), as the model would write it.
EXAMPLE = json.loads(
    """
{"contract": "miner-output-model/1",
 "lessons": [{"id": "L1", "shape": "correction", "scope": "user", "type": "behavior",
   "kind": "anti-pattern",
   "trigger": "About to accept a subagent's 'all tests pass' report as the result of delegated work",
   "instruction": "Open the files the subagent changed and run one check yourself before reporting; its report is a claim, not evidence.",
   "fact": null, "context": null,
   "evidence": [{"line": 640, "quote": "you handed this to a subagent and never checked what it wrote"}],
   "steps": [{"line": 602, "what": "agent delegates the fix to a subagent"},
             {"subagent": "a1b2c3d4e5", "line": 88, "what": "subagent reports success"},
             {"line": 640, "what": "user points out nothing was checked"},
             {"line": 701, "what": "agent opens the files and finds the change incomplete"}],
   "verification": {"line": 701, "quote": "the subagent reported success but", "how": "the agent reopened the files"},
   "incident_cost": null, "generality": "general-practice",
   "why_durable": "Delegation happens in most long sessions.",
   "subagent_cause": "unchecked-report"}],
 "sightings": [],
 "rule_checks": [{"record": "lrn-19f82fc5", "outcome": "cannot-tell",
                  "situation": {"line": 655}, "action": null}]}
"""
)

CANARY = "ZQXCANARY 7731 do-not-echo"


def _ref(line: int, role: str = "user", **extra) -> dict:
    d = {
        "session": "sess-1",
        "project_dir": "-work-repo",
        "line": line,
        "uuid": f"uuid-{line}",
        "entry_ts": "2026-09-01T10:00:00Z",
        "cwd": "/work/repo",
        "role": role,
    }
    d.update(extra)
    return d


def _evidence(line: int, role: str = "user", **extra) -> dict:
    d = {"ref": _ref(line, role), "turn": 3, "quote": "a quote", "verdict": "exact", "corrected_from": None}
    d.update(extra)
    return d


def checked_example() -> dict:
    return {
        "contract": "miner-output/1",
        "run_id": "20261006T010203Z-1",
        "mode": "testset",
        "model": "claude-sonnet-5",
        "method_version": "1",
        "session": {
            "id": "sess-1",
            "project_dir": "-work-repo",
            "file": "-work-repo/sess-1.jsonl",
            "judged": {"first_line": 1, "last_line": 900, "first_turn": 1, "last_turn": 9},
            "typed_turns": 9,
            "spine_tokens_est": 12_000,
            "over_budget": False,
            "search_mode": "lexical-only",
            "flags": [{"record": "lrn-19f82fc5", "turn": 7, "basis": "lexical"}],
        },
        "status": "ok",
        "lessons": [
            {
                "id": "L1",
                "shape": "correction",
                "scope": "user",
                "type": "behavior",
                "kind": "anti-pattern",
                "trigger": "About to accept a subagent report",
                "instruction": "Open the changed files first",
                "fact": None,
                "context": None,
                "evidence": [_evidence(640)],
                "steps": [
                    {"ref": _ref(602, "assistant"), "turn": 6, "what": "agent delegates"},
                    {"ref": _ref(640), "turn": 7, "what": "user objects"},
                ],
                "verification": dict(_evidence(701, "assistant"), how="the agent reopened the files"),
                "incident_cost": {"ref": _ref(701, "assistant"), "turn": 7, "text": "an hour lost"},
                "generality": "general-practice",
                "why_durable": "delegation recurs",
                "subagent_cause": "unchecked-report",
            }
        ],
        "sightings": [{"record": "lrn-19f82fc5", "evidence": [_evidence(655, corrected_from=650, verdict="nearby")]}],
        "rule_checks": [
            {
                "record": "lrn-19f82fc5",
                "outcome": "cannot-tell",
                "situation": {"ref": _ref(655, "assistant"), "turn": 7},
                "action": None,
            }
        ],
        "drops": [{"item": "L2.evidence[1]", "reason": "quote-not-found", "detail": "1 other session searched"}],
        "redactions": 0,
    }


def run_example() -> dict:
    return {
        "contract": "miner-shadow-run/1",
        "run_id": "20261006T010203Z-1",
        "mode": "testset",
        "started_at": "2026-10-06T01:02:03Z",
        "finished_at": "2026-10-06T01:20:00Z",
        "model": "claude-sonnet-5",
        "method_version": "1",
        "settings": {"parallel": 4, "spine_tokens": 20000, "max_usd": 40.0},
        "testset": {"dir": "set", "manifest_sha256": "0" * 64},
        "status": "ok",
        "search_mode": "lexical-only",
        "sessions": [
            _run_session("sess-1", "called", None, "ok", cost=0.31),
            _run_session("sess-2", "skipped", "no-marker", None),
            _run_session("sess-3", "not-run", "spend-ceiling", None),
        ],
        "totals": {
            "called": 1,
            "skipped": {"no-marker": 1},
            "not_run": 1,
            "cost_usd": 0.31,
            "lessons": 1,
            "sightings": 1,
            "rule_checks": 1,
            "drops": {"quote-not-found": 1},
        },
    }


def _run_session(sid: str, status: str, reason, out_status, *, cost=None) -> dict:
    return {
        "session": sid,
        "file": f"-work-repo/{sid}.jsonl",
        "status": status,
        "reason": reason,
        "out_status": out_status,
        "attempts": 1 if status == "called" else 0,
        "failure_class": None,
        "cost_usd": cost,
        "turns": 5 if status == "called" else None,
        "claude_session_id": "c-1" if status == "called" else None,
        "usage_first_response": {"input_tokens": 3} if status == "called" else None,
        "usage_session": None,
        "charter_denials": 0,
        "duration_secs": 12.5 if status == "called" else 0,
    }


def _mutated(base: dict, edit) -> dict:
    d = copy.deepcopy(base)
    edit(d)
    return d


def _has(errors: list[str], prefix: str) -> bool:
    return any(e.startswith(prefix) for e in errors)


def _lesson(d):  # the one lesson of the example
    return d["lessons"][0]


# ------------------------------------------------------------------------ K1


def test_k1_the_spec_example_validates():
    assert c.validate_model_output(EXAMPLE) == []


def _set(path_keys, value):
    def edit(d):
        node = d
        for k in path_keys[:-1]:
            node = node[k]
        node[path_keys[-1]] = value

    return edit


def _drop(path_keys):
    def edit(d):
        node = d
        for k in path_keys[:-1]:
            node = node[k]
        del node[path_keys[-1]]

    return edit


def _knowledge(d):
    L = _lesson(d)
    L.update(type="knowledge", kind=None, trigger=None, instruction=None, fact="A fact", context="Some context")


# (case id, edit, the path the message must start with)
K1_CASES = [
    ("contract-wrong", _set(["contract"], "miner-output-model/2"), "contract:"),
    ("missing-lessons", _drop(["lessons"]), "lessons: missing"),
    ("missing-sightings", _drop(["sightings"]), "sightings: missing"),
    ("missing-rule-checks", _drop(["rule_checks"]), "rule_checks: missing"),
    ("unknown-top-key", _set(["extra"], 1), "extra: unknown key"),
    ("lessons-not-array", _set(["lessons"], {}), "lessons: not an array"),
    ("too-many-lessons", lambda d: d.__setitem__("lessons", [dict(_lesson(d), id=f"L{i}") for i in range(1, 10)] * 2), "lessons: more than 10 items"),
    ("too-many-sightings", _set(["sightings"], [{"record": "lrn-19f82fc5", "evidence": [{"line": 1, "quote": "q"}]}] * 21), "sightings: more than 20 items"),
    ("too-many-rule-checks", lambda d: d.__setitem__("rule_checks", d["rule_checks"] * 9), "rule_checks: more than 8 items"),
    ("id-L11", _set(["lessons", 0, "id"], "L11"), "lessons[0].id:"),
    ("id-L0", _set(["lessons", 0, "id"], "L0"), "lessons[0].id:"),
    ("id-lowercase", _set(["lessons", 0, "id"], "l1"), "lessons[0].id:"),
    ("duplicate-id", lambda d: d["lessons"].append(copy.deepcopy(_lesson(d))), "lessons[1].id: duplicate id"),
    ("shape-enum", _set(["lessons", 0, "shape"], "gossip"), "lessons[0].shape:"),
    ("scope-empty-skill", _set(["lessons", 0, "scope"], "skill:"), "lessons[0].scope:"),
    ("scope-unknown", _set(["lessons", 0, "scope"], "team"), "lessons[0].scope:"),
    ("type-enum", _set(["lessons", 0, "type"], "rumour"), "lessons[0].type:"),
    ("kind-enum", _set(["lessons", 0, "kind"], "vibe"), "lessons[0].kind:"),
    ("kind-null", _set(["lessons", 0, "kind"], None), "lessons[0].kind:"),
    ("behavior-missing-kind", _drop(["lessons", 0, "kind"]), "lessons[0].kind: missing"),
    ("bad-type-bad-kind", lambda d: _lesson(d).update(type="rumour", kind="vibe"), "lessons[0].kind:"),
    ("knowledge-with-kind", lambda d: (_knowledge(d), _lesson(d).__setitem__("kind", "anti-pattern")), "lessons[0].kind: must be null for a knowledge lesson"),
    ("knowledge-with-bad-kind", lambda d: (_knowledge(d), _lesson(d).__setitem__("kind", "vibe")), "lessons[0].kind: must be null for a knowledge lesson"),
    ("behavior-no-trigger", _set(["lessons", 0, "trigger"], None), "lessons[0].trigger:"),
    ("behavior-no-instruction", _set(["lessons", 0, "instruction"], None), "lessons[0].instruction:"),
    ("behavior-with-fact", _set(["lessons", 0, "fact"], "a fact"), "lessons[0].fact: must be null"),
    ("behavior-with-context", _set(["lessons", 0, "context"], "ctx"), "lessons[0].context: must be null"),
    ("trigger-too-long", _set(["lessons", 0, "trigger"], "x" * 1001), "lessons[0].trigger: longer than 1000"),
    ("trigger-empty", _set(["lessons", 0, "trigger"], ""), "lessons[0].trigger: shorter than 1"),
    ("instruction-too-long", _set(["lessons", 0, "instruction"], "x" * 1001), "lessons[0].instruction: longer than 1000"),
    ("knowledge-no-fact", lambda d: (_knowledge(d), _lesson(d).__setitem__("fact", None)), "lessons[0].fact:"),
    ("knowledge-with-trigger", lambda d: (_knowledge(d), _lesson(d).__setitem__("trigger", "t")), "lessons[0].trigger: must be null"),
    ("knowledge-with-instruction", lambda d: (_knowledge(d), _lesson(d).__setitem__("instruction", "i")), "lessons[0].instruction: must be null"),
    ("knowledge-context-too-long", lambda d: (_knowledge(d), _lesson(d).__setitem__("context", "x" * 1001)), "lessons[0].context: longer than 1000"),
    ("knowledge-fact-too-long", lambda d: (_knowledge(d), _lesson(d).__setitem__("fact", "x" * 1001)), "lessons[0].fact: longer than 1000"),
    ("no-evidence", _set(["lessons", 0, "evidence"], []), "lessons[0].evidence: fewer than 1 items"),
    ("five-evidence", lambda d: _lesson(d).__setitem__("evidence", _lesson(d)["evidence"] * 5), "lessons[0].evidence: more than 4 items"),
    ("quote-too-long", _set(["lessons", 0, "evidence", 0, "quote"], "q" * 401), "lessons[0].evidence[0].quote: longer than 400"),
    ("quote-empty", _set(["lessons", 0, "evidence", 0, "quote"], ""), "lessons[0].evidence[0].quote: shorter than 1"),
    ("quote-missing", _drop(["lessons", 0, "evidence", 0, "quote"]), "lessons[0].evidence[0].quote: missing"),
    ("line-zero", _set(["lessons", 0, "evidence", 0, "line"], 0), "lessons[0].evidence[0].line:"),
    ("line-bool", _set(["lessons", 0, "evidence", 0, "line"], True), "lessons[0].evidence[0].line: not an integer"),
    ("line-string", _set(["lessons", 0, "evidence", 0, "line"], "640"), "lessons[0].evidence[0].line:"),
    ("line-float", _set(["lessons", 0, "evidence", 0, "line"], 640.0), "lessons[0].evidence[0].line: not an integer"),
    ("id-trailing-newline", _set(["lessons", 0, "id"], "L1\n"), "lessons[0].id:"),
    ("scope-skill-newline", _set(["lessons", 0, "scope"], "skill:\n"), "lessons[0].scope:"),
    ("scope-skill-multiline", _set(["lessons", 0, "scope"], "skill:a\nb"), "lessons[0].scope:"),
    # a valid name plus ONE trailing newline: the case a search or a prefix match lets through
    ("scope-skill-name-trailing-newline", _set(["lessons", 0, "scope"], "skill:name\n"), "lessons[0].scope:"),
    ("scope-user-trailing-newline", _set(["lessons", 0, "scope"], "user\n"), "lessons[0].scope:"),
    ("subagent-trailing-newline", _set(["lessons", 0, "steps", 1, "subagent"], "abc\n"), "lessons[0].steps[1].subagent:"),
    ("sighting-record-trailing-newline", _set(["sightings"], [{"record": "lrn-19f82fc5\n", "evidence": [{"line": 1, "quote": "q"}]}]), "sightings[0].record:"),
    ("check-record-trailing-newline", _set(["rule_checks", 0, "record"], "lrn-19f82fc5\n"), "rule_checks[0].record:"),
    ("subagent-bad-pattern", _set(["lessons", 0, "evidence", 0, "subagent"], "a b/c"), "lessons[0].evidence[0].subagent:"),
    ("subagent-too-long", _set(["lessons", 0, "evidence", 0, "subagent"], "a" * 65), "lessons[0].evidence[0].subagent:"),
    ("evidence-unknown-key", _set(["lessons", 0, "evidence", 0, "page"], 1), "lessons[0].evidence[0].page: unknown key"),
    ("lesson-unknown-key", _set(["lessons", 0, "confidence"], "high"), "lessons[0].confidence: unknown key"),
    ("lesson-missing-why", _drop(["lessons", 0, "why_durable"]), "lessons[0].why_durable: missing"),
    ("one-step", lambda d: _lesson(d).__setitem__("steps", _lesson(d)["steps"][:1]), "lessons[0].steps: must hold 0 or 2..6"),
    ("seven-steps", lambda d: _lesson(d).__setitem__("steps", (_lesson(d)["steps"] * 2)[:7]), "lessons[0].steps: must hold 0 or 2..6"),
    ("step-what-too-long", _set(["lessons", 0, "steps", 0, "what"], "w" * 301), "lessons[0].steps[0].what: longer than 300"),
    ("step-what-missing", _drop(["lessons", 0, "steps", 0, "what"]), "lessons[0].steps[0].what: missing"),
    ("step-line-zero", _set(["lessons", 0, "steps", 1, "line"], 0), "lessons[0].steps[1].line:"),
    ("verification-no-how", _drop(["lessons", 0, "verification", "how"]), "lessons[0].verification.how: missing"),
    ("verification-how-too-long", _set(["lessons", 0, "verification", "how"], "h" * 301), "lessons[0].verification.how: longer than 300"),
    ("verification-quote-too-long", _set(["lessons", 0, "verification", "quote"], "q" * 401), "lessons[0].verification.quote: longer than 400"),
    ("verification-not-object", _set(["lessons", 0, "verification"], "yes"), "lessons[0].verification: not an object"),
    ("cost-text-too-long", _set(["lessons", 0, "incident_cost"], {"line": 5, "text": "t" * 301}), "lessons[0].incident_cost.text: longer than 300"),
    ("cost-no-text", _set(["lessons", 0, "incident_cost"], {"line": 5}), "lessons[0].incident_cost.text: missing"),
    ("generality-enum", _set(["lessons", 0, "generality"], "sometimes"), "lessons[0].generality:"),
    ("why-too-long", _set(["lessons", 0, "why_durable"], "w" * 301), "lessons[0].why_durable: longer than 300"),
    ("why-empty", _set(["lessons", 0, "why_durable"], ""), "lessons[0].why_durable: shorter than 1"),
    ("cause-enum", _set(["lessons", 0, "subagent_cause"], "bad-weather"), "lessons[0].subagent_cause:"),
    ("sighting-bad-record", _set(["sightings"], [{"record": "lrn-XYZ", "evidence": [{"line": 1, "quote": "q"}]}]), "sightings[0].record:"),
    ("sighting-no-evidence", _set(["sightings"], [{"record": "lrn-19f82fc5", "evidence": []}]), "sightings[0].evidence: fewer than 1 items"),
    ("sighting-four-evidence", _set(["sightings"], [{"record": "lrn-19f82fc5", "evidence": [{"line": 1, "quote": "q"}] * 4}]), "sightings[0].evidence: more than 3 items"),
    ("sighting-quote-too-long", _set(["sightings"], [{"record": "lrn-19f82fc5", "evidence": [{"line": 1, "quote": "q" * 401}]}]), "sightings[0].evidence[0].quote: longer than 400"),
    ("check-bad-record", _set(["rule_checks", 0, "record"], "19f82fc5"), "rule_checks[0].record:"),
    ("check-outcome-enum", _set(["rule_checks", 0, "outcome"], "violated"), "rule_checks[0].outcome:"),
    ("check-no-situation", _drop(["rule_checks", 0, "situation"]), "rule_checks[0].situation: missing"),
    ("check-situation-line", _set(["rule_checks", 0, "situation", "line"], -3), "rule_checks[0].situation.line:"),
    ("check-action-unknown-key", _set(["rule_checks", 0, "action"], {"line": 4, "quote": "q"}), "rule_checks[0].action.quote: unknown key"),
    ("check-action-not-object", _set(["rule_checks", 0, "action"], "later"), "rule_checks[0].action: not an object"),
]


@pytest.mark.parametrize("case_id,edit,prefix", K1_CASES, ids=[k[0] for k in K1_CASES])
def test_k1_each_broken_rule_fails_with_its_path(case_id, edit, prefix):
    # positive control first: the unbroken example is valid
    assert c.validate_model_output(EXAMPLE) == []
    errors = c.validate_model_output(_mutated(EXAMPLE, edit))
    assert errors, case_id
    assert _has(errors, prefix), (case_id, errors)


@pytest.mark.parametrize("bad", [None, [], "text", 3])
def test_k1_a_root_that_is_not_an_object_is_refused(bad):
    assert c.validate_model_output(bad) == ["$: not an object"]


def test_k1_valid_knowledge_and_optional_fields_pass():
    d = _mutated(EXAMPLE, _knowledge)
    assert d["lessons"][0]["kind"] is None  # a knowledge lesson carries no kind, as a ledger record carries none
    assert c.validate_model_output(d) == []
    d["lessons"][0]["context"] = None
    d["lessons"][0]["steps"] = []
    d["lessons"][0]["verification"] = None
    d["lessons"][0]["subagent_cause"] = None
    d["lessons"][0]["scope"] = "skill:demo"
    d["rule_checks"][0]["action"] = {"line": 700, "subagent": "ab-12"}
    assert c.validate_model_output(d) == []


def test_k1_messages_never_echo_a_value():
    d = copy.deepcopy(EXAMPLE)
    lesson = d["lessons"][0]
    lesson["shape"] = CANARY
    lesson["scope"] = CANARY
    lesson["evidence"][0]["quote"] = CANARY * 40  # too long
    lesson["evidence"][0]["subagent"] = CANARY
    lesson["steps"][0]["what"] = CANARY * 40
    lesson[CANARY] = 1  # an invented key name with free text in it
    d[CANARY + "!"] = 1
    errors = c.validate_model_output(d)
    assert len(errors) >= 6  # positive control: each of the above was reported
    assert all("ZQX" not in e and "7731" not in e and "do-not-echo" not in e for e in errors), errors
    # a plain-identifier key IS named (so the path is useful)
    assert _has(c.validate_model_output(_mutated(EXAMPLE, _set(["lessons", 0, "bogus"], 1))), "lessons[0].bogus: unknown key")


def _secret_keys():
    """Key names the secret scan flags, built at run time (a literal would trip the commit scan)."""
    return ["ghp_" + "Q7w8E9r0" * 4 + "Zx1Y", "AKIA" + "QWERTYUIOPASDFGH"]


def test_k1_a_secret_shaped_key_is_never_echoed_but_a_plain_one_still_is():
    for secret in _secret_keys():
        assert len(secret) <= 41 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", secret)  # control: it looks like a plain identifier
        assert redact(secret)[0] != secret  # control: the secret scan flags it
        docs = (
            (c.validate_model_output, _mutated(EXAMPLE, _set([secret], 1))),
            (c.validate_model_output, _mutated(EXAMPLE, _set(["lessons", 0, secret], 1))),
            (c.validate_checked_output, _mutated(checked_example(), _set(["lessons", 0, "evidence", 0, secret], 1))),
            (c.validate_run, _mutated(run_example(), _set([secret], 1))),
        )
        for validate, doc in docs:
            errors = validate(doc)
            assert errors, validate  # positive control: the key was reported ...
            assert any("unknown key" in e for e in errors)
            assert all(secret not in e for e in errors), errors  # ... but not named
    # a plain identifier is still named, so a path stays useful (also in the checked output and run record)
    assert _has(c.validate_checked_output(_mutated(checked_example(), _set(["bogus"], 1))), "bogus: unknown key")
    assert _has(c.validate_run(_mutated(run_example(), _set(["bogus"], 1))), "bogus: unknown key")


def test_k1_every_error_is_a_path_then_a_message():
    for _id, edit, _prefix in K1_CASES:
        for e in c.validate_model_output(_mutated(EXAMPLE, edit)):
            path, sep, msg = e.partition(": ")
            assert sep and path and msg, e


# ------------------------------------------------------------------------ K2


#: SHA-256 of ``json.dumps(model_output_json_schema(), indent=1, sort_keys=True)``.
#: A change to the schema is always deliberate: update this constant with it.
SCHEMA_SHA256 = "3ae98270590b398a71247ed28694d8cf7bc964311856a44ea926870f5dbfb93b"


def _schema_text() -> str:
    return json.dumps(c.model_output_json_schema(), indent=1, sort_keys=True)


def test_k2_schema_is_stable():
    assert _schema_text() == _schema_text()
    assert hashlib.sha256(_schema_text().encode("utf-8")).hexdigest() == SCHEMA_SHA256
    # a fresh document per call: editing one never leaks into the next
    s = c.model_output_json_schema()
    s["properties"]["lessons"]["maxItems"] = 99
    assert c.model_output_json_schema()["properties"]["lessons"]["maxItems"] == c.MAX_LESSONS


def _json_schema_validators():
    """A JSON Schema validator for the model-output schema, plus the stock one.

    Two settings make the validator read the schema the way the model does: an integer is a token
    written without a fraction (stock draft 2020-12 calls 640.0 an integer; JSON text and this
    contract do not), and ``$`` ends the string (ECMA 262; Python's ``re`` lets ``$`` match before
    a final newline)."""
    import jsonschema
    from jsonschema import Draft202012Validator, validators

    def integer(_checker, instance):
        return isinstance(instance, int) and not isinstance(instance, bool)

    def pattern(validator, patrn, instance, _schema):
        if validator.is_type(instance, "string"):
            ecma = patrn[:-1] + r"\Z" if patrn.endswith("$") else patrn
            if not re.search(ecma, instance):
                yield jsonschema.ValidationError(f"does not match {patrn!r}")

    strict = validators.extend(
        Draft202012Validator,
        validators={"pattern": pattern},
        type_checker=Draft202012Validator.TYPE_CHECKER.redefine("integer", integer),
    )
    schema = c.model_output_json_schema()
    return strict(schema), Draft202012Validator(schema)


#: What JSON Schema cannot express: a lesson id used twice.
INEXPRESSIBLE_IN_JSON_SCHEMA = {"duplicate-id"}


def test_k2_the_validator_and_a_json_schema_validator_agree():
    strict, stock = _json_schema_validators()

    def schema_errors(doc):
        return list(strict.iter_errors(doc))

    # documents both accept
    valid = [EXAMPLE, _mutated(EXAMPLE, _knowledge)]
    optional = _mutated(EXAMPLE, lambda d: _lesson(d).update(context=None, steps=[], verification=None, subagent_cause=None, scope="skill:demo"))
    optional["rule_checks"][0]["action"] = {"line": 700, "subagent": "ab-12"}
    valid.append(optional)
    valid.append(_mutated(EXAMPLE, _set(["lessons", 0, "steps"], EXAMPLE["lessons"][0]["steps"][:2])))
    for doc in valid:
        assert c.validate_model_output(doc) == [] and schema_errors(doc) == []
    # documents both refuse: every K1 case the validator refuses, the schema refuses too, except duplicate ids
    disagreements = []
    for case_id, edit, _prefix in K1_CASES:
        doc = _mutated(EXAMPLE, edit)
        mine, lib = c.validate_model_output(doc), schema_errors(doc)
        assert mine, case_id
        if case_id in INEXPRESSIBLE_IN_JSON_SCHEMA:
            assert not lib, case_id  # the one difference, stated: a schema cannot say "unique ids"
        elif not lib:
            disagreements.append(case_id)
    assert disagreements == []
    # the three disagreements the gate found, by name
    one_step = _mutated(EXAMPLE, _set(["lessons", 0, "steps"], EXAMPLE["lessons"][0]["steps"][:1]))
    assert c.validate_model_output(one_step) and schema_errors(one_step)
    float_line = _mutated(EXAMPLE, _set(["lessons", 0, "evidence", 0, "line"], 640.0))
    assert c.validate_model_output(float_line) and schema_errors(float_line)
    assert not list(stock.iter_errors(float_line))  # control: stock draft 2020-12 calls 640.0 an integer, hence the strict reading
    newline_scope = _mutated(EXAMPLE, _set(["lessons", 0, "scope"], "skill:\n"))
    assert c.validate_model_output(newline_scope) and schema_errors(newline_scope)
    # the schema tells the model how to write a line number
    assert "640.0" in c.model_output_json_schema()["description"]


def _lesson_props(schema: dict) -> dict:
    return schema["properties"]["lessons"]["items"]["properties"]


def test_k2_schema_enums_equal_the_constants_and_the_imported_sets():
    s = c.model_output_json_schema()
    props = _lesson_props(s)
    assert props["shape"]["enum"] == list(c.SHAPES)
    assert props["type"]["enum"] == sorted(records.TYPES)
    assert [x for x in props["kind"]["enum"] if x is not None] == sorted(records.KINDS)
    assert None in props["kind"]["enum"]  # null, for a knowledge lesson
    assert props["generality"]["enum"] == sorted(records.GENERALITIES)
    assert [x for x in props["subagent_cause"]["enum"] if x is not None] == list(c.SUBAGENT_CAUSES)
    assert None in props["subagent_cause"]["enum"]
    rc = s["properties"]["rule_checks"]["items"]["properties"]
    assert rc["outcome"]["enum"] == list(c.OUTCOMES)
    # the constants are the spec's words, and the verdict subset is derived from refs
    assert c.SHAPES == ("correction", "verified-gotcha", "standing-preference", "repeated-friction")
    assert c.OUTCOMES == ("suspected-compliance", "suspected-violation", "cannot-tell")
    assert c.SUBAGENT_CAUSES == ("bad-brief", "left-brief", "unchecked-report")
    assert c.EVIDENCE_VERDICTS == ("exact", "normalised", "nearby", "elsewhere_in_file")
    assert set(c.EVIDENCE_VERDICTS) < set(refs.VERDICTS)
    # the closed set of drop reasons, as the spec lists them
    assert len(c.DROP_REASONS) == 15 and len(set(c.DROP_REASONS)) == 15
    assert {"over-count", "bad-output", "not-flagged", "quote-stitched"} <= set(c.DROP_REASONS)


def test_k2_schema_limits_and_required_keys_agree_with_the_validator():
    s = c.model_output_json_schema()
    top = s["properties"]
    assert top["lessons"]["maxItems"] == c.MAX_LESSONS
    assert top["sightings"]["maxItems"] == c.MAX_SIGHTINGS
    assert top["rule_checks"]["maxItems"] == c.MAX_RULE_CHECKS
    lesson = s["properties"]["lessons"]["items"]
    assert lesson["properties"]["evidence"]["maxItems"] == c.MAX_EVIDENCE
    assert lesson["properties"]["steps"]["maxItems"] == c.MAX_STEPS
    assert top["sightings"]["items"]["properties"]["evidence"]["maxItems"] == c.MAX_SIGHTING_EVIDENCE
    quote = lesson["properties"]["evidence"]["items"]["properties"]["quote"]
    assert quote["maxLength"] == c.QUOTE_MAX and quote["minLength"] == 1
    assert lesson["properties"]["trigger"]["maxLength"] == c.TEXT_MAX
    assert lesson["properties"]["why_durable"]["maxLength"] == c.WHY_DURABLE_MAX
    # every key the schema requires is required by the validator, at every level
    for key in s["required"]:
        assert _has(c.validate_model_output(_mutated(EXAMPLE, _drop([key]))), f"{key}: missing"), key
    for key in lesson["required"]:
        assert _has(c.validate_model_output(_mutated(EXAMPLE, _drop(["lessons", 0, key]))), f"lessons[0].{key}: missing"), key
    for key in lesson["properties"]["evidence"]["items"]["required"]:
        errs = c.validate_model_output(_mutated(EXAMPLE, _drop(["lessons", 0, "evidence", 0, key])))
        assert _has(errs, f"lessons[0].evidence[0].{key}: missing"), key
    # every key the example carries is a key the schema defines (nothing the validator accepts is missing from it)
    assert set(EXAMPLE["lessons"][0]) == set(lesson["properties"])
    assert set(EXAMPLE["rule_checks"][0]) == set(top["rule_checks"]["items"]["properties"])
    # the schema says what the validator says about kind: one of the kinds for behavior, null for knowledge
    then = {b["if"]["properties"]["type"]["const"]: b["then"]["properties"] for b in lesson["allOf"]}
    assert then["behavior"]["kind"] == {"enum": sorted(records.KINDS)}
    assert then["knowledge"]["kind"] == {"type": "null"}
    assert lesson["additionalProperties"] is False and s["additionalProperties"] is False
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert s["properties"]["contract"] == {"const": c.MODEL_CONTRACT}


# ------------------------------------------------------------------------ K3


def test_k3_checked_output_and_run_record_validate():
    assert c.validate_checked_output(checked_example()) == []
    assert c.validate_run(run_example()) == []


def _cl(d):
    return d["lessons"][0]


def _cknowledge(d):
    _cl(d).update(type="knowledge", kind=None, trigger=None, instruction=None, fact="A fact", context=None)


K3_CHECKED_CASES = [
    ("root", None, "$: not an object"),
    ("contract", _set(["contract"], "miner-output/2"), "contract:"),
    ("missing-drops", _drop(["drops"]), "drops: missing"),
    ("unknown-top-key", _set(["extra"], 1), "extra: unknown key"),
    ("mode-enum", _set(["mode"], "weekly"), "mode:"),
    ("status-enum", _set(["status"], "great"), "status:"),
    ("run-id-empty", _set(["run_id"], ""), "run_id: shorter than 1"),
    ("redactions-negative", _set(["redactions"], -1), "redactions: less than 0"),
    ("redactions-bool", _set(["redactions"], False), "redactions: not an integer"),
    ("session-missing-id", _drop(["session", "id"]), "session.id: missing"),
    ("judged-last-before-first", _set(["session", "judged", "last_line"], 0), "session.judged.last_line:"),
    ("judged-reversed", lambda d: d["session"]["judged"].update(first_line=50, last_line=10), "session.judged.last_line: before first_line"),
    ("judged-turn-negative", _set(["session", "judged", "first_turn"], -1), "session.judged.first_turn:"),
    ("typed-turns-str", _set(["session", "typed_turns"], "9"), "session.typed_turns:"),
    ("over-budget-int", _set(["session", "over_budget"], 1), "session.over_budget: not a boolean"),
    ("search-mode-enum", _set(["session", "search_mode"], "semantic"), "session.search_mode:"),
    ("flag-basis-enum", _set(["session", "flags", 0, "basis"], "vibes"), "session.flags[0].basis:"),
    ("flag-record-pattern", _set(["session", "flags", 0, "record"], "x"), "session.flags[0].record:"),
    ("ref-missing-role", _drop(["lessons", 0, "evidence", 0, "ref", "role"]), "lessons[0].evidence[0].ref.role: missing"),
    ("ref-role-enum", _set(["lessons", 0, "evidence", 0, "ref", "role"], "bot"), "lessons[0].evidence[0].ref.role:"),
    ("ref-line-zero", _set(["lessons", 0, "evidence", 0, "ref", "line"], 0), "lessons[0].evidence[0].ref.line:"),
    ("ref-unknown-key", _set(["lessons", 0, "evidence", 0, "ref", "extra"], 1), "lessons[0].evidence[0].ref.extra: unknown key"),
    ("ref-uuid-int", _set(["lessons", 0, "evidence", 0, "ref", "uuid"], 5), "lessons[0].evidence[0].ref.uuid:"),
    ("ref-subagent-file-empty", _set(["lessons", 0, "evidence", 0, "ref", "subagent_file"], ""), "lessons[0].evidence[0].ref.subagent_file:"),
    ("evidence-no-verdict", _drop(["lessons", 0, "evidence", 0, "verdict"]), "lessons[0].evidence[0].verdict: missing"),
    ("verdict-stitched", _set(["lessons", 0, "evidence", 0, "verdict"], "stitched"), "lessons[0].evidence[0].verdict:"),
    ("verdict-not-found", _set(["lessons", 0, "evidence", 0, "verdict"], "not_found"), "lessons[0].evidence[0].verdict:"),
    ("corrected-from-zero", _set(["lessons", 0, "evidence", 0, "corrected_from"], 0), "lessons[0].evidence[0].corrected_from:"),
    ("turn-str", _set(["lessons", 0, "evidence", 0, "turn"], "3"), "lessons[0].evidence[0].turn:"),
    ("evidence-quote-too-long", _set(["lessons", 0, "evidence", 0, "quote"], "q" * 401), "lessons[0].evidence[0].quote: longer than 400"),
    ("lesson-text-rule", _set(["lessons", 0, "trigger"], None), "lessons[0].trigger:"),
    ("lesson-behavior-with-fact", _set(["lessons", 0, "fact"], "f"), "lessons[0].fact: must be null"),
    ("lesson-behavior-no-kind", _set(["lessons", 0, "kind"], None), "lessons[0].kind:"),
    ("lesson-behavior-missing-kind", _drop(["lessons", 0, "kind"]), "lessons[0].kind: missing"),
    ("lesson-knowledge-with-kind", lambda d: (_cknowledge(d), _cl(d).__setitem__("kind", "anti-pattern")), "lessons[0].kind: must be null for a knowledge lesson"),
    ("lesson-unknown-key", _set(["lessons", 0, "confidence"], "high"), "lessons[0].confidence: unknown key"),
    ("lesson-missing-key", _drop(["lessons", 0, "why_durable"]), "lessons[0].why_durable: missing"),
    ("lesson-id-pattern", _set(["lessons", 0, "id"], "L12"), "lessons[0].id:"),
    ("lesson-duplicate-id", lambda d: d["lessons"].append(copy.deepcopy(_cl(d))), "lessons[1].id: duplicate id"),
    ("lesson-no-evidence", _set(["lessons", 0, "evidence"], []), "lessons[0].evidence: fewer than 1 items"),
    ("steps-one", lambda d: _cl(d).__setitem__("steps", _cl(d)["steps"][:1]), "lessons[0].steps: must hold 0 or 2..6"),
    ("step-no-ref", _drop(["lessons", 0, "steps", 0, "ref"]), "lessons[0].steps[0].ref: missing"),
    ("step-what-too-long", _set(["lessons", 0, "steps", 0, "what"], "w" * 301), "lessons[0].steps[0].what: longer than 300"),
    ("verification-no-how", _drop(["lessons", 0, "verification", "how"]), "lessons[0].verification.how: missing"),
    ("verification-no-ref", _drop(["lessons", 0, "verification", "ref"]), "lessons[0].verification.ref: missing"),
    ("cost-text-too-long", _set(["lessons", 0, "incident_cost", "text"], "t" * 301), "lessons[0].incident_cost.text: longer than 300"),
    ("cost-no-ref", _drop(["lessons", 0, "incident_cost", "ref"]), "lessons[0].incident_cost.ref: missing"),
    ("too-many-lessons", lambda d: d.__setitem__("lessons", [dict(_cl(d), id=f"L{i}") for i in range(1, 10)] * 2), "lessons: more than 10 items"),
    ("sighting-bad-record", _set(["sightings", 0, "record"], "nope"), "sightings[0].record:"),
    ("sighting-no-evidence", _set(["sightings", 0, "evidence"], []), "sightings[0].evidence: fewer than 1 items"),
    ("sighting-evidence-shape", _set(["sightings", 0, "evidence", 0, "ref"], {}), "sightings[0].evidence[0].ref.session: missing"),
    ("check-outcome", _set(["rule_checks", 0, "outcome"], "violated"), "rule_checks[0].outcome:"),
    ("check-situation-bare-line", _set(["rule_checks", 0, "situation"], {"line": 3}), "rule_checks[0].situation.ref: missing"),
    ("check-action-bare-line", _set(["rule_checks", 0, "action"], {"line": 3}), "rule_checks[0].action.ref: missing"),
    ("drop-reason-enum", _set(["drops", 0, "reason"], "felt-like-it"), "drops[0].reason:"),
    ("drop-detail-too-long", _set(["drops", 0, "detail"], "d" * 201), "drops[0].detail: longer than 200"),
    ("drop-item-not-a-path", _set(["drops", 0, "item"], "a quote with spaces"), "drops[0].item: does not match"),
    ("drop-item-empty", _set(["drops", 0, "item"], ""), "drops[0].item: shorter than 1"),
    ("drop-item-trailing-newline", _set(["drops", 0, "item"], "L2\n"), "drops[0].item: does not match"),
    ("lesson-id-trailing-newline", _set(["lessons", 0, "id"], "L1\n"), "lessons[0].id:"),
    ("lesson-scope-newline", _set(["lessons", 0, "scope"], "skill:\n"), "lessons[0].scope:"),
    ("lesson-scope-name-trailing-newline", _set(["lessons", 0, "scope"], "skill:name\n"), "lessons[0].scope:"),
    ("sighting-record-trailing-newline", _set(["sightings", 0, "record"], "lrn-19f82fc5\n"), "sightings[0].record:"),
    ("flag-record-trailing-newline", _set(["session", "flags", 0, "record"], "lrn-19f82fc5\n"), "session.flags[0].record:"),
    ("drop-unknown-key", _set(["drops", 0, "text"], "t"), "drops[0].text: unknown key"),
    ("failed-with-lessons", _set(["status"], "failed"), "lessons: must be empty unless the status is ok"),
    ("bad-output-with-sightings", _set(["status"], "bad-output"), "sightings: must be empty unless the status is ok"),
]


@pytest.mark.parametrize("case_id,edit,prefix", K3_CHECKED_CASES, ids=[k[0] for k in K3_CHECKED_CASES])
def test_k3_each_broken_checked_output_fails_with_its_path(case_id, edit, prefix):
    assert c.validate_checked_output(checked_example()) == []  # control
    obj = None if edit is None else _mutated(checked_example(), edit)
    errors = c.validate_checked_output(obj)
    assert errors, case_id
    assert _has(errors, prefix), (case_id, errors)


def test_k3_a_checked_knowledge_lesson_has_no_kind():
    d = _mutated(checked_example(), _cknowledge)
    assert _cl(d)["kind"] is None
    assert c.validate_checked_output(d) == []  # accepted without a kind
    _cl(d)["kind"] = "anti-pattern"
    assert _has(c.validate_checked_output(d), "lessons[0].kind: must be null for a knowledge lesson")  # refused with one


def test_k3_a_session_that_did_not_succeed_may_carry_empty_lists():
    d = checked_example()
    d.update(status="failed", lessons=[], sightings=[], rule_checks=[])
    assert c.validate_checked_output(d) == []


def _skip_edit(**kw):
    def edit(d):
        d["sessions"][1].update(kw)

    return edit


K3_RUN_CASES = [
    ("root", None, "$: not an object"),
    ("contract", _set(["contract"], "miner-shadow-run/2"), "contract:"),
    ("mode", _set(["mode"], "weekly"), "mode:"),
    ("started-not-iso", _set(["started_at"], "yesterday"), "started_at: not an ISO-8601"),
    ("finished-int", _set(["finished_at"], 5), "finished_at:"),
    ("settings-parallel-zero", _set(["settings", "parallel"], 0), "settings.parallel:"),
    ("settings-max-usd-str", _set(["settings", "max_usd"], "40"), "settings.max_usd:"),
    ("settings-missing", _drop(["settings", "spine_tokens"]), "settings.spine_tokens: missing"),
    ("testset-sha", _set(["testset", "manifest_sha256"], "abc"), "testset.manifest_sha256:"),
    ("testset-sha-trailing-newline", _set(["testset", "manifest_sha256"], "0" * 64 + "\n"), "testset.manifest_sha256:"),
    ("session-listed-twice", lambda d: d["sessions"].append(copy.deepcopy(d["sessions"][1])), "sessions[3].session: listed twice"),
    ("called-session-listed-twice", lambda d: d["sessions"].insert(1, copy.deepcopy(d["sessions"][0])), "sessions[1].session: listed twice"),
    ("testset-missing-dir", _drop(["testset", "dir"]), "testset.dir: missing"),
    ("status-enum", _set(["status"], "done"), "status:"),
    ("search-mode", _set(["search_mode"], "both"), "search_mode:"),
    ("session-status", _set(["sessions", 0, "status"], "ran"), "sessions[0].status:"),
    ("session-missing-key", _drop(["sessions", 0, "duration_secs"]), "sessions[0].duration_secs: missing"),
    ("session-unknown-key", _set(["sessions", 0, "extra"], 1), "sessions[0].extra: unknown key"),
    ("session-cost-str", _set(["sessions", 0, "cost_usd"], "0.3"), "sessions[0].cost_usd:"),
    ("session-attempts-negative", _set(["sessions", 0, "attempts"], -1), "sessions[0].attempts:"),
    ("called-with-reason", _set(["sessions", 0, "reason"], "no-marker"), "sessions[0].reason: must be null for a called"),
    ("called-without-out-status", _set(["sessions", 0, "out_status"], None), "sessions[0].out_status: a called session needs"),
    ("called-bad-out-status", _set(["sessions", 0, "out_status"], "fine"), "sessions[0].out_status:"),
    ("skip-reason-enum", _skip_edit(reason="boring"), "sessions[1].reason:"),
    ("skip-reason-null", _skip_edit(reason=None), "sessions[1].reason:"),
    ("skip-with-out-status", _skip_edit(out_status="ok"), "sessions[1].out_status: must be null unless"),
    ("not-run-reason", _set(["sessions", 2, "reason"], "no-marker"), "sessions[2].reason:"),
    ("usage-not-object", _set(["sessions", 0, "usage_session"], 5), "sessions[0].usage_session: not an object or null"),
    ("totals-called", _set(["totals", "called"], 2), "totals.called: does not equal"),
    ("totals-not-run", _set(["totals", "not_run"], 0), "totals.not_run: does not equal"),
    ("totals-skipped-tally", _set(["totals", "skipped"], {"halted": 1}), "totals.skipped: does not equal"),
    ("totals-skipped-key", _set(["totals", "skipped"], {"boring": 1}), "totals.skipped: key not in the closed set"),
    ("totals-drops-key", _set(["totals", "drops"], {"felt-like-it": 1}), "totals.drops: key not in the closed set"),
    ("totals-drops-negative", _set(["totals", "drops"], {"duplicate": -1}), "totals.drops.duplicate: less than 0"),
    ("totals-cost-negative", _set(["totals", "cost_usd"], -1), "totals.cost_usd:"),
    ("totals-missing", _drop(["totals", "lessons"]), "totals.lessons: missing"),
]


@pytest.mark.parametrize("case_id,edit,prefix", K3_RUN_CASES, ids=[k[0] for k in K3_RUN_CASES])
def test_k3_each_broken_run_record_fails_with_its_path(case_id, edit, prefix):
    assert c.validate_run(run_example()) == []  # control
    obj = None if edit is None else _mutated(run_example(), edit)
    errors = c.validate_run(obj)
    assert errors, case_id
    assert _has(errors, prefix), (case_id, errors)


def test_k3_a_dry_run_and_an_activation_may_list_no_sessions():
    for status in ("dry-run", "activated"):
        d = run_example()
        d.update(status=status, sessions=[], testset=None, finished_at=None, mode="night")
        d["totals"] = {"called": 0, "skipped": {}, "not_run": 0, "cost_usd": 0, "lessons": 0, "sightings": 0, "rule_checks": 0, "drops": {}}
        assert c.validate_run(d) == [], status


# ------------------------------------------------------------------------ K4


def _typed(text: str, **extra) -> dict:
    e = {"type": "user", "message": {"role": "user", "content": text}, "origin": {"kind": "human"}, "promptSource": "typed"}
    e.update(extra)
    return e


def _asst(text: str = "ok", **extra) -> dict:
    e = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    e.update(extra)
    return e


def _result(text: str = "out") -> dict:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": text}]}}


def _plain_user(text: str, **extra) -> dict:
    e = {"type": "user", "message": {"role": "user", "content": text}}
    e.update(extra)
    return e


def test_k4_typed_turn_lines_follow_the_role_rules():
    entries = [
        _typed("first typed turn"),  # L1  user (origin human)
        _asst("an answer"),  # L2  assistant
        _result("a tool result"),  # L3  tool_result
        _plain_user("<task-notification>done</task-notification>", origin={"kind": "task-notification"}),  # L4 relay
        _plain_user("skill text", isMeta=True),  # L5 relay
        _plain_user("a summary", isCompactSummary=True),  # L6 relay
        _plain_user("a program prompt", promptSource="sdk"),  # L7 relay
        _plain_user("<local-command-stdout>x</local-command-stdout>"),  # L8 relay (envelope)
        _plain_user("an older typed turn with no marker"),  # L9 user (structural rule)
        {"type": "attachment", "attachment": {"type": "queued_command", "prompt": "do the docs too", "origin": {"kind": "human"}}},  # L10 user
        {"type": "attachment", "attachment": {"type": "queued_command", "prompt": "from a peer", "origin": {"kind": "peer"}}},  # L11 relay
        _typed("   "),  # L12 blank text: not a turn
        _typed("a sidechain turn", isSidechain=True),  # L13 subagent
        {"type": "last-prompt"},  # L14 bookkeeping
        _typed("the last typed turn"),  # L15
    ]
    assert c.typed_turn_lines(entries) == [1, 9, 10, 15]
    # control: the helper really does read each entry (a different rule set gives a different answer)
    assert refs.role_of(entries[4]) == "relay" and refs.role_of(entries[8]) == "user"


def test_k4_a_slot_per_physical_line_keeps_the_numbers_true():
    entries = [_typed("one"), None, _asst("two"), None, None, _typed("three")]
    assert c.typed_turn_lines(entries) == [1, 6]
    assert c.typed_turn_lines([]) == []
    assert c.typed_turn_lines([None, None]) == []


def test_k4_has_typed_turn_marker():
    assert c.has_typed_turn_marker([_asst(), _typed("hi")]) is True  # origin object
    assert c.has_typed_turn_marker([_plain_user("hi", promptSource="sdk")]) is True  # promptSource key alone
    assert c.has_typed_turn_marker([_plain_user("hi", promptSource=None)]) is True  # the key, not its value
    # controls: no marker, a non-object origin, markers on rows that are not user rows
    assert c.has_typed_turn_marker([_plain_user("old session"), _asst()]) is False
    assert c.has_typed_turn_marker([_plain_user("hi", origin="human")]) is False
    assert c.has_typed_turn_marker([_asst(origin={"kind": "human"}, promptSource="typed")]) is False
    assert c.has_typed_turn_marker([{"type": "attachment", "origin": {"kind": "human"}}]) is False
    assert c.has_typed_turn_marker([None, None]) is False
    assert c.has_typed_turn_marker([]) is False


def test_k4_turn_of():
    lines = [10, 20, 30]
    assert [c.turn_of(lines, n) for n in (1, 9, 10, 11, 19, 20, 29, 30, 31, 10**6)] == [0, 0, 1, 1, 1, 2, 2, 3, 3, 3]
    assert c.turn_of([], 5) == 0


def test_k4_the_one_definition_agrees_with_the_roles_on_a_whole_file():
    # T<k> numbering equals "the k-th entry whose role is user (and has text)"
    entries = [_typed("a"), _result(), _asst(), _typed("b"), _plain_user("c", isMeta=True), _typed("d")]
    lines = c.typed_turn_lines(entries)
    assert lines == [1, 4, 6]
    assert [c.turn_of(lines, n) for n in range(1, 7)] == [1, 1, 1, 2, 2, 3]


# ------------------------------------------------------------------------ K5


def _write_run(root: Path, *, run=None, outs=None) -> Path:
    run = run if run is not None else _loadable_run()
    root.mkdir(parents=True, exist_ok=True)
    (root / "run.json").write_text(json.dumps(run), encoding="utf-8")
    (root / "out").mkdir(exist_ok=True)
    for name, obj in (outs if outs is not None else {"sess-1": checked_example()}).items():
        (root / "out" / f"{name}.json").write_text(json.dumps(obj), encoding="utf-8")
    return root


def _loadable_run() -> dict:
    return run_example()


def test_k5_load_run_reads_and_validates_a_folder(tmp_path):
    root = _write_run(tmp_path / "run")
    run, outs = c.load_run(root)
    assert run["run_id"] == "20261006T010203Z-1"
    assert list(outs) == ["sess-1"] and outs["sess-1"]["lessons"][0]["id"] == "L1"


def _load_errors(tmp_path, **kw) -> list[str]:
    with pytest.raises(c.ContractError) as exc:
        c.load_run(_write_run(tmp_path / "bad", **kw))
    return exc.value.errors


def test_k5_load_run_names_the_file_and_the_path(tmp_path):
    bad_run = _mutated(run_example(), _set(["mode"], "weekly"))
    assert _has(_load_errors(tmp_path, run=bad_run), "run.json: mode:")
    # control: the same folder with a good run.json loads (checked above)


def test_k5_a_broken_out_file_is_named(tmp_path):
    bad = _mutated(checked_example(), _set(["lessons", 0, "shape"], "gossip"))
    assert _has(_load_errors(tmp_path, outs={"sess-1": bad}), "out/sess-1.json: lessons[0].shape:")


def test_k5_folder_must_agree_with_itself(tmp_path):
    # a called session with no out file
    assert _has(_load_errors(tmp_path, outs={}), "out/sess-1.json: missing for a called session")


def test_k5_agreement_checks(tmp_path):
    other = checked_example()
    other["session"]["id"] = "sess-9"
    errs = _load_errors(tmp_path / "a", outs={"sess-1": checked_example(), "sess-9": other})
    assert _has(errs, "out/sess-9.json: present for a session that was not called")

    wrong_name = _load_errors(tmp_path / "b", outs={"sess-1": other})
    assert _has(wrong_name, "out/sess-1.json: session.id does not match the file name")

    run_id = _mutated(checked_example(), _set(["run_id"], "other-run"))
    assert _has(_load_errors(tmp_path / "c", outs={"sess-1": run_id}), "out/sess-1.json: run_id differs")

    mode = _mutated(checked_example(), _set(["mode"], "night"))
    assert _has(_load_errors(tmp_path / "d", outs={"sess-1": mode}), "out/sess-1.json: mode differs")

    status = _mutated(checked_example(), lambda d: d.update(status="failed", lessons=[], sightings=[], rule_checks=[]))
    assert _has(_load_errors(tmp_path / "e", outs={"sess-1": status}), "out/sess-1.json: status differs")


def test_k5_totals_must_equal_the_files(tmp_path):
    run = _mutated(run_example(), _set(["totals", "lessons"], 4))
    assert _has(_load_errors(tmp_path / "a", run=run), "run.json: totals.lessons does not equal the out files")
    run = _mutated(run_example(), _set(["totals", "drops"], {"duplicate": 1}))
    assert _has(_load_errors(tmp_path / "b", run=run), "run.json: totals.drops does not equal the out files")


def test_k5_a_session_listed_twice_is_refused_in_either_order(tmp_path):
    for n, order in enumerate((0, 1)):
        run = run_example()
        first, dup = run["sessions"][0], dict(run["sessions"][1], session="sess-1")
        run["sessions"][:2] = [first, dup] if order == 0 else [dup, first]
        assert _has(_load_errors(tmp_path / f"d{n}", run=run), "run.json: sessions[1].session: listed twice")


def test_k5_missing_or_garbled_files(tmp_path):
    with pytest.raises(c.ContractError) as exc:
        c.load_run(tmp_path / "nowhere")
    assert exc.value.errors == ["run.json: missing"]
    root = _write_run(tmp_path / "garbled")
    (root / "run.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(c.ContractError) as exc2:
        c.load_run(root)
    assert exc2.value.errors[0].startswith("run.json: not valid JSON")
    assert "not json" not in exc2.value.errors[0]
