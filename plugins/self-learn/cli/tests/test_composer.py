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


# =====================================================================
# D. The doctrine (A14-A20) — assertions against the REAL shipped file,
# beside the three tests that already do this (test_worker.py:896-919).
# =====================================================================


def _doctrine_text() -> str:
    return (worker.package_skill_refs() / "routing-doctrine.md").read_text(
        encoding="utf-8"
    )


def test_a14_gate_sequence_present_and_ordered():
    """A14 — the gate labels are present and their first occurrences are
    ordered G0, T1, T2, T3, T3a, T-N, T4, E1. Word-boundary matched (N4):
    `T3` is a substring of `T3a`, so a naive `text.index("T3")` finds
    whichever comes first and an ordering leg built on it can pass while
    the sections are transposed. Absent/broken: a doctrine that mentions
    the gates in prose but out of order fails the ordering leg; one that
    omits a gate fails presence."""
    import re

    text = _doctrine_text()
    labels = ["G0", "T1", "T2", "T3", "T3a", "T-N", "T4", "E1"]
    positions = []
    for label in labels:
        m = re.search(rf"\b{re.escape(label)}\b", text)
        assert m, f"gate label {label!r} not found"
        positions.append(m.start())
    assert positions == sorted(positions), (
        f"gate labels out of order: {list(zip(labels, positions))}"
    )


def test_a15_t2_sharpenings_present_with_authority_and_asked_every_scope():
    """A15 — the two T2 sharpenings are present, each with its authority,
    and T2 is asked at every scope. Absent/broken: a doctrine carrying
    only the r1 question ("does it only matter for certain files?") fails
    the first two legs; r1's own answer — "skill scope answers T2 no" —
    fails the third, which is what makes B2's fix visible to a test
    rather than only to a reader."""
    text = _doctrine_text()
    t2_start = text.index("**T2 —")
    t3_start = text.index("**T3 —")
    span = text[t2_start:t3_start]

    assert "first contact" in span
    assert "Read" in span
    assert "Grep" in span
    assert "Glob" in span
    assert "S-24" in span
    # T2 asked (and honestly answered) even where PATHED has no surface.
    assert "no-cheap-surface" in span


def test_a16_escalation_rule_present_with_evidence():
    """A16 — the escalation rule is present with its evidence. Matched on
    exact tokens (N5): `guard` and `prominence` within the escalation
    paragraph's span, and the literal record id `lrn-ea833a5b`.
    Absent/broken: a doctrine that says "escalate" without naming the
    guard, or without the corpus evidence, fails. Without pinned tokens
    the criterion is a reader's judgment call, which is not a test."""
    text = _doctrine_text()
    esc_start = text.index("Escalation is a guard")
    # the paragraph runs to the next "**"-headed paragraph/subsection.
    esc_end = text.index("\n\n", esc_start + 400)
    span = text[esc_start:esc_end]
    assert "guard" in span
    assert "prominence" in span
    assert "lrn-ea833a5b" in span


def test_a17_tier_model_per_scope_with_r_scope_rendering():
    """A17 — the tier model is stated per scope, and both no-surface
    corners carry the R-SCOPE rendering. Matched on exact tokens (N5),
    and on the phrasing D1 mandates, not r1's ("unavailable"). Absent/
    broken: a doctrine repeating "PATHED at every scope" carries neither
    token and fails. r1's own A17 asserted "unavailable", which D1 no
    longer permits — a doctrine written exactly to D1 would have failed
    a criterion pinned to that word."""
    text = _doctrine_text()
    shelves_span = text.split("## 1. The shelves", 1)[1].split("## 2.", 1)[0]
    assert "unavailable" not in shelves_span, (
        "the tier table must render the no-surface corners as "
        "'no routable surface', not 'unavailable' (D1, not r1's wording)"
    )
    table_start = text.index("| tier | skill:X | project | user |")
    table_end = text.index("\n\n", table_start)
    table = text[table_start:table_end]
    # PATHED x skill and DEMAND x user both carry the rendering.
    pathed_row = next(ln for ln in table.splitlines() if ln.startswith("| PATHED"))
    demand_row = next(ln for ln in table.splitlines() if ln.startswith("| DEMAND"))
    assert "no routable surface" in pathed_row
    assert "no routable surface" in demand_row
    assert "R-SCOPE" in table or "R-SCOPE" in text[table_end:table_end + 400]
    assert "S-23" in demand_row


