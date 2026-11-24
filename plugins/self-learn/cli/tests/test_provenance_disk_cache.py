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
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
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
    with p.saving():
        with pytest.raises(KeyboardInterrupt):
            p.sweep([root])
        # Still inside the block: a killed process never reaches its end.
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


def _forged_as_sent_nothing():
    """Rewrite the file to say every transcript sent nothing, under the right code hash."""
    path = p._disk_path()
    data = json.loads(path.read_text())
    for row in data["files"].values():
        row[2] = []
    path.write_text(json.dumps(data))
    return path.read_bytes()


@pytest.mark.parametrize("how", ["environment", "config"])
def test_with_the_setting_off_the_file_is_neither_read_nor_written(tmp_path, monkeypatch, how):
    """`provenance.disk_cache` is the rollback switch. The file is forged to
    say the transcript sent nothing. Positive control first: with the
    setting on, the forged file is believed (`user`). Off, by the
    environment or by config.yaml: the transcript is parsed and answers
    `agent`, the forged bytes stay as they were, and with no file none is
    made. Mutation: ignore the setting -> `user` -> red."""
    from self_learn import config
    from self_learn.ledger import resolve_home

    root = transcripts(tmp_path)
    assert role(root) == "agent"
    forged = _forged_as_sent_nothing()
    fresh_process()
    assert role(root) == "user", "control: on, the forged file answers"
    if how == "environment":
        monkeypatch.setenv("SELF_LEARN_PROVENANCE_DISK_CACHE", "0")
    else:
        home = resolve_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / config.CONFIG_BASENAME).write_text("provenance:\n  disk_cache: false\n", encoding="utf-8")
    fresh_process()
    assert role(root) == "agent"
    assert p._disk_path().read_bytes() == forged
    p._disk_path().unlink()
    fresh_process()
    assert role(root) == "agent" and not p._disk_path().exists()


def test_turning_the_setting_off_reaches_a_process_that_is_already_running(tmp_path, monkeypatch):
    """The host process that runs the nightly mine lives for days and has
    already taken entries from the file into memory. Off must stop those
    answering too, without a restart. One process throughout (no
    `fresh_process` after the forged file is loaded). Positive control: on,
    the forged entry answers `user`, from memory, twice. Mutation: flip only
    the file's use -> memory still answers `user` -> red."""
    root = transcripts(tmp_path)
    assert role(root) == "agent"
    forged = _forged_as_sent_nothing()
    fresh_process()
    assert role(root) == "user" and role(root) == "user", "control: the forged entry is in memory and answers"
    monkeypatch.setenv("SELF_LEARN_PROVENANCE_DISK_CACHE", "0")
    assert role(root) == "agent"
    assert p._disk_path().read_bytes() == forged, "off never touches the file, even a bad one"
    monkeypatch.delenv("SELF_LEARN_PROVENANCE_DISK_CACHE")
    assert role(root) == "agent", "back on in the same process: what it parsed while off is what it remembers"
    # The switch is not a repair: the file is as it was, and a NEW process
    # believes it again. Discarding a suspect file means deleting it.
    fresh_process()
    assert role(root) == "user"
    p.forget()
    assert role(root) == "agent"


def test_a_block_that_ends_after_the_setting_went_off_writes_nothing(tmp_path, monkeypatch):
    """The save at the end of `saving()` asks the setting as it is then."""
    root = transcripts(tmp_path)
    with p.saving():
        assert len(p.sweep([root])) == 1
        monkeypatch.setenv("SELF_LEARN_PROVENANCE_DISK_CACHE", "0")
    assert not p._disk_path().exists()
    monkeypatch.delenv("SELF_LEARN_PROVENANCE_DISK_CACHE")
    with p.saving():
        pass
    assert p._disk_path().is_file(), "control: the same unsaved entry is written once the setting is on"


def test_the_setting_has_plain_words_and_the_settings_surfaces_load():
    """A registry entry without a row in settings_plain makes that module
    refuse to import, which takes `config get`/`config set` and the whole web
    UI with it (the first draft of this setting did exactly that)."""
    from self_learn import settings, settings_plain
    from self_learn.ledger import resolve_home

    plain = settings_plain.plain_for("provenance.disk_cache")
    assert plain.group in settings_plain.GROUP_IDS and plain.label and plain.plain
    assert settings.setting_row(resolve_home(), settings.by_name("provenance.disk_cache"))


def test_the_setting_is_on_unless_set(tmp_path):
    from self_learn import settings

    setting = settings.by_name("provenance.disk_cache")
    assert setting.default is True and setting.kind == "bool" and setting.tier == "A"
    assert p._switch_on() is True


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
    assert path.stat().st_mtime <= at < path.stat().st_ctime, "control: old mtime, new ctime"
    fresh_process()
    assert sum(s.file_text for s in p.sweep([root])._sends) == 0


