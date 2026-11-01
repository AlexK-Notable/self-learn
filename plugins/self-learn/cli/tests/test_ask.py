"""The inbox's "ask about this" agent (attention round 2026-10-31c, design
r2 §3.3; contracts §4.6, §4.8; §5.4 tests 3-15).

Every turn here runs on `invocation.FakeBackend` (`ask._backend`); no test
crosses the real model boundary. Person's-shell tests: the module fixture
deletes every agent marker; the one agent-shell test sets one.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import signal
import subprocess
import time

import pytest

from self_learn import (
    ask, attention, cli as cli_mod, intents, miner, model_failures, settings, workspace,
)
from self_learn.invocation import failure_class
from self_learn.invocation.fake import (
    Exits, Fails, FakeBackend, Streams, Text, TimesOut, ToolCall,
)
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import lifecycle
from support import days_ago, git, make_home
from test_recover_or_refuse import _plant_stop

TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
BILLING_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX")


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    for var in (*BILLING_VARS, "SELF_LEARN_PROVIDER", "SELF_LEARN_ASK_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    person_home = tmp_path / "person-home"
    (person_home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(person_home))
    # The inbox reader asks systemd about the host once; not here.
    monkeypatch.setattr(attention, "_systemctl_active", lambda unit: True)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


HOLD_CAUSE = "Failed to authenticate: OAuth session expired and could not be refreshed"


def _hold(home) -> str:
    """A `hold.credentials` item: the steward held on a login failure."""
    at = days_ago(1)
    journal = attention.cache_dir(home) / "steward" / "journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({"ts": at, "status": "held-environment", "cause": HOLD_CAUSE})
                       + "\n", encoding="utf-8")
    item_id = attention.item_id("hold.credentials", f"credentials@{at}")
    assert attention.find(home, item_id) is not None
    return item_id


@pytest.fixture()
def item(home):
    return _hold(home)


def _turn(monkeypatch, home, item_id, steps, message="Why does this need me?", **kw):
    backend = FakeBackend(steps)
    monkeypatch.setattr(ask, "_backend", backend)
    out, err = io.StringIO(), io.StringIO()
    code, emitter = ask.run_ask(home, item_id, message, stream=True, out=out, err=err, **kw)
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    return code, events, backend, err.getvalue()


def _rows(home, item_id):
    return workspace.rows(home, item_id)


# ------------------------------------------------------------------- 3


def test_a_later_turn_resumes_the_session_and_a_lost_one_is_rebuilt_from_the_record(
        monkeypatch, home, item):
    """Mutation: never set `resume_session_id` -> red."""
    code, events, backend, _ = _turn(monkeypatch, home, item, [
        Streams(events=(), then=Text("first answer"), session_id="sess-A")])
    assert code == 0
    assert backend.specs[0].resume_session_id is None
    assert backend.prompts[0].startswith(f"{ask.SESSION_OPENING}{item}.")
    assert events[0]["ev"] == "start" and events[0]["resumed"] is False
    state = json.loads((ask.workspace_dir(home, item) / "state.json").read_text())
    assert state["session_id"] == "sess-A" and state["turns"] == 1

    code, events, backend, _ = _turn(monkeypatch, home, item, [Text("second answer")],
                                     message="And if I wait?")
    assert code == 0
    assert backend.specs[0].resume_session_id == "sess-A"
    assert backend.prompts[0] == "The person asks: And if I wait?"
    assert events[0]["resumed"] is True and events[0]["reinjected"] is False

    code, events, backend, _ = _turn(monkeypatch, home, item, [
        Exits(1, "No conversation found with session ID: sess-A"), Text("third answer")],
        message="Still there?")
    assert code == 0
    assert [s.resume_session_id for s in backend.specs] == ["sess-A", None]
    starts = [e for e in events if e["ev"] == "start"]
    assert (starts[-1]["resumed"], starts[-1]["reinjected"]) == (False, True)
    rebuilt = backend.prompts[1]
    assert rebuilt.startswith(f"{ask.SESSION_OPENING}{item}.")
    assert "Earlier in this conversation (from the record):" in rebuilt
    assert "first answer" in rebuilt and "And if I wait?" in rebuilt
    assert rebuilt.endswith("The person asks: Still there?")


# ------------------------------------------------------------------- 4


class _Lines(io.StringIO):
    """Records each write and whether a flush followed it."""

    def __init__(self):
        super().__init__()
        self.log: list[str] = []

    def write(self, s):
        if s:  # `print(..., end="")` also writes the empty end
            self.log.append("write")
        return super().write(s)

    def flush(self):
        self.log.append("flush")
        return super().flush()


def test_streaming_relays_start_deltas_and_done_in_order_each_line_flushed(monkeypatch, home, item):
    """Mutation: buffer the events to the end of the turn -> red (nothing
    reaches stdout while the session runs)."""
    out = _Lines()
    seen_while_running: list[int] = []

    class _Watching(FakeBackend):
        def write_session(self, spec):
            outcome = super().write_session(spec)
            seen_while_running.append(out.getvalue().count("\n"))
            return outcome

    first = "The steward is held until you log in. " * 8
    second = "Nothing is lost meanwhile."
    answer = first + second
    monkeypatch.setattr(ask, "_backend", _Watching([Streams(events=(
        {"ev": "delta", "text": first}, {"ev": "tool", "name": "Read", "target": str(home)},
        {"ev": "delta", "text": second}), then=Text(answer))]))
    code, _emitter = ask.run_ask(home, item, "What is this?", stream=True, out=out,
                                 err=io.StringIO())
    assert code == 0
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    kinds = [e["ev"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert set(kinds[1:-1]) == {"delta", "tool"}
    assert "".join(e["text"] for e in events if e["ev"] == "delta") == answer
    assert events[-1]["text"] == answer
    # Every line is written and flushed before the next is written.
    assert out.log == ["write", "flush"] * len(events)
    # And the deltas left while the session was still running.
    assert seen_while_running and seen_while_running[0] >= 3


# ------------------------------------------------------------------- 5


def test_a_broken_login_is_exit_3_with_the_login_fix_and_both_rows_sealed(monkeypatch, home, item):
    """Mutation: classify the login failure as `failed` -> red."""
    code, events, _backend, err = _turn(monkeypatch, home, item, [Fails(OSError(HOLD_CAUSE))])
    assert code == 3
    error = events[-1]
    assert error["ev"] == "error" and error["code"] == "login"
    assert error["fix"] == failure_class.LOGIN_FIX
    rows = _rows(home, item)
    assert [(r["role"], r["kind"]) for r in rows[1:]] == [("user", "question"), ("system", "note")]
    assert rows[-1]["text"].startswith("the agent could not answer: ")
    assert all(isinstance(r["t"], int) for r in rows)


# ------------------------------------------------------------------- 6


@pytest.mark.parametrize("setup", [
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "bedrock-provider", "policy-env-only",
])
def test_a_route_that_would_bill_money_is_refused_before_any_session(monkeypatch, home, item, setup):
    """Mutations: read `os.environ` only (the policy-env case goes green
    for money -> red); check after the spawn (the empty script raises ->
    red)."""
    if setup in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.setenv(setup, "sk-test-not-a-real-key")
    elif setup.startswith("CLAUDE_CODE_USE_"):
        monkeypatch.setenv(setup, "1")
    elif setup == "bedrock-provider":
        monkeypatch.setenv("SELF_LEARN_PROVIDER", "bedrock")
        monkeypatch.setenv("SELF_LEARN_BEDROCK_REGION", "us-east-1")
        monkeypatch.setenv("SELF_LEARN_ASK_MODEL", "us.anthropic.claude-opus-4-1-v1:0")
    else:
        monkeypatch.setattr(backend_mod, "provider_env",
                            lambda spec: {"ANTHROPIC_API_KEY": "sk-from-policy"})
    code, events, backend, err = _turn(monkeypatch, home, item, [])
    assert code == 4
    assert backend.specs == []
    assert events[-1]["code"] == "money" and "Nothing was sent" in events[-1]["message"]
    assert not workspace.transcript_path(home, item).exists()


def test_billing_route_names_each_route_and_passes_a_subscription():
    assert ask.billing_route({}) is None
    assert ask.billing_route({"ANTHROPIC_API_KEY": "  "}) is None
    assert ask.billing_route({"CLAUDE_CODE_USE_BEDROCK": "0"}) is None
    assert "ANTHROPIC_API_KEY" in ask.billing_route({"ANTHROPIC_API_KEY": "x"})
    assert "bedrock" in ask.billing_route({}, provider="bedrock")


# ------------------------------------------------------------------- 7


def test_sigterm_mid_turn_is_exit_7_and_clears_only_this_item_s_sidecar(monkeypatch, home, item):
    """Mutations, each red: sweep with `sweep_orphans("ask")` instead of
    this item's one key -> the sibling's sidecar is cleared; ignore the
    person's Stop marker (gate r2 MINOR 1) -> not "stopped by you"."""
    cache = lifecycle.worker.cache_dir()
    sibling = cache / "ask.sdk-child.ffffffffffff.pid"
    sibling.write_text(json.dumps({"pid": 2 ** 22 + 12345, "started_at": 0, "cli": "claude"}),
                       encoding="utf-8")
    ran: dict[str, bool] = {}

    class _Stopped:
        def write_session(self, spec):
            lifecycle.write_sidecar("ask", os.getpid(), "claude", session_key=spec.sidecar_key)
            try:
                ask.request_stop(home, item)  # the page's Stop, before its signal
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(5)
            finally:
                ran["ladder"] = True  # the seam's `finally`: the kill ladder, then the sidecar
                lifecycle.clear_sidecar("ask", session_key=spec.sidecar_key)
            raise AssertionError("SIGTERM did not interrupt the turn")

        text_session = write_session

    before = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(ask, "_backend", _Stopped())
    out = io.StringIO()
    code, _ = ask.run_ask(home, item, "Stop me", stream=True, out=out, err=io.StringIO())
    assert code == 7
    assert ran == {"ladder": True}
    assert not (cache / f"ask.sdk-child.{item[4:]}.pid").exists()
    assert sibling.exists()
    assert signal.getsignal(signal.SIGTERM) is before
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    assert events[-1]["code"] == "interrupted"
    assert _rows(home, item)[-1]["text"] == "stopped by you" == ask.STOPPED_NOTE
    assert not ask.stop_marker(home, item).exists()