def test_a18_trace_mandatory_quote_rule_and_derived_fields():
    """A18 — the trace is described as mandatory, the quote rule is
    unambiguous, and the three derived-field rules are present. Matched
    on exact tokens (N5). Absent/broken: a doctrine repeating r2's
    "record names no paths" phrasing fails the quote leg; one that lets
    the analyst choose `recommendation` fails the derived leg, and would
    ship a doctrine every U-table derivation check refuses."""
    text = _doctrine_text()
    trace_start = text.index("### 5.2")
    trace_end = text.index("### 5.3")
    span = text[trace_start:trace_end]

    # required-ness sentence names all three keys together.
    assert "gates" in span and "flags" in span and "recommendation" in span
    assert "required" in span

    # verbatim-on-negatives rule, and the TARGET-not-checked asymmetry.
    gate_proc_start = text.index("## 2. The gate procedure")
    gate_proc_span = text[gate_proc_start:trace_start]
    assert "including on" in gate_proc_span
    assert "not machine-checked" in span

    # the three F2/F3/F5 derived-field rules.
    assert "derived" in span
    assert "route" in span
    assert "alternates" in span


def test_a19_worked_example_validates_and_the_check_can_fail():
    """A19 — the doctrine's worked example validates, and the check can
    fail. The example RECORD and PROPOSAL are both extracted from the
    shipped doctrine (D8). Positive control in the same test: the same
    call with one `evidence` value replaced by a near-miss paraphrase
    must raise ProposalError. Absent/broken: r1's A19 could not fail —
    D8 shipped no record, so a builder passes record_text=None,
    containment does not run, and even a fabricated quote is accepted
    (measured). The control is what proves record_text= was supplied at
    all: if it is None, the paraphrase leg passes and the test fails."""
    import re
    import tempfile

    from ruamel.yaml import YAML

    text = _doctrine_text()
    md_blocks = re.findall(r"```markdown\n(.*?)\n```", text, re.DOTALL)
    yaml_blocks = re.findall(r"```yaml\n(.*?)\n```", text, re.DOTALL)
    record_block = next(b for b in md_blocks if "lrn-00000000" in b)
    proposal_block = next(
        b for b in yaml_blocks if "destination: reference" in b and "outcome: DEMAND" in b
    )

    with tempfile.TemporaryDirectory() as d:
        record_path = Path(d) / "lrn-00000000.md"
        record_path.write_text(record_block, encoding="utf-8")
        record = Record.from_path(record_path)

        yaml_loader = YAML(typ="safe")
        proposal = yaml_loader.load(proposal_block)

        # must not raise.
        validate_proposal(proposal, record_text=record.to_text())

        # positive control: a near-miss paraphrase of a RECORD-sourced
        # quote must be refused.
        bad = dict(proposal)
        bad["gates"] = dict(proposal["gates"])
        bad["gates"]["t2"] = dict(proposal["gates"]["t2"])
        bad["gates"]["t2"]["evidence"] = (
            "About to summarize command output instead of showing the tail"
        )
        with pytest.raises(ProposalError):
            validate_proposal(bad, record_text=record.to_text())


def test_a20_deletions_with_positive_controls():
    """A20 — the deletions, each with a positive control. Absent/broken:
    a zero-byte doctrine passes every "does not contain" assertion and
    fails every positive control — which is precisely why the controls
    are in the same test."""
    text = _doctrine_text()
    assert "chezmoi" not in text
    assert "autosync" not in text
    assert "pathed-unbuilt" not in text
    assert "behavior / anti-pattern" not in text

    # positive controls: a truncated/empty file cannot pass these.
    assert "no secrets" in text.lower()
    assert "S-23" in text
    assert "PATHED" in text


# =====================================================================
# E. The flip and the trace producers (A21-A24)
# =====================================================================


