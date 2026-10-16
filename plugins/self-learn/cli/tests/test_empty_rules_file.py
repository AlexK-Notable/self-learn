"""An emptied rules file is removed, not kept as a bare marker pair (S-87).

A rules route (`claude-md:rules:<topic>`) writes `.claude/rules/<topic>.md`
in a project (or `~/.claude/rules/<topic>.md` at user scope). Claude Code
loads every such file, and one with no `paths:` in every session. Until
S-87, the last lesson leaving one left a file holding only

    <!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->
    <!-- self-learn:end -->

and deleting it by hand made `self-learn --selftest` fail ("file missing"),
since the markers check still counted the lessons that once lived there.
The user, 2026-10-15: "yeah delete stuff that doesn't matter".

What every leg that can empty a rules file now does (retire, reroute,
replace, a reconsider's reject applied through `batch`, and `recompile` for
the files emptied before this change):

- when what the write would leave is nothing but self-learn's empty region
  (the paths pre-pass has already dropped self-learn's own `paths:`), the
  file is deleted instead, and its compile-record entry goes in the same
  ledger commit;
- a file holding any text a person wrote (a line outside the markers, a
  frontmatter key or comment) is kept, as before, and so is a symlink;
- only a rules file: a `CLAUDE.md` emptied the same way keeps its marker
  pair;
- `recompile` removes an already-emptied file only when its region is
  exactly what its compile record says self-learn wrote; an edited region,
  or one with no compile-record entry, keeps its file;
- the selftest's markers check owes nothing for a rules file that is absent
  and holds no live lesson, while one live lesson with no file still fails
  with the old wording.

Every scenario runs the real CLI (`self-learn init`, `host add`, `teach`,
`route`, `retire`, ...) in-process against a ledger and hosts under pytest's
tmpdir, with HOME pointed there too (user scope resolves `~/.claude`
through it). No model is called.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from self_learn import batch, cases, cli, compiled, verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.hosts import host_slug
from self_learn.ledger_ops import find_record_path
from self_learn.records import Record
from support import commit_all, git, init_repo
from test_steward import _dump_yaml
from test_steward_refusals import _case

#: What a pre-S-87 emptying left: the two marker lines.
BARE_PAIR = f"{BEGIN_MARKER}\n{END_MARKER}\n"


# ------------------------------------------------------------------ sandbox


class Sandbox:
    """A ledger made by `self-learn init`, HOME under tmpdir, and hosts
    registered by `self-learn host add`. Calls go through `cli.main`."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        self.tmp = tmp_path
        self.mp = monkeypatch
        self.capsys = capsys
        self.home = tmp_path / "ledger"
        self.user_home = tmp_path / "user-home"
        self.user_home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(self.home))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        monkeypatch.setenv("HOME", str(self.user_home))
        for name in ("SELF_LEARN_ANALYST_MODEL", "SELF_LEARN_ANALYST_TIMEOUT"):
            monkeypatch.delenv(name, raising=False)
        assert self.cli("init") == 0

    def cli(self, *argv: str, cwd: Path | None = None) -> int:
        self.mp.chdir(cwd if cwd is not None else self.tmp)
        return cli.main(list(argv))

    def out(self) -> str:
        captured = self.capsys.readouterr()
        return captured.out + captured.err

    def host(self, name: str, mode: str = "plain") -> Path:
        repo = self.tmp / name
        init_repo(repo)
        (repo / "README.md").write_text("host\n", encoding="utf-8")
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        commit_all(repo, "host seed")
        assert self.cli("host", "add", str(repo), "--mode", mode) == 0
        return repo

    def _pending(self) -> set[str]:
        return {p.stem for p in self.home.rglob("pending/lrn-*.md")}

    def teach(self, cwd: Path, *flags: str, trigger: str = "Editing a file") -> str:
        before = self._pending()
        rc = self.cli(
            "teach", *flags, "--trigger", trigger, "--instruction", "Check it first.",
            cwd=cwd,
        )
        assert rc == 0
        (rid,) = self._pending() - before
        return rid

    def lesson(self, cwd: Path, topic: str, *route_flags: str, scope: str = "--project",
               trigger: str = "Editing a file") -> str:
        """Teach a lesson and route it to `claude-md:rules:<topic>`."""
        rid = self.teach(cwd, scope, trigger=trigger)
        rc = self.cli(
            "route", rid, "--dest", f"claude-md:rules:{topic}", "--no-push",
            *route_flags, cwd=cwd,
        )
        assert rc == 0, self.out()
        return rid

    def retire(self, rid: str) -> None:
        assert self.cli(
            "retire", rid, "--covered-by", "claude-md:CLAUDE.md", "--no-push"
        ) == 0, self.out()

    def record(self, rid: str) -> Record:
        return Record.from_path(find_record_path(self.home, rid))

    def entry(self, host: Path, target: Path, scope_kind: str = "project") -> dict | None:
        data = compiled.load_record(self.home, host_slug(self.home, host, scope_kind=scope_kind))
        return compiled.entry_for(
            data, compiled.region_key(host, target, "managed"), region="managed"
        )

    def ledger_head(self) -> str:
        return git(self.home, "rev-parse", "HEAD").stdout.strip()

    def selftest_rows(self) -> dict[str, str]:
        self.out()
        self.cli("--selftest")
        rows: dict[str, str] = {}
        for line in self.out().splitlines():
            m = re.match(r"selftest: (PASS|FAIL|UNMEASURED) (\w+) — (.*)$", line)
            if m:
                rows[m.group(2)] = f"{m.group(1)} {m.group(3)}"
        return rows