# ------------------------------------------------------------------- 8


def test_a_draft_is_sealed_inside_its_tool_call_and_survives_a_timeout(monkeypatch, home, item):
    """Mutation: seal the draft after the turn ends -> the timed-out turn
    loses it -> red."""
    code, events, backend, _ = _turn(monkeypatch, home, item, [Streams(events=(
        ToolCall("draft_reply", {"text": "Not now; keep the jobs held."}),), then=TimesOut())])
    assert code == 5
    draft_event = next(e for e in events if e["ev"] == "draft")
    assert draft_event["draft_id"].startswith("drf-") and draft_event["option"] is None
    assert events[-1]["code"] == "timeout"
    drafts = [r for r in _rows(home, item) if r.get("kind") == "draft"]
    assert len(drafts) == 1
    assert drafts[0]["draft_id"] == draft_event["draft_id"]
    assert isinstance(drafts[0]["t"], int) and drafts[0]["role"] == "agent"
    assert workspace.resolve(home, f"workspace:{item}#T{drafts[0]['t']}")["kind"] == "draft"
    # An option that was not offered is refused, and nothing is sealed.
    reply = backend.tool_replies[0]
    assert reply.is_error is False
    _code, _events, backend, _ = _turn(monkeypatch, home, item, [Streams(events=(
        ToolCall("draft_reply", {"text": "Yes", "option": "opt-invented"}),), then=Text("ok"))])
    assert backend.tool_replies[0].is_error is True
    assert len([r for r in _rows(home, item) if r.get("kind") == "draft"]) == 1
    # ask-agent gate r1 NIT 6 (the last leg, added at integration once the
    # answers lane merged): the sealed draft is what `attention answer
    # --draft` accepts, recorded as the agent's draft the person sent.
    from self_learn import attention_answers

    sent = attention_answers.answer(home, item, draft_id=draft_event["draft_id"])
    assert sent.statement is None and sent.choice is not None
    (choice,) = [json.loads(line) for line in
                 (home / "attention" / "choices.jsonl").read_text("utf-8").splitlines()]
    assert (choice["how"], choice["draft_id"], choice["text"], choice["offered_by"]) == (
        "draft-accepted", draft_event["draft_id"], "Not now; keep the jobs held.", "agent")


