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


# ------------------------------------ snippet, activation, reachability (item 4)


def test_the_route_prints_the_warn_hooks_event_in_its_manual_steps(env):
    seed_hook(env, hook=warn_hook("PostToolUse"), examples=_examples())
    result = verbs.route(env.home, RID)
    notes = "\n".join(result.post_notes)
    assert "under PostToolUse" in notes
    assert f'"PostToolUse": [{{"matcher": "Edit|Write", "hooks": [{{"type": "command", ' \
        f'"command": "$HOME/.claude/hooks/{NAME}"}}]}}]' in notes
    assert '"PreToolUse"' not in notes
    assert '"PostToolUse"' in env.host_body()


def test_a_deny_route_still_prints_pretooluse(env):
    seed_hook(env)
    notes = "\n".join(verbs.route(env.home, RID).post_notes)
    assert "under PreToolUse" in notes and '"PreToolUse": [' in notes


def _settings(claude_dir: Path) -> dict:
    return json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse"])
def test_activation_registers_the_warn_hooks_event_and_deactivation_removes_it(
    env, claude_dir, monkeypatch, event
):
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
    _route_warn(env, event)
    result = verbs.hook_activate(env.home, RID, no_push=True)
    hooks = _settings(claude_dir)["hooks"]
    assert list(hooks) == [event]
    entry = hooks[event][0]
    assert entry["matcher"] == "Edit|Write"
    assert entry["hooks"][0]["command"].endswith(f"/hooks/{NAME}")
    assert (claude_dir / "hooks" / NAME).is_symlink()
    assert result.hook_replay == "ran"
    assert any(f"inserted the {event} entry" in note for note in result.post_notes)
    verbs.hook_deactivate(env.home, RID, no_push=True)
    assert "hooks" not in _settings(claude_dir)
    assert not (claude_dir / "hooks" / NAME).exists()


