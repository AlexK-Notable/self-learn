"""U-ancestry: ancestor canon inheritance, and the already-canon scan's
widened read (`docs/specs/self-learn/drafts/u-ancestry-ancestor-canon-spec.md`).

Covers the LOAD/ANC/SCAN/CARD/TEL/UN/DOC criteria that are not more
naturally exercised beside an existing suite (SCAN1/SCAN8 — the whole-file
read and the over-cap ordered-retention truncation — live in
`test_worker.py`, beside the four rewritten `canon_excerpt` tests they
supersede; ANC7/UN3 — `selfcheck._loaded_surface`'s ancestor member and its
negative control — live in `test_selftest.py`, beside the rest of the
`test_reach_*` family; CARD3 — the `already_kept` card section's render
order — lives in `ui/tests/test_card_sections.py`).

No `SELF_LEARN_WORKER_AUTOKICK`/miner env is needed here: every fixture is
built directly (`Hosts`/`save_hosts`, `create_record`, `queue()`), never
through a live worker/miner run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from self_learn import verbs, worker
from self_learn.compilers import BEGIN_MARKER, END_MARKER, compile_pointer_text
from self_learn.hosts import Hosts, ancestors_of, load_hosts, save_hosts, slug_for, unregistered_ancestor_dirs
from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import (
    bucket_project_path,
    create_record,
    ensure_project_meta,
)
from self_learn.ledger_ops import queue as _queue
from self_learn.records import Record

from support import commit_all, init_repo, make_behavior, make_env, make_knowledge


def _repo_root() -> Path:
    p = Path(__file__).resolve().parent
    for _ in range(10):
        if (p / ".git").exists():
            return p
        p = p.parent
    raise RuntimeError("repo root not found above test_u_ancestry.py")


# --------------------------------------------------------------- fixtures


def _ancestor_pair(tmp_path: Path, *, ancestor_rule: str = "Ancestor-only distinctive ANCTOKEN rule.") -> tuple[Path, Path, Path]:
    """A ledger home with TWO registered project hosts in an ancestor
    relation — `ancestor` and `ancestor/child-repo`, both real git repos
    (H-3). Returns ``(home, ancestor, child)``. Modelled on the measured
    live shape (§2.4): a single directory level apart."""
    ancestor = tmp_path / "ancestor-repo"
    init_repo(ancestor)
    (ancestor / "CLAUDE.md").write_text(
        f"# ancestor project\n\n{ancestor_rule}\n", encoding="utf-8"
    )
    commit_all(ancestor, "ancestor seed")

    child = ancestor / "child-repo"
    init_repo(child)
    (child / "CLAUDE.md").write_text(
        "# child project\n\nChild-only distinctive rule.\n", encoding="utf-8"
    )
    commit_all(child, "child seed")

    home = tmp_path / "ledger-home"
    init_repo(home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()
    save_hosts(home, Hosts(projects=[child, ancestor]))
    commit_all(home, "ledger seed")
    return home, ancestor, child


def _pending_project_entry(home: Path, host: Path, *, record_id: str = "lrn-0000a1a1"):
    """Capture a project-scope pending record under `host` and return its
    `(bucket, entry)` pair, the shape `compose_record_block`/`canon_blocks`
    consume."""
    record = make_behavior(scope="project", record_id=record_id)
    create_record(home, record, project_path=host)
    (bucket,) = [
        b
        for b in discover_buckets(home)
        if b.scope == "project" and bucket_project_path(b.path) == host.resolve()
    ]
    (entry,) = _queue(bucket)
    return bucket, entry


# =================================================================== LOAD


def test_ancestors_of_orders_nearest_first(tmp_path):
    """LOAD1: `ancestors_of` returns exactly the registered ancestors,
    NEAREST-first (longest prefix first). The fixture lists them
    FARTHEST-first in the registry (gate N12) so the assertion is on the
    ORDERED list, not a set — dropping the sort would leave this set-equal
    but list-unequal."""
    root = tmp_path / "root"
    mid = root / "mid"
    leaf = mid / "leaf"
    leaf.mkdir(parents=True)
    hosts = Hosts(projects=[root, mid])  # registered farthest-first
    assert ancestors_of(hosts, leaf) == [mid, root]


def test_ancestors_of_excludes_self_sibling_descendant(tmp_path):
    """LOAD2: never the target itself, a sibling, or a descendant. The
    `/x/a` + `/x/ab` pair (gate N12) makes the separator-less
    `startswith` bug observable on the SIBLING leg too, not only self."""
    x = tmp_path / "x"
    a = x / "a"
    ab = x / "ab"
    b_under_a = a / "b"
    b_under_a.mkdir(parents=True)
    ab.mkdir(parents=True)

    hosts = Hosts(projects=[a, ab])
    assert a not in ancestors_of(hosts, a)  # self
    assert ancestors_of(hosts, b_under_a) == [a]  # sibling `ab` excluded

    hosts_with_descendant = Hosts(projects=[a, b_under_a])
    assert b_under_a not in ancestors_of(hosts_with_descendant, a)  # descendant


def test_ancestors_of_crosses_git_boundary(tmp_path):
    """LOAD3: a registered ancestor ABOVE the child's git root is still
    returned — `ancestors_of` never consults VCS state (§2.3 measured:
    Claude Code's own ancestor walk crosses git roots)."""
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    init_repo(child)  # git init ONLY in the child — root is not a repo
    hosts = Hosts(projects=[root])
    assert ancestors_of(hosts, child) == [root]


def test_unregistered_ancestor_dirs_reports_path_only(tmp_path):
    """LOAD4: an unregistered directory carrying a `CLAUDE.md` between the
    child and its nearest REGISTERED ancestor is NOT in `ancestors_of`,
    and IS in `unregistered_ancestor_dirs` — paths only."""
    grandparent = tmp_path / "gp"
    mid = grandparent / "mid"
    leaf = mid / "leaf"
    leaf.mkdir(parents=True)
    (mid / "CLAUDE.md").write_text("mid canon, unregistered\n", encoding="utf-8")

    hosts = Hosts(projects=[grandparent])
    assert ancestors_of(hosts, leaf) == [grandparent]
    assert mid not in ancestors_of(hosts, leaf)
    assert unregistered_ancestor_dirs(hosts, leaf) == [mid]


def test_unregistered_ancestor_dirs_finds_dot_claude_form_too(tmp_path):
    """LOAD4's other half: the `.claude/CLAUDE.md` ancestor form (§2.2's
    CHARLIE case) is detected exactly like the bare form."""
    grandparent = tmp_path / "gp"
    mid = grandparent / "mid"
    leaf = mid / "leaf"
    (mid / ".claude").mkdir(parents=True)
    leaf.mkdir(parents=True)
    (mid / ".claude" / "CLAUDE.md").write_text("dot-claude canon\n", encoding="utf-8")

    hosts = Hosts(projects=[grandparent])
    assert unregistered_ancestor_dirs(hosts, leaf) == [mid]


def test_load5_decisions_row_names_the_instrument():
    """LOAD5: `03-decisions.md` records the loading rule AND names the
    instrument that produced each half — `InstructionsLoaded` hook events
    for the positives and negatives, the `nested_traversal` positive
    control, and the concatenation order/terminus as doc-sourced, "not
    measured" (matched case-insensitively — S-52 writes it "NOT
    measured").

    Code gate r1 N5: a bare `"X" in row` check tolerates a PARTIAL
    deletion — a mutation that guts most of the row's explanatory prose
    but happens to leave both bare substrings stranded next to each
    other, with no surrounding sentence of their own, would still pass
    it. S-52 is written as ONE physical markdown-table line, so there is
    no literal newline to split on; splitting the row into SENTENCES
    instead and requiring the two tokens to land in DISTINCT sentences
    proves each still carries its own explanation, not merely its own
    spelling."""
    text = (_repo_root() / "docs/specs/self-learn/03-decisions.md").read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if ln.startswith("| S-52 ")]
    assert len(rows) == 1, "expected exactly one S-52 row"
    row = rows[0]
    assert "InstructionsLoaded" in row
    assert "nested_traversal" in row
    assert "not measured" in row.lower()

    # First occurrence only -- S-52's trailing "Source" cell legitimately
    # recaps both tokens together in one closing sentence, which is not
    # the deletion this check guards against.
    sentences = row.split(". ")
    loaded_first = next(i for i, s in enumerate(sentences) if "InstructionsLoaded" in s)
    traversal_first = next(i for i, s in enumerate(sentences) if "nested_traversal" in s)
    assert loaded_first != traversal_first, (
        "InstructionsLoaded and nested_traversal must each introduce their "
        "own sentence -- a partial deletion could otherwise leave both "
        "bare tokens stranded together in what is left of a single sentence"
    )


