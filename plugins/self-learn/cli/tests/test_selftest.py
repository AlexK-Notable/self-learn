"""T11: `self-learn --selftest` — loud PASS/FAIL installation checks.

Checks (08 §3 T11 row; marker check per 02 §4; drift per doc 13 §4.2):
(a) capture path via a scratch record, (b) compiler dry-run (in-memory,
no writes), (c) marker check — only targets that SHOULD have a section
(≥1 routed record) are flagged, (d) hosts-aware drift check, (e) sentinel
writability (real cache path resolution, XDG-redirected here). There is
no worker row (fold r1, 2026-09-04 dropped M-K's unconditional M2
placeholder — see :func:`self_learn.selfcheck.run_selftest`'s
docstring): a fully healthy sandbox now exits 0, not 9.

Targets resolve via hosts.yaml (doc 13): resolved records live in the
LEDGER home, the compiled SKILL.md lives in the registered HOST repo.

DoD: green on a healthy sandbox; loud + non-zero on a sabotaged marker;
clean refusal on a missing home.
"""

from __future__ import annotations

import pytest

from self_learn import cli, selfcheck, sentinel
from self_learn.compilers import BEGIN_MARKER, END_MARKER, compile_managed_file
from self_learn.hosts import Hosts, save_hosts
from self_learn.ledger import Bucket
from self_learn.verbs import DEFAULT_USER_CLAUDE_MD

from support import SKILL_MD_SEED, commit_all, init_repo, make_behavior, make_env, make_knowledge

SKILL_MD = SKILL_MD_SEED.format(name="s")


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel probes go to a per-test XDG cache, never the real ~/.cache."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


def routed_record(record_id: str = "lrn-0a1b2c3d", destination: str = "skill-md"):
    record = make_behavior(scope="skill:s", record_id=record_id)
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": destination, "by": "human"}
    )
    record.set_status("routed")
    return record


def seed_routed_skill_target(env):
    """A resolved routed record in the LEDGER + its compiled SKILL.md in
    the HOST (markers present). Returns the host-side SKILL.md path."""
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True)
    record = routed_record()
    record.write(resolved / f"{record.id}.md")
    compile_managed_file(env.skill_md, [record])  # bootstraps the marker pair
    return env.skill_md


def seed_reference_record(env, record_id="lrn-0a1b2c3d", reference_file=None, bucket="s"):
    """A resolved, LIVE `reference`-routed record in the skill `s` bucket
    (U-reach RR: `status: routed`, `superseded_by: null`,
    `routing.destination: reference`). Writes nothing on the HOST side —
    callers seed the target file / SKILL.md pointer (or don't, for the
    unreachable fixtures)."""
    resolved = env.ledger / "skills" / bucket / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record = make_behavior(scope=f"skill:{bucket}", record_id=record_id)
    routing = {
        "routed_at": "2026-07-13T18:02:00Z",
        "destination": "reference",
        "by": "human",
    }
    if reference_file is not None:
        routing["reference_file"] = reference_file
    record.set_routing(routing)
    record.set_status("routed")
    record.write(resolved / f"{record.id}.md")
    return record


# ----------------------------------------------------------------- healthy


def test_selftest_exits_9_on_healthy_sandbox_no_real_claude_dir(env, capsys):
    skill_md = seed_routed_skill_target(env)
    assert BEGIN_MARKER in skill_md.read_text(encoding="utf-8")

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    # this fixture's `env` has no real ~/.claude, so `surface` is
    # genuinely UNMEASURED (claude-dir-absent, not a free PASS) -- the
    # only reason this run is 9, not 0; fold r1, 2026-09-04 removed the
    # separate, unconditional worker placeholder row that used to make
    # EVERY home exit 9 regardless of this one real UNMEASURED check.
    assert rc == 9
    assert "FAIL" not in out
    for check in ("capture", "compiler", "markers", "drift", "sentinel"):
        assert f"PASS {check}" in out
    assert "worker" not in out
    assert "UNMEASURED surface" in out
    assert "8 passed, 1 unmeasured, 0 failed" in out


