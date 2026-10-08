"""An emptied shelf loses its pointer (S-77 (3) as amended, 2026-10-07).

A shelf is a project's or a skill's `references/LEARNINGS.md` (or a named
references file), reached through one line in the pointer block
(`<!-- self-learn:pointers:begin ... -->`) of the always-loaded CLAUDE.md or
SKILL.md. Until this change, a shelf whose last entry left kept that line
and the block around it -- about eight lines in every session, pointing at
a file holding nothing but its header. The user, 2026-10-07: "yeah, makes
sense. empty shelves lose their pointer."

What every retirement leg now does when it leaves a shelf EMPTY -- nothing
but one of self-learn's own two headers left on it (`retire`, its alias
`graduate`, `supersede`, a `reroute` off the shelf, a route that completes a
`teach --supersedes`, and a reconsider's `reject` / `defer`, the last two in
`test_reconsider_off_shelf.py`):

- the shelf's line leaves the pointer block, in the same locked section,
  and the whole block goes when no other line is left and nothing but
  self-learn's own preamble remains; only a line in self-learn's own
  pointer grammar (``- `<token>` — <label>``) whose token resolves to the
  shelf leaves -- a person's own line, in any other shape, stays;
- the default shelf file (`references/LEARNINGS.md`, which self-learn
  creates and re-creates on demand) is removed when nothing in the surface
  names it any more, unless it is a symlink; a named shelf stays;
- a shelf holding a person's own text but no entry is not empty: it keeps
  its pointer and its file;
- the compile record follows in the same ledger commit: a region that is
  gone loses its entry, a region that changed is re-recorded, so the next
  write reads neither `missing` nor `edited`;
- a git host commits all of it in the one `(reference retired)` commit, and
  puts it all back when that commit is refused; a plain host is changed and
  recorded, never committed.

In a plain host inside a git repository (S-80), the retirement writes only
files git ignores: the pointer file it rewrites gets its ignore line first
and is refused, as a removal (`needs-person`), when git tracks it; the shelf
it deletes is asked only whether git tracks it. The pre-flight, the ledger's
prediction and the host write judge the same files, so the compile record
never says a region is gone while the check keeps it on disk. The plain
hosts here hide self-learn's own `.self-learn-host` marker with an
operator's line in `info/exclude`, as the tracked-file tests do.

Every scenario runs on a sandbox ledger and host (`support.make_env` under
pytest's tmpdir); no model is called.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from self_learn import batch, compiled, compilers, verbs
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
    last_verb_sha,
    make_behavior,
    make_env,
)
from test_tracked_target_guard import (
    _block as _exclude_block,
    _ignored,
    _plain_repo_host,
    _sheet,
    _status,
    _write_operator_lines,
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
    one, whose `.self-learn-host` marker an operator's `info/exclude` line
    hides (see the module docstring)."""
    host = tmp_path / f"{mode}-host"
    init_repo(host)
    (host / "README.md").write_text("host\n", encoding="utf-8")
    commit_all(host, "host seed")
    (host / "CLAUDE.md").write_text(seed, encoding="utf-8")
    if mode == "git":
        commit_all(host, "claude seed")
    else:
        _write_operator_lines(host)
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
    status = _status(host)
    if mode == "git":
        subjects = git(host, "log", "--format=%s", f"{before}..HEAD").stdout.splitlines()
        retired = f"self-learn: apply {rid} → references/LEARNINGS.md (reference retired)"
        assert retired in subjects, subjects
        assert status == "", status
        assert git(host, "ls-files", "references").stdout == ""  # the deletion is committed
        assert git(host, "show", "HEAD:CLAUDE.md").stdout == CLAUDE_MD_SEED
        assert _exclude_block(host) is None  # S-80 leaves a git host's ignore file alone
    else:
        assert _head(host) == before, "a plain host is never committed to"
        assert git(host, "ls-files", "CLAUDE.md", "references").stdout == ""
        assert (host / "CLAUDE.md").is_file()  # control: the rewritten file is there ...
        assert _ignored(host, "CLAUDE.md")  # ... ignored by its own line (S-80) ...
        assert "/CLAUDE.md" in (_exclude_block(host) or [])
        assert status == "", status  # ... so git shows nothing at all


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
def test_a_named_shelf_keeps_its_file_and_loses_its_line_only_when_empty(
    tmp_path, mode, header
):
    """A named shelf is a file a person made (self-learn never creates one,
    and a later `reference:<file>` route needs it to exist), so its FILE
    always stays. Its LINE leaves only when the shelf is empty -- nothing
    but a copy of one of self-learn's own headers on it. A person's own
    header is a person's text: that shelf is not empty, and keeps its line."""
    text = NAMED_HEADER if header == "own" else _LEARNINGS_HEADER
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    named = _named_shelf(home, host, mode, header=text)
    _shelve(home, host, RID, dest="reference:git.md")
    claude = host / "CLAUDE.md"
    with_pointer = claude.read_text(encoding="utf-8")
    assert "`references/git.md`" in (_block(with_pointer) or "")  # control

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert named.read_text(encoding="utf-8") == text  # a person's file stays
    entry = _entry(home, host, named, "reference")
    assert entry is not None and entry["sha256"] == _region_sha(named, "reference")
    if header == "own":
        assert claude.read_text(encoding="utf-8") == with_pointer
        pointer = _entry(home, host, claude, "pointer")
        assert pointer is not None and pointer["sha256"] == _region_sha(claude, "pointer")
    else:
        assert claude.read_text(encoding="utf-8") == CLAUDE_MD_SEED
        assert _entry(home, host, claude, "pointer") is None


