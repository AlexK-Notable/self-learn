"""Gate regressions for malformed stores, file dates and Hermes caching."""
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from self_learn import provenance as p
from test_provenance_senders import BRIEF, ORCH, _ts, bash, brief_file, harness, role, send_file, write


@pytest.mark.parametrize("harness_name", ["claude", "codex", "pi", "agy", "hermes"])
@pytest.mark.parametrize("bad_field,bad_char", [("filename", "\0"), ("cwd", "\0"),
                                                ("filename", "\ud800"), ("cwd", "\udfff")])
def test_bad_stored_paths_drop_only_the_bad_row(tmp_path, harness_name, bad_field, bad_char):
    good = send_file(tmp_path / "good", f"herdr agent prompt worker '{BRIEF}'")
    assert role(good) == "agent"
    cwd = str(tmp_path) + bad_char if bad_field == "cwd" else str(tmp_path)
    filename = str(tmp_path / "brief") + bad_char if bad_field == "filename" else "brief"
    command = f'herdr agent prompt worker "$(cat \'{filename}\')"'
    if harness_name == "claude":
        bad = send_file(tmp_path / "bad", command, cwd)
    else:
        bad = harness(tmp_path / "bad", harness_name, command, tmp_path if harness_name == "hermes" else cwd)
        if harness_name == "hermes":
            set_hermes_args(bad, command, workdir=cwd)
        if harness_name == "codex":
            path = next(bad.rglob("*.jsonl"))
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[1]["payload"]["arguments"] = json.dumps({"cmd": command, "workdir": cwd})
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        if harness_name == "pi":  # A per-call cwd, not just a separate header row.
            path = next(bad.rglob("*.jsonl"))
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[1]["message"]["content"][0]["arguments"]["cwd"] = cwd
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert len(p.sweep([bad])) == 0
    # A valid row in the very same file/database must survive the bad row.
    inline = f"herdr agent prompt worker '{BRIEF}'"
    if harness_name == "hermes":
        calls = [{"function": {"name": "terminal", "arguments": json.dumps({"command": inline})}}]
        with sqlite3.connect(bad / "state.db") as db:
            db.execute("INSERT INTO messages VALUES (?, ?, ?, ?)",
                       ("good", p._epoch(_ts(8)), "assistant", json.dumps(calls)))
    else:
        if harness_name == "claude":
            valid = bash(inline, 8)
        elif harness_name == "codex":
            valid = {"type": "response_item", "timestamp": _ts(8), "payload": {
                "type": "function_call", "arguments": json.dumps({"cmd": inline, "workdir": str(tmp_path)})}}
        elif harness_name == "pi":
            valid = {"type": "message", "timestamp": _ts(8), "message": {"role": "assistant", "content": [
                {"type": "toolCall", "name": "bash", "arguments": {"command": inline, "cwd": str(tmp_path)}}]}}
        else:
            valid = {"type": "PLANNER_RESPONSE", "created_at": _ts(8), "tool_calls": [
                {"name": "run_command", "args": {"CommandLine": inline, "Cwd": str(tmp_path)}}]}
        with next(bad.rglob("*.jsonl")).open("a") as fh:
            fh.write(json.dumps(valid) + "\n")
    assert len(p.sweep([bad])) == 1
    assert len(p.sweep([bad, good])) == 2


@pytest.mark.parametrize("bad", ["/bad\0name", "/bad\ud800name"])
def test_invalid_path_text_rejected_before_path_construction(monkeypatch, bad):
    assert p._cwd("/synthetic") == "/synthetic"
    valid = p.Send(1, "sender", 'herdr agent prompt worker "$(cat /synthetic)"', "")
    assert p._brief_paths(valid) == [Path("/synthetic")]
    original = p.Path

    def guarded(value):
        assert value != bad, "invalid stored text reached Path"
        return original(value)

    monkeypatch.setattr(p, "Path", guarded)
    with pytest.raises(ValueError):
        p._cwd(bad)
    with pytest.raises(ValueError):
        p._brief_paths(p.Send(1, "sender", f'herdr agent prompt worker "$(cat {bad})"', ""))