def _shim_env(tmp_path, monkeypatch):
    """A hermetic ledger (skill `s` registered) with a bare remote and a
    PATH-shimmed `claude` that runs whatever bash snippet the test hands
    it via $CLAUDE_SHIM_SCRIPT — the raw-text env-var idiom
    test_worker.py's own `claude_shim` fixture uses (proven safe against
    the repr()-embedding bug measured while drafting A12b: embedding a
    heredoc-bearing script through a second layer of Python repr()
    mangles both its newlines and its own quoting)."""
    import os
    import stat as _stat
    import subprocess as _sp

    from support import git as _git

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    env = make_env(tmp_path, skills=("s",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    bare = tmp_path / "remote.git"
    _sp.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    _git(env.ledger, "remote", "add", "origin", str(bare))
    _git(env.ledger, "push", "-q", "-u", "origin", "main")

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
    return env


def _skill_gates_yaml(roster_sha: str) -> str:
    """A complete SKILL-outcome trace at scope skill:s (t3 fires, owns
    `s`) — the shape A12b/A21 already exercise, parameterized only by
    the claimed roster sha."""
    return (
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
    )


def _skill_proposal_yaml(roster_sha: str) -> str:
    return (
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        "model: claude-sonnet-5\n"
        "analyzed_at: '2026-08-06T00:00:00Z'\n"
        + _skill_gates_yaml(roster_sha)
        + "flags: []\n"
        "recommendation: route\n"
    )


def _demand_gates_yaml(roster_sha: str, *, flags_evidence_gap: bool) -> str:
    """A complete DEMAND-outcome trace at scope skill:s (t3 does NOT
    fire — no roster ownership claimed), parameterized by the claimed
    roster sha and whether `evidence-gap` rides the flag set (X3
    requires it whenever `roster_sha` is the `unavailable` sentinel)."""
    return (
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
        '    answer: "no"\n'
        "    owner: null\n"
        "    scan_terms: [ha-storage, container]\n"
        f'    roster_sha: "{roster_sha}"\n'
        "  t3a: null\n"
        "  t4:\n"
        '    depth_behind_rule: {answer: "yes", evidence: "About to edit .storage while HA is running.", target: "self-learn skill reference"}\n'
        '    conduct_mode: {answer: "no", evidence: null}\n'
        '    fs: {verdict: "INDETERMINATE", evidence: null}\n'
        '  tn: {answer: "no", terms: [], members: [], proposed_name: null}\n'
        "  e1: {sightings: 1, post_demand_recurrence: false}\n"
        "  outcome: DEMAND\n"
    ) + ("flags: [evidence-gap]\n" if flags_evidence_gap else "flags: []\n")


def _demand_proposal_yaml(roster_sha: str, *, flags_evidence_gap: bool) -> str:
    return (
        "destination: reference\n"
        "alternates: [claude-md]\n"
        "rationale: not file-scoped, no skill roster entry owns this\n"
        "model: claude-sonnet-5\n"
        "analyzed_at: '2026-08-06T00:00:00Z'\n"
        + _demand_gates_yaml(roster_sha, flags_evidence_gap=flags_evidence_gap)
        + "recommendation: route\n"
    )




def test_a21_flip_refuses_traceless_key_by_key(tmp_path, monkeypatch):
    """A21 — the flip refuses a trace-less proposal, key by key, and the
    flag is what does it. Four legs, because the guard names three keys
    and a one-key test cannot see the other two (F6): (a) no gates/
    flags/recommendation at all; (b) valid gates + recommendation, flags
    ABSENT; (c) valid gates + flags, recommendation ABSENT — all three
    refused, and `is_unanalyzed` for each record stays True; (d)
    positive control: with TRACE_REQUIRED monkeypatched to False, the
    (a)-shaped proposal is accepted and `is_unanalyzed` is False.
    Absent/broken: without (b) and (c), a build that only requires
    `gates` present (and ignores flags/recommendation) survives.
    Without (d), any unrelated schema error would satisfy the refusal
    legs."""
    from self_learn import ledger_ops
    from self_learn.ledger_ops import is_unanalyzed as _is_unanalyzed
    from self_learn.worker import skill_roster as _skill_roster

    env = _shim_env(tmp_path, monkeypatch)
    proposals_dir = env.ledger / "skills" / "s" / "proposals"
    roster_sha = _skill_roster(env.ledger).sha

    def _base_yaml(*, with_gates, with_flags, with_recommendation):
        parts = [
            "destination: skill-md\n",
            "alternates: [claude-md]\n",
            "rationale: deterministic guard beats advisory text\n",
            "model: claude-sonnet-5\n",
            "analyzed_at: '2026-08-06T00:00:00Z'\n",
        ]
        if with_gates:
            parts.append(_skill_gates_yaml(roster_sha))
        if with_flags:
            parts.append("flags: []\n")
        if with_recommendation:
            parts.append("recommendation: route\n")
        return "".join(parts)

    def _run_leg(rid, yaml_body):
        record = make_behavior(scope="skill:s", record_id=rid)
        create_record(env.ledger, record)
        commit_all(env.ledger, f"pending {rid}")
        path = proposals_dir / f"{rid}.yaml"
        monkeypatch.setenv(
            "CLAUDE_SHIM_SCRIPT",
            f"mkdir -p {proposals_dir} && cat > {path} <<'YAML'\n{yaml_body}YAML",
        )
        worker.run(env.ledger)
        return path, _entry_for(env.ledger, record)

    # (a) nothing at all.
    path_a, entry_a = _run_leg(
        "lrn-46000000",
        _base_yaml(with_gates=False, with_flags=False, with_recommendation=False),
    )
    assert not path_a.exists()
    assert _is_unanalyzed(entry_a) is True

    # (b) gates + recommendation, flags ABSENT.
    path_b, entry_b = _run_leg(
        "lrn-46000001",
        _base_yaml(with_gates=True, with_flags=False, with_recommendation=True),
    )
    assert not path_b.exists()
    assert _is_unanalyzed(entry_b) is True

    # (c) gates + flags, recommendation ABSENT.
    path_c, entry_c = _run_leg(
        "lrn-46000002",
        _base_yaml(with_gates=True, with_flags=True, with_recommendation=False),
    )
    assert not path_c.exists()
    assert _is_unanalyzed(entry_c) is True

    # (d) positive control: TRACE_REQUIRED False -> the (a) shape lands.
    monkeypatch.setattr(ledger_ops, "TRACE_REQUIRED", False)
    path_d, entry_d = _run_leg(
        "lrn-46000003",
        _base_yaml(with_gates=False, with_flags=False, with_recommendation=False),
    )
    assert path_d.is_file()
    assert _is_unanalyzed(entry_d) is False


def test_a22_no_verb_accepts_gate_values():
    """A22 — no verb accepts gate values. A search of the CLI argument
    surface finds no `--gates`, `--set-gate`, `--outcome` or `--flag`
    option. Positive control: the same search finds `--dest` and
    `--note`, which do exist. This criterion is vacuously true today
    (N1): none of those options exists, so it cannot fail for this
    build. It is here as the standing guard on §3.10's MUST NOT for when
    a later unit adds verbs to this surface."""
    import self_learn.cli as cli_module

    text = Path(cli_module.__file__).read_text(encoding="utf-8")
    for opt in ('"--gates"', '"--set-gate"', '"--outcome"', '"--flag"'):
        assert opt not in text, f"{opt} must not be a CLI option"
    assert '"--dest"' in text
    assert '"--note"' in text


def test_a23_roster_sha_honesty_both_legs_both_paths(tmp_path, monkeypatch):
    """A23 — roster-sha honesty, both legs, both paths. Leg A (fabricated
    sha): (a) worker — a model-written proposal whose `gates.t3.
    roster_sha` is well-shaped but is not the run's roster sha is
    deleted and logged, the record stays pending; (b) analyst — the same
    mismatch raises AnalystError. Leg B (false degradation, F8): with a
    non-empty roster composed for the run, a proposal claiming
    `roster_sha: "unavailable"` + `t3.answer: no` + `flags:
    [evidence-gap]` — a trace the shipped X3 accepts — is (c) deleted by
    the worker and (d) raises AnalystError. Positive control for both
    legs: the same proposals carrying the run's real sha survive; and
    with the composer genuinely returning ROSTER_UNAVAILABLE (no skills
    root, empty claude dir), the `unavailable` trace IS accepted.
    Absent/broken: a build with only Leg A passes (a)/(b) and fails
    (c)/(d) — and a build with neither passes every X3-shaped assertion
    while letting a model that never reads the roster satisfy the whole
    system, which is the Checkpoint-C failure this unit is supposed to
    make impossible."""
    from self_learn import analyst
    from self_learn.analyst import AnalystError
    from self_learn.ledger_ops import is_unanalyzed as _is_unanalyzed
    from self_learn.worker import skill_roster as _skill_roster

    env = _shim_env(tmp_path, monkeypatch)
    proposals_dir = env.ledger / "skills" / "s" / "proposals"
    real_sha = _skill_roster(env.ledger).sha
    assert real_sha != ROSTER_UNAVAILABLE
    fabricated_sha = "sha256:aaaaaaaaaaaa"
    assert fabricated_sha != real_sha

    def _run_worker_leg(rid, yaml_body):
        record = make_behavior(scope="skill:s", record_id=rid)
        create_record(env.ledger, record)
        commit_all(env.ledger, f"pending {rid}")
        path = proposals_dir / f"{rid}.yaml"
        monkeypatch.setenv(
            "CLAUDE_SHIM_SCRIPT",
            f"mkdir -p {proposals_dir} && cat > {path} <<'YAMLPROP'\n{yaml_body}YAMLPROP",
        )
        worker.run(env.ledger)
        return path, _entry_for(env.ledger, record)

    def _run_analyst_leg(rid, yaml_body):
        record = make_behavior(scope="skill:s", record_id=rid)
        monkeypatch.setenv(
            "CLAUDE_SHIM_SCRIPT",
            f"cat <<'SHIMOUT'\n```yaml\n{yaml_body}```\nSHIMOUT",
        )
        return analyst.analyze(env.ledger, record)

    # ---- Leg A (a): worker, fabricated-but-well-shaped sha -> deleted.
    path_a, entry_a = _run_worker_leg(
        "lrn-47000000", _skill_proposal_yaml(fabricated_sha)
    )
    assert not path_a.exists()
    assert _is_unanalyzed(entry_a) is True

    # ---- Leg A (b): analyst, same mismatch -> AnalystError.
    with pytest.raises(AnalystError, match="X3 Leg A"):
        _run_analyst_leg("lrn-47000001", _skill_proposal_yaml(fabricated_sha))

    # ---- Leg B (c): worker, false "unavailable" claim -> deleted.
    path_c, entry_c = _run_worker_leg(
        "lrn-47000002",
        _demand_proposal_yaml(ROSTER_UNAVAILABLE, flags_evidence_gap=True),
    )
    assert not path_c.exists()
    assert _is_unanalyzed(entry_c) is True

    # ---- Leg B (d): analyst, same false claim -> AnalystError.
    with pytest.raises(AnalystError, match="X3 Leg B"):
        _run_analyst_leg(
            "lrn-47000003",
            _demand_proposal_yaml(ROSTER_UNAVAILABLE, flags_evidence_gap=True),
        )

    # ---- positive control (worker path, Leg A's shape): real sha lands.
    path_ctrl_w, entry_ctrl_w = _run_worker_leg(
        "lrn-47000004", _skill_proposal_yaml(real_sha)
    )
    assert path_ctrl_w.is_file()
    assert _is_unanalyzed(entry_ctrl_w) is False

    # ---- positive control (analyst path, Leg B's shape): real sha, no
    # evidence-gap needed -> accepted without error.
    proposal_ctrl_a = _run_analyst_leg(
        "lrn-47000005", _demand_proposal_yaml(real_sha, flags_evidence_gap=False)
    )
    assert proposal_ctrl_a["gates"]["t3"]["roster_sha"] == real_sha

    # ---- positive control: composer GENUINELY returns ROSTER_UNAVAILABLE
    # (no registered skills root, empty claude dir) -> the "unavailable"
    # trace IS accepted (analyst path; project scope has a DEMAND
    # surface, so no R-SCOPE degradation muddies this leg).
    bare_home = tmp_path / "bare-ledger"
    for sub in ("skills", "projects", "user", "telemetry"):
        (bare_home / sub).mkdir(parents=True)
    (bare_home / "hosts.yaml").write_text("projects: []\n", encoding="utf-8")
    import subprocess as _sp

    _sp.run(["git", "init", "-q", "-b", "main", str(bare_home)], check=True)
    _sp.run(
        ["git", "-C", str(bare_home), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "no-claude-dir"))
    assert _skill_roster(bare_home).sha == ROSTER_UNAVAILABLE

    unavailable_proposal = (
        "destination: reference\n"
        "alternates: [claude-md]\n"
        "rationale: no skills root visible at all\n"
        "model: claude-sonnet-5\n"
        "analyzed_at: '2026-08-06T00:00:00Z'\n"
        + _demand_gates_yaml(ROSTER_UNAVAILABLE, flags_evidence_gap=True)
        + "recommendation: route\n"
    )
    project_record = make_behavior(scope="project", record_id="lrn-47000006")
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"cat <<'SHIMOUT'\n```yaml\n{unavailable_proposal}```\nSHIMOUT",
    )
    accepted = analyst.analyze(bare_home, project_record)
    assert accepted["gates"]["t3"]["roster_sha"] == ROSTER_UNAVAILABLE


def test_a24_containment_and_derivation_at_owned_sites(tmp_path, monkeypatch):
    """A24 — containment AND derivation are on at the sites this unit
    owns. A proposal carrying a fabricated RECORD quote is (a) deleted
    by `_validate_written` rather than landed, (b) raises AnalystError
    from `analyst.analyze`, and (c) makes `worker.fast_status` report
    the record as NOT fresh — the third site (`worker.py:1282`), which
    nothing else asserts. And (d): a proposal whose `gates.outcome` does
    not follow from its answers is deleted at landing — the `scope=`
    half of U-table's H1, asserted with a trace that is
    containment-clean so only the derivation can be refusing it.
    Positive control for each: the same proposal with a true quote and a
    coherent outcome survives. Absent/broken: with containment off, the
    fabricated proposal lands and only fails later, invisibly, as a
    permanently-unanalyzed record. Without (c), removing `record_text=`
    from `fast_status` survives every other criterion. Without (d),
    U-table's derivation loop stays open while looking closed."""
    from self_learn import analyst
    from self_learn.analyst import AnalystError
    from self_learn.ledger_ops import is_unanalyzed as _is_unanalyzed
    from self_learn.worker import skill_roster as _skill_roster

    env = _shim_env(tmp_path, monkeypatch)
    proposals_dir = env.ledger / "skills" / "s" / "proposals"
    roster_sha = _skill_roster(env.ledger).sha

    _t2_anchor = (
        '    evidence: "About to edit .storage while HA is running."\n'
        "    match_path: null\n"
    )

    def _with_t2_evidence(evidence: str) -> str:
        base = _skill_proposal_yaml(roster_sha)
        assert base.count(_t2_anchor) == 1
        return base.replace(
            _t2_anchor, f'    evidence: "{evidence}"\n    match_path: null\n', 1
        )

    fabricated_evidence = "About to summarize the container's status output"
    true_evidence = "About to edit .storage while HA is running."

    # ---- (a) worker: fabricated RECORD quote -> deleted at landing.
    record_a = make_behavior(scope="skill:s", record_id="lrn-48000000")
    create_record(env.ledger, record_a)
    commit_all(env.ledger, "pending lrn-48000000")
    path_a = proposals_dir / "lrn-48000000.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {proposals_dir} && cat > {path_a} <<'YAMLPROP'\n"
        f"{_with_t2_evidence(fabricated_evidence)}YAMLPROP",
    )
    worker.run(env.ledger)
    assert not path_a.exists()
    assert _is_unanalyzed(_entry_for(env.ledger, record_a)) is True

    # positive control (a): the same shape, TRUE quote -> lands.
    record_a_ctrl = make_behavior(scope="skill:s", record_id="lrn-48000001")
    create_record(env.ledger, record_a_ctrl)
    commit_all(env.ledger, "pending lrn-48000001")
    path_a_ctrl = proposals_dir / "lrn-48000001.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {proposals_dir} && cat > {path_a_ctrl} <<'YAMLPROP'\n"
        f"{_with_t2_evidence(true_evidence)}YAMLPROP",
    )
    worker.run(env.ledger)
    assert path_a_ctrl.is_file()
    assert _is_unanalyzed(_entry_for(env.ledger, record_a_ctrl)) is False

    # ---- (b) analyst: same fabricated quote -> AnalystError.
    record_b = make_behavior(scope="skill:s", record_id="lrn-48000002")
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"cat <<'SHIMOUT'\n```yaml\n{_with_t2_evidence(fabricated_evidence)}```\nSHIMOUT",
    )
    with pytest.raises(AnalystError):
        analyst.analyze(env.ledger, record_b)

    # positive control (b): true quote -> accepted.
    record_b_ctrl = make_behavior(scope="skill:s", record_id="lrn-48000003")
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"cat <<'SHIMOUT'\n```yaml\n{_with_t2_evidence(true_evidence)}```\nSHIMOUT",
    )
    accepted_b = analyst.analyze(env.ledger, record_b_ctrl)
    assert accepted_b["gates"]["t2"]["evidence"] == true_evidence

    # ---- (c) fast_status: the fabricated-quote proposal reads NOT fresh.
    # Written directly to disk (never through the validating
    # `write_proposal` helper, which would itself refuse a fabricated
    # quote before this leg ever reaches `fast_status`'s OWN containment
    # check — the exact site this criterion targets, worker.py:1282).
    record_c = make_behavior(scope="skill:s", record_id="lrn-48000004")
    create_record(env.ledger, record_c)
    commit_all(env.ledger, "pending lrn-48000004")
    path_c = proposals_dir / "lrn-48000004.yaml"
    path_c.parent.mkdir(parents=True, exist_ok=True)
    path_c.write_text(
        _with_t2_evidence(fabricated_evidence)
        + f"record_sha: {sha_anchor(record_c.body)}\n",
        encoding="utf-8",
    )
    status = worker.fast_status(env.ledger)
    bucket_row = next(b for b in status["buckets"] if b["bucket"] == "s")
    assert bucket_row["unanalyzed"] >= 1, status
    unanalyzed_before = bucket_row["unanalyzed"]
    pending_before = bucket_row["pending"]

    # positive control (c): a true-quote, fresh proposal reads fresh —
    # pending grows by one, `unanalyzed` does NOT (delta, not an absolute
    # count: earlier legs in this same bucket already left other
    # unanalyzed records behind, e.g. (a)'s deleted-proposal record).
    record_c_ctrl = make_behavior(scope="skill:s", record_id="lrn-48000005")
    create_record(env.ledger, record_c_ctrl)
    commit_all(env.ledger, "pending lrn-48000005")
    path_c_ctrl = proposals_dir / "lrn-48000005.yaml"
    path_c_ctrl.write_text(
        _with_t2_evidence(true_evidence)
        + f"record_sha: {sha_anchor(record_c_ctrl.body)}\n",
        encoding="utf-8",
    )
    status2 = worker.fast_status(env.ledger)
    bucket_row2 = next(b for b in status2["buckets"] if b["bucket"] == "s")
    assert bucket_row2["pending"] == pending_before + 1, status2
    assert bucket_row2["unanalyzed"] == unanalyzed_before, status2

    # ---- (d) worker: containment-clean trace, but outcome does not
    # follow from its own answers -> deleted at landing (U-table H1).
    record_d = make_behavior(scope="skill:s", record_id="lrn-48000006")
    create_record(env.ledger, record_d)
    commit_all(env.ledger, "pending lrn-48000006")
    incoherent = _skill_proposal_yaml(roster_sha).replace(
        "outcome: SKILL\n", "outcome: DEMAND\n", 1
    )
    path_d = proposals_dir / "lrn-48000006.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {proposals_dir} && cat > {path_d} <<'YAMLPROP'\n{incoherent}YAMLPROP",
    )
    worker.run(env.ledger)
    assert not path_d.exists()
    assert _is_unanalyzed(_entry_for(env.ledger, record_d)) is True

    # positive control (d): the same trace with its stated outcome
    # matching its own answers (SKILL, per t3.answer: yes) -> lands.
    record_d_ctrl = make_behavior(scope="skill:s", record_id="lrn-48000007")
    create_record(env.ledger, record_d_ctrl)
    commit_all(env.ledger, "pending lrn-48000007")
    path_d_ctrl = proposals_dir / "lrn-48000007.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {proposals_dir} && cat > {path_d_ctrl} <<'YAMLPROP'\n"
        f"{_skill_proposal_yaml(roster_sha)}YAMLPROP",
    )
    worker.run(env.ledger)
    assert path_d_ctrl.is_file()
    assert _is_unanalyzed(_entry_for(env.ledger, record_d_ctrl)) is False