# ------------------------------------------------------------------- 9


def test_a_secret_in_the_message_is_refused_before_anything_is_written_or_spawned(
        monkeypatch, home, item):
    code, events, backend, _ = _turn(monkeypatch, home, item, [], message=f"is {TOKEN} mine?")
    assert code == 64 and events[-1]["code"] == "secret"
    assert backend.specs == []
    assert not workspace.transcript_path(home, item).exists()


def test_a_secret_in_the_answer_is_redacted_in_the_row_and_in_every_delta(monkeypatch, home, item):
    """Mutation: relay the raw deltas -> red."""
    head = "Here is what I found in the file, " + " the key is " + TOKEN[:20]
    tail = TOKEN[20:] + " and that is all. " + "Then the rest of the answer. " * 14
    code, events, _backend, _ = _turn(monkeypatch, home, item, [Streams(events=(
        {"ev": "delta", "text": head}, {"ev": "delta", "text": tail}),
        then=Text(head + tail))])
    assert code == 0
    deltas = [e["text"] for e in events if e["ev"] == "delta"]
    assert deltas, "positive control: the answer was streamed"
    joined = "".join(deltas)
    assert "Then the rest of the answer. " * 14 in joined
    for text in deltas:
        assert "ghp_" not in text and TOKEN[20:30] not in text
    assert TOKEN not in events[-1]["text"]
    answer = [r for r in _rows(home, item) if r.get("kind") == "answer"][-1]
    assert answer["redacted"] and TOKEN not in json.dumps(answer)
    assert TOKEN not in workspace.transcript_path(home, item).read_text(encoding="utf-8")


# ------------------------------------------------------------------- 10


def test_the_nightly_miner_halts_an_ask_session(tmp_path, monkeypatch, home, item):
    """Mutation: remove the ask header from `SELF_PROMPT_HEADERS` -> red."""
    from test_miner_self_sessions import (
        SDK_ROW, assistant_row, ordinary_session_lines, slice_of, user_row, write_session,
    )

    _code, _events, backend, _ = _turn(monkeypatch, home, item, [Text("an answer")])
    prompt = backend.prompts[0]
    root = tmp_path / "transcripts"
    (root / "-ask").mkdir(parents=True)
    path = write_session(root, "-ask", "sess-ask", [user_row(prompt, **SDK_ROW),
                                                     assistant_row("ASK-TAIL")])
    assert miner.digest_transcript(slice_of(path)) == (None, True)
    ordinary = write_session(root, "-ask", "sess-person", ordinary_session_lines())
    assert miner.digest_transcript(slice_of(ordinary))[1] is False


# ------------------------------------------------------------------- 11


def test_check_login_records_the_login_and_the_hold_clears(monkeypatch, home, item):
    """Mutation: skip writing `login-ok.json` -> the hold stays -> red."""
    assert item in {i["id"] for i in attention.read(home)["items"]}  # positive control
    monkeypatch.setattr(ask, "_backend", FakeBackend([Text("OK")]))
    assert cli_mod.main(["attention", "check-login"]) == 0
    spec = ask._backend.specs[0]
    assert spec.surface == "ask" and spec.max_turns == 1 and spec.prompt == "Reply with OK."
    assert ask.login_ok_path(home).is_file()
    assert item not in {i["id"] for i in attention.read(home)["items"]}


def test_check_login_refuses_a_billing_route_and_reports_a_broken_login(monkeypatch, home, item):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr(ask, "_backend", FakeBackend([]))
    assert cli_mod.main(["attention", "check-login"]) == 4
    assert ask._backend.specs == []
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(ask, "_backend", FakeBackend([Fails(OSError(HOLD_CAUSE))]))
    assert cli_mod.main(["attention", "check-login"]) == 3
    assert not ask.login_ok_path(home).exists()


# ------------------------------------------------------------------- 12


def _tools(home, item_id, **kw):
    item = attention.public(attention.find(home, item_id))
    folder = ask.workspace_dir(home, item_id)
    folder.mkdir(parents=True, exist_ok=True)
    return ask.AskTools(home, item, roots=ask.read_roots(home), denied=ask.read_denied(home),
                        cwd=folder, **kw)


