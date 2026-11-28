"""Git history, path identity and index contracts on a hostile checkout."""
from __future__ import annotations

from contextlib import closing
from datetime import date, timezone
import json
import os
import socket
import sqlite3
import subprocess
import time

import pytest

from self_learn import gitops, script_proof, select, series
from self_learn.index import fts5
from self_learn.index.store import LessonIndex
from self_learn.records import Record

windows = pytest.mark.skipif(os.name != "nt", reason="native Windows Git contract")


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          timeout=15).stdout


def put(root, key, data):
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def repo(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    root = tmp_path / "ledger space"
    root.mkdir()
    for key in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(profile))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(profile / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("SELF_LEARN_HOME", str(root))
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2025-03-02T12:00:00Z")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2025-03-02T12:00:00Z")
    git(root, "config", "--global", "core.autocrlf", "true")
    git(root, "init", "-q", "-b", "main")
    assert git(root, "config", "--get", "core.autocrlf").strip() == b"true"
    # The capture lane owns setting this on init. Exercise the reader's input.
    git(root, "config", "--local", "core.autocrlf", "false")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    return root


def test_daily_history(repo):
    pending = "projects/box [1]/pending/lrn-00000001.md"
    deferred = "user/pending/lrn-00000002.md"
    data = "---\r\nstatus: pending\r\n---\r\ncafé\r\n".encode()
    put(repo, pending, data)
    put(repo, deferred, data.replace(b"pending", b"deferred"))
    put(repo, "café [x].txt", b"not a record\n")
    git(repo, "add", "--", ".")
    git(repo, "commit", "-qm", "daily snapshot")
    assert git(repo, "cat-file", "blob", "HEAD:" + pending) == data
    result = series.day_series(repo, today=date(2025, 3, 2), tz=timezone.utc, days=2, events=[])
    assert result["error"] is None
    assert [(r["date"], r["pending"], r["deferred"]) for r in result["rows"]] == [
        ("2025-03-01", 0, 0), ("2025-03-02", 1, 1)]


@windows
def test_windows_history_counts_quoted_bucket_and_framed_blob(repo):
    # Text resembling a batch header is legal inside the counted blob.
    key = "skills/café [2]/pending/lrn-00000003.md"
    put(repo, key, b"---\r\n" + b"a" * 40 + b" blob 8\r\nstatus: deferred\r\n---\r\n\xff")
    git(repo, "add", "--", ".")
    git(repo, "commit", "-qm", "unicode bucket")
    result = series.day_series(repo, today=date(2025, 3, 2), tz=timezone.utc, days=1, events=[])
    assert result["error"] is None
    assert result["rows"][0]["deferred"] == 1


def test_selected_paths(repo):
    keys = ["src/box[1].txt", "src/two words.txt", "src/café.txt"]
    if os.name != "nt":
        keys.append("src/two\nlines.txt")
    for key in keys:
        put(repo, key, b"x")
    git(repo, "add", "--", "src")
    expected = sorted(keys)
    assert list(select._git_files(repo, {"src"}, [0, 0], deadline=time.monotonic() + 15)) == expected
    assert select.task_paths(["src/*.txt"], repo) == expected
    # Both consumers see these exact names, including the POSIX-only newline.
    status = git(repo, "--literal-pathspecs", "status", "--porcelain", "-z", "--", "src")
    assert gitops._dirty_path_names(status) == expected


def test_review_commit_bytes(repo):
    from self_learn.skill_scripts import INDEX, _held

    row = {"id": "example", "skill": "café [1]", "name": "two words", "version": "v1",
           "state": "approved", "review": {"session": "test", "verdict": "approve"}}
    draft = _held(repo, row)
    raw = b"# bytes\r\n\xff\x00\r\n"
    transcript = '{"note":"café"}\r\n'.encode()
    put(repo, draft, raw)
    put(repo, draft.with_name("review.jsonl"), transcript)
    put(repo, INDEX, json.dumps({"scripts": [row]}, ensure_ascii=False).encode())
    git(repo, "add", "--", ".")
    git(repo, "commit", "-qm", "self-learn: script review example: approve",
        "-m", "Script-Version: v1\nScript-Session: test")
    for path, data in [(draft, raw), (draft.with_name("review.jsonl"), transcript)]:
        assert git(repo, "show", "HEAD:" + path.relative_to(repo).as_posix()) == data
    assert script_proof.verify_commit(repo, row, raw, transcript) is None
    for a, b in ((raw.replace(b"\r\n", b"\n"), transcript), (raw, transcript.rstrip(b"\r\n") + b"\n")):
        with pytest.raises(ValueError, match="matching self-learn review commit"):
            script_proof.verify_commit(repo, row, a, b)


