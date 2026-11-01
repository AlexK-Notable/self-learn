"""The ask surface at the seam (attention round 2026-10-31c, design r2 §3.3,
§4.10, §4.11; §5.4 tests 1 and 2).

Person's-shell tests: the module fixture deletes every agent marker. No
session is started here: the charter is driven through its callback, and
the options through `options_kwargs`.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from self_learn import ask, attention, attention_packet, invocation, provider, settings
from self_learn.invocation import contract
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import charter as charter_mod
from support import make_home


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
