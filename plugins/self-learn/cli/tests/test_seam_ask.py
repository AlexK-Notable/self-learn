"""The ask surface at the seam (attention round 2026-10-31c, design r2 §3.3,
§4.10, §4.11; §5.4 tests 1 and 2).

Person's-shell tests: the module fixture deletes every agent marker. No
session is started here: the charter is driven through its callback, and
the options through `options_kwargs`.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import pytest

from self_learn import ask, attention, attention_packet, invocation, provider, settings
from self_learn.invocation import contract
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import charter as charter_mod
from support import days_ago, make_home


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.delenv("SELF_LEARN_ASK_MODEL", raising=False)
    fake_home = tmp_path / "person-home"
    (fake_home / ".claude" / "rules").mkdir(parents=True)
    (fake_home / ".claude" / "CLAUDE.md").write_text("# always loaded\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))


def _call(cb, tool, tool_input):
    return asyncio.run(cb(tool, tool_input, None))


# ------------------------------------------------------------------- 1


def test_ask_is_a_surface_in_every_table_and_its_model_defaults_to_opus_at_tier_a(tmp_path):
    """Mutation: `models.ask` defaulting to `sonnet` -> red."""
    home = make_home(tmp_path)
    assert contract.SURFACES[-1] == "ask"
    for table in (contract.SELECTOR_FOR_SURFACE, contract.LOG_TEMPLATES, contract.TRANSPORT,
                  provider.MODEL_KEY_FOR_SURFACE):
        assert "ask" in table
    assert contract.SELECTOR_FOR_SURFACE["ask"] == "ASK"
    assert contract.LOG_TEMPLATES["ask"].os_error == "run: ask agent invocation failed ({exc})"
    assert provider.MODEL_KEY_FOR_SURFACE["ask"] == "ask"
    assert backend_mod._DEFAULT_MAX_TURNS["ASK"] == 40
    assert backend_mod._MAX_TURNS_SETTING_NAME["ASK"] == "sdk.max_turns.ask"
    assert "ask" in backend_mod._OWN_TOOLS_WITH_BUILTINS
    assert "ask" not in backend_mod._OWN_TOOLS_ONLY

    model = settings.by_name("models.ask")
    assert model.tier == "A" and model.env_var == "SELF_LEARN_ASK_MODEL"
    assert provider.model_for("ask", home=home) == "opus"
    timeout = settings.by_name("ask.timeout_secs")
    assert timeout.tier == "A" and timeout.default == 300.0
    assert settings.by_name("sdk.max_turns.ask").default == 40
    assert settings.by_name("provider.bedrock.models.ask").default is None


def test_only_a_session_that_asks_for_them_gets_resume_and_partial_messages(tmp_path):
    """The two `SessionSpec` fields add their option keys only when set, so
    every other surface's options are unchanged (positive control: a spec
    without them carries no `resume` and `include_partial_messages=False`)."""
    home = make_home(tmp_path)
    plain = invocation.SessionSpec(
        surface="worker", prompt="p", cwd=home, timeout=5,
        containment=invocation.containment_for("worker", home=home), log=lambda m: None,
    )
    kwargs = backend_mod.options_kwargs(plain)
    assert "resume" not in kwargs and kwargs["include_partial_messages"] is False
    streaming = dataclasses.replace(plain, resume_session_id="sess-1", on_event=lambda e: None)
    kwargs = backend_mod.options_kwargs(streaming)
    assert kwargs["resume"] == "sess-1" and kwargs["include_partial_messages"] is True
    # Both fields are last, after every older field.
    names = [f.name for f in dataclasses.fields(invocation.SessionSpec)]
    assert names[-2:] == ["resume_session_id", "on_event"]
    assert [f.name for f in dataclasses.fields(invocation.Containment)][-1] == "read_denied_names"


# ------------------------------------------------------------------- 2


def _ask_fixture(tmp_path):
    home = make_home(tmp_path)
    item = {"id": "att-0123456789ab", "kind": "hold.credentials", "options": []}
    folder = ask.workspace_dir(home, item["id"])
    folder.mkdir(parents=True)
    tools, toolset = ask.build_toolset(home, item, roots=(), denied=(), cwd=folder)
    containment = ask.ask_containment(home, toolset)
    return home, folder, toolset, containment


def test_the_ask_charter_reads_inside_its_roots_and_never_writes_or_reads_a_secret(tmp_path):
    """Mutations, each red: a write glob on the ask containment; Bash in
    `ask.allowed_tools`; empty `read_denied_names` in `ask.ask_containment`."""
    home, folder, toolset, containment = _ask_fixture(tmp_path)
    allowed = set((containment.allowed_tools or "").split(","))
    assert allowed == {"Read", "Glob", *toolset.qualified_names}
    assert containment.write_globs == () and containment.write_exact == ()
    assert containment.default_mode == "default" and containment.strict_mcp is True
    assert containment.read_denied_names == attention_packet.SECRET_DENY.names
    cache = attention.cache_dir(home)
    cb = charter_mod.build_can_use_tool(containment, cwd=folder)

    (home / "notes-plain.md").write_text("fine\n", encoding="utf-8")
    (home / "token.env").write_text("X=1\n", encoding="utf-8")
    (home / ".mcp.json").write_text("{}\n", encoding="utf-8")
    (home / "keys").mkdir()
    (home / "keys" / "id_rsa").write_text("key\n", encoding="utf-8")
    (home / "notes.md").symlink_to(home / "keys" / "id_rsa")
    (cache / "sessions").mkdir(parents=True, exist_ok=True)
    (cache / "sessions" / "x").write_text("other run\n", encoding="utf-8")
    (cache / "ui-token").write_text("t\n", encoding="utf-8")
    outside = tmp_path / "outside" / "x.md"
    outside.parent.mkdir()
    outside.write_text("no\n", encoding="utf-8")
    claude_md = tmp_path / "person-home" / ".claude" / "CLAUDE.md"

    # Positive controls first: the fence lets these through.
    for path in (home / "notes-plain.md", claude_md, folder / "packet.md"):
        assert _call(cb, "Read", {"file_path": str(path)}).behavior == "allow", path
    assert _call(cb, "Glob", {"pattern": "*.md", "path": str(home)}).behavior == "allow"

    denied = {
        "Write": {"file_path": str(home / "x.md"), "content": "x"},
        "Edit": {"file_path": str(home / "notes-plain.md"), "old_string": "a", "new_string": "b"},
        "Bash": {"command": "ls"},
        "Grep": {"pattern": "x", "path": str(home)},
    }
    for tool, tool_input in denied.items():
        assert _call(cb, tool, tool_input).behavior == "deny", tool
    for path in (cache / "sessions" / "x", cache / "ui-token", home / "token.env",
                 home / ".mcp.json", home / "notes.md", outside):
        result = _call(cb, "Read", {"file_path": str(path)})
        assert result.behavior == "deny", path


def test_every_other_surface_s_containment_is_unchanged(tmp_path):
    """Positive control for the new field: each older surface builds the
    same `Containment` it built before `read_denied_names` existed, and a
    steward Read of a `token.env` is still judged by its roots only."""
    home = make_home(tmp_path)
    stage = tmp_path / "stage"
    sessions = tmp_path / "sessions"
    expected = {
        "worker": contract.Containment(
            allowed_tools="Read", disallowed_tools="Bash", write_globs=(
                f"{home}/skills/**/proposals/**", f"{home}/projects/**/proposals/**",
                f"{home}/user/proposals/**"),
            write_exact=(), strict_mcp=True, default_mode="default"),
        "worker-repair": contract.Containment(
            allowed_tools="Read", disallowed_tools="Bash", write_globs=(),
            write_exact=("/x/a.yaml",), strict_mcp=True, default_mode="default"),
        "miner-reader": contract.Containment(
            allowed_tools=None, disallowed_tools="Bash", write_globs=(f"{stage}/**",),
            write_exact=(), strict_mcp=True, default_mode="default"),
        "analyst": contract.Containment(
            allowed_tools="Read", disallowed_tools=None, write_globs=(), write_exact=(),
            strict_mcp=False, default_mode=None),
        "steward": contract.Containment(
            allowed_tools="Read", disallowed_tools="Bash", write_globs=(f"{stage}/steward/**",),
            write_exact=(), strict_mcp=True, default_mode="default",
            read_denied=(str(sessions),)),
        "overseer": contract.Containment(
            allowed_tools="Read", disallowed_tools="Bash", write_globs=(f"{stage}/overseer/**",),
            write_exact=(), strict_mcp=True, default_mode="default",
            read_roots=(f"{stage}/overseer",)),
        "miner-session": contract.Containment(
            allowed_tools="Read", disallowed_tools="Bash", write_globs=(), write_exact=(),
            strict_mcp=True, default_mode="default"),
    }
    for surface, want in expected.items():
        got = invocation.containment_for(
            surface, allowed_tools="Read", disallowed_tools="Bash", home=home, stage_dir=stage,
            write_exact=("/x/a.yaml",), spool_dir=stage, sessions_dir=sessions,
            read_roots=("/ignored",), read_denied=("/ignored",), read_denied_names=("*",),
        )
        assert got == want, surface
        assert got.read_denied_names == ()
    steward = expected["steward"]
    (home / "token.env").write_text("X=1\n", encoding="utf-8")
    cb = charter_mod.build_can_use_tool(steward, cwd=home)
    assert _call(cb, "Read", {"file_path": str(home / "token.env")}).behavior == "allow"
    with pytest.raises(ValueError):
        invocation.containment_for("ask", allowed_tools="Read,Bash")


def test_sweep_orphan_judges_only_its_own_key(tmp_path, monkeypatch):
    """The ask turn's pre-start sweep: a dead sidecar under its own key is
    cleared, a sibling's (also dead) is left alone. Mutation: delegate to
    `children.sweep_orphans` -> the sibling goes -> red."""
    import json

    from self_learn.invocation_sdk import lifecycle

    monkeypatch.setenv("SELF_LEARN_HOME", str(make_home(tmp_path)))
    cache = lifecycle.worker.cache_dir()
    dead = {"pid": 2 ** 22 + 4321, "started_at": 0, "cli": "claude"}
    own = cache / "ask.sdk-child.0123456789ab.pid"
    sibling = cache / "ask.sdk-child.ba9876543210.pid"
    for path in (own, sibling):
        path.write_text(json.dumps(dead), encoding="utf-8")
    lines: list[str] = []
    lifecycle.sweep_orphan("ask", "0123456789ab", lines.append)
    assert not own.exists() and sibling.exists()
    assert lines and "no live process" in lines[0]


# ------------------------------------------------- the real seam's relay


FAKE_ASK_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"
_OWN_RECORD = "mcp__selflearn_ask__record"


@pytest.fixture()
def fake_ask_cli(tmp_path, monkeypatch):
    """Every session here runs against the fake CLI, never a real one
    (`tests/conftest.py` blocks `_find_cli`). Its argv is captured."""
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_ASK_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    argv_log = tmp_path / "fake-argv"
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(argv_log))
    return argv_log


def test_the_sdk_seam_streams_deltas_tool_uses_and_own_tool_results_in_order(
        tmp_path, monkeypatch, fake_ask_cli):
    """Gate r1 MAJOR 1: the relay a real ask turn takes, through
    `SdkBackend` and a fake CLI that prints real `stream_event` lines.
    Mutations, each red: drop the `StreamEvent` branch of the drain; drop
    `relay.tool_use`; relay every tool result, own or not; never send
    `resume`."""
    from self_learn.invocation_sdk.backend import SdkBackend

    home, folder, toolset, containment = _ask_fixture(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    events: list[dict] = []
    spec = invocation.SessionSpec(
        surface="ask", prompt="ask_stream", cwd=folder, timeout=30, containment=containment,
        log=lambda m: None, doctrine=ask.ASK_DOCTRINE, ledger_home=home, mcp_toolset=toolset,
        sidecar_key="0" * 12, skip_orphan_sweep=True, resume_session_id="sess-old",
        on_event=events.append,
    )
    outcome = SdkBackend().write_session(spec)
    assert outcome.ok, outcome.detail
    assert outcome.stdout == "Looking at the record. It says no."
    assert events == [
        {"ev": "delta", "text": "Looking at "},
        {"ev": "delta", "text": "the record."},
        {"ev": "tool", "name": _OWN_RECORD, "target": "lrn-0123abcd"},
        {"ev": "tool-result", "name": _OWN_RECORD, "is_error": False,
         "text": "lrn-0123abcd: pending"},
        {"ev": "tool", "name": "Read", "target": "/ledger/user/canon.md"},
    ]
    argv = fake_ask_cli.read_text(encoding="utf-8").split("\0")
    assert "--resume=sess-old" in argv and "--include-partial-messages" in argv


def test_an_ask_turn_through_the_sdk_seam_reaches_stdout_and_resumes_its_session(
        tmp_path, monkeypatch, fake_ask_cli):
    """The verb end to end on the real seam (`ask._backend` is `None`): its
    NDJSON carries the streamed text and the tool use, and the next
    question on the item continues the session the first one named."""
    import io
    import json

    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ask_stream")
    monkeypatch.setattr(attention, "_systemctl_active", lambda unit: True)
    journal = attention.cache_dir(home) / "steward" / "journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    at = days_ago(1)
    journal.write_text(json.dumps({"ts": at, "status": "held-environment",
                                   "cause": "Failed to authenticate"}) + "\n", encoding="utf-8")
    item_id = attention.item_id("hold.credentials", f"credentials@{at}")
    assert attention.find(home, item_id) is not None
    assert ask._backend is None

    out = io.StringIO()
    code, _ = ask.run_ask(home, item_id, "What is this?", stream=True, out=out,
                          err=io.StringIO())
    assert code == 0
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    kinds = [e["ev"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["ev"] == "delta") == "Looking at the record."
    assert {"ev": "tool", "name": _OWN_RECORD, "target": "lrn-0123abcd"} in events
    assert events[-1]["text"] == "Looking at the record. It says no."
    assert events[-1]["session"] == "fake-session-1"
    assert "--resume=fake-session-1" not in fake_ask_cli.read_text(encoding="utf-8").split("\0")

    code, _ = ask.run_ask(home, item_id, "And then?", stream=True, out=io.StringIO(),
                          err=io.StringIO())
    assert code == 0
    assert "--resume=fake-session-1" in fake_ask_cli.read_text(encoding="utf-8").split("\0")


def test_the_relay_starts_a_later_text_block_on_a_new_paragraph(tmp_path):
    """Gate r2 NIT 4: narration before a tool call and the text after it,
    or a later message's text, are relayed with a paragraph break between
    them, never glued ("…case.The case says…"). The first block gets
    none. Mutation: never prefix the break -> red."""
    from claude_agent_sdk.types import StreamEvent

    home, folder, toolset, containment = _ask_fixture(tmp_path)
    events: list[dict] = []
    spec = invocation.SessionSpec(
        surface="ask", prompt="", cwd=folder, timeout=30, containment=containment,
        log=lambda m: None, ledger_home=home, mcp_toolset=toolset, on_event=events.append)
    relay = backend_mod._EventRelay(spec)

    def _se(event):
        return StreamEvent(uuid="u", session_id="s", event=event)

    def _text_start():
        relay.stream(_se({"type": "content_block_start", "index": 0,
                          "content_block": {"type": "text", "text": ""}}))

    def _text(t):
        relay.stream(_se({"type": "content_block_delta", "index": 0,
                          "delta": {"type": "text_delta", "text": t}}))

    _text_start()
    _text("Let me check ")
    _text("the case.")
    relay.tool_use("tu-1", _OWN_RECORD, {"id": "lrn-0123abcd"})
    _text("The case says no.")          # after a tool call, no block start seen
    _text_start()
    _text("A later message.")           # a new text block
    texts = [e["text"] for e in events if e["ev"] == "delta"]
    assert texts == ["Let me check ", "the case.", "\n\nThe case says no.",
                     "\n\nA later message."]