def test_a_brief_that_could_not_be_read_is_not_kept_in_the_file(tmp_path, monkeypatch):
    """A brief that passes every test and then fails to open (no file
    handles left, an I/O error) is a passing fault, not a fact about the
    file: its fingerprint is unchanged, so an entry saved now would say in
    every later process that the brief was never sent, and an agent's brief
    would read as the person's words for good. Positive control: with the
    fault the answer is `user` in this process. Then a new process, the fault
    gone, must read the brief. Mutation: save the entry anyway -> `user`
    again -> red."""
    path = brief_file(tmp_path)
    root = transcripts(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    real_open = os.open

    def no_handles(target, *args, **kwargs):
        if str(target) == str(path):
            raise OSError(24, "Too many open files")
        return real_open(target, *args, **kwargs)

    monkeypatch.setattr(os, "open", no_handles)
    assert role(root) == "user", "control: the fault hides the brief in this process"
    monkeypatch.setattr(os, "open", real_open)
    fresh_process()
    assert role(root) == "agent"
    fresh_process()
    no_parsing(monkeypatch)
    assert role(root) == "agent", "and the good read is kept"


def test_a_good_entry_is_withdrawn_when_a_later_read_of_its_brief_fails(tmp_path, monkeypatch):
    """The file already holds a good entry; the brief's fingerprint then
    changes (so the entry is stale) and the re-read fails. The stale entry
    must leave the file with it, never be left looking current."""
    path = brief_file(tmp_path)
    root = transcripts(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"
    assert len(json.loads(p._disk_path().read_text())["files"]) == 1
    path.write_text(BRIEF)  # same text, new mtime and ctime: after the send, so no longer evidence
    os.utime(path, (p._epoch(typed("", 1)["timestamp"]), p._epoch(typed("", 1)["timestamp"])))
    real_open = os.open

    def no_handles(target, *args, **kwargs):
        if str(target) == str(path):
            raise OSError(24, "Too many open files")
        return real_open(target, *args, **kwargs)

    monkeypatch.setattr(os, "open", no_handles)
    fresh_process()
    role(root)
    assert json.loads(p._disk_path().read_text())["files"] == {}


def test_the_temporary_file_of_a_killed_save_is_removed_by_a_later_one(tmp_path):
    """The inbox page stops a packet with SIGKILL, which can land during a
    save and leave a temporary file as large as the cache. A later save
    removes one that is old, and leaves a fresh one (another process may be
    writing it right now)."""
    root = transcripts(tmp_path)
    assert role(root) == "agent"
    folder = p._disk_path().parent
    old, new = folder / ".sends-killed.tmp", folder / ".sends-inflight.tmp"
    for leftover in (old, new):
        leftover.write_text("{")
    os.utime(old, (1_700_000_000, 1_700_000_000))
    write(root, "0f0e0d0c-0000-4000-8000-00000000abcd", [bash('herdr agent prompt worker "one more"', 8)])
    fresh_process()
    assert role(root) == "agent"
    assert len(json.loads(p._disk_path().read_text())["files"]) == 2, "control: that sweep saved"
    assert not old.exists() and new.exists()


def test_a_packets_many_sweeps_write_the_file_once(tmp_path, monkeypatch):
    """A packet sweeps once for every turn it quotes, and a transcript still
    being written is parsed again each time. Inside one `saving()` block
    those sweeps save together when the block ends, not one rewrite of the
    whole file each. Positive control: the file does hold the last state."""
    root = tmp_path / "transcripts"
    saves, real = [], p.os.replace
    monkeypatch.setattr(p.os, "replace", lambda a, b: (saves.append(str(b)), real(a, b))[1])
    with p.saving():
        for n in range(4):
            write(root, ORCH, [bash(f'herdr agent prompt worker "instruction number {i} for the worker"', 8)
                               for i in range(n + 1)])
            assert len(p.sweep([root])) == n + 1
    assert saves == [str(p._disk_path())]
    assert len(next(iter(json.loads(p._disk_path().read_text())["files"].values()))[2]) == 4


def test_a_stat_that_fails_just_after_a_good_read_is_not_kept(tmp_path, monkeypatch):
    """The second way a passing fault could have reached the file: the brief
    is read, then cannot be examined. Positive control: `user` while the
    fault lasts; a new process without it reads the brief."""
    path = brief_file(tmp_path)
    root = transcripts(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    real, calls = p._fingerprint, []

    def failing_after_read(target):
        if target == path:
            calls.append(target)
            if len(calls) == 2:  # the first is before the read, the second just after it
                return None
        return real(target)

    monkeypatch.setattr(p, "_fingerprint", failing_after_read)
    assert role(root) == "user" and len(calls) >= 2, "control: the fault hid the brief"
    monkeypatch.setattr(p, "_fingerprint", real)
    fresh_process()
    assert role(root) == "agent"


def test_every_change_to_the_entries_holds_the_lock(tmp_path, monkeypatch):
    """`ask` runs its tools in threads and two of them sweep; a save walks
    the entries another sweep adds to. The save swallows the RuntimeError
    that would raise, so a threaded test cannot tell a held lock from luck.
    This one is exact: the entries are a dict that refuses to be changed or
    walked unless this thread holds `_DISK_LOCK`. Mutation: drop the lock
    around the insert or the save -> AssertionError -> red."""
    class Guarded(dict):
        def _held(self):
            assert p._DISK_LOCK._is_owned(), "the entries were touched without the lock"

        def __setitem__(self, key, value):
            self._held()
            super().__setitem__(key, value)

        def __delitem__(self, key):
            self._held()
            super().__delitem__(key)

        def pop(self, *args):
            self._held()
            return super().pop(*args)

        def items(self):
            self._held()
            return super().items()

        def __iter__(self):
            self._held()
            return super().__iter__()

    monkeypatch.setattr(p, "_disk_read", lambda path: Guarded())
    path = brief_file(tmp_path)
    root = transcripts(tmp_path, f'herdr agent prompt worker "$(cat \'{path}\')"')
    assert role(root) == "agent"                      # insert, then save
    assert isinstance(p._DISK.entries, Guarded) and len(p._DISK.entries) == 1, "control: the guarded dict is in use"
    for old in root.rglob("*.jsonl"):
        old.unlink()
    write(root, "0f0e0d0c-0000-4000-8000-00000000abcd", [bash('herdr agent prompt worker "one more"', 8)])
    assert len(json.loads(p._disk_path().read_text())["files"]) == 1
    with p.saving():
        p.sweep([root])                               # insert, then prune and save
    assert list(json.loads(p._disk_path().read_text())["files"]) == [str(next(root.rglob("*.jsonl")))]
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda target, *a, **k: (_ for _ in ()).throw(OSError(24, "no handles"))
                        if str(target) == str(path) else real_open(target, *a, **k))
    for old in root.rglob("*.jsonl"):
        old.unlink()
    write(root, ORCH, [bash(f'herdr agent prompt worker "$(cat \'{path}\')"', 9)])
    p._CACHE.clear()
    assert role(root) == "user"                       # pop of the unread entry, under the lock


def test_two_threads_sweeping_at_once_save_without_error(tmp_path, monkeypatch):
    """`ask` runs its tools in threads, and two of them sweep. A save walks
    the entries another thread's sweep adds to; unguarded, that raises
    RuntimeError out of `sweep`. Each thread parses its own store's 40
    transcripts with the save interval at zero, so saves and inserts
    interleave throughout."""
    import threading

    monkeypatch.setattr(p, "_DISK_SAVE_EVERY_SECS", 0.0)
    roots = []
    for n in range(2):
        root = tmp_path / f"store-{n}"
        for i in range(40):
            write(root, f"0f0e0d0c-0000-4000-8000-{n:04d}{i:08d}", [bash(f'herdr agent prompt worker "task {n} {i} for the worker"', 8)])
        roots.append(root)
    errors, counts = [], []

    def work(root):
        try:
            with p.saving():
                counts.append(len(p.sweep([root])))
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever escaped
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(root,)) for root in roots]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == [] and counts == [40, 40]
    assert len(json.loads(p._disk_path().read_text())["files"]) == 80


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


@pytest.mark.parametrize("command", [
    f'hc\tsend worker "{BRIEF}"',
    f'cd /work\nhc\t--json\tsend worker "{BRIEF}"',
])
def test_a_tab_after_hc_is_still_a_send(tmp_path, command):
    """A transcript stores the command JSON-escaped, so a tab after `hc` is
    the two bytes backslash and t, which no `\\s` in a bytes pattern matches:
    the line was dropped before it was read, and the decoded command, which
    is a send, never looked at. Positive control: the stored line holds the
    escaped form."""
    root = transcripts(tmp_path, command)
    stored = next(root.rglob("*.jsonl")).read_text()
    assert "hc\\t" in stored and "herdr" not in stored
    assert role(root) == "agent"


def test_the_gate_is_not_the_pattern():
    """The gate only narrows what the pattern is run on: a line it lets
    through can still be no call at all."""
    raw = b'the word hc "quoted" and then nothing'
    assert p._HC_CALL_GATE.search(raw) is not None
    assert p._HC_CALL_BYTES.search(raw) is None


def test_an_hc_send_is_still_found_through_the_gate(tmp_path):
    root = transcripts(tmp_path, f'hc send worker "{BRIEF}"')
    assert role(root) == "agent"
