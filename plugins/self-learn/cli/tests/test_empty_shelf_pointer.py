"""An emptied shelf loses its pointer (S-77 (3) as amended, 2026-10-07).

A shelf is a project's or a skill's `references/LEARNINGS.md` (or a named
references file), reached through one line in the pointer block
(`<!-- self-learn:pointers:begin ... -->`) of the always-loaded CLAUDE.md or
SKILL.md. Until this change, a shelf whose last entry left kept that line
and the block around it -- about eight lines in every session, pointing at
a file holding nothing but its header. The user, 2026-10-07: "yeah, makes
sense. empty shelves lose their pointer."

What every retirement leg now does when it leaves a shelf with no entry
(`retire`, its alias `graduate`, `supersede`, a `reroute` off the shelf, a
route that completes a `teach --supersedes`, and a reconsider's `reject` /
`defer`, the last two in `test_reconsider_off_shelf.py`):

- the shelf's line leaves the pointer block, in the same locked section,
  and the whole block goes when no other line is left and nothing but
  self-learn's own preamble remains;
- the default shelf file (`references/LEARNINGS.md`, which self-learn
  creates and re-creates on demand) is removed when it holds nothing but
  one of self-learn's two headers and nothing in the surface names it any
  more; a named shelf, or one holding any other text, stays;
- the compile record follows in the same ledger commit: a region that is
  gone loses its entry, a region that changed is re-recorded, so the next
  write reads neither `missing` nor `edited`;
- a git host commits all of it in the one `(reference retired)` commit; a
  plain host is changed and recorded, never committed.

The plain hosts here keep CLAUDE.md untracked: a parallel lane (G1) will
refuse writes into a TRACKED file of a plain host, which is expected and
not this file's concern.

Every scenario runs on a sandbox ledger and host (`support.make_env` under
pytest's tmpdir); no model is called.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from self_learn import compiled, compilers, verbs
from self_learn.compilers import (
    _LEARNINGS_HEADER,
    POINTER_BEGIN_MARKER,
    POINTER_END_MARKER,
    CompileError,
)
from self_learn.hosts import host_add, host_slug
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.records import Record
from support import (
    CLAUDE_MD_SEED,
    SKILL_MD_SEED,
    commit_all,
    git,
    init_repo,
    make_behavior,
    make_env,
)

RID = "lrn-5e2f0001"
OTHER = "lrn-5e2f0002"
THIRD = "lrn-5e2f0003"
NEW = "lrn-5e2f0004"
SHELF_LINE = "- `references/LEARNINGS.md` — captured lessons for this project"
NAMED_HEADER = "# Git notes\n\nKept by hand; self-learn appends entries below.\n"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


# ------------------------------------------------------------------ helpers


def _record(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _project_host(home: Path, tmp_path: Path, mode: str, seed: str = CLAUDE_MD_SEED) -> Path:
    """A git repository registered as a project host in *mode*. Its
    CLAUDE.md is committed on a git host and left UNTRACKED on a plain
    one (see the module docstring)."""
    host = tmp_path / f"{mode}-host"
    init_repo(host)
    (host / "README.md").write_text("host\n", encoding="utf-8")
    commit_all(host, "host seed")
    (host / "CLAUDE.md").write_text(seed, encoding="utf-8")
    if mode == "git":
        commit_all(host, "claude seed")
    host_add(home, host, "project", mode=mode)
    return host


def _lesson(home: Path, host: Path, rid: str, supersedes: str | None = None) -> None:
    record = make_behavior(scope="project", record_id=rid, trigger=f"Editing {rid}.")
    if supersedes is not None:
        record.set_supersedes(supersedes)
    create_record(home, record, project_path=host)
    commit_all(home, f"seed {rid}")


def _shelve(home: Path, host: Path, rid: str, dest: str = "reference") -> None:
    _lesson(home, host, rid)
    verbs.route(home, rid, dest=dest, no_push=True)


def _block(text: str) -> str | None:
    if POINTER_BEGIN_MARKER not in text:
        return None
    start = text.index(POINTER_BEGIN_MARKER)
    return text[start : text.index(POINTER_END_MARKER) + len(POINTER_END_MARKER)]


def _entry(home: Path, host: Path, target: Path, region: str, scope_kind: str = "project"):
    data = compiled.load_record(home, host_slug(home, host, scope_kind=scope_kind))
    return compiled.entry_for(data, compiled.region_key(host, target, region), region=region)


def _region_sha(path: Path, region: str) -> str | None:
    found = compiled.region_bytes(path.read_text(encoding="utf-8"), region)
    return hashlib.sha256(found).hexdigest() if found is not None else None


def _shelf(host: Path, name: str = "LEARNINGS.md") -> Path:
    return host / "references" / name


def _assert_shelved(home: Path, host: Path, rid: str) -> None:
    """Positive control: the lesson is on the default shelf, the pointer
    line names it, and the compile record knows both regions."""
    shelf = _shelf(host)
    assert f"— {rid}" in shelf.read_text(encoding="utf-8")
    block = _block((host / "CLAUDE.md").read_text(encoding="utf-8"))
    assert block is not None and SHELF_LINE in block, block
    pointer = _entry(home, host, host / "CLAUDE.md", "pointer")
    assert pointer is not None and pointer["sha256"] == _region_sha(host / "CLAUDE.md", "pointer")
    reference = _entry(home, host, shelf, "reference")
    assert reference is not None and reference["sha256"] == _region_sha(shelf, "reference")


def _assert_pointer_and_shelf_gone(home: Path, host: Path) -> None:
    claude = host / "CLAUDE.md"
    assert claude.read_text(encoding="utf-8") == CLAUDE_MD_SEED  # the block and its blank line left
    assert not _shelf(host).exists()  # header-only default shelf removed
    assert _shelf(host).parent.is_dir()  # the directory is left alone
    # the compile record lost both entries (a region that is gone has none)
    assert _entry(home, host, claude, "pointer") is None
    assert _entry(home, host, _shelf(host), "reference") is None


def _assert_host_side(host: Path, mode: str, before: str, rid: str) -> None:
    status = git(host, "status", "--porcelain").stdout
    if mode == "git":
        subjects = git(host, "log", "--format=%s", f"{before}..HEAD").stdout.splitlines()
        retired = f"self-learn: apply {rid} → references/LEARNINGS.md (reference retired)"
        assert retired in subjects, subjects
        assert status == "", status
        assert git(host, "ls-files", "references").stdout == ""  # the deletion is committed
        assert git(host, "show", "HEAD:CLAUDE.md").stdout == CLAUDE_MD_SEED
    else:
        assert _head(host) == before, "a plain host is never committed to"
        assert git(host, "ls-files", "CLAUDE.md", "references").stdout == ""
        assert "?? CLAUDE.md" in status, status  # control: the file is there, untracked


def _route_again(home: Path, host: Path, rid: str) -> None:
    """The next write to the shelf and its pointer is not read as a hand
    edit: the shelf is created afresh and the pointer line comes back."""
    _lesson(home, host, rid)
    verbs.route(home, rid, dest="reference", no_push=True)
    shelf = _shelf(host)
    assert shelf.read_text(encoding="utf-8").startswith(_LEARNINGS_HEADER)
    assert f"— {rid}" in shelf.read_text(encoding="utf-8")
    block = _block((host / "CLAUDE.md").read_text(encoding="utf-8"))
    assert block is not None and SHELF_LINE in block


# ------------------------------------------------- every leg, both modes


def _leg(home: Path, host: Path, leg: str) -> None:
    if leg == "retire":
        verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)
    elif leg == "graduate":
        verbs.graduate(home, RID, no_push=True)
    elif leg == "supersede":
        _lesson(home, host, NEW)
        verbs.supersede(home, RID, NEW, no_push=True)
    elif leg == "reroute":
        verbs.reroute(home, RID, dest="claude-md:rules:moved-off",
                      rules_paths=["README.md"], no_push=True)
    elif leg == "route-supersedes":
        _lesson(home, host, NEW, supersedes=RID)
        verbs.route(home, NEW, dest="claude-md:rules:moved-off",
                    rules_paths=["README.md"], no_push=True)
    else:  # pragma: no cover
        raise AssertionError(leg)


@pytest.mark.parametrize("mode", ["git", "plain"])
@pytest.mark.parametrize(
    "leg", ["retire", "graduate", "supersede", "reroute", "route-supersedes"]
)
def test_the_last_entry_leaving_takes_the_pointer_and_the_shelf(tmp_path, leg, mode):
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    _shelve(home, host, RID)
    _assert_shelved(home, host, RID)
    before = _head(host)

    _leg(home, host, leg)

    assert _record(home, RID).status == ("routed" if leg == "reroute" else "superseded")
    _assert_pointer_and_shelf_gone(home, host)
    _assert_host_side(host, mode, before, RID)
    if leg in ("reroute", "route-supersedes"):
        moved = NEW if leg == "route-supersedes" else RID
        assert moved in (host / ".claude" / "rules" / "moved-off.md").read_text(encoding="utf-8")
    _route_again(home, host, OTHER)


@pytest.mark.parametrize("mode", ["git", "plain"])
def test_a_reroute_into_the_same_file_drops_the_pointer_and_writes_the_managed_region(
    tmp_path, mode
):
    """A shelf lesson rerouted to `claude-md` lands in the managed region of
    the SAME CLAUDE.md whose pointer block names the shelf: the two regions
    change in one motion, each keeps its own compile-record entry (S-74),
    and later writes to either region are not read as hand edits."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    _shelve(home, host, RID)
    _assert_shelved(home, host, RID)
    claude = host / "CLAUDE.md"

    verbs.reroute(home, RID, dest="claude-md", no_push=True)

    text = claude.read_text(encoding="utf-8")
    assert _block(text) is None
    assert f"({RID})" in text  # the managed region now carries the lesson
    assert text.startswith(CLAUDE_MD_SEED.rstrip("\n"))
    assert not _shelf(host).exists()
    assert _entry(home, host, claude, "pointer") is None
    managed = _entry(home, host, claude, "managed")
    assert managed is not None and managed["sha256"] == _region_sha(claude, "managed")
    if mode == "git":
        assert git(host, "status", "--porcelain").stdout == ""

    _route_again(home, host, OTHER)  # the pointer region again
    _lesson(home, host, THIRD)  # ... and the managed region
    verbs.route(home, THIRD, dest="claude-md", no_push=True)
    assert f"({THIRD})" in claude.read_text(encoding="utf-8")