def test_probe_runs_only_its_allowlist_as_argv(monkeypatch, home, item):
    """Mutation: allow `systemctl restart` -> red."""
    ran: list[list[str]] = []
    monkeypatch.setattr(ask, "_run_probe", lambda argv: ran.append(argv) or "exit 0\nok\n")
    tools = _tools(home, item)
    allowed = {
        ("systemctl show", "self-learn-host.service"): [
            "systemctl", "--user", "show", "self-learn-host.service",
            "--property=ActiveState,SubState,LoadState,FragmentPath,DropInPaths,"
            "ActiveEnterTimestamp,NRestarts,Result"],
        ("systemctl is-active", "oo7-daemon.service"): [
            "systemctl", "--user", "is-active", "oo7-daemon.service"],
        ("systemctl status", "foo@bar.timer"): [
            "systemctl", "--user", "status", "foo@bar.timer", "--no-pager", "--lines=0"],
        ("journalctl", "self-learn-ui.service"): [
            "journalctl", "--user", "-u", "self-learn-ui.service", "-n", "200", "--no-pager",
            "-o", "short-iso"],
        ("pacman -Q", "python-pyqt6"): ["pacman", "-Q", "python-pyqt6"],
    }
    for (command, target), argv in allowed.items():
        assert tools.probe({"command": command, "target": target}).startswith("$ ")
        assert ran[-1] == argv
    count = len(ran)
    for command, target in (("systemctl restart", "self-learn-host.service"),
                            ("systemctl show", "--system"),
                            ("systemctl show", "a.service;rm -rf x"),
                            ("systemctl show", "a b.service"),
                            ("pacman -Q", "--sync"),
                            ("cat", "/etc/passwd")):
        with pytest.raises(ask._Refused):
            tools.probe({"command": command, "target": target})
    assert len(ran) == count


# ------------------------------------------------------------------- 13


def test_search_list_dir_and_settings_hooks_keep_to_the_fence(tmp_path, monkeypatch, home, item):
    """Mutation: `settings_hooks` returns the whole file -> red."""
    tools = _tools(home, item)
    cache = attention.cache_dir(home)
    (home / "notes").mkdir()
    (home / "notes" / "a.md").write_text("the needle is here\n", encoding="utf-8")
    (home / "notes" / "token.env").write_text("NEEDLE=1 needle\n", encoding="utf-8")
    (cache / "sessions" / "run-1").mkdir(parents=True)
    (cache / "sessions" / "run-1" / "s.md").write_text("needle in a kept session\n",
                                                       encoding="utf-8")
    (cache / "visible.md").write_text("needle in the cache\n", encoding="utf-8")

    found = tools.search({"pattern": "needle", "path": str(home / "notes")})
    assert "a.md:1:" in found  # positive control
    assert "token.env" not in found
    found = tools.search({"pattern": "needle", "path": str(cache)})
    assert "visible.md:1:" in found  # positive control
    assert "sessions" not in found
    with pytest.raises(ask._Refused):
        tools.search({"pattern": "needle", "path": str(cache / "sessions")})
    with pytest.raises(ask._Refused):
        tools.search({"pattern": "needle", "path": str(tmp_path / "person-home")})

    listing = json.loads(tools.list_dir({"path": str(home / "notes")}))
    by_name = {e["name"]: e for e in listing["entries"]}
    assert by_name["a.md"]["size"] > 0  # positive control
    assert "size" not in by_name["token.env"] and by_name["token.env"]["readable"] is False
    with pytest.raises(ask._Refused):
        tools.list_dir({"path": str(cache / "sessions")})

    settings_file = tmp_path / "person-home" / ".claude" / "settings.json"
    settings_file.write_text(json.dumps({
        "env": {"SOME_KEY": "value-that-must-not-leave"}, "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]},
    }), encoding="utf-8")
    shown = json.loads(tools.settings_hooks({}))
    assert shown == {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]}}


# ------------------------------------------------------------------- 14


