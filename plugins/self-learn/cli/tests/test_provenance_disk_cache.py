"""The sweep's on-disk cache and its line gate (02 §3a.6, S-163).

A sweep reads every transcript of every harness, and the in-memory cache
dies with the process, so `attention packet` paid a full sweep each time
and the inbox page never got one inside its 15 s. These tests play a second
process by clearing the in-memory state (`fresh_process`) and prove what the
file may and may not do: save the parse, never change the answer.
"""
import json
import os
import stat

import pytest

from self_learn import provenance as p, refs
from test_provenance import BRIEF, ORCH, write
from test_provenance_senders import bash, brief_file, typed


def fresh_process():
    """What a new CLI process starts with: no in-memory entries, the file unread."""
    p._CACHE.clear()
    p._DISK.path, p._DISK.entries, p._DISK.dirty = None, {}, False


@pytest.fixture(autouse=True)
def _own_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    fresh_process()
    yield
    fresh_process()


def transcripts(tmp_path, command=f'herdr agent prompt worker "{BRIEF}"'):
    root = tmp_path / "transcripts"
    write(root, ORCH, [bash(command, 8)])
    return root


def role(root, text=BRIEF):
    """As a caller that keeps the file does: the sweep runs inside `saving()`."""
    with p.saving():
        return refs.role_of(typed(text, 10), sent=p.sweep([root]))


def no_parsing(monkeypatch):
    """Any parse of a transcript row from here on fails the test."""
    def boom(*_a, **_k):
        raise AssertionError("a transcript row was parsed again")
    monkeypatch.setattr(p, "_claude_sends", boom)


def test_a_second_process_answers_from_the_file_without_parsing(tmp_path, monkeypatch):
    """Positive control first: the first sweep finds the send and writes the
    file. Then a new process gets the same answer with row parsing forbidden.
    Mutation: never read the file -> the row is parsed -> red."""
    root = transcripts(tmp_path)
    assert role(root) == "agent"
    assert p._disk_path().is_file()
    fresh_process()
    no_parsing(monkeypatch)
    assert role(root) == "agent"


def test_the_file_is_private_and_holds_the_parsing_codes_hash(tmp_path):
    root = transcripts(tmp_path)
    assert role(root) == "agent"
    path = p._disk_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.is_relative_to(tmp_path / "xdg-cache"), "the file follows XDG_CACHE_HOME"
    data = json.loads(path.read_text())
    assert data["version"] == p._DISK_VERSION and data["code"] == p._code_hash() and len(data["code"]) == 64
    assert [name for name in os.listdir(path.parent)] == ["sends.json"], "no temporary file is left behind"


def test_a_changed_transcript_is_read_again(tmp_path):
    """The file's entry is trusted only for the same mtime and size. The
    transcript gains a second send; a new process must see it. Mutation:
    trust the entry by path alone -> the second text reads `user` -> red."""
    root = transcripts(tmp_path)
    other = "A second, different instruction sent to the worker after the first one."
    assert role(root) == "agent" and role(root, other) == "user"
    write(root, ORCH, [bash(f'herdr agent prompt worker "{BRIEF}"', 8),
                       bash(f'herdr agent prompt worker "{other}"', 9)])
    fresh_process()
    assert role(root, other) == "agent"