@pytest.mark.parametrize("mode", ["git", "plain"])
@pytest.mark.parametrize("leg", ["retire", "supersede"])
def test_the_shelf_hosts_lock_covers_the_pointer_prediction_and_its_removal(
    tmp_path, monkeypatch, leg, mode
):
    """REC12: the pointer surface is predicted for the compile record and
    rewritten under the shelf host's lock, the same lock the shelf entry's
    own prediction and removal already take, so no other producer can
    change the surface between the two."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    _shelve(home, host, RID)
    lock = str(verbs.gitops.host_lock_path(host, mode))
    seen: list[tuple[str, bool]] = []
    real_plan, real_retire = verbs._plan_shelf_retirement, verbs.retire_empty_shelf

    def plan(*args, **kwargs):
        seen.append(("predict", lock in verbs.gitops._held_locks))
        return real_plan(*args, **kwargs)

    def retire(*args, **kwargs):
        seen.append(("remove", lock in verbs.gitops._held_locks))
        return real_retire(*args, **kwargs)

    monkeypatch.setattr(verbs, "_plan_shelf_retirement", plan)
    monkeypatch.setattr(verbs, "retire_empty_shelf", retire)
    assert lock not in verbs.gitops._held_locks  # control: nothing holds it before
    _leg(home, host, leg)
    assert seen == [("predict", True), ("remove", True)], seen
    _assert_pointer_and_shelf_gone(home, host)


# ------------------------------------------------------ what stays behind


@pytest.mark.parametrize("mode", ["git", "plain"])
def test_the_pointer_stays_while_one_entry_is_left(tmp_path, mode):
    """Positive control for the leg above: with two lessons on the shelf,
    retiring one leaves the line, the block and the file; retiring the
    second takes them."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    _shelve(home, host, RID)
    _shelve(home, host, OTHER)
    claude = host / "CLAUDE.md"
    with_both = claude.read_text(encoding="utf-8")

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)
    assert claude.read_text(encoding="utf-8") == with_both
    text = _shelf(host).read_text(encoding="utf-8")
    assert f"— {RID}" not in text and f"— {OTHER}" in text

    verbs.retire(home, OTHER, covered_by="claude-md:CLAUDE.md", no_push=True)
    _assert_pointer_and_shelf_gone(home, host)


