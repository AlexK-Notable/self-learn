"""Synthetic sender formats and conservative file-backed provenance (02 §3a.6)."""
import json
import os
import sqlite3
from pathlib import Path

import pytest

from self_learn import provenance as p, refs
from test_provenance import BRIEF, ORCH, bash, typed, write, _ts


def brief_file(tmp_path, text=BRIEF):
    path = tmp_path / "brief with spaces.md"
    path.write_text(text)
    os.utime(path, (p._epoch(_ts(1)), p._epoch(_ts(1))))
    return path


def send_file(tmp_path, command, cwd=None):
    root = tmp_path / "transcripts"
    row = bash(command, 8)
    if cwd is not None:
        row["cwd"] = str(cwd)
    write(root, ORCH, [row])
    return root


def role(root, text=BRIEF):
    return refs.role_of(typed(text, 10), sent=p.sweep([root]))


@pytest.mark.parametrize("form", ['"$(cat \'{path}\')"', '"$(< \'{path}\')"', '"$(cat -- \'{path}\')"'])
@pytest.mark.parametrize("verb", ["agent prompt", "pane send-text"])
def test_file_argument_is_sent(tmp_path, form, verb):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, f"herdr {verb} worker " + form.format(path=path))
    assert refs.role_of(typed(BRIEF, 10)) == "user"
    assert role(root) == "agent"
    # File sends must equal the entire argument, not merely contain the turn.
    assert role(root, BRIEF[:45]) == "user"


def test_short_file_argument_is_whole_text(tmp_path):
    path = brief_file(tmp_path, "yes\n")
    root = send_file(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root, "yes") == "agent"
    assert role(root, "ye") == "user"


def test_file_cache_tracks_change_removal_and_creation(tmp_path):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"
    os.utime(path, (p._epoch(_ts(9)), p._epoch(_ts(9))))
    assert role(root) == "user"  # same transcript, file newer than send
    os.utime(path, (p._epoch(_ts(1)), p._epoch(_ts(1))))
    assert role(root) == "agent"
    path.unlink()
    assert role(root) == "user"
    brief_file(tmp_path)
    assert role(root) == "agent"  # negative dependency invalidates too
    old = path.stat()
    path.write_text("X" * len(BRIEF))  # same size and mtime; ctime changes
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert len(BRIEF) == path.stat().st_size
    assert role(root) == "user"


@pytest.mark.parametrize("prefix,cwd_ok", [("", True), ("cd /elsewhere && ", False)])
def test_relative_file_requires_recorded_unchanged_cwd(tmp_path, prefix, cwd_ok):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"
    command = prefix + f'herdr agent prompt worker "$(cat \'{path.name}\')"'
    send_file(tmp_path, command, tmp_path)
    assert role(root) == ("agent" if cwd_ok else "user")
    send_file(tmp_path, command)
    assert role(root) == "user"


@pytest.mark.parametrize("command", [
    "echo herdr agent prompt worker {arg}",
    "cat {arg}; herdr pane read worker",  # file mentioned elsewhere
    "herdr agent prompt {arg} hello",  # pane argument, not text
    "echo 'herdr agent prompt worker {arg}'",
    "herdr agent prompt worker '{arg}'",  # literal single-quoted substitution
    "herdr agent prompt worker \"prefix {arg}\"",
    "cat '{path}' | herdr agent prompt worker",  # herdr requires a TEXT argument
    "herdr agent prompt worker < '{path}'",
    "herdr agent prompt worker \"$(cat $BRIEF)\"",
    "herdr agent prompt worker \"$(cat '{path}' another.md)\"",
    "cat <<EOF\nherdr agent prompt worker {arg}\nEOF",
])
def test_non_text_or_ambiguous_shell_form_does_not_read_file(tmp_path, command):
    path = brief_file(tmp_path)
    arg = f'"$(cat {path.parent}/brief.md)"'
    plain = path.parent / "brief.md"
    path.rename(plain)
    root = send_file(tmp_path, f"herdr agent prompt worker {arg}")
    assert role(root) == "agent"
    send_file(tmp_path, command.format(arg=arg, path=plain))
    assert role(root) == "user"


