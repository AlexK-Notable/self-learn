"""U-cap — the report-only context budget (spec:
docs/specs/self-learn/drafts/u-cap-context-budget-spec.md §7, T2-T8/T10).

Covers the four signals (`budget`, `crowding`, `composition`, `growth`)
and the two conditional verdicts (`reference`, `rules_cofire`) under
`report.context_budget()`, plus the T10 report-only invariant (nothing
here ever refuses a route). T1 (retirement completeness), T9
(`surface_fill` shape), T11 (verb envelope/note), T12 (UI) live in their
own files per the spec's file map (§8 / this unit's builder notes) —
`test_surface_fill.py`, `test_resolution_evidence.py`,
`ui/tests/test_models_detail.py`, `ui/tests/test_routes.py`.

Every ``~/.claude`` read in this unit (the session skill index AND the
default user ``CLAUDE.md`` target, §4.2's ``_SKILL_INDEX_KEY``/the
``user-claude-md`` row) resolves through ``selfcheck.claude_runtime_dir()``
-- ``SELF_LEARN_CLAUDE_DIR`` if set, else the real ``~/.claude`` (code gate
r1, MAJOR 1 fold: previously a plain ``Path("~/...").expanduser()``, HOME-
driven and unsandboxed by anything except this file's own ``env`` fixture,
so every OTHER test in the suite that reached ``report.gather()`` read the
operator's real home). The ``env`` fixture below sets BOTH ``HOME`` (belt)
and ``SELF_LEARN_CLAUDE_DIR`` (the actual resolution knob now) to an
isolated ``tmp_path`` directory carrying an empty ``.claude/skills`` index
for every test in this file — without it, these tests would silently read
the real operator's ``~/.claude/skills`` (45 real skills, one host
measurement 2026-08-23) and real ``~/.claude/CLAUDE.md``, which is exactly
the hazard this unit's hard boundary ("~/.claude/skills is read-only
input; tests use a sandboxed index") exists to prevent. Suite-wide
hermeticity for the OTHER 70-odd CLI test files rides the SAME knob: it is
already set globally, unconditionally, by ``cli/tests/conftest.py``'s
(unmodified, armor-pinned) ``_worker_test_defaults`` fixture — see
``report.py``'s ``_resolve_user_claude_md_row``/``_skill_description_row``
docstrings for why conftest.py itself was not touched to fix this.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from self_learn import cli, report, verbs, worker
from self_learn.ledger_ops import bucket_dir_for_scope, create_record, ensure_project_meta
from self_learn.records import Record

from support import git, init_repo, make_behavior, make_env

from test_refread import _instrument, days_ago_ts, write_tracked_event

TODAY = date(2026, 8, 23)


# --------------------------------------------------------------- fixtures


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A ledger + host sandbox (``support.make_env``) with ``HOME`` AND
    ``SELF_LEARN_CLAUDE_DIR`` redirected to an ISOLATED tmp directory
    carrying an empty ``.claude/skills`` index — every ``~/.claude``-
    rooted read this unit's report code performs lands here, never on
    the real operator's home. ``SELF_LEARN_CLAUDE_DIR`` is the one that
    actually matters post-MAJOR-1-fold (``claude_runtime_dir()`` checks
    it BEFORE falling back to HOME-driven ``~/.claude``); ``HOME`` is
    kept in step for any code path that still resolves `~` directly
    (e.g. `Path.home()` call sites elsewhere in this codebase)."""
    e = make_env(tmp_path, skills=("s",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    fake_home = tmp_path / "fake-home"
    (fake_home / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(fake_home / ".claude"))
    e.fake_home = fake_home
    e.user_claude_md = fake_home / ".claude" / "CLAUDE.md"
    e.skills_index = fake_home / ".claude" / "skills"
    return e


# ----------------------------------------------------------------- helpers


def _n_words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def _set_user_claude_md(env, text: str) -> None:
    env.user_claude_md.parent.mkdir(parents=True, exist_ok=True)
    env.user_claude_md.write_text(text, encoding="utf-8")


def _write_routed(
    env,
    *,
    scope: str,
    record_id: str,
    destination: str,
    routed_at: str,
    rtype: str = "knowledge",
    fact: str | None = None,
    kind: str | None = None,
    trigger: str | None = None,
    instruction: str | None = None,
    new_skill: str | None = None,
    project_path: Path | None = None,
    status: str = "routed",
    superseded_by: str | None = None,
) -> Record:
    """A resolved routed record, written straight into ``<bucket>/resolved``
    — the same pattern ``test_surface_fill.py``'s ``_routed_knowledge`` /
    ``_write_routed`` use, generalized to any destination/scope."""
    if rtype == "knowledge":
        rec = Record.create(
            type="knowledge", scope=scope, source="teach",
            fact=fact or f"fact for {record_id}", record_id=record_id,
        )
    else:
        rec = Record.create(
            type="behavior", scope=scope, source="teach",
            kind=kind or "anti-pattern",
            trigger=trigger or f"trigger for {record_id}",
            instruction=instruction or "do the corrective thing",
            record_id=record_id,
        )
    routing = {"routed_at": routed_at, "destination": destination, "by": "human"}
    if new_skill is not None:
        routing["new_skill"] = new_skill
    rec.set_routing(routing)
    rec.set_status(status)
    if superseded_by is not None:
        rec.set_superseded_by(superseded_by)
    bucket_dir = bucket_dir_for_scope(env.ledger, scope, project_path=project_path)
    if scope == "project":
        ensure_project_meta(bucket_dir, project_path)
    resolved = bucket_dir / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    rec.write(resolved / f"{rec.id}.md")
    if scope == "user" and destination == "claude-md" and status == "routed":
        _sync_user_claude_md(env)
    return rec


def _sync_user_claude_md(env) -> None:
    """A hand-authored ``resolved/*.md`` record (this file's own
    ``_write_routed``) never runs through the real ``route`` apply step,
    so ``env.user_claude_md`` on disk would otherwise still hold ONLY the
    hand-authored preamble while the bucket already lists the record as
    routed — exactly the split-source-of-truth a real fixture never has.
    Re-derives the compiled section from every ``routed``,
    non-superseded, ``claude-md``-destined user-scope record on disk and
    writes it into the target, mirroring the real apply step so
    ``file_words``/``managed_share`` see the same state a production
    fixture would."""
    from self_learn.compilers import compile_managed_text

    if not env.user_claude_md.is_file():
        return
    resolved_dir = env.ledger / "user" / "resolved"
    records: list[Record] = []
    if resolved_dir.is_dir():
        for path in sorted(resolved_dir.glob("lrn-*.md")):
            try:
                rec = Record.from_path(path)
            except Exception:
                continue
            if (
                rec.status == "routed"
                and rec.superseded_by is None
                and (rec.routing or {}).get("destination") == "claude-md"
            ):
                records.append(rec)
    text = env.user_claude_md.read_text(encoding="utf-8")
    result = compile_managed_text(text, records)
    env.user_claude_md.write_text(result.text, encoding="utf-8")


def _add_project_host(env, path: Path) -> None:
    """Appends one more ``- path: <path>`` entry to the sandbox's
    ``hosts.yaml`` (``make_env`` already writes one for ``env.host``) —
    hand-appended, matching that file's exact format, never a second
    ``host add`` invocation this unit doesn't need."""
    hosts_yaml = env.ledger / "hosts.yaml"
    text = hosts_yaml.read_text(encoding="utf-8")
    text += f"  - path: {path}\n"
    hosts_yaml.write_text(text, encoding="utf-8")


def _seed_index_skill(env, name: str, n_words: int, *, tier: str = "strict") -> Path:
    """One skill directory in the SESSION INDEX (``~/.claude/skills``,
    never ``skills_root``) with an ``n_words``-word description at the
    requested extraction tier."""
    d = env.skills_index / name
    d.mkdir(parents=True, exist_ok=True)
    desc = _n_words(n_words, prefix=f"{name}w")
    if tier == "strict":
        text = f"---\nname: {name}\ndescription: {desc}\n---\nbody\n"
    elif tier == "lenient":
        # An embedded ": " breaks ruamel's safe-load of the leading block
        # (empirically verified) but the lenient regex line-scan still
        # recovers it verbatim.
        text = f"---\nname: {name}\ndescription: Use this: {desc}\n---\nbody\n"
    elif tier == "unreadable":
        text = "just prose, no frontmatter block at all\n"
    else:
        raise ValueError(tier)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d


def _lenient_words(n_words: int, name: str) -> int:
    """``_seed_index_skill``'s lenient description's real word count —
    ``"Use this: " + n_words tokens`` = ``n_words + 2`` (``Use``, ``this:``)."""
    return n_words + 2


def _crowding_pool(env, n: int = 45, *, scope: str = "skill:s") -> None:
    """``n`` pending filler records with pairwise-disjoint single-token
    vocabulary — the global-pool denominator T3's fixture rule (B3)
    requires so a (+) fixture's shared rare tokens don't collapse to a
    near-zero IDF score."""
    for i in range(n):
        rec = Record.create(
            type="knowledge", scope=scope, source="teach",
            fact=f"unrelatedfillertopic{i:04d}", record_id=f"lrn-fa{i:06d}",
        )
        create_record(env.ledger, rec)


# ===================================================================== #
# T2 -- budget
# ===================================================================== #


class TestT2Budget:
    def test_t2_1_rows_and_totals(self, env):
        preamble = _n_words(200)
        _set_user_claude_md(env, preamble)
        recs = [
            _write_routed(
                env, scope="user", record_id=f"lrn-aa00000{i}",
                destination="claude-md", routed_at=days_ago_ts(1),
                fact=f"fact number {i} here",
            )
            for i in range(3)
        ]
        from self_learn.compilers import compile_managed_text

        # Ground truth from the compiler itself, against the PRISTINE
        # preamble (never the post-sync file, which already carries the
        # marker pair) -- `expected.text` is the whole file a real route
        # would produce, markers included (T2.1: "not a recomputation").
        expected = compile_managed_text(preamble, recs)

        budget = report.context_budget(env.ledger, TODAY)["budget"]
        row = next(r for r in budget["surfaces"] if r["surface"] == "user-claude-md")
        assert row["state"] == "ok"
        assert row["file_words"] == len(expected.text.split())
        assert row["managed_words"] == expected.word_count
        assert row["managed_entries"] == expected.entry_count
        assert row["managed_share"] == round(
            expected.word_count / len(expected.text.split()), 3
        )

    def test_t2_2_quiet_below_advisory(self, env):
        below = report.SESSION_BASELINE_WORDS_ADVISORY - 1
        _set_user_claude_md(env, _n_words(below))
        budget = report.context_budget(env.ledger, TODAY)["budget"]
        assert budget["flagged"] is False
        assert budget["session_baseline_words"] == below

    def test_t2_3_trips_on_the_largest_baseline_row_only(self, env):
        at = report.SESSION_BASELINE_WORDS_ADVISORY
        _set_user_claude_md(env, _n_words(at))
        _seed_index_skill(env, "s1", 10)
        _add_project_host(env, env.host)

        budget = report.context_budget(env.ledger, TODAY)["budget"]
        assert budget["flagged"] is True
        flagged_rows = [r for r in budget["surfaces"] if r.get("flagged")]
        assert len(flagged_rows) == 1
        assert flagged_rows[0]["surface"] == "user-claude-md"
        assert all(r["surface"] != "project-claude-md" for r in flagged_rows)

    def test_t2_4_blindness_unreadable_target(self, env):
        text = _n_words(500)
        _set_user_claude_md(env, text)
        healthy = report.context_budget(env.ledger, TODAY)["budget"]
        healthy_row = next(
            r for r in healthy["surfaces"] if r["surface"] == "user-claude-md"
        )
        assert healthy_row["state"] == "ok"

        os.chmod(env.user_claude_md, 0o000)
        try:
            blind = report.context_budget(env.ledger, TODAY)["budget"]
        finally:
            os.chmod(env.user_claude_md, 0o644)

        blind_row = next(
            r for r in blind["surfaces"] if r["surface"] == "user-claude-md"
        )
        assert blind_row["state"] == "unreadable"
        assert blind_row["file_words"] is None
        assert blind["surfaces_unmeasured"] == 1
        assert blind["totals_are_lower_bound"] is True
        # the 500 words vanish from the total, never read as 0
        assert (
            healthy["session_baseline_words"] - blind["session_baseline_words"]
            == healthy_row["file_words"]
        )

    def test_t2_5_blindness_unregistered_project_never_omitted(self, env):
        # make_env already registers exactly ONE project (env.host) --
        # break IT (moved/removed) rather than adding a second entry, so
        # the fixture carries exactly one project row, and it is the
        # not-registered one.
        import shutil

        shutil.rmtree(env.host)
        _set_user_claude_md(env, _n_words(5))

        budget = report.context_budget(env.ledger, TODAY)["budget"]
        project_rows = [r for r in budget["surfaces"] if r["surface"] == "project-claude-md"]
        assert len(project_rows) == 1
        assert project_rows[0]["state"] == "not-registered"
        assert project_rows[0]["file_words"] is None

    def test_t2_6_user_key_is_the_literal_tilde_form(self, env):
        _set_user_claude_md(env, _n_words(5))
        budget = report.context_budget(env.ledger, TODAY)["budget"]
        row = next(r for r in budget["surfaces"] if r["surface"] == "user-claude-md")
        assert row["key"] == "~/.claude/CLAUDE.md"
        for r in budget["surfaces"]:
            assert "/home/" not in r["key"]
            assert "/Users/" not in r["key"]

    def test_t2_7_project_key_is_an_eight_hex_digest(self, env):
        import re

        _add_project_host(env, env.host)
        budget = report.context_budget(env.ledger, TODAY)["budget"]
        row = next(r for r in budget["surfaces"] if r["surface"] == "project-claude-md")
        assert re.fullmatch(r"[0-9a-f]{8}", row["key"])

    def test_t2_8_skill_index_row(self, env):
        _seed_index_skill(env, "aaa", 10)
        _seed_index_skill(env, "bbb", 20)
        _seed_index_skill(env, "ccc", 30)
        row = report._skill_description_row(env.ledger)
        assert row["file_words"] == 60
        words = [s["description_words"] for s in row["skills"]]
        assert words == sorted(words, reverse=True)
        assert row["managed_words"] is None

    def test_t2_8a_reads_the_session_index_not_skills_root(self, env):
        # session index: 3 skills totalling 60 words
        _seed_index_skill(env, "aaa", 10)
        _seed_index_skill(env, "bbb", 20)
        _seed_index_skill(env, "ccc", 30)
        # skills_root (env.host, registered separately) has ONE skill of 5
        # words -- a build that globbed skills_root instead reports 5.
        other = env.host / "plugins" / "other-plugin" / "skills" / "other"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text(
            f"---\nname: other\ndescription: {_n_words(5)}\n---\nbody\n",
            encoding="utf-8",
        )
        row = report._skill_description_row(env.ledger)
        assert row["file_words"] == 60

    def test_t2_8b_symlinked_index_entries_dedup_on_resolved_path(self, env):
        real_dir = env.skills_index / "real-skill"
        real_dir.mkdir(parents=True)
        (real_dir / "SKILL.md").write_text(
            f"---\nname: real-skill\ndescription: {_n_words(12)}\n---\nbody\n",
            encoding="utf-8",
        )
        alias_dir = env.skills_index / "aliased-skill"
        alias_dir.symlink_to(real_dir, target_is_directory=True)

        row = report._skill_description_row(env.ledger)
        assert len(row["skills"]) == 1
        assert row["skills_total"] == 1
        assert row["file_words"] == 12

    def test_t2_unenumerable_index_is_unmeasured_not_a_measured_zero(self, env):
        """MAJOR 3 (u-cap code gate r1): an index dir that IS a directory
        but cannot be LISTED (permissions -- proven with chmod 000) must
        not fall through to state "ok" / file_words 0. That reads as a
        measured, empty surface (contributes 0 to
        session_baseline_words, `flagged` reads clean) when the true
        state is "we could not see this surface at all" (§4.0.4:
        unmeasurable is never zero -- the exact fail-open class the
        ledger has recorded three times: lrn-ea833a5b, lrn-6d21607e,
        lrn-fc481dcb)."""
        if os.name != "posix" or os.getuid() == 0:
            pytest.skip("chmod 000 has no effect for root")
        _seed_index_skill(env, "aaa", 10)
        env.skills_index.chmod(0)
        try:
            row = report._skill_description_row(env.ledger)
        finally:
            env.skills_index.chmod(0o755)

        assert row["state"] != "ok"
        assert row["file_words"] is None
        assert row["file_words"] != 0  # the positive control this finding names

        _set_user_claude_md(env, _n_words(5))
        # re-run through the FULL signal (not just the row helper): the
        # unreadable row must not be silently absorbed into a clean
        # session_baseline_words total either.
        env.skills_index.chmod(0)
        try:
            budget = report.context_budget(env.ledger, TODAY)["budget"]
        finally:
            env.skills_index.chmod(0o755)
        assert budget["surfaces_unmeasured"] > 0
        assert budget["totals_are_lower_bound"] is True

    def test_t2_9_two_tier_extraction(self, env):
        _seed_index_skill(env, "strictskill", 5, tier="strict")
        _seed_index_skill(env, "lenientskill", 6, tier="lenient")
        _seed_index_skill(env, "brokenskill", 0, tier="unreadable")

        row = report._skill_description_row(env.ledger)
        assert row["skills_strict"] == 1
        assert row["skills_lenient"] == 1
        assert row["skills_unreadable"] == 1
        lenient = next(s for s in row["skills"] if s["name"] == "lenientskill")
        assert lenient["extraction"] == "lenient"
        assert lenient["description_words"] == _lenient_words(6, "lenientskillw")
        assert lenient["description_words"] > 0
        assert row["file_words"] >= lenient["description_words"]

        _set_user_claude_md(env, _n_words(5))
        budget = report.context_budget(env.ledger, TODAY)["budget"]
        assert budget["totals_are_lower_bound"] is True

    def test_t2_9_lenient_without_unreadable_is_not_a_lower_bound(self, env):
        _seed_index_skill(env, "strictskill", 5, tier="strict")
        _seed_index_skill(env, "lenientskill", 6, tier="lenient")
        _set_user_claude_md(env, _n_words(5))

        budget = report.context_budget(env.ledger, TODAY)["budget"]
        assert budget["totals_are_lower_bound"] is False

    def test_t2_9a_lenient_words_land_in_file_words(self, env):
        """The regression control for the 16% hole: a strict-only
        implementation drops the lenient skill's words entirely."""
        _seed_index_skill(env, "lenientskill", 6, tier="lenient")
        row = report._skill_description_row(env.ledger)
        lenient = row["skills"][0]
        assert lenient["extraction"] == "lenient"
        assert row["file_words"] == lenient["description_words"]
        assert row["file_words"] > 0

    def test_t2_10_tokens_est_is_words_times_1_33(self, env):
        _set_user_claude_md(env, _n_words(1000))
        budget = report.context_budget(env.ledger, TODAY)["budget"]
        row = next(r for r in budget["surfaces"] if r["surface"] == "user-claude-md")
        assert row["file_tokens_est"] == round(1000 * report.TOKENS_PER_WORD_EST)

        payload = report.context_budget(env.ledger, TODAY)
        assert not _contains_key_named(payload, "tokens")

    def test_t2_11_all_blind(self, env):
        # no user CLAUDE.md (default: env fixture never creates one). The
        # env fixture DOES create an empty (but present, hence "ok")
        # skills index, and make_env DOES register env.host as a sound
        # project (hence "ok") -- both must be removed to reach true
        # all-blind: every surface unmeasurable.
        import shutil

        shutil.rmtree(env.skills_index)
        shutil.rmtree(env.host)
        budget = report.context_budget(env.ledger, TODAY)["budget"]
        assert budget["surfaces_measured"] == 0
        assert budget["session_baseline_words"] is None
        assert budget["session_max_words"] is None
        assert budget["flagged"] is None
        assert budget["flagged"] is not False

    def test_t2_12_baseline_never_absorbs_project_words(self, env):
        host2 = env.host.parent / "host2"
        host3 = env.host.parent / "host3"
        init_repo(host2)
        init_repo(host3)
        (host2 / "CLAUDE.md").write_text(_n_words(2000), encoding="utf-8")
        (host3 / "CLAUDE.md").write_text(_n_words(9000), encoding="utf-8")
        git(host2, "add", "-A")
        git(host2, "commit", "-q", "-m", "seed")
        git(host3, "add", "-A")
        git(host3, "commit", "-q", "-m", "seed")
        _add_project_host(env, host2)
        _add_project_host(env, host3)
        # env.host is already registered by make_env with a 3-word CLAUDE.md
        # seed ("# host project\n\nAuthored context stays put.\n" -> not
        # exactly 1000, so give the baseline an exact, known number instead:
        _set_user_claude_md(env, _n_words(1000))

        budget = report.context_budget(env.ledger, TODAY)["budget"]
        assert budget["session_baseline_words"] == 1000
        assert budget["largest_project_words"] == 9000
        assert budget["session_max_words"] == 10000
        # all_hosts_words sums EVERY project row too (env.host's own seed +
        # host2 + host3) -- assert it is strictly larger than session_max,
        # proving it is not what flagging reads.
        assert budget["all_hosts_words"] > budget["session_max_words"]


def _contains_key_named(obj, name: str) -> bool:
    if isinstance(obj, dict):
        if any(k == name for k in obj):
            return True
        return any(_contains_key_named(v, name) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_key_named(v, name) for v in obj)
    return False


# ===================================================================== #
# T3 -- crowding
# ===================================================================== #


class TestT3Crowding:
    def test_t3_1_rare_shared_tokens_trip_crowding(self, env):
        _crowding_pool(env, 45)
        _set_user_claude_md(env, "# canon\n")
        a = _write_routed(
            env, scope="user", record_id="lrn-cc000001", destination="claude-md",
            routed_at=days_ago_ts(1),
            fact="wombat crenellated turnip glissando alpha",
        )
        b = _write_routed(
            env, scope="user", record_id="lrn-cc000002", destination="claude-md",
            routed_at=days_ago_ts(1),
            fact="wombat crenellated turnip glissando beta",
        )
        crowding = report.context_budget(env.ledger, TODAY)["crowding"]
        row = next(r for r in crowding["surfaces"] if r["surface"] == "user-claude-md")
        assert row["pairs"], "expected at least one scored pair"
        pair = row["pairs"][0]
        assert pair["score"] >= worker.CANDIDATE_SCORE_FLOOR
        assert {pair["a"], pair["b"]} == {a.id, b.id}
        assert crowding["flagged"] is True

    def test_t3_1a_corpus_control_compile_set_alone_scores_zero(self, env, monkeypatch):
        """The B3 degeneracy control: forcing the corpus down to the
        compile set (n_docs == 2, both records share every token) makes
        every shared token's IDF collapse to log(1) == 0."""
        _set_user_claude_md(env, "# canon\n")
        _write_routed(
            env, scope="user", record_id="lrn-cc000001", destination="claude-md",
            routed_at=days_ago_ts(1), fact="wombat crenellated turnip glissando alpha",
        )
        _write_routed(
            env, scope="user", record_id="lrn-cc000002", destination="claude-md",
            routed_at=days_ago_ts(1), fact="wombat crenellated turnip glissando beta",
        )
        # No pool filler records at all -- the global pool degenerates to
        # exactly the two records above (n_docs == 2, df == 2 for every
        # shared token).
        crowding = report.context_budget(env.ledger, TODAY)["crowding"]
        row = next(r for r in crowding["surfaces"] if r["surface"] == "user-claude-md")
        assert row["pairs"] == []
        assert crowding["corpus_docs"] == 2

    def test_t3_2_disjoint_vocabulary_is_quiet(self, env):
        _crowding_pool(env, 45)
        _set_user_claude_md(env, "# canon\n")
        _write_routed(
            env, scope="user", record_id="lrn-dd000001", destination="claude-md",
            routed_at=days_ago_ts(1), fact="alpha bravo charlie",
        )
        _write_routed(
            env, scope="user", record_id="lrn-dd000002", destination="claude-md",
            routed_at=days_ago_ts(1), fact="delta echo foxtrot",
        )
        crowding = report.context_budget(env.ledger, TODAY)["crowding"]
        row = next(r for r in crowding["surfaces"] if r["surface"] == "user-claude-md")
        assert row["pairs"] == []
        assert row["pairs_total"] == 0
        assert row["state"] == "ok"
        assert crowding["flagged"] is False

    def test_t3_3_too_few_entries(self, env):
        _set_user_claude_md(env, "# canon\n")
        _write_routed(
            env, scope="user", record_id="lrn-ee000001", destination="claude-md",
            routed_at=days_ago_ts(1), fact="solo entry",
        )
        crowding = report.context_budget(env.ledger, TODAY)["crowding"]
        row = next(r for r in crowding["surfaces"] if r["surface"] == "user-claude-md")
        assert row["state"] == "too-few-entries"
        assert row["pairs_total"] is None

    def test_t3_3a_all_blind(self, env):
        # make_env registers env.host as a sound project with its own
        # seeded (unrouted) CLAUDE.md -- that alone counts as MEASURED
        # ("too-few-entries" on zero routed records still counts). Remove
        # it to reach a genuinely unmeasurable crowding signal.
        import shutil

        shutil.rmtree(env.host)
        crowding = report.context_budget(env.ledger, TODAY)["crowding"]
        assert crowding["surfaces_measured"] == 0
        assert crowding["flagged"] is None
        assert crowding["flagged"] is not False

    def test_t3_4_scorer_identity_monkeypatch_pair_similarity(self, env, monkeypatch):
        _set_user_claude_md(env, "# canon\n")
        for i in range(3):
            _write_routed(
                env, scope="user", record_id=f"lrn-ff00000{i}", destination="claude-md",
                routed_at=days_ago_ts(1), fact=f"utterly distinct token set {i}",
            )
        monkeypatch.setattr(worker, "pair_similarity", lambda *a, **kw: 1.0)
        crowding = report.context_budget(env.ledger, TODAY)["crowding"]
        row = next(r for r in crowding["surfaces"] if r["surface"] == "user-claude-md")
        # 3 records -> C(3,2) == 3 candidate pairs, all emitted at score 1.0
        assert row["pairs_total"] == 3
        assert all(p["score"] == 1.0 for p in row["pairs"])

    def test_t3_4a_cluster_candidates_unaffected_by_the_factoring(self, env):
        """N1 (u-cap code gate r1): the r1 version of this test never
        called `cluster_candidates` at all -- it called `pair_similarity`
        twice and asserted determinism, which is T3.4's job, not T3.4a's.
        T3.4a guards the "one definition" refactor from changing MINER
        behavior: a DIRECT call over a real pending pool must still
        return the token-sharing sibling as a candidate and exclude the
        record with no shared tokens -- exactly what it did before
        `pair_similarity` was factored out of its closures (§4.3.2)."""
        from self_learn.ledger import discover_buckets
        from self_learn.ledger_ops import queue

        a = make_behavior(
            scope="skill:s", record_id="lrn-3a000001",
            trigger="platypus obelisk narwhal alpha shared",
        )
        b = make_behavior(
            scope="skill:s", record_id="lrn-3a000002",
            trigger="platypus obelisk narwhal beta shared",
        )
        isolated = make_behavior(
            scope="skill:s", record_id="lrn-3a000003",
            trigger="utterly disjoint vocabulary here",
        )
        for record in (a, b, isolated):
            create_record(env.ledger, record)

        (bucket,) = [
            bk for bk in discover_buckets(env.ledger)
            if bk.scope == "skill" and bk.name == "s"
        ]
        entries = {e.record.id: e for e in queue(bucket, include_deferred=True)}
        batch = [entries[a.id], entries[isolated.id]]

        result = worker.cluster_candidates(env.ledger, batch)

        a_candidates = result[a.id]
        assert a_candidates, "expected the token-sharing sibling as a candidate"
        assert a_candidates[0].record_id == b.id
        assert a_candidates[0].score >= worker.CANDIDATE_SCORE_FLOOR
        assert result[isolated.id] == []

    def test_t3_5_score_floor_and_pairs_cap(self, env):
        _crowding_pool(env, 45)
        _set_user_claude_md(env, "# canon\n")
        # 7 entries -> C(7,2) == 21 pairs, but every entry shares the SAME
        # rare tokens with every other -> all 21 clear the floor.
        for i in range(7):
            _write_routed(
                env, scope="user", record_id=f"lrn-0500000{i}", destination="claude-md",
                routed_at=days_ago_ts(1),
                fact=f"quokka jubilee marmoset entry{i}",
            )
        crowding = report.context_budget(env.ledger, TODAY)["crowding"]
        assert crowding["score_floor"] == worker.CANDIDATE_SCORE_FLOOR
        row = next(r for r in crowding["surfaces"] if r["surface"] == "user-claude-md")
        assert len(row["pairs"]) <= 5
        assert row["pairs_total"] == 21
        assert crowding["corpus_docs"] == 45 + 7

    def test_t3_6_no_merge_offer_or_collapse_string_anywhere(self, env):
        _crowding_pool(env, 45)
        _set_user_claude_md(env, "# canon\n")
        _write_routed(
            env, scope="user", record_id="lrn-06000001", destination="claude-md",
            routed_at=days_ago_ts(1), fact="platypus obelisk narwhal alpha",
        )
        _write_routed(
            env, scope="user", record_id="lrn-06000002", destination="claude-md",
            routed_at=days_ago_ts(1), fact="platypus obelisk narwhal beta",
        )
        payload = report.context_budget(env.ledger, TODAY)
        assert not _contains_key_named(payload, "merge_offer")
        assert not _contains_key_named(payload, "cluster_id")
        assert not _contains_string(payload, "--collapse")
        # positive control: the same helper DOES find it in a fixture that
        # deliberately contains the string.
        assert _contains_string({"x": "route --collapse cluster-1"}, "--collapse")

    def test_t3_7_supersedes_never_appears_twice_in_one_command(self):
        """MAJOR 5 (u-cap code gate r1): the r1 version of this test
        built its OWN string in-body and read no file -- it could not
        have caught a broken card; `commands/review.md` could ship the
        repeated-flag silent half-merge form and it would stay green.
        T3.7 per spec: "A grep over the spec-derived card text and the
        CLI source asserts the substring --supersedes never appears
        twice in one command string." Reads the REAL card
        (`commands/review.md`) and the REAL CLI source."""
        import re

        review_md = Path(__file__).resolve().parents[2] / "commands" / "review.md"
        assert review_md.is_file(), review_md
        card_text = review_md.read_text(encoding="utf-8")

        # command-shaped chunks: everything inside one pair of backticks
        # that mentions --supersedes -- a command string never spans a
        # markdown paragraph break, so backtick-delimited is the right
        # unit to check arity within.
        chunks = re.findall(r"`([^`\n]*--supersedes[^`\n]*)`", card_text)
        assert chunks, "no --supersedes command example found in review.md"
        for chunk in chunks:
            assert chunk.count("--supersedes") == 1, (
                f"--supersedes repeated in one command: {chunk!r}"
            )

        src_root = Path(__file__).resolve().parent.parent / "src"
        for path in sorted(src_root.rglob("*.py")):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                assert line.count("--supersedes") <= 1, (
                    f"{path}:{lineno} repeats --supersedes in one line: {line!r}"
                )

        # positive control: the same regex+count check, run against a
        # fixture string that DOES repeat the flag, must catch it --
        # otherwise a mis-scoped chunk boundary would pass vacuously.
        decoy = "`self-learn teach --supersedes lrn-aaaa --supersedes lrn-bbbb`"
        decoy_chunks = re.findall(r"`([^`\n]*--supersedes[^`\n]*)`", decoy)
        assert decoy_chunks and decoy_chunks[0].count("--supersedes") == 2


def _contains_string(obj, needle: str) -> bool:
    if isinstance(obj, str):
        return needle in obj
    if isinstance(obj, dict):
        return any(_contains_string(v, needle) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_string(v, needle) for v in obj)
    return False


# ===================================================================== #
# T4 -- composition
# ===================================================================== #


class TestT4Composition:
    def test_t4_1_reconstructed_delta(self, env):
        preamble = _n_words(100)
        _set_user_claude_md(env, preamble)
        old = [
            _write_routed(
                env, scope="user", record_id=f"lrn-0700000{i}", destination="claude-md",
                routed_at=days_ago_ts(60), fact=f"old fact {i}",
            )
            for i in range(4)
        ]
        new = [
            _write_routed(
                env, scope="user", record_id=f"lrn-0800000{i}", destination="claude-md",
                routed_at=days_ago_ts(5), fact=f"new fact {i}",
            )
            for i in range(4)
        ]
        from self_learn.compilers import compile_managed_text

        # Ground truth against the PRISTINE preamble, not the post-sync
        # file (which already carries the marker pair).
        old_only = compile_managed_text(preamble, old)
        both = compile_managed_text(preamble, old + new)

        comp = report.context_budget(env.ledger, TODAY)["composition"]
        row = next(r for r in comp["surfaces"] if r["surface"] == "user-claude-md")
        assert row["managed_words_30d_ago"] == old_only.word_count
        assert row["managed_words_delta_30d"] == both.word_count - old_only.word_count
        file_words = len(both.text.split())
        expected_pp = round(100 * row["managed_words_delta_30d"] / file_words, 1)
        assert row["managed_share_growth_30d_pp"] == expected_pp
        assert comp["past_is_lower_bound"] is True

    def test_t4_2_share_30d_ago_is_always_null(self, env):
        _set_user_claude_md(env, _n_words(5000))
        for i in range(6):
            _write_routed(
                env, scope="user", record_id=f"lrn-0900000{i}", destination="claude-md",
                routed_at=days_ago_ts(1), fact=f"lots of words here for entry {i} " * 5,
            )
        comp = report.context_budget(env.ledger, TODAY)["composition"]
        for row in comp["surfaces"]:
            assert row["managed_share_30d_ago"] is None

    def test_t4_3_share_trigger(self, env):
        _set_user_claude_md(env, "small preamble\n")
        for i in range(20):
            _write_routed(
                env, scope="user", record_id=f"lrn-0a{i:06d}", destination="claude-md",
                routed_at=days_ago_ts(1), fact=" ".join(f"tok{i}_{j}" for j in range(20)),
            )
        comp = report.context_budget(env.ledger, TODAY)["composition"]
        row = next(r for r in comp["surfaces"] if r["surface"] == "user-claude-md")
        assert row["managed_share"] >= report.COMPOSITION_SHARE_ADVISORY
        assert row["flagged"] is True
        assert "share" in row["flagged_by"]

    def test_t4_4_growth_trigger_independent_of_share(self, env):
        # Large hand preamble keeps share low, but ALL managed words landed
        # inside the 30d window (nothing routed 30+ days ago), so growth pp
        # == share's own contribution and can cross its OWN threshold while
        # share stays below its.
        _set_user_claude_md(env, _n_words(1000))
        for i in range(6):
            _write_routed(
                env, scope="user", record_id=f"lrn-0b00000{i}", destination="claude-md",
                routed_at=days_ago_ts(1), fact=" ".join(f"g{i}_{j}" for j in range(30)),
            )
        comp = report.context_budget(env.ledger, TODAY)["composition"]
        row = next(r for r in comp["surfaces"] if r["surface"] == "user-claude-md")
        assert row["managed_share"] < report.COMPOSITION_SHARE_ADVISORY
        assert row["managed_share_growth_30d_pp"] >= report.COMPOSITION_GROWTH_PP_ADVISORY
        assert row["flagged"] is True
        assert row["flagged_by"] == ["growth"]

    def test_t4_5_quiet(self, env):
        _set_user_claude_md(env, _n_words(4000))
        old = [
            _write_routed(
                env, scope="user", record_id=f"lrn-0c00000{i}", destination="claude-md",
                routed_at=days_ago_ts(60), fact=f"stale fact {i}",
            )
            for i in range(3)
        ]
        comp = report.context_budget(env.ledger, TODAY)["composition"]
        row = next(r for r in comp["surfaces"] if r["surface"] == "user-claude-md")
        assert row["flagged"] is False
        assert row["flagged_by"] == []
        assert row["managed_words_delta_30d"] == 0

    def test_t4_6_kind_mix(self, env):
        _set_user_claude_md(env, _n_words(50))
        _write_routed(
            env, scope="user", record_id="lrn-0d000001", destination="claude-md",
            routed_at=days_ago_ts(1), rtype="behavior", kind="anti-pattern",
            trigger="about to do X", instruction="stop and do Y",
        )
        _write_routed(
            env, scope="user", record_id="lrn-0d000002", destination="claude-md",
            routed_at=days_ago_ts(1), rtype="behavior", kind="surface-rule",
            trigger="about to do Z", instruction="check W first",
        )
        _write_routed(
            env, scope="user", record_id="lrn-0d000003", destination="claude-md",
            routed_at=days_ago_ts(1), rtype="behavior", kind="reasoning-pattern",
            trigger="about to reason", instruction="widen the frame",
        )
        _write_routed(
            env, scope="user", record_id="lrn-0d000004", destination="claude-md",
            routed_at=days_ago_ts(1), rtype="knowledge", fact="a plain fact",
        )
        comp = report.context_budget(env.ledger, TODAY)["composition"]
        row = next(r for r in comp["surfaces"] if r["surface"] == "user-claude-md")
        assert row["kind_mix"] == {
            "anti-pattern": 1, "surface-rule": 1, "reasoning-pattern": 1,
            "unclassified": 1,
        }
        assert row["caution_share"] == round(1 / 3, 3)

    def test_t4_7_caution_trigger(self, env):
        _set_user_claude_md(env, _n_words(20))
        for i in range(5):
            _write_routed(
                env, scope="user", record_id=f"lrn-0e00000{i}", destination="claude-md",
                routed_at=days_ago_ts(1), rtype="behavior", kind="anti-pattern",
                trigger=f"trigger {i}", instruction=f"instruction {i}",
            )
        comp = report.context_budget(env.ledger, TODAY)["composition"]
        row = next(r for r in comp["surfaces"] if r["surface"] == "user-claude-md")
        assert row["caution_share"] == 1.0
        assert "caution" in row["flagged_by"]

    def test_t4_8_blindness_unreadable_file(self, env):
        _set_user_claude_md(env, _n_words(5))
        os.chmod(env.user_claude_md, 0o000)
        try:
            comp = report.context_budget(env.ledger, TODAY)["composition"]
        finally:
            os.chmod(env.user_claude_md, 0o644)
        row = next(r for r in comp["surfaces"] if r["surface"] == "user-claude-md")
        assert row["state"] == "unreadable"
        for key in (
            "managed_share", "managed_words", "managed_words_30d_ago",
            "managed_words_delta_30d", "managed_share_growth_30d_pp",
            "kind_mix", "caution_share",
        ):
            assert row[key] is None
        assert row["caution_share"] is not 0.0  # noqa: F632 -- literal-identity check is the point

    def test_t4_9_word_count_parity_across_payload_sites(self, env, capsys):
        _set_user_claude_md(env, _n_words(50))
        for i in range(4):
            _write_routed(
                env, scope="user", record_id=f"lrn-0f00000{i}", destination="claude-md",
                routed_at=days_ago_ts(1), fact=f"parity check fact {i}",
            )
        payload = report.context_budget(env.ledger, TODAY)
        budget_row = next(
            r for r in payload["budget"]["surfaces"] if r["surface"] == "user-claude-md"
        )
        comp_row = next(
            r for r in payload["composition"]["surfaces"] if r["surface"] == "user-claude-md"
        )
        assert budget_row["managed_words"] == comp_row["managed_words"]

        # a PENDING user-scope record so `list` (pending-queue only) has
        # something to show; its surface_fill reflects the compile SET
        # (already-routed records), independent of the displayed record.
        pending = Record.create(
            type="knowledge", scope="user", source="teach",
            fact="a still-pending lesson", record_id="lrn-0f000099",
        )
        create_record(env.ledger, pending)

        rc = cli.main(["list", "--json", "--surface-fill"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        fills = [i["surface_fill"]["claude-md"]["words"] for i in out if "surface_fill" in i]
        assert fills and all(w == comp_row["managed_words"] for w in fills)


# ===================================================================== #
# T5 -- growth
# ===================================================================== #


class TestT5Growth:
    def _make_skill(self, env, name: str, desc_words: int) -> None:
        d = env.host / "plugins" / f"{name}-plugin" / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {_n_words(desc_words, prefix=name)}\n---\nbody\n",
            encoding="utf-8",
        )

    def test_t5_1_growth_trip(self, env):
        _set_user_claude_md(env, _n_words(10))
        for i in range(3):
            _write_routed(
                env, scope="user", record_id=f"lrn-1000000{i}", destination="claude-md",
                routed_at=days_ago_ts(1),
                fact=" ".join(f"m{i}_{j}" for j in range(167)),  # ~500 words / 3
            )
        self._make_skill(env, "skillone", 150)
        self._make_skill(env, "skilltwo", 120)
        _write_routed(
            env, scope="skill:skillone", record_id="lrn-10000010",
            destination="new-skill", new_skill="skillone", routed_at=days_ago_ts(1),
            fact="landed in skillone",
        )
        _write_routed(
            env, scope="skill:skilltwo", record_id="lrn-10000011",
            destination="new-skill", new_skill="skilltwo", routed_at=days_ago_ts(1),
            fact="landed in skilltwo",
        )
        growth = report.context_budget(env.ledger, TODAY)["growth"]
        assert growth["new_skill_description_words_added_30d"] == 150 + 120
        assert growth["always_on_words_added_30d"] == (
            growth["managed_words_added_30d"] + 270
        )
        assert growth["always_on_words_added_30d"] >= report.GROWTH_ALARM_WORDS_PER_30D
        assert growth["flagged"] is True

    def test_t5_2_boundary_quiet_at_exactly_below(self, env):
        _set_user_claude_md(env, _n_words(10))
        _write_routed(
            env, scope="user", record_id="lrn-11000001", destination="claude-md",
            routed_at=days_ago_ts(1), fact=" ".join(f"w{j}" for j in range(698)),
        )
        growth = report.context_budget(env.ledger, TODAY)["growth"]
        assert growth["always_on_words_added_30d"] == 700
        assert growth["flagged"] is False

    def test_t5_3_doubling_denominator_is_the_baseline(self, env):
        from self_learn.compilers import compile_managed_text

        preamble = _n_words(5940)
        _set_user_claude_md(env, preamble)
        fact = " ".join(f"w{j}" for j in range(598))
        rec = _write_routed(
            env, scope="user", record_id="lrn-12000001", destination="claude-md",
            routed_at=days_ago_ts(1), fact=fact,
        )
        expected = compile_managed_text(preamble, [rec])
        expected_file_words = len(expected.text.split())

        growth = report.context_budget(env.ledger, TODAY)["growth"]
        assert growth["session_baseline_words"] == expected_file_words
        assert growth["always_on_words_added_30d"] == expected.word_count
        expected_doubling = round(30 * expected_file_words / expected.word_count, 1)
        assert growth["doubling_days_est"] == expected_doubling

        host2 = env.host.parent / "host2-t5-3"
        init_repo(host2)
        (host2 / "CLAUDE.md").write_text(_n_words(9000), encoding="utf-8")
        git(host2, "add", "-A")
        git(host2, "commit", "-q", "-m", "seed")
        _add_project_host(env, host2)

        growth2 = report.context_budget(env.ledger, TODAY)["growth"]
        assert growth2["doubling_days_est"] == expected_doubling

    def test_t5_4_zero_added_is_null_not_zero(self, env):
        _set_user_claude_md(env, _n_words(10))
        growth = report.context_budget(env.ledger, TODAY)["growth"]
        assert growth["always_on_words_added_30d"] == 0
        assert growth["doubling_days_est"] is None

    def test_t5_5_dedup_on_existing_skill(self, env):
        _set_user_claude_md(env, _n_words(10))
        self._make_skill(env, "sharedskill", 200)
        _write_routed(
            env, scope="skill:sharedskill", record_id="lrn-13000001",
            destination="new-skill", new_skill="sharedskill", routed_at=days_ago_ts(2),
            fact="first lesson",
        )
        _write_routed(
            env, scope="skill:sharedskill", record_id="lrn-13000002",
            destination="skill-md", routed_at=days_ago_ts(1),
            fact="second lesson, same skill, not a NEW skill route",
        )
        # a SECOND new-skill route into the SAME already-existing skill:
        _write_routed(
            env, scope="skill:sharedskill", record_id="lrn-13000003",
            destination="new-skill", new_skill="sharedskill", routed_at=days_ago_ts(1),
            fact="third lesson",
        )
        growth = report.context_budget(env.ledger, TODAY)["growth"]
        assert growth["new_skill_routes_30d"] == 2
        assert growth["new_skill_description_words_added_30d"] == 200

    def test_t5_6_deleted_skill_dir_contributes_nothing(self, env):
        _set_user_claude_md(env, _n_words(10))
        _write_routed(
            env, scope="user", record_id="lrn-14000001",
            destination="new-skill", new_skill="ghost-skill", routed_at=days_ago_ts(1),
            fact="lesson into a skill dir that never existed",
        )
        growth = report.context_budget(env.ledger, TODAY)["growth"]
        assert growth["new_skill_description_words_added_30d"] == 0
        assert growth["totals_are_lower_bound"] is True

    def test_t5_7_half_open_window_boundary(self, env):
        window_start = TODAY - timedelta(days=report._REFERENCE_WINDOW_DAYS)
        boundary_ts = f"{window_start.isoformat()}T00:00:00Z"
        _set_user_claude_md(env, _n_words(10))
        self._make_skill(env, "boundaryskill", 90)
        _write_routed(
            env, scope="user", record_id="lrn-15000001", destination="claude-md",
            routed_at=boundary_ts, fact=" ".join(f"b{j}" for j in range(40)),
        )
        _write_routed(
            env, scope="skill:boundaryskill", record_id="lrn-15000002",
            destination="new-skill", new_skill="boundaryskill", routed_at=boundary_ts,
            fact="landed exactly at window_start",
        )
        growth = report.context_budget(env.ledger, TODAY)["growth"]
        # entry_line adds "- " + " *(id)*" -> +2 words over the raw fact.
        assert growth["managed_words_added_30d"] == 42
        assert growth["new_skill_description_words_added_30d"] == 90

        from self_learn.compilers import compile_managed_text

        composition = report.context_budget(env.ledger, TODAY)["composition"]
        row = next(
            r for r in composition["surfaces"] if r["surface"] == "user-claude-md"
        )
        text = env.user_claude_md.read_text(encoding="utf-8")
        past_only = compile_managed_text(text, [])  # nothing STRICTLY before window_start
        assert row["managed_words_30d_ago"] == past_only.word_count == 0


# ===================================================================== #
# T6 -- description soft ceiling / new-skill charging
# ===================================================================== #


class TestT6DescriptionCeiling:
    def test_t6_1_boundary(self, env):
        under = _seed_index_skill(env, "underceil", 80, tier="strict")
        over = _seed_index_skill(env, "overceil", 85, tier="strict")
        row = report._skill_description_row(env.ledger)
        by_name = {s["name"]: s for s in row["skills"]}
        assert by_name["underceil"]["over_soft_max"] is False
        assert by_name["overceil"]["over_soft_max"] is True

    def _seed_marketplace(self, env):
        marketplace = env.host / ".claude-plugin" / "marketplace.json"
        marketplace.parent.mkdir(parents=True, exist_ok=True)
        marketplace.write_text(
            json.dumps({"name": "sandbox-skills", "plugins": []}), encoding="utf-8"
        )
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "marketplace seed")

    def test_t6_2_over_ceiling_route_still_succeeds_byte_identical(self, env):
        self._seed_marketplace(env)
        big_desc = " ".join(f"cw{i}" for i in range(85))
        rec = Record.create(
            type="knowledge", scope="user", source="teach",
            fact=big_desc, record_id="lrn-16000001",
        )
        create_record(env.ledger, rec)
        # NEW_SKILL charging: `scaffold_description` derives its text from
        # the record's own fact -- an 85-word fact makes an 85-word (over
        # the 80-word soft max) scaffolded description.
        result = verbs.route(env.ledger, "lrn-16000001", dest="new-skill:bigdesc-skill")
        assert result.commit_message.endswith("bigdesc-skill")

        skill_md = env.host / "plugins" / "bigdesc-skill" / "skills" / "bigdesc-skill" / "SKILL.md"
        before = skill_md.read_text(encoding="utf-8")
        # a second, unrelated route into the SAME skill must not truncate
        # or otherwise touch the description already on disk.
        rec2 = Record.create(
            type="knowledge", scope="skill:bigdesc-skill", source="teach",
            fact="a second unrelated lesson", record_id="lrn-16000002",
        )
        create_record(env.ledger, rec2)
        verbs.route(env.ledger, "lrn-16000002", dest="skill-md")
        after = skill_md.read_text(encoding="utf-8")
        before_fm = before.split("---")[1]
        after_fm = after.split("---")[1]
        assert before_fm == after_fm

    def test_t6_3_first_new_skill_route_charges_the_description(self, env):
        self._seed_marketplace(env)
        rec = Record.create(
            type="knowledge", scope="user", source="teach",
            fact="a short new skill lesson", record_id="lrn-17000001",
        )
        create_record(env.ledger, rec)
        result = verbs.route(env.ledger, "lrn-17000001", dest="new-skill:freshskill")
        note = result.budget_note()
        assert note is not None
        assert "always-on description words" in note
        assert "+0 always-on words" not in note

    def test_t6_4_second_route_into_same_skill_charges_nothing_more(self, env):
        self._seed_marketplace(env)
        rec = Record.create(
            type="knowledge", scope="user", source="teach",
            fact="first lesson into a fresh skill", record_id="lrn-18000001",
        )
        create_record(env.ledger, rec)
        verbs.route(env.ledger, "lrn-18000001", dest="new-skill:secondskill")
        skill_md = env.host / "plugins" / "secondskill" / "skills" / "secondskill" / "SKILL.md"
        before = skill_md.read_text(encoding="utf-8")

        rec2 = Record.create(
            type="knowledge", scope="skill:secondskill", source="teach",
            fact="second lesson, same skill", record_id="lrn-18000002",
        )
        create_record(env.ledger, rec2)
        result2 = verbs.route(env.ledger, "lrn-18000002", dest="new-skill:secondskill")
        note = result2.budget_note()
        assert note is not None
        assert "+0 always-on words" in note
        after = skill_md.read_text(encoding="utf-8")
        assert before.split("---")[1] == after.split("---")[1]


# ===================================================================== #
# T7 -- conditional.rules_cofire
# ===================================================================== #


class TestT7RulesCofire:
    def _rules_dir(self, env) -> Path:
        _set_user_claude_md(env, "# user conduct\n")
        rules_dir = env.user_claude_md.parent / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        return rules_dir

    def test_t7_1_disjoint_topics_quiet(self, env):
        rules_dir = self._rules_dir(env)
        for ext in "abcdef":
            (rules_dir / f"topic-{ext}.md").write_text(
                f"---\npaths:\n  - '**/*.{ext}'\n---\n", encoding="utf-8"
            )
        rc = report.context_budget(env.ledger, TODAY)["conditional"]["rules_cofire"]
        user_scope = next(s for s in rc["scopes"] if s["scope"] == "user")
        assert user_scope["crowded"] is False
        assert user_scope["max_fanin"] <= 5

    def test_t7_2_intersecting_topics_trip(self, env):
        rules_dir = self._rules_dir(env)
        for i in range(6):
            (rules_dir / f"topic{i}.md").write_text(
                "---\npaths:\n  - '**/*.md'\n---\n", encoding="utf-8"
            )
        rc = report.context_budget(env.ledger, TODAY)["conditional"]["rules_cofire"]
        user_scope = next(s for s in rc["scopes"] if s["scope"] == "user")
        assert user_scope["crowded"] is True
        assert user_scope["max_fanin"] > 5
        assert user_scope["max_fanin_is_upper_bound"] is True

    def test_t7_3_datum_is_rules_cofire_unchanged(self, env, monkeypatch):
        self._rules_dir(env)
        sentinel = {
            "topics": ["sentinel"], "unpathed": [], "pairs": [], "max_fanin": 99,
        }
        monkeypatch.setattr(verbs, "_rules_cofire", lambda rules_dir: dict(sentinel))
        rc = report.context_budget(env.ledger, TODAY)["conditional"]["rules_cofire"]
        user_scope = next(s for s in rc["scopes"] if s["scope"] == "user")
        assert user_scope["topics"] == ["sentinel"]
        assert user_scope["max_fanin"] == 99

    def test_t7_4_escalation_is_gone_from_surface_fill(self, env):
        rules_dir = self._rules_dir(env)
        for i in range(6):
            (rules_dir / f"topic{i}.md").write_text(
                "---\npaths:\n  - '**/*.md'\n---\n", encoding="utf-8"
            )
        result = verbs.surface_fill(
            env.ledger, env.ledger / "user", "user", user_claude_md=env.user_claude_md,
        )
        entry = result["claude-md"]
        assert entry["cofire_crowded"] is True
        assert "over_cap" not in entry
        assert "cap_reason" not in entry

    def test_t7_5_no_rules_dir(self, env):
        _set_user_claude_md(env, "# user conduct\n")
        rc = report.context_budget(env.ledger, TODAY)["conditional"]["rules_cofire"]
        user_scope = next(s for s in rc["scopes"] if s["scope"] == "user")
        assert user_scope["state"] == "absent"
        assert user_scope["topics"] == []
        assert user_scope["max_fanin"] == 0
        assert user_scope["crowded"] is False


# ===================================================================== #
# T8 -- conditional.reference read-rate verdict
# ===================================================================== #


class TestT8ReferenceVerdict:
    def test_t8_1_not_instrumented(self, env):
        v = report.reference_read_verdict(env.ledger, TODAY)
        assert v["read_rate_state"] == "not-instrumented"
        assert v["safe_overflow"] is None

    def test_t8_2_instrumented_zero_enumerable(self, env, tmp_path, monkeypatch):
        claude_dir = tmp_path / "t8-2-claude"
        monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
        _instrument(claude_dir)
        v = report.reference_read_verdict(env.ledger, TODAY)
        assert v["read_rate_state"] == "none-enumerable"
        assert v["safe_overflow"] is None

    def test_t8_3_the_load_bearing_control(self, env, tmp_path, monkeypatch):
        claude_dir = tmp_path / "t8-3-claude"
        monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
        _instrument(claude_dir)

        r1 = _write_routed(
            env, scope="skill:s", record_id="lrn-19000001", destination="reference",
            routed_at=days_ago_ts(10), fact="ref fact one",
        )
        r2 = _write_routed(
            env, scope="skill:s", record_id="lrn-19000002", destination="reference",
            routed_at=days_ago_ts(10), fact="ref fact two",
        )
        r1_with_ref = r1
        r1_with_ref.set_routing({**r1.routing, "reference_file": "README.md"})
        bucket_dir = bucket_dir_for_scope(env.ledger, "skill:s")
        r1_with_ref.write(bucket_dir / "resolved" / f"{r1_with_ref.id}.md")
        r2.set_routing({**r2.routing, "reference_file": "NOTES.md"})
        r2.write(bucket_dir / "resolved" / f"{r2.id}.md")
        refs_dir = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        (refs_dir / "README.md").write_text("x", encoding="utf-8")
        (refs_dir / "NOTES.md").write_text("x", encoding="utf-8")
        # RefTarget.key format (refread.py): "<scope>:<bucket>/references/<relpath>"
        write_tracked_event(
            env.ledger, ts=days_ago_ts(1), ref_target="skill:s/references/README.md",
            scope="skill", bucket="s", subagent=False, session="sess-1",
        )
        write_tracked_event(
            env.ledger, ts=days_ago_ts(1), ref_target="skill:s/references/NOTES.md",
            scope="skill", bucket="s", subagent=False, session="sess-1",
        )
        v = report.reference_read_verdict(env.ledger, TODAY)
        assert v["read_rate_state"] == "ok"
        assert v["safe_overflow"] is True

        monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "t8-3-uninstrumented"))
        v2 = report.reference_read_verdict(env.ledger, TODAY)
        assert v2["read_rate_state"] == "not-instrumented"
        assert v2["safe_overflow"] is None
        assert v2["safe_overflow"] is not True
        assert v2["safe_overflow"] is not False

    def test_t8_4_all_zero_read(self, env, tmp_path, monkeypatch):
        claude_dir = tmp_path / "t8-4-claude"
        monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
        _instrument(claude_dir)
        _write_routed(
            env, scope="skill:s", record_id="lrn-1a000001", destination="reference",
            routed_at=days_ago_ts(10), fact="cold ref",
        )
        v = report.reference_read_verdict(env.ledger, TODAY)
        assert v["targets_total"] >= 1
        assert v["read_rate_state"] == "no-reads-observed"
        assert v["safe_overflow"] is False

    def test_t8_5_partly_cold(self, env, tmp_path, monkeypatch):
        claude_dir = tmp_path / "t8-5-claude"
        monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
        _instrument(claude_dir)
        r1 = _write_routed(
            env, scope="skill:s", record_id="lrn-1b000001", destination="reference",
            routed_at=days_ago_ts(10), fact="read ref",
        )
        r1.set_routing({**r1.routing, "reference_file": "README.md"})
        bucket_dir = bucket_dir_for_scope(env.ledger, "skill:s")
        r1.write(bucket_dir / "resolved" / f"{r1.id}.md")
        refs_dir = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        (refs_dir / "README.md").write_text("x", encoding="utf-8")
        _write_routed(
            env, scope="skill:s", record_id="lrn-1b000002", destination="reference",
            routed_at=days_ago_ts(10), fact="unread ref",
        )
        write_tracked_event(
            env.ledger, ts=days_ago_ts(1), ref_target="skill:s/references/README.md",
            scope="skill", bucket="s", subagent=False, session="sess-1",
        )
        v = report.reference_read_verdict(env.ledger, TODAY)
        assert v["targets_total"] == 2
        assert v["read_rate_state"] == "partly-cold"
        assert v["safe_overflow"] is False

    def test_t8_6_flush_state_propagates_lower_bound(self, env, tmp_path, monkeypatch):
        claude_dir = tmp_path / "t8-6-claude"
        monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
        _instrument(claude_dir)
        v_ok = report.reference_read_verdict(env.ledger, TODAY, flush_state="ok")
        assert v_ok["counts_are_lower_bound"] is False
        v_bad = report.reference_read_verdict(env.ledger, TODAY, flush_state="failed")
        assert v_bad["counts_are_lower_bound"] is True
        assert v_bad["read_rate_state"] == v_ok["read_rate_state"]

    def test_t8_7_why_mapping_covers_every_state(self):
        assert set(report.REFERENCE_READ_RATE_STATES) == {
            "not-instrumented", "none-enumerable", "no-reads-observed",
            "partly-cold", "ok",
        }
        for state in report.REFERENCE_READ_RATE_STATES:
            assert report._REFERENCE_WHY[state]