def _named_shelf(home: Path, host: Path, mode: str, header: str = NAMED_HEADER) -> Path:
    """A named shelf a person made by hand (self-learn never creates one).
    A git host's history is its provenance; a plain host refuses a file the
    compile record has never seen (`unknown`), and `recompile --adopt` has
    no form for a reference file, so the entry an adopt would write is
    written here directly."""
    named = _shelf(host, "git.md")
    named.parent.mkdir(parents=True, exist_ok=True)
    named.write_text(header, encoding="utf-8")
    if mode == "git":
        commit_all(host, "a named shelf")
    else:
        region = named.read_bytes()
        compiled.adopt_entry(
            home, host_slug(home, host, scope_kind="project"),
            compiled.region_key(host, named, "reference"), region="reference",
            observed_hash=hashlib.sha256(region).hexdigest(), nbytes=len(region),
            host=str(host), mode=mode,
        )
        commit_all(home, "adopt the named shelf")
    return named


@pytest.mark.parametrize("mode", ["git", "plain"])
def test_another_shelfs_line_keeps_the_block_and_its_record_stays_true(tmp_path, mode):
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    named = _named_shelf(home, host, mode)
    _shelve(home, host, RID)
    _shelve(home, host, OTHER, dest="reference:git.md")
    claude = host / "CLAUDE.md"
    block = _block(claude.read_text(encoding="utf-8"))
    assert block is not None and SHELF_LINE in block and "`references/git.md`" in block

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    block = _block(claude.read_text(encoding="utf-8"))
    assert block is not None, "the other shelf's line keeps the block"
    assert SHELF_LINE not in block and "`references/git.md`" in block
    assert not _shelf(host).exists()
    assert f"— {OTHER}" in named.read_text(encoding="utf-8")
    pointer = _entry(home, host, claude, "pointer")
    assert pointer is not None and pointer["sha256"] == _region_sha(claude, "pointer")
    if mode == "git":
        assert git(host, "status", "--porcelain").stdout == ""

    # The next write to the same pointer region is not read as a hand edit
    # (a leftover entry would make it refuse, `edited`, in either mode).
    _lesson(home, host, THIRD)
    verbs.route(home, THIRD, dest="reference:git.md", no_push=True)
    assert f"— {THIRD}" in named.read_text(encoding="utf-8")
    _route_again(home, host, NEW)