def test_the_status_tool_never_runs_the_cli_and_matches_its_payload(monkeypatch, home, item, capsys):
    """Mutation: the tool shells out to `self-learn status` -> red.

    The payload's own home check asks git one question (`git rev-parse`,
    exactly as `status --fast` does); the spawn guard lets git through and
    refuses every other process, the CLI above all."""
    tools = _tools(home, item)
    expected = cli_mod.status_fast_data(home)
    real_popen = subprocess.Popen
    spawned: list[list[str]] = []

    def _guard(argv, *a, **k):
        words = [str(w) for w in (argv if isinstance(argv, (list, tuple)) else [argv])]
        spawned.append(words)
        if os.path.basename(words[0]) != "git":
            raise AssertionError(f"the status tool started {words}")
        return real_popen(argv, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(subprocess, "Popen", _guard)
        shown = json.loads(tools.status({}))
    assert spawned and all(os.path.basename(w[0]) == "git" for w in spawned)
    assert set(shown) == set(expected)
    assert shown["home_state"] == "ok"

    capsys.readouterr()
    assert cli_mod.main(["status", "--json", "--fast"]) == 0
    printed = capsys.readouterr().out
    assert printed == json.dumps(cli_mod.status_fast_data(home)) + "\n"


def test_status_fast_on_a_missing_home_prints_its_payload_unchanged(tmp_path, monkeypatch,
                                                                            capsys):
    bare = tmp_path / "not-a-ledger"
    monkeypatch.setenv("SELF_LEARN_HOME", str(bare))
    assert cli_mod.main(["status", "--json", "--fast"]) == 5
    printed = capsys.readouterr().out
    assert printed == json.dumps(cli_mod.status_fast_data(bare)) + "\n"
    assert json.loads(printed)["home_state"] == "missing"


def test_ask_never_ticks_the_miner_watchdog(tmp_path, monkeypatch, home, item, capsys):
    """Mutation: drop `ask` from the watchdog exclusion -> red."""
    kicks: list[str] = []
    monkeypatch.setattr(miner, "maybe_kick", lambda h, **k: kicks.append(str(h)) or "fresh")
    monkeypatch.setattr(ask, "_backend", FakeBackend([Text("an answer")]))
    message = tmp_path / "message.txt"
    message.write_text("What happens meanwhile?", encoding="utf-8")
    assert cli_mod.main(["ask", item, "--message-file", str(message), "--stream"]) == 0
    assert kicks == []
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["ev"] == "start" and lines[-1]["ev"] == "done"
    assert cli_mod.main(["status", "--json"]) in (0, 1)
    assert kicks, "positive control: status --json ticks the watchdog"


def test_an_agent_shell_may_not_ask(monkeypatch, home, item):
    monkeypatch.setenv("CLAUDECODE", "1")
    code, events, backend, err = _turn(monkeypatch, home, item, [Text("never")])
    assert code == 64 and backend.specs == []
    assert "the ask box is the person's" in err
    assert not workspace.transcript_path(home, item).exists()


# ------------------------------------------------------------------- 15


def test_a_turn_completes_while_the_ledger_is_stopped(monkeypatch, home, item):
    target = home / "user" / "stop-probe.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("seed\n", encoding="utf-8")
    git(home, "add", "--", str(target))
    git(home, "commit", "-q", "-m", "seed probe")
    _plant_stop(home, target)
    with pytest.raises(intents.LedgerStoppedError):
        with intents.ledger_write(home):
            pass
    head = git(home, "rev-parse", "HEAD").stdout
    code, events, _backend, _ = _turn(monkeypatch, home, item, [Streams(events=(
        ToolCall("draft_reply", {"text": "Wait until it is repaired."}),),
        then=Text("It is stopped; this answer waits on this machine."))])
    assert code == 0
    assert git(home, "rev-parse", "HEAD").stdout == head
    pending = [json.loads(line) for line in
               workspace.pending_path(home, item).read_text(encoding="utf-8").splitlines()]
    assert [(r["role"], r["kind"]) for r in pending] == [
        ("user", "question"), ("agent", "draft"), ("agent", "answer")]
    assert all(r["t"] is None for r in pending)
    assert events[-1]["ev"] == "done" and events[-1]["sealed"] == []


# ----------------------------------------------- the ledger tools, read


def test_the_ledger_tools_answer_from_the_record(tmp_path, monkeypatch):
    """Each read tool answers from a real ledger: a lesson, its case and the
    statement the case names. Mutation: `record` reads the wrong field
    (`record.status` for the text) -> red."""
    from test_attention_packet import LESSON, _case_with_links

    ledger, case_id, stmt = _case_with_links(tmp_path, monkeypatch)
    item = {"id": "att-0123456789ab", "kind": "ask.system-change", "options": []}
    folder = ask.workspace_dir(ledger, item["id"])
    folder.mkdir(parents=True)
    tools = ask.AskTools(ledger, item, roots=ask.read_roots(ledger),
                         denied=ask.read_denied(ledger), cwd=folder)

    lesson = json.loads(tools.record({"id": LESSON}))
    assert lesson["id"] == LESSON and "Restart oo7-daemon by hand." in lesson["text"]
    with pytest.raises(ask._Refused):
        tools.record({"id": "lrn-ffffffff"})
    case_text = tools.case({"id": case_id})
    assert "Should oo7-daemon be bound to the session bus?" in case_text
    assert f"Line of successors: {case_id}" in case_text
    rows = json.loads(tools.statements({"ids": [stmt]}))
    assert [r["id"] for r in rows] == [stmt] and rows[0]["verbatim"]
    assert json.loads(tools.statements({"query": "no such words anywhere"})) == []
    context = tools.words_in_context({"statement_id": stmt})
    assert context.startswith(f"{stmt} (")
    history = tools.ledger_history({"path_or_id": case_id})
    assert history != "(no commits)" and "self-learn" in history
    (ledger / "overseer").mkdir(exist_ok=True)
    (ledger / "overseer" / "latest-report.md").write_text("# Week\n\n## Hooks\nnone\n",
                                                          encoding="utf-8")
    assert tools.report({}).startswith("# Week")
    with pytest.raises(ask._Refused):
        tools.report({"date": "last week"})


def test_an_unexpected_failure_puts_the_stop_handler_back_and_frees_the_item(monkeypatch, home, item):
    """A seam that raises (a programming error) leaves no SIGTERM handler of
    the turn behind and no lock on the item: the next question runs.
    Mutation: drop the `finally` restore -> red."""
    before = signal.getsignal(signal.SIGTERM)

    class _Broken:
        def write_session(self, spec):
            raise RuntimeError("a bug in the seam")

        text_session = write_session

    monkeypatch.setattr(ask, "_backend", _Broken())
    with pytest.raises(RuntimeError):
        ask.run_ask(home, item, "First?", stream=True, out=io.StringIO(), err=io.StringIO())
    assert signal.getsignal(signal.SIGTERM) is before
    code, events, _backend, _ = _turn(monkeypatch, home, item, [Text("now it works")],
                                      message="Second?")
    assert code == 0 and events[-1]["ev"] == "done"


# ------------------------------------------------ gate r1, fix round 1


def _state(home, item_id):
    return json.loads((ask.workspace_dir(home, item_id) / "state.json").read_text())


def test_a_resumed_session_that_cannot_be_continued_is_never_resumed_again(
        monkeypatch, home, item):
    """Gate r1 MINOR 2. Mutations, each red: drop `failed to resume` from
    `_RESUME_GONE` (leg 1); keep the dead session's id (leg 3)."""
    _turn(monkeypatch, home, item, [Streams(events=(), then=Text("first"), session_id="sess-A")])

    # Leg 1: Claude Code's other words for a lost session start afresh.
    code, _events, backend, _ = _turn(monkeypatch, home, item, [
        Exits(1, "Failed to resume session"),
        Streams(events=(), then=Text("rebuilt"), session_id="sess-B")], message="Again?")
    assert code == 0
    assert [s.resume_session_id for s in backend.specs] == ["sess-A", None]
    assert "Earlier in this conversation (from the record):" in backend.prompts[1]
    assert _state(home, item)["session_id"] == "sess-B"

    # Leg 2 (positive control): a resumed turn that fails on the login
    # keeps its session; the session is fine, the login is not.
    code, _events, backend, _ = _turn(monkeypatch, home, item, [Fails(OSError(HOLD_CAUSE))],
                                      message="Login?")
    assert code == 3 and backend.specs[0].resume_session_id == "sess-B"
    assert _state(home, item)["session_id"] == "sess-B"

    # Leg 3: a resume that fails before any turn for a reason nothing
    # names is dropped, so the next question is not stuck on it.
    code, _events, backend, _ = _turn(monkeypatch, home, item, [
        Exits(1, "the session file could not be parsed")], message="Hello?")
    assert code == 1 and backend.specs[0].resume_session_id == "sess-B"
    assert _state(home, item)["session_id"] is None
    code, events, backend, _ = _turn(monkeypatch, home, item, [Text("fresh")], message="Now?")
    assert code == 0 and backend.specs[0].resume_session_id is None
    assert (events[0]["resumed"], events[0]["reinjected"]) == (False, True)
    assert backend.prompts[0].startswith(f"{ask.SESSION_OPENING}{item}.")


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class _Slow(FakeBackend):
    """Each session costs the time given for it on the test's clock."""

    def __init__(self, clock, steps, costs):
        super().__init__(steps)
        self.clock, self.costs, self.timeouts = clock, list(costs), []

    def write_session(self, spec):
        self.timeouts.append(spec.timeout)
        self.clock.t += self.costs.pop(0)
        return super().write_session(spec)


def test_every_attempt_of_a_turn_shares_one_deadline(monkeypatch, home, item):
    """Gate r1 MINOR 3 and NIT 7. Mutations, each red: give the retry the
    whole timeout (leg 1); retry whatever time is left (leg 2)."""
    clock = _Clock()
    monkeypatch.setattr(ask, "_clock", clock)
    monkeypatch.setattr(model_failures, "_sleep", lambda s: setattr(clock, "t", clock.t + s))

    # Leg 1: an overloaded first attempt took 200 s; the retry waits 30 s
    # and gets the 70 s that are left, and the page restarts its bubble.
    backend = _Slow(clock, [Exits(1, "API Error: 529 overloaded"), Text("second try")],
                    [200, 10])
    monkeypatch.setattr(ask, "_backend", backend)
    out = io.StringIO()
    code, _ = ask.run_ask(home, item, "Why?", stream=True, out=out, err=io.StringIO())
    assert code == 0
    assert backend.timeouts == [300.0, 70.0]
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [e["ev"] for e in events if e["ev"] in ("start", "done")] == ["start", "start", "done"]

    # Leg 2: with 50 s left there is no room for the wait and a real
    # attempt, so the turn reports the failure inside its own bound.
    backend = _Slow(clock, [Exits(1, "API Error: 529 overloaded"), Text("never")], [250])
    monkeypatch.setattr(ask, "_backend", backend)
    code, _ = ask.run_ask(home, item, "Why again?", stream=True, out=io.StringIO(),
                          err=io.StringIO())
    assert code == 1 and len(backend.timeouts) == 1


def test_a_sigterm_after_the_turn_s_deadline_is_not_recorded_as_the_person_s_stop(
        monkeypatch, home, item):
    """Gate r1 MINOR 3: past the deadline a SIGTERM is the UI's watchdog.
    The person's Stop (test 7) is the positive control. Mutation: seal
    "stopped by you" whatever the clock says -> red."""
    clock = _Clock()
    monkeypatch.setattr(ask, "_clock", clock)

    class _Overran:
        def write_session(self, spec):
            clock.t += spec.timeout + 31
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)
            raise AssertionError("SIGTERM did not interrupt the turn")

        text_session = write_session

    monkeypatch.setattr(ask, "_backend", _Overran())
    out = io.StringIO()
    code, _ = ask.run_ask(home, item, "Slow one", stream=True, out=out, err=io.StringIO())
    assert code == 7
    assert _rows(home, item)[-1]["text"] == ask.OVERRAN_NOTE
    assert "stopped by you" not in workspace.transcript_path(home, item).read_text("utf-8")
    assert json.loads(out.getvalue().splitlines()[-1])["message"] == ask.OVERRAN_NOTE