def _function_body(path: Path, def_line: str) -> str:
    """The source text of one top-level function, from its ``def`` line
    up to (not including) the next top-level ``def``/``class`` or EOF —
    used to inspect a specific function's body in isolation rather than
    grepping the whole file (which also matches prose/comments/docstrings
    in unrelated functions, e.g. an error-message mentioning
    ``meta.yaml`` in a completely different function)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(def_line))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("def ") or lines[i].startswith("class "):
            end = i
            break
    return "\n".join(lines[start:end])


def test_load6_ancestry_is_derived_never_persisted_meta_writer_census():
    """LOAD6 leg (c): `ancestors_of` and `unregistered_ancestor_dirs` are
    pure path arithmetic — neither function's own body ever writes
    `meta.yaml` (or anything else): no `_dump_yaml` call, no
    `write_text`/`open(...` call, and no mention of the literal
    `meta.yaml` filename at all. The two real `meta.yaml` writers,
    `ledger_ops.ensure_project_meta` and `hosts._dump_meta`, both exist
    and both DO call the codebase's yaml-writing helper — confirming the
    body-extraction helper actually finds writer calls when a function
    has one, so the negative checks on the ancestry functions are a real
    discriminator, not a helper that always reads empty."""
    hosts_path = _repo_root() / "plugins/self-learn/cli/src/self_learn/hosts.py"
    ledger_ops_path = _repo_root() / "plugins/self-learn/cli/src/self_learn/ledger_ops.py"

    ensure_project_meta = _function_body(ledger_ops_path, "def ensure_project_meta(")
    dump_meta = _function_body(hosts_path, "def _dump_meta(")
    assert "_dump_yaml(" in ensure_project_meta
    assert "_dump_yaml(" in dump_meta

    ancestors_of_body = _function_body(hosts_path, "def ancestors_of(")
    unregistered_body = _function_body(hosts_path, "def unregistered_ancestor_dirs(")
    for body in (ancestors_of_body, unregistered_body):
        assert "meta.yaml" not in body
        assert "_dump_yaml(" not in body
        assert "write_text(" not in body
        assert "open(" not in body


def test_load6_bucket_identity_and_ledger_files_unchanged_across_analyst_read(tmp_path):
    """LOAD6 legs (a)/(b): `Bucket`'s identity (`(scope, name)`) is
    untouched by ancestry, and a full `sha256 + mtime` snapshot of every
    file under a two-host fixture home is BYTE-IDENTICAL before and after
    the analyst's read path (`compose_batch_prompt`, which calls
    `ancestors_of`/`unregistered_ancestor_dirs`/`canon_blocks` internally)
    runs over it."""
    import hashlib

    home, ancestor, child = _ancestor_pair(tmp_path)
    bucket, entry = _pending_project_entry(home, child)
    assert (bucket.scope, bucket.name) == ("project", slug_for(child))

    def snapshot() -> dict[str, tuple[str, int]]:
        out = {}
        for path in sorted(home.rglob("*")):
            if path.is_file():
                st = path.stat()
                out[str(path.relative_to(home))] = (
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    st.st_mtime_ns,
                )
        return out

    before = snapshot()
    worker.compose_batch_prompt(home, [entry])  # the analyst read path
    after = snapshot()

    assert before == after
    assert (bucket.scope, bucket.name) == ("project", slug_for(child))


# ==================================================================== ANC


def test_canon_blocks_ancestor(tmp_path):
    """ANC1: for a project record whose host has a registered ancestor,
    `canon_blocks` contains a block headed by the ancestor's absolute
    `CLAUDE.md` path and labelled `inherited`."""
    home, ancestor, child = _ancestor_pair(tmp_path)
    _bucket, entry = _pending_project_entry(home, child)

    blocks = worker.canon_blocks(home, entry.record, entry.bucket_dir)
    ancestor_target = str((ancestor / "CLAUDE.md").resolve())
    assert ancestor_target in blocks
    assert "(inherited — loads in every session under this host)" in blocks
    assert "Ancestor-only distinctive ANCTOKEN rule." in blocks


def test_ancestor_blocks_nearest_first_and_capped(tmp_path):
    """ANC2: ancestor blocks are nearest-first and at most
    `ANCESTOR_DEPTH_CAP` — a fixture with THREE registered ancestors above
    the child proves the cap, not just the order."""
    great = tmp_path / "great"
    grand = great / "grand"
    parent = grand / "parent"
    child = parent / "child"
    for d in (great, grand, parent, child):
        init_repo(d)
    (great / "CLAUDE.md").write_text("great rule GREATTOKEN\n", encoding="utf-8")
    (grand / "CLAUDE.md").write_text("grand rule GRANDTOKEN\n", encoding="utf-8")
    (parent / "CLAUDE.md").write_text("parent rule PARENTTOKEN\n", encoding="utf-8")
    (child / "CLAUDE.md").write_text("child rule CHILDTOKEN\n", encoding="utf-8")
    # Commit INNERMOST first: a nested repo with zero commits makes the
    # outer repo's `git add -A` fail ("does not have a commit checked
    # out"), so the commit order must invert the directory nesting order.
    for d in (child, parent, grand, great):
        commit_all(d, "seed")

    home = tmp_path / "ledger-home"
    init_repo(home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()
    save_hosts(home, Hosts(projects=[child, parent, grand, great]))
    commit_all(home, "ledger seed")

    hosts = load_hosts(home)
    assert ancestors_of(hosts, child) == [parent, grand, great]  # nearest-first, all three

    _bucket, entry = _pending_project_entry(home, child)
    blocks = worker.canon_blocks(home, entry.record, entry.bucket_dir)

    assert "PARENTTOKEN" in blocks
    assert "GRANDTOKEN" in blocks
    assert "GREATTOKEN" not in blocks  # beyond ANCESTOR_DEPTH_CAP (2)
    # nearest-first ordering in the composed text
    assert blocks.index("PARENTTOKEN") < blocks.index("GRANDTOKEN")


def test_canon_blocks_no_ancestor_offproject_scopes(tmp_path, monkeypatch):
    """ANC3: skill- and user-scope records get NO ancestor block, even
    when a registered host sits at the parent of the user-scope surface
    (gate N13 — otherwise no registered host is a proper prefix of
    `~/.claude` and the guard's absence goes unobserved on that leg)."""
    fake_home = tmp_path / "fake-home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "CLAUDE.md").write_text("user canon\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))

    ledger = tmp_path / "ledger-home"
    init_repo(ledger)
    for sub in ("skills", "projects", "user", "telemetry"):
        (ledger / sub).mkdir()
    # A registered host at the PARENT of the user-scope surface (fake_home
    # itself) — the only way to make ANC3's user leg observable.
    parent_host = fake_home
    init_repo(parent_host)
    (parent_host / "CLAUDE.md").write_text("host canon\n", encoding="utf-8")
    commit_all(parent_host, "seed")
    save_hosts(ledger, Hosts(projects=[parent_host]))
    commit_all(ledger, "ledger seed")

    user_record = make_knowledge(scope="user", record_id="lrn-00000bb1")
    create_record(ledger, user_record)
    blocks = worker.canon_blocks(ledger, user_record, ledger / "user")
    assert "inherited" not in blocks

    # Skill scope: skills_root is itself a registered project host, so
    # every SKILL.md already has a registered proper prefix — no help
    # fixture needed for this leg.
    env = make_env(tmp_path / "skillside", skills=("s",))
    skill_record = make_behavior(scope="skill:s", record_id="lrn-00000bb2")
    create_record(env.ledger, skill_record)
    (bucket,) = [b for b in discover_buckets(env.ledger) if b.name == "s"]
    (entry,) = _queue(bucket)
    skill_blocks = worker.canon_blocks(env.ledger, entry.record, entry.bucket_dir)
    assert "inherited" not in skill_blocks


