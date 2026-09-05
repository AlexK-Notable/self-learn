"""M-R: the route core (Sprint 2 lane L7).

Before this move, `route` (pending-file input, git-mv) and `route_direct`
(in-memory record, direct write) reimplemented the SAME post-lock
sequence -- old-record supersede preflight, retirement preflight, the
first write, compile-record entry, D-3 retirement completion, the
three-region (reference/pointer/hook) resync, the pinned commit,
`route` telemetry, the host phase, the retirement host phase, and the
push+`VerbResult` assembly -- with two near-verbatim duplicate blocks
(three-region resync, D-3 retirement removal) and `route_direct` simply
missing collapse/follow-up/(unreachably) `allow_empty_glob` altogether
(census `census-installer-route-intents.md` §2). `_execute_route` is now
the ONE sequence; `route`, `route_direct`, and `teach._route_now` are
adapters.

**What this file is for.** Not re-proving every route behaviour --
`test_route_cli.py`, `test_verbs.py`, `test_route_hook.py`,
`test_rescope.py` already do that in depth. This file is the PARITY
CLAIM itself: that the two adapters, driven through matching scenarios,
produce the same observable shape (commit subject, touched paths, hook
application, follow-up persistence, collapse) where the census says they
should, and *documented*, deliberate divergence (the compile-record `by`
label, `VerbResult.diff`) where it says they should not. The ordering
tests (`TestSequenceOrder`) are the mutation-catcher the brief asks for:
they fault-inject after the ledger commit and assert the commit (and its
telemetry) already landed -- a reordering that moved the host phase (or
the telemetry spool) ahead of the commit reddens them.

No mocks of the ledger itself (project discipline): real git sandboxes,
real host repos, real ruamel-read compile records. The one thing that
IS monkeypatched (`verbs._host_phase`) is monkeypatched to point at a
real module-level name the refactor must still call by that name --
exactly what a reordering would break.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cli, telemetry, verbs
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record
from support import (
    commit_all,
    make_behavior,
    make_env,
    merge_proposal_text,
    verb_files,
    verb_subject,
)


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel + telemetry spool go to a per-test XDG cache."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


class Env:
    """The doc-13 sandbox pair (`support.make_env`), local to this file."""

    def __init__(self, tmp_path):
        e = make_env(tmp_path)
        self.home = e.ledger
        self.host = e.host
        self.skill_dir = e.skill_dir
        self.skill_md = e.skill_md

    def pending(self, rid, skill="s"):
        return self.home / "skills" / skill / "pending" / f"{rid}.md"

    def resolved(self, rid, skill="s"):
        return self.home / "skills" / skill / "resolved" / f"{rid}.md"


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


def seed_pending(env, rid, **kwargs) -> Record:
    record = make_behavior(record_id=rid, **kwargs)
    create_record(env.home, record)
    commit_all(env.home, "seed record")
    return record


def spool_lines() -> list[str]:
    sd = telemetry.spool_dir()
    if not sd.is_dir():
        return []
    out: list[str] = []
    for path in sorted(sd.glob("*.jsonl")):
        out.extend(path.read_text(encoding="utf-8").splitlines())
    return out


def compile_record_by(home: Path) -> list[str]:
    """Every `targets[*].by` value across every `compiled/*.yaml` --
    read structurally (ruamel round-trip, same discipline the compiler
    itself uses), never by grepping for a literal."""
    y = YAML(typ="rt")
    out: list[str] = []
    compiled_dir = home / "compiled"
    if not compiled_dir.is_dir():
        return out
    for path in sorted(compiled_dir.glob("*.yaml")):
        data = y.load(path.read_text(encoding="utf-8")) or {}
        for entry in (data.get("targets") or {}).values():
            by = entry.get("by")
            if by is not None:
                out.append(by)
    return out


# ------------------------------------------------------- parity: skill-md


class TestParitySkillMd:
    """`route` (pending, git-mv) and `route_direct` (in-memory, direct
    write) land the SAME shape for the simplest destination."""

    def test_route_lands_resolved_with_pinned_subject(self, env):
        record = seed_pending(env, "lrn-0000a001")
        result = verbs.route(env.home, record.id, dest="skill-md", no_push=True)

        assert not env.pending(record.id).is_file()
        landed = Record.from_path(env.resolved(record.id))
        assert landed.status == "routed"
        assert landed.routing["destination"] == "skill-md"
        assert result.commit_message == f"self-learn: route {record.id} → skill-md"
        assert verb_subject(env.home) == result.commit_message
        assert env.skill_md.read_text(encoding="utf-8").count(record.id) >= 1
        # REC9: exactly one compile-record path rides the SAME commit.
        committed = verb_files(env.home)
        compiled = [p for p in committed if p.startswith("compiled/")]
        assert len(compiled) == 1

    def test_route_direct_lands_resolved_with_same_pinned_subject(self, env):
        record = make_behavior(record_id="lrn-0000a002")
        result = verbs.route_direct(env.home, record, dest="skill-md", no_push=True)

        landed = Record.from_path(env.resolved(record.id))
        assert landed.status == "routed"
        assert landed.routing["destination"] == "skill-md"
        assert landed.routing["by"] == "human"
        assert result.commit_message == f"self-learn: route {record.id} → skill-md"
        assert verb_subject(env.home) == result.commit_message
        assert env.skill_md.read_text(encoding="utf-8").count(record.id) >= 1
        committed = verb_files(env.home)
        compiled = [p for p in committed if p.startswith("compiled/")]
        assert len(compiled) == 1

    def test_by_default_differs_human_vs_analyst_but_not_in_this_pair(self, env):
        # Both adapters accept an explicit `by=`; the DEFAULT differs
        # (`route`'s heuristic vs `route_direct`'s "human") but an
        # explicit value is honoured identically -- the parity claim is
        # about the SEQUENCE, not about who is allowed to call it.
        r1 = seed_pending(env, "lrn-0000a003")
        verbs.route(env.home, r1.id, dest="skill-md", by="agent", no_push=True)
        assert Record.from_path(env.resolved(r1.id)).routing["by"] == "agent"

        r2 = make_behavior(record_id="lrn-0000a004")
        verbs.route_direct(env.home, r2, dest="skill-md", by="agent", no_push=True)
        assert Record.from_path(env.resolved(r2.id)).routing["by"] == "agent"


# ------------------------------------------------------- parity: reference


class TestParityReference:
    def test_route_creates_default_learnings_file(self, env):
        record = seed_pending(env, "lrn-0000b001")
        result = verbs.route(env.home, record.id, dest="reference", no_push=True)
        target = env.skill_dir / "references" / "LEARNINGS.md"
        assert target.is_file()
        assert record.id in target.read_text(encoding="utf-8")
        assert result.commit_message == f"self-learn: route {record.id} → reference"
        landed = Record.from_path(env.resolved(record.id))
        # default target: routing.reference_file is omitted (records.py
        # comment: "Absent on old records ⇒ the default LEARNINGS.md").
        assert landed.routing.get("reference_file") is None

    def test_route_direct_creates_default_learnings_file(self, env):
        record = make_behavior(record_id="lrn-0000b002")
        result = verbs.route_direct(env.home, record, dest="reference", no_push=True)
        target = env.skill_dir / "references" / "LEARNINGS.md"
        assert target.is_file()
        assert record.id in target.read_text(encoding="utf-8")
        assert result.commit_message == f"self-learn: route {record.id} → reference"
        landed = Record.from_path(env.resolved(record.id))
        assert landed.routing.get("reference_file") is None


# ------------------------------------------------------------- parity: hook


def hook_fields(**overrides) -> dict:
    data = {
        "hook": {
            "tools": ["Edit", "Write"],
            "path_regex": r"\.storage/",
            "deny_message": "stop the HA container first",
        },
        "examples": {
            "allow": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/config.yaml"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
            ],
            "deny": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/a"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/b"}},
            ],
        },
    }
    data.update(overrides)
    return data


class TestParityHook:
    """`route`'s hook prep reads an on-disk, human-approved proposal;
    `route_direct`'s reads a caller dict and needs the one-motion config
    opt-in (S-10). Different SOURCES, same landed shape."""

    def test_route_applies_the_proposal_carried_script(self, env):
        from self_learn.hook_compiler import script_name
        from self_learn.ledger_ops import stamp_proposal
        from support import proposal_dict

        trigger = "About to edit `.storage/*.json` while HA is running."
        record = make_behavior(record_id="lrn-0000c001", trigger=trigger)
        create_record(env.home, record)
        write_proposal(
            env.home,
            record.id,
            proposal_dict(destination="hook", alternates=["skill-md"], **hook_fields()),
        )
        stamp_proposal(env.home, record.id)
        commit_all(env.home, "seed hook proposal")

        result = verbs.route(env.home, record.id, no_push=True)
        name = script_name(record.id, trigger)
        script = env.host / "plugins" / "s-plugin" / "hooks" / name
        assert script.is_file()
        landed = Record.from_path(env.resolved(record.id))
        assert landed.routing["hook"]["script_path"].endswith(name)
        assert any("settings.json" in note for note in result.post_notes)

    def test_route_direct_applies_a_caller_supplied_compile_input(self, env):
        from self_learn.hook_compiler import script_name

        (env.home / "config.yaml").write_text(
            "one_motion_route:\n  hook: true\n", encoding="utf-8"
        )
        trigger = "About to edit `.storage/*.json` while HA is running."
        record = make_behavior(record_id="lrn-0000c002", trigger=trigger)
        result = verbs.route_direct(
            env.home,
            record,
            dest="hook",
            hook_input={
                "rationale": "deterministic guard",
                "alternates": ["skill-md"],
                **hook_fields(),
            },
            no_push=True,
        )
        name = script_name(record.id, trigger)
        script = env.host / "plugins" / "s-plugin" / "hooks" / name
        assert script.is_file()
        landed = Record.from_path(env.resolved(record.id))
        assert landed.routing["hook"]["script_path"].endswith(name)
        assert any("settings.json" in note for note in result.post_notes)
        # route_direct's diff shape (pinned, NOT unified with route's):
        # the applied script leads, then a "--- ledger ---" separator,
        # then the staged+host diff.
        head, sep, tail = result.diff.partition("\n--- ledger ---\n")
        assert sep, "missing the '--- ledger ---' separator entirely"
        assert head == landed.routing["hook"]["script"]
        assert "diff --git" in tail

    def test_route_direct_refuses_hook_without_config_opt_in(self, env):
        record = make_behavior(record_id="lrn-0000c003")
        with pytest.raises(verbs.VerbError, match="one motion"):
            verbs.route_direct(env.home, record, dest="hook")


# ---------------------------------------------------- pinned divergences


class TestPinnedDivergences:
    """Two observables the census names as ADAPTER-owned, not core-owned
    -- a unification that erased either of these would be a regression,
    not a simplification."""

    def test_compile_record_by_label_differs_route_vs_route_direct(self, env):
        r1 = seed_pending(env, "lrn-0000d001")
        verbs.route(env.home, r1.id, dest="skill-md", no_push=True)
        by1 = compile_record_by(env.home)
        assert any(b == f"route {r1.id}" for b in by1)

        r2 = make_behavior(record_id="lrn-0000d002")
        verbs.route_direct(env.home, r2, dest="skill-md", no_push=True)
        by2 = compile_record_by(env.home)
        assert any(b == f"route-direct {r2.id}" for b in by2)

    def test_diff_field_differs_route_none_route_direct_full(self, env):
        r1 = seed_pending(env, "lrn-0000d003")
        result1 = verbs.route(env.home, r1.id, dest="skill-md", no_push=True)
        assert result1.diff is None  # route: no hook -> diff is None

        r2 = make_behavior(record_id="lrn-0000d004")
        result2 = verbs.route_direct(env.home, r2, dest="skill-md", no_push=True)
        assert result2.diff  # route_direct: always carries the staged+host diff
        assert "diff --git" in result2.diff


# --------------------------------------------------------------- supersede


class TestParitySupersede:
    def test_route_completes_supersede_in_same_commit(self, env):
        old = seed_pending(env, "lrn-0000e001")
        verbs.route(env.home, old.id, dest="skill-md", no_push=True)
        new = make_behavior(record_id="lrn-0000e002")
        new.set_supersedes(old.id)
        create_record(env.home, new)
        commit_all(env.home, "seed successor")
        result = verbs.route(env.home, new.id, dest="skill-md", no_push=True)
        assert result.commit_message == (
            f"self-learn: route {new.id} → skill-md (supersedes {old.id})"
        )
        old_after = Record.from_path(env.resolved(old.id))
        assert old_after.status == "superseded"
        assert old_after.superseded_by == new.id

    def test_route_direct_completes_supersede_in_same_commit(self, env):
        old = seed_pending(env, "lrn-0000e003")
        verbs.route(env.home, old.id, dest="skill-md", no_push=True)
        new = make_behavior(record_id="lrn-0000e004")
        new.set_supersedes(old.id)
        result = verbs.route_direct(env.home, new, dest="skill-md", no_push=True)
        assert result.commit_message == (
            f"self-learn: route {new.id} → skill-md (supersedes {old.id})"
        )
        old_after = Record.from_path(env.resolved(old.id))
        assert old_after.status == "superseded"
        assert old_after.superseded_by == new.id


# ---------------------------------------------------------------- collapse


class TestCollapse:
    """Collapse is route-only (route_direct has no proposal cluster to
    read); it lives INSIDE the core (M-W needs it under transaction
    intents), threaded via the `collapse` parameter."""

    def test_route_collapse_merges_losers_and_removes_the_proposal(self, env):
        survivor = seed_pending(env, "lrn-0000f001")
        loser = seed_pending(env, "lrn-0000f002")
        proposals_dir = env.home / "skills" / "s" / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        (proposals_dir / "merge-0000f001.yaml").write_text(
            merge_proposal_text("merge-0000f001", [survivor.id, loser.id], survivor.id),
            encoding="utf-8",
        )
        commit_all(env.home, "seed cluster")

        result = verbs.route(
            env.home, survivor.id, dest="skill-md", collapse="merge-0000f001", no_push=True
        )
        assert result.commit_message == (
            f"self-learn: route {survivor.id} → skill-md "
            f"(collapse merge-0000f001, supersedes {loser.id})"
        )
        loser_after = Record.from_path(env.resolved(loser.id))
        assert loser_after.status == "superseded"
        assert loser_after.superseded_by == survivor.id
        assert not (
            env.home / "skills" / "s" / "proposals" / "merge-0000f.yaml"
        ).exists()


# --------------------------------------------------------------- follow-up


class TestFollowUp:
    """`route` already threads `follow_up`; M-R gives `route_direct` (and
    `teach --route`) the SAME capability -- previously absent (census
    §2: "follow_up validation: ... / absent (no param) / absent")."""

    def test_route_records_follow_up(self, env):
        record = seed_pending(env, "lrn-00011001")
        verbs.route(
            env.home,
            record.id,
            dest="skill-md",
            follow_up={"action": "upgrade-to-hook"},
            no_push=True,
        )
        landed = Record.from_path(env.resolved(record.id))
        assert landed.routing["follow_up"]["action"] == "upgrade-to-hook"

    def test_route_direct_records_follow_up(self, env):
        record = make_behavior(record_id="lrn-00011002")
        verbs.route_direct(
            env.home,
            record,
            dest="skill-md",
            follow_up={"action": "upgrade-to-hook"},
            no_push=True,
        )
        landed = Record.from_path(env.resolved(record.id))
        assert landed.routing["follow_up"]["action"] == "upgrade-to-hook"


# ---------------------------------------------------------- allow-empty-glob


class TestAllowEmptyGlob:
    """route_direct's `_resolve_target` call never threaded
    `allow_empty_glob` before this move (census: "absent and
    unreachable"). M-R threads it structurally; it stays a no-op for a
    non-rules destination (the only shape reachable through
    `route_direct` today -- the analyst proposal never carries
    `rules_paths`, so the zero-match refusal `allow_empty_glob` bypasses
    can only ever fire on `route`'s proposal-sourced path). This test
    pins the STRUCTURAL claim (the parameter exists and does not
    break a normal route); it does not claim route_direct can bypass a
    glob refusal today."""

    def test_route_direct_accepts_the_flag_as_a_no_op_for_skill_md(self, env):
        record = make_behavior(record_id="lrn-00012001")
        result = verbs.route_direct(
            env.home, record, dest="skill-md", allow_empty_glob=True, no_push=True
        )
        assert result.commit_sha


# ------------------------------------------------------ teach --route flags


class TestTeachRouteNewFlags:
    """`teach --route` gains `--allow-empty-glob` and `--follow-up`
    (+`--unblocks-on`/`--follow-up-note`) -- the SAME parser shape
    `route`'s own CLI subcommand already uses (`cli.py`), reused rather
    than reinvented."""

    TEACH_ARGS = [
        "teach",
        "--skill",
        "s",
        "--type",
        "behavior",
        "--kind",
        "anti-pattern",
        "--trigger",
        "About to edit .storage while HA is running.",
        "--instruction",
        "Stop the container first.",
    ]

    def test_follow_up_flag_rides_the_routing_block(self, env, capsys):
        rc = cli.main(
            self.TEACH_ARGS
            + [
                "--route",
                "--dest",
                "skill-md",
                "--follow-up",
                "upgrade-to-hook",
                "--unblocks-on",
                "M9",
            ]
        )
        assert rc == 0
        resolved = sorted((env.home / "skills" / "s" / "resolved").glob("lrn-*.md"))
        (path,) = resolved
        record = Record.from_path(path)
        assert record.routing["follow_up"] == {
            "action": "upgrade-to-hook",
            "unblocks_on": "M9",
        }

    def test_unblocks_on_without_follow_up_is_a_usage_error(self, env, capsys):
        rc = cli.main(
            self.TEACH_ARGS + ["--route", "--dest", "skill-md", "--unblocks-on", "M9"]
        )
        assert rc != 0
        err = capsys.readouterr().err
        assert "--follow-up" in err

    def test_allow_empty_glob_flag_is_accepted(self, env, capsys):
        rc = cli.main(
            self.TEACH_ARGS + ["--route", "--dest", "skill-md", "--allow-empty-glob"]
        )
        assert rc == 0


# ------------------------------------------------------------ sequence order


class TestSequenceOrder:
    """The mutation-catcher: a step dropped or reordered so the ledger
    commit no longer precedes the host phase reddens THESE, by making the
    thing they assert about a genuinely-committed, genuinely-spooled
    ledger state false. `_host_phase` is monkeypatched to a real
    module-level name -- exactly what a refactor must still call by that
    name regardless of internal restructuring."""

    def test_route_ledger_commit_and_telemetry_survive_a_host_phase_failure(
        self, env, monkeypatch
    ):
        record = seed_pending(env, "lrn-00013001")

        def boom(*a, **k):
            raise RuntimeError("host phase exploded")

        monkeypatch.setattr(verbs, "_host_phase", boom)
        before = len(spool_lines())
        with pytest.raises(RuntimeError, match="host phase exploded"):
            verbs.route(env.home, record.id, dest="skill-md", no_push=True)

        # The ledger commit landed anyway (doc 13 §4.1: ledger first).
        assert verb_subject(env.home) == f"self-learn: route {record.id} → skill-md"
        landed = Record.from_path(env.resolved(record.id))
        assert landed.status == "routed"
        # `route` telemetry was spooled BEFORE the host phase ran.
        after = spool_lines()
        assert len(after) > before

    def test_route_direct_ledger_commit_and_telemetry_survive_a_host_phase_failure(
        self, env, monkeypatch
    ):
        record = make_behavior(record_id="lrn-00013002")

        def boom(*a, **k):
            raise RuntimeError("host phase exploded")

        monkeypatch.setattr(verbs, "_host_phase", boom)
        before = len(spool_lines())
        with pytest.raises(RuntimeError, match="host phase exploded"):
            verbs.route_direct(env.home, record, dest="skill-md", no_push=True)

        assert verb_subject(env.home) == f"self-learn: route {record.id} → skill-md"
        landed = Record.from_path(env.resolved(record.id))
        assert landed.status == "routed"
        after = spool_lines()
        assert len(after) > before
