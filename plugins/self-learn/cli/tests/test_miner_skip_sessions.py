"""The miner never reads a session the user lists in ``miner.skip_sessions``.

The user, 2026-10-11: "add the ability to create a blacklist of session id's
for the miner. that feels like it should be trivial". The use in view: a test
bed copies a real transcript under a new session id and forks it several times
(``claude --resume <id> --fork-session --session-id <id>``). Each copy has a
new id, landing dedupes by ``transcript:<session id>#L<n>``, so without a list
every copy would be read from line 0 and land the same lessons again.

A listed session is skipped by the walk before its file is read, on the normal
cursor path and on the ``--since`` backfill alike (the backfill re-reads even a
halted file, so ``halt`` is not enough). Nothing is persisted for it: taking the
id off the list makes the file minable again from its cursor, or from line 0 if
it never had one.

Every session here is a plain typed session, never a scheduled job's or
self-learn's own, so the digest would mine it: when a listed session's text is
missing from the reader's prompt, the list is the only thing that kept it out.
Each test carries an unlisted sibling in the same project folder as the
positive control.
"""

from __future__ import annotations

import json

import pytest

from self_learn import miner, settings
from support import commit_all, make_home

LISTED_TAIL = "LISTED-SESSION-TAIL-marimba"
SIBLING_TAIL = "SIBLING-SESSION-TAIL-xylophone"
GROWN_TAIL = "GROWN-SESSION-TAIL-tubular-bells"

FOLDER = "-home-u-repos-proj"
LISTED_ID = "0b6f3c1e-forked-copy-1"
OTHER_LISTED_ID = "0b6f3c1e-forked-copy-2"
SIBLING_ID = "7d2a9e44-original"

TYPED_ROW = {"entrypoint": "cli", "promptSource": "typed", "origin": {"kind": "human"}}

ENV_VAR = "SELF_LEARN_MINER_SKIP_SESSIONS"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.delenv(ENV_VAR, raising=False)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


@pytest.fixture()
def transcripts(tmp_path, monkeypatch):
    root = tmp_path / "transcripts"
    (root / FOLDER).mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    miner._save_cursors({"__initialized__": "test-fixture"})
    return root


# ------------------------------------------------------- helpers


def user_row(text, **extra):
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}
    )


def assistant_row(text):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


def typed_lines(tail):
    return [user_row("please fix the failing test in the parser", **TYPED_ROW), assistant_row(tail)]


def write_session(root, name, lines):
    path = root / FOLDER / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def append(path, *lines):
    with open(path, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


def track_at_end(path):
    """A cursor entry on `path` as an earlier mine left it: read to the end."""
    cursors = miner._load_cursors()
    cursors[str(path)] = {"lines": len(path.read_text(encoding="utf-8").splitlines()), "size": path.stat().st_size}
    miner._save_cursors(cursors)


def shim_reader(monkeypatch):
    """Replace the model pass; return the list of prompts it was given."""
    prompts: list[str] = []

    def fake(h, prompt):
        prompts.append(prompt)
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps({"candidates": [], "fires": []}), encoding="utf-8")
        return out

    monkeypatch.setattr(miner, "_invoke_reader", fake)
    return prompts


def record_reads(monkeypatch):
    """Every path the walk opens for its lines."""
    read: list[str] = []
    real = miner._complete_lines

    def recording(path):
        read.append(str(path))
        return real(path)

    monkeypatch.setattr(miner, "_complete_lines", recording)
    return read


# ------------------------------------------------- positive control first


def test_with_no_list_both_sessions_are_read(home, transcripts, monkeypatch):
    """The fixture's sessions are minable: with nothing listed, the walk reads
    both and the reader sees both tails."""
    listed = write_session(transcripts, LISTED_ID, typed_lines(LISTED_TAIL))
    sibling = write_session(transcripts, SIBLING_ID, typed_lines(SIBLING_TAIL))
    read = record_reads(monkeypatch)

    assert {s.session_id for s in miner.walk()} == {LISTED_ID, SIBLING_ID}
    assert str(listed) in read and str(sibling) in read


# ------------------------------------------------- the list


def test_a_listed_session_is_not_read_and_lands_nothing(home, transcripts, monkeypatch):
    """Listed through config.yaml, the way `self-learn config set` writes it.
    The walk never opens the listed file, the reader never sees its text, and
    the run leaves no cursor entry for it (so no `halt` either)."""
    (home / "config.yaml").write_text(f"miner:\n  skip_sessions: '{LISTED_ID}'\n", encoding="utf-8")
    commit_all(home, "config: skip one session")
    listed = write_session(transcripts, LISTED_ID, typed_lines(LISTED_TAIL))
    sibling = write_session(transcripts, SIBLING_ID, typed_lines(SIBLING_TAIL))
    read = record_reads(monkeypatch)

    assert [s.session_id for s in miner.walk()] == [SIBLING_ID]
    assert str(sibling) in read  # positive control: the walk did read files
    assert str(listed) not in read

    prompts = shim_reader(monkeypatch)
    result = miner.run(home)

    assert result.status == "ok" and result.sessions_scanned == 1
    assert SIBLING_TAIL in prompts[0]
    assert LISTED_TAIL not in prompts[0]
    cursors = miner._load_cursors()
    assert str(sibling) in cursors
    assert str(listed) not in cursors