def test_resolve_target_unchanged_under_ancestry(tmp_path):
    """ANC4: no WRITE target is derived from an ancestor —
    `_resolve_target`'s returned `TargetSpec` is byte-identical for the
    same (scope, destination, ref_name) triple whether or not the host
    has a registered ancestor."""
    home, ancestor, child = _ancestor_pair(tmp_path)
    record = make_behavior(scope="project", record_id="lrn-0000a4a4")
    create_record(home, record, project_path=child)
    (bucket,) = [b for b in discover_buckets(home) if b.scope == "project"]

    spec_with_ancestor = verbs._resolve_target(
        home, bucket.path, "project", "claude-md", None,
        check_dirty=False, project_path=child,
    )

    # Now drop the ancestor registration and re-resolve.
    save_hosts(home, Hosts(projects=[child]))
    spec_without_ancestor = verbs._resolve_target(
        home, bucket.path, "project", "claude-md", None,
        check_dirty=False, project_path=child,
    )

    assert spec_with_ancestor == spec_without_ancestor
    assert spec_with_ancestor.target == (child / "CLAUDE.md").resolve() or spec_with_ancestor.target == child / "CLAUDE.md"


def test_canon_blocks_unregistered_ancestor_path_only(tmp_path):
    """ANC5: an unregistered ancestor directory with a `CLAUDE.md` yields
    a PATH-ONLY line in `canon_blocks`' output — its distinctive content
    never appears anywhere in the composed block."""
    grandparent = tmp_path / "gp"
    mid = grandparent / "mid"
    child = mid / "child"
    for d in (grandparent, mid, child):
        init_repo(d)
    (grandparent / "CLAUDE.md").write_text("grandparent canon\n", encoding="utf-8")
    (mid / "CLAUDE.md").write_text(
        "UNREGISTERED-MID-DISTINCTIVE-CONTENT should never be read\n", encoding="utf-8"
    )
    (child / "CLAUDE.md").write_text("child canon\n", encoding="utf-8")
    # Innermost first — see the sibling fixture's comment above.
    for d in (child, mid, grandparent):
        commit_all(d, "seed")

    home = tmp_path / "ledger-home"
    init_repo(home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()
    save_hosts(home, Hosts(projects=[child, grandparent]))  # `mid` deliberately unregistered
    commit_all(home, "ledger seed")

    _bucket, entry = _pending_project_entry(home, child, record_id="lrn-0000a5a5")
    blocks = worker.canon_blocks(home, entry.record, entry.bucket_dir)

    assert "UNREGISTERED-MID-DISTINCTIVE-CONTENT" not in blocks
    assert f"unregistered ancestor with a CLAUDE.md: {mid}" in blocks
    assert "not read" in blocks


def test_pointer_prose_names_its_base():
    """ANC8: a pointer block written into a host with a registered
    ancestor OR descendant gains the verbatim base-naming sentence; a
    host with neither does not. The TOKEN grammar is untouched —
    `compile_pointer_text`'s `line` argument and its position in the
    block are identical either way; only the surrounding PREAMBLE
    differs."""
    line = "- `references/LEARNINGS.md` — captured lessons for this project"
    sentence = (
        "paths are relative to the directory containing this file, not "
        "your working directory"
    )

    with_base, _ = compile_pointer_text("", line, names_base=True)
    assert sentence in with_base

    without_base, _ = compile_pointer_text("", line, names_base=False)
    assert sentence not in without_base
    # the token itself is byte-identical either way
    assert line in with_base
    assert line in without_base


def test_pointer_names_base_predicate_and_end_to_end_emission(tmp_path):
    """ANC8, the EMISSION path (code gate r1 M-1): the unit test above
    only drives `compile_pointer_text` by hand -- nothing exercised the
    PREDICATE (`verbs._pointer_names_base`) or the real `_apply_target`/
    `route` call site that decides its argument, and nothing asserted
    the NEGATIVE half (a host with neither a registered ancestor nor a
    registered descendant keeps today's byte-identical block). Both legs
    here close that gap; M23 (emit the sentence for every host,
    ancestor or not) reddens this test's negative assertions.

    Three registered project hosts: `ancestor` and `ancestor/child-repo`
    (a real ancestor/descendant pair) plus `standalone`, unrelated to
    either. Leg 1 checks the predicate directly, via a REAL `TargetSpec`
    from `_resolve_target` (never hand-built) for each host. Leg 2 routes
    an actual `reference` record on each host through `verbs.route` --
    the real call site -- and reads the freshly written CLAUDE.md back
    off disk."""


    ancestor = tmp_path / "ancestor-repo"
    init_repo(ancestor)
    (ancestor / "CLAUDE.md").write_text("# ancestor project\n", encoding="utf-8")
    commit_all(ancestor, "ancestor seed")

    child = ancestor / "child-repo"
    init_repo(child)
    (child / "CLAUDE.md").write_text("# child project\n", encoding="utf-8")
    commit_all(child, "child seed")

    standalone = tmp_path / "standalone-repo"
    init_repo(standalone)
    (standalone / "CLAUDE.md").write_text("# standalone project\n", encoding="utf-8")
    commit_all(standalone, "standalone seed")

    home = tmp_path / "ledger-home"
    init_repo(home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()
    save_hosts(home, Hosts(projects=[child, ancestor, standalone]))
    commit_all(home, "ledger seed")

    sentence = (
        "paths are relative to the directory containing this file, not "
        "your working directory"
    )

    # Leg 1: the predicate, via a REAL resolved TargetSpec per host.
    for host, expected in ((ancestor, True), (child, True), (standalone, False)):
        bucket_dir = home / "projects" / slug_for(host)
        spec = verbs._resolve_target(
            home, bucket_dir, "project", "reference", None,
            check_dirty=False, project_path=host,
        )
        assert verbs._pointer_names_base(home, spec) is expected, host

    # Leg 2: end-to-end through the real `route` call site.
    for host in (ancestor, child, standalone):
        rec = make_knowledge(
            scope="project",
            record_id=f"lrn-{slug_for(host)[-8:]}",
            fact=f"A distinctive fact routed for {host.name}.",
        )
        create_record(home, rec, project_path=host)
        verbs.route(home, rec.id, dest="reference", no_push=True)
        claude_md = (host / "CLAUDE.md").read_text(encoding="utf-8")
        if host is standalone:
            assert sentence not in claude_md, host
        else:
            assert sentence in claude_md, host


# =================================================================== SCAN


def test_canon_blocks_references_project_scope_labelled(tmp_path):
    """SCAN2/SCAN3: the project references block appears, sorted, capped,
    and carries the verbatim `(captured, NOT loaded — pointer-reached;
    not eligible for g0.canon)` label."""
    env = make_env(tmp_path)
    (env.host / "references").mkdir()
    (env.host / "references" / "LEARNINGS.md").write_text(
        "## captured lesson ZEBRA\n", encoding="utf-8"
    )
    (env.host / "references" / "OTHER.md").write_text(
        "## captured lesson ALPHA\n", encoding="utf-8"
    )
    record = make_behavior(scope="project", record_id="lrn-00000bc1")
    create_record(env.ledger, record, project_path=env.host)
    (bucket,) = [b for b in discover_buckets(env.ledger) if b.scope == "project"]
    (entry,) = _queue(bucket)

    blocks = worker.canon_blocks(env.ledger, entry.record, entry.bucket_dir)
    assert "ZEBRA" in blocks
    assert "ALPHA" in blocks
    assert "(captured, NOT loaded — pointer-reached; not eligible for g0.canon)" in blocks
    # sorted: LEARNINGS.md before OTHER.md alphabetically... OTHER < LEARNINGS
    # is false; assert the actual sort order directly.
    assert blocks.index(str(env.host / "references" / "LEARNINGS.md")) < blocks.index(
        str(env.host / "references" / "OTHER.md")
    )


def test_canon_blocks_references_skill_scope_labelled(tmp_path):
    """SCAN2: the skill-scope references block resolves under the SKILL
    directory, same label."""
    env = make_env(tmp_path, skills=("s",))
    (env.skill_dir / "references").mkdir()
    (env.skill_dir / "references" / "LEARNINGS.md").write_text(
        "## captured skill lesson OKAPI\n", encoding="utf-8"
    )
    record = make_behavior(scope="skill:s", record_id="lrn-00000bc2")
    create_record(env.ledger, record)
    (bucket,) = [b for b in discover_buckets(env.ledger) if b.name == "s"]
    (entry,) = _queue(bucket)

    blocks = worker.canon_blocks(env.ledger, entry.record, entry.bucket_dir)
    assert "OKAPI" in blocks
    assert "(captured, NOT loaded — pointer-reached; not eligible for g0.canon)" in blocks


def test_canon_blocks_references_absent_at_user_scope(tmp_path, monkeypatch):
    """SCAN2: user scope emits NO references block at all — S-23 rules
    user scope has no references dir; the absence is correct output, not
    a degraded one, so no sentinel line is emitted either."""
    fake_home = tmp_path / "fake-home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "CLAUDE.md").write_text("user canon\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))

    record = make_knowledge(scope="user", record_id="lrn-00000bc3")
    blocks = worker.canon_blocks(tmp_path, record, tmp_path / "bucket")
    # Not a blanket "references" substring check: pytest's own tmp_path
    # naming embeds this test function's name (which contains the word
    # "references") into the fixture's absolute paths, and those paths
    # legitimately appear in the emitted `### <path> (...)` headers — a
    # bare substring check would flag that as a false positive. Check for
    # the specific references-block markers instead: the verbatim label
    # and a `references/`-shaped path component in any block header.
    assert "captured, NOT loaded" not in blocks
    assert "(captured, NOT loaded — pointer-reached; not eligible for g0.canon)" not in blocks
    assert not re.search(r"^### .*/references/", blocks, re.MULTILINE)


