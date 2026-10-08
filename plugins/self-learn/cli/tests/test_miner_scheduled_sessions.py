"""The old miner skips scheduled jobs' sessions and keeps background jobs'.

The user, 2026-10-07, asked whether the miner should also skip sessions a
program ran rather than ones they typed: "scheduled jobs maybe not unless i
explicitly ask for coverage. background jobs yes."

Measured on the live machine the same day (494 transcripts): a Claude Desktop
scheduled task opens its session's first user turn with
``<scheduled-task name="<task>" file="…/scheduled-tasks/<task>/SKILL.md">`` (38
of 38 such sessions, and no session of any other kind does). A Claude Code
background session carries ``sessionKind: "bg"`` on its rows and opens with
whatever it was asked. So the miner halts a session whose first user turn
opens with that tag, the way it halts self-learn's own (M-5), unless the
user names the job in ``miner.mined_scheduled_jobs``.

The synthetic rows below carry the fields Claude Code writes on each kind
(entrypoint, promptSource, sessionKind, origin), so a rule that keyed on them
instead of on the opening would be caught by the two positive controls at
the top: a background job's session and a typed session are both mined.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import miner, settings
from support import commit_all, make_home

SCHEDULED_TAIL = "SCHEDULED-SESSION-TAIL-glockenspiel"
BACKGROUND_TAIL = "BACKGROUND-SESSION-TAIL-celesta"
TYPED_TAIL = "TYPED-SESSION-TAIL-vibraphone"

#: Project folders shaped like the real ones.
SCHEDULED_FOLDER = "-home-u-notes-news"
WORK_FOLDER = "-home-u-repos-proj"

#: What Claude Code writes on the first user row of each kind (measured).
SCHEDULED_ROW = {"entrypoint": "claude-desktop", "promptSource": "sdk"}
BACKGROUND_ROW = {"entrypoint": "cli", "promptSource": "queued", "sessionKind": "bg", "origin": {"kind": "human"}}
TYPED_ROW = {"entrypoint": "cli", "promptSource": "typed", "origin": {"kind": "human"}}

ENV_VAR = "SELF_LEARN_MINER_MINED_SCHEDULED_JOBS"


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
    for folder in (SCHEDULED_FOLDER, WORK_FOLDER):
        (root / folder).mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    miner._save_cursors({"__initialized__": "test-fixture"})
    return root


# ------------------------------------------------------- row builders


def user_row(text, **extra):
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}
    )


def assistant_row(text):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


def write_session(root, folder, name, lines):
    path = root / folder / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def append(path, *lines):
    with open(path, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


def slice_of(path, start=0):
    lines = path.read_text(encoding="utf-8").splitlines()
    return miner.SessionSlice(
        path=path, session_id=path.stem, project=path.parent.name, start_line=start, lines=lines[start:]
    )


def track_at_end(path):
    """A cursor entry on `path` as an earlier mine left it: read to the end,
    `halt` unset (the live machine's 38 scheduled-task sessions, 2026-10-07)."""
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


def scheduled_prompt(name):
    """The opening Claude Desktop's scheduler writes (measured), then the task."""
    return (
        f'<scheduled-task name="{name}" file="/home/u/.claude/scheduled-tasks/{name}/SKILL.md">\n'
        "Collect today's announcements and write the digest into the notes folder.\n"
        "</scheduled-task>"
    )


def scheduled_lines(name, tail=SCHEDULED_TAIL):
    return [user_row(scheduled_prompt(name), **SCHEDULED_ROW), assistant_row(f"{tail} {name}")]


def background_lines(tail=BACKGROUND_TAIL):
    return [
        user_row("Rebuild the parser fixtures and report which ones changed.", **BACKGROUND_ROW),
        assistant_row(tail),
    ]


def typed_lines(tail=TYPED_TAIL):
    return [user_row("please fix the failing test in the parser", **TYPED_ROW), assistant_row(tail)]


def log_text():
    return (miner.miner_dir() / "miner.log").read_text(encoding="utf-8")


# ------------------------------------------------- positive controls first


def test_a_background_job_session_is_mined(home, transcripts, monkeypatch):
    """The user: "background jobs yes". A Claude Code background session, new
    or tracked and grown, reaches the reader and is never halted."""
    new = write_session(transcripts, WORK_FOLDER, "sess-bg-new", background_lines())
    tracked = write_session(transcripts, WORK_FOLDER, "sess-bg-tracked", background_lines("first"))
    track_at_end(tracked)
    append(tracked, user_row(f"{BACKGROUND_TAIL} second task", **BACKGROUND_ROW), assistant_row("ok"))
    prompts = shim_reader(monkeypatch)

    result = miner.run(home)

    assert result.status == "ok" and result.sessions_scanned == 2
    assert BACKGROUND_TAIL in prompts[0] and f"{BACKGROUND_TAIL} second task" in prompts[0]
    cursors = miner._load_cursors()
    assert not cursors[str(new)].get("halt") and not cursors[str(tracked)].get("halt")


def test_a_typed_session_is_mined(home, transcripts, monkeypatch):
    path = write_session(transcripts, WORK_FOLDER, "sess-typed", typed_lines())
    prompts = shim_reader(monkeypatch)

    assert miner.run(home).status == "ok"

    assert TYPED_TAIL in prompts[0]
    assert not miner._load_cursors()[str(path)].get("halt")


# ------------------------------------------------------ the digest


def test_a_scheduled_job_session_is_halted_by_the_digest(transcripts):
    path = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    s = slice_of(path)

    assert miner.digest_transcript(s) == (None, True)
    assert s.halt_reason == miner.HALT_SCHEDULED_JOB


def test_a_job_named_in_the_opt_in_is_digested(transcripts):
    path = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    s = slice_of(path)

    digest, halt = miner.digest_transcript(s, mined_scheduled=frozenset({"news-digest"}))

    assert halt is False and s.halt_reason is None
    assert digest is not None and SCHEDULED_TAIL in digest
    # positive control: a different name is still a skipped job
    assert miner.digest_transcript(slice_of(path), mined_scheduled=frozenset({"other-job"})) == (None, True)


def test_the_tag_counts_only_as_the_opening_of_the_first_turn(transcripts):
    """Like a self-learn header: a person who pastes the tag into their own
    message, or a later turn that opens with it, is not a scheduled job."""
    scheduled = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    assert miner.digest_transcript(slice_of(scheduled)) == (None, True)  # positive control: the opening halts

    pasted = write_session(
        transcripts, WORK_FOLDER, "sess-pasted",
        [user_row(f"why does my job open with {scheduled_prompt('news-digest')} ?", **TYPED_ROW), assistant_row(TYPED_TAIL)],
    )
    later = write_session(
        transcripts, WORK_FOLDER, "sess-later",
        [*typed_lines(), user_row(scheduled_prompt("news-digest"), **TYPED_ROW), assistant_row("done")],
    )
    for path in (pasted, later):
        digest, halt = miner.digest_transcript(slice_of(path))
        assert halt is False and digest is not None and TYPED_TAIL in digest


def test_the_job_name_is_read_from_the_opening_tag():
    assert miner._scheduled_job_name(scheduled_prompt("news-digest")) == "news-digest"
    assert miner._scheduled_job_name('  <scheduled-task file="/x/SKILL.md" name="late-name">\nbody') == "late-name"
    assert miner._scheduled_job_name("<scheduled-task>\nno name at all") == ""
    # a different tag that shares the prefix, and plain text, are not jobs
    assert miner._scheduled_job_name('<scheduled-tasks name="news-digest">') is None
    assert miner._scheduled_job_name("scheduled-task news-digest") is None


# ------------------------------------------------------ a whole night


def test_a_new_scheduled_session_is_halted_and_never_mined(home, transcripts, monkeypatch):
    scheduled = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    typed = write_session(transcripts, WORK_FOLDER, "sess-typed", typed_lines())
    prompts = shim_reader(monkeypatch)

    assert miner.run(home).status == "ok"

    assert TYPED_TAIL in prompts[0]  # positive control: the reader ran on this night's sessions
    assert SCHEDULED_TAIL not in prompts[0] and "news-digest" not in prompts[0]
    assert miner._load_cursors()[str(scheduled)].get("halt") is True
    assert not miner._load_cursors()[str(typed)].get("halt")

    # a scheduled session that grows stays unread
    append(scheduled, user_row(f"{SCHEDULED_TAIL} follow-up", **SCHEDULED_ROW), assistant_row("ok"))
    append(typed, user_row(f"{TYPED_TAIL} follow-up", **TYPED_ROW), assistant_row("ok"))
    assert miner.run(home).status == "ok"
    assert f"{TYPED_TAIL} follow-up" in prompts[1]
    assert SCHEDULED_TAIL not in prompts[1]


def test_the_run_logs_its_halts_by_reason_and_names_nothing(home, transcripts, monkeypatch):
    write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    write_session(transcripts, SCHEDULED_FOLDER, "sess-sync", scheduled_lines("notes-sync"))
    write_session(
        transcripts, WORK_FOLDER, "sess-miner",
        [user_row("You are the self-learn transcript miner. Below are digests.", promptSource="sdk"), assistant_row("x")],
    )
    write_session(transcripts, WORK_FOLDER, "sess-typed", typed_lines())
    shim_reader(monkeypatch)

    assert miner.run(home).status == "ok"

    text = log_text()
    assert "halted 3 sessions, the rest of each never mined (scheduled job: 2, self-learn prompt: 1)" in text
    for secret in ("news-digest", "notes-sync", "sess-news", SCHEDULED_FOLDER, SCHEDULED_TAIL):
        assert secret not in text


def test_a_job_the_user_names_is_mined_and_the_others_are_not(home, transcripts, monkeypatch):
    """The opt-in, through config.yaml the way `self-learn config set` writes it:
    comma-separated job names."""
    (home / "config.yaml").write_text(
        "miner:\n  mined_scheduled_jobs: 'news-digest, weekly-review'\n", encoding="utf-8"
    )
    commit_all(home, "config: opt two scheduled jobs in")
    named = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    unnamed = write_session(transcripts, SCHEDULED_FOLDER, "sess-sync", scheduled_lines("notes-sync"))
    prompts = shim_reader(monkeypatch)

    assert miner.run(home).status == "ok"

    assert f"{SCHEDULED_TAIL} news-digest" in prompts[0]
    assert f"{SCHEDULED_TAIL} notes-sync" not in prompts[0]
    cursors = miner._load_cursors()
    assert not cursors[str(named)].get("halt") and cursors[str(unnamed)].get("halt") is True


def test_the_opt_in_is_a_comma_separated_list_and_none_by_default(home, monkeypatch):
    assert settings.by_name("miner.mined_scheduled_jobs").default == ""
    assert miner.mined_scheduled_jobs(home) == frozenset()
    monkeypatch.setenv(ENV_VAR, " news-digest,, weekly-review ,")
    assert miner.mined_scheduled_jobs(home) == frozenset({"news-digest", "weekly-review"})


def test_a_backfill_still_skips_a_scheduled_session(home, transcripts, monkeypatch):
    """`--since` re-reads files from their first line whatever their cursor says,
    halted ones included; the first turn halts the scheduled one again."""
    scheduled = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    typed = write_session(transcripts, WORK_FOLDER, "sess-typed", typed_lines())
    for path in (scheduled, typed):
        track_at_end(path)
    prompts = shim_reader(monkeypatch)

    assert miner.run(home, since="2000-01-01").status == "ok"

    assert TYPED_TAIL in prompts[0]  # positive control: the backfill re-read the tracked files
    assert SCHEDULED_TAIL not in prompts[0]


# ----------------------------------------- sessions the cursor file already tracks


def test_tracked_scheduled_sessions_are_halted_by_the_next_mine(home, transcripts, monkeypatch):
    """The live machine's state on 2026-10-07: every scheduled-task session
    tracked, none halted. The next mine halts them before it walks, so one that
    grows is not read from its cursor onward; a tracked background session that
    grows is read as before."""
    scheduled = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    background = write_session(transcripts, WORK_FOLDER, "sess-bg", background_lines("first"))
    for path in (scheduled, background):
        track_at_end(path)
    append(scheduled, user_row(f"{SCHEDULED_TAIL} follow-up", **SCHEDULED_ROW), assistant_row("ok"))
    append(background, user_row(f"{BACKGROUND_TAIL} follow-up", **BACKGROUND_ROW), assistant_row("ok"))
    prompts = shim_reader(monkeypatch)

    assert miner.run(home).status == "ok"

    assert f"{BACKGROUND_TAIL} follow-up" in prompts[0]  # positive control
    assert SCHEDULED_TAIL not in prompts[0]
    cursors = miner._load_cursors()
    assert cursors[str(scheduled)].get("halt") is True and not cursors[str(background)].get("halt")
    assert cursors[miner._SCHEDULED_CHECKED_KEY] == miner._scheduled_fingerprint(frozenset())
    assert "halted 1 tracked sessions of scheduled jobs" in log_text()


def test_the_tracked_check_runs_once_per_rule_and_again_when_the_opt_in_changes(home, transcripts, monkeypatch):
    """Reading the head of every tracked file is a one-time cost: the next mine
    reads none. Taking a job out of the opt-in is a change of rule, so the
    tracked files are checked once more and that job's sessions are halted."""
    monkeypatch.setenv(ENV_VAR, "news-digest")
    scheduled = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    typed = write_session(transcripts, WORK_FOLDER, "sess-typed", typed_lines())
    for path in (scheduled, typed):
        track_at_end(path)
    shim_reader(monkeypatch)
    opened: list[Path] = []
    real_open = Path.open

    def spying_open(self, *args, **kwargs):
        if self.suffix == ".jsonl":
            opened.append(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spying_open)

    miner.run(home)
    assert scheduled in opened and typed in opened  # positive control: the first mine read the heads
    assert not miner._load_cursors()[str(scheduled)].get("halt")  # the job is opted in

    opened.clear()
    miner.run(home)
    assert opened == []  # same rule: no transcript read

    monkeypatch.setenv(ENV_VAR, "")
    miner.run(home)
    assert scheduled in opened  # the changed rule is checked again
    assert miner._load_cursors()[str(scheduled)].get("halt") is True
    assert not miner._load_cursors()[str(typed)].get("halt")


def test_a_tracked_file_that_cannot_be_checked_for_jobs_is_checked_again(home, transcripts, monkeypatch):
    scheduled = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    track_at_end(scheduled)
    shim_reader(monkeypatch)
    real = miner._first_user_text

    def failing(path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(miner, "_first_user_text", failing)
    assert miner.run(home).status == "idle"

    cursors = miner._load_cursors()
    assert not cursors[str(scheduled)].get("halt")
    assert miner._SCHEDULED_CHECKED_KEY not in cursors  # not stamped
    text = log_text()
    assert "1 tracked sessions were not checked for scheduled jobs" in text
    assert str(scheduled) not in text

    monkeypatch.setattr(miner, "_first_user_text", real)
    assert miner.run(home).status == "idle"
    cursors = miner._load_cursors()
    assert cursors[str(scheduled)].get("halt") is True
    assert cursors[miner._SCHEDULED_CHECKED_KEY] == miner._scheduled_fingerprint(frozenset())


# ------------------------------------------------- first-time activation


def test_first_activation_halts_existing_scheduled_sessions(home, transcripts, monkeypatch):
    miner._save_cursors({})  # a machine that has never mined
    monkeypatch.setenv(ENV_VAR, "weekly-review")
    scheduled = write_session(transcripts, SCHEDULED_FOLDER, "sess-news", scheduled_lines("news-digest"))
    named = write_session(transcripts, SCHEDULED_FOLDER, "sess-weekly", scheduled_lines("weekly-review"))
    background = write_session(transcripts, WORK_FOLDER, "sess-bg", background_lines())
    shim_reader(monkeypatch)

    assert miner.run(home).status == "initialized"

    cursors = miner._load_cursors()
    assert str(background) in cursors and not cursors[str(background)].get("halt")  # positive control
    assert cursors[str(scheduled)].get("halt") is True
    assert not cursors[str(named)].get("halt")
    # the seeding already applied this rule: the next mine has nothing to catch up on
    assert cursors[miner._SCHEDULED_CHECKED_KEY] == miner._scheduled_fingerprint(frozenset({"weekly-review"}))
