"""S-73 (FW-161 items 1 and 2, 2026-09-28): warning hooks end to end.

A warn hook routes, is placed and replays on every path a hook takes (the
analyst proposal, the one-motion input, the steward's and the overseer's
sheet lines), for both events; the doctor replays placed hooks; activation
registers the right event; the reconsider preview checks a re-decision's
hook before apply time.

Every scenario runs on a sandbox ledger and host (`support.make_env` under
pytest's tmpdir) with a scratch Claude runtime directory
(`SELF_LEARN_CLAUDE_DIR`); the real `~/.claude` is snapshotted before and
after by `_real_claude_dir_never_touched`. No real model call is made.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from self_learn import verbs
from self_learn.hook_compiler import script_name
from self_learn.records import Record
from self_learn.selfcheck import Verdict, _check_hooks
from test_hook_activation import _real_claude_dir_never_touched  # noqa: F401 -- the real-~/.claude control
from test_route_hook import RID, TRIGGER, Env, seed_hook

NAME = script_name(RID, TRIGGER)
WARN_MESSAGE = "HA rewrites .storage on shutdown.\nStop the container first, or your edit is lost."


def warn_hook(event: str = "PostToolUse", **overrides) -> dict:
    block = {
        "mode": "warn",
        "event": event,
        "tools": ["Edit", "Write"],
        "path_regex": r"\.storage/",
        "warn_message": WARN_MESSAGE,
    }
    block.update(overrides)
    return block


WARN_EXAMPLES = {
    "allow": [
        {"tool_name": "Edit", "tool_input": {"file_path": "/x/configuration.yaml"}},
        {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
    ],
    "warn": [
        {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/core.config"}},
        {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/auth"}},
    ],
}


def _examples(**overrides) -> dict:
    return {**json.loads(json.dumps(WARN_EXAMPLES)), **overrides}


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def claude_dir(tmp_path, monkeypatch):
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    return claude


def run_hook(script: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run([str(script)], input=json.dumps(payload),
                          capture_output=True, text=True)


def assert_placed_warn_hook(script: Path, meta: dict, event: str) -> None:
    """The placed bytes are the warning script for *event*, and routing.hook
    records what activation, the doctor and reachability read."""
    assert script.is_file()
    assert script.read_text(encoding="utf-8") == meta["script"]
    assert f"{event} warning hook" in meta["script"]
    assert (meta["mode"], meta["event"], meta["warn_message"]) == ("warn", event, WARN_MESSAGE)
    assert "deny_message" not in meta
    assert set(meta["examples"]) == {"allow", "warn"}
    hit = run_hook(script, WARN_EXAMPLES["warn"][0])
    assert hit.returncode == 0
    assert json.loads(hit.stdout) == {
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": WARN_MESSAGE}
    }
    miss = run_hook(script, WARN_EXAMPLES["allow"][0])
    assert (miss.returncode, miss.stdout) == (0, "")


# ------------------------------------------------ route paths (item 3)


@pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse"])
def test_a_proposal_carried_warn_hook_routes_is_placed_and_replays(env, event):
    seed_hook(env, hook=warn_hook(event), examples=_examples())
    result = verbs.route(env.home, RID)
    routed = Record.from_path(env.resolved())
    assert routed.status == "routed" and routed.routing["destination"] == "hook"
    script = env.host / "plugins" / "s-plugin" / "hooks" / NAME
    assert_placed_warn_hook(script, routed.routing["hook"], event)
    assert script.read_text(encoding="utf-8") == result.diff


def test_a_proposal_carried_warn_hook_whose_example_is_wrong_aborts_the_route(env):
    bad = _examples(warn=[WARN_EXAMPLES["warn"][0], WARN_EXAMPLES["allow"][0]])
    seed_hook(env, hook=warn_hook(), examples=bad)
    with pytest.raises(verbs.VerbError, match=r"warn\[1\] expected a warning"):
        verbs.route(env.home, RID)
    assert env.pending().is_file() and not env.resolved().exists()
    assert not (env.host / "plugins" / "s-plugin" / "hooks" / NAME).exists()


@pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse"])
def test_a_one_motion_warn_hook_routes_is_placed_and_replays(tmp_path, monkeypatch, event):
    from support import make_behavior
    from test_one_motion_config import Env as OneMotionEnv
    from test_one_motion_config import hook_input

    one = OneMotionEnv(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(one.home))
    one.enable("hook")
    record = make_behavior(scope="skill:s", trigger=TRIGGER)
    verbs.route_direct(one.home, record, dest="hook",
                       hook_input=hook_input(hook=warn_hook(event), examples=_examples()))
    routed = Record.from_path(one.bucket / "resolved" / f"{record.id}.md")
    script = one.host / "plugins" / "s-plugin" / "hooks" / script_name(record.id, TRIGGER)
    assert_placed_warn_hook(script, routed.routing["hook"], event)


def test_a_deny_route_keeps_its_routing_payload_shape(env):
    """Positive control for the payload helper: a deny block with no mode
    records exactly the keys it always did."""
    seed_hook(env)
    verbs.route(env.home, RID)
    meta = Record.from_path(env.resolved()).routing["hook"]
    assert list(meta) == ["tools", "path_regex", "deny_message", "script_path", "script",
                          "examples"]


# ---------------------------------------------- the doctor replays (item 3)


def _route_warn(env, event: str = "PostToolUse") -> Path:
    seed_hook(env, hook=warn_hook(event), examples=_examples())
    verbs.route(env.home, RID)
    return env.host / "plugins" / "s-plugin" / "hooks" / NAME


def _rewrite_meta(env, **changes) -> None:
    record = Record.from_path(env.resolved())
    routing = dict(record.routing)
    routing["hook"] = {**routing["hook"], **changes}
    record.set_routing(routing)
    record.write(env.resolved())


def test_the_doctor_passes_a_placed_warn_hook_and_fails_one_whose_replay_breaks(env, claude_dir):
    _route_warn(env)
    verdict, message = _check_hooks(env.home, claude_dir)
    assert verdict is Verdict.PASS, message
    assert "1 live hook script(s) intact" in message
    # the examples no longer agree with the placed bytes: a warn example
    # the script does not warn on
    _rewrite_meta(env, examples=_examples(warn=[WARN_EXAMPLES["warn"][0],
                                                WARN_EXAMPLES["allow"][1]]))
    verdict, message = _check_hooks(env.home, claude_dir)
    assert verdict is Verdict.FAIL
    assert "failed its replay" in message and "warn[1] expected a warning" in message


def test_the_doctor_catches_a_warn_hook_that_silently_stopped_firing(env, claude_dir, monkeypatch):
    """The fail-open case the doctor exists for: jq gone. The deny guard
    would fail loudly; the warn hook goes quiet, and only a replay sees it."""
    import shutil

    _route_warn(env)
    bin_dir = env.home.parent / "bin-without-jq"
    bin_dir.mkdir()
    for tool in ("bash", "cat", "grep", "git", "env"):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    assert _check_hooks(env.home, claude_dir)[0] is Verdict.PASS  # control
    monkeypatch.setenv("PATH", str(bin_dir))
    verdict, message = _check_hooks(env.home, claude_dir)
    assert verdict is Verdict.FAIL
    assert "warn[0] expected a warning but the hook printed nothing" in message


def test_the_doctor_replays_a_deny_guard_too(env, claude_dir):
    seed_hook(env)
    verbs.route(env.home, RID)
    assert _check_hooks(env.home, claude_dir)[0] is Verdict.PASS  # control
    meta = Record.from_path(env.resolved()).routing["hook"]
    examples = meta["examples"]
    _rewrite_meta(env, examples={"allow": examples["deny"], "deny": examples["allow"]})
    verdict, message = _check_hooks(env.home, claude_dir)
    assert verdict is Verdict.FAIL and "failed its replay" in message


# --------------------------------------------- the steward's sheet (item 3)


def _sheet_hook_input(event: str = "PostToolUse", examples: dict | None = None) -> dict:
    return {
        "rationale": "Warns on an Edit or Write under .storage/; the call still runs.",
        "hook": warn_hook(event),
        "examples": examples or _examples(),
    }


@pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse"])
def test_a_steward_warn_hook_is_placed_and_parked_for_activation(
    tmp_path, monkeypatch, claude_dir, event
):
    from self_learn import steward
    from support import make_behavior, make_env
    from test_steward import _enable_steward
    from test_steward_refusals import _case, _dispositions, _notifications, _seed
    from test_u3b_steward_authority import HOOK_TRIGGER, _stage_pairs

    sandbox = make_env(tmp_path)
    home = sandbox.ledger
    rid = _seed(home, "lrn-a7300001",
                record=make_behavior(record_id="lrn-a7300001", trigger=HOOK_TRIGGER))
    _enable_steward(home)
    _notifications(monkeypatch)

    def session(spec):
        return _stage_pairs(spec, {rid: (
            _case([rid], "route", "route"),
            [{"id": rid, "verb": "route", "dest": "hook", "hook": _sheet_hook_input(event)}],
        )})

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[rid]["state"] == "applied", rows[rid]
    record = Record.from_path(verbs.find_record_path(home, rid))
    meta = record.routing["hook"]
    script = sandbox.host / "plugins" / "s-plugin" / "hooks" / script_name(rid, HOOK_TRIGGER)
    assert_placed_warn_hook(script, meta, event)
    assert (claude_dir / "hooks" / script.name).is_symlink()  # placed
    assert not (claude_dir / "settings.json").exists()  # activation is off: never registered