def test_canon_blocks_reads_nothing_outside_canon_roots(tmp_path):
    """SCAN4: nothing outside `canon_read_roots`' project family is ever
    read — a host carrying `docs/known-issues.md`, `README.md`,
    `src/x.md` AND `CLAUDE.local.md`, each with a distinct sentinel,
    contributes NONE of them to the composed canon blocks."""
    env = make_env(tmp_path)
    (env.host / "docs").mkdir()
    (env.host / "docs" / "known-issues.md").write_text("SENTINEL-DOCS-KI\n", encoding="utf-8")
    (env.host / "README.md").write_text("SENTINEL-README\n", encoding="utf-8")
    (env.host / "src").mkdir()
    (env.host / "src" / "x.md").write_text("SENTINEL-SRC-X\n", encoding="utf-8")
    (env.host / "CLAUDE.local.md").write_text("SENTINEL-LOCAL\n", encoding="utf-8")

    record = make_behavior(scope="project", record_id="lrn-00000bd1")
    create_record(env.ledger, record, project_path=env.host)
    (bucket,) = [b for b in discover_buckets(env.ledger) if b.scope == "project"]
    (entry,) = _queue(bucket)

    blocks = worker.canon_blocks(env.ledger, entry.record, entry.bucket_dir)
    for sentinel in ("SENTINEL-DOCS-KI", "SENTINEL-README", "SENTINEL-SRC-X", "SENTINEL-LOCAL"):
        assert sentinel not in blocks