@pytest.mark.parametrize("mode", ["git", "plain"])
@pytest.mark.parametrize("header", ["own", "self-learn's"])
def test_a_named_shelf_loses_its_line_and_keeps_its_file(tmp_path, mode, header):
    """A named shelf is a file a person made (self-learn never creates one,
    and a later `reference:<file>` route needs it to exist), so it stays
    even when it holds nothing but a copy of self-learn's own header."""
    text = NAMED_HEADER if header == "own" else _LEARNINGS_HEADER
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    named = _named_shelf(home, host, mode, header=text)
    _shelve(home, host, RID, dest="reference:git.md")
    claude = host / "CLAUDE.md"
    assert "`references/git.md`" in (_block(claude.read_text(encoding="utf-8")) or "")

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert claude.read_text(encoding="utf-8") == CLAUDE_MD_SEED
    assert named.read_text(encoding="utf-8") == text  # a person's file stays
    entry = _entry(home, host, named, "reference")
    assert entry is not None and entry["sha256"] == _region_sha(named, "reference")
    assert _entry(home, host, claude, "pointer") is None


def test_a_default_shelf_holding_a_persons_text_keeps_its_file(tmp_path):
    """A LEARNINGS.md a person wrote before self-learn first appended to it
    (a git host accepts such a file; its history is its provenance)."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, "git")
    shelf = _shelf(host)
    shelf.parent.mkdir()
    own = "# Lessons\n\nMy own note about the build.\n"
    shelf.write_text(own, encoding="utf-8")
    commit_all(host, "a person's shelf")
    _shelve(home, host, RID)
    assert f"— {RID}" in shelf.read_text(encoding="utf-8")
    assert SHELF_LINE in (_block((host / "CLAUDE.md").read_text(encoding="utf-8")) or "")

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert shelf.read_text(encoding="utf-8") == own
    assert (host / "CLAUDE.md").read_text(encoding="utf-8") == CLAUDE_MD_SEED
    assert git(host, "status", "--porcelain").stdout == ""


def test_a_shelf_the_surface_names_by_hand_keeps_its_file(tmp_path):
    """When CLAUDE.md already names the shelf in a person's own words, no
    pointer line was ever written (`apply_pointer`'s idempotence leg).
    Removing the file would leave that sentence pointing at nothing, so it
    stays, and the sentence is not touched. The control is the same
    retirement on a host whose CLAUDE.md does not name the shelf: there the
    header-only file goes."""
    seed = "# host project\n\nSee references/LEARNINGS.md before a release.\n"
    control_home = make_env(tmp_path / "control").ledger
    control = _project_host(control_home, tmp_path / "control", "git")
    _shelve(control_home, control, RID)
    verbs.retire(control_home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)
    assert not _shelf(control).exists()

    home = make_env(tmp_path / "named").ledger
    host = _project_host(home, tmp_path / "named", "git", seed=seed)
    _shelve(home, host, RID)
    claude = host / "CLAUDE.md"
    assert claude.read_text(encoding="utf-8") == seed  # control: no block was written

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert claude.read_text(encoding="utf-8") == seed
    assert _shelf(host).read_text(encoding="utf-8") == _LEARNINGS_HEADER
    entry = _entry(home, host, _shelf(host), "reference")
    assert entry is not None and entry["sha256"] == _region_sha(_shelf(host), "reference")


def test_a_skills_shelf_loses_its_pointer_too(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    create_record(home, make_behavior(record_id=RID))
    commit_all(home, f"seed {RID}")
    verbs.route(home, RID, dest="reference", no_push=True)
    shelf = env.skill_dir / "references" / "LEARNINGS.md"
    line = "- `references/LEARNINGS.md` — captured lessons for this skill"
    assert line in (_block(env.skill_md.read_text(encoding="utf-8")) or "")
    assert f"— {RID}" in shelf.read_text(encoding="utf-8")
    before = _head(env.host)

    verbs.retire(home, RID, covered_by="skill-md:s", no_push=True)

    assert env.skill_md.read_text(encoding="utf-8") == SKILL_MD_SEED.format(name="s")
    assert not shelf.exists()
    assert _entry(home, env.host, env.skill_md, "pointer", scope_kind="skill") is None
    assert _entry(home, env.host, shelf, "reference", scope_kind="skill") is None
    assert _head(env.host) != before
    assert git(env.host, "status", "--porcelain").stdout == ""


# ------------------------------- two writes to one pointer region, composed


@pytest.mark.parametrize("mode", ["git", "plain"])
@pytest.mark.parametrize("leg", ["reroute", "route-supersedes"])
def test_a_move_from_one_shelf_to_another_records_the_pointer_it_leaves(tmp_path, leg, mode):
    """Two writes land on one pointer region in one motion: the NEW shelf's
    line is added and the emptied OLD shelf's line removed. `reroute`
    writes them old-first, a route completing `teach --supersedes`
    new-first; both predict the new line before the old one's removal is
    known, and the record must hold the region the two writes leave."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    named = _named_shelf(home, host, mode)
    _shelve(home, host, RID)
    claude = host / "CLAUDE.md"

    moved = RID
    if leg == "reroute":
        verbs.reroute(home, RID, dest="reference:git.md", no_push=True)
    else:
        moved = NEW
        _lesson(home, host, NEW, supersedes=RID)
        verbs.route(home, NEW, dest="reference:git.md", no_push=True)

    block = _block(claude.read_text(encoding="utf-8"))
    assert block is not None and "`references/git.md`" in block and SHELF_LINE not in block
    assert f"— {moved}" in named.read_text(encoding="utf-8")
    assert not _shelf(host).exists()
    pointer = _entry(home, host, claude, "pointer")
    assert pointer is not None and pointer["sha256"] == _region_sha(claude, "pointer")
    _lesson(home, host, OTHER)
    verbs.route(home, OTHER, dest="reference:git.md", no_push=True)  # not `edited`
    _route_again(home, host, THIRD)


@pytest.mark.parametrize("mode", ["git", "plain"])
def test_a_route_that_supersedes_onto_the_same_shelf_records_the_shelf_it_leaves(tmp_path, mode):
    """`teach --supersedes`'s completion appends the new entry, then removes
    the old one, from the SAME shelf. The shelf keeps an entry, so its
    pointer stays; and the compile record holds the shelf the two writes
    leave, so the next route to it is not refused as a hand edit."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    _shelve(home, host, RID)
    claude = host / "CLAUDE.md"
    with_pointer = claude.read_text(encoding="utf-8")
    _lesson(home, host, NEW, supersedes=RID)

    verbs.route(home, NEW, dest="reference", no_push=True)

    shelf = _shelf(host)
    text = shelf.read_text(encoding="utf-8")
    assert f"— {RID}" not in text and f"— {NEW}" in text
    assert claude.read_text(encoding="utf-8") == with_pointer
    entry = _entry(home, host, shelf, "reference")
    assert entry is not None and entry["sha256"] == _region_sha(shelf, "reference")
    _lesson(home, host, OTHER)
    verbs.route(home, OTHER, dest="reference", no_push=True)
    assert f"— {OTHER}" in shelf.read_text(encoding="utf-8")


def test_a_fresh_block_after_the_move_keeps_the_ancestry_sentence_in_the_record(tmp_path):
    """On a host with a registered descendant, a pointer block is written
    with ANC8's base sentence. Moving the only shelf lesson to a named shelf
    removes the block and writes a fresh one, base sentence included; the
    record must predict that sentence too. (The first shelf route on such a
    host records its pointer without the sentence -- a separate, earlier
    defect -- so the person adopts the region first, as the refusal says.)"""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, "git")
    inner = host / "inner"
    inner.mkdir()
    (inner / "README.md").write_text("inner\n", encoding="utf-8")
    commit_all(host, "a nested project")
    host_add(home, inner, "project", mode="plain")
    named = _named_shelf(home, host, "git")
    _shelve(home, host, RID)
    claude = host / "CLAUDE.md"
    base = "paths are relative to the directory containing this file"
    assert base in claude.read_text(encoding="utf-8")  # control: ANC8 applies here
    verbs.recompile(home, no_push=True, adopt=f"{claude}#pointer")

    verbs.reroute(home, RID, dest="reference:git.md", no_push=True)

    block = _block(claude.read_text(encoding="utf-8"))
    assert block is not None and base in block and "`references/git.md`" in block
    assert SHELF_LINE not in block
    pointer = _entry(home, host, claude, "pointer")
    assert pointer is not None and pointer["sha256"] == _region_sha(claude, "pointer")
    _lesson(home, host, OTHER)
    verbs.route(home, OTHER, dest="reference:git.md", no_push=True)  # not `edited`
    assert f"— {OTHER}" in named.read_text(encoding="utf-8")


# ------------------------------------------------ the pure text transforms


SURFACE = Path("/sandbox/host/CLAUDE.md")
TARGET = Path("/sandbox/host/references/LEARNINGS.md")
NAMED = Path("/sandbox/host/references/git.md")


def _bootstrapped(text: str, *, names_base: bool = False) -> str:
    line = compilers.pointer_line("references/LEARNINGS.md", "captured lessons for this project")
    return compilers.compile_pointer_text(text, line, names_base=names_base)[0]


@pytest.mark.parametrize("names_base", [False, True])
@pytest.mark.parametrize(
    "before",
    ["", "# host\n\nprose\n", "# host\n\nprose"],
    ids=["whole-file", "after-content", "no-final-newline"],
)
def test_removing_the_only_line_is_the_inverse_of_the_bootstrap(before, names_base):
    with_block = _bootstrapped(before, names_base=names_base)
    assert POINTER_BEGIN_MARKER in with_block  # control: a block was written
    after, block_removed = compilers._retire_pointer_text(with_block, SURFACE, TARGET)
    assert block_removed is True
    assert after == (before.rstrip("\n") + "\n" if before else "")


def test_content_after_the_block_is_kept_with_one_blank_line():
    with_block = _bootstrapped("# host\n\nprose\n") + "\n## Later\n\nmore prose\n"
    after, block_removed = compilers._retire_pointer_text(with_block, SURFACE, TARGET)
    assert block_removed is True
    assert after == "# host\n\nprose\n\n## Later\n\nmore prose\n"


def test_only_the_named_shelfs_line_leaves_and_text_outside_the_block_is_untouched():
    other = compilers.pointer_line("references/git.md", "captured lessons for this project")
    text = _bootstrapped("# host\n\nSee references/LEARNINGS.md first.\n")
    text = compilers.compile_pointer_text(text, other)[0]
    after, block_removed = compilers._retire_pointer_text(text, SURFACE, TARGET)
    assert block_removed is False
    assert SHELF_LINE not in after and other in after
    assert "See references/LEARNINGS.md first." in after
    assert after == text.replace(SHELF_LINE + "\n", "")
    # a surface that does not name the target is returned unchanged
    assert compilers._retire_pointer_text(after, SURFACE, NAMED.with_name("x.md")) == (after, False)


def test_a_block_holding_anything_but_the_preamble_is_kept():
    """Only pointer lines (the `pointer_line` grammar) leave; a person's own
    line inside the block stays even when it names the same shelf, and it
    keeps the block."""
    note = "A note a person left: references/LEARNINGS.md is long."
    text = _bootstrapped("# host\n")
    text = text.replace(SHELF_LINE, note + "\n" + SHELF_LINE)
    after, block_removed = compilers._retire_pointer_text(text, SURFACE, TARGET)
    assert block_removed is False
    assert POINTER_BEGIN_MARKER in after and note in after
    assert SHELF_LINE not in after


def test_broken_pointer_markers_are_refused_by_name():
    text = _bootstrapped("# host\n") + POINTER_END_MARKER + "\n"
    with pytest.raises(CompileError, match="pointer-block markers"):
        compilers._retire_pointer_text(text, SURFACE, TARGET)


def test_both_of_self_learns_headers_read_as_header_only_and_nothing_else_does():
    legacy = (
        "# Learnings\n\nReference-routed lessons, appended by self-learn (newest last). Each\n"
        "entry carries its record id for provenance; regenerate nothing here —\n"
        "this file is append-only.\n"
    )
    for header in (_LEARNINGS_HEADER, legacy):
        assert compilers.shelf_is_header_only(header)
        assert compilers.shelf_is_header_only(header + "\n")
        assert not compilers.shelf_is_header_only(header + "\nA person's note.\n")
        assert not compilers.shelf_has_entries(header)
        assert compilers.shelf_has_entries(header + f"\n## 2026-10-07 — {RID}\n\nbody\n")
    assert not compilers.shelf_is_header_only("")  # self-learn never wrote it
    assert not compilers.shelf_is_header_only(NAMED_HEADER)
    assert not compilers.shelf_has_entries("## Not an entry\n")