def test_selftest_green_on_empty_home(env, capsys):
    # No routed records: nothing should have a section yet. Every real
    # check trivially PASSes (nothing in any domain to fail or leave
    # unmeasured), and fold r1, 2026-09-04 dropped the worker placeholder
    # row that used to force exit 9 regardless -- a genuinely empty,
    # healthy home exits 0.
    rc = cli.main(["--selftest"])
    assert rc == 0
    assert "FAIL" not in capsys.readouterr().out


def test_selftest_leaves_no_scratch_litter(env, capsys):
    seed_routed_skill_target(env)
    assert cli.main(["--selftest"]) == 9
    leftovers = [
        p for p in env.ledger.rglob("*") if "selftest" in p.name.lower()
    ]
    assert leftovers == []


def test_selftest_compiler_dry_run_writes_nothing(env, capsys):
    skill_md = seed_routed_skill_target(env)
    before = skill_md.read_bytes()
    assert cli.main(["--selftest"]) == 9
    assert skill_md.read_bytes() == before


# --------------------------------------------------------------- sabotage


def test_sabotaged_marker_fails_loud_naming_the_file(env, capsys):
    skill_md = seed_routed_skill_target(env)
    text = skill_md.read_text(encoding="utf-8")
    skill_md.write_text(text.replace(END_MARKER + "\n", ""), encoding="utf-8")

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    assert rc != 0
    assert "FAIL markers" in out
    assert str(skill_md) in out


def test_target_missing_markers_entirely_fails(env, capsys):
    skill_md = seed_routed_skill_target(env)
    skill_md.write_text(SKILL_MD, encoding="utf-8")  # markers gone

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    assert rc != 0
    assert "FAIL markers" in out
    assert str(skill_md) in out


def test_target_file_missing_fails(env, capsys):
    skill_md = seed_routed_skill_target(env)
    skill_md.unlink()
    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "FAIL markers" in out
    assert str(skill_md) in out


def test_unrouted_targets_are_not_flagged(env, capsys):
    # A markerless host SKILL.md with NO routed records must not fail:
    # 02 §4's bootstrap rule covers first-route targets. (The seed
    # SKILL.md in the host is already markerless.) Nothing routed means
    # every real check trivially PASSes; fold r1, 2026-09-04 dropped the
    # worker placeholder row, so this healthy home exits 0.
    (env.ledger / "skills" / "s" / "pending").mkdir(parents=True)
    rc = cli.main(["--selftest"])
    assert rc == 0
    assert "FAIL" not in capsys.readouterr().out


# ---------------------------------------------------------------- sentinel


def test_selftest_leaves_a_live_foreign_sentinel_in_place(env, capsys):
    hold = sentinel.hold()  # another flow's live hold (e.g. slash review)
    assert hold.owned

    rc = cli.main(["--selftest"])

    # a live foreign sentinel is a PASS (heartbeat ok), not a FAIL or an
    # UNMEASURED -- with nothing routed, every real check PASSes, so
    # (fold r1, 2026-09-04, no worker placeholder row) this exits 0.
    assert rc == 0
    assert sentinel.sentinel_path().exists()  # never deleted a live hold
    assert "PASS sentinel" in capsys.readouterr().out


def test_selftest_probe_sentinel_is_released(env, capsys):
    assert not sentinel.sentinel_path().exists()
    # fold r1, 2026-09-04: no worker placeholder row -- nothing routed
    # means every real check PASSes, so this exits 0.
    assert cli.main(["--selftest"]) == 0
    assert not sentinel.sentinel_path().exists()


# ------------------------------------------------------------ missing home