def test_canon_bytes_logged_per_record_and_batch(tmp_path, monkeypatch):
    """SCAN5: `canon_bytes` is logged per record and per batch, and a cap
    that fires is logged, never raised. Positive control: an over-cap
    fixture logs a non-zero drop."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    env = make_env(tmp_path)
    (env.host / "references").mkdir()
    # BR-1 drops references blocks last-first once the RECORD cap
    # (CANON_BYTES_PER_RECORD) is exceeded — but each individual block is
    # already truncated to CANON_BYTES_PER_FILE by `_canon_block` before
    # the record-level check ever sees it, so a SINGLE oversized file
    # never trips it (it retains exactly CANON_BYTES_PER_FILE either
    # way). Use several files each near the per-file cap instead, so
    # their SUMMED retained bytes clear the per-record cap.
    per_file = "x" * (worker.CANON_BYTES_PER_FILE - 1)
    n_files = (worker.CANON_BYTES_PER_RECORD // worker.CANON_BYTES_PER_FILE) + 2
    for i in range(n_files):
        (env.host / "references" / f"BIG{i}.md").write_text(per_file, encoding="utf-8")
    record = make_behavior(scope="project", record_id="lrn-00000bd2")
    create_record(env.ledger, record, project_path=env.host)
    (bucket,) = [b for b in discover_buckets(env.ledger) if b.scope == "project"]
    (entry,) = _queue(bucket)

    worker.canon_blocks(env.ledger, entry.record, entry.bucket_dir)  # must not raise

    log_path = worker.cache_dir() / "worker.log"
    log_text = log_path.read_text(encoding="utf-8")
    lines = [ln for ln in log_text.splitlines() if f"canon_bytes record={record.id}" in ln]
    assert lines, log_text
    m = re.search(r"dropped_record_cap=(\d+)", lines[-1])
    assert m is not None and int(m.group(1)) > 0

    worker.compose_batch_prompt(env.ledger, [entry])
    batch_lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if "canon_bytes batch" in ln]
    assert batch_lines


def test_hand_written_canon_needs_card_and_flag(tmp_path):
    """SCAN6 (HW-1): a `g0.canon.target` naming a region OUTSIDE a managed
    section, without the `already_kept` card section OR without the
    `canon-hand-written` flag, is refused by `proposal validate` (rc 1) —
    dropping either half of the conjunction reddens this. Code gate r1
    D3: the fixture's card uses the REAL registry key (`already_kept`,
    CARD1's own entry) rather than a synthetic placeholder, asserted
    explicitly below -- the validator's own check is deliberately
    generic (any non-empty `card` entry, matching `_validate_card`'s
    established "the section SET is the registry's business, not this
    module's" precedent, and CARD2's own no-hardcoded-key requirement),
    so this test's job is to prove the REAL key satisfies HW-1 in
    practice, not that the validator special-cases it by name."""
    from self_learn.ledger_ops import ProposalError, validate_proposal
    from support import proposal_dict

    host = tmp_path / "host"
    init_repo(host)
    lines = [f"hand-written line {i}" for i in range(50)]
    lines[10] = "the covering hand-written rule lives here"
    text = "\n".join(lines) + "\n"
    (host / "CLAUDE.md").write_text(text, encoding="utf-8")
    commit_all(host, "seed")
    target = f"{(host / 'CLAUDE.md').resolve()}:11"

    base = proposal_dict(scope="project", destination="claude-md")
    base["gates"]["g0"]["canon"] = {
        "answer": "yes",
        "evidence": "the covering hand-written rule lives here",
        "target": target,
    }
    base["already_canon"] = True

    home = tmp_path / "ledger"
    init_repo(home)

    # Missing BOTH card and flag.
    with pytest.raises(ProposalError, match="HW-1"):
        validate_proposal(dict(base), home=home)

    # Flag present, card missing — still refused.
    with_flag = dict(base)
    with_flag["flags"] = ["canon-hand-written"]
    with pytest.raises(ProposalError, match="HW-1"):
        validate_proposal(with_flag, home=home)

    # Card present, flag missing — still refused.
    with_card = dict(base)
    with_card["card"] = {"already_kept": "It loads: host CLAUDE.md line 11."}
    assert "already_kept" in with_card["card"]  # D3: the real registry key, not a placeholder
    with pytest.raises(ProposalError, match="HW-1"):
        validate_proposal(with_card, home=home)

    # BOTH present — accepted (no HW-1 refusal for this leg).
    both = dict(base)
    both["flags"] = ["canon-hand-written"]
    both["card"] = {"already_kept": "It loads: host CLAUDE.md line 11."}
    assert "already_kept" in both["card"]  # D3: the real registry key, not a placeholder
    validate_proposal(both, home=home)  # must not raise


def test_no_autograduate_on_hand_written_hit(tmp_path):
    """SCAN7: no verb auto-resolves on a hand-written hit — `graduate`
    still requires an explicit human invocation and `already_canon: true`.
    Two legs (code gate r1 N1 added the second): a structural check that
    `verbs.route`'s own body never references `graduate(`/`canon-hand-
    written` at all (route() takes no proposal argument through which
    either could even reach it -- this leg proves that absence directly,
    not merely by grep), plus a BEHAVIOURAL one -- a real hand-written-hit
    proposal (flag + card, HW-1-passing), written via the real
    `write_proposal`, then applied via the real `route(dest=...)` call a
    human/UI issues after reading it -- and the resulting record is
    checked on disk: `status == "routed"`, `superseded_by is None`. A
    silent auto-graduate would show up as `superseded_by == "canon"`."""
    src = (_repo_root() / "plugins/self-learn/cli/src/self_learn/verbs.py").read_text(
        encoding="utf-8"
    )
    route_fn = re.search(r"\ndef route\(.*?\n(?=\ndef |\Z)", src, re.S)
    assert route_fn is not None
    assert "graduate(" not in route_fn.group(0)
    assert "canon-hand-written" not in route_fn.group(0)

    # Behavioural leg.
    from self_learn.ledger_ops import write_proposal
    from self_learn.records import Record
    from support import proposal_dict

    host = tmp_path / "host"
    init_repo(host)
    lines = [f"hand-written line {i}" for i in range(50)]
    lines[10] = "the covering hand-written rule lives here"
    (host / "CLAUDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    commit_all(host, "seed")
    target = f"{(host / 'CLAUDE.md').resolve()}:11"

    home = tmp_path / "ledger"
    init_repo(home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()
    save_hosts(home, Hosts(projects=[host]))

    record = make_behavior(scope="project", record_id="lrn-000005c7")
    create_record(home, record, project_path=host)

    both = proposal_dict(scope="project", destination="claude-md")
    both["gates"]["g0"]["canon"] = {
        "answer": "yes",
        "evidence": "the covering hand-written rule lives here",
        "target": target,
    }
    both["gates"]["outcome"] = "GRADUATE"  # Table-1: g0.canon "yes" derives GRADUATE
    both["recommendation"] = "graduate"  # R-FALL: GRADUATE outcome renders "graduate"
    both["already_canon"] = True
    both["flags"] = ["canon-hand-written"]
    both["card"] = {"already_kept": "It loads: host CLAUDE.md line 11."}
    write_proposal(home, record.id, both)  # must not raise -- HW-1's conjunction is satisfied

    verbs.route(home, record.id, dest="claude-md", no_push=True)

    resolved = next((home / "projects").glob(f"*/resolved/{record.id}.md"))
    routed = Record.from_path(resolved)
    assert routed.status == "routed"
    assert routed.superseded_by is None


# ==================================================================== CARD


def test_card1_already_kept_registered():
    from ruamel.yaml import YAML

    yaml = YAML(typ="rt")
    data = yaml.load(worker.package_skill_refs().joinpath("card-sections.yaml").read_text())
    assert data["already_kept"]["order"] == 35
    assert data["already_kept"]["required"] == "optional"


def test_card2_no_surface_hardcodes_the_key():
    """CARD2: no surface names the key — including command prose. The
    same grep for `conflict` returning hits (positive control: `review.md`
    among them) proves the grep can see command prose."""
    import subprocess

    root = _repo_root()
    proc = subprocess.run(
        [
            "grep", "-rn", "already_kept",
            "plugins/self-learn/ui/src", "plugins/self-learn",
            "--include=*.py", "--include=*.md",
        ],
        cwd=root, capture_output=True, text=True,
    )
    # Exclude the registry file itself (the one place the key MUST be
    # named) and test directories: test files legitimately construct
    # fixtures using the literal key (e.g. `test_hand_written_canon_
    # needs_card_and_flag`'s `card = {"already_kept": ...}` above) — they
    # exercise the registry's contract, they are not a rendering surface
    # in the doctrine's sense, and CARD2 is about surfaces.
    hits = [
        ln
        for ln in proc.stdout.splitlines()
        if "references/card-sections.yaml" not in ln
        and "/tests/" not in ln
        and not ln.startswith("tests/")
    ]
    assert hits == [], hits

    control = subprocess.run(
        [
            "grep", "-rln", "conflict",
            "plugins/self-learn/ui/src", "plugins/self-learn",
            "--include=*.py", "--include=*.md",
        ],
        cwd=root, capture_output=True, text=True,
    )
    assert "plugins/self-learn/commands/review.md" in control.stdout


