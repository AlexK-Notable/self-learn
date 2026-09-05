"""M-K: tri-state `--selftest` verdicts (PASS/FAIL/UNMEASURED) and the
exit-9 namespace they earn (Sprint 2, lane L2). New file, armor
untouched: asserts the ``Verdict`` enum's own contract plus the verdict
class each pinned site family renders, and the fold into
``cli.EXIT_UNMEASURED`` (9) that ``run_selftest`` performs.

Load-bearing finding, stated here (and in the sprint report) rather than
buried in a comment nobody reads: the ``worker`` row (M2 — not yet
implemented) is now a REAL, COUNTED, UNCONDITIONAL ``UNMEASURED`` row —
it never ran a check, so it can never be anything else. Combined with
"any UNMEASURED with no FAIL exits 9", this means ``--selftest`` cannot
exit 0 on ANY home today, healthy or not; every "healthy" scenario below
asserts exit 9, never 0, for exactly this reason. Exit 0 becomes
reachable again only once M2 gives the worker row something to measure.
"""

from __future__ import annotations

import pytest

from self_learn import cli, provider, selfcheck
from self_learn.compilers import END_MARKER, compile_managed_file
from self_learn.selfcheck import Verdict

from support import init_repo, make_behavior, make_env


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel probes go to a per-test XDG cache, never the real ~/.cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


def _seed_routed_skill_target(env):
    """A resolved, live skill-md-routed record + its compiled SKILL.md
    (markers present) — the minimal fixture that puts exactly one row in
    every reachability-domain check (surface) while leaving drift/reach/
    hooks/markers/compiler each with their own single measured row."""
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True)
    record = make_behavior(scope="skill:s", record_id="lrn-0a1b2c3d")
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "skill-md", "by": "human"}
    )
    record.set_status("routed")
    record.write(resolved / f"{record.id}.md")
    compile_managed_file(env.skill_md, [record])
    return env.skill_md


# ------------------------------------------------------- the type itself


def test_verdict_has_no_truth_value():
    """The `__bool__` guard: pinned text is silent on it, but a plain
    object with no override IS truthy, so a leftover `if verdict:` /
    `assert verdict` would silently read FAIL and UNMEASURED alike as
    PASS — exactly the fail-open shape M-K exists to close. Every caller
    must compare explicitly."""
    with pytest.raises(TypeError):
        bool(Verdict.PASS)
    with pytest.raises(TypeError):
        bool(Verdict.FAIL)
    with pytest.raises(TypeError):
        bool(Verdict.UNMEASURED)


def test_verdict_members_render_as_their_own_name():
    assert Verdict.PASS.value == "PASS"
    assert Verdict.FAIL.value == "FAIL"
    assert Verdict.UNMEASURED.value == "UNMEASURED"


# ------------------------------------------------- run_selftest end to end


def test_healthy_home_exits_9_not_0_because_worker_is_always_unmeasured(env, capsys):
    """Class: healthy zeros (a home with nothing routed). Every real
    check PASSes; only `worker` (M2, now counted) is UNMEASURED.
    Mutation witness: change `cli.EXIT_UNMEASURED` from 9 to 0 (or
    `run_selftest`'s `return EXIT_UNMEASURED` back to `return 0`) and
    this reddens on the exit-code assertion alone."""
    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out

    assert rc == 9
    assert "FAIL" not in out
    assert "UNMEASURED worker — M2 — not checked" in out
    assert "9 passed, 1 unmeasured, 0 failed" in out


def test_hosts_yaml_absent_is_unmeasured_not_a_silent_pass(tmp_path, monkeypatch):
    """Class: the four explicit skips on a missing prerequisite the check
    cannot itself supply (drift/reach/surface/hooks, each pinned to
    UNMEASURED). A bare repo with no hosts.yaml can measure NOTHING about
    any of the four. Mutation witness: flip any one of the four sites
    back to `Verdict.PASS` (the old bare `True`) and its own assertion
    below reddens."""
    bare = tmp_path / "bare-ledger"
    init_repo(bare)
    monkeypatch.setenv("SELF_LEARN_HOME", str(bare))

    claude_dir = selfcheck.claude_runtime_dir()
    assert selfcheck._check_drift(bare)[0] is Verdict.UNMEASURED
    assert selfcheck._check_reach(bare)[0] is Verdict.UNMEASURED
    assert selfcheck._check_surface(bare, claude_dir)[0] is Verdict.UNMEASURED
    assert selfcheck._check_hooks(bare, claude_dir)[0] is Verdict.UNMEASURED

    rc = cli.main(["--selftest"])
    assert rc == 9


def test_all_unmeasurable_surface_is_unmeasured_not_a_free_pass(env, capsys):
    """Class: the 1011 conditional — every row in the surface check's
    domain is `unmeasurable` (here: one skill-md-routed record, no real
    claude_dir at all, so its row reads `claude-dir-absent`). Must be
    UNMEASURED, never PASS-by-virtue-of-nothing-failing. Mutation
    witness: revert `_check_surface`'s tail to the pre-M-K expression
    `ok = not unreachable and not fails_on_settings` — that expression is
    `True` here (unreachable == 0), so this test's own assertion reddens
    directly, and the exit-code assertion reddens too (9 -> 0)."""
    _seed_routed_skill_target(env)

    ok, msg = selfcheck._check_surface(env.ledger, selfcheck.claude_runtime_dir())
    assert ok is Verdict.UNMEASURED
    assert "0 of 1 verified reachable" in msg
    assert "UNMEASURABLE" in msg

    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out
    assert rc == 9
    assert "UNMEASURED surface" in out


def test_all_skip_preflight_is_unmeasured_not_a_free_pass(env, monkeypatch):
    """Class: the 1039 conditional — a preflight sweep whose rows are all
    WARN/SKIP/INFO (no PASS, no FAIL) decided nothing about invocation
    health. Mutation witness: revert `_check_invocation` to the pre-M-K
    `ok = not any(row.verdict == "FAIL" for row in rows)` — that
    expression is `True` on an all-SKIP sweep, so this test's own
    assertion reddens directly."""

    def all_skip(home):
        return [provider.Row(name="sdk", verdict="SKIP", detail="stubbed for this test")]

    # selfcheck.py does `from . import provider` — patching the shared
    # module object's attribute is visible through selfcheck's own
    # `provider` name too (same singleton module, not a copied binding).
    monkeypatch.setattr(provider, "preflight", all_skip)

    ok, reason = selfcheck._check_invocation(env.ledger)

    assert ok is Verdict.UNMEASURED
    assert "no PASS/FAIL preflight row" in reason


def test_fail_beside_unmeasured_exits_1_never_9(env, capsys):
    """Class: FAIL wins over UNMEASURED in the exit code even when
    UNMEASURED rows are ALSO present in the same run (surface is
    UNMEASURED here too, via the same absent-claude_dir shape as the
    test above, while markers is a real, sabotaged-marker FAIL)."""
    skill_md = _seed_routed_skill_target(env)
    text = skill_md.read_text(encoding="utf-8")
    skill_md.write_text(text.replace(END_MARKER + "\n", ""), encoding="utf-8")

    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "FAIL markers" in out
    assert "UNMEASURED surface" in out