def test_missing_home_refuses_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "nowhere"))
    rc = cli.main(["--selftest"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "SELF_LEARN_HOME" in err or "nowhere" in err


# --------------------------------------------------------- reach (U-reach)
#
# The R14 defect this check exists to catch: a `reference`-routed record
# whose target file the drift check confirms is WRITTEN, but that nothing
# in the loaded surface (SKILL.md / CLAUDE.md) NAMES — drift answers "did
# the write land?"; reach answers "can anything get to it?".


def test_reach_reachable_fixture_passes_criterion_1(env):
    """F1/criterion 1: a real pointer PASSES, and the count is asserted in
    the message — a `(True, …)` produced because RR came out EMPTY is the
    exact failure this half of the gate exists to exclude."""
    record = seed_reference_record(env)
    target = env.skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"lesson from {record.id}\n", encoding="utf-8")
    env.skill_md.write_text(
        SKILL_MD + "\n[Learnings](references/LEARNINGS.md)\n", encoding="utf-8"
    )

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.PASS
    assert "1 reference-routed record(s) reachable" in reason

    # fold r1, 2026-09-04: no worker placeholder row -- this reference
    # -only fixture (surface's own domain is empty) is genuinely all-PASS.
    assert cli.main(["--selftest"]) == 0


def test_reach_ancestor_only_pointer_makes_a_child_record_reachable_anc7(env, tmp_path):
    """ANC7 end-to-end leg: a PROJECT-scope reference-routed record's own
    bucket is the CHILD host; its own `CLAUDE.md` carries NO resolving
    pointer at all. A resolving pointer is hand-placed ONLY in the
    registered ANCESTOR's `CLAUDE.md`. `_check_reach` still finds it
    reachable, because `_loaded_surface`'s project branch appends the
    registered ancestor's `CLAUDE.md` (nearest-first) after the host's
    own — the SAME loading fact `InstructionsLoaded` measured (S-52).
    Reverting that append (dropping the `_loaded_surface` ancestor
    member) reddens this by turning the pass FAIL, naming the record."""
    ancestor = tmp_path / "ancestor-repo"
    init_repo(ancestor)
    (ancestor / "CLAUDE.md").write_text("# ancestor project\n", encoding="utf-8")
    commit_all(ancestor, "ancestor seed")

    child = ancestor / "child-repo"
    init_repo(child)
    (child / "CLAUDE.md").write_text("# child project\n", encoding="utf-8")
    commit_all(child, "child seed")

    save_hosts(env.ledger, Hosts(projects=[child, ancestor]))

    from self_learn.hosts import slug_for
    from self_learn.ledger_ops import ensure_project_meta

    bucket_dir = env.ledger / "projects" / slug_for(child)
    resolved = bucket_dir / "resolved"
    resolved.mkdir(parents=True)
    ensure_project_meta(bucket_dir, child)

    record = make_behavior(scope="project", record_id="lrn-0000a7a7")
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "reference", "by": "human"}
    )
    record.set_status("routed")
    record.write(resolved / f"{record.id}.md")

    target = child / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"lesson from {record.id}\n", encoding="utf-8")

    # The resolving pointer lives ONLY in the ancestor's CLAUDE.md, as a
    # path RELATIVE TO THE ANCESTOR (the token is read as the author
    # meant it, `compilers.surface_names_target`) -- the child's own
    # CLAUDE.md never mentions it.
    (ancestor / "CLAUDE.md").write_text(
        "# ancestor project\n\n[Learnings](child-repo/references/LEARNINGS.md)\n",
        encoding="utf-8",
    )

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.PASS, reason
    assert "1 reference-routed record(s) reachable" in reason

    # fold r1, 2026-09-04: no worker placeholder row -- this reference
    # -only fixture (surface's own domain is empty) is genuinely all-PASS.
    assert cli.main(["--selftest"]) == 0


