"""2026-09-26 (agenda item 24): a model is never shown the text a secret
scan matched.

The steward's repair turn relayed the ledger's refusal of a sheet line whose
`note` held a secret, and the relayed message carried the matched span: the
secret never reached the ledger, but the model saw it (and the run record
kept it). Every message a runner shows its model, or commits into its run
record, about a secret-scan hit now names the rule and the offsets only:

- `batch` item details (`run` and `dry_run`) -- the seam behind the repair
  turn, the sent-back rows, the steward's case results, and the overseer's
  "Refused / could not do" lines;
- `route --dry-run`'s `would_refuse` entries (a batch route preview);
- the steward's apply-time case refusal and maintenance refusal, and the
  overseer's user-model refusal (`scan.refusal_text` over the hits the
  `CaseError` / `StatementError` / `UserModelError` now carries).

A person running a verb by hand still sees the span (`str(exc)` is
unchanged). Each test carries a positive control that the message IS
produced. The fake secret is built at runtime; none is committed.

Sandbox ledgers under pytest's tmpdir only.
"""

from __future__ import annotations

import random
import string
import pytest

from self_learn import batch, cases, scan, statements, steward, user_model, verbs
from self_learn.invocation.contract import Outcome
from support import make_env, make_knowledge
from test_steward import _dump_yaml, _enable_steward, _journal_rows, _stage_dir
from test_steward_refusals import (
    _REPAIR_HEADER,
    _case,
    _dispositions,
    _notifications,
    _seed,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _fake_token(seed: int = 24) -> str:
    rng = random.Random(seed)
    alnum = string.ascii_letters + string.digits
    return "gh" + "p_" + "".join(rng.choice(alnum) for _ in range(36))


SECRET = _fake_token()
RULE = "github-token"


def _path_segment(seed: int = 25) -> str:
    """30 random base64-charset characters with an upper, a lower and a
    digit: inside a folder path the scan fires on it as a segment, but on
    its own it is too short to fire again (under 40)."""
    rng = random.Random(seed)
    alnum = string.ascii_letters + string.digits
    while True:
        out = "".join(rng.choice(alnum) for _ in range(30))
        if any(c.isupper() for c in out) and any(c.islower() for c in out) \
                and any(c.isdigit() for c in out):
            return out


SEGMENT = _path_segment()
#: A secret whose span a scan of the refusal message itself cannot find
#: again, so only the hits the error carries can withhold it.
PATH_SECRET = f"/srv/cache/{SEGMENT}/data"


def _sheet(items: list[dict]) -> list[batch.SheetItem]:
    return [
        batch.SheetItem(n=n, id=item["id"], verb=item["verb"],
                        fields={k: v for k, v in item.items() if k not in {"id", "verb"}})
        for n, item in enumerate(items, start=1)
    ]


#: A record-file secret the machine's commit hooks let through (the
#: `credential-assignment` rule), so the sandbox ledger can commit it.
RECORD_SECRET = "pass" + "word = " + "hunter2" + "secret99"


# ------------------------------------------------------- the helper itself


def test_refusal_text_withholds_every_span_the_error_carries():
    text = "a path /data/x/y/z and " + SECRET
    hits = scan.scan(text)
    assert [h.rule for h in hits] == [RULE]  # positive control: the scan fires
    exc = verbs.SecretRefusal("refusing:\n" + scan.format_refusal(hits), hits)
    assert SECRET in str(exc)  # a person running the verb still sees it
    shown = scan.refusal_text(exc)
    assert SECRET not in shown
    assert f"[{RULE}]" in shown and scan.WITHHELD in shown


def test_a_span_that_does_not_match_alone_is_withheld_through_the_carried_hits():
    hits = scan.scan(PATH_SECRET)
    assert [h.span for h in hits] == [SEGMENT]  # positive control: the segment fires
    message = scan.format_refusal(hits)
    assert scan.scan(message) == []  # ...and does not fire again in the message
    exc = verbs.SecretRefusal(message, hits)
    shown = scan.refusal_text(exc)
    assert SEGMENT not in shown and "[high-entropy-base64]" in shown, shown


def test_a_secret_in_a_message_with_no_carried_hits_is_withheld_by_the_rescan():
    exc = verbs.VerbError(f"the line reads {SECRET}")
    assert not hasattr(exc, "hits")
    shown = scan.refusal_text(exc)
    assert SECRET not in shown and shown.startswith("the line reads "), shown


def test_refusal_text_reads_hits_from_the_exception_it_was_raised_from():
    hits = scan.scan(PATH_SECRET)
    inner = verbs.SecretRefusal(scan.format_refusal(hits), hits)
    try:
        try:
            raise inner
        except verbs.SecretRefusal as exc:
            raise verbs.VerbError(str(exc)) from exc
    except verbs.VerbError as outer:
        assert SEGMENT in str(outer)  # positive control
        shown = scan.refusal_text(outer)
    assert SEGMENT not in shown and "[high-entropy-base64]" in shown


def test_the_case_statement_and_user_model_errors_carry_their_hits(tmp_path):
    """The path-segment secret: only the carried hits can withhold it."""
    with pytest.raises(cases.CaseError) as case_exc:
        cases._scan_or_refuse([f"because {PATH_SECRET}"])  # noqa: SLF001
    home = make_env(tmp_path).ledger
    with pytest.raises(statements.StatementError) as stmt_exc:
        statements.add(home, verbatim=f"always {PATH_SECRET}",
                       source={"message_ref": "transcript:fake#L1"}, recorded_by="steward")
    with pytest.raises(user_model.UserModelError) as um_exc:
        user_model.add_entry(home, container="A", by="overseer", title="t",
                             because=f"b {PATH_SECRET}", source="own-words")
    with pytest.raises(user_model.UserModelError) as lapse_exc:
        entry = user_model.add_entry(home, container="D", by="overseer", title="t2",
                                     because="plain words", source="system-reading",
                                     ref="record:lrn-0123abcd")
        user_model.lapse_entry(home, entry, by="overseer",
                               changed_condition=f"moved to {PATH_SECRET}")
    for exc in (case_exc.value, stmt_exc.value, um_exc.value, lapse_exc.value):
        assert SEGMENT in str(exc), exc  # positive control: the span is in the message
        shown = scan.refusal_text(exc)
        assert SEGMENT not in shown and "[high-entropy-base64]" in shown, shown


# ------------------------------------------------------------ the batch seam


def test_a_batch_preview_of_a_note_with_a_secret_names_the_rule_only(tmp_path):
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-d2400001")
    for verb in ("reject", "route"):
        preview = batch.dry_run(home, _sheet([{"id": rid, "verb": verb, "note": f"see {SECRET}"}]),
                                actor="steward")
        (item,) = preview.items
        assert item.state == "would-refuse", (verb, item)  # positive control
        assert f"[{RULE}]" in (item.detail or ""), (verb, item.detail)
        assert SECRET not in str(preview.to_json()), verb


def test_a_batch_run_refusing_a_record_with_a_secret_names_the_rule_only(tmp_path):
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-d2400002", record=make_knowledge(
        scope="skill:s", record_id="lrn-d2400002", fact=RECORD_SECRET,
    ))

    result = batch.run(home, _sheet([{"id": rid, "verb": "reject"}]), actor="steward")

    (item,) = result.items
    assert item.state == "refused" and item.kind == "secret-record", item  # positive control
    assert "[credential-assignment]" in (item.detail or ""), item.detail
    assert "hunter2" not in (item.detail or "")