def test_references_hit_is_not_already_canon(tmp_path):
    """CARD4: a `g0.canon.target` resolving inside `<host>/references/`
    is refused by `proposal validate` (rc 1) — a references hit is the
    `already_kept` shelf signal, never `g0.canon` evidence."""
    from self_learn.ledger_ops import ProposalError, validate_proposal
    from support import proposal_dict

    host = tmp_path / "host"
    init_repo(host)
    (host / "references").mkdir()
    (host / "references" / "LEARNINGS.md").write_text("## an entry\n", encoding="utf-8")
    commit_all(host, "seed")
    target = f"{(host / 'references' / 'LEARNINGS.md').resolve()}:1"

    base = proposal_dict(scope="project", destination="claude-md")
    base["gates"]["g0"]["canon"] = {
        "answer": "yes",
        "evidence": "an entry",
        "target": target,
    }
    base["already_canon"] = True

    with pytest.raises(ProposalError, match="CARD4|references/"):
        validate_proposal(base)  # even with no `home` — CARD4 is lexical, unconditional


# ===================================================================== TEL


def test_fire_crosses_host_boundary(tmp_path):
    """TEL1: a `fire … outcome: violated` naming an ANCESTOR-bucket
    record, observed while mining a CHILD-host session, raises the
    `recurrence-suspect` against that ancestor record — `miner._canon_index`
    already iterates every bucket, so this is a no-regression assertion."""
    from self_learn import miner

    home, ancestor, child = _ancestor_pair(tmp_path)
    ancestor_record = make_behavior(scope="project", record_id="lrn-00000be1")
    ancestor_record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "claude-md", "by": "human"}
    )
    ancestor_record.set_status("routed")
    (bucket_dir := home / "projects" / slug_for(ancestor)).mkdir(parents=True)
    ensure_project_meta(bucket_dir, ancestor)
    (bucket_dir / "resolved").mkdir()
    ancestor_record.write(bucket_dir / "resolved" / f"{ancestor_record.id}.md")

    index = miner._canon_index(home)
    assert ancestor_record.id in index, "the ancestor-bucket record must be indexable from ANY session"