def test_reach_un3_no_ancestor_reach_row_matches_the_pre_ancestry_shape(env):
    """UN3: for a project-scope host with NO registered ancestor,
    `_loaded_surface` returns exactly ONE member (the host's own
    `CLAUDE.md`, unchanged) and `--selftest`'s reach row reads exactly as
    it would have before U-ancestry -- proof the ANC7 append is
    additive-only and never touches the no-ancestor case."""
    from self_learn.hosts import slug_for
    from self_learn.ledger_ops import ensure_project_meta
    from self_learn.ledger import Bucket as _Bucket

    host = env.ledger.parent / "solo-host"
    init_repo(host)
    (host / "CLAUDE.md").write_text(
        "# solo project\n\n[Learnings](references/LEARNINGS.md)\n", encoding="utf-8"
    )
    commit_all(host, "solo seed")

    # A second, CHILD host nested inside `host` is also registered here
    # (unused by the project-scope assertion below, which is about
    # `host` itself having no ancestor) purely so `hosts.yaml` contains
    # a real ancestor RELATION somewhere -- the user-scope assertion
    # after this needs at least one to exist, or M20's leak (appending
    # `ancestors_of(hosts, p)` for every registered project) would have
    # nothing to append and could pass while genuinely broken.
    child = host / "child-repo"
    init_repo(child)
    (child / "CLAUDE.md").write_text("# child project\n", encoding="utf-8")
    commit_all(child, "child seed")

    save_hosts(env.ledger, Hosts(projects=[host, child]))

    bucket_dir = env.ledger / "projects" / slug_for(host)
    resolved = bucket_dir / "resolved"
    resolved.mkdir(parents=True)
    ensure_project_meta(bucket_dir, host)

    record = make_behavior(scope="project", record_id="lrn-000003a3")
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "reference", "by": "human"}
    )
    record.set_status("routed")
    record.write(resolved / f"{record.id}.md")

    (host / "references").mkdir()
    (host / "references" / "LEARNINGS.md").write_text(
        f"lesson from {record.id}\n", encoding="utf-8"
    )

    surfaces = selfcheck._loaded_surface(
        env.ledger, _Bucket(scope="project", name=slug_for(host), path=bucket_dir), record
    )
    assert surfaces == [host / "CLAUDE.md"]

    # UN3's other half (M20): USER scope is untouched by the ancestry
    # append too -- even with a registered host present in hosts.yaml
    # (the same fixture, above), `_loaded_surface` for a user-scope
    # record still returns exactly the one real user CLAUDE.md member,
    # never widened by iterating any host's ancestors.
    user_record = make_knowledge(scope="user", record_id="lrn-000003a4")
    user_surfaces = selfcheck._loaded_surface(
        env.ledger, _Bucket(scope="user", name="user", path=env.ledger / "user"), user_record
    )
    assert user_surfaces == [DEFAULT_USER_CLAUDE_MD.expanduser()]

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.PASS
    assert reason == "1 reference-routed record(s) reachable from their scope's loaded surface"


def test_reach_unreachable_fixture_fails_criterion_2(env, capsys):
    """F2, the other half of the gate: the SAME fixture with the pointer
    line removed FAILS, naming both the record and the surface path."""
    record = seed_reference_record(env)
    target = env.skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"lesson from {record.id}\n", encoding="utf-8")
    # env.skill_md stays the bare seed — no pointer anywhere in it.

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.FAIL
    assert record.id in reason
    assert str(env.skill_md) in reason

    assert cli.main(["--selftest"]) == 1
    out = capsys.readouterr().out
    assert "FAIL reach" in out


def test_reach_count_leads_the_message(env):
    """Criterion 3: the failing count LEADS the message, both at 3-of-3
    and at 2-of-3 — greppable from one line (§9's Checkpoint B need)."""
    ids = []
    for i, ref_file in enumerate(("notes-a.md", "notes-b.md", "notes-c.md")):
        record = seed_reference_record(
            env, record_id=f"lrn-0000000{i}", reference_file=ref_file
        )
        ids.append(record.id)

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.FAIL
    assert reason.startswith("3 of 3")
    for rid in ids:
        assert rid in reason

    # Name exactly ONE of the three targets — one reachable, two not.
    target_a = env.skill_dir / "references" / "notes-a.md"
    target_a.parent.mkdir(parents=True, exist_ok=True)
    target_a.write_text("x\n", encoding="utf-8")
    env.skill_md.write_text(SKILL_MD + "\nsee references/notes-a.md\n", encoding="utf-8")

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.FAIL
    assert reason.startswith("2 of 3")


def test_reach_token_must_resolve_not_merely_appear(tmp_path):
    """Criterion 6, one test, four directions, same fixture. The bare
    basename leg is the discriminator for a bare-basename-only predicate
    (§2.1 steps 3-4); the trailing-period leg is the §2.1-step-2
    discriminator (left-maximal, anchored on the basename — a
    both-directions-maximal tokenizer fails this leg and nothing else in
    this suite would notice, F6)."""
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    surface = skill_dir / "SKILL.md"
    target = skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True)
    target.write_text("lessons\n", encoding="utf-8")

    surface.write_text("read LEARNINGS.md for prior lessons\n", encoding="utf-8")
    assert not selfcheck._surface_names_target(surface, target)

    surface.write_text("read references/LEARNINGS.md\n", encoding="utf-8")
    assert selfcheck._surface_names_target(surface, target)

    surface.write_text("see references/LEARNINGS.md.\n", encoding="utf-8")
    assert selfcheck._surface_names_target(surface, target)

    surface.write_text(f"see {target}\n", encoding="utf-8")
    assert selfcheck._surface_names_target(surface, target)


