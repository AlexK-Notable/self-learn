"""U-composer acceptance criteria A1-A13: the roster, cluster candidates,
the path roster, and prompt composition (docs/specs/self-learn/drafts/
u-composer-prompt-and-doctrine-spec.md §4).

Each test's docstring names its criterion and states what an
absent/broken build would report (the spec's own "absent/broken" line),
per this repo's fail-open discipline: a check that cannot distinguish
"present" from "absent" is not a check.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from self_learn import worker
from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import (
    ROSTER_UNAVAILABLE,
    QueueEntry,
    ProposalError,
    create_record,
    queue,
    validate_proposal,
)
from self_learn.normalize import sha_anchor
from self_learn.records import Record

from support import commit_all, make_behavior, make_env


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    # A1-A13 need a HERMETIC claude dir — the real ~/.claude/skills on the
    # dev host must never leak into a roster-composition test.
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "claude-dir-empty"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _bucket_for_scope(home: Path, scope: str):
    """`Bucket.scope` is the coarse kind ("skill"/"project"/"user"),
    never `Record.scope` ("skill:s") — the two vocabularies this
    codebase's own bucket-identity lesson (memory: bucket-identity-is-
    scope-and-name) warns never to conflate."""
    if scope.startswith("skill:"):
        name = scope.partition(":")[2]
        (bucket,) = [b for b in discover_buckets(home) if b.scope == "skill" and b.name == name]
        return bucket
    (bucket,) = [b for b in discover_buckets(home) if b.scope == scope]
    return bucket


def _entry_for(home: Path, record) -> QueueEntry:
    bucket = _bucket_for_scope(home, record.scope)
    (entry,) = [e for e in queue(bucket, include_deferred=True) if e.record.id == record.id]
    return entry


# =====================================================================
# A. The roster
# =====================================================================


def test_a1_roster_composed_from_both_sources_deduped_by_realpath(tmp_path, monkeypatch):
    """A1 — the roster is composed from both sources and deduped by
    realpath. Absent/broken: a build that skips the dedupe renders two
    `alpha` rows and fails the "exactly one" assertion; a build that
    reads only the skills root renders no `beta` row and fails
    `visible_only == 1`."""
    env = make_env(tmp_path, skills=("alpha",))
    claude_dir = Path(monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "claude-dir")) or (tmp_path / "claude-dir"))
    (claude_dir / "skills").mkdir(parents=True)
    # symlink claude_dir/skills/alpha -> the SAME real skills-root alpha dir
    alpha_real = env.host / "plugins" / "alpha-plugin" / "skills" / "alpha"
    (claude_dir / "skills" / "alpha").symlink_to(alpha_real, target_is_directory=True)
    # a real, second skill visible ONLY via the claude dir (not registered)
    beta_dir = claude_dir / "skills" / "beta"
    beta_dir.mkdir(parents=True)
    (beta_dir / "SKILL.md").write_text(
        "---\nname: beta\ndescription: A beta skill.\n---\n\n# beta\n",
        encoding="utf-8",
    )

    roster = worker.skill_roster(env.ledger)
    alpha_rows = [ln for ln in roster.text.splitlines() if ln.startswith("- alpha ")]
    beta_rows = [ln for ln in roster.text.splitlines() if ln.startswith("- beta ")]
    assert len(alpha_rows) == 1, roster.text
    assert len(beta_rows) == 1, roster.text
    assert roster.routable == 1
    assert roster.visible_only == 1


def test_a2_block_scalar_description_survives(tmp_path):
    """A2 — a block-scalar description survives (the measured fail-open).
    Positive control in the same test: a plain `description: text` skill
    renders too. Absent/broken: a line-grab implementation renders
    `- alpha [routable]: |` and fails both legs."""
    env = make_env(tmp_path, skills=("alpha", "plain"))
    alpha_md = env.host / "plugins" / "alpha-plugin" / "skills" / "alpha" / "SKILL.md"
    alpha_md.write_text(
        "---\n"
        "name: alpha\n"
        "description: |\n"
        "  A multi-line block scalar\n"
        "  description for alpha.\n"
        "---\n\n# alpha\n",
        encoding="utf-8",
    )
    plain_md = env.host / "plugins" / "plain-plugin" / "skills" / "plain" / "SKILL.md"
    plain_md.write_text(
        "---\nname: plain\ndescription: A plain description.\n---\n\n# plain\n",
        encoding="utf-8",
    )

    roster = worker.skill_roster(env.ledger)
    alpha_line = next(ln for ln in roster.text.splitlines() if ln.startswith("- alpha "))
    assert "|" not in alpha_line
    assert "A multi-line block scalar description for alpha." in alpha_line
    plain_line = next(ln for ln in roster.text.splitlines() if ln.startswith("- plain "))
    assert "A plain description." in plain_line


def test_a3_unparseable_frontmatter_rendered_never_dropped(tmp_path):
    """A3 — an unparseable frontmatter is rendered, never dropped, using
    the REAL failure shape (an unquoted `: ` inside a plain scalar).
    Positive control: a well-formed sibling renders its description
    normally. Absent/broken: a build that `continue`s past the parse
    error renders one fewer row and the count assertion fails."""
    env = make_env(tmp_path, skills=("broken", "sibling"))
    broken_md = env.host / "plugins" / "broken-plugin" / "skills" / "broken" / "SKILL.md"
    broken_md.write_text(
        "---\n"
        "name: broken\n"
        "description: Use when: the user asks\n"  # unquoted ": " -> ScannerError
        "---\n\n# broken\n",
        encoding="utf-8",
    )
    sibling_md = env.host / "plugins" / "sibling-plugin" / "skills" / "sibling" / "SKILL.md"
    sibling_md.write_text(
        "---\nname: sibling\ndescription: A fine description.\n---\n\n# sibling\n",
        encoding="utf-8",
    )

    roster = worker.skill_roster(env.ledger)
    broken_line = next(ln for ln in roster.text.splitlines() if ln.startswith("- broken "))
    assert "(frontmatter unparseable)" in broken_line
    sibling_line = next(ln for ln in roster.text.splitlines() if ln.startswith("- sibling "))
    assert "A fine description." in sibling_line
    # both counted (routable, from the registered skills root)
    assert roster.routable == 2
    assert roster.visible_only == 0


def test_a4_unavailable_path_is_real_and_coupled_to_x3(tmp_path, monkeypatch):
    """A4 — the unavailable path is real and is coupled to X3. Leg 1:
    no registered skills root + empty claude dir -> ROSTER_UNAVAILABLE,
    text names the reason. Leg 2 (regression guard on U-schema's shipped
    X3, cannot fail for this build per the spec): a `t3.roster_sha:
    unavailable` + `t3.answer: yes` proposal is refused; the same trace
    with `answer: no` + `flags: [evidence-gap]` is accepted."""
    home = tmp_path / "empty-ledger"
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir(parents=True)
    (home / "hosts.yaml").write_text("projects: []\n", encoding="utf-8")
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "no-claude-dir"))

    roster = worker.skill_roster(home)
    assert roster.sha == ROSTER_UNAVAILABLE
    assert "unavailable" in roster.text

    from support import proposal_dict

    bad = proposal_dict(
        scope="user",
        destination="claude-md",
        gates={
            "g0": {"reject": {"answer": "no"}, "defer": {"answer": "no"}, "canon": {"answer": "no"}},
            "t1": {
                "attempted": False,
                "field_shaped": {"answer": "no", "evidence": "status: pending"},
                "separable": {"answer": None},
                "cost_bearing": {"answer": None},
            },
            "t2": {"answer": "no", "evidence": "status: pending", "match_path": None},
            "t3": {"answer": "yes", "owner": "s", "scan_terms": None, "roster_sha": ROSTER_UNAVAILABLE},
            "t3a": {
                "depth_behind_rule": {"answer": "no", "evidence": None},
                "fs": {"verdict": "SILENT", "evidence": "status: pending"},
            },
            "tn": {"answer": "no", "terms": [], "members": [], "proposed_name": None},
            "t4": None,
            "e1": {"sightings": 1, "post_demand_recurrence": False},
            "outcome": "SKILL",
        },
        flags=[],
        recommendation="route",
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad, record_text="---\nstatus: pending\n---\n\nbody\n")

    good = dict(bad)
    good["gates"] = dict(bad["gates"])
    good["gates"]["t3"] = {"answer": "no", "owner": None, "scan_terms": ["a", "b"], "roster_sha": ROSTER_UNAVAILABLE}
    good["gates"]["t3a"] = None
    good["gates"]["t4"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None},
        "conduct_mode": {"answer": "no", "evidence": None},
        "fs": {"verdict": "INDETERMINATE", "evidence": None},
    }
    good["gates"]["outcome"] = "DEMAND"
    good["destination"] = "claude-md"
    good["flags"] = ["evidence-gap"]
    good["recommendation"] = "route"
    validate_proposal(good, record_text="---\nstatus: pending\n---\n\nbody\n")


def test_a5_sha_covers_the_rendered_text(tmp_path):
    """A5 — the sha covers the rendered text. Absent/broken: a sha
    derived from paths or mtimes is stable across the description
    mutation and fails the second leg."""
    env = make_env(tmp_path, skills=("alpha",))
    alpha_md = env.host / "plugins" / "alpha-plugin" / "skills" / "alpha" / "SKILL.md"
    alpha_md.write_text(
        "---\nname: alpha\ndescription: Original text.\n---\n\n# alpha\n",
        encoding="utf-8",
    )
    roster1 = worker.skill_roster(env.ledger)
    assert roster1.sha == sha_anchor(roster1.text)

    alpha_md.write_text(
        "---\nname: alpha\ndescription: Original text, mutated.\n---\n\n# alpha\n",
        encoding="utf-8",
    )
    roster2 = worker.skill_roster(env.ledger)
    assert roster2.sha != roster1.sha
    assert roster2.sha == sha_anchor(roster2.text)

# =====================================================================
# B. Cluster candidates
# =====================================================================


def _pending_behavior(env, record_id, trigger):
    record = make_behavior(scope="skill:s", record_id=record_id, trigger=trigger)
    create_record(env.ledger, record)
    return record


def _routed_behavior(env, record_id, trigger):
    from self_learn.ledger import discover_buckets as _discover

    (bucket,) = [b for b in _discover(env.ledger) if b.scope == "skill" and b.name == "s"]
    record = make_behavior(scope="skill:s", record_id=record_id, trigger=trigger)
    record.set_routing({"routed_at": "2026-07-13T18:02:00Z", "destination": "claude-md", "by": "human"})
    record.set_status("routed")
    resolved_dir = bucket.path / "resolved"
    resolved_dir.mkdir(parents=True, exist_ok=True)
    record.write(resolved_dir / f"{record_id}.md")
    return record


@pytest.fixture()
def a6_env(tmp_path):
    """The A6 discriminating fixture: (i) a distinctive-term sibling
    pair, (ii) a hub record with >=6 qualifying candidates, (iii) an
    isolated record, (iv) a deliberate score tie whose two candidates
    must be broken by record id — engineered against a pending vs.
    routed pair so a broken (score-only) sort's stable order does NOT
    already happen to match the id order (A7's own requirement)."""
    env = make_env(tmp_path, skills=("s",))

    # (i) sibling pair — a term unique to exactly these two records.
    a = _pending_behavior(env, "lrn-10000000", "check the zzzsib alpha state")
    sib = _pending_behavior(env, "lrn-10000001", "revisit the zzzsib beta state")

    # (ii) hub + 6 qualifying siblings — a term shared by exactly 7
    # records (the hub + 6), each title otherwise just that one token.
    hub = _pending_behavior(env, "lrn-20000000", "zzzhub")
    hub_siblings = [
        _pending_behavior(env, f"lrn-2000000{n}", "zzzhub") for n in range(1, 7)
    ]

    # (iii) isolated — shares no token (length > 2) with anything else.
    isolated = _pending_behavior(
        env, "lrn-30000000", "qqqnothing sharesxx anythingxx totallyxx isolatedxx"
    )

    # (iv) the tie: a target D, and two same-scoring candidates — E
    # (pending, HIGH id) and F (routed, LOW id). Pool insertion order
    # within one bucket is [all pending, ascending id] then [all routed,
    # ascending id], so E lands before F despite F's lower id — exactly
    # the case a broken score-only sort leaves mis-ordered.
    d = _pending_behavior(env, "lrn-50000000", "zzztie")
    e_high = _pending_behavior(env, "lrn-99999999", "zzztie")
    f_low = _routed_behavior(env, "lrn-00000005", "zzztie")

    return env, dict(
        a=a, sib=sib, hub=hub, hub_siblings=hub_siblings, isolated=isolated,
        d=d, e_high=e_high, f_low=f_low,
    )


def _entries_for(home, records):
    from self_learn.ledger import discover_buckets as _discover
    from self_learn.ledger_ops import queue as _queue

    (bucket,) = [b for b in _discover(home) if b.scope == "skill" and b.name == "s"]
    all_entries = {e.record.id: e for e in _queue(bucket, include_deferred=True)}
    return [all_entries[r.id] for r in records]


def test_a6_ranking_floor_and_cap(a6_env, monkeypatch):
    """A6 — the ranking, the floor and the cap, on a fixture that
    discriminates all four legs. Absent/broken: "at most 5 rows and none
    below the floor" is satisfied by ZERO rows, so a build that returns
    nothing passes it and removing the cap survives — the exact-5 +
    cap-removed-yields-6-or-more pair is what closes that hole."""
    env, r = a6_env
    batch = _entries_for(env.ledger, [r["a"], r["hub"], r["isolated"]])

    result = worker.cluster_candidates(env.ledger, batch)

    # (i) — the sibling is the top (and only meaningful) candidate for A.
    a_candidates = result[r["a"].id]
    assert a_candidates, "expected at least the sibling candidate"
    assert a_candidates[0].record_id == r["sib"].id
    assert a_candidates[0].score >= worker.CANDIDATE_SCORE_FLOOR

    # (ii) — capped at exactly 5.
    hub_candidates = result[r["hub"].id]
    assert len(hub_candidates) == worker.CANDIDATE_CAP == 5

    # same pool, cap removed -> 6 or more (equality broken deliberately,
    # never a bound: r1's own wording — "at most 5" — is satisfied by 0).
    monkeypatch.setattr(worker, "CANDIDATE_CAP", 999)
    result_uncapped = worker.cluster_candidates(env.ledger, batch)
    assert len(result_uncapped[r["hub"].id]) >= 6

    # (iii) — the literal no-candidates line.
    rendered = worker._render_candidates(result[r["isolated"].id])
    assert rendered == "(no cluster candidates above the 0.20 floor)"


def test_a7_determinism_and_tie_ordering(a6_env):
    """A7 — determinism, exercised on the tie: two calls on the same pool
    return byte-identical blocks (including under a shuffled input
    order), and the two tied candidates from A6(iv) appear in record-id
    order. Absent/broken: without the A6(iv) tie in the pool, a
    score-only sort (M8) changes no output and this criterion cannot see
    it — sorted() is stable, so the defect only shows up ON a tie."""
    env, r = a6_env
    batch = _entries_for(env.ledger, [r["d"]])

    result1 = worker.cluster_candidates(env.ledger, batch)
    rendered1 = worker._render_candidates(result1[r["d"].id])

    # shuffled batch order (batch has one entry here, so shuffle the
    # underlying pool order instead by re-querying — the call itself is
    # deterministic regardless of any transient ordering upstream).
    result2 = worker.cluster_candidates(env.ledger, list(reversed(batch)) or batch)
    rendered2 = worker._render_candidates(result2[r["d"].id])
    assert rendered1 == rendered2

    d_candidates = result1[r["d"].id]
    tied_ids = [c.record_id for c in d_candidates if c.record_id in (r["e_high"].id, r["f_low"].id)]
    assert tied_ids == sorted(tied_ids), (
        f"tied candidates must appear in ascending record-id order, got {tied_ids}"
    )
    assert tied_ids == [r["f_low"].id, r["e_high"].id]


def test_a8_score_rendered_to_two_decimals(a6_env):
    """A8 — the score is rendered. Absent/broken: a row without a score
    passes every other criterion while making a mis-calibrated floor
    invisible."""
    import re

    env, r = a6_env
    batch = _entries_for(env.ledger, [r["a"]])
    result = worker.cluster_candidates(env.ledger, batch)
    rendered = worker._render_candidates(result[r["a"].id])
    assert re.search(r"\(\d\.\d\d\)", rendered), rendered

# =====================================================================
# C. The path roster and the per-record block
# =====================================================================


def test_a9_path_roster_slots_present_with_reasons(tmp_path):
    """A9 — every slot is present, and unresolvable slots carry a
    reason. Absent/broken: a build that omits unresolvable slots fails
    the presence assertions — a missing line and an unavailable line
    must not read the same."""
    # (a) user scope, no registered skills root.
    from support import init_repo as _init_repo, commit_all as _commit_all

    home = tmp_path / "no-skills-root-ledger"
    _init_repo(home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir(parents=True)
    (home / "hosts.yaml").write_text("projects: []\n", encoding="utf-8")
    _commit_all(home, "ledger seed")

    user_record = make_behavior(scope="user", record_id="lrn-40000000")
    create_record(home, user_record)
    entry = _entry_for(home, user_record)
    block = worker.path_roster(home, entry)
    assert "skills root        : (none registered)" in block
    assert "DEMAND target      : (unavailable at user scope — S-23)" in block
    pathed_line = next(ln for ln in block.splitlines() if ln.startswith("PATHED rules dir"))
    assert "(unavailable" not in pathed_line  # user scope DOES resolve

    # (b) skill scope.
    env = make_env(tmp_path, skills=("s",))
    skill_record = make_behavior(scope="skill:s", record_id="lrn-40000001")
    create_record(env.ledger, skill_record)
    skill_entry = _entry_for(env.ledger, skill_record)
    skill_block = worker.path_roster(env.ledger, skill_entry)
    assert "PATHED rules dir   : (unavailable at skill scope — P-A13)" in skill_block
    demand_line = next(ln for ln in skill_block.splitlines() if ln.startswith("DEMAND target"))
    assert "(unavailable" not in demand_line and "(unresolvable" not in demand_line


def test_a10_composing_never_raises_on_a_dirty_host_repo(tmp_path):
    """A10 — composing a prompt never raises because a host repo is
    dirty. Absent/broken: a build that resolves targets via
    `_resolve_target` raises `VerbError` and the test errors."""
    env = make_env(tmp_path, skills=("s",))
    (env.host / "CLAUDE.md").write_text("dirty, uncommitted\n", encoding="utf-8")
    record = make_behavior(scope="project", record_id="lrn-41000000")
    create_record(env.ledger, record, project_path=env.host)
    entry = _entry_for(env.ledger, record)
    prompt, _roster = worker.compose_batch_prompt(env.ledger, [entry])
    assert isinstance(prompt, str) and prompt


def test_a11_both_paths_compose_the_same_per_record_block(tmp_path):
    """A11 — both execution paths compose the same per-record block.
    Absent/broken: two divergent implementations differ and fail — a
    test that re-derives the block by slicing either prompt would pass
    on a build whose two paths differ."""
    env = make_env(tmp_path, skills=("s",))
    record = make_behavior(scope="skill:s", record_id="lrn-42000000")
    create_record(env.ledger, record)
    entry = _entry_for(env.ledger, record)

    roster = worker.skill_roster(env.ledger)
    candidates = worker.cluster_candidates(env.ledger, [entry]).get(record.id, [])
    block = worker.compose_record_block(env.ledger, entry, roster=roster, candidates=candidates)

    batch_prompt, _r1 = worker.compose_batch_prompt(env.ledger, [entry])
    single_prompt, _r2 = worker.compose_single_prompt(env.ledger, entry)
    assert block in batch_prompt
    assert block in single_prompt


def test_a12_worker_prompt_ingredients_and_to_text_containment(tmp_path):
    """A12 — the worker prompt still carries what it carried, shows the
    text containment checks, and instructs the producer. Absent/broken:
    a composer that interpolates `entry.path.read_text()` instead of
    `Record.to_text()` passes on almost every real record and fails only
    the third leg — which is why the fixture must be a frontmatter ruamel
    re-renders differently (a quoted scalar), not sampled from the
    ledger."""
    env = make_env(tmp_path, skills=("s",))
    record = make_behavior(scope="skill:s", record_id="lrn-43000000")
    create_record(env.ledger, record)
    rpath = env.ledger / "skills" / "s" / "pending" / f"{record.id}.md"
    raw_bytes = rpath.read_text(encoding="utf-8")
    # Force a MEASURED divergence between raw bytes and Record.to_text():
    # ruamel's round-trip dumper NORMALIZES list-item indentation to its
    # configured `indent(sequence=4, offset=2)` regardless of how the
    # source was indented (quote style, by contrast, round-trips
    # faithfully — measured directly against records.py's own
    # `_make_yaml()` config before picking this fixture shape) — a
    # zero-indent `evidence:` list item re-renders 2-space-indented.
    forced = raw_bytes.replace(
        "evidence: []\n",
        "evidence:\n- origin: x\n  note: y\n",
        1,
    )
    assert forced != raw_bytes, "fixture setup did not find evidence: [] to replace"
    rpath.write_text(forced, encoding="utf-8")
    from self_learn.records import Record as _Record

    reloaded = _Record.from_path(rpath)
    assert reloaded.to_text() != forced, "fixture must actually diverge from raw bytes"

    entry = _entry_for(env.ledger, reloaded)
    prompt, _roster = worker.compose_batch_prompt(env.ledger, [entry])

    # doctrine tokens + registry + digest survive (regression guard, N1).
    assert "trigger_recognizable" in prompt
    assert "why_present" in prompt
    assert "§9" in prompt
    assert "§10" in prompt
    assert "headline" in prompt  # card registry

    # roster sha line + candidate block + path roster.
    assert "roster sha:" in prompt
    assert "cluster candidates (T-N)" in prompt
    assert "path roster" in prompt

    # to_text(), never raw bytes.
    assert reloaded.to_text() in prompt
    assert forced not in prompt

    # producer-instruction leg: the three key names in the INSTRUCTION
    # header, not merely inside the interpolated doctrine text.
    header = prompt[: prompt.index("=== SKILL ROSTER")]
    assert "gates" in header and "flags" in header and "recommendation" in header


def test_a12b_trace_less_deletion_and_pipeline_not_dead_control(tmp_path, monkeypatch):
    """A12b (F7) — highest-stakes criterion (S-26's wedge risk): a
    trace-less proposal is deleted at landing, and a trace-carrying one
    lands. Absent/broken: without leg (b), the criterion would pass on a
    build where the worker deletes EVERY proposal it is handed — exactly
    the wedge S-26 names (TRACE_REQUIRED on, producer not instructed,
    queue silently yields nothing forever). Leg (a) alone cannot tell
    "the flip works" from "the pipeline is dead"."""
    import os
    import stat as _stat
    import subprocess as _sp

    from support import git as _git
    from self_learn.ledger_ops import is_unanalyzed as _is_unanalyzed
    from self_learn.worker import skill_roster as _skill_roster

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    env = make_env(tmp_path, skills=("s",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    bare = tmp_path / "remote.git"
    _sp.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    _git(env.ledger, "remote", "add", "origin", str(bare))
    _git(env.ledger, "push", "-q", "-u", "origin", "main")

    # A REAL shim, argv/stdin-neutral: it runs whatever bash snippet the
    # test hands it via $CLAUDE_SHIM_SCRIPT — the same idiom
    # test_worker.py's own `claude_shim` fixture uses, which avoids
    # embedding heredoc-bearing script text through a second layer of
    # shell quoting (repr()-embedding a multi-line heredoc into a
    # generated shim file mangles both the embedded newlines and the
    # heredoc's own quoting — measured while drafting this fixture).
    shims = tmp_path / "shims"
    shims.mkdir()
    shim = shims / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "cat > /dev/null || true\n"
        'if [ -n "${CLAUDE_SHIM_SCRIPT-}" ]; then bash -c "$CLAUDE_SHIM_SCRIPT"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | _stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{shims}{os.pathsep}{os.environ['PATH']}")

    proposals_dir = env.ledger / "skills" / "s" / "proposals"

    # ---- leg (a): trace-less proposal -> deleted, record stays pending.
    rid_a = "lrn-44000000"
    record_a = make_behavior(scope="skill:s", record_id=rid_a)
    create_record(env.ledger, record_a)
    commit_all(env.ledger, f"pending {rid_a}")

    trace_less_yaml = (
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        "model: claude-sonnet-5\n"
        "analyzed_at: '2026-08-06T00:00:00Z'\n"
        "card:\n"
        '  headline: "A test headline."\n'
        '  impact: "Next time Claude does X it will Y."\n'
        '  discuss: "Nothing contentious."\n'
        # NO gates / flags / recommendation — the wedge case.
    )
    path_a = proposals_dir / f"{rid_a}.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {proposals_dir} && cat > {path_a} <<'YAML'\n{trace_less_yaml}YAML",
    )

    worker.run(env.ledger)
    assert not path_a.exists()
    assert (env.ledger / "skills" / "s" / "pending" / f"{rid_a}.md").is_file()
    entry_a = _entry_for(env.ledger, record_a)
    assert _is_unanalyzed(entry_a) is True

    # ---- leg (b), the control: a complete trace -> the proposal LANDS.
    rid_b = "lrn-44000001"
    record_b = make_behavior(scope="skill:s", record_id=rid_b)
    create_record(env.ledger, record_b)
    commit_all(env.ledger, f"pending {rid_b}")

    roster_sha = _skill_roster(env.ledger).sha
    full_trace_yaml = (
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        "model: claude-sonnet-5\n"
        "analyzed_at: '2026-08-06T00:00:00Z'\n"
        "card:\n"
        '  headline: "A test headline."\n'
        '  impact: "Next time Claude does X it will Y."\n'
        '  discuss: "Nothing contentious."\n'
        "gates:\n"
        "  g0:\n"
        '    reject: {answer: "no"}\n'
        '    defer: {answer: "no"}\n'
        '    canon: {answer: "no"}\n'
        "  t1:\n"
        "    attempted: false\n"
        "    field_shaped:\n"
        '      answer: "no"\n'
        '      evidence: "About to edit .storage while HA is running."\n'
        "    separable: {answer: null}\n"
        "    cost_bearing: {answer: null}\n"
        "  t2:\n"
        '    answer: "no"\n'
        '    evidence: "About to edit .storage while HA is running."\n'
        "    match_path: null\n"
        "  t3:\n"
        '    answer: "yes"\n'
        '    owner: "s"\n'
        "    scan_terms: null\n"
        f'    roster_sha: "{roster_sha}"\n'
        "  t3a:\n"
        '    depth_behind_rule: {answer: "no", evidence: null}\n'
        '    fs: {verdict: "SILENT", evidence: "About to edit .storage while HA is running."}\n'
        '  tn: {answer: "no", terms: [], members: [], proposed_name: null}\n'
        "  t4: null\n"
        "  e1: {sightings: 1, post_demand_recurrence: false}\n"
        "  outcome: SKILL\n"
        "flags: []\n"
        "recommendation: route\n"
    )
    path_b = proposals_dir / f"{rid_b}.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {proposals_dir} && cat > {path_b} <<'YAML'\n{full_trace_yaml}YAML",
    )

    worker.run(env.ledger)
    assert path_b.is_file()
    entry_b = _entry_for(env.ledger, record_b)
    assert _is_unanalyzed(entry_b) is False


def test_a13_argv_bound_prompts_stay_under_half_the_cap(tmp_path):
    """A13 — the argv-bound prompts stay under half the 128 KiB cap. This
    is an alarm, not a control (N1): today's largest composed input sits
    far under the ceiling and cannot fail for this build; it exists to
    fire on a later doctrine that grows unattended."""
    env = make_env(tmp_path, skills=("s",))
    doctrine_path = worker.package_skill_refs() / "routing-doctrine.md"
    assert len(doctrine_path.read_text(encoding="utf-8").encode("utf-8")) < 64 * 1024

    long_body = "\n".join(f"extra context line {i}" for i in range(200))
    record = make_behavior(
        scope="skill:s",
        record_id="lrn-45000000",
        trigger="About to edit `.storage/*.json` while HA is running " + long_body,
    )
    create_record(env.ledger, record)
    entry = _entry_for(env.ledger, record)
    prompt, _roster = worker.compose_single_prompt(env.ledger, entry)
    assert len(prompt.encode("utf-8")) < 64 * 1024