def test_recurrence_suspects_same_bucket_only(tmp_path):
    """TEL2: `worker._recurrence_suspects` still compares only within
    `entry.bucket_dir / "resolved"` — this unit does NOT widen it.
    Positive control: an ancestor-bucket routed record with 1.0 title
    overlap against a CHILD pending record raises 0 suspects."""
    home, ancestor, child = _ancestor_pair(tmp_path)

    routed = make_behavior(
        scope="project", record_id="lrn-00000be2", trigger="A very distinctive shared trigger phrase"
    )
    routed.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "claude-md", "by": "human"}
    )
    routed.set_status("routed")
    (ancestor_bucket := home / "projects" / slug_for(ancestor)).mkdir(parents=True)
    ensure_project_meta(ancestor_bucket, ancestor)
    (ancestor_bucket / "resolved").mkdir()
    routed.write(ancestor_bucket / "resolved" / f"{routed.id}.md")

    pending = make_behavior(
        scope="project", record_id="lrn-00000be3", trigger="A very distinctive shared trigger phrase"
    )
    create_record(home, pending, project_path=child)
    (child_bucket,) = [
        b for b in discover_buckets(home)
        if b.scope == "project" and bucket_project_path(b.path) == child.resolve()
    ]
    (entry,) = _queue(child_bucket)

    n = worker._recurrence_suspects(home, [entry])
    assert n == 0


# ====================================================================== UN


def test_un_no_ancestor_block(tmp_path):
    """UN1: for a record in a no-ancestor host, `canon_blocks` emits
    EXACTLY one block header -- the own-host `### <path> (...)` line --
    and nothing else. Tightened (code gate r1 M-2) from a substring
    absence check (`"inherited" not in blocks`) to the exact header SET:
    a label-free `### (ancestors)`-shaped header carrying no `inherited`
    text would satisfy the old check while still leaking a second block
    into the composed prompt."""
    env = make_env(tmp_path)
    record = make_behavior(scope="project", record_id="lrn-00000ba1")
    create_record(env.ledger, record, project_path=env.host)
    (bucket,) = [b for b in discover_buckets(env.ledger) if b.scope == "project"]
    (entry,) = _queue(bucket)

    blocks = worker.canon_blocks(env.ledger, entry.record, entry.bucket_dir)
    claude_md = env.host / "CLAUDE.md"
    expected_header = f"### {claude_md} ({len(claude_md.read_bytes())} B)"
    headers = re.findall(r"^### .*$", blocks, re.MULTILINE)
    assert headers == [expected_header]