def _pem(edge: str) -> str:
    """A PEM armour line, built at run time so no key-shaped literal sits in
    the source (the repository's secret scanners would flag it)."""
    return "-----" + edge + " PRIVATE" + " KEY-----"


PEM_LINES = [
    "MIIEowIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0gun",
    "VTLw7onLRnrq0/IzW7yWR7QkrmBL7jTKEn5u+qKhbwKfBstIs+bMY2Zkp18gnTxK",
    "Xy7Kq0vD==",
]


def test_a_private_key_in_the_answer_is_withheld_whole(monkeypatch, home, item):
    """Gate r1 MINOR 4: the scan matches a PEM header only and a short
    last body line passes every rule, so the block goes as one, in every
    delta, in `done` and in the sealed row. Mutation: redact through
    `redact_text` alone -> the last line leaks -> red."""
    assert workspace.secret_rule(PEM_LINES[-1]) is None  # it passes the scan on its own
    header = _pem("BEGIN RSA")
    head = "I found a key in the config:\n" + header[:19]
    body = (header[19:] + "\n" + PEM_LINES[0] + "\n" + PEM_LINES[1][:30])
    rest = (PEM_LINES[1][30:] + "\n" + PEM_LINES[2] + "\n" + _pem("END RSA") + "\n"
            + "After the key, the rest of the answer. " * 10)
    answer = head + body + rest
    code, events, _backend, _ = _turn(monkeypatch, home, item, [Streams(events=(
        {"ev": "delta", "text": head}, {"ev": "delta", "text": body},
        {"ev": "delta", "text": rest}), then=Text(answer))])
    assert code == 0
    deltas = "".join(e["text"] for e in events if e["ev"] == "delta")
    done = events[-1]["text"]
    for shown in (deltas, done):
        assert "After the key, the rest of the answer. " * 10 in shown  # positive control
        assert "I found a key in the config:" in shown
        assert "[redacted: private-key]" in shown
        for line in PEM_LINES:
            assert line[:12] not in shown and line[-8:] not in shown
    answer_row = [r for r in _rows(home, item) if r.get("kind") == "answer"][-1]
    assert answer_row["redacted"] == "private-key"
    sealed = workspace.transcript_path(home, item).read_text(encoding="utf-8")
    assert "After the key" in sealed
    for line in PEM_LINES:
        assert line[-8:] not in sealed