def harness(tmp_path, name, command, cwd, *, valid=True):
    home = tmp_path / "home"
    if name == "pi":
        root = home / ".pi" / "agent" / "sessions"
        root.mkdir(parents=True, exist_ok=True)
        rows = [{"type": "session", "cwd": str(cwd)},
                {"type": "message", "timestamp": _ts(8), "message": {
                    "role": "assistant" if valid else "user", "content": [
                        {"type": "toolCall", "name": "bash", "arguments": {"command": command}}]}}]
        (root / "example.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    elif name == "agy":
        root = home / ".gemini" / "antigravity-cli" / "brain"
        log = root / "example" / ".system_generated" / "logs"
        log.mkdir(parents=True, exist_ok=True)
        row = {"type": "PLANNER_RESPONSE" if valid else "USER_INPUT", "created_at": _ts(8),
               "tool_calls": [{"name": "run_command", "args": {"CommandLine": command, "Cwd": str(cwd)}}]}
        (log / "transcript_full.jsonl").write_text(json.dumps(row) + "\n")
    elif name == "hermes":
        root = home / ".hermes"
        root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(root / "state.db") as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions(id TEXT, cwd TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS messages(session_id TEXT, timestamp REAL, role TEXT, tool_calls TEXT)")
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM messages")
            db.execute("INSERT INTO sessions VALUES (?, ?)", ("example", str(cwd)))
            calls = [{"function": {"name": "terminal", "arguments": json.dumps({"command": command})}}]
            db.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", ("example", p._epoch(_ts(8)),
                       "assistant" if valid else "user", json.dumps(calls)))
    else:
        root = home / ".codex" / "sessions"
        root.mkdir(parents=True, exist_ok=True)
        rows = [{"type": "turn_context", "payload": {"cwd": str(cwd)}},
                {"type": "response_item", "timestamp": _ts(8), "payload": {
                    "type": "function_call" if valid else "function_call_output",
                    "arguments": json.dumps({"cmd": command})}}]
        (root / "rollout-example.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return root


@pytest.mark.parametrize("name", ["pi", "agy", "hermes", "codex"])
def test_new_sender_inline_file_cwd_and_nonassistant(tmp_path, name):
    path = brief_file(tmp_path)
    inline = f"herdr agent prompt worker '{BRIEF}'"
    root = harness(tmp_path, name, inline, tmp_path)
    assert role(root) == "agent"
    root = harness(tmp_path, name, f'herdr agent prompt worker "$(cat \'{path.name}\')"', tmp_path)
    assert role(root) == "agent"
    harness(tmp_path, name, inline, tmp_path, valid=False)
    assert role(root) == "user"


def test_hermes_reads_wal_and_never_creates_missing_database(tmp_path):
    root = harness(tmp_path, "hermes", f"herdr agent prompt worker '{BRIEF}'", tmp_path)
    assert role(root) == "agent"
    db = sqlite3.connect(root / "state.db")
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        assert role(root) == "agent"
        db.execute("DELETE FROM messages")
        db.commit()
        assert role(root) == "user"
    finally:
        db.close()
    (root / "state.db").unlink()
    assert role(root) == "user"
    assert not (root / "state.db").exists()


def test_regular_bounded_utf8_file_only(tmp_path):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"
    for data in [BRIEF.encode() + b'\xff', BRIEF.encode() + b' ' * (1024 * 1024 + 1), b'']:
        path.write_bytes(data)
        os.utime(path, (p._epoch(_ts(1)), p._epoch(_ts(1))))
        assert role(root) == "user"
    path.unlink()
    os.mkfifo(path)
    assert role(root) == "user"


def test_file_changed_during_read_is_rejected(tmp_path, monkeypatch):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"
    p._CACHE.clear()
    original = p._fingerprint
    calls = 0

    def changing(target):
        nonlocal calls
        fp = original(target)
        if target == path:
            calls += 1
            if calls == 2:
                return None
        return fp

    monkeypatch.setattr(p, "_fingerprint", changing)
    assert role(root) == "user"
    assert calls == 2


@pytest.mark.parametrize("name", ["pi", "agy"])
def test_json_sender_requires_command_tool_and_timestamp(tmp_path, name):
    root = harness(tmp_path, name, f"herdr agent prompt worker '{BRIEF}'", tmp_path)
    assert role(root) == "agent"
    path = next(root.rglob("*.jsonl"))
    original = path.read_text()
    for old, new in [(_ts(8), "not-a-date"),
                     ('"bash"' if name == "pi" else '"run_command"', '"read_file"'),
                     ('"herdr agent prompt', '"echo agent prompt')]:
        assert old in original
        path.write_text(original.replace(old, new))
        assert role(root) == "user"


def test_hermes_requires_command_tool_and_timestamp(tmp_path):
    root = harness(tmp_path, "hermes", f"herdr agent prompt worker '{BRIEF}'", tmp_path)
    assert role(root) == "agent"
    with sqlite3.connect(root / "state.db") as db:
        original = db.execute("SELECT tool_calls FROM messages").fetchone()[0]
        db.execute("UPDATE messages SET tool_calls=?", (original.replace('terminal', 'read_file'),))
    assert role(root) == "user"
    with sqlite3.connect(root / "state.db") as db:
        db.execute("UPDATE messages SET tool_calls=?, timestamp=?", (original, "bad"))
    assert role(root) == "user"
    with sqlite3.connect(root / "state.db") as db:
        db.execute("UPDATE messages SET timestamp=?, tool_calls=?", (p._epoch(_ts(8)), "not JSON herdr"))
    assert role(root) == "user"


def test_file_stat_cache_avoids_reopening_unchanged_transcript(tmp_path, monkeypatch):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"
    original = Path.open

    def forbidden(target, *args, **kwargs):
        if target.suffix == ".jsonl":
            pytest.fail("unchanged transcript reopened")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbidden)
    assert role(root) == "agent"
