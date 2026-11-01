"""The inbox reader (attention round 2026-10-31c, design r2 §5.1 tests
1-8, 12, 13 and 15).

Every test here is a person's shell unless it sets an agent marker itself
(design r2 §3.4.1, "Tests in agent shells"): the module fixture deletes
``settings.AGENT_CALLER_MARKERS``.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import (
    attention,
    cases,
    cli,
    execution_evidence,
    miner,
    settings,
    skill_cli,
    statements,
    steward,
    user_model,
    workspace,
)
from self_learn.invocation.contract import Outcome
from support import commit_all, git, make_env, make_home
from test_steward import _dump_yaml, _enable_steward, _seed_fresh_proposals, _write_decision_stage


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(path))
    return path


def _iso(delta: timedelta = timedelta()) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _journal(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _steward_journal(home: Path) -> Path:
    return attention.cache_dir(home) / "steward" / "journal.jsonl"


LOGIN_CAUSE = "API Error: OAuth token has expired. Please run /login"


def _login_hold(home: Path, at: str) -> None:
    _journal(_steward_journal(home), [
        {"ts": at, "run_id": "run-x", "status": "held-environment", "cause": LOGIN_CAUSE},
    ])


def _items(home: Path, **kw) -> list[dict]:
    return attention.read(home, **kw)["items"]


def _by_kind(home: Path, kind: str) -> list[dict]:
    return [i for i in _items(home) if i["kind"] == kind]


# ------------------------------------------------------------------ 1. KINDS


_TABLE = {
    "hold.credentials": ("needs-you", "credentials", False),
    "hold.money": ("needs-you", "money", False),
    "broken.host": ("needs-you", "broken", False),
    "broken.stopped": ("needs-you", "broken", False),
    "broken.job": ("needs-you", "broken", False),
    "conflict.case-tampered": ("needs-you", "conflict", False),
    "ask.system-change": ("needs-you", "system-change", False),
    "ask.foreign-history": ("needs-you", "foreign-history", False),
    "ask.conflict": ("needs-you", "conflict", False),
    "ask.money": ("needs-you", "money", False),
    "ask.sudo": ("needs-you", "sudo", False),
    "approved.pending": ("approved", None, False),
    "decided.overseer-run": ("decided", None, True),
    "decided.steward-run": ("decided", None, False),
    "decided.always-loaded": ("decided", None, True),
    "decided.hook-activated": ("decided", None, True),
    "decided.ask-default": ("decided", None, False),
    "decided.reading": ("decided", None, False),
    "decided.grant-use": ("decided", None, False),
    "decided.registration": ("decided", None, False),
    "decided.skill": ("decided", None, False),
    "decided.notice": ("decided", None, False),
    "decided.withdrawn": ("decided", None, False),
    "decided.approved-done": ("decided", None, True),
    "decided.ledger-paths": ("decided", None, False),
}


def test_every_kind_lands_in_its_class_key_and_flag():
    """Mutation: `hold.credentials` set to decided -> red; empty options
    for `broken.host` -> red."""
    assert set(attention.KINDS) == set(_TABLE)
    for kind, (klass, because, flagged) in _TABLE.items():
        row = attention.KINDS[kind]
        assert (row.klass, row.because, row.flagged) == (klass, because, flagged), kind
    assert [k for k, r in attention.KINDS.items() if r.popup] == ["hold.credentials"]
    code_needs = [
        k for k, r in attention.KINDS.items() if r.klass == "needs-you" and not k.startswith("ask.")
    ]
    assert code_needs, "positive control: the code needs-you kinds are found"
    for kind in code_needs:
        options = attention.KINDS[kind].options
        assert options, f"{kind} must offer at least one action"
        assert all(o["id"].startswith("opt-") and o["label"] for o in options)
    assert [o["id"] for o in attention.KINDS["broken.host"].options] == ["opt-restart"]
    assert [o["id"] for o in attention.KINDS["hold.credentials"].options] == ["opt-login", "opt-check"]
    assert {o["id"] for o in attention.KINDS["conflict.case-tampered"].options} == {"opt-keep", "opt-restore"}
    for kind in ("broken.stopped", "broken.job"):
        row = attention.KINDS[kind]
        assert row.options[0]["effect"] == "approve" and row.plan and row.plan["checks"]
    # The settings registry offers a class override for every code kind.
    assert set(settings.ATTENTION_CODE_KINDS) == {k for k in attention.KINDS if not k.startswith("ask.")}


# ------------------------------------------------------------------ 2. ask rows


_OO7 = {
    "id": "q-oo7-daemon-bus-binding", "kind": "ask", "cases": ["case-0fcce296"],
    "text": "Bind oo7-daemon to the session bus so it survives a bus restart?",
    "why": "It changes how your desktop starts a service, outside self-learn.",
    "needs": "user", "because": "system-change",
    "default": "Nothing on your system was changed; answer if you want it done.",
    "asked_at": "2026-09-28T04:15:00Z",
    "options": [
        {"id": "opt-yes", "label": "Yes, add the binding", "effect": "approve"},
        {"id": "opt-yes-conditions", "label": "Yes, with conditions", "effect": "approve", "note": "required"},
        {"id": "opt-no", "label": "No, keep the manual note", "effect": "decline"},
    ],
    "recommend": {"option": "opt-yes", "reasoning": "the drop-in is the standard fix"},
    "plan": {
        "summary": "Add a systemd drop-in binding oo7-daemon to dbus-broker.", "cwd": None,
        "checks": [{"say": "No drop-in binds it already", "command": "systemctl --user show oo7-daemon.service --property=DropInPaths"}],
        "steps": [{"say": "Reload user units", "command": "systemctl --user daemon-reload", "sudo": False}],
        "files": [],
    },
    "look_at": [], "statements": [],
}


def _ask(**over) -> dict:
    row = {"id": "q-x", "kind": "ask", "cases": [], "text": "A question?", "why": "because"}
    row.update(over)
    return row


def test_ask_rows_are_classified_with_legacy_inference(home, monkeypatch):
    """Mutation: drop the legacy inference (`system`/`register`) -> red."""
    rows = [
        _OO7,
        _ask(id="q-legacy-system", system=True, default="Nothing on your system was changed."),
        _ask(id="q-legacy-register", register={"path": "/x", "mode": "plain", "kind": "project"}),
        _ask(id="q-stead", needs="stead", default="Agents keep doing it the usual way."),
        _ask(id="q-bad-key", needs="user", because="credentials", default="d"),
    ]
    monkeypatch.setattr(attention, "_load_questions", lambda _home: rows)
    by_subject = {i["subject"]: i for i in _items(home)}
    assert (by_subject["q-oo7-daemon-bus-binding"]["kind"], by_subject["q-oo7-daemon-bus-binding"]["class"]) == (
        "ask.system-change", "needs-you")
    assert by_subject["q-oo7-daemon-bus-binding"]["because"] == "system-change"
    assert by_subject["q-legacy-system"]["kind"] == "ask.system-change"
    assert by_subject["q-legacy-register"]["kind"] == "ask.foreign-history"
    assert by_subject["q-stead"]["kind"] == "decided.ask-default"
    assert by_subject["q-stead"]["meanwhile"] == "Agents keep doing it the usual way."
    # `credentials` is code's key, never the overseer's: refiled as stead.
    assert by_subject["q-bad-key"]["kind"] == "decided.ask-default"
    oo7 = by_subject["q-oo7-daemon-bus-binding"]
    assert [o["id"] for o in oo7["options"]] == ["opt-yes", "opt-yes-conditions", "opt-no"]
    assert oo7["options"][0]["recommended"] and oo7["options"][1]["note"] == "required"


# ------------------------------------------------------------------ 3. read-only


def test_attention_json_reads_only_and_never_ticks_the_miner_watchdog(home, tmp_path, monkeypatch, capsys):
    """No subprocess but the one bounded `systemctl --user is-active`, no
    ledger write, no model call, no watchdog tick. Mutations: a `git log`
    in `attention.read` -> red; `attention` dropped from cli's exclusion ->
    red."""
    monkeypatch.delenv("SELF_LEARN_MINER_AUTOKICK", raising=False)
    kicks: list[str] = []
    monkeypatch.setattr(miner, "maybe_kick", lambda h, **k: kicks.append(str(h)) or "fresh")
    from self_learn import invocation

    def no_model(*_a, **_k):
        raise AssertionError("the reader made a model call")

    monkeypatch.setattr(invocation, "write_session", no_model)
    monkeypatch.setattr(invocation, "text_session", no_model)
    # The host unit is installed and its heartbeat is missing: the one
    # subprocess the reader may run is asked, and answers "inactive".
    unit_dir = tmp_path / "xdg-config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "self-learn-host.service").write_text("[Unit]\n", encoding="utf-8")
    _login_hold(home, _iso(-timedelta(hours=1)))
    calls: list[list[str]] = []
    real_run = subprocess.run
    real_popen = subprocess.Popen

    def guard_run(argv, *a, **k):
        calls.append(list(argv))
        if list(argv)[:3] == ["systemctl", "--user", "is-active"]:
            return subprocess.CompletedProcess(argv, 3, stdout="inactive\n", stderr="")
        return real_run(argv, *a, **k)

    def guard_popen(argv, *a, **k):
        calls.append(list(argv))
        return real_popen(argv, *a, **k)

    def ledger_state() -> dict[str, bytes]:
        return {
            str(p.relative_to(home)): p.read_bytes()
            for p in sorted(home.rglob("*")) if p.is_file() and ".git" not in p.parts
        }

    before = ledger_state()
    head = git(home, "rev-parse", "HEAD").stdout
    monkeypatch.setattr(subprocess, "run", guard_run)
    monkeypatch.setattr(subprocess, "Popen", guard_popen)
    try:
        # Positive control: the same guard catches a forced git call.
        from self_learn import gitops

        gitops._git(home, "log", "-1")  # noqa: SLF001
        assert any(argv[:1] == ["git"] for argv in calls)
        calls.clear()
        assert cli.main(["attention", "--json"]) == 0
        document = json.loads(capsys.readouterr().out)
    finally:
        monkeypatch.setattr(subprocess, "run", real_run)
        monkeypatch.setattr(subprocess, "Popen", real_popen)
    assert calls == [["systemctl", "--user", "is-active", "self-learn-host.service"]]
    assert {i["kind"] for i in document["items"]} >= {"broken.host", "hold.credentials"}
    assert document["state"] == "broken" and document["cache_dir"]
    assert kicks == [], "attention ticked the miner watchdog"
    assert ledger_state() == before and git(home, "rev-parse", "HEAD").stdout == head
    # Positive control for the ledger guard: a write IS seen.
    (home / "probe.txt").write_text("x", encoding="utf-8")
    assert ledger_state() != before
    (home / "probe.txt").unlink()
    # Positive control for the watchdog: `status --json` does tick it.
    assert cli.main(["status", "--json"]) in (0, 1)
    capsys.readouterr()
    assert kicks, "status --json must call maybe_kick (positive control)"


# ------------------------------------------------------------------ 4/5/7. seen and flags


def _manifest(home: Path, run_id: str, *, actor: str, effects: list[dict] | None = None, **extra) -> None:
    runs = home / "cases" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "actor": actor, "run_id": run_id, "ledger_effects": [], **extra}
    if actor == "steward":
        data.setdefault("completed_at", _iso(-timedelta(hours=2)))
        data.setdefault("started_at", _iso(-timedelta(hours=3)))
        data.setdefault("decided", ["lrn-00000001"])
    else:
        data.setdefault("status", "complete")
        data.setdefault("last_attempt_at", _iso(-timedelta(hours=2)))
        data.setdefault("week", _iso()[:10])
    if effects is not None:
        data["attention_effects"] = effects
    (runs / f"{run_id}.json").write_text(json.dumps(data), encoding="utf-8")


def test_seen_clears_only_new_never_needs_you(home):
    """Mutation: let seen subtract from `needs_you` -> red."""
    _login_hold(home, _iso(-timedelta(hours=1)))
    _manifest(home, "abcd1234", actor="overseer")
    first = attention.read(home)
    assert first["counts"]["needs_you"] == 1 and first["counts"]["new"] == 1
    marked, unknown = attention.mark_seen(home, [i["id"] for i in first["items"]])
    assert len(marked) == 2 and unknown == []
    after = attention.read(home)
    assert after["counts"]["needs_you"] == 1, "seen never takes a needs-you item out of the count"
    assert after["counts"]["new"] == 0 and after["state"] == "needs-you"
    assert all(i["seen"] for i in after["items"])


def test_flags_follow_answer_5(home):
    """A steward digest never lights the icon; an overseer digest does; an
    `attention_effects` hook row does whichever runner wrote it.
    Mutations: flag steward digests -> red; read effects only from overseer
    manifests -> red."""
    _manifest(home, "run-aaaaaaaaaaaa", actor="steward")
    only_steward = attention.read(home)
    assert [i["kind"] for i in only_steward["items"]] == ["decided.steward-run"]
    assert only_steward["state"] == "idle" and only_steward["counts"]["decided_unseen"] == 1

    _manifest(home, "run-bbbbbbbbbbbb", actor="steward", effects=[{
        "lesson": "lrn-0000aaaa", "verb": "route", "destination": "hook",
        "always_loaded": False, "hook_activated": True, "at": _iso(-timedelta(hours=1)),
    }])
    with_hook = attention.read(home)
    hook = [i for i in with_hook["items"] if i["kind"] == "decided.hook-activated"]
    assert len(hook) == 1 and hook[0]["source"]["by"] == "steward" and hook[0]["flagged"]
    assert hook[0]["undo"] == {"label": "Turn it off", "redo_label": "Turn it back on", "redo": False}
    assert with_hook["state"] == "new"

    attention.mark_seen(home, [hook[0]["id"]])
    assert attention.read(home)["state"] == "idle"
    _manifest(home, "abcd1234", actor="overseer")
    assert attention.read(home)["state"] == "new"


def test_a_missing_or_corrupt_seen_file_still_answers(home):
    _manifest(home, "abcd1234", actor="overseer")
    item_id = attention.read(home)["items"][0]["id"]
    attention.mark_seen(home, [item_id])
    assert attention.read(home)["state"] == "idle", "positive control: a valid seen.json hides new"
    attention.seen_path(home).write_text("{not json", encoding="utf-8")
    document = attention.read(home)
    assert document["error"] is None and document["state"] == "new"
    attention.seen_path(home).unlink()
    assert attention.read(home)["state"] == "new"


# ------------------------------------------------------------------ 6. feedback


def test_feedback_on_a_code_kind_changes_its_class_and_on_an_ask_only_records(home, monkeypatch, capsys):
    """Mutations: apply the override to ask kinds -> red; allow agent-shell
    feedback -> red."""
    _login_hold(home, _iso(-timedelta(hours=1)))
    monkeypatch.setattr(attention, "_load_questions", lambda _home: [_OO7])
    hold = _by_kind(home, "hold.credentials")[0]
    ask = _by_kind(home, "ask.system-change")[0]
    assert hold["class"] == "needs-you"

    # An agent's shell is refused and writes nothing.
    head = git(home, "rev-parse", "HEAD").stdout
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["attention", "feedback", hold["id"], "--wanted", "decided"]) == 64
    assert "person's own click" in capsys.readouterr().err
    assert git(home, "rev-parse", "HEAD").stdout == head
    assert not (home / "attention" / "feedback.jsonl").exists()
    monkeypatch.delenv("CLAUDECODE")

    assert cli.main(["attention", "feedback", hold["id"], "--wanted", "decided"]) == 0
    rows = [json.loads(l) for l in (home / "attention" / "feedback.jsonl").read_text().splitlines()]
    assert rows[-1]["kind"] == "hold.credentials" and rows[-1]["by"] == "human"
    assert rows[-1]["class_shown"] == "needs-you" and rows[-1]["class_wanted"] == "decided"
    value, _src = settings.resolve_setting(home, settings.by_name("attention.class.hold-credentials"))
    assert value == "decided"
    moved = _by_kind(home, "hold.credentials")[0]
    assert moved["class"] == "decided" and moved["id"] == hold["id"]
    assert git(home, "log", "-1", "--format=%B").stdout.strip().endswith("By: human")

    config_before = (home / "config.yaml").read_text(encoding="utf-8")
    assert cli.main(["attention", "feedback", ask["id"], "--wanted", "decided"]) == 0
    assert (home / "config.yaml").read_text(encoding="utf-8") == config_before
    rows = [json.loads(l) for l in (home / "attention" / "feedback.jsonl").read_text().splitlines()]
    assert rows[-1]["kind"] == "ask.system-change" and len(rows) == 2
    assert _by_kind(home, "ask.system-change")[0]["class"] == "needs-you"
    assert cli.main(["attention", "feedback", "att-000000000000", "--wanted", "silent"]) == 2


# ------------------------------------------------------------------ 8. ids


def test_item_ids_are_stable_and_episodes_are_new_items(home, monkeypatch):
    """Mutations: hash the title -> red; drop `@<since>` -> red."""
    rows = [dict(_OO7)]
    monkeypatch.setattr(attention, "_load_questions", lambda _home: rows)
    first = _by_kind(home, "ask.system-change")[0]["id"]
    assert _by_kind(home, "ask.system-change")[0]["id"] == first
    rows[0] = {**_OO7, "text": "Reworded: bind oo7-daemon to the bus?"}
    reworded = _by_kind(home, "ask.system-change")[0]
    assert reworded["id"] == first and reworded["title"].startswith("Reworded")
    assert first == attention.item_id("ask.system-change", "q-oo7-daemon-bus-binding")

    _login_hold(home, _iso(-timedelta(hours=5)))
    episode_one = _by_kind(home, "hold.credentials")[0]
    _journal(_steward_journal(home), [
        {"ts": _iso(-timedelta(hours=4)), "run_id": "run-y", "status": "applied", "decided": []},
    ])
    assert _by_kind(home, "hold.credentials") == [], "a later success ends the episode"
    _login_hold(home, _iso(-timedelta(hours=1)))
    episode_two = _by_kind(home, "hold.credentials")[0]
    assert episode_two["id"] != episode_one["id"]
    assert episode_two["subject"].startswith("credentials@")


def test_login_ok_ends_a_credentials_hold(home):
    _login_hold(home, _iso(-timedelta(hours=1)))
    assert _by_kind(home, "hold.credentials")
    target = attention.cache_dir(home) / "attention" / "login-ok.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"at": _iso()}), encoding="utf-8")
    assert _by_kind(home, "hold.credentials") == []


def test_approval_moves_an_ask_to_approved_then_done(home, monkeypatch):
    """§1.3: an approve choice makes the ask approved (its own item); an
    outcome makes it a flagged done item; words alone leave it open."""
    monkeypatch.setattr(attention, "_load_questions", lambda _home: [_OO7])
    ask = _by_kind(home, "ask.system-change")[0]
    (home / "attention").mkdir(exist_ok=True)
    statements_rows = [{"id": "stmt-0000aaaa", "at": _iso(), "verbatim": "yes but quietly",
                        "answers": {"kind": "question", "ref": _OO7["id"]},
                        "source": {"message_ref": "transcript:s#L1"}, "recorded_by": "human"}]
    monkeypatch.setattr(attention, "_statements", lambda _home: statements_rows)
    still = _by_kind(home, "ask.system-change")
    assert still and still[0]["state"] == "open" and still[0]["answer"]["how"] == "typed"
    choice = {"id": "chc-0000aaaa", "at": _iso(), "item": ask["id"], "subject": _OO7["id"],
              "how": "clicked", "option": "opt-yes", "label": "Yes, add the binding",
              "effect": "approve", "answers": {"kind": "question", "ref": _OO7["id"]}}
    (home / "attention" / "choices.jsonl").write_text(json.dumps(choice) + "\n", encoding="utf-8")
    approved = _by_kind(home, "approved.pending")
    assert _by_kind(home, "ask.system-change") == [] and len(approved) == 1
    assert approved[0]["class"] == "approved" and approved[0]["state"] == "approved"
    assert attention.read(home)["counts"]["approved"] == 1
    outcome = {"id": "out-0000aaaa", "at": _iso(timedelta(seconds=5)), "item": approved[0]["id"],
               "subject": _OO7["id"], "result": "done", "note": "added the drop-in", "by": "agent"}
    (home / "attention" / "outcomes.jsonl").write_text(json.dumps(outcome) + "\n", encoding="utf-8")
    done = _by_kind(home, "decided.approved-done")
    assert len(done) == 1 and done[0]["flagged"] and _by_kind(home, "approved.pending") == []


def test_a_reopened_ask_counts_answers_only_from_its_reopen(home, monkeypatch):
    """Integration (overseer-asks gate r3, cross-lane): after "Ask me anyway"
    the inbox's walk floors at `reopened_at`, as the overseer's walk does.
    A withdrawn approval comes back as a question, and an old click no
    longer closes a reopened ask without a plan.

    Mutations: drop `since=` at the `_approval_track` call -> the reopened
    plan reads approved.pending (red); drop the floor on `chose` -> the
    reopened no-plan ask stays closed (red)."""
    before = _iso(timedelta(hours=-2))
    reopened = _iso(timedelta(hours=-1))
    approve = {"id": "chc-0000bbbb", "at": before, "item": "att-000000000000",
               "subject": _OO7["id"], "how": "clicked", "option": "opt-yes",
               "label": "Yes, add the binding", "effect": "approve",
               "answers": {"kind": "question", "ref": _OO7["id"]}}
    no_plan = _ask(id="q-money-np", needs="user", because="money", default="Nothing is spent.",
                   asked_at="2026-09-28T04:15:00Z",
                   options=[{"id": "opt-no", "label": "No", "effect": "decline"}])
    decline = {"id": "chc-0000cccc", "at": before, "item": "att-000000000001",
               "subject": no_plan["id"], "how": "clicked", "option": "opt-no", "label": "No",
               "effect": "decline", "answers": {"kind": "question", "ref": no_plan["id"]}}
    (home / "attention").mkdir(exist_ok=True)
    (home / "attention" / "choices.jsonl").write_text(
        json.dumps(approve) + "\n" + json.dumps(decline) + "\n", encoding="utf-8")
    monkeypatch.setattr(attention, "_statements", lambda _home: [])

    # Positive control: never reopened, the old clicks stand.
    monkeypatch.setattr(attention, "_load_questions", lambda _home: [_OO7, no_plan])
    assert len(_by_kind(home, "approved.pending")) == 1
    assert _by_kind(home, "ask.system-change") == []
    assert _by_kind(home, "ask.money") == []

    # Reopened after the clicks: both are questions again, with no answer.
    rows = [{**_OO7, "reopened_at": reopened}, {**no_plan, "reopened_at": reopened}]
    monkeypatch.setattr(attention, "_load_questions", lambda _home: rows)
    assert _by_kind(home, "approved.pending") == []
    oo7 = _by_kind(home, "ask.system-change")
    assert len(oo7) == 1 and oo7[0]["state"] == "open" and oo7[0]["answer"] is None
    money = _by_kind(home, "ask.money")
    assert len(money) == 1 and money[0]["state"] == "open" and money[0]["answer"] is None

    # A click after the reopen counts again.
    later = {**approve, "id": "chc-0000dddd", "at": _iso()}
    with (home / "attention" / "choices.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(later) + "\n")
    assert len(_by_kind(home, "approved.pending")) == 1


# ------------------------------------------------------------------ 12. steward manifest


def _write_hook_route_stage(spec):
    outcome = _write_decision_stage(spec)
    match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
    assert match is not None
    stage = Path(match.group(1))
    sheet = next((stage / "sheets").glob("*.yaml"))
    from ruamel.yaml import YAML

    data = YAML(typ="safe").load(sheet.read_text(encoding="utf-8"))
    data["items"][0] = {"id": data["items"][0]["id"], "verb": "route", "dest": "hook"}
    _dump_yaml(sheet, data)
    case = next((stage / "cases").glob("*.yaml"))
    case_data = YAML(typ="safe").load(case.read_text(encoding="utf-8"))
    case_data["outcome"] = "route"
    case_data["decision"]["verb"] = "route"
    _dump_yaml(case, case_data)
    return outcome


def test_the_steward_manifest_gains_attention_effects_for_a_hook_route(tmp_path, monkeypatch):
    """Mutation: write no row for the steward -> red. `ledger_effects` is
    untouched (positive control: it is still the empty proof list)."""
    home = make_home(tmp_path)
    rid = _seed_fresh_proposals(home, 1)[0]
    _enable_steward(home)
    with (home / "config.yaml").open("a", encoding="utf-8") as fh:
        fh.write("overseer:\n  hook_activation: true\n")
    commit_all(home, "hooks on")
    preview = steward.batch.DryRunResult(items=[steward.batch.DryRunItem(
        n=1, id=rid, verb="route", state="would-apply", route_preview={})])
    monkeypatch.setattr(steward.batch, "dry_run", lambda *a, **k: preview)

    def applied(home_arg, items, **kwargs):
        return steward.batch.BatchResult(
            items=[steward.batch.ItemResult(n=1, id=rid, verb="route", rc=0, state="applied")],
            process_code=0, case=getattr(items, "case", None),
            sheet_sha=getattr(items, "sheet_sha", None), actor="steward",
        )

    monkeypatch.setattr(steward.batch, "run", applied)
    monkeypatch.setattr(steward.invocation, "write_session", _write_hook_route_stage)
    result = steward.run(home)
    assert result.run_id is not None
    manifest = execution_evidence.read_manifest(home, result.run_id, at="HEAD")
    assert manifest["ledger_effects"] == []
    rows = manifest["attention_effects"]
    assert [(r["lesson"], r["verb"], r["destination"], r["hook_activated"]) for r in rows] == [
        (rid, "route", "hook", True)]
    hook_items = [i for i in attention.read(home)["items"] if i["kind"] == "decided.hook-activated"]
    assert len(hook_items) == 1 and hook_items[0]["source"]["by"] == "steward"


# ------------------------------------------------------------------ 13. steward replay


def test_steward_maintenance_replay_accepts_a_workspace_ref(tmp_path, monkeypatch):
    """Mutation: revert the `steward.py` ref-prefix widening -> red."""
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    item = attention.item_id("ask.sudo", "q-workspace-steward")
    (t,) = workspace.append(home, item, [
        {"role": "user", "origin": "typed", "kind": "question", "text": "Never restart my bar without asking."},
    ], header={"item_kind": "ask.sudo", "subject": "q-workspace-steward", "title": "t"})
    ref = f"workspace:{item}#T{t}"

    def write_stage(spec):
        outcome = _write_decision_stage(spec)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        assert match
        _dump_yaml(Path(match[1]) / "statements.yaml", {"items": [
            {"verbatim": "Never restart my bar without asking.", "source": {"message_ref": ref}},
        ]})
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", write_stage)
    steward.run(home)
    rows = statements.list_statements(home)
    assert [(r["source"]["message_ref"], r["recorded_by"]) for r in rows] == [(ref, "steward")]


# ------------------------------------------------------------------ 15. C7 value sets


def test_agent_joins_every_value_set_and_case_observe_records_it(tmp_path, monkeypatch, capsys):
    """Mutation: drop `agent` from `cases.ACTORS` -> red."""
    assert "agent" in cases.ACTORS
    assert "agent" in statements.RECORDED_BY_VALUES
    assert "agent" in user_model.ACTORS
    assert "agent" in execution_evidence._ACTORS  # noqa: SLF001
    assert "agent" in skill_cli._CLI_BY_VALUES  # noqa: SLF001
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    stage = tmp_path / "case.yaml"
    _dump_yaml(stage, {
        "kind": "resolution", "trigger": "human", "outcome": "no-action", "records": ["lrn-00000001"],
        "scope": "user", "question": "q?", "evidence": [{"ref": "transcript:s#L1", "quote": "x"}],
        "decision": {"verb": "no-action", "because": "nothing to do", "confidence": "settled"},
        "dependencies": {"statements": [], "user_model": [], "conditions": [], "capabilities": []},
    })
    assert cli.main(["case", "record", str(stage), "--actor", "human"]) == 0
    case_id = re.search(r"case-[0-9a-f]{8}", capsys.readouterr().out).group(0)
    monkeypatch.setenv("CLAUDECODE", "1")
    code = cli.main([
        "case", "observe", case_id, "--by", "agent", "--kind", "statement",
        "--text", "the user said so in their session",
    ])
    out = capsys.readouterr()
    assert code == 0, out.err
    text = next(env.ledger.glob(f"cases/*/{case_id}.md")).read_text(encoding="utf-8")
    assert re.search(r"obs-[0-9a-f]{8} \S+ agent statement: the user said so", text)
    body = git(env.ledger, "log", "-1", "--format=%B").stdout.strip()
    assert body.rpartition("\n\n")[2].splitlines()[0] == "By: agent"


# ------------------------------------------------- fix round 1 (gate r1)


def test_an_answer_an_agent_relayed_reads_as_relayed():
    """Gate r1 MINOR 4. Mutation: `how` always "typed" -> red."""
    said = {"id": "stmt-0000abcd", "at": _iso(), "verbatim": "yes, bind it",
            "recorded_by": "agent", "source": {"message_ref": "transcript:s#L4"}}
    assert attention._answer_of(said, None)["how"] == "relayed"  # noqa: SLF001
    typed = {**said, "recorded_by": "human", "source": {"message_ref": "workspace:att-0#T1"}}
    assert attention._answer_of(typed, None)["how"] == "typed"  # noqa: SLF001


def test_a_plain_registration_names_no_actor(tmp_path, monkeypatch, capsys):
    """Gate r1 MINOR 5: a registration no grant-use row explains is the
    code's notice, never "the overseer decided it for you" (it may be the
    person's own `host add`). Mutation: `by="overseer"` again -> red."""
    from support import init_repo

    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    attention.read(env.ledger)  # the first read only learns what is there
    project = tmp_path / "plain-project"
    init_repo(project)
    (project / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(project, "seed")
    assert cli.main(["host", "add", str(project), "--mode", "plain"]) == 0, capsys.readouterr().err
    (item,) = [i for i in attention.read(env.ledger)["items"] if i["kind"] == "decided.registration"]
    assert item["source"]["by"] == "code"
    assert "overseer" not in item["title"] and "registered as a plain project host" in item["title"]
    found = attention.find(env.ledger, item["id"])
    assert found is not None and found["_decided"]["by"] == "code"
    assert "may have been you" in found["_decided"]["because"]


def test_the_steward_prompt_offers_the_workspace_ref():
    """Gate r1 NIT 1 (`steward_prompt.py:1289`). Mutation: drop the
    `workspace:` line from the grammar text -> red."""
    from self_learn import steward_prompt

    text = steward_prompt._render_output_contract()  # noqa: SLF001
    assert "`workspace:att-<12 hex>#T<n>`" in text
    assert "`conversation:obs-<8 hex>`" in text  # control: the grammar block rendered