def test_reach_same_basename_wrong_directory_fails_criterion_4(tmp_path):
    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    surface = skill_dir / "SKILL.md"
    target = skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True)
    target.write_text("x\n", encoding="utf-8")
    other = tmp_path / "skills" / "other" / "LEARNINGS.md"
    other.parent.mkdir(parents=True)
    other.write_text("y\n", encoding="utf-8")  # a REAL file, wrong directory

    surface.write_text("see ../other/LEARNINGS.md\n", encoding="utf-8")
    assert not selfcheck._surface_names_target(surface, target)


def test_reach_different_file_same_directory_fails_criterion_5(tmp_path):
    skill_dir = tmp_path / "skills" / "s"
    (skill_dir / "references").mkdir(parents=True)
    surface = skill_dir / "SKILL.md"
    target = skill_dir / "references" / "LEARNINGS.md"
    target.write_text("x\n", encoding="utf-8")
    (skill_dir / "references" / "GOTCHAS.md").write_text("y\n", encoding="utf-8")

    surface.write_text("see references/GOTCHAS.md\n", encoding="utf-8")
    assert not selfcheck._surface_names_target(surface, target)


# The three tests below re-run criteria 4, 5, 6 through the FULL
# `_check_reach` pipeline (RR discovery + `_reference_target_for` +
# `_loaded_surface`, not just the predicate in isolation) — the direct
# `_surface_names_target` tests above pin the predicate precisely; these
# pin the end-to-end wiring, so a mutation to `_check_reach` itself (e.g.
# M1's destination-literal swap) has a fixture to kill, not just a
# mutation to `_surface_names_target`.


def test_reach_same_basename_wrong_directory_fails_criterion_4_e2e(env):
    record = seed_reference_record(env)
    target = env.skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n", encoding="utf-8")
    other = env.host / "plugins" / "s-plugin" / "skills" / "other" / "LEARNINGS.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("y\n", encoding="utf-8")  # a REAL file, wrong directory
    env.skill_md.write_text(SKILL_MD + "\nsee ../other/LEARNINGS.md\n", encoding="utf-8")

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.FAIL
    assert record.id in reason


def test_reach_different_file_same_directory_fails_criterion_5_e2e(env):
    record = seed_reference_record(env)
    target = env.skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n", encoding="utf-8")
    (env.skill_dir / "references" / "GOTCHAS.md").write_text("y\n", encoding="utf-8")
    env.skill_md.write_text(SKILL_MD + "\nsee references/GOTCHAS.md\n", encoding="utf-8")

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.FAIL
    assert record.id in reason


def test_reach_token_must_resolve_not_merely_appear_criterion_6_e2e(env):
    seed_reference_record(env)
    target = env.skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n", encoding="utf-8")

    env.skill_md.write_text(
        SKILL_MD + "\nread LEARNINGS.md for prior lessons\n", encoding="utf-8"
    )
    ok, _reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.FAIL

    env.skill_md.write_text(
        SKILL_MD + "\nread references/LEARNINGS.md\n", encoding="utf-8"
    )
    ok, _reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.PASS

    env.skill_md.write_text(
        SKILL_MD + "\nsee references/LEARNINGS.md.\n", encoding="utf-8"
    )
    ok, _reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.PASS

    env.skill_md.write_text(SKILL_MD + f"\nsee {target}\n", encoding="utf-8")
    ok, _reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.PASS


def test_reach_unresolvable_target_fails_naming_the_record_criterion_7(env):
    """A skill-scope reference record whose skill is NOT under the
    registered skills root — `_reference_target_for` cannot resolve it, and
    the check must FAIL naming the record, never skip (M6)."""
    resolved = env.ledger / "skills" / "ghost" / "resolved"
    resolved.mkdir(parents=True)
    record = make_behavior(scope="skill:ghost", record_id="lrn-00000007")
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "reference", "by": "human"}
    )
    record.set_status("routed")
    record.write(resolved / f"{record.id}.md")

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.FAIL
    assert record.id in reason