def test_activation_replays_the_warn_examples_against_the_placed_hook(env, claude_dir, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
    _route_warn(env)
    _rewrite_meta(env, examples=_examples(warn=[WARN_EXAMPLES["warn"][0],
                                                WARN_EXAMPLES["allow"][1]]))
    # refused by the replay step itself, before anything is registered
    # (the doctor step after it would also see this; the replay must not
    # leave it to the doctor)
    with pytest.raises(verbs.VerbError, match=r"(?s)guard replay failed against the placed "
                       r"symlink.*warn\[1\] expected a warning"):
        verbs.hook_activate(env.home, RID, no_push=True)
    assert not (claude_dir / "settings.json").exists()


def test_activation_refuses_the_same_script_under_another_event(env, claude_dir, monkeypatch):
    from self_learn.hook_compiler import command_for

    monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
    _route_warn(env, "PostToolUse")
    command = command_for(NAME, claude_dir)
    stale = {"hooks": {"PreToolUse": [{"matcher": "Edit|Write",
                                       "hooks": [{"type": "command", "command": command}]}]}}
    (claude_dir / "settings.json").write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(verbs.VerbError, match="already registered under PreToolUse, expected PostToolUse"):
        verbs.hook_activate(env.home, RID, no_push=True)
    assert _settings(claude_dir) == stale  # untouched
    with pytest.raises(verbs.VerbError, match="registered under PreToolUse, expected PostToolUse"):
        verbs.hook_deactivate(env.home, RID, no_push=True)
    assert _settings(claude_dir) == stale


def test_reachability_reads_the_warn_hooks_event(env, claude_dir, monkeypatch):
    from self_learn.reachability import reachability_rows

    monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
    _route_warn(env, "PostToolUse")
    verbs.hook_activate(env.home, RID, no_push=True)
    row = next(r for r in reachability_rows(env.home, claude_dir) if r.record_id == RID)
    assert (row.state, row.reason) == ("reachable", "registered"), row
    assert "under PostToolUse" in row.detail
    # the same registration moved to PreToolUse is the wrong event for it
    data = _settings(claude_dir)
    data["hooks"] = {"PreToolUse": data["hooks"]["PostToolUse"]}
    (claude_dir / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    row = next(r for r in reachability_rows(env.home, claude_dir) if r.record_id == RID)
    assert (row.state, row.reason) == ("unreachable", "wrong-event"), row
    assert "never PostToolUse" in row.detail


# ------------------------------- everyone who writes a hook is told (item 5)


def test_the_steward_brief_tells_warn_exists_from_the_constants(monkeypatch):
    from self_learn import hook_compiler, steward_prompt

    text = "\n".join(steward_prompt._hook_lines())
    assert "only DENIES" not in text
    assert "mode deny or warn" in text and "warn_message" in text
    assert "event PreToolUse or PostToolUse" in text
    assert "{allow: [...], warn: [...]} for warn" in text
    assert "Choose warn when the lesson is advice the agent may rightly override" in text
    monkeypatch.setattr(hook_compiler, "WARN_MESSAGE_MAX", 1234)
    assert "up to 1234 characters" in "\n".join(steward_prompt._hook_lines())


def test_the_brief_stays_byte_identical_across_packets():
    from self_learn import steward_prompt

    assert steward_prompt._hook_lines() == steward_prompt._hook_lines()


def test_the_method_and_the_doctrine_describe_warn():
    from self_learn import worker

    refs = worker.package_skill_refs()
    method = (refs / "steward-method.md").read_text(encoding="utf-8")
    assert "can only\ndeny" not in method and "is not a hook" not in method
    assert "`mode: warn`" in method and "choose `deny` when the call is always wrong" in method
    doctrine = (refs / "routing-doctrine.md").read_text(encoding="utf-8")
    assert "A hook may warn instead of deny (S-73)" in doctrine
    assert "mode: warn" in doctrine and "warn_message" in doctrine


def _formats_root(tmp_path: Path) -> Path:
    from self_learn.overseer import formats

    return formats.write(tmp_path / "ws", "B")


def test_the_overseer_formats_carry_warn_hook_examples_and_each_validates(tmp_path):
    from ruamel.yaml import YAML

    from self_learn import ledger_ops
    from self_learn.overseer import run as overseer_run
    from support import make_home
    from test_u3b_steward_authority import _replays

    home = make_home(tmp_path)
    root = _formats_root(tmp_path)
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "A hook can only deny" not in readme
    modes = {}
    for name in ("sheet-redecide-example.yaml", "sheet-hook-warn-post-example.yaml",
                 "sheet-hook-deny-example.yaml"):
        assert name in readme, name
        work = tmp_path / name
        work.write_text((root / name).read_text(encoding="utf-8"), encoding="utf-8")
        sheet = overseer_run._load_sheet_allow_empty(work, home)
        assert sheet is not None and len(sheet) == 1, name
        line = YAML(typ="safe").load((root / name).read_text(encoding="utf-8"))["items"][0]
        hook_input = line["hook"]
        ledger_ops._validate_hook_extension({"destination": "hook", **hook_input})
        assert _replays(hook_input) == [], name
        block = hook_input["hook"]
        modes[name] = (block.get("mode", "deny"), block.get("event", "PreToolUse"))
    assert modes == {
        "sheet-redecide-example.yaml": ("warn", "PreToolUse"),
        "sheet-hook-warn-post-example.yaml": ("warn", "PostToolUse"),
        "sheet-hook-deny-example.yaml": ("deny", "PreToolUse"),
    }
    # the re-decision is the pgrep/pkill -f self-match shape, as a warning
    redecide = YAML(typ="safe").load((root / "sheet-redecide-example.yaml").read_text(
        encoding="utf-8"))["items"][0]["hook"]
    assert "p(kill|grep)" in redecide["hook"]["path_regex"]
    assert set(redecide["examples"]) == {"allow", "warn"}
    # broken twin: a warn example the script does not warn on
    redecide["examples"]["warn"][0]["tool_input"]["command"] = "ls"
    assert _replays(redecide) != []


def test_the_formats_closed_sets_carry_the_hook_block_per_mode(tmp_path):
    from ruamel.yaml import YAML

    sets = YAML(typ="safe").load((_formats_root(tmp_path) / "closed-sets.yaml").read_text(
        encoding="utf-8"))
    hook = sets["hook"]
    assert hook["mode"] == ["deny", "warn"]
    assert hook["events_per_mode"] == {"deny": ["PreToolUse"], "warn": ["PreToolUse", "PostToolUse"]}
    assert hook["keys_per_mode"]["warn"]["required"] == ["tools", "path_regex", "warn_message"]
    assert hook["example_verdicts_per_mode"]["warn"] == ["allow", "warn"]


# ----------------------------------------- the reconsider preview (item 6)


def _stage_reconsider(tmp_path: Path, home: Path, rid: str, prior: str, items: list[dict],
                      records: list[str] | None = None) -> Path:
    from test_steward import _dump_yaml
    from test_steward_refusals import _case

    stage = tmp_path / "stage"
    case = _case(records or [rid], "route", "route")
    case.update(kind="reconsider", supersedes=prior)
    _dump_yaml(stage / "cases" / "redecide.yaml", case)
    _dump_yaml(stage / "sheets" / "redecide.yaml",
               {"version": 1, "case": "$CASE_ID", "items": items})
    return stage


def _routed_lesson(tmp_path: Path, rid: str):
    from support import make_env
    from test_u3b_steward_authority import _route_through_a_case

    sandbox = make_env(tmp_path)
    (tmp_path / "setup").mkdir()
    prior = _route_through_a_case(sandbox.ledger, tmp_path / "setup", rid)
    return sandbox, prior


def _redecide_line(rid: str, examples: dict | None = None) -> dict:
    return {"id": rid, "verb": "route", "dest": "hook",
            "hook": _sheet_hook_input("PreToolUse", examples)}


def test_the_repair_preview_reports_a_broken_warn_example_on_a_reconsider_line(tmp_path):
    from self_learn import steward

    rid = "lrn-a7300101"
    sandbox, prior = _routed_lesson(tmp_path, rid)
    home = sandbox.ledger
    good = _stage_reconsider(tmp_path / "good", home, rid, prior, [_redecide_line(rid)])
    assert steward._ledger_repair_message(home, good, {rid: "routed"}) is None  # control
    broken = _examples(warn=[WARN_EXAMPLES["warn"][0], WARN_EXAMPLES["allow"][1]])
    bad = _stage_reconsider(tmp_path / "bad", home, rid, prior, [_redecide_line(rid, broken)])
    message = steward._ledger_repair_message(home, bad, {rid: "routed"})
    assert message is not None
    assert f"(route {rid})" in message and "warn[1] expected a warning" in message
    # the preview wrote nothing: the lesson is still where it was
    record = Record.from_path(verbs.find_record_path(home, rid))
    assert record.routing["destination"] == "skill-md"


def test_the_repair_preview_still_skips_the_plain_status_refusal_for_a_covered_line(tmp_path):
    from self_learn import steward

    rid, other = "lrn-a7300102", "lrn-a7300103"
    sandbox, prior = _routed_lesson(tmp_path, rid)
    home = sandbox.ledger
    from test_steward_refusals import _seed

    _seed(home, other)
    verbs.reject(home, other, no_push=True)
    line = {"id": other, "verb": "defer", "until": "2099-01-01"}
    # control: uncovered, the same refused line is reported
    uncovered = _stage_reconsider(tmp_path / "u", home, rid, prior, [line], records=[rid])
    assert f"(defer {other})" in (steward._ledger_repair_message(
        home, uncovered, {other: "rejected"}) or "")
    covered = _stage_reconsider(tmp_path / "c", home, rid, prior, [line], records=[rid, other])
    assert steward._ledger_repair_message(home, covered, {other: "rejected"}) is None


def test_both_previews_widen_the_lines_the_staged_case_covers(tmp_path, monkeypatch):
    from self_learn import batch, steward

    rid = "lrn-a7300104"
    sandbox, prior = _routed_lesson(tmp_path, rid)
    stage = _stage_reconsider(tmp_path, sandbox.ledger, rid, prior, [_redecide_line(rid)])
    seen: list[frozenset] = []
    real = batch.dry_run

    def spy(*args, **kwargs):
        seen.append(frozenset(kwargs.get("reconsidered", ())))
        return real(*args, **kwargs)

    monkeypatch.setattr(batch, "dry_run", spy)
    steward._ledger_repair_message(sandbox.ledger, stage, {rid: "routed"})
    # `_forced_parking_reason`'s preview, then the repair preview's own
    assert seen == [frozenset({rid}), frozenset({rid})]


def test_the_preview_placeholder_cannot_come_from_text(tmp_path):
    """A string equal to the placeholder is checked like any case id: only
    the preview's own instance skips the case-file read."""
    rid = "lrn-a7300105"
    sandbox, _prior = _routed_lesson(tmp_path, rid)
    home = sandbox.ledger
    assert verbs._reconsider_case_check(
        home, verbs.PreviewReconsiderCase(verbs.PREVIEW_RECONSIDER_CASE_ID), rid) is None
    with pytest.raises(verbs.VerbError):
        verbs._reconsider_case_check(home, verbs.PREVIEW_RECONSIDER_CASE_ID, rid)
    with pytest.raises(verbs.VerbError, match="malformed case id"):
        verbs.reject(home, rid, no_push=True, reconsider_case=verbs.PREVIEW_RECONSIDER_CASE_ID)
    assert Record.from_path(verbs.find_record_path(home, rid)).status == "routed"


def test_a_dry_run_without_reconsidered_is_unchanged(tmp_path):
    """Positive control on the default: no covered ids, the routed lesson's
    route line stops at the status refusal as before."""
    from self_learn import batch
    from test_steward import _dump_yaml

    rid = "lrn-a7300106"
    sandbox, _prior = _routed_lesson(tmp_path, rid)
    path = tmp_path / "sheet.yaml"
    _dump_yaml(path, {"version": 1, "items": [_redecide_line(rid)]})
    sheet = batch.load_sheet(path, home=sandbox.ledger)
    plain = batch.dry_run(sandbox.ledger, sheet, actor="steward")
    assert plain.items[0].state == "would-refuse" and plain.items[0].kind == "status"
    widened = batch.dry_run(sandbox.ledger, sheet, actor="steward", reconsidered={rid})
    assert widened.items[0].state == "would-apply", widened.items[0].detail


# -------------------------- the lrn-19f82fc5 shape, end to end (the live case)


@pytest.mark.parametrize("example", ["EXAMPLE_HOOK_INPUT", "EXAMPLE_POST_HOOK_INPUT"])
def test_the_overseer_moves_a_routed_lesson_to_a_warning_hook(tmp_path, monkeypatch, claude_dir,
                                                               example):
    """A routed lesson, a reconsider case and a `dest: hook` warn line (the
    formats' own example, the lrn-19f82fc5 shape), applied by the overseer
    runner with fakes: the hook is placed and parked, not registered,
    while `overseer.hook_activation` is off."""
    from ruamel.yaml import YAML

    from self_learn import config
    from self_learn.overseer import formats
    from self_learn.overseer import run as overseer_run
    from test_failstate_overseer import _dump, _ok, _phase_a, _phase_b_common
    from test_overseer_run import _enabled
    from test_steward_refusals import _case
    from test_u3b_steward_authority import HOOK_TRIGGER, _record_case

    rid = "lrn-a7300107"
    sandbox, _prior = _routed_lesson(tmp_path, rid)
    home = sandbox.ledger
    _enabled(monkeypatch)
    assert config.hook_activation_enabled(home) is False
    parked = _case([rid], "parked", "route")
    parked.update(kind="parked", parked_for="overseer", parked_reason="hook")
    parked_id = _record_case(home, tmp_path / "setup", parked)
    load = YAML(typ="safe").load
    successor = load(formats.phase_b_examples()["case-redecide-example.yaml"])
    successor.update(records=[rid], scope="skill:s", supersedes=parked_id)
    successor["evidence"] = [{"ref": f"record:{rid}", "quote": "status: routed"}]
    sheet = load(formats.phase_b_examples()["sheet-redecide-example.yaml"])
    hook_input = json.loads(json.dumps(getattr(formats, example)))
    sheet["items"][0].update(id=rid, hook=hook_input)

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "case-a.yaml", successor)
            _dump(spec.cwd / "sheet-a.yaml", sheet)
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    overseer_run.run(home, no_push=True)

    record = Record.from_path(verbs.find_record_path(home, rid))
    assert record.status == "routed" and record.routing["destination"] == "hook"
    assert record.routing["by"] == "overseer"
    meta = record.routing["hook"]
    block = hook_input["hook"]
    assert (meta["mode"], meta["event"], meta["warn_message"]) == (
        "warn", block["event"], block["warn_message"])
    name = script_name(rid, HOOK_TRIGGER)
    script = sandbox.host / "plugins" / "s-plugin" / "hooks" / name
    assert script.read_text(encoding="utf-8") == meta["script"]
    assert f"{block['event']} warning hook" in meta["script"]
    assert (claude_dir / "hooks" / name).is_symlink()  # placed
    assert not (claude_dir / "settings.json").exists()  # parked: never registered
    entry = next(h for h in record.history if h.get("event") == "hook-activated")
    assert "switched off" in (entry.get("note") or "")
    hit = run_hook(script, hook_input["examples"]["warn"][0])
    assert json.loads(hit.stdout)["hookSpecificOutput"]["additionalContext"] == block["warn_message"]


def test_the_repair_preview_now_reports_a_refusal_only_the_widened_line_meets(tmp_path):
    """The widening's discriminating case: rejecting a REFERENCE-routed
    lesson under a reconsider case is refused (a reference route is
    corrected by hand) -- a repairable `bad-line`. Without the widening
    the preview stopped at the routed-status refusal, which it skips for a
    covered line, so the model was never told; apply time refused it with
    no repair turn left."""
    from self_learn import batch, steward
    from support import commit_all, make_behavior, make_env, proposal_dict
    from test_steward import _dump_yaml
    from test_steward_refusals import _case
    from test_u3b_steward_authority import HOOK_TRIGGER, _record_case

    rid = "lrn-a7300108"
    sandbox = make_env(tmp_path)
    home = sandbox.ledger
    (tmp_path / "setup").mkdir()
    from self_learn import ledger_ops

    ledger_ops.create_record(home, make_behavior(record_id=rid, trigger=HOOK_TRIGGER))
    ledger_ops.write_proposal(home, rid, proposal_dict())
    ledger_ops.stamp_proposal(home, rid)
    commit_all(home, f"seed {rid}")
    prior = _record_case(home, tmp_path / "setup", _case([rid], "route", "route"))
    first = tmp_path / "first.yaml"
    _dump_yaml(first, {"version": 1, "case": prior,
                       "items": [{"id": rid, "verb": "route", "dest": "reference:x.md"}]})
    assert batch.run(home, batch.load_sheet(first, home=home), no_push=True,
                     actor="steward").items[0].state == "applied"
    stage = _stage_reconsider(tmp_path / "s", home, rid, prior, [{"id": rid, "verb": "reject"}])
    message = steward._ledger_repair_message(home, stage, {rid: "routed"})
    assert message is not None and f"(reject {rid})" in message
    assert "corrected by hand" in message