def test_an_unlisted_sibling_in_the_same_folder_is_read_as_before(home, transcripts, monkeypatch):
    """Only the listed id is skipped: a sibling in the same project folder,
    new or tracked and grown, is read from where its cursor says."""
    monkeypatch.setenv(ENV_VAR, LISTED_ID)
    write_session(transcripts, LISTED_ID, typed_lines(LISTED_TAIL))
    sibling = write_session(transcripts, SIBLING_ID, typed_lines(SIBLING_TAIL))
    grown = write_session(transcripts, "7d2a9e44-tracked", typed_lines("first-part"))
    track_at_end(grown)
    append(grown, user_row("one more thing", **TYPED_ROW), assistant_row(GROWN_TAIL))
    prompts = shim_reader(monkeypatch)

    assert miner.run(home).status == "ok"

    assert SIBLING_TAIL in prompts[0] and GROWN_TAIL in prompts[0]
    assert "first-part" not in prompts[0]  # the grown one is read from its cursor, as before
    assert LISTED_TAIL not in prompts[0]
    cursors = miner._load_cursors()
    assert not cursors[str(sibling)].get("halt") and not cursors[str(grown)].get("halt")


def test_a_listed_session_is_skipped_by_a_since_backfill(home, transcripts, monkeypatch):
    """`--since` re-reads files from line 0 whatever their cursor says, halted
    ones included. A listed file is skipped there too."""
    monkeypatch.setenv(ENV_VAR, LISTED_ID)
    listed = write_session(transcripts, LISTED_ID, typed_lines(LISTED_TAIL))
    sibling = write_session(transcripts, SIBLING_ID, typed_lines(SIBLING_TAIL))
    for path in (listed, sibling):
        track_at_end(path)
    read = record_reads(monkeypatch)

    assert [s.session_id for s in miner.walk(since="2000-01-01")] == [SIBLING_ID]
    assert str(listed) not in read

    prompts = shim_reader(monkeypatch)
    assert miner.run(home, since="2000-01-01").status == "ok"

    assert SIBLING_TAIL in prompts[0]  # positive control: the backfill re-read a tracked file
    assert LISTED_TAIL not in prompts[0]


def test_taking_an_id_off_the_list_makes_the_file_readable_again(home, transcripts, monkeypatch):
    """The list persists nothing. A listed file the miner never tracked is read
    from line 0 once the id is gone; a tracked one grown while listed is read
    from its cursor, and its cursor entry is left exactly as it was."""
    monkeypatch.setenv(ENV_VAR, f"{LISTED_ID},{OTHER_LISTED_ID}")
    never_tracked = write_session(transcripts, LISTED_ID, typed_lines(LISTED_TAIL))
    tracked = write_session(transcripts, OTHER_LISTED_ID, typed_lines("already-mined-part"))
    track_at_end(tracked)
    tracked_entry = dict(miner._load_cursors()[str(tracked)])
    append(tracked, user_row("one more thing", **TYPED_ROW), assistant_row(GROWN_TAIL))
    write_session(transcripts, SIBLING_ID, typed_lines(SIBLING_TAIL))
    prompts = shim_reader(monkeypatch)

    assert miner.run(home).status == "ok"
    assert SIBLING_TAIL in prompts[0]  # positive control
    assert LISTED_TAIL not in prompts[0] and GROWN_TAIL not in prompts[0]
    cursors = miner._load_cursors()
    assert str(never_tracked) not in cursors
    assert cursors[str(tracked)] == tracked_entry  # no halt, no advance

    monkeypatch.setenv(ENV_VAR, "")
    assert miner.run(home).status == "ok"

    assert len(prompts) == 2
    assert LISTED_TAIL in prompts[1]  # from line 0
    assert GROWN_TAIL in prompts[1]  # from its cursor ...
    assert "already-mined-part" not in prompts[1]  # ... not from line 0
    cursors = miner._load_cursors()
    assert not cursors[str(never_tracked)].get("halt") and not cursors[str(tracked)].get("halt")


# ------------------------------------------------- parsing


def test_the_list_is_comma_separated_and_empty_by_default(home, monkeypatch):
    assert settings.by_name("miner.skip_sessions").default == ""
    assert miner.skip_sessions(home) == frozenset()
    monkeypatch.setenv(ENV_VAR, f" {LISTED_ID},, {OTHER_LISTED_ID} ,")
    assert miner.skip_sessions(home) == frozenset({LISTED_ID, OTHER_LISTED_ID})
    monkeypatch.setenv(ENV_VAR, " , ,")
    assert miner.skip_sessions(home) == frozenset()


def test_config_yaml_wins_over_the_env_var(home, monkeypatch):
    """S-58: config.yaml > env > default, as for every miner setting."""
    monkeypatch.setenv(ENV_VAR, OTHER_LISTED_ID)
    assert miner.skip_sessions(home) == frozenset({OTHER_LISTED_ID})  # the env rung alone
    (home / "config.yaml").write_text(f"miner:\n  skip_sessions: ' {LISTED_ID} ,'\n", encoding="utf-8")
    commit_all(home, "config: skip one session")
    assert miner.skip_sessions(home) == frozenset({LISTED_ID})