def test_reach_empty_ls_fails_never_skips_criterion_8(env, monkeypatch):
    """A project-scope reference record whose bucket has no registered
    project host (no meta.yaml — `bucket_project_path` returns None, so
    `_loaded_surface` genuinely returns `[]`). `_reference_target_for` is
    keyed off the SAME lookup for project scope, so it fails identically
    in any REAL fixture — criterion 7 (target-unresolvable) is already
    exercised end-to-end above; forcing the target to resolve here isolates
    criterion 8's own branch (M7) instead of re-testing M6 by accident."""
    resolved = env.ledger / "projects" / "orphan" / "resolved"
    resolved.mkdir(parents=True)
    record = make_knowledge(scope="project", record_id="lrn-00000008")
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "reference", "by": "human"}
    )
    record.set_status("routed")
    record.write(resolved / f"{record.id}.md")

    fake_target = env.ledger / "elsewhere" / "LEARNINGS.md"
    monkeypatch.setattr(
        selfcheck, "_reference_target_for", lambda home, bucket, rec: fake_target
    )

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.FAIL
    assert record.id in reason


def test_reach_present_but_missing_surface_fails_criterion_8a(env):
    """LS is non-empty (the path resolves via the registered skill), but
    the file itself does not exist — criterion 8 does not cover this;
    `if not surface.is_file(): return True` (M7a) turns nothing red without
    this fixture."""
    record = seed_reference_record(env)
    target = env.skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n", encoding="utf-8")
    env.skill_md.unlink()  # the skill DIRECTORY still resolves; the file doesn't

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.FAIL
    assert record.id in reason


def test_reach_target_resolve_is_load_bearing_through_symlink_criterion_8b(env, tmp_path):
    """The registered skills root is reached through a SYMLINK, so
    `_reference_target_for`'s target carries the symlink's own prefix,
    unresolved, while the SKILL.md pointer names the REAL absolute path —
    only `target.resolve()` (§2.1 step 4) makes them equal (M5b drops it;
    on Linux, without a symlink in the fixture, that mutation turns
    nothing red — reviewer's INV-3)."""
    link_root = tmp_path / "skills-link"
    link_root.symlink_to(env.host, target_is_directory=True)
    save_hosts(env.ledger, Hosts(skills_root=link_root, projects=[env.host]))

    record = seed_reference_record(env)
    target_real = env.skill_dir / "references" / "LEARNINGS.md"
    target_real.parent.mkdir(parents=True, exist_ok=True)
    target_real.write_text(f"lesson from {record.id}\n", encoding="utf-8")
    env.skill_md.write_text(
        f"{SKILL_MD}\nsee {target_real.resolve()}\n", encoding="utf-8"
    )

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.PASS, reason
    assert "1 reference-routed record(s) reachable" in reason


def test_reach_only_live_records_count_criterion_9(env):
    """A `superseded_by`-set reference record and a `status: pending` one
    are both excluded from RR — reach reports 0 and PASSes."""
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True)

    superseded = make_behavior(scope="skill:s", record_id="lrn-00000009")
    superseded.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "reference", "by": "human"}
    )
    superseded.set_status("superseded")
    superseded.set_superseded_by("lrn-00000099")
    superseded.write(resolved / f"{superseded.id}.md")

    pending = make_behavior(scope="skill:s", record_id="lrn-00000010")
    pending.write(resolved / f"{pending.id}.md")  # fresh Record.create: status pending

    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.PASS
    assert "no reference-routed records" in reason


