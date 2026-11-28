"""Finding Claude Code's session transcripts on native Windows.

On Windows the rule Claude Code uses to name a transcript folder after the
working directory is not documented, and two working directories can share
one folder name. These tests build a synthetic ``projects`` tree in both
plausible spellings (drive colon replaced by ``-`` and dropped; backslashes
replaced by ``-``) and check that every reader chooses files by what they
record (``sessionId``, ``cwd``), compares paths the way registered projects
are compared, follows no link inside the tree, and reads CRLF, non-ASCII and
still-growing files. No real transcript and no model call: every file here
is written by the test.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn import hosts, miner, session_copies
from self_learn.ledger import Bucket
from self_learn.mining import flags, tasks
from self_learn.primitives import names

windows = pytest.mark.skipif(os.name != "nt", reason="Windows transcript discovery")
linux = pytest.mark.skipif(os.name == "nt", reason="Linux transcript discovery")

SID = {k: f"{k}0000000-1111-2222-3333-444444444444" for k in "abcdefgh"}
WIDE = "é日本"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    home = tmp_path / "ledger"
    home.mkdir()
    claude = tmp_path / "claude"
    projects = claude / "projects"
    projects.mkdir(parents=True)
    work = tmp_path / "work"
    project = work / f"Proj-{WIDE}"
    other = work / "Proj" / WIDE  # a different project; its folder hint collides with `project`'s
    for p in (project, other):
        p.mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    monkeypatch.delenv("SELF_LEARN_TRANSCRIPTS_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    hint = names.claude_folder_hint(project, style="transcript")
    return SimpleNamespace(
        tmp=tmp_path, home=home, claude=claude, projects=projects, project=project, other=other,
        # the two plausible spellings of `project`'s folder
        colon=hint, nocolon=names.claude_folder_hint(str(project).replace(":", ""), style="transcript"),
    )


def _now(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()


def row(sid: str, cwd: Path | str, text: str = "hello", *, kind: str = "assistant", ts: str | None = None) -> str:
    entry: dict = {"type": kind, "sessionId": sid, "cwd": str(cwd), "timestamp": ts or _now()}
    if kind == "assistant":
        entry["message"] = {"content": [{"type": "text", "text": text}]}
    else:
        entry["message"] = {"role": "user", "content": text}
    return json.dumps(entry, ensure_ascii=False)


def write(path: Path, rows: list[str], *, newline: str = "\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(r + newline for r in rows).encode("utf-8"))
    return path


def junction(target: Path, link: Path) -> None:
    import _winapi

    target.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))
    assert link.is_junction()


# --------------------------------------------------------------- Windows


@windows
def test_windows_root_follows_claude_root_and_keeps_one_spelling(tree, monkeypatch):
    # The built-in default resolves through names.claude_root(use="transcripts").
    assert str(miner.transcripts_root()) == str(tree.projects.resolve())
    config = tree.tmp / "config-dir"
    (config / "projects").mkdir(parents=True)
    monkeypatch.delenv("SELF_LEARN_CLAUDE_DIR")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    assert str(miner.transcripts_root()) == str((config / "projects").resolve())
    # A configured root written in another case or with forward slashes
    # gives the same cursor keys: one spelling, the one on disk.
    for spelling in (str(tree.projects).upper(), str(tree.projects).replace("\\", "/")):
        monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", spelling)
        assert str(miner.transcripts_root()) == str(tree.projects.resolve())


@windows
def test_windows_walk_chooses_files_by_content_not_folder(tree):
    a = write(tree.projects / tree.colon / f"{SID['a']}.jsonl", [row(SID["a"], tree.project)])
    b = write(tree.projects / tree.nocolon / f"{SID['b']}.jsonl", [row(SID["b"], tree.project)])
    # named for one session, recording another: not that session's transcript
    write(tree.projects / tree.colon / f"{SID['c']}.jsonl", [row(SID["d"], tree.project)])
    # a junction inside projects/ leads out of the tree
    outside = tree.tmp / "outside"
    write(outside / f"{SID['e']}.jsonl", [row(SID["e"], tree.project)])
    junction(outside, tree.projects / "linked-folder")
    # a linked file inside an ordinary folder
    stray = write(tree.tmp / "stray" / "s.jsonl", [row(SID["f"], tree.project)])
    (tree.projects / tree.colon / f"{SID['f']}.jsonl").symlink_to(stray)

    assert tree.colon != tree.nocolon
    slices = miner.walk()
    # (resolved: the runner's temporary folder may be spelled with 8.3 short names)
    assert sorted((s.session_id, s.path) for s in slices) == sorted([(SID["a"], a.resolve()), (SID["b"], b.resolve())])
    # forward-only seeding never reads through a link either
    miner._save_cursors({})
    assert miner.initialize_cursors() == 3
    keys = [k for k in miner._load_cursors() if not k.startswith("__")]
    assert all(Path(k).parent.parent == miner.transcripts_root() for k in keys)
    assert not any(SID["e"] in k or SID["f"] in k for k in keys)


@windows
def test_windows_walk_reads_crlf_non_ascii_while_appended(tree):
    path = tree.projects / tree.colon / f"{SID['a']}.jsonl"
    rows = [row(SID["a"], tree.project, f"first {WIDE}", kind="user"), row(SID["a"], tree.project, f"second {WIDE}")]
    write(path, rows, newline="\r\n")
    last = row(SID["a"], tree.project, f"third {WIDE}")
    cut = len(last.encode("utf-8")) // 2
    # Claude Code still holds the file open and is mid-row.
    with path.open("ab") as writer:
        writer.write(last.encode("utf-8")[:cut])
        writer.flush()
        [first] = miner.walk()
        assert len(first.lines) == 2 and first.start_line == 0
        assert [json.loads(r)["message"]["content"] if i == 0 else json.loads(r)["message"]["content"][0]["text"]
                for i, r in enumerate(first.lines)] == [f"first {WIDE}", f"second {WIDE}"]
        assert all(r.endswith("\r") for r in first.lines)
        miner._advance_cursors([(first, False)])
        writer.write(last.encode("utf-8")[cut:] + b"\r\n")
        writer.flush()
        [second] = miner.walk()
    assert second.start_line == 2 and len(second.lines) == 1
    assert json.loads(second.lines[0])["message"]["content"][0]["text"] == f"third {WIDE}"


def _capture(tree, sid: str, cwd: Path | str | None):
    return session_copies.capture(home=tree.home, surface="steward", session_id=sid, group="g1",
                                  fallback_group="fallback", cwd=cwd)


@windows
def test_windows_session_copy_proves_session_and_working_directory(tree):
    sid = SID["a"]
    # The folder the cwd rule would guess holds a copy of the id written by a
    # different project (and larger, so "first" or "largest" would pick it).
    write(tree.projects / tree.colon / f"{sid}.jsonl",
          [row(sid, tree.other, "WRONG PROJECT " + "x" * 400)])
    # The real one records the same project spelled in another case and with
    # forward slashes, in the other spelling's folder.
    spelled = str(tree.project).upper().replace("\\", "/")
    real = write(tree.projects / tree.nocolon / f"{sid}.jsonl", [row(sid, spelled, "RIGHT PROJECT")])
    write(real.parent / sid / "subagents" / "agent-a1.jsonl", [row(sid, spelled, "sub")])

    record = _capture(tree, sid, tree.project)
    assert record is not None and "error" not in record, record
    copy = session_copies.worker.cache_dir(tree.home) / record["path"]
    assert b"RIGHT PROJECT" in copy.read_bytes()
    assert record["subagent_files"] == 1

    # Only a copy written by another project: nothing is attributed.
    lone = SID["b"]
    write(tree.projects / tree.colon / f"{lone}.jsonl", [row(lone, tree.other)])
    assert _capture(tree, lone, tree.project)["error"] == "no transcript file found for this session"


@windows
def test_windows_session_copy_follows_no_link(tree):
    sid = SID["c"]
    real = write(tree.projects / tree.colon / f"{sid}.jsonl", [row(sid, tree.project)])
    outside = tree.tmp / "outside-subagents"
    write(outside / "agent-z9.jsonl", [row(sid, tree.project, "outside the tree")])
    (real.parent / sid).mkdir()
    junction(outside, real.parent / sid / "subagents")
    record = _capture(tree, sid, tree.project)
    assert record is not None and "error" not in record, record
    assert "subagent_files" not in record

    # The session's only copy sits in a linked folder: not found.
    linked = SID["d"]
    elsewhere = tree.tmp / "elsewhere"
    write(elsewhere / f"{linked}.jsonl", [row(linked, tree.project)])
    junction(elsewhere, tree.projects / "linked-folder")
    assert _capture(tree, linked, tree.project)["error"] == "no transcript file found for this session"


@windows
def test_windows_project_scope_compares_like_registered_projects(tree):
    bucket = Bucket(path=tree.tmp / "bucket", scope="project", name=hosts.slug_for(tree.project))
    registered = [tree.project, tree.other]
    text = str(tree.project)
    same = [Path(text.lower()), Path(text.upper()), Path(text.replace("\\", "/")), Path(text + "\\"),
            Path("\\\\?\\" + text), tree.project / "src" / "deep"]
    for cwd in same:
        assert flags._in_scope(bucket, cwd, registered, []), cwd
    for cwd in (tree.other, Path(text + "-other"), tree.tmp / "work"):
        assert not flags._in_scope(bucket, cwd, registered, []), cwd


@windows
def test_windows_named_and_backfill_sessions_are_chosen_by_content(tree):
    sid = SID["a"]
    good = write(tree.projects / tree.colon / f"{sid}.jsonl", [row(sid, tree.project, "named")])
    # larger impostors: a file of that name recording another session, and a
    # copy reached through a junction
    write(tree.projects / tree.nocolon / f"{sid}.jsonl", [row(SID["h"], tree.project, "y" * 500)])
    outside = tree.tmp / "outside"
    write(outside / f"{sid}.jsonl", [row(sid, tree.project, "z" * 500)])
    junction(outside, tree.projects / "linked-folder")
    slices, missing = miner._named_slices(tree.home, [sid, SID["g"]])
    assert [s.path for s in slices] == [good.resolve()] and missing == [SID["g"]]

    # self-learn's own session: its recorded cwd lies under the cache root,
    # whatever folder Claude Code put it in
    own_cwd = miner.miner_dir().parent.parent / "stage" / "work"
    write(tree.projects / "ordinary-looking" / f"{SID['b']}.jsonl", [row(SID["b"], own_cwd)])
    found = miner._backfill_slices(tree.home, 1)
    assert sorted(s.session_id for s in found) == [sid]


@windows
def test_windows_later_session_search_follows_recorded_working_directory(tree):
    words = "frobnicate the widget"
    start = tree.projects / tree.colon / f"{SID['a']}.jsonl"
    write(start, [row(SID["a"], tree.project, "begin", kind="user", ts=_now(-7200))])
    # one folder, two projects (the collision the folder rule cannot tell apart)
    write(tree.projects / tree.colon / f"{SID['b']}.jsonl", [row(SID["b"], tree.project, words)])
    write(tree.projects / tree.colon / f"{SID['c']}.jsonl", [row(SID["c"], tree.other, words)])
    # the project's worktree, in a folder of any name
    worktree = str(tree.project).lower() + "\\.claude\\worktrees\\w1"
    write(tree.projects / "anything" / f"{SID['d']}.jsonl", [row(SID["d"], worktree, words)])
    # an unrelated project, and self-learn's own session
    write(tree.projects / "unrelated" / f"{SID['e']}.jsonl", [row(SID["e"], tree.tmp / "work", words)])
    own_cwd = miner.miner_dir().parent.parent / "stage"
    write(tree.projects / "unrelated" / f"{SID['f']}.jsonl", [row(SID["f"], own_cwd, words)])

    item = {"session": SID["a"], "transcript": str(start), "cwd": str(tree.project), "line": 1,
            "entry_ts": _now(-3600), "project_dir": tree.colon}
    check = tasks.CheckTools({"T1": item}, tree.projects, None, frozenset(),  # type: ignore[arg-type]
                             skip_prefix=miner._own_folders_prefix())

    def sessions(text: str) -> set[str]:
        return {sid for sid in SID.values() if f"session {sid}" in text}

    assert sessions(check.search_later_sessions("T1", words)) == {SID["b"], SID["d"]}
    assert sessions(check.search_later_sessions("T1", words, all_folders=True)) == {SID["b"], SID["d"], SID["e"]}


# ----------------------------------------------------------------- Linux


@linux
def test_linux_discovery_keeps_the_folder_listing_and_trusts_names(tmp_path, monkeypatch):
    """Linux is unchanged: the listing is the one glob it always was, and a
    file is mined by its name, whatever its rows record."""
    root = tmp_path / "transcripts"
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "ledger"))
    (tmp_path / "ledger").mkdir()
    path = write(root / "-home-u-proj" / f"{SID['a']}.jsonl", ['{"type": "user", "message": {"content": "x"}}'])
    calls = []
    original = Path.glob

    def glob(self, pattern, *args, **kwargs):
        calls.append((self, pattern))
        return original(self, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", glob)
    miner._save_cursors({"__initialized__": "test"})
    assert [s.path for s in miner.walk()] == [path]
    assert calls == [(root, "*/*.jsonl")]