def test_un_block_sha_unchanged(tmp_path):
    """UN2: for a synthetic host whose `CLAUDE.md` is 100% managed
    section and whose `references/` is absent, `canon_blocks`' entire
    output is byte-identical to a REAL baseline -- never a second call
    to (possibly mutated) current code. Code gate r1 M-2: the prior
    two-fixture self-comparison passed with M19's leaked, unconditional
    ancestor header present in BOTH runs -- deterministic code compared
    only to itself can never catch a deterministic regression, since the
    leak shows up identically on both sides and cancels out.

    The baseline is DERIVED, not guessed, from base commit `0e96a91`
    (`git show 0e96a91:plugins/self-learn/cli/src/self_learn/worker.py`
    -- read directly for this derivation, not executed): `canon_excerpt`
    (that file's line 1309) returns a target's content UNWRAPPED -- no
    header, no ancestor block, no references block -- whenever the file
    is under 200 lines; this fixture (`zmk-config-offsetkey`'s live
    shape, 3 lines) is squarely that case, so base's own-host content is
    fully known without running anything. SCAN1 (this same unit)
    universally wraps every own-host block in a `### <path> (<N> B)`
    header, ancestor or not -- that wrapper is an intended, ancestry-
    independent change and is NOT what UN2 exists to catch, so it is
    part of the expected value, not stripped from it. One further byte
    -level note, since this pins content exactly: base's `"\n".join
    (lines)` drops a trailing newline that `Path.read_text()` (what
    `_canon_block` actually calls) does not -- `expected_content` below
    uses the real `read_text()` value, matching current code's actual,
    correct behaviour rather than replicating base's line-stripping.
    With the header and the content both fully determined, the ENTIRE
    expected `canon_blocks` return value is a closed-form string --
    any further text (an ancestor block, an unregistered-ancestor line,
    a references block) is a deviation this equality catches directly."""
    from self_learn.compilers import compile_managed_text

    env = make_env(tmp_path)
    routed = make_behavior(record_id="lrn-00000ba2")
    routed.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "claude-md", "by": "human"}
    )
    routed.set_status("routed")
    compiled = compile_managed_text("", [routed])
    claude_md = env.host / "CLAUDE.md"
    claude_md.write_text(compiled.text, encoding="utf-8")
    # Base's own branch guard (`len(lines) < 200`) -- confirms this
    # fixture is squarely the unwrapped-content case the derivation
    # above relies on.
    assert len(claude_md.read_text(encoding="utf-8").splitlines()) < 200

    record = make_behavior(scope="project", record_id="lrn-00000ba3")
    create_record(env.ledger, record, project_path=env.host)
    (bucket,) = [b for b in discover_buckets(env.ledger) if b.scope == "project"]
    (entry,) = _queue(bucket)

    blocks = worker.canon_blocks(env.ledger, entry.record, entry.bucket_dir)

    expected_header = f"### {claude_md} ({len(claude_md.read_bytes())} B)"
    expected_content = claude_md.read_text(encoding="utf-8")
    expected = f"{expected_header}\n{expected_content}"
    assert blocks == expected


# ===================================================================== DOC


def test_doc1_decisions_row_present():
    text = (_repo_root() / "docs/specs/self-learn/03-decisions.md").read_text(encoding="utf-8")
    assert len([ln for ln in text.splitlines() if ln.startswith("| S-52 ")]) == 1


def test_doc2_forward_work_map_rows_present():
    text = (_repo_root() / "docs/specs/self-learn/14-forward-work-map.md").read_text(encoding="utf-8")
    for fw in ("FW-125", "FW-126", "FW-127"):
        assert len([ln for ln in text.splitlines() if ln.startswith(f"| {fw} ")]) == 1, fw


def test_doc3_doctrine_amendment_lands_in_three_sections():
    text = (
        _repo_root()
        / "plugins/self-learn/skills/self-learn/references/routing-doctrine.md"
    ).read_text(encoding="utf-8")

    def section(start_pat: str, end_pat: str) -> str:
        m = re.search(start_pat, text, re.MULTILINE)
        assert m is not None, start_pat
        rest = text[m.end():]
        e = re.search(end_pat, rest, re.MULTILINE)
        return rest[: e.start()] if e else rest

    g0_section = section(r"^## 2\. The gate procedure", r"^## 2a\.")
    tier_section = section(r"^## 3\. The tier model", r"^## 4\.")
    conv_section = section(r"^## 4\. Repo conventions", r"^## 5\.")

    assert "ancestor host" in g0_section
    assert "ancestor host" in tier_section
    assert "ancestor host" in conv_section


def test_doc4_deployed_skill_is_a_symlink():
    """DOC4: `~/.claude/skills/self-learn` is a LIVE symlink (not a
    copy), and it resolves to a `plugins/self-learn/skills/self-learn`
    directory OUTSIDE any worktree. Not asserted against `_repo_root()`
    (this test's own worktree copy) -- a builder's worktree and the
    live checkout that symlink correctly targets are two different
    directories on disk ("working tree is production": `~/bin/self-learn`
    runs the MAIN repo's working tree, never a build worktree's copy),
    so a byte-for-byte path match here would fail even when the
    deployment is completely correct."""
    deployed = Path("~/.claude/skills/self-learn").expanduser()
    assert deployed.is_symlink()
    target = deployed.resolve()
    assert str(target).endswith("plugins/self-learn/skills/self-learn"), target
    assert ".claude/worktrees" not in str(target), target


def test_doc5_u_marker_supersession_note():
    marker_spec = (
        _repo_root() / "docs/specs/self-learn/drafts/u-marker-excerpt-case-spec.md"
    ).read_text(encoding="utf-8")
    assert "Superseded in part by S-52" in marker_spec

    fwmap = (_repo_root() / "docs/specs/self-learn/14-forward-work-map.md").read_text(
        encoding="utf-8"
    )
    fw44_row = next(ln for ln in fwmap.splitlines() if ln.startswith("| FW-44 "))
    assert "S-52" in fw44_row