def test_loaded_surface_user_scope_returns_default_claude_md_criterion_9a(
    tmp_path, monkeypatch
):
    """A direct unit test of the LS helper: `record.scope == "user"`
    returns `[DEFAULT_USER_CLAUDE_MD.expanduser()]`, never `[]`. The `user`
    row is dead code end-to-end via any REAL routing flow — permanently,
    per S-23 (2) (`03-decisions.md`), not "until `U-demand-user`" as this
    docstring said at write time: S-23 ruled user scope's cheap surface is
    PATHED rules only, explicitly not a user-level reference file, and
    re-scoped `U-demand-user` away from ever opening it. `reference` is
    refused at user scope by design (§6) — `_reference_target_for` returns
    `None` before LS is ever consulted — so the helper is tested directly;
    the alternative is a scope silently outside RR (F1)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    home = tmp_path / "ledger"
    home.mkdir()
    bucket = Bucket(path=home / "user", scope="user", name="user")
    record = make_behavior(scope="user", record_id="lrn-00000011")

    surfaces = selfcheck._loaded_surface(home, bucket, record)

    assert surfaces == [DEFAULT_USER_CLAUDE_MD.expanduser()]
    assert surfaces != []


def test_reach_domain_walks_the_user_bucket_criterion_9a(env):
    """M8a / F1's own mutation, the other half of 9a: `discover_buckets`
    (never a `<home>/*/*/resolved/` glob) is what makes the ONE-LEVEL
    `user/` bucket part of RR's domain. The record is hand-crafted
    straight into `user/resolved/` — the destination refusal makes this
    dead via any real routing verb, which is exactly why a narrower
    glob's silent drop was invisible until this unit. The record still
    FAILS either way (`_reference_target_for` returns None for user scope
    regardless), so the observable fact a narrower glob would hide is not
    the verdict — it's whether the record was COUNTED at all."""
    resolved = env.ledger / "user" / "resolved"
    resolved.mkdir(parents=True)
    record = make_behavior(scope="user", record_id="lrn-0000009a")
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "reference", "by": "human"}
    )
    record.set_status("routed")
    record.write(resolved / f"{record.id}.md")

    ok, reason = selfcheck._check_reach(env.ledger)

    assert ok is selfcheck.Verdict.FAIL
    assert reason.startswith("1 of 1")
    assert record.id in reason


def test_reach_zero_reference_records_passes_criterion_10(env):
    ok, reason = selfcheck._check_reach(env.ledger)
    assert ok is selfcheck.Verdict.PASS
    assert "no reference-routed records" in reason


def test_reach_hosts_yaml_absent_is_unmeasured_not_checked_criterion_11(tmp_path):
    bare = tmp_path / "bare-ledger"
    init_repo(bare)
    ok, reason = selfcheck._check_reach(bare)
    assert ok is selfcheck.Verdict.UNMEASURED
    assert "not checked" in reason


def test_reach_missing_home_fails_criterion_11(tmp_path):
    ok, reason = selfcheck._check_reach(tmp_path / "nowhere")
    assert ok is selfcheck.Verdict.FAIL


def test_reach_not_a_repo_home_fails_criterion_11(tmp_path):
    not_repo = tmp_path / "plain-dir"
    not_repo.mkdir()
    ok, reason = selfcheck._check_reach(not_repo)
    assert ok is selfcheck.Verdict.FAIL


def test_selftest_reports_nine_checks_criterion_12(env, capsys):
    seed_routed_skill_target(env)
    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out
    # this `env` fixture has no real ~/.claude, so `surface` is genuinely
    # UNMEASURED (claude-dir-absent) -- the only reason this run is 9,
    # not 0. fold r1, 2026-09-04 dropped the worker placeholder row, so
    # the summary line has one fewer UNMEASURED than before (1, not 2).
    assert rc == 9
    assert "PASS reach" in out
    assert "8 passed, 1 unmeasured, 0 failed" in out


# --------------------------------------------------- FW-66: decode safety
#
# `--selftest` must FAIL loud (or skip a record the same way a malformed
# one already does) on non-UTF-8 bytes, never traceback — measured live: a
# corrupt loaded surface or resolved record file killed `_check_reach`
# outright with a raw `UnicodeDecodeError`, and a corrupt resolved record
# file killed `run_selftest` even earlier (`_section_targets`, called
# before any of the seven checks run), before a single PASS/FAIL row
# printed.


def _write_bad_bytes(path, prefix: str = "") -> None:
    """`prefix` (valid UTF-8) + a byte that is not a valid UTF-8 lead byte
    anywhere — guaranteed to raise ``UnicodeDecodeError`` on decode."""
    path.write_bytes(prefix.encode("utf-8") + b"\xff\xfe garbage")