# ===================================================================== #
# T10 -- the report-only invariant
# ===================================================================== #


class TestT10ReportOnlyInvariant:
    def _build_everything_flagged(self, env, tmp_path, monkeypatch):
        # u-cap code gate r1, MAJOR 1 fold: instrument the SAME
        # `SELF_LEARN_CLAUDE_DIR` the `env` fixture already set
        # (`env.fake_home / ".claude"`), not a second, separate
        # directory -- `claude_runtime_dir()` (report.py's
        # `_resolve_user_claude_md_row`/`_skill_description_row`) now
        # resolves off that SAME env var, and `_set_user_claude_md`
        # below writes into `env.user_claude_md`, which lives under
        # `env.fake_home / ".claude"`. Re-pointing SELF_LEARN_CLAUDE_DIR
        # at a fresh, unrelated dir here would make the budget signal
        # find nothing at the target it just wrote 6200 words to.
        claude_dir = env.fake_home / ".claude"
        monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
        _instrument(claude_dir)

        _crowding_pool(env, 45)
        # 6200 hand words + ~819 managed words (incl. the 13-word marker
        # pair) -> baseline >= 7000, and ALL managed words land inside
        # the 30d window (nothing routed 30+ days ago) -> growth flags
        # (>= 750 added) AND composition's growth-pp flags.
        _set_user_claude_md(env, _n_words(6200))
        _write_routed(
            env, scope="user", record_id="lrn-a10a0001", destination="claude-md",
            routed_at=days_ago_ts(1),
            fact="zephyrine octarine wallaby shared token set alpha " * 3,
        )
        _write_routed(
            env, scope="user", record_id="lrn-a10a0002", destination="claude-md",
            routed_at=days_ago_ts(1),
            fact="zephyrine octarine wallaby shared token set beta " * 3,
        )
        for i in range(5):
            _write_routed(
                env, scope="user", record_id=f"lrn-a10b000{i}", destination="claude-md",
                routed_at=days_ago_ts(1),
                fact=" ".join(f"pad{i}_{j}" for j in range(150)),
            )
        # cold reference shelf
        r1 = _write_routed(
            env, scope="skill:s", record_id="lrn-a10c0001", destination="reference",
            routed_at=days_ago_ts(10), fact="cold reference shelf entry",
        )
        r1.set_routing({**r1.routing, "reference_file": "README.md"})
        bucket_dir = bucket_dir_for_scope(env.ledger, "skill:s")
        r1.write(bucket_dir / "resolved" / f"{r1.id}.md")

        pending = Record.create(
            type="knowledge", scope="user", source="teach",
            fact="the new lesson this route lands", record_id="lrn-a10d0001",
        )
        create_record(env.ledger, pending)
        return pending.id

    def test_t10_1_route_never_refuses_even_when_everything_flags(
        self, env, tmp_path, monkeypatch
    ):
        pending_id = self._build_everything_flagged(env, tmp_path, monkeypatch)

        payload = report.context_budget(env.ledger, TODAY)
        # N7 (u-cap code gate r1): the r1 version of this test asserted
        # only budget+growth flagged -- the spec's own fixture
        # description ("large file, high share, crowded pairs, 900 w
        # growth, cold reference shelf") names every signal, and the
        # fixture built by `_build_everything_flagged` above DOES trip
        # crowding (the two `zephyrine octarine wallaby` shared-rare-
        # token records) and composition (all managed words land inside
        # the 30d window) -- assert them too, not just the two the r1
        # test happened to check.
        assert payload["budget"]["flagged"] is True
        assert payload["growth"]["flagged"] is True
        assert payload["crowding"]["flagged"] is True
        assert payload["composition"]["flagged"] is True

        rc = cli.main(["route", pending_id, "--dest", "claude-md"])
        assert rc == 0

        from self_learn.records import Record as _Record

        bucket_dir = bucket_dir_for_scope(env.ledger, "user")
        routed = _Record.from_path(bucket_dir / "resolved" / f"{pending_id}.md")
        assert routed.status == "routed"
        text = env.user_claude_md.read_text(encoding="utf-8")
        assert pending_id in text

    def test_t10_2_stderr_carries_the_note_never_a_warning(self, env, tmp_path, monkeypatch, capsys):
        self._build_everything_flagged(env, tmp_path, monkeypatch)
        pending = Record.create(
            type="knowledge", scope="user", source="teach",
            fact="a second fresh lesson", record_id="lrn-a10e0001",
        )
        create_record(env.ledger, pending)

        rc = cli.main(["route", "lrn-a10e0001", "--dest", "claude-md"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "budget:" in err
        assert "warning" not in err.lower()
        assert "over cap" not in err.lower()
        assert "graduate the oldest" not in err.lower()

    def test_t10_3_report_json_severity_and_no_over_cap(self, env, tmp_path, monkeypatch):
        self._build_everything_flagged(env, tmp_path, monkeypatch)
        payload = report.context_budget(env.ledger, TODAY)
        for key in ("budget", "crowding", "composition", "growth"):
            assert payload[key]["severity"] == "informational"
        for key in ("reference", "rules_cofire"):
            assert payload["conditional"][key]["severity"] == "informational"
        assert not _contains_key_named(payload, "over_cap")

    def test_t10_4_surface_budget_event_has_no_overflow_key(self, env, tmp_path, monkeypatch):
        self._build_everything_flagged(env, tmp_path, monkeypatch)
        pending = Record.create(
            type="knowledge", scope="user", source="teach",
            fact="a third fresh lesson for telemetry", record_id="lrn-a10f0001",
        )
        create_record(env.ledger, pending)
        rc = cli.main(["route", "lrn-a10f0001", "--dest", "claude-md"])
        assert rc == 0

        from self_learn.telemetry import read_events

        events = [
            e for e in read_events(env.ledger)
            if e.get("kind") == "surface-budget"
        ]
        assert events
        assert all("overflow" not in e for e in events)


# ===================================================================== #
# MAJOR 4 (u-cap code gate r1) -- render_text consumes context_budget
# ===================================================================== #


class TestRenderTextConsumesContextBudget:
    """MAJOR 4 (u-cap code gate r1): `render_text` never consumed
    `context_budget` at all -- `self-learn report` without `--json`
    showed none of this unit. Covers the obligations the gate named
    unimplemented: §4.0.1 (a text-render line is a permitted effect at
    all), §4.0.5 (a total computed while surfaces_unmeasured > 0 is a
    lower bound, and the TEXT must say so, not just the JSON),
    §4.2 (name the lenient skill-description extraction count when
    non-zero), §4.2.1 (`all_hosts_words` is a diagnostic ONLY and must
    be labelled "not a session cost"), §4.4.1 (`past_is_lower_bound` is
    an emitted field, not a comment -- print it whenever a reconstructed
    delta is non-null)."""

    def test_section_exists_and_names_the_baseline(self, env):
        _set_user_claude_md(env, _n_words(50))
        facts = report.gather(env.ledger, today=TODAY)
        text = report.render_text(facts)
        assert "Context budget" in text
        assert "session baseline:" in text

    def test_tri_state_all_blind_says_could_not_measure_not_zero(self, env):
        import shutil

        shutil.rmtree(env.skills_index)
        shutil.rmtree(env.host)
        facts = report.gather(env.ledger, today=TODAY)
        text = report.render_text(facts)
        assert "could not measure" in text
        # the null/all-blind leg must never read as a clean "0" measurement
        budget_line = next(
            ln for ln in text.splitlines() if ln.strip().startswith("budget:")
        )
        assert "0 words" not in budget_line

    def test_totals_are_lower_bound_labelled_in_text(self, env):
        if os.name != "posix" or os.getuid() == 0:
            pytest.skip("chmod 000 has no effect for root")
        _set_user_claude_md(env, _n_words(50))
        env.skills_index.chmod(0)
        try:
            facts = report.gather(env.ledger, today=TODAY)
        finally:
            env.skills_index.chmod(0o755)
        text = report.render_text(facts)
        baseline_line = next(
            ln for ln in text.splitlines() if ln.strip().startswith("session baseline:")
        )
        assert "lower bound" in baseline_line

    def test_lenient_skill_count_named_when_non_zero(self, env):
        _set_user_claude_md(env, _n_words(50))
        _seed_index_skill(env, "lenientskill", 6, tier="lenient")
        facts = report.gather(env.ledger, today=TODAY)
        text = report.render_text(facts)
        assert "extracted via the lenient fallback" in text
        assert "1 of" in text

    def test_all_hosts_words_labelled_not_a_session_cost(self, env):
        # make_env registers env.host as a sound project with its own
        # seeded CLAUDE.md by default (T2.11's own comment) -- an OK
        # project row plus the user row is enough for all_hosts_words to
        # be non-null.
        _set_user_claude_md(env, _n_words(50))
        facts = report.gather(env.ledger, today=TODAY)
        text = report.render_text(facts)
        assert "not a session cost" in text

    def test_composition_delta_prints_past_is_lower_bound(self, env):
        _set_user_claude_md(env, _n_words(50))
        _write_routed(
            env, scope="user", record_id="lrn-0900001a", destination="claude-md",
            routed_at=days_ago_ts(1), fact="a recent fact for the composition delta",
        )
        facts = report.gather(env.ledger, today=TODAY)
        text = report.render_text(facts)
        comp_line = next(
            ln for ln in text.splitlines() if "~/.claude/CLAUDE.md:" in ln
        )
        assert "words/30d" in comp_line
        assert "lower bound" in comp_line

    def test_growth_prints_past_is_lower_bound_and_rate(self, env):
        _set_user_claude_md(env, _n_words(50))
        _write_routed(
            env, scope="user", record_id="lrn-0900002b", destination="claude-md",
            routed_at=days_ago_ts(1), fact="a recent fact big enough to add growth words " * 20,
        )
        facts = report.gather(env.ledger, today=TODAY)
        text = report.render_text(facts)
        growth_line = next(
            ln for ln in text.splitlines() if ln.strip().startswith("growth:")
        )
        assert "always-on words/30d" in growth_line
        assert "lower bound" in growth_line


# ===================================================================== #
# NITs (u-cap code gate r1) -- N3/N4/N5/N6
# ===================================================================== #


class TestNitFixes:
    def test_n3_one_cofire_threshold_constant_not_two(self):
        """N3: `verbs.py` used to carry its OWN
        `_COFIRE_CROWDED_THRESHOLD` duplicating
        `report._COFIRE_MAX_FANIN_ADVISORY` -- same number, two names, a
        drift risk if only one were ever tuned. Now there is exactly
        one, and `verbs` reads it via deferred import."""
        assert not hasattr(verbs, "_COFIRE_CROWDED_THRESHOLD")
        assert report._COFIRE_MAX_FANIN_ADVISORY == 5

    def test_n4_budget_note_uses_tilde_form_for_user_scope_target(self, env):
        """N4: §6.2's own example prints the tilde form
        (`~/.claude/CLAUDE.md`), never the expanded absolute path (the
        note is pasted into public issues)."""
        _set_user_claude_md(env, _n_words(5))
        rec = Record.create(
            type="knowledge", scope="user", source="teach",
            fact="a lesson for the tilde-path check", record_id="lrn-1a000001",
        )
        create_record(env.ledger, rec)
        result = verbs.route(env.ledger, "lrn-1a000001", dest="claude-md")
        note = result.budget_note()
        assert note is not None
        assert "~/.claude/CLAUDE.md is" in note
        assert str(env.fake_home) not in note

    def test_n5_budget_note_degrades_on_unicode_decode_error_too(self, env):
        """N5: the whole-file read in `budget_note` used to catch only
        `OSError`, not `UnicodeDecodeError` -- a target that exists but
        is not valid UTF-8 must degrade the same way a permissions
        failure does (T11.3's clause), not raise."""
        _set_user_claude_md(env, _n_words(5))
        rec = Record.create(
            type="knowledge", scope="user", source="teach",
            fact="a lesson before the target goes binary", record_id="lrn-1b000001",
        )
        create_record(env.ledger, rec)
        result = verbs.route(env.ledger, "lrn-1b000001", dest="claude-md")

        env.user_claude_md.write_bytes(b"\xff\xfe not valid utf-8 \x00\x01")
        note = result.budget_note()
        assert note is not None
        assert "surface size unavailable" in note
        assert "entries" in note and "words" in note

    def test_n6_unpathed_row_is_absent_not_unreadable_when_removed(self, env):
        """N6: `_one_unpathed_row` used to only distinguish "ok" from
        "unreadable" -- a topic file that has since been removed (the
        co-firing scan named a stem that no longer resolves to a file)
        is a different, nameable fact ("absent"), not folded into the
        generic "unreadable" bucket."""
        from self_learn.report import _one_unpathed_row

        missing = env.fake_home / "does-not-exist.md"
        row = _one_unpathed_row("user", "missing-topic", missing)
        assert row["state"] == "absent"
        assert row["file_words"] is None