def test_search_withholds_a_private_key_s_lines_whole(monkeypatch, home, item):
    """Gate r1 MINOR 4, the search tool. Mutation: show each line through
    the scan alone -> the short last line is shown -> red."""
    tools = _tools(home, item)
    (home / "notes").mkdir()
    (home / "notes" / "deploy.conf").write_text(
        "host = example\n" + _pem("BEGIN OPENSSH") + "\n" + "\n".join(PEM_LINES)
        + "\n" + _pem("END OPENSSH") + "\nport = Xy7Kq0 22\n", encoding="utf-8")
    found = tools.search({"pattern": "Xy7Kq0", "path": str(home / "notes")})
    assert "deploy.conf:7: port = Xy7Kq0 22" in found  # positive control, after END
    assert "deploy.conf:5: [redacted: private-key]" in found
    assert PEM_LINES[-1] not in found


# ------------------------------------------------ gate r2, fix round 2


class _Terminated:
    """A session the verb's process gets SIGTERM in, before the deadline,
    from whoever *stop* says."""

    def __init__(self, stop=None):
        self.stop = stop

    def write_session(self, spec):
        if self.stop is not None:
            self.stop()
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(5)
        raise AssertionError("SIGTERM did not interrupt the turn")

    text_session = write_session


def test_a_sigterm_the_person_did_not_send_is_never_recorded_as_their_stop(
        monkeypatch, home, item):
    """Gate r2 MINOR 1: the UI service's stop or restart, a logout or a
    shutdown signals the verb directly (systemd's control-group kill),
    before the deadline. Test 7 (the page's Stop, marker written) is the
    positive control. Mutations, each red: seal "stopped by you" for any
    SIGTERM before the deadline (leg 1); keep a marker left from before
    the turn (leg 2)."""
    # Leg 1: no marker -> a neutral note, nothing said about the person.
    monkeypatch.setattr(ask, "_backend", _Terminated())
    out = io.StringIO()
    code, _ = ask.run_ask(home, item, "Restart me", stream=True, out=out, err=io.StringIO())
    assert code == 7
    assert _rows(home, item)[-1]["text"] == ask.INTERRUPTED_NOTE
    last = json.loads(out.getvalue().splitlines()[-1])
    assert (last["code"], last["message"]) == ("interrupted", ask.INTERRUPTED_NOTE)
    assert "stopped by you" not in workspace.transcript_path(home, item).read_text("utf-8")

    # Leg 2: a marker the page wrote as an earlier turn was ending is not
    # this turn's Stop.
    ask.request_stop(home, item)
    assert ask.stop_marker(home, item).exists()
    code, _ = ask.run_ask(home, item, "Restart me again", stream=True, out=io.StringIO(),
                          err=io.StringIO())
    assert code == 7
    assert _rows(home, item)[-1]["text"] == ask.INTERRUPTED_NOTE
    assert "stopped by you" not in workspace.transcript_path(home, item).read_text("utf-8")
    assert not ask.stop_marker(home, item).exists()

    # Leg 3 (positive control in this test): the person's Stop during the
    # turn is theirs.
    monkeypatch.setattr(ask, "_backend", _Terminated(lambda: ask.request_stop(home, item)))
    code, _ = ask.run_ask(home, item, "Stop me", stream=True, out=io.StringIO(),
                          err=io.StringIO())
    assert code == 7 and _rows(home, item)[-1]["text"] == ask.STOPPED_NOTE


class _Turned(FakeBackend):
    """Every outcome carries *turns*, as the SDK seam's does when the
    session ran turns before it failed."""

    def __init__(self, steps, turns):
        super().__init__(steps)
        self.turns = turns

    def write_session(self, spec):
        outcome = super().write_session(spec)
        return backend_mod.SdkOutcome(
            ok=outcome.ok, rc=outcome.rc, stdout=outcome.stdout, detail=outcome.detail,
            failure=outcome.failure, exc=outcome.exc, turns=self.turns)