def test_reach_undecodable_surface_fails_naming_the_record(env, capsys):
    """The loaded surface is a file self-learn does not own and cannot
    constrain — an undecodable SKILL.md must FAIL the record (never
    crash, never a silent pass), with a message DISTINCT from "not named
    by its loaded surface" (the real problem is the encoding, not a
    missing pointer — criterion: an un-checkable condition reports as
    itself, not as a different claim)."""
    record = seed_reference_record(env)
    target = env.skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"lesson from {record.id}\n", encoding="utf-8")
    _write_bad_bytes(
        env.skill_md, SKILL_MD + "\n[Learnings](references/LEARNINGS.md)\n"
    )

    ok, reason = selfcheck._check_reach(env.ledger)

    assert ok is selfcheck.Verdict.FAIL
    assert record.id in reason
    assert "not readable as UTF-8" in reason
    assert "not named by its loaded surface" not in reason

    assert cli.main(["--selftest"]) == 1
    out = capsys.readouterr().out
    assert "FAIL reach" in out
    assert "not readable as UTF-8" in out


def test_reach_undecodable_resolved_record_skipped_not_crashed(env):
    """A resolved record file with bad bytes is skipped exactly like a
    RecordError (malformed YAML) resolved file already was (T3's problem,
    not this check's — its routing/destination/scope cannot even be
    read). Never a traceback, and never lets the corrupt file block a
    REAL, reachable record's own row."""
    good = seed_reference_record(env, record_id="lrn-00009999")
    target = env.skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"lesson from {good.id}\n", encoding="utf-8")
    env.skill_md.write_text(
        SKILL_MD + "\n[Learnings](references/LEARNINGS.md)\n", encoding="utf-8"
    )
    resolved = env.ledger / "skills" / "s" / "resolved"
    _write_bad_bytes(resolved / "lrn-0badbeef.md", "---\ntype: knowledge\n---\n")

    ok, reason = selfcheck._check_reach(env.ledger)

    assert ok is selfcheck.Verdict.PASS  # the corrupt file never counted; the good one is reachable
    assert "1 reference-routed record(s) reachable" in reason


def test_selftest_survives_corrupt_resolved_record_prints_all_nine_rows(env, capsys):
    """The end-to-end proof: `_section_targets` (feeding checks (b)/(c),
    called BEFORE the seven-check loop even runs) shares the identical
    from_path/RecordError gap — left unfixed, a corrupt resolved record
    file killed `--selftest` before it printed a single row, not just the
    reach/drift ones. Exercised through the full `cli.main(["--selftest"])`
    a user actually runs, not the `_check_reach` unit alone."""
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    _write_bad_bytes(resolved / "lrn-0badbeef.md", "---\ntype: knowledge\n---\n")

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    # fold r1, 2026-09-04: no worker placeholder row, and nothing routed
    # to skill-md/claude-md here means every real check PASSes (the
    # corrupt resolved record is skipped, not counted) -- exit 0.
    assert rc == 0
    assert "9 passed, 0 unmeasured, 0 failed" in out
    for check in (
        "capture", "compiler", "markers", "drift", "reach", "hooks", "surface", "sentinel",
    ):
        assert f"PASS {check}" in out


def test_drift_undecodable_target_fails_naming_the_file(env, capsys):
    """FW-66's twin fix in `_check_drift`: the compiled managed-section
    target self-learn writes CAN still carry non-UTF-8 bytes (a hand edit,
    a bad merge) — must FAIL naming the file, never crash."""
    skill_md = seed_routed_skill_target(env)
    text = skill_md.read_text(encoding="utf-8")
    _write_bad_bytes(skill_md, text)

    ok, reason = selfcheck._check_drift(env.ledger)

    assert ok is selfcheck.Verdict.FAIL
    assert "not readable as UTF-8" in reason
    assert str(skill_md) in reason

    assert cli.main(["--selftest"]) == 1
    out = capsys.readouterr().out
    assert "FAIL drift" in out


def test_drift_undecodable_references_file_fails_naming_the_record(env):
    """The reference-destination twin of the above: an undecodable
    references file must FAIL, never crash, and distinctly from "entry
    missing" (the real problem is the encoding, not an absent entry)."""
    record = seed_reference_record(env)
    target = env.skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_bad_bytes(target, f"lesson from {record.id}\n")

    ok, reason = selfcheck._check_drift(env.ledger)

    assert ok is selfcheck.Verdict.FAIL
    assert record.id in reason
    assert "not readable as UTF-8" in reason
    assert "entry missing" not in reason