@windows
def test_windows_literal_status_and_diff(repo):
    folder = "café [1]"
    old = f"{folder}/old name"
    new = f"{folder}/new [2]"
    sibling = "café 1/unrelated"
    put(repo, old, b"rename me")
    put(repo, sibling, b"original")
    git(repo, "add", "--", ".")
    git(repo, "commit", "-qm", "before rename")
    git(repo, "mv", "--", old, new)
    put(repo, sibling, b"decoy edit")
    git(repo, "add", "--", sibling)
    assert gitops.is_tracked(repo, new)
    assert not gitops.is_tracked(repo, f"{folder}/unrelated")
    assert gitops.paths_dirty(repo, new)
    assert not gitops.paths_dirty(repo, f"{folder}/unrelated")
    assert gitops.dirty_paths(repo, folder) == [new]
    diff = gitops.staged_diff(repo, [repo / folder])
    assert "rename from " in diff and "decoy edit" not in diff
    assert "decoy edit" in gitops.staged_diff(repo, [sibling])
    assert gitops.staged_diff(repo, [f"{folder}/unrelated"]) == ""
    assert git(repo, "show", ":" + sibling) == b"decoy edit"
    put(repo, f"{folder}/untracked dir/file", b"new")
    assert set(gitops.dirty_paths(repo, folder)) == {new, f"{folder}/untracked dir/"}


def test_fts5_round_trip(repo, tmp_path):
    print(f"SQLite {sqlite3.sqlite_version}")
    rid = "lrn-00112233"
    fact = "Le café conserve sa fraîcheur."
    record = Record.create(type="knowledge", scope="user", source="teach", fact=fact, record_id=rid)
    data = record.to_text().replace("\n", "\r\n").encode()
    lesson = put(repo, f"user/pending/{rid}.md", data)
    db = tmp_path / "index.sqlite"
    with closing(LessonIndex.open_at(db, repo)) as index:
        assert index.build(provider=None).added == [rid]
    with closing(LessonIndex.open_at(db, repo)) as reopened:
        assert [key for key, _ in fts5.search(reopened.conn, "fraîcheur")] == [rid]
        assert reopened.docs()[rid].text == fact
    assert b"\r\n" in data and lesson.read_bytes() == data


def test_push_local_bare(repo, tmp_path):
    remote = tmp_path / "bare remote"
    git(repo, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "config", "push.default", "current")
    git(repo, "commit", "--allow-empty", "-qm", "publish")
    assert gitops.push_if_remote(repo).ok
    assert git(remote, "rev-parse", "refs/heads/main") == git(repo, "rev-parse", "HEAD")


@windows
def test_windows_unreachable_push_env(repo, tmp_path, monkeypatch):
    trace = tmp_path / "trace.jsonl"
    git(repo, "commit", "--allow-empty", "-qm", "unpublished")
    git(repo, "config", "push.default", "current")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("GIT_TRACE2_EVENT", trace.as_posix())
    prompt_vars = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    monkeypatch.setenv("GIT_TRACE2_ENV_VARS", ",".join(prompt_vars))
    for key in prompt_vars:
        monkeypatch.delenv(key, raising=False)
    # Reserve the port without listening. Both connection attempts get a local refusal.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        remote = f"https://127.0.0.1:{reserved.getsockname()[1]}/unreachable"
        git(repo, "remote", "add", "origin", remote)
        monkeypatch.setattr(gitops, "GIT_NETWORK_TIMEOUT", 8)
        start = time.monotonic()
        result = gitops.push_with_retry(repo)
        assert time.monotonic() - start < 20
    assert result.exit_code == gitops.EXIT_PUSH_FAILED and result.retried
    events = [json.loads(line) for line in trace.read_bytes().splitlines()]
    for verb in ("push", "pull"):
        ids = [e["sid"] for e in events if e["event"] == "start" and verb in e["argv"]]
        assert len(ids) == 1
        seen = {e["param"]: e["value"] for e in events
                if e["sid"] == ids[0] and e["event"] == "def_param" and e["param"] in prompt_vars}
        assert seen == prompt_vars