def test_value_errors_in_stat_and_open_are_misses(tmp_path, monkeypatch):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"
    original_stat = Path.stat

    def broken_stat(target, *args, **kwargs):
        if target == path:
            raise ValueError("malformed stored path")
        return original_stat(target, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", broken_stat)
    assert p._fingerprint(path) is None
    assert role(root) == "user"
    assert len(p.sweep([root])) == 1
    monkeypatch.setattr(Path, "stat", original_stat)
    assert role(root) == "agent"
    p._CACHE.clear()
    original_open = os.open

    def broken_open(target, *args, **kwargs):
        if target == path:
            raise ValueError("malformed stored path")
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(os, "open", broken_open)
    assert role(root) == "user"
    assert len(p.sweep([root])) == 1


def test_bad_store_does_not_abort_other_stores(tmp_path, monkeypatch):
    good = send_file(tmp_path / "good", f"herdr agent prompt worker '{BRIEF}'")
    assert role(good) == "agent"
    broken = tmp_path / ".hermes"
    broken.mkdir()
    (broken / "state.db").write_bytes(b"not a sqlite database")
    bad_file = write(good, "000-broken", [bash("herdr pane read worker", 8)])
    original = p._file_sends

    def read(path):
        if path == bad_file:
            raise TypeError("malformed store")
        return original(path)

    monkeypatch.setattr(p, "_file_sends", read)
    assert len(p.sweep([broken, Path("bad\0store"), good])) == 1


def test_old_mtime_with_new_ctime_is_not_historical_evidence(tmp_path):
    path = tmp_path / "brief"
    replacement = tmp_path / "older-draft"
    for target in (path, replacement):
        target.write_text(BRIEF)
        os.utime(target, (1, 1))
    at = time.time()
    cmd = f'herdr agent prompt worker "$(cat {path})"'
    row = bash(cmd, 8)
    row["timestamp"] = datetime.fromtimestamp(at, timezone.utc).isoformat()
    root = tmp_path / "transcripts"
    write(root, ORCH, [row])
    assert sum(s.file_text for s in p.sweep([root])._sends) == 1
    time.sleep(0.002)
    os.replace(replacement, path)
    assert path.stat().st_mtime <= at < path.stat().st_ctime
    assert sum(s.file_text for s in p.sweep([root])._sends) == 0
    p._CACHE.clear()  # The guard is necessary on a cold process too.
    assert sum(s.file_text for s in p.sweep([root])._sends) == 0


def test_relative_cwd_never_uses_the_process_directory(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    path = brief_file(work)
    monkeypatch.chdir(tmp_path)
    command = f'herdr agent prompt worker "$(cat \'{path.name}\')"'
    root = send_file(tmp_path, command, work)
    assert role(root) == "agent"
    send_file(tmp_path, command, "work")
    assert role(root) == "user"


@pytest.mark.parametrize("filename", ["$brief", "brief*", "brief?", "brief[1]", "~brief",
                                      "brief;x", "brief&x", "brief|x", "brief<x", "brief>x"])
def test_filename_character_filter_has_a_real_matching_file(tmp_path, filename):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"
    rejected = tmp_path / filename
    path.rename(rejected)
    send_file(tmp_path, f'herdr agent prompt worker "$(cat \'{rejected}\')"')
    assert role(root) == "user"


@pytest.mark.parametrize("prefix", ["echo agent prompt", "herdr agent read", "herdr pane prompt"])
def test_executable_and_verb_are_required_at_the_same_argument_positions(tmp_path, prefix):
    path = brief_file(tmp_path)
    suffix = f' worker "$(cat \'{path}\')"'
    root = send_file(tmp_path, "herdr agent prompt" + suffix)
    assert role(root) == "agent"
    send_file(tmp_path, prefix + suffix)
    assert role(root) == "user"


def set_hermes_args(root, command, **extra):
    calls = [{"function": {"name": "terminal", "arguments": json.dumps({"command": command, **extra})}}]
    with sqlite3.connect(root / "state.db") as db:
        db.execute("UPDATE messages SET tool_calls=?", (json.dumps(calls),))


def test_hermes_relative_paths_require_explicit_absolute_workdir(tmp_path):
    path = brief_file(tmp_path)
    cmd = f'herdr agent prompt worker "$(cat \'{path.name}\')"'
    root = harness(tmp_path, "hermes", cmd, tmp_path)
    assert role(root) == "agent"
    set_hermes_args(root, cmd)
    assert role(root) == "user"  # sessions.cwd still names the matching directory
    set_hermes_args(root, cmd, cwd=str(tmp_path))
    assert role(root) == "user"  # terminal does not use this key
    set_hermes_args(root, cmd, workdir=".")
    assert role(root) == "user"
    set_hermes_args(root, cmd, workdir=str(tmp_path))
    assert role(root) == "agent"


def test_hermes_cache_skips_unchanged_reads_and_observes_wal(tmp_path, monkeypatch):
    root = harness(tmp_path, "hermes", f"herdr agent prompt worker '{BRIEF}'", tmp_path)
    original = p._read_hermes_sends
    reads = 0

    def read(path):
        nonlocal reads
        reads += 1
        return original(path)

    monkeypatch.setattr(p, "_read_hermes_sends", read)
    assert role(root) == "agent"
    assert reads == 1
    assert role(root) == "agent"
    assert reads == 1
    db = sqlite3.connect(root / "state.db")
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        assert role(root) == "agent"
        at = p._db_stamp(root / "state.db")
        before = reads
        db.execute("DELETE FROM messages")
        db.commit()
        assert p._db_stamp(root / "state.db") == at  # Only the WAL changed.
        assert role(root) == "user"
        assert reads == before + 1
        assert role(root) == "user"
        assert reads == before + 1
    finally:
        db.close()


def test_hermes_cache_detects_database_replacement_with_same_size_and_mtime(tmp_path):
    root = harness(tmp_path, "hermes", f"herdr agent prompt worker '{BRIEF}'", tmp_path)
    assert role(root) == "agent"
    path = root / "state.db"
    stamp = p._db_stamp(path)
    replacement = root / "replacement.db"
    shutil.copyfile(path, replacement)
    with sqlite3.connect(replacement) as db:
        db.execute("DELETE FROM messages")
    os.utime(replacement, ns=(stamp[0], stamp[0]))
    os.replace(replacement, path)
    assert p._db_stamp(path)[:2] == stamp[:2]
    assert p._db_stamp(path)[2] != stamp[2]
    assert role(root) == "user"
