"""A reconsider takes a lesson off a reference shelf (2026-10-06).

A shelf is a project's (or a skill's) `references/LEARNINGS.md`, reached
through one pointer line in its CLAUDE.md. Measured 2026-10-05, no
self-learn shelf had ever been read. The user said yes to the correction
that moves lessons off them. At 2fc0888 a `reject` or `defer` under a
`kind: reconsider` case refused a shelf lesson by name ("hook and reference
routes are corrected by hand"); a reconsider's `route` line already moved
one (`verbs.reroute`, RER6). Now both do, for the steward and the overseer:
the lesson's entry block leaves the shelf file in the same locked section
the status flips in, its compile-record entry rides the same ledger commit,
and a plain host's file is changed and recorded but never committed. When
no entry is left, the shelf loses its pointer line and its header-only file
too (S-77 (3) as amended, 2026-10-07; every leg, in
`test_empty_shelf_pointer.py`). The hook half stays refused
(`test_preview_parity.py`'s hook rows pin that wording).

Every scenario runs on a sandbox ledger and host (`support.make_env` under
pytest's tmpdir); the batch, the verbs, the cases and the overseer's runner
are the real code, and no model is called.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from self_learn import batch, cases, compiled, gitops, steward, verbs
from self_learn.hosts import host_add, host_slug
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.overseer import run as overseer_run
from self_learn.records import Record
from support import (
    CLAUDE_MD_SEED,
    commit_all,
    git,
    init_repo,
    last_verb_sha,
    make_behavior,
    make_env,
    verb_files,
)
from test_failstate_overseer import _dump, _ok, _phase_a, _phase_b_common
from test_overseer_run import _enabled
from test_steward import _dump_yaml
from test_steward_refusals import _case

RID = "lrn-5e1f0001"
OTHER = "lrn-5e1f0002"
_GONE = {"reject": "rejected", "defer": "deferred"}


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _record(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _project_host(home: Path, tmp_path: Path, mode: str) -> Path:
    """A git repository registered as a project host in *mode* (`host add
    --mode`; a plain host gets its marker file). Plain hosts are git
    repositories too on this user's machine; self-learn just never
    commits to them, and that is what this file checks. A plain host's
    CLAUDE.md is left untracked: the pointer block in it is written and
    removed here, and since G1 (2026-10-07) self-learn writes a plain
    host's file only once git ignores it, and never one git tracks."""
    host = tmp_path / f"{mode}-host"
    init_repo(host)
    (host / "README.md").write_text("host\n", encoding="utf-8")
    commit_all(host, "host seed")
    (host / "CLAUDE.md").write_text(CLAUDE_MD_SEED, encoding="utf-8")
    if mode == "git":
        commit_all(host, "claude seed")
    host_add(home, host, "project", mode=mode)
    return host


def _project_lesson(home: Path, host: Path, rid: str) -> None:
    create_record(home, make_behavior(scope="project", record_id=rid), project_path=host)
    commit_all(home, f"seed {rid}")