# ------------------------------------------------------- the steward's relays


def _stage_one(spec, rid: str, item: dict, outcome: str) -> Outcome:
    stage = _stage_dir(spec)
    _dump_yaml(stage / "cases" / f"{rid}.yaml", _case([rid], outcome, item["verb"]))
    _dump_yaml(stage / "sheets" / f"{rid}.yaml",
               {"version": 1, "case": "$CASE_ID", "items": [item]})
    return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)


def test_the_repair_turn_names_the_rule_and_never_the_secret(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-d2400003")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        if _REPAIR_HEADER in spec.prompt:
            return _stage_one(spec, rid, {"id": rid, "verb": "reject"}, "reject")
        return _stage_one(spec, rid, {"id": rid, "verb": "reject", "note": f"see {SECRET}"},
                          "reject")

    monkeypatch.setattr(steward.invocation, "write_session", session)

    result = steward.run(home)

    assert len(prompts) == 2, "the refused line went to the repair turn"  # positive control
    repair = prompts[1].split(_REPAIR_HEADER, 1)[1]
    assert "The ledger would refuse these lines of your sheets as written:" in repair
    assert f"- sheets/{rid}.yaml: item 1 (reject {rid}): " in repair
    assert f"[{RULE}]" in repair
    assert SECRET not in repair
    assert result.decided == [rid]


def test_an_apply_time_case_refusal_keeps_the_rule_and_not_the_secret(tmp_path, monkeypatch):
    """The sent-back row and the journal carry the case writer's refusal
    with the span withheld."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-d2400004")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        lambda spec: _stage_one(spec, rid, {"id": rid, "verb": "reject"}, "reject"),
    )
    real_record = steward.cases.record

    def record(home_, path, *, actor, reserved_id=None, **kwargs):
        if reserved_id is not None and actor == "steward":
            cases._scan_or_refuse([f"because {SECRET}"])  # noqa: SLF001
        return real_record(home_, path, actor=actor, reserved_id=reserved_id, **kwargs)

    monkeypatch.setattr(steward.cases, "record", record)

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "refused", row  # positive control
    assert f"[{RULE}]" in row["reason"] and SECRET not in row["reason"], row
    refused = [r for r in _journal_rows(home) if r.get("status") == "refused"]
    assert refused and all(SECRET not in str(r) for r in refused), refused


def test_a_maintenance_refusal_keeps_the_rule_and_not_the_secret(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-d2400005")
    _enable_steward(home)
    _notifications(monkeypatch)

    def session(spec):
        outcome = _stage_one(spec, rid, {"id": rid, "verb": "reject"}, "reject")
        _dump_yaml(_stage_dir(spec) / "statements.yaml",
                   [{"verbatim": "always check the thing",
                     "source": {"message_ref": "transcript:fake#L1"}}])
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", session)

    def add(*args, **kwargs):
        raise scan.attach_hits(
            statements.StatementError(scan.format_refusal(scan.scan(SECRET))),
            scan.scan(SECRET),
        )

    monkeypatch.setattr(steward.statements, "add", add)

    result = steward.run(home)

    rows = [r for r in _journal_rows(home) if r.get("status") == "statement-refused"]
    assert rows, _journal_rows(home)  # positive control: the operation was refused
    assert all(f"[{RULE}]" in r["error"] and SECRET not in r["error"] for r in rows), rows
    committed = str(steward.committed_manifests(home))
    assert result.run_id in committed and SECRET not in committed


# ------------------------------------------------------ the overseer's relay


def test_an_overseer_user_model_refusal_keeps_the_rule_and_not_the_secret(tmp_path):
    import json

    from self_learn import execution_evidence
    from self_learn.overseer import run as overseer_run
    from support import commit_all

    home = make_env(tmp_path).ledger
    run_id = "d2400006"
    payload = {
        "action": "add", "container": "D", "title": "One reading",
        "because": f"it said {RECORD_SECRET}", "source": "system-reading",
        "ref": "record:lrn-0123abcd",
    }
    operation = overseer_run._model_operation(payload, ordinal=1)  # noqa: SLF001
    path = execution_evidence.manifest_path(home, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "run_id": run_id, "maintenance": [operation]}) + "\n")
    commit_all(home, "self-learn: overseer prepare maintenance")

    applied, refused, halted, lines = overseer_run._maintain_manifest(home, run_id)  # noqa: SLF001

    assert (applied, refused, halted) == (0, 1, False)  # positive control
    manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
    error = manifest["maintenance"][0]["result"]["error"]
    assert "[credential-assignment]" in error and "hunter2" not in error, error
    assert lines and all("hunter2" not in line for line in lines), lines  # the report's lines
    rows = [r for r in overseer_run.read_journal(home, limit=100)
            if r.get("status") == "model-update-refused"]
    assert rows and all("hunter2" not in r["reason"] for r in rows), rows