def test_a_changed_brief_file_is_read_again_by_a_new_process(tmp_path):
    """A send that names a file depends on that file; the entry carries its
    fingerprint across processes. Positive control: the file's text is the
    agent's. Then the file is rewritten after the send, which makes it too
    new to have been what was sent. Mutation: store no dependencies -> the
    stale text still reads `agent` -> red."""
    path = brief_file(tmp_path)
    root = transcripts(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"
    fresh_process()
    assert role(root) == "agent"
    os.utime(path, (p._epoch(typed("", 9)["timestamp"]), p._epoch(typed("", 9)["timestamp"])))
    fresh_process()
    assert role(root) == "user"


def test_a_file_from_other_code_is_ignored(tmp_path):
    """An entry is only as good as the code that parsed it. The file is
    rewritten to say every send was something else, under a different code
    hash; the answer must come from the transcript. Mutation: skip the hash
    check -> the forged entry answers -> red."""
    root = transcripts(tmp_path)
    assert role(root) == "agent"
    path = p._disk_path()
    data = json.loads(path.read_text())
    for row in data["files"].values():
        row[2] = []  # forged: this transcript sent nothing
    path.write_text(json.dumps(data))
    fresh_process()
    assert role(root) == "user", "control: with the right hash the forged file would be believed"
    data["code"] = "0" * 64
    path.write_text(json.dumps(data))
    fresh_process()
    assert role(root) == "agent"


@pytest.mark.parametrize("damage", [
    lambda data: "not json at all",
    lambda data: json.dumps([1, 2, 3]),
    lambda data: json.dumps({**data, "version": 0}),
    lambda data: json.dumps({**data, "files": []}),
    lambda data: json.dumps({**data, "files": {k: v[:3] for k, v in data["files"].items()}}),
    lambda data: json.dumps({**data, "files": {k: [str(v[0]), *v[1:]] for k, v in data["files"].items()}}),
    lambda data: json.dumps({**data, "files": {k: [v[0], v[1], [{"at": 1.0}], v[3]] for k, v in data["files"].items()}}),
    lambda data: json.dumps({**data, "files": {k: [v[0], v[1], [{**v[2][0], "raw": 7}], v[3]]
                                               for k, v in data["files"].items()}}),
    lambda data: json.dumps({**data, "files": {k: [v[0], v[1], [{**v[2][0], "at": True}], v[3]]
                                               for k, v in data["files"].items()}}),
    lambda data: json.dumps({**data, "files": {k: [v[0], v[1], v[2], {"/x": [1, 2]}] for k, v in data["files"].items()}}),
])
def test_a_malformed_file_changes_nothing(tmp_path, damage):
    """Whatever is wrong with the file, the sweep answers from the transcript
    and then replaces the file with a good one."""
    root = transcripts(tmp_path)
    assert role(root) == "agent"
    path = p._disk_path()
    good = json.loads(path.read_text())
    assert good["files"] and all(row[2] for row in good["files"].values()), "control: the entry holds the send"
    path.write_text(damage(good))
    fresh_process()
    assert role(root) == "agent"
    assert json.loads(path.read_text()) == good


def test_a_cache_that_cannot_be_written_changes_nothing(tmp_path, monkeypatch):
    """`XDG_CACHE_HOME` names a place no directory can be made in (a regular
    file is in the way): the sweep still answers, and raises nothing."""
    blocker = tmp_path / "blocker"
    blocker.write_text("in the way")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
    fresh_process()
    root = transcripts(tmp_path)
    assert role(root) == "agent"
    assert blocker.read_text() == "in the way"


def test_a_removed_transcript_leaves_the_file_at_the_next_save(tmp_path):
    root = transcripts(tmp_path)
    assert role(root) == "agent"
    first = set(json.loads(p._disk_path().read_text())["files"])
    assert len(first) == 1
    for old in root.rglob("*.jsonl"):
        old.unlink()
    write(root, "0f0e0d0c-0000-4000-8000-00000000abcd", [bash(f'herdr agent prompt worker "{BRIEF}"', 8)])
    fresh_process()
    assert role(root) == "agent"
    second = set(json.loads(p._disk_path().read_text())["files"])
    assert len(second) == 1 and second != first


def test_a_long_sweep_saves_before_it_ends(tmp_path, monkeypatch):
    """The inbox page stops a packet after 15 s, so a first sweep that only
    saved at its end would never leave a file and every later one would
    start from nothing. With the interval at zero, each parsed transcript is
    saved as it is done: a sweep stopped after the first of two files has
    already written that one. Mutation: save only at the end -> no file ->
    red."""
    root = tmp_path / "transcripts"
    write(root, ORCH, [bash(f'herdr agent prompt worker "{BRIEF}"', 8)])
    write(root, "0f0e0d0c-0000-4000-8000-00000000abcd", [bash('herdr agent prompt worker "something else entirely"', 8)])
    monkeypatch.setattr(p, "_DISK_SAVE_EVERY_SECS", 0.0)
    real, seen = p._file_sends, []

    def stop_after_one(path):
        if seen:
            raise KeyboardInterrupt  # the page gave up and killed the process
        seen.append(path)
        return real(path)

    monkeypatch.setattr(p, "_file_sends", stop_after_one)
    with pytest.raises(KeyboardInterrupt), p.saving():
        p.sweep([root])
    assert list(json.loads(p._disk_path().read_text())["files"]) == [str(seen[0])]


def test_a_sweep_outside_saving_reads_the_file_and_never_writes_it(tmp_path, monkeypatch):
    """A verb that promises to change nothing still sweeps. Outside
    `saving()`: with no file, none appears; with one, it answers (row
    parsing forbidden) and its bytes stay as they were, even when the sweep
    has something new it could have added. Mutation: save in every sweep ->
    the file appears -> red."""
    root = transcripts(tmp_path)
    assert refs.role_of(typed(BRIEF, 10), sent=p.sweep([root])) == "agent"
    assert not p._disk_path().exists()
    fresh_process()
    assert role(root) == "agent"  # inside saving(): the file is written
    before = p._disk_path().read_bytes()
    write(root, "0f0e0d0c-0000-4000-8000-00000000abcd", [bash('herdr agent prompt worker "one more"', 8)])
    fresh_process()
    assert len(p.sweep([root])) == 2, "control: the unsaving sweep did read the new transcript"
    assert p._disk_path().read_bytes() == before
    fresh_process()
    (root / "-work-repo" / "0f0e0d0c-0000-4000-8000-00000000abcd.jsonl").unlink()
    no_parsing(monkeypatch)
    assert refs.role_of(typed(BRIEF, 10), sent=p.sweep([root])) == "agent"


def test_what_an_unsaving_sweep_parsed_is_written_by_the_next_saving_one(tmp_path):
    """One long-lived process: a sweep outside `saving()` parses a
    transcript, then a sweep inside it finds nothing new to parse. The file
    must still get the entry, or it would stay cold for every other
    process. Mutation: forget unsaved work -> no file -> red."""
    root = transcripts(tmp_path)
    assert len(p.sweep([root])) == 1 and not p._disk_path().exists()
    with p.saving():
        assert len(p.sweep([root])) == 1
    assert len(json.loads(p._disk_path().read_text())["files"]) == 1


def test_forget_drops_the_memory_and_the_file(tmp_path, monkeypatch):
    """`forget` is how a test (or a person) asks for a parse from nothing.
    Positive control: the row parser is reached again after it. Mutation:
    clear only the memory -> the file answers -> the parser is not reached
    -> red."""
    root = transcripts(tmp_path)
    assert role(root) == "agent"
    assert p._disk_path().is_file()
    p.forget()
    assert not p._disk_path().exists()
    real, parsed = p._claude_sends, []
    monkeypatch.setattr(p, "_claude_sends", lambda raw, session: parsed.append(session) or real(raw, session))
    assert role(root) == "agent"
    assert parsed, "the transcript was parsed again"


def test_the_cold_process_guard_holds_through_the_file(tmp_path):
    """test_provenance_hardening's ctime guard, for a process that starts with
    the file but no memory: a brief replaced after the send (old mtime, new
    ctime and inode) must not count as what was sent, even though the entry
    written before the replacement says it did."""
    import time
    from datetime import datetime, timezone

    path, replacement = tmp_path / "brief", tmp_path / "older-draft"
    for target in (path, replacement):
        target.write_text(BRIEF)
        os.utime(target, (1, 1))
    at = time.time()
    row = bash(f'herdr agent prompt worker "$(cat {path})"', 8)
    row["timestamp"] = datetime.fromtimestamp(at, timezone.utc).isoformat()
    root = tmp_path / "transcripts"
    write(root, ORCH, [row])
    with p.saving():
        assert sum(s.file_text for s in p.sweep([root])._sends) == 1
    kept = json.loads(p._disk_path().read_text())["files"]
    assert any(s["file_text"] for row in kept.values() for s in row[2]), "control: the entry on disk holds the file's text"
    time.sleep(0.002)
    os.replace(replacement, path)
    fresh_process()
    assert sum(s.file_text for s in p.sweep([root])._sends) == 0


# ------------------------------------------------------------ the line gate

@pytest.mark.parametrize("line", [
    f'hc send worker "{BRIEF}"',
    'hc --json send worker "x"',
    "hc run --name w -- claude 'go'",
    'cd /work\\nhc send worker "x"',
    'true\\thc\trun x y',
    '{"command": ["hc", "send", "worker", "x"]}',
    '{"command": ["/opt/bin/hc", "--json", "run", "x", "y"]}',
    '{"arguments": "{\\"command\\": [\\"hc\\", \\"send\\", \\"worker\\", \\"x\\"]}"}',
    '{"arguments": "{\\"command\\": [\\"/usr/bin/hc\\" , \\"run\\"]}"}',
    "hc\nsend worker x",
])
def test_every_line_the_hc_pattern_keeps_passes_the_gate(line):
    """The gate runs before the pattern, so a line it drops is never seen.
    Positive control first: the pattern itself keeps the line."""
    raw = line.encode()
    assert p._HC_CALL_BYTES.search(raw) is not None, "control: the full pattern matches this line"
    assert p._HC_CALL_GATE.search(raw) is not None


def test_the_gate_is_not_the_pattern():
    """The gate only narrows what the pattern is run on: a line it lets
    through can still be no call at all."""
    raw = b'the word hc "quoted" and then nothing'
    assert p._HC_CALL_GATE.search(raw) is not None
    assert p._HC_CALL_BYTES.search(raw) is None


def test_an_hc_send_is_still_found_through_the_gate(tmp_path):
    root = transcripts(tmp_path, f'hc send worker "{BRIEF}"')
    assert role(root) == "agent"