def test_a_default_shelf_holding_a_persons_text_keeps_its_file_and_its_pointer(tmp_path):
    """A LEARNINGS.md a person wrote before self-learn first appended to it
    (a git host accepts such a file; its history is its provenance). With
    the entry gone, the person's text is left: the shelf is not empty, so
    the pointer that reaches it stays too."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, "git")
    shelf = _shelf(host)
    shelf.parent.mkdir()
    own = "# Lessons\n\nMy own note about the build.\n"
    shelf.write_text(own, encoding="utf-8")
    commit_all(host, "a person's shelf")
    _shelve(home, host, RID)
    claude = host / "CLAUDE.md"
    with_pointer = claude.read_text(encoding="utf-8")
    assert f"— {RID}" in shelf.read_text(encoding="utf-8")  # control
    assert SHELF_LINE in (_block(with_pointer) or "")  # control

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert shelf.read_text(encoding="utf-8") == own
    assert claude.read_text(encoding="utf-8") == with_pointer
    assert git(host, "status", "--porcelain").stdout == ""


RELEASE_CHECKLIST = "\n## Release checklist\n\nTag before you push.\n"


@pytest.mark.parametrize("mode", ["git", "plain"])
def test_a_shelf_holding_a_persons_section_is_not_empty(tmp_path, mode):
    """Gate SH2 finding 5 (probe p16): the default shelf carries self-learn's
    own header AND a person's `## Release checklist` section. The last
    entry leaving leaves the person's section, which is not emptiness:
    the user's words were "empty shelves lose their pointer". The pointer,
    the file and the person's text all stay, and the compile record holds
    what is on disk. (A plain host never accepts a file the record has not
    seen, so the person's shelf is adopted there, as `_named_shelf` does.)"""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    shelf = _shelf(host)
    shelf.parent.mkdir()
    shelf.write_text(_LEARNINGS_HEADER + RELEASE_CHECKLIST, encoding="utf-8")
    if mode == "git":
        commit_all(host, "a person's section on the shelf")
    else:
        region = shelf.read_bytes()
        compiled.adopt_entry(
            home, host_slug(home, host, scope_kind="project"),
            compiled.region_key(host, shelf, "reference"), region="reference",
            observed_hash=hashlib.sha256(region).hexdigest(), nbytes=len(region),
            host=str(host), mode=mode,
        )
        commit_all(home, "adopt the person's shelf")
    _shelve(home, host, RID)
    claude = host / "CLAUDE.md"
    with_pointer = claude.read_text(encoding="utf-8")
    assert SHELF_LINE in (_block(with_pointer) or "")  # control: the pointer is there
    assert f"— {RID}" in shelf.read_text(encoding="utf-8")  # control

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert shelf.read_text(encoding="utf-8") == _LEARNINGS_HEADER + RELEASE_CHECKLIST
    assert claude.read_text(encoding="utf-8") == with_pointer
    pointer = _entry(home, host, claude, "pointer")
    assert pointer is not None and pointer["sha256"] == _region_sha(claude, "pointer")
    reference = _entry(home, host, shelf, "reference")
    assert reference is not None and reference["sha256"] == _region_sha(shelf, "reference")


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


# ------------------------------------------- what a person made stays (gate)


PERSONS_BULLET = "- Team note: read references/LEARNINGS.md before every release."


@pytest.mark.parametrize("mode", ["git", "plain"])
def test_a_persons_own_bullet_inside_the_block_keeps_the_block_and_the_shelf(tmp_path, mode):
    """Gate SH2 finding 1 (probe p1). A person's own bullet line inside the
    pointer block names the shelf but is not in self-learn's pointer
    grammar (``- `<token>` — <label>``). The last entry leaving takes only
    self-learn's line: the person's line stays, so the block stays, and the
    shelf stays because that line still names it. Reached once the block is
    adopted (`recompile --adopt CLAUDE.md#pointer`), in either mode."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    _shelve(home, host, RID)
    claude = host / "CLAUDE.md"
    claude.write_text(
        claude.read_text(encoding="utf-8").replace(SHELF_LINE, SHELF_LINE + "\n" + PERSONS_BULLET),
        encoding="utf-8",
    )
    if mode == "git":
        commit_all(host, "a person's own line in the block")
    verbs.recompile(home, no_push=True, adopt=f"{claude}#pointer")
    assert PERSONS_BULLET in (_block(claude.read_text(encoding="utf-8")) or "")  # control

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    block = _block(claude.read_text(encoding="utf-8"))
    assert block is not None and PERSONS_BULLET in block
    assert SHELF_LINE not in block
    assert _shelf(host).read_text(encoding="utf-8") == _LEARNINGS_HEADER
    pointer = _entry(home, host, claude, "pointer")
    assert pointer is not None and pointer["sha256"] == _region_sha(claude, "pointer")
    reference = _entry(home, host, _shelf(host), "reference")
    assert reference is not None and reference["sha256"] == _region_sha(_shelf(host), "reference")
    if mode == "git":
        assert _status(host) == ""


@pytest.mark.parametrize("mode", ["git", "plain"])
def test_a_symlinked_default_shelf_keeps_its_link_and_loses_its_pointer(tmp_path, mode):
    """Gate SH2 finding 4 (probe p8). `references/LEARNINGS.md` is a person's
    symlink to a shared file. When it empties, the pointer still goes, but
    the link is never deleted -- deleting it would end the person's
    arrangement, and the next route would make a plain file in its place."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    shared = tmp_path / "shared" / "LEARNINGS.md"
    shared.parent.mkdir()
    link = _shelf(host)
    link.parent.mkdir()
    link.symlink_to(shared)
    if mode == "git":
        commit_all(host, "a shared shelf")
    _shelve(home, host, RID)
    assert link.is_symlink() and f"— {RID}" in shared.read_text(encoding="utf-8")  # control

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert link.is_symlink() and link.resolve() == shared.resolve()
    assert shared.read_text(encoding="utf-8") == _LEARNINGS_HEADER
    assert (host / "CLAUDE.md").read_text(encoding="utf-8") == CLAUDE_MD_SEED
    reference = _entry(home, host, link, "reference")
    assert reference is not None and reference["sha256"] == _region_sha(link, "reference")
    _lesson(home, host, OTHER)
    verbs.route(home, OTHER, dest="reference", no_push=True)
    assert link.is_symlink() and f"— {OTHER}" in shared.read_text(encoding="utf-8")


def test_broken_pointer_markers_leave_the_pointer_and_the_shelf_and_say_so(tmp_path):
    """Gate SH2 M21 (probe p2), end to end: a stray end marker makes the
    block unreadable. The entry still leaves the shelf, but the surface is
    left exactly as it is, the warning names the markers, and the shelf
    file stays because the surface still names it."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, "git")
    _shelve(home, host, RID)
    claude = host / "CLAUDE.md"
    claude.write_text(claude.read_text(encoding="utf-8") + "\n" + POINTER_END_MARKER + "\n",
                      encoding="utf-8")
    commit_all(host, "a stray end marker")
    before = claude.read_text(encoding="utf-8")
    pointer_before = _entry(home, host, claude, "pointer")

    result = verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert claude.read_text(encoding="utf-8") == before
    assert any("pointer-block markers" in w for w in result.warnings), result.warnings
    assert _shelf(host).read_text(encoding="utf-8") == _LEARNINGS_HEADER
    assert _entry(home, host, claude, "pointer") == pointer_before
    reference = _entry(home, host, _shelf(host), "reference")
    assert reference is not None and reference["sha256"] == _region_sha(_shelf(host), "reference")
    assert _status(host) == ""


def test_a_shelf_whose_entry_is_already_gone_is_still_removed_and_committed(tmp_path):
    """Gate SH2 M20 (probe p4). A host older than shelf compile records:
    the entry was already taken off by hand and committed, and the record
    holds no entry for the shelf. Retiring the lesson removes nothing from
    the shelf, but the shelf is empty, so its pointer and the file go -- and
    the deletion is committed too, leaving `git status` clean."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, "git")
    _shelve(home, host, RID)
    shelf = _shelf(host)
    shelf.write_text(_LEARNINGS_HEADER, encoding="utf-8")
    commit_all(host, "entry removed by hand")
    slug = host_slug(home, host, scope_kind="project")
    compiled.delete_entry(home, slug, compiled.region_key(host, shelf, "reference"))
    commit_all(home, "legacy: no shelf entry")
    before = _head(host)

    verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert not shelf.exists()
    assert (host / "CLAUDE.md").read_text(encoding="utf-8") == CLAUDE_MD_SEED
    assert _head(host) != before  # control: something was committed ...
    assert git(host, "ls-files", "references").stdout == ""  # ... the deletion with it
    assert _status(host) == ""


# ------------------------------------------- a refused host commit (gate)


def test_a_refused_host_commit_puts_the_host_back_and_blocks_no_later_write(tmp_path):
    """Gate SH2 finding 2 (probes p10/p10b). The host's pre-commit hook
    refuses the `(reference retired)` commit. The host write is undone the
    way `_host_phase` undoes its own (Sweep 2, R3): CLAUDE.md and the shelf
    are put back and unstaged, so nothing a person did not make is left in
    their tree and no later write reads the file as busy. The warning names
    both files and tells the truth about the repair: `recompile` never takes
    a retired lesson out, so it is finished by hand."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, "git")
    _shelve(home, host, RID)
    claude, shelf = host / "CLAUDE.md", _shelf(host)
    claude_bytes, shelf_bytes = claude.read_bytes(), shelf.read_bytes()
    hook = host / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho refused-by-hook >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    result = verbs.retire(home, RID, covered_by="claude-md:CLAUDE.md", no_push=True)

    assert _record(home, RID).status == "superseded"  # the ledger commit stands
    (failed,) = [w for w in result.warnings if "REFERENCE RETIREMENT FAILED" in w]
    assert "refused-by-hook" in failed  # control: it is the hook's refusal
    assert str(claude) in failed and str(shelf) in failed
    assert "put back" in failed and "by hand" in failed
    assert "recompile` to repair" not in failed
    assert claude.read_bytes() == claude_bytes and shelf.read_bytes() == shelf_bytes
    assert _status(host) == ""
    hook.unlink()
    _lesson(home, host, OTHER)
    managed = verbs.route(home, OTHER, dest="claude-md", no_push=True)
    assert not [w for w in managed.warnings if "FAILED" in w], managed.warnings
    assert f"({OTHER})" in claude.read_text(encoding="utf-8")
    _lesson(home, host, THIRD)
    shelved = verbs.route(home, THIRD, dest="reference", no_push=True)
    assert not [w for w in shelved.warnings if "FAILED" in w], shelved.warnings
    assert f"— {THIRD}" in shelf.read_text(encoding="utf-8")
    assert _status(host) == ""


# ------------------------------------- the old shelf on another host (gate)


def test_a_route_completing_a_supersede_on_another_host_predicts_under_that_hosts_lock(
    tmp_path, monkeypatch
):
    """Gate SH2 finding 3 (probe p17). A project lesson routed to its own
    host supersedes a SKILL lesson whose shelf lives in the skills root, a
    different repository with its own lock. The old shelf and its pointer
    surface are read for the ledger's prediction under THAT host's lock,
    taken after the ledger lock and the new host's (one order everywhere),
    as the removal already was."""
    env = make_env(tmp_path)
    home = env.ledger
    create_record(home, make_behavior(record_id=RID))  # skill:s, shelf in env.host
    commit_all(home, f"seed {RID}")
    verbs.route(home, RID, dest="reference", no_push=True)
    skill_shelf = env.skill_dir / "references" / "LEARNINGS.md"
    assert f"— {RID}" in skill_shelf.read_text(encoding="utf-8")  # control
    host = _project_host(home, tmp_path, "git")
    _lesson(home, host, NEW, supersedes=RID)
    lock = str(verbs.gitops.host_lock_path(env.host, "git"))
    assert lock != str(verbs.gitops.host_lock_path(host, "git"))  # control: two locks
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

    verbs.route(home, NEW, dest="claude-md", no_push=True)

    assert seen == [("predict", True), ("remove", True)], seen
    assert not skill_shelf.exists()
    assert env.skill_md.read_text(encoding="utf-8") == SKILL_MD_SEED.format(name="s")
    assert lock not in verbs.gitops._held_locks  # released afterwards


# ------------------------------ the tracked-file check (S-80), plain hosts


def _plain_shelved(home: Path, tmp_path: Path, *rids: str) -> Path:
    """S-80's own fixture: a plain host inside a git repository whose
    CLAUDE.md is untracked and the marker hidden; *rids* go on its default
    shelf, which leaves the pointer file and the shelf ignored by their
    lines."""
    host = _plain_repo_host(home, tmp_path, track_claude_md=False)
    for rid in rids:
        _shelve(home, host, rid)
    assert _exclude_block(host) == ["/CLAUDE.md", "/references/LEARNINGS.md"]  # control
    return host


def _track(host: Path, *rels: str) -> None:
    git(host, "add", "-f", "--", *rels)
    git(host, "commit", "-q", "-m", f"track {' '.join(rels)}")


def test_the_pointer_file_gets_its_ignore_line_back_before_the_pointer_leaves(tmp_path):
    """CLAUDE.md is untracked and ignorable, but its ignore line was lost.
    The last entry leaving rewrites CLAUDE.md (its pointer goes), so the
    line is written back first; the shelf is deleted, which needs no line
    (git shows nothing for a file that is gone and was never tracked)."""
    home = make_env(tmp_path).ledger
    host = _plain_shelved(home, tmp_path, RID)
    _write_operator_lines(host)  # the block is lost
    assert not _ignored(host, "CLAUDE.md")  # control
    head = _head(host)

    verbs.graduate(home, RID, no_push=True)

    assert (host / "CLAUDE.md").read_text(encoding="utf-8") == CLAUDE_MD_SEED
    assert not _shelf(host).exists()
    assert _exclude_block(host) == ["/CLAUDE.md"]
    assert _ignored(host, "CLAUDE.md")
    assert _status(host) == ""
    assert _head(host) == head


def test_the_last_entry_leaving_a_shelf_whose_pointer_file_git_tracks_waits_for_a_person(
    tmp_path,
):
    """CLAUDE.md, holding the pointer block, was tracked after the route.
    The last entry leaving would rewrite it: refused as a removal
    (`needs-person` -- no destination choice moves a pointer that is
    already there), in the preview and the run alike, BEFORE the ledger
    commit and before anything in the host is written."""
    home = make_env(tmp_path).ledger
    host = _plain_shelved(home, tmp_path, RID)
    _track(host, "CLAUDE.md")
    claude_bytes = (host / "CLAUDE.md").read_bytes()
    shelf_bytes = _shelf(host).read_bytes()
    assert SHELF_LINE.encode() in claude_bytes  # control: the pointer is there
    ledger_head = last_verb_sha(home)
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "graduate"}])

    preview = batch.dry_run(home, sheet, actor="human")
    result = batch.run(home, sheet, no_push=True, actor="human")

    (pitem,), (item,) = preview.items, result.items
    assert (pitem.state, pitem.kind) == ("would-refuse", "needs-person"), pitem.detail
    assert (item.state, item.kind) == ("refused", "needs-person"), item.detail
    assert "CLAUDE.md is tracked by git" in (item.detail or "")
    assert "Taking this lesson out would change that file" in (item.detail or "")
    assert _record(home, RID).status == "routed"
    assert last_verb_sha(home) == ledger_head  # a telemetry flush may ride on top
    assert (host / "CLAUDE.md").read_bytes() == claude_bytes
    assert _shelf(host).read_bytes() == shelf_bytes
    assert _status(host) == ""


@pytest.mark.parametrize("left", [0, 1], ids=["deleted", "rewritten"])
def test_a_shelf_git_tracks_is_refused_whether_it_would_be_deleted_or_rewritten(tmp_path, left):
    """The shelf itself was tracked. Emptied, it would be DELETED -- a
    deletion asks whether git tracks the file, and it does; with another
    entry left it would be REWRITTEN. Both refuse, `needs-person`, with
    nothing written."""
    home = make_env(tmp_path).ledger
    host = _plain_shelved(home, tmp_path, RID, *([OTHER] if left else []))
    _track(host, "references/LEARNINGS.md")
    shelf_bytes = _shelf(host).read_bytes()
    claude_bytes = (host / "CLAUDE.md").read_bytes()

    with pytest.raises(verbs.NeedsPerson) as caught:
        verbs.graduate(home, RID, no_push=True)

    assert "LEARNINGS.md is tracked by git" in str(caught.value)
    assert _record(home, RID).status == "routed"
    assert _shelf(host).read_bytes() == shelf_bytes
    assert (host / "CLAUDE.md").read_bytes() == claude_bytes


def test_an_emptied_shelf_git_does_not_track_is_deleted_even_when_the_repo_re_admits_it(
    tmp_path,
):
    """A deletion asks only "does git track it?" (S-80, `deleting=True`): an
    untracked file's deletion publishes nothing. Here the repo's own
    `.gitignore` re-admits the shelf, so it could not be given a working
    ignore line -- which would refuse a REWRITE -- yet, emptied, it is
    deleted all the same."""
    home = make_env(tmp_path).ledger
    host = _plain_shelved(home, tmp_path, RID)
    (host / ".gitignore").write_text("!/references/LEARNINGS.md\n", encoding="utf-8")
    _track(host, ".gitignore")
    assert not _ignored(host, "references/LEARNINGS.md")  # control: the repo re-admits it

    result = verbs.graduate(home, RID, no_push=True)

    assert not [w for w in result.warnings if "FAILED" in w], result.warnings
    assert not _shelf(host).exists()
    assert (host / "CLAUDE.md").read_text(encoding="utf-8") == CLAUDE_MD_SEED
    assert _status(host) == ""


def test_a_pointer_file_tracked_after_the_pre_flight_leaves_the_record_true(
    tmp_path, monkeypatch
):
    """The gate's handoff note. The pre-flight passed; then, before the
    ledger's prediction, the owner tracked CLAUDE.md (stood in for here by
    tracking it as the ledger write begins). The host write refuses it, so
    nothing in the host changes -- and the prediction applies the same
    check, so the compile record does not claim the pointer or the shelf
    changed. Both regions still read `clean` against the record."""
    home = make_env(tmp_path).ledger
    host = _plain_shelved(home, tmp_path, RID)
    claude = host / "CLAUDE.md"
    claude_bytes, shelf_bytes = claude.read_bytes(), _shelf(host).read_bytes()
    real_resolve = verbs.resolve_record

    def track_then_resolve(*args, **kwargs):
        _track(host, "CLAUDE.md")
        return real_resolve(*args, **kwargs)

    monkeypatch.setattr(verbs, "resolve_record", track_then_resolve)

    result = verbs.graduate(home, RID, no_push=True)

    assert _record(home, RID).status == "superseded"  # the ledger commit stands
    (failed,) = [w for w in result.warnings if "REFERENCE RETIREMENT FAILED" in w]
    assert "CLAUDE.md is tracked by git" in failed
    assert "nothing was written" in failed
    assert claude.read_bytes() == claude_bytes and _shelf(host).read_bytes() == shelf_bytes
    pointer = _entry(home, host, claude, "pointer")
    assert pointer is not None and pointer["sha256"] == _region_sha(claude, "pointer")
    reference = _entry(home, host, _shelf(host), "reference")
    assert reference is not None and reference["sha256"] == _region_sha(_shelf(host), "reference")


def test_a_supersede_onto_the_same_shelf_never_judges_the_pointer_file_it_keeps(tmp_path):
    """`teach --supersedes` completed by a route onto the SAME shelf: the new
    entry lands before the old one leaves, so the shelf is never empty and
    CLAUDE.md is not rewritten. The pre-flight reads it that way too, so a
    CLAUDE.md git tracks does not refuse the route."""
    home = make_env(tmp_path).ledger
    host = _plain_shelved(home, tmp_path, RID)
    _track(host, "CLAUDE.md")
    claude_bytes = (host / "CLAUDE.md").read_bytes()
    _lesson(home, host, NEW, supersedes=RID)

    result = verbs.route(home, NEW, dest="reference", no_push=True)

    assert not [w for w in result.warnings if "FAILED" in w], result.warnings
    text = _shelf(host).read_text(encoding="utf-8")
    assert f"— {NEW}" in text and f"— {RID}" not in text
    assert _record(home, RID).status == "superseded"
    assert (host / "CLAUDE.md").read_bytes() == claude_bytes
    assert _status(host) == ""


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


def test_a_persons_bullet_naming_the_shelf_is_not_a_pointer_line():
    """Gate SH2 finding 1, the pure half: a bullet a person wrote inside the
    block ("- Team note: ...") is not in the pointer grammar, so it stays
    even though it names the shelf -- and with it, the block."""
    text = _bootstrapped("# host\n").replace(SHELF_LINE, SHELF_LINE + "\n" + PERSONS_BULLET)
    assert PERSONS_BULLET in text and SHELF_LINE in text  # control
    after, block_removed = compilers._retire_pointer_text(text, SURFACE, TARGET)
    assert block_removed is False
    assert POINTER_BEGIN_MARKER in after and PERSONS_BULLET in after
    assert SHELF_LINE not in after


def test_a_pointer_line_leaves_only_when_its_whole_token_resolves_to_the_shelf():
    """Gate SH2 M12: the token is resolved as a PATH, never matched by its
    basename. A pointer line to a same-named shelf in another directory, or
    to a file whose name merely starts with the shelf's, stays."""
    archive = compilers.pointer_line(
        "references/archive/LEARNINGS.md", "captured lessons for this project"
    )
    longer = compilers.pointer_line("references/LEARNINGS.md.bak", "captured lessons")
    text = _bootstrapped("# host\n")
    for line in (archive, longer):
        text = compilers.compile_pointer_text(text, line)[0]
    after, block_removed = compilers._retire_pointer_text(text, SURFACE, TARGET)
    assert block_removed is False
    assert SHELF_LINE not in after  # control: the shelf's own line did leave
    assert archive in after and longer in after


def test_a_shelf_holding_anything_but_a_self_learn_header_is_not_empty():
    """Item 2, the pure half: only a shelf holding nothing but one of
    self-learn's headers is empty. One holding a person's text -- under
    self-learn's header, or under the person's own -- changes nothing."""
    surface = _bootstrapped("# host\n")
    for shelf_text in (
        _LEARNINGS_HEADER + RELEASE_CHECKLIST,
        NAMED_HEADER,
        "",
    ):
        plan = compilers.plan_empty_shelf(
            TARGET, shelf_text, SURFACE, surface, default_shelf=True
        )
        assert (plan.emptied, plan.surface_changed, plan.delete_shelf) == (False, False, False)
        assert plan.surface_text == surface
    plan = compilers.plan_empty_shelf(  # control: self-learn's header alone is empty
        TARGET, _LEARNINGS_HEADER, SURFACE, surface, default_shelf=True
    )
    assert (plan.emptied, plan.surface_changed, plan.delete_shelf) == (True, True, True)


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
