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

import inspect
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cli, telemetry, verbs
from self_learn.hosts import host_add, slug_for
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record
from support import (
    commit_all,
    init_repo,
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


def compile_record_entries(home: Path) -> list[dict]:
    """Every `targets[*]` entry dict (region, sha256, based_on_sha256,
    by, ...) across every `compiled/*.yaml` -- same ruamel round-trip
    discipline as `compile_record_by`. Gate r1 MAJOR-1/minor: the
    parity matrix never opened one of these before this fold."""
    y = YAML(typ="rt")
    out: list[dict] = []
    compiled_dir = home / "compiled"
    if not compiled_dir.is_dir():
        return out
    for path in sorted(compiled_dir.glob("*.yaml")):
        data = y.load(path.read_text(encoding="utf-8")) or {}
        for entry in (data.get("targets") or {}).values():
            out.append(dict(entry))
    return out


def compile_record_kinds(home: Path) -> list[str]:
    """Every `targets[*].region` value across every `compiled/*.yaml`
    (gate r1 MAJOR-1: the sibling of `compile_record_by` named there)."""
    return [
        e["region"] for e in compile_record_entries(home) if e.get("region") is not None
    ]


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

    def test_route_pins_the_pre_write_observed_hash_as_based_on_sha256(self, env):
        """MAJOR-1(e) (gate r1): `observed_hash = _observe_region_hash(spec)`
        is read BEFORE anything below it mutates the ledger (REC12/REC13
        -- the compile record's `based_on_sha256` must be the state THIS
        write is based on, never a later re-read). A fresh SKILL.md has
        no managed-region markers yet on the FIRST route (there is
        nothing to observe), so this needs a SECOND route to the same
        target: the first route's own output becomes the "before" state
        the second route's own pre-write observation must match exactly."""
        from self_learn import compiled as compiled_mod

        r1 = seed_pending(env, "lrn-0000a005")
        verbs.route(env.home, r1.id, dest="skill-md", no_push=True)

        before_text = env.skill_md.read_text(encoding="utf-8")
        expected_hash = compiled_mod.sha256_hex(
            compiled_mod.region_bytes(before_text, "managed")
        )

        r2 = seed_pending(env, "lrn-0000a006")
        verbs.route(env.home, r2.id, dest="skill-md", no_push=True)

        managed = [e for e in compile_record_entries(env.home) if e.get("region") == "managed"]
        assert any(e.get("based_on_sha256") == expected_hash for e in managed), (
            f"no managed compile-record entry has based_on_sha256="
            f"{expected_hash!r} (the pre-route-2 SKILL.md hash); found "
            f"{[e.get('based_on_sha256') for e in managed]}"
        )

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
        # MAJOR-1(a) (gate r1): the compile record must carry BOTH a
        # `reference` entry (the LEARNINGS.md region) and a `pointer`
        # entry (the skill's SKILL.md pointer surface) -- proof
        # `_resync_three_regions` actually ran, not just that the file
        # exists on disk.
        kinds = compile_record_kinds(env.home)
        assert "reference" in kinds
        assert "pointer" in kinds

    def test_route_direct_creates_default_learnings_file(self, env):
        record = make_behavior(record_id="lrn-0000b002")
        result = verbs.route_direct(env.home, record, dest="reference", no_push=True)
        target = env.skill_dir / "references" / "LEARNINGS.md"
        assert target.is_file()
        assert record.id in target.read_text(encoding="utf-8")
        assert result.commit_message == f"self-learn: route {record.id} → reference"
        landed = Record.from_path(env.resolved(record.id))
        assert landed.routing.get("reference_file") is None
        kinds = compile_record_kinds(env.home)
        assert "reference" in kinds
        assert "pointer" in kinds


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
        # MAJOR-1(b) (gate r1): the compile record must carry a `script`
        # entry for the applied hook -- proof `_resync_three_regions`
        # actually ran its hook branch, not just that the script file
        # landed on disk.
        assert "script" in compile_record_kinds(env.home)

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
        assert "script" in compile_record_kinds(env.home)

    def test_route_direct_refuses_hook_without_config_opt_in(self, env):
        record = make_behavior(record_id="lrn-0000c003")
        with pytest.raises(verbs.VerbError, match="one motion"):
            verbs.route_direct(env.home, record, dest="hook")

    def test_route_completes_a_hook_supersede_by_clearing_the_old_script_entry_and_removing_it_from_the_host(
        self, env
    ):
        """MAJOR-1(c) (gate r1): the D-3 retirement path for a
        superseded HOOK record -- `_complete_old_retirement` must clear
        the old record's `script` compile-record entry (delete, not a
        stale leftover) AND `_retirement_host_phase` must actually
        `git rm` the guard script from the old record's host repo. A
        supersede that landed and passed the whole suite while leaving a
        dead guard script live on disk would be exactly the kind of
        silent D-3 regression this move's own duplicate-block extraction
        is supposed to make impossible to miss."""
        from self_learn.hook_compiler import script_name
        from self_learn.ledger_ops import stamp_proposal
        from support import proposal_dict

        trigger = "About to edit `.storage/*.json` while HA is running."
        old = make_behavior(record_id="lrn-00018001", trigger=trigger)
        create_record(env.home, old)
        write_proposal(
            env.home,
            old.id,
            proposal_dict(destination="hook", alternates=["skill-md"], **hook_fields()),
        )
        stamp_proposal(env.home, old.id)
        commit_all(env.home, "seed old hook proposal")
        verbs.route(env.home, old.id, no_push=True)

        name = script_name(old.id, trigger)
        script = env.host / "plugins" / "s-plugin" / "hooks" / name
        assert script.is_file()
        assert "script" in compile_record_kinds(env.home)

        new = make_behavior(record_id="lrn-00018002")
        new.set_supersedes(old.id)
        create_record(env.home, new)
        commit_all(env.home, "seed successor")
        verbs.route(env.home, new.id, dest="skill-md", no_push=True)

        assert not script.is_file(), (
            "the old hook's guard script must be git-rm'd from the host "
            "repo by _retirement_host_phase"
        )
        assert "script" not in compile_record_kinds(env.home), (
            "the old hook's compile-record `script` entry must be "
            "cleared by _complete_old_retirement, not left stale"
        )


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
        # minor-3 (gate r1): "diff --git" alone is a substring EITHER
        # half of the diff supplies on its own -- severing the staged
        # ledger diff or the host diff independently left this
        # assertion green either way. Pin both halves by their own,
        # distinct path.
        # Full `diff --git a/X b/X` HEADER lines, not bare paths: the
        # staged half's own compile-record YAML legitimately mentions
        # the host-relative path too (as a `targets:` key), so a bare
        # substring check of the host path would pass even with the
        # host half severed entirely -- measured live while mutation-
        # verifying this exact assertion.
        ledger_rel = f"skills/s/resolved/{r2.id}.md"
        assert f"diff --git a/{ledger_rel} b/{ledger_rel}" in result2.diff, (
            "staged (ledger) half missing"
        )
        host_rel = env.skill_md.relative_to(env.host).as_posix()
        assert f"diff --git a/{host_rel} b/{host_rel}" in result2.diff, (
            "host half missing"
        )


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


# --------------------------------------------------------- ordering witness


class TestOldRecordPreflightOrdering:
    """MAJOR-2 (gate r1): the module docstring pins "(a) scan, THEN (b)
    sentinel self-hold" for the OLD (superseded) record's own preflight
    -- both adapters run it pre-sentinel, and `_execute_route` takes the
    three results as parameters specifically so a refusal there never
    happens after the sentinel is already held. Nothing asserted that
    order before this fold: hoisting `sentinel.hold()` above the old-
    record scan/status check left the whole suite green."""

    def test_route_refuses_a_bad_supersede_target_before_taking_the_sentinel(
        self, env, monkeypatch
    ):
        old = seed_pending(env, "lrn-00014001")
        verbs.reject(env.home, old.id, no_push=True)  # status -> "rejected"

        new = make_behavior(record_id="lrn-00014002")
        new.set_supersedes(old.id)
        create_record(env.home, new)
        commit_all(env.home, "seed successor")

        calls: list[object] = []
        monkeypatch.setattr(verbs.sentinel, "hold", lambda *a, **k: calls.append(1))

        with pytest.raises(verbs.VerbError, match="rejected"):
            verbs.route(env.home, new.id, dest="skill-md", no_push=True)
        assert calls == [], "sentinel.hold() must never run before the refusal"

    def test_route_direct_refuses_a_bad_supersede_target_before_taking_the_sentinel(
        self, env, monkeypatch
    ):
        old = seed_pending(env, "lrn-00014003")
        verbs.reject(env.home, old.id, no_push=True)  # status -> "rejected"

        new = make_behavior(record_id="lrn-00014004")
        new.set_supersedes(old.id)

        calls: list[object] = []
        monkeypatch.setattr(verbs.sentinel, "hold", lambda *a, **k: calls.append(1))

        with pytest.raises(verbs.VerbError, match="rejected"):
            verbs.route_direct(env.home, new, dest="skill-md")
        assert calls == [], "sentinel.hold() must never run before the refusal"


# ------------------------------------------------------------ project meta


class TestProjectMeta:
    """MAJOR-3 (gate r1): `ensure_project_meta` on the project-scope
    `route_direct` path (`_execute_route`'s "direct" first-write branch)
    had no witness anywhere in the suite -- replacing the whole call
    with `pass` left every test green, including a project-scope
    `teach --route`."""

    def test_route_direct_writes_and_commits_the_project_meta(self, env, tmp_path):
        proj = tmp_path / "proj-repo"
        init_repo(proj)
        (proj / "README.md").write_text("proj\n", encoding="utf-8")
        commit_all(proj, "proj seed")
        host_add(env.home, proj, "project")

        record = make_behavior(scope="project", record_id="lrn-00015001")
        result = verbs.route_direct(
            env.home, record, dest="claude-md", project_path=proj, no_push=True
        )
        assert result.commit_sha

        meta = env.home / "projects" / slug_for(proj) / "meta.yaml"
        assert meta.is_file()
        assert str(proj.resolve()) in meta.read_text(encoding="utf-8")
        assert f"projects/{slug_for(proj)}/meta.yaml" in verb_files(env.home)


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
        merge_path = proposals_dir / "merge-0000f001.yaml"
        merge_path.write_text(
            merge_proposal_text("merge-0000f001", [survivor.id, loser.id], survivor.id),
            encoding="utf-8",
        )
        commit_all(env.home, "seed cluster")
        # minor-4 (gate r1) positive control: the proposal must exist
        # BEFORE the route, or the absence assertion below proves
        # nothing about what the route itself did.
        assert merge_path.is_file()

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
        # minor-4 (gate r1): the ORIGINAL assertion here checked a
        # filename (`merge-0000f.yaml`) that never existed -- the seeded
        # file is `merge-0000f001.yaml` -- so it was true unconditionally
        # regardless of what the route did. Glob the real directory
        # instead, now that the positive control above proves there was
        # something to remove.
        assert not list(proposals_dir.glob("*.yaml"))
        # MAJOR-1(d) (gate r1): the survivor's own `sightings`/evidence
        # must show the merge actually happened -- proof `merged.write`
        # ran, not just that the loser got superseded (which the merge-
        # proposal cleanup alone would also produce).
        survivor_after = Record.from_path(env.resolved(survivor.id))
        assert survivor_after.sightings == 2
        assert any(
            e.get("merged_from") == loser.id for e in survivor_after.evidence
        )


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

    def test_route_direct_has_the_allow_empty_glob_parameter(self):
        # minor-2 (gate r1), structural half: the parameter itself must
        # exist on the signature the CLI layer's kwarg call targets.
        assert "allow_empty_glob" in inspect.signature(verbs.route_direct).parameters

    @pytest.mark.parametrize("flag_value", [True, False])
    def test_route_direct_threads_allow_empty_glob_into_resolve_target(
        self, env, monkeypatch, flag_value
    ):
        # minor-2 (gate r1), reddening half: the file's OWN docstring
        # concedes the prior test "pins the STRUCTURAL claim" only --
        # dropping `allow_empty_glob=allow_empty_glob` at either the
        # `teach.py` layer or the `_resolve_target` call inside
        # `route_direct` left every test in this class green. Spy on the
        # real `_resolve_target` (still calling it, so the route itself
        # still succeeds) and assert the kwarg actually arrives.
        #
        # nit-1 (gate delta r2): parametrized over True AND False -- the
        # original single-value (`True`-only) version stayed green even
        # after hardcoding `allow_empty_glob=True` at the
        # `_resolve_target` call site inside `route_direct` (a stale
        # spy result matching a stale hardcode). Asserting the SPY'S
        # OWN observed value equals whatever was PASSED IN, for both
        # values, is what actually pins the threading rather than one
        # coincidentally-matching literal.
        calls: list[dict] = []
        original = verbs._resolve_target

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return original(*args, **kwargs)

        monkeypatch.setattr(verbs, "_resolve_target", spy)
        record = make_behavior(record_id="lrn-00012002")
        verbs.route_direct(
            env.home, record, dest="skill-md", allow_empty_glob=flag_value, no_push=True
        )
        assert calls and calls[-1].get("allow_empty_glob") is flag_value

    @pytest.mark.parametrize("flag_value", [True, False])
    def test_teach_route_threads_allow_empty_glob_into_resolve_target(
        self, env, monkeypatch, flag_value
    ):
        # minor-2 (gate r1) / nit-1 (gate delta r2): the SAME reddening
        # check, one layer further out -- `teach --route
        # [--allow-empty-glob]` must reach the exact same
        # `_resolve_target` kwarg through `route_direct`, for BOTH the
        # flag given and the flag absent (defaulting False) -- not just
        # a hardcoded `True` a stale hardcode downstream could still
        # satisfy.
        calls: list[dict] = []
        original = verbs._resolve_target

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return original(*args, **kwargs)

        monkeypatch.setattr(verbs, "_resolve_target", spy)
        args = [
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
            "--route",
            "--dest",
            "skill-md",
        ]
        if flag_value:
            args = args + ["--allow-empty-glob"]
        rc = cli.main(args)
        assert rc == 0
        assert calls and calls[-1].get("allow_empty_glob") is flag_value


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
        # minor-1 (gate r1): `--follow-up-note` was accepted by the
        # parser and threaded by `_route_now` (teach.py:791-792) but no
        # test ever passed it -- deleting that one line left this whole
        # test green. Passing it here strengthens the equality below
        # into a genuine three-key check.
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
                "--follow-up-note",
                "why",
            ]
        )
        assert rc == 0
        resolved = sorted((env.home / "skills" / "s" / "resolved").glob("lrn-*.md"))
        (path,) = resolved
        record = Record.from_path(path)
        assert record.routing["follow_up"] == {
            "action": "upgrade-to-hook",
            "unblocks_on": "M9",
            "note": "why",
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