def test_a_resumed_session_that_timed_out_or_made_turns_is_kept(monkeypatch, home, item):
    """Gate r2 MINOR 2: only a resumed session that failed before any turn,
    for no reason the classifier knows, is dropped. A slow turn and one
    that worked before failing keep the agent's context. Mutations, each
    red: drop `_resume_dead`'s timeout clause (leg 1); drop its `turns`
    clause (leg 2)."""
    _turn(monkeypatch, home, item, [Streams(events=(), then=Text("first"), session_id="sess-A")])

    # Leg 1: a resumed turn runs out of time (the seam's timeout carries no
    # result message, so no turns) and the session is kept.
    code, _events, backend, _ = _turn(monkeypatch, home, item, [TimesOut()], message="Slow?")
    assert code == 5 and backend.specs[0].resume_session_id == "sess-A"
    assert failure_class.outcome_class(  # what keeps it is the timeout clause alone
        backend_mod.SdkOutcome(ok=False, rc=None, stdout="", detail="", failure="timeout")
    ) == "unclassified"
    assert _state(home, item)["session_id"] == "sess-A"

    # Leg 2: a resumed session that made turns, then failed for a reason
    # nothing names, is kept too.
    backend = _Turned([Exits(1, "the session file could not be parsed")], turns=3)
    monkeypatch.setattr(ask, "_backend", backend)
    code, _ = ask.run_ask(home, item, "Worked a bit?", stream=True, out=io.StringIO(),
                          err=io.StringIO())
    assert code == 1 and backend.specs[0].resume_session_id == "sess-A"
    assert _state(home, item)["session_id"] == "sess-A"

    # Positive control: the same failure with no turns made drops it.
    backend = _Turned([Exits(1, "the session file could not be parsed")], turns=None)
    monkeypatch.setattr(ask, "_backend", backend)
    code, _ = ask.run_ask(home, item, "And now?", stream=True, out=io.StringIO(),
                          err=io.StringIO())
    assert code == 1 and _state(home, item)["session_id"] is None


def test_a_key_header_named_in_a_sentence_keeps_the_rest_of_the_answer(monkeypatch, home, item):
    """Gate r2 NIT 3: with no END line, only a header that ends its line
    opens a withheld block. Mutation: let any header open a block to the
    end of the text -> the words after it are lost -> red."""
    header = _pem("BEGIN OPENSSH")
    prose = (f"An OpenSSH key file starts with `{header}` on its first line. "
             + "The rest of the answer stays. " * 12)
    code, events, _backend, _ = _turn(monkeypatch, home, item, [Streams(events=(
        {"ev": "delta", "text": prose[:60]}, {"ev": "delta", "text": prose[60:]}),
        then=Text(prose))])
    assert code == 0
    deltas = "".join(e["text"] for e in events if e["ev"] == "delta")
    for shown in (deltas, events[-1]["text"]):
        assert "[redacted: private-key]" in shown  # the header itself is still withheld
        assert header not in shown
        assert "The rest of the answer stays. " * 12 in shown
    # A header that ends its line, with no END yet, still opens a block,
    # also inside a string's escaped newline.
    for sep in ("\n", "\\n"):
        text = "cfg: " + header + sep + PEM_LINES[0] + sep + PEM_LINES[2]
        assert ask.redact(text) == "cfg: [redacted: private-key]"


def test_request_stop_ignores_an_id_that_is_not_an_item(tmp_path, monkeypatch):
    """ask-agent gate r3 NIT 2 (added at integration): `request_stop`
    builds a path from the id, so an id such as `../x` writes nothing.
    Mutation: drop the id check -> red (a marker lands beside the
    workspace folder, in the cache)."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    home = tmp_path / "ledger"
    home.mkdir()
    good = "att-0123456789ab"
    ask.request_stop(home, good)
    marker = ask.stop_marker(home, good)
    assert marker.exists()  # control: a real id is marked
    watched = marker.parent.parent.parent  # <cache>, above workspace/<id>/
    assert str(watched).startswith(str(tmp_path / "cache"))
    before = set(watched.rglob("*"))
    ask.request_stop(home, "../escaped")
    assert set(watched.rglob("*")) == before


def test_json_without_stream_prints_only_the_final_object(tmp_path, monkeypatch, capsys, home):
    """`ask --json` without `--stream` (S-124): the turn's own lines go to an
    in-memory sink, and stdout carries exactly one JSON object, the done or
    error event plus the exit code. 2026-11-01 (integration): the sink was
    `open(os.devnull, "w")`, which the raw-write gate refuses; it is now an
    `io.StringIO`. Control first: with `--stream` the turn's line shows."""
    message = tmp_path / "message.txt"
    message.write_text("why is this here?\n", encoding="utf-8")

    def fake_run_ask(home_, item_id, text, *, stream, out):
        print('{"ev": "delta", "text": "partial"}', file=out)
        done = {"ev": "done", "text": "because", "item": item_id}
        return 0, type("E", (), {"events": [{"ev": "delta"}, done]})()

    monkeypatch.setattr(ask, "run_ask", fake_run_ask)
    parser = ask.add_parser(argparse.ArgumentParser().add_subparsers())

    assert ask.dispatch(parser.parse_args(["att-00000001", "--message-file", str(message),
                                           "--json", "--stream"])) == 0
    assert '"partial"' in capsys.readouterr().out  # control: the sink is stdout here

    assert ask.dispatch(parser.parse_args(["att-00000001", "--message-file", str(message),
                                           "--json"])) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1, lines
    assert json.loads(lines[0]) == {"ev": "done", "text": "because", "item": "att-00000001",
                                    "exit": 0}