def _record_case(home: Path, folder: Path, data: dict, actor: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"case-{len(list(folder.glob('case-*.yaml')))}.yaml"
    _dump_yaml(path, data)
    return cases.record(home, path, actor=actor)


def _shelved(tmp_path: Path, mode: str) -> tuple[Path, Path, Path, str]:
    """A project lesson the steward put on the project's shelf BEFORE the
    agents were barred from it (its case, then the route the steward's
    runner applied that night). Returns (ledger, host, shelf file, the
    steward's case)."""
    home = make_env(tmp_path).ledger
    host = _project_host(home, tmp_path, mode)
    _project_lesson(home, host, RID)
    prior = _record_case(
        home, tmp_path / "setup", _case([RID], "route", "route", scope="project"), "steward"
    )
    verbs.route(home, RID, dest="reference", by="steward", no_push=True)
    shelf = host / "references" / "LEARNINGS.md"
    assert f"— {RID}" in shelf.read_text(encoding="utf-8")  # positive control: on the shelf
    assert (_record(home, RID).routing or {}).get("destination") == "reference"
    return home, host, shelf, prior


def _reconsider(home: Path, folder: Path, supersedes: str, outcome: str, actor: str) -> str:
    case = _case([RID], outcome, outcome, scope="project")
    case.update(kind="reconsider", supersedes=supersedes)
    return _record_case(home, folder, case, actor)


def _sheet(tmp_path: Path, name: str, case_id: str, items: list[dict]) -> batch.Sheet:
    path = tmp_path / f"{name}.yaml"
    _dump_yaml(path, {"version": 1, "case": case_id, "items": items})
    return batch.load_sheet(path)


def _reference_entry(home: Path, host: Path, shelf: Path) -> tuple[dict, dict | None]:
    """The host's compile record, and its entry for the shelf file."""
    data = compiled.load_record(home, host_slug(home, host, scope_kind="project"))
    key = compiled.region_key(host, shelf, "reference")
    return data, compiled.entry_for(data, key, region="reference")


def _assert_host_side(host: Path, mode: str, host_before: str, rid: str) -> None:
    """git mode commits the shelf's change in the host -- here, the emptied
    shelf's removal and its pointer's; plain mode leaves it changed and
    uncommitted there (PLAIN11/H-j), and ignored (G1)."""
    status = git(host, "status", "--porcelain").stdout
    if mode == "git":
        assert _head(host) != host_before
        subject = git(host, "log", "-1", "--format=%s").stdout.strip()
        assert subject == f"self-learn: apply {rid} → references/LEARNINGS.md (reference retired)"
        assert status == "", status
        # control for the removal: the shelf was tracked before this commit
        assert git(host, "ls-tree", "-r", "--name-only", "HEAD~1", "references").stdout
        assert git(host, "ls-files", "references").stdout == ""
        assert git(host, "show", "HEAD:CLAUDE.md").stdout == CLAUDE_MD_SEED
    else:
        assert _head(host) == host_before, "a plain host is never committed to"
        tracked = git(host, "ls-files", "references").stdout
        assert tracked == "", tracked  # the shelf never entered the host's history
        assert git(host, "ls-files", "CLAUDE.md").stdout == ""
        # G1: CLAUDE.md is on disk and uncommitted, and ignored through the
        # self-learn block of the host's info/exclude (its pointer line went
        # in first, and the block only grows), so `git status` shows neither
        # it nor the shelf. The control comes first: the file is on disk.
        assert (host / "CLAUDE.md").is_file()
        git(host, "check-ignore", "-q", "--", "CLAUDE.md")
        assert "CLAUDE.md" not in status and "references/" not in status, status


# ------------------------------------------------ reject / defer off a shelf


@pytest.mark.parametrize("actor", ["steward", "overseer"])
@pytest.mark.parametrize("mode", ["git", "plain"])
@pytest.mark.parametrize("verb", ["reject", "defer"])
def test_a_reconsider_reject_or_defer_takes_the_lesson_off_its_shelf(tmp_path, verb, mode, actor):
    home, host, shelf, prior = _shelved(tmp_path, mode)
    host_before = _head(host)
    pointer_before = (host / "CLAUDE.md").read_text(encoding="utf-8")
    assert "references/LEARNINGS.md" in pointer_before  # control: the pointer line exists
    rc = _reconsider(home, tmp_path / "setup", prior, verb, actor)
    if actor == "steward":
        # the steward's runner records the record's side of the reconsider
        verbs.reconsider(home, RID, case=rc, by="steward", no_push=True)
    sheet = _sheet(tmp_path, "off", rc, [{"id": RID, "verb": verb}])

    preview = batch.dry_run(home, sheet, actor=actor)
    assert preview.items[0].state == "would-apply", preview.items[0].detail
    result = batch.run(home, sheet, no_push=True, actor=actor)
    assert result.items[0].state == "applied", result.items[0].detail

    assert _record(home, RID).status == _GONE[verb]
    # S-77 (3) as amended: its last entry gone, the shelf loses its pointer
    # (the block leaves CLAUDE.md as it was before the route) and its
    # header-only file.
    assert not shelf.exists()
    assert (host / "CLAUDE.md").read_text(encoding="utf-8") == CLAUDE_MD_SEED
    # The compile record dropped both regions' entries in the SAME ledger
    # commit as the status flip, in the host's own mode.
    slug = host_slug(home, host, scope_kind="project")
    assert f"compiled/{slug}.yaml" in verb_files(home)
    data, entry = _reference_entry(home, host, shelf)
    assert entry is None
    pointer_key = compiled.region_key(host, host / "CLAUDE.md", "pointer")
    assert compiled.entry_for(data, pointer_key, region="pointer") is None
    assert data["mode"] == mode
    _assert_host_side(host, mode, host_before, RID)

    # The next write to the shelf is not read as a hand edit (a stale
    # compile-record entry reads "edited" in either mode and refuses).
    _project_lesson(home, host, OTHER)
    verbs.route(home, OTHER, dest="reference", no_push=True)
    assert f"— {OTHER}" in shelf.read_text(encoding="utf-8")


@pytest.mark.parametrize("mode", ["git", "plain"])
@pytest.mark.parametrize("verb", ["reject", "defer"])
def test_the_shelf_hosts_lock_is_held_from_the_prediction_through_the_write(
    tmp_path, monkeypatch, mode, verb
):
    """REC12, the discipline `_retire_impl` already follows for a shelf:
    the shelf's host lock is taken before its bytes are observed and
    predicted for the compile record, and held through the host write, so
    no other producer can change the shelf between the two. `reject` and
    `defer` each take it on their own `with` line, so each is run. (The
    prediction is `_plan_shelf_retirement`; the host write is
    `retire_empty_shelf`, which takes the entry off -- or, as here, where
    the entry is the shelf's last, deletes the header-only shelf.)"""
    home, host, shelf, prior = _shelved(tmp_path, mode)
    lock = str(gitops.host_lock_path(host, mode))
    seen: list[tuple[str, bool]] = []
    real_predict = verbs._plan_shelf_retirement
    real_remove = verbs.retire_empty_shelf

    def predict(*args, **kwargs):
        seen.append(("predict", lock in gitops._held_locks))
        return real_predict(*args, **kwargs)

    def remove(*args, **kwargs):
        seen.append(("remove", lock in gitops._held_locks))
        return real_remove(*args, **kwargs)

    monkeypatch.setattr(verbs, "_plan_shelf_retirement", predict)
    monkeypatch.setattr(verbs, "retire_empty_shelf", remove)
    rc = _reconsider(home, tmp_path / "setup", prior, verb, "overseer")
    assert lock not in gitops._held_locks  # control: nothing holds it before the run
    result = batch.run(home, _sheet(tmp_path, "off", rc, [{"id": RID, "verb": verb}]),
                       no_push=True, actor="overseer")
    assert result.items[0].state == "applied", result.items[0].detail
    assert seen == [("predict", True), ("remove", True)], seen


@pytest.mark.parametrize("mode", ["git", "plain"])
@pytest.mark.parametrize("verb", ["reject", "defer"])
def test_the_shelfs_compile_record_names_the_bytes_it_was_based_on(tmp_path, verb, mode):
    """The compile-record entry a retirement writes carries two hashes:
    `sha256`, the shelf's bytes after the removal, and `based_on_sha256`,
    the shelf's bytes OBSERVED before it (REC12: "the state this write is
    based on"). `compiled.verdict` reads a leftover entry whose
    `based_on_sha256` matches the file as `stale` and lets the next writer
    through; with no `based_on_sha256` the same file reads `edited` and
    refuses it. The value is checked against the hash taken here, off the
    file, before the verb runs -- never against a field merely present.
    A second lesson stays on the shelf, so the shelf (and its entry) stays."""
    home, host, shelf, prior = _shelved(tmp_path, mode)
    _project_lesson(home, host, OTHER)
    verbs.route(home, OTHER, dest="reference", no_push=True)
    before = hashlib.sha256(shelf.read_bytes()).hexdigest()
    # control: the route left an entry whose hash is the file's, so `before`
    # is what the compile record knew the shelf as
    _data, routed = _reference_entry(home, host, shelf)
    assert routed is not None and routed["sha256"] == before
    rc = _reconsider(home, tmp_path / "setup", prior, verb, "overseer")
    result = batch.run(home, _sheet(tmp_path, "off", rc, [{"id": RID, "verb": verb}]),
                       no_push=True, actor="overseer")
    assert result.items[0].state == "applied", result.items[0].detail

    _data, entry = _reference_entry(home, host, shelf)
    assert entry is not None
    after = hashlib.sha256(shelf.read_bytes()).hexdigest()
    assert after != before  # control: the removal changed the shelf's bytes
    assert entry["sha256"] == after
    assert entry["based_on_sha256"] == before


def test_the_preview_and_the_run_agree_about_the_shelf_line(tmp_path):
    """S-71 §6: the preview runs the verb's own checks. Before, both said
    "corrected by hand"; now both apply, and the steward's repair turn
    is no longer told a correct line is wrong. The positive control is a
    line that IS refused on the same reconsider case (an agent's route
    back onto a shelf), so the repair message is shown to be live."""
    home, _host, _shelf, prior = _shelved(tmp_path, "git")
    stage = tmp_path / "stage"
    case = _case([RID], "reject", "reject", scope="project")
    case.update(kind="reconsider", supersedes=prior)
    _dump_yaml(stage / "cases" / "off.yaml", case)
    _dump_yaml(stage / "sheets" / "off.yaml",
               {"version": 1, "case": "$CASE_ID", "items": [{"id": RID, "verb": "reject"}]})
    assert steward._ledger_repair_message(home, stage, {RID: "routed"}) is None

    _dump_yaml(stage / "sheets" / "off.yaml", {"version": 1, "case": "$CASE_ID", "items": [
        {"id": RID, "verb": "route", "dest": "reference:LEARNINGS.md"}]})
    message = steward._ledger_repair_message(home, stage, {RID: "routed"})
    assert message is not None and f"(route {RID})" in message
    assert "reference shelf is refused for the steward" in message


# ------------------------------------------ rerouted off, never back on


@pytest.mark.parametrize("actor", ["steward", "overseer"])
@pytest.mark.parametrize("mode", ["git", "plain"])
def test_an_agent_moves_a_lesson_off_its_shelf_and_cannot_put_it_back(tmp_path, mode, actor):
    """The first half (a reconsider's `route` line moving a shelf lesson to
    a path-scoped rule) already worked at 2fc0888 -- `verbs.reroute`
    retires a reference placement (RER6). It is here for both agents and
    both host modes, which nothing covered. The second half is new: the
    same agent's later re-decision back onto the shelf is refused."""
    home, host, shelf, prior = _shelved(tmp_path, mode)
    host_before = _head(host)
    rc = _reconsider(home, tmp_path / "setup", prior, "route", actor)
    line = {"id": RID, "verb": "route", "dest": "claude-md:rules:moved-off",
            "rules_paths": ["CLAUDE.md"]}
    result = batch.run(home, _sheet(tmp_path, "off", rc, [line]), no_push=True, actor=actor)
    assert result.items[0].state == "applied", result.items[0].detail
    routing = _record(home, RID).routing or {}
    assert (routing.get("destination"), routing.get("rules_topic")) == ("claude-md", "moved-off")
    assert not shelf.exists()  # its only entry gone, the shelf goes with its pointer
    assert (host / "CLAUDE.md").read_text(encoding="utf-8") == CLAUDE_MD_SEED
    assert RID in (host / ".claude" / "rules" / "moved-off.md").read_text(encoding="utf-8")
    if mode == "plain":
        assert _head(host) == host_before, "a plain host is never committed to"

    back = _reconsider(home, tmp_path / "setup", rc, "route", actor)
    sheet = _sheet(tmp_path, "back", back, [{"id": RID, "verb": "route", "dest": "reference"}])
    preview = batch.dry_run(home, sheet, actor=actor)
    assert (preview.items[0].state, preview.items[0].kind) == ("would-refuse", "bad-line")
    result = batch.run(home, sheet, no_push=True, actor=actor)
    assert (result.items[0].state, result.items[0].kind) == ("refused", "bad-line")
    assert result.items[0].detail == preview.items[0].detail
    assert f"refused for the {actor}" in (result.items[0].detail or "")
    assert (_record(home, RID).routing or {}).get("rules_topic") == "moved-off"
    assert not shelf.exists()


# ------------------------------------------ the overseer, under S-76


def test_the_overseer_takes_a_steward_shelved_lesson_off_its_shelf(tmp_path, monkeypatch):
    """S-76: the overseer corrects a steward decision that is not parked
    with a `kind: reconsider` successor. Here the steward's case shelved a
    lesson; the overseer rejects it. At 2fc0888 the pair's preview refused
    its one line ("corrected by hand"), so it was dropped at phase B and
    the lesson stayed on the shelf."""
    home, host, shelf, prior = _shelved(tmp_path, "plain")
    host_before = _head(host)
    _enabled(monkeypatch)
    successor = _case([RID], "reject", "reject", scope="project")
    successor.update(kind="reconsider", trigger="weekly", supersedes=prior)
    successor["evidence"] = [{"ref": f"record:{RID}", "quote": "status: routed"}]

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "case-off-shelf.yaml", successor)
            _dump(spec.cwd / "sheet-off-shelf.yaml",
                  {"version": 1, "items": [{"id": RID, "verb": "reject"}]})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)

    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    refused = report.partition("## Refused / could not do")[2]
    assert refused, report  # positive control: the section rendered
    assert "dropped" not in refused, refused
    assert result.status == "applied", result
    reconsider_id = cases.show(home, prior, evidence_only=False).frontmatter.get("superseded_by")
    assert reconsider_id
    assert cases.show(home, reconsider_id, evidence_only=False).frontmatter["actor"] == "overseer"
    assert _record(home, RID).status == "rejected"
    assert not shelf.exists()
    assert (host / "CLAUDE.md").read_text(encoding="utf-8") == CLAUDE_MD_SEED
    assert _head(host) == host_before  # plain host: changed, never committed
    assert last_verb_sha(home)  # the ledger carries the reject