@pytest.fixture
def sb(tmp_path, monkeypatch, capsys) -> Sandbox:
    return Sandbox(tmp_path, monkeypatch, capsys)


def _rules(host: Path, topic: str = "topic") -> Path:
    return host / ".claude" / "rules" / f"{topic}.md"


def _assert_selftest_clean(sb: Sandbox) -> None:
    rows = sb.selftest_rows()
    for name in ("compiler", "markers", "drift"):
        assert rows.get(name, "").startswith("PASS"), rows


def _leftover(sb: Sandbox, host: Path, rid: str) -> Path:
    """What a retirement left before S-87: the real `retire` verb with the
    removal decision forced to "stays", so the file is rewritten to the bare
    marker pair and the compile record re-recorded, by the verb."""
    target = _rules(host)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(verbs, "_rules_file_goes", lambda home, spec: False)
        sb.retire(rid)
    # positive control: exactly the two marker lines, and an entry that
    # accepts them as they stand
    assert target.read_text(encoding="utf-8") == BARE_PAIR
    entry = sb.entry(host, target)
    assert entry is not None
    assert entry["sha256"] == compiled.sha256_hex(BARE_PAIR.rstrip("\n").encode("utf-8"))
    return target


# ------------------------------------------------ the host write removes it


def test_the_last_lesson_leaving_a_rules_file_removes_it_and_its_entry(sb):
    host = sb.host("plain-host")
    target = _rules(host)
    unpathed = sb.lesson(host, "topic", trigger="Editing anything")
    pathed = sb.lesson(host, "topic", "--rules-path", "src/**", trigger="Editing src")

    sb.retire(unpathed)
    # positive control: one live lesson left, so the file stays, now carrying
    # self-learn's own `paths:` block for the pathed lesson
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---\npaths:\n  - src/**\n---\n"), text
    assert f"({pathed})" in text and f"({unpathed})" not in text
    assert sb.entry(host, target) is not None

    before = sb.ledger_head()
    sb.retire(pathed)
    assert not target.exists()
    assert sb.entry(host, target) is None
    # the entry left in the retirement's own ledger commit
    slug = host_slug(sb.home, host, scope_kind="project")
    retire_commit = git(sb.home, "log", "--format=%H", "--grep", f"retire {pathed}", before + "..HEAD").stdout.split()
    assert len(retire_commit) == 1
    files = git(sb.home, "show", "--name-only", "--format=", retire_commit[0]).stdout
    assert f"compiled/{slug}.yaml" in files, files
    retired = sb.record(pathed)
    assert retired.status == "superseded"  # retired, its routing block kept
    assert (retired.routing or {}).get("rules_topic") == "topic"
    _assert_selftest_clean(sb)


def test_a_new_route_to_the_topic_after_removal_writes_a_fresh_file(sb):
    host = sb.host("plain-host")
    target = _rules(host)
    first = sb.lesson(host, "topic")
    sb.retire(first)
    assert not target.exists()
    second = sb.lesson(host, "topic", trigger="Editing again")
    text = target.read_text(encoding="utf-8")
    assert f"({second})" in text
    entry = sb.entry(host, target)
    assert entry is not None and entry["based_on_sha256"] is None
    _assert_selftest_clean(sb)


@pytest.mark.parametrize(
    "shape",
    ["line-outside", "frontmatter-key", "frontmatter-comment"],
)
def test_a_rules_file_holding_a_persons_text_is_kept(sb, shape):
    host = sb.host("plain-host")
    target = _rules(host)
    rid = sb.lesson(host, "topic", "--rules-path", "src/**")
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---\npaths:\n")  # control: self-learn's own block
    if shape == "line-outside":
        text = text + "\nAlso: keep the tests green.\n"
    elif shape == "frontmatter-key":
        text = text.replace("---\npaths:", "---\ndescription: my rules\npaths:", 1)
    else:
        text = text.replace("---\npaths:", "---\n# mine, keep\npaths:", 1)
    target.write_text(text, encoding="utf-8")
    # The person's text sits outside the managed region, which the compile
    # record does not cover: the region still reads `clean`, so the
    # retirement proceeds with no adopt.
    region = compiled.region_bytes(text, "managed")
    assert region is not None
    entry = sb.entry(host, target)
    assert entry is not None and entry["sha256"] == compiled.sha256_hex(region)

    sb.retire(rid)
    assert target.is_file()
    kept = target.read_text(encoding="utf-8")
    assert f"{BEGIN_MARKER}\n{END_MARKER}" in kept
    assert f"({rid})" not in kept and "src/**" not in kept
    person = {
        "line-outside": "Also: keep the tests green.",
        "frontmatter-key": "description: my rules",
        "frontmatter-comment": "# mine, keep",
    }[shape]
    assert person in kept
    assert sb.entry(host, target) is not None
    _assert_selftest_clean(sb)


def test_a_symlinked_rules_file_is_kept(sb):
    host = sb.host("plain-host")
    target = _rules(host)
    rid = sb.lesson(host, "topic")
    real = sb.tmp / "dotfiles-topic.md"
    real.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.unlink()
    target.symlink_to(real)
    sb.retire(rid)
    assert target.is_symlink()
    assert real.read_text(encoding="utf-8") == BARE_PAIR


def test_a_claude_md_emptied_the_same_way_keeps_its_markers(sb):
    host = sb.host("plain-host")
    rid = sb.teach(host, "--project")
    assert sb.cli("route", rid, "--dest", "claude-md:local", "--no-push", cwd=host) == 0
    local = host / "CLAUDE.local.md"
    assert f"({rid})" in local.read_text(encoding="utf-8")
    sb.retire(rid)
    assert local.read_text(encoding="utf-8") == BARE_PAIR
    assert sb.entry(host, local) is not None


def test_user_scope_rules_file_is_removed(sb):
    host = sb.host("plain-host")
    target = sb.user_home / ".claude" / "rules" / "topic.md"
    rid = sb.lesson(host, "topic", scope="--user")
    assert f"({rid})" in target.read_text(encoding="utf-8")  # control
    user_host = sb.user_home / ".claude"
    assert sb.entry(user_host, target, "user") is not None
    sb.retire(rid)
    assert not target.exists()
    assert sb.entry(user_host, target, "user") is None
    _assert_selftest_clean(sb)


def test_reroute_of_the_last_lesson_removes_the_old_file(sb):
    host = sb.host("plain-host")
    target = _rules(host)
    rid = sb.lesson(host, "topic")
    assert target.is_file()
    assert sb.cli("reroute", rid, "--dest", "claude-md:local", "--no-push") == 0, sb.out()
    assert not target.exists()
    assert sb.entry(host, target) is None
    assert f"({rid})" in (host / "CLAUDE.local.md").read_text(encoding="utf-8")
    _assert_selftest_clean(sb)


def test_replace_into_another_topic_removes_the_old_file(sb):
    host = sb.host("plain-host")
    old_target, new_target = _rules(host), _rules(host, "other")
    rid = sb.lesson(host, "topic")
    rc = sb.cli(
        "replace", rid, "--dest", "claude-md:rules:other", "--trigger", "Editing a file",
        "--instruction", "Check it twice.", "--because", "clearer", "--no-push",
    )
    assert rc == 0, sb.out()
    assert not old_target.exists()
    assert sb.entry(host, old_target) is None
    assert "check it twice." in new_target.read_text(encoding="utf-8")
    _assert_selftest_clean(sb)


def test_a_batch_applied_reconsider_reject_removes_the_file(sb):
    host = sb.host("plain-host")
    target = _rules(host)
    rid = sb.teach(host, "--project")
    folder = sb.tmp / "cases"
    folder.mkdir()

    def record_case(data: dict, actor: str) -> str:
        path = folder / f"case-{len(list(folder.glob('case-*.yaml')))}.yaml"
        _dump_yaml(path, data)
        return cases.record(sb.home, path, actor=actor)

    prior = record_case(_case([rid], "route", "route", scope="project"), "steward")
    verbs.route(sb.home, rid, dest="claude-md:rules:topic", by="steward", no_push=True)
    assert f"({rid})" in target.read_text(encoding="utf-8")  # control
    case = _case([rid], "reject", "reject", scope="project")
    case.update(kind="reconsider", supersedes=prior)
    rc = record_case(case, "steward")
    verbs.reconsider(sb.home, rid, case=rc, by="steward", no_push=True)
    sheet_path = sb.tmp / "sheet.yaml"
    _dump_yaml(sheet_path, {"version": 1, "case": rc, "items": [{"id": rid, "verb": "reject"}]})
    sheet = batch.load_sheet(sheet_path)

    preview = batch.dry_run(sb.home, sheet, actor="steward")
    assert preview.items[0].state == "would-apply", preview.items[0].detail
    result = batch.run(sb.home, sheet, no_push=True, actor="steward")
    assert result.items[0].state == "applied", result.items[0].detail
    assert sb.record(rid).status == "rejected"
    assert not target.exists()
    assert sb.entry(host, target) is None
    _assert_selftest_clean(sb)


# ------------------------------------------------------------- a git host


def _install_refusing_hook(tmp_path: Path, host: Path) -> None:
    hooks = tmp_path / "refusing-hooks"
    hooks.mkdir(exist_ok=True)
    script = hooks / "pre-commit"
    script.write_text("#!/bin/sh\necho 'test-hook: REFUSED' >&2\nexit 1\n", encoding="utf-8")
    script.chmod(0o755)
    git(host, "config", "core.hooksPath", str(hooks))


def test_a_git_host_commits_the_removal(sb):
    host = sb.host("git-host", mode="git")
    target = _rules(host)
    rid = sb.lesson(host, "topic")
    rel = ".claude/rules/topic.md"
    assert git(host, "ls-files", rel).stdout.strip() == rel  # control: tracked
    sb.retire(rid)
    assert not target.exists()
    assert git(host, "ls-files", rel).stdout == ""
    stat = git(host, "show", "--summary", "--format=%s", "HEAD").stdout
    assert f"delete mode 100644 {rel}" in stat, stat
    assert stat.startswith(f"self-learn: apply {rid}"), stat
    assert git(host, "status", "--porcelain").stdout == ""
    assert sb.entry(host, target) is None
    _assert_selftest_clean(sb)


def test_a_refused_host_commit_puts_the_rules_file_back(sb):
    host = sb.host("git-host", mode="git")
    target = _rules(host)
    rid = sb.lesson(host, "topic")
    before = target.read_bytes()
    head = git(host, "rev-parse", "HEAD").stdout.strip()
    _install_refusing_hook(sb.tmp, host)
    sb.out()
    sb.retire(rid)
    out = sb.out()
    assert "HOST PHASE FAILED" in out and "put back" in out, out
    assert target.read_bytes() == before
    assert git(host, "rev-parse", "HEAD").stdout.strip() == head
    assert git(host, "status", "--porcelain").stdout == ""
    # The entry left with the ledger commit, so the restored region has no
    # compile-record entry: the next recompile rewrites it to the empty
    # region (and records it), and the one after removes it.
    assert sb.entry(host, target) is None
    git(host, "config", "--unset", "core.hooksPath")
    assert sb.cli("recompile", "--no-push") == 0, sb.out()
    assert target.read_text(encoding="utf-8") == BARE_PAIR
    assert sb.entry(host, target) is not None
    assert sb.cli("recompile", "--no-push") == 0, sb.out()
    assert not target.exists()
    assert sb.entry(host, target) is None


# ------------------------------------------------------- recompile's leftovers


def test_recompile_removes_a_leftover_and_drops_its_entry(sb):
    host = sb.host("plain-host")
    rid = sb.lesson(host, "topic")
    target = _leftover(sb, host, rid)

    assert sb.cli("recompile", "--no-push") == 0, sb.out()
    assert not target.exists()
    assert sb.entry(host, target) is None
    _assert_selftest_clean(sb)
    head = sb.ledger_head()
    assert sb.cli("recompile", "--no-push") == 0
    assert sb.ledger_head() == head  # a second run has nothing to do


def test_recompile_removes_a_leftover_in_a_git_host_and_commits_it(sb):
    host = sb.host("git-host", mode="git")
    rid = sb.lesson(host, "topic")
    target = _leftover(sb, host, rid)
    rel = ".claude/rules/topic.md"
    assert git(host, "show", f"HEAD:{rel}").stdout == BARE_PAIR  # control: committed

    assert sb.cli("recompile", "--no-push") == 0, sb.out()
    assert not target.exists()
    stat = git(host, "show", "--summary", "--format=%s", "HEAD").stdout
    assert stat.startswith(f"self-learn: recompile {rel}"), stat
    assert f"delete mode 100644 {rel}" in stat, stat
    assert git(host, "status", "--porcelain").stdout == ""
    assert sb.entry(host, target) is None
    _assert_selftest_clean(sb)


def test_recompile_drops_the_entry_of_a_leftover_deleted_and_committed_by_hand(sb):
    host = sb.host("git-host", mode="git")
    rid = sb.lesson(host, "topic")
    target = _leftover(sb, host, rid)
    rel = ".claude/rules/topic.md"
    git(host, "rm", "-q", "--", rel)
    git(host, "commit", "-q", "-m", "drop the empty rules file by hand")
    # positive control: gone from disk and from HEAD, the tree clean, and
    # the compile record still holds its entry
    assert not target.exists()
    assert git(host, "ls-files", rel).stdout == ""
    assert git(host, "status", "--porcelain").stdout == ""
    assert sb.entry(host, target) is not None
    head = git(host, "rev-parse", "HEAD").stdout.strip()

    assert sb.cli("recompile", "--no-push") == 0, sb.out()
    assert not target.exists()
    assert sb.entry(host, target) is None
    assert git(host, "rev-parse", "HEAD").stdout.strip() == head  # nothing to commit there
    _assert_selftest_clean(sb)


def test_recompile_rewrites_a_stale_leftover_and_re_records_it(sb):
    """A plain host whose host write never landed: the ledger and the
    compile record say the lesson left (entry = the bare pair, based on
    the region that still held it), the file still holds the old region
    (`stale`). `recompile` does not remove a stale file; it rewrites it to
    the bare pair and re-records it -- the entry must stay while the file
    does."""
    host = sb.host("plain-host")
    target = _rules(host)
    rid = sb.lesson(host, "topic")
    unlanded = target.read_text(encoding="utf-8")
    _leftover(sb, host, rid)
    target.write_text(unlanded, encoding="utf-8")  # the write that never landed
    entry = sb.entry(host, target)
    region = compiled.region_bytes(unlanded, "managed")
    assert entry is not None and region is not None
    # positive control: the region reads `stale` against its entry
    assert compiled.verdict_for(entry, compiled.sha256_hex(region)) == "stale"

    assert sb.cli("recompile", "--no-push") == 0, sb.out()
    assert target.read_text(encoding="utf-8") == BARE_PAIR
    entry = sb.entry(host, target)
    assert entry is not None
    assert entry["sha256"] == compiled.sha256_hex(BARE_PAIR.rstrip("\n").encode("utf-8"))
    _assert_selftest_clean(sb)
    # and with the record now `clean`, the next recompile removes it
    assert sb.cli("recompile", "--no-push") == 0, sb.out()
    assert not target.exists()
    assert sb.entry(host, target) is None


def test_recompile_keeps_an_edited_leftover(sb):
    host = sb.host("plain-host")
    rid = sb.lesson(host, "topic")
    target = _leftover(sb, host, rid)
    edited = BARE_PAIR.replace(END_MARKER, "- my own note\n" + END_MARKER)
    target.write_text(edited, encoding="utf-8")
    sb.out()
    sb.cli("recompile", "--no-push")
    assert "edited" in sb.out()
    assert target.read_text(encoding="utf-8") == edited
    assert sb.entry(host, target) is not None


def test_recompile_keeps_a_leftover_with_no_compile_record_entry(sb):
    host = sb.host("plain-host")
    rid = sb.lesson(host, "topic")
    target = _leftover(sb, host, rid)
    # unknown provenance: the record holds no entry for this file
    slug = host_slug(sb.home, host, scope_kind="project")
    assert compiled.delete_entry(sb.home, slug, compiled.region_key(host, target, "managed"))
    commit_all(sb.home, "drop the entry by hand")
    assert sb.cli("recompile", "--no-push") == 0, sb.out()
    assert target.read_text(encoding="utf-8") == BARE_PAIR


def test_recompile_does_not_recreate_a_hand_deleted_leftover(sb):
    host = sb.host("plain-host")
    rid = sb.lesson(host, "topic")
    target = _leftover(sb, host, rid)
    target.unlink()
    assert sb.cli("recompile", "--no-push") == 0, sb.out()
    assert not target.exists()
    assert sb.entry(host, target) is None
    _assert_selftest_clean(sb)


# ------------------------------------------------------------ the selftest


def test_selftest_passes_a_hand_deleted_leftover(sb):
    host = sb.host("plain-host")
    rid = sb.lesson(host, "topic")
    target = _leftover(sb, host, rid)
    # control: with the file present the markers row counts it
    rows = sb.selftest_rows()
    assert rows["markers"].startswith("PASS marker pairs intact on 1 target"), rows
    target.unlink()
    rows = sb.selftest_rows()
    assert rows["markers"].startswith("PASS"), rows
    assert "file missing" not in rows["markers"]


def test_selftest_still_fails_a_live_rules_lesson_with_no_file(sb):
    host = sb.host("plain-host")
    target = _rules(host)
    sb.lesson(host, "topic")
    target.unlink()
    rows = sb.selftest_rows()
    assert rows["markers"] == f"FAIL {target} (1 routed record): file missing", rows


def test_selftest_still_fails_a_non_rules_target_with_no_file(sb):
    host = sb.host("plain-host")
    rid = sb.teach(host, "--project")
    assert sb.cli("route", rid, "--dest", "claude-md:local", "--no-push", cwd=host) == 0
    sb.retire(rid)
    local = host / "CLAUDE.local.md"
    local.unlink()
    rows = sb.selftest_rows()
    assert rows["markers"] == f"FAIL {local} (1 routed record): file missing", rows


def test_the_leftover_sha_matches_the_live_host_files():
    """The two leftovers on the maintainer's host (premise in the brief)
    hash `e73f82e5…e233`; the bare pair this file builds is those bytes."""
    digest = hashlib.sha256(BARE_PAIR.encode("utf-8")).hexdigest()
    assert digest.startswith("e73f82e5") and digest.endswith("e233")
