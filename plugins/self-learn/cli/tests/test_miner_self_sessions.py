"""The old miner does not read self-learn's own agent sessions.

The nightly miner (`miner.py`) halts a session whose first user turn opens
with one of `SELF_PROMPT_HEADERS` (M-5). Until 2026-10-06 that list named the
worker's normal-pass prompt and the miner's own prompt only, so the steward's
and the overseer's sessions, and the worker's repair-pass sessions (their
prompt opens "...worker's REPAIR pass", which a header ending in a period never
matched), were read like anyone's work: on the live machine the cursor file
tracked their transcripts with `halt` unset.

Every synthetic session here is built from the REAL prompts, not from a
hand-typed header: `overseer.run._phase_a_prompt` / `_phase_b_prompt`,
`steward_prompt.assemble`, and the worker's `compose_batch_prompt` /
`_compose_repair_prompt`. A later edit to how any of them opens therefore turns
a test red instead of silently re-enabling mining.

Behaviour tests do not name anything this unit added, so they run (red) against
the code before the fix. Only the two pin tests at the bottom name the new
constants.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from self_learn import miner, steward, steward_prompt, worker
from self_learn.overseer import run as overseer_run
from support import make_home

# The distinctive words a session says AFTER its prompt. They must never reach
# the reader's prompt for a self-learn session, and must reach it for an
# ordinary one (the positive control behind every "never" below).
OWN_TAIL = "OWN-SESSION-TAIL-xylophone"
ORDINARY_TAIL = "ORDINARY-SESSION-TAIL-marimba"

#: Project folders shaped like the real ones (Claude Code names a folder after
#: the session's working directory, `/` and `.` becoming `-`).
STEWARD_FOLDER = "-home-u--cache-self-learn-home-0123abcd-steward-runs-run-test1"
OVERSEER_FOLDER = "-home-u--cache-self-learn-home-0123abcd-overseer-workspace-overseer"
WORKER_FOLDER = "-home-u--self-learn"
ORDINARY_FOLDER = "-home-u-proj"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


@pytest.fixture()
def transcripts(tmp_path, monkeypatch):
    root = tmp_path / "transcripts"
    for folder in (ORDINARY_FOLDER, STEWARD_FOLDER, OVERSEER_FOLDER, WORKER_FOLDER):
        (root / folder).mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    miner._save_cursors({"__initialized__": "test-fixture"})
    return root


# ------------------------------------------------------- row builders

#: What Claude Code writes on a prompt a program sent (no `origin`) and on a
#: turn a person typed.
SDK_ROW = {"promptSource": "sdk"}
TYPED_ROW = {"origin": {"kind": "human"}, "promptSource": "typed"}


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


def shim_reader(monkeypatch):
    """Replace the model pass; return the dict that captures its prompt."""
    captured: dict = {}

    def fake(h, prompt):
        captured["prompt"] = prompt
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps({"candidates": [], "fires": []}), encoding="utf-8")
        return out

    monkeypatch.setattr(miner, "_invoke_reader", fake)
    return captured


# ------------------------------------------------------- the real prompts


def overseer_prompts(tmp_path) -> dict[str, str]:
    stage = tmp_path / "stage"
    return {
        "phase-a": overseer_run._phase_a_prompt(stage, 3, 0),
        "phase-b": overseer_run._phase_b_prompt(stage, ("case-0123abcd",), ("case-89abcdef",)),
    }


def steward_prompts(tmp_path, home) -> dict[str, str]:
    context = steward_prompt.RunContext(
        run_id="run-test1",
        stage_dir=tmp_path / "stage",
        packet_index=1,
        packet_count=1,
        last_run_at=None,
        verbs_the_runner_executes=("case record", "batch"),
    )
    packet = steward_prompt.assemble(home, tmp_path / "cache", context, [])
    spec = steward._session_spec(home, tmp_path / "run-dir", packet.per_packet, label="steward-t")
    return {
        # the user message since 2026-09-26: the part of the brief a run does NOT share
        "per-packet": packet.per_packet,
        # the whole brief, the user message of every steward session before that date
        "whole-brief": packet.text,
        # the steward's repair turn is its own session; its prompt extends the packet's
        "repair-turn": steward._repair_spec(spec, "a stage file failed its check").prompt,
    }


def worker_prompts(tmp_path, home) -> dict[str, str]:
    proposal = tmp_path / "proposals" / "lrn-aa00beef.yaml"
    proposal.parent.mkdir(parents=True, exist_ok=True)
    proposal.write_text("recommendation: route\n", encoding="utf-8")
    return {
        "normal-pass": worker.compose_batch_prompt(home, [])[0],
        # the repair pass is its own session, with its own prompt
        "repair-pass": worker._compose_repair_prompt(home, {proposal: "S4: a required key is missing"}),
    }


def own_session_lines(prompt):
    """A finished self-learn session as Claude Code writes it: the program's
    prompt (no `origin`), then the agent's work."""
    return [user_row(prompt, **SDK_ROW), assistant_row(OWN_TAIL)]


def ordinary_session_lines(first="please fix the failing test in the parser"):
    return [user_row(first, **TYPED_ROW), assistant_row(ORDINARY_TAIL)]


# ---------------------------------------------------------- the digest


@pytest.mark.parametrize("phase", ["phase-a", "phase-b"])
def test_overseer_session_is_halted(tmp_path, transcripts, phase):
    prompt = overseer_prompts(tmp_path)[phase]
    path = write_session(transcripts, OVERSEER_FOLDER, f"sess-overseer-{phase}", own_session_lines(prompt))
    assert miner.digest_transcript(slice_of(path)) == (None, True)


@pytest.mark.parametrize("kind", ["per-packet", "whole-brief", "repair-turn"])
def test_steward_session_is_halted(tmp_path, home, transcripts, kind):
    prompt = steward_prompts(tmp_path, home)[kind]
    path = write_session(transcripts, STEWARD_FOLDER, f"sess-steward-{kind}", own_session_lines(prompt))
    assert miner.digest_transcript(slice_of(path)) == (None, True)


@pytest.mark.parametrize("kind", ["normal-pass", "repair-pass"])
def test_worker_session_is_halted(tmp_path, home, transcripts, kind):
    prompt = worker_prompts(tmp_path, home)[kind]
    path = write_session(transcripts, WORKER_FOLDER, f"sess-worker-{kind}", own_session_lines(prompt))
    assert miner.digest_transcript(slice_of(path)) == (None, True)


def test_ordinary_session_is_still_mined(tmp_path, transcripts):
    """Positive control: the halt is not a blanket one. A person's session is
    digested, whatever markers its rows carry."""
    path = write_session(transcripts, ORDINARY_FOLDER, "sess-ordinary", ordinary_session_lines())
    digest, halt = miner.digest_transcript(slice_of(path))
    assert halt is False
    assert digest is not None and "please fix the failing test" in digest and ORDINARY_TAIL in digest


def test_a_prompt_that_only_mentions_the_openings_is_still_mined(tmp_path, home, transcripts):
    """The opening must BEGIN the first user turn. A person who pastes a
    steward or overseer prompt into the middle of their own message is not one
    of self-learn's agents."""
    quoted = (
        "why does the overseer say this?\n"
        + overseer_prompts(tmp_path)["phase-a"]
        + "\n"
        + steward_prompts(tmp_path, home)["per-packet"]
    )
    path = write_session(transcripts, ORDINARY_FOLDER, "sess-quoting", [user_row(quoted, **TYPED_ROW), assistant_row(ORDINARY_TAIL)])
    digest, halt = miner.digest_transcript(slice_of(path))
    assert halt is False and digest is not None and "why does the overseer say this?" in digest


# ------------------------------------------------- a night's run (new files)


def test_run_halts_new_own_sessions_and_mines_the_ordinary_one(tmp_path, home, transcripts, monkeypatch):
    prompts = overseer_prompts(tmp_path)
    steward_texts = steward_prompts(tmp_path, home)
    own = [
        write_session(transcripts, OVERSEER_FOLDER, "sess-overseer", own_session_lines(prompts["phase-a"])),
        write_session(transcripts, STEWARD_FOLDER, "sess-steward", own_session_lines(steward_texts["per-packet"])),
    ]
    ordinary = write_session(transcripts, ORDINARY_FOLDER, "sess-ordinary", ordinary_session_lines())
    captured = shim_reader(monkeypatch)

    result = miner.run(home)

    assert result.status == "ok" and result.sessions_scanned == 1
    assert ORDINARY_TAIL in captured["prompt"]  # positive control: the reader ran and saw the ordinary session
    assert OWN_TAIL not in captured["prompt"]
    cursors = miner._load_cursors()
    assert [cursors[str(p)].get("halt") for p in own] == [True, True]
    assert not cursors[str(ordinary)].get("halt")


# --------------------------------- sessions the cursor file already tracks


def track_at_end(path):
    """Put a cursor entry on `path` as an earlier mine left it: read to the
    end, `halt` unset (the state of the live machine's steward and overseer
    transcripts)."""
    cursors = miner._load_cursors()
    cursors[str(path)] = {"lines": len(path.read_text(encoding="utf-8").splitlines()), "size": path.stat().st_size}
    miner._save_cursors(cursors)


def test_tracked_own_sessions_are_halted_by_the_next_mine(tmp_path, home, transcripts, monkeypatch):
    """The ~78 files the cursor file tracks with `halt` unset: finished, so the
    walk skips them on an unchanged size and never reads their first turn. The
    next mine halts them anyway, in the cursor file, where it can be seen."""
    prompts = overseer_prompts(tmp_path)
    steward_texts = steward_prompts(tmp_path, home)
    worker_texts = worker_prompts(tmp_path, home)
    own = [
        write_session(transcripts, OVERSEER_FOLDER, "sess-overseer-a", own_session_lines(prompts["phase-a"])),
        write_session(transcripts, OVERSEER_FOLDER, "sess-overseer-b", own_session_lines(prompts["phase-b"])),
        write_session(transcripts, STEWARD_FOLDER, "sess-steward-now", own_session_lines(steward_texts["per-packet"])),
        write_session(transcripts, STEWARD_FOLDER, "sess-steward-old", own_session_lines(steward_texts["whole-brief"])),
        write_session(transcripts, WORKER_FOLDER, "sess-worker-normal", own_session_lines(worker_texts["normal-pass"])),
        write_session(transcripts, WORKER_FOLDER, "sess-worker-repair", own_session_lines(worker_texts["repair-pass"])),
    ]
    ordinary = write_session(transcripts, ORDINARY_FOLDER, "sess-ordinary", ordinary_session_lines())
    for path in (*own, ordinary):
        track_at_end(path)
    for path in (*own, ordinary):
        assert not miner._load_cursors()[str(path)].get("halt")  # the starting state
    before_ordinary = miner._load_cursors()[str(ordinary)]
    captured = shim_reader(monkeypatch)

    result = miner.run(home)

    cursors = miner._load_cursors()
    assert [cursors[str(p)].get("halt") for p in own] == [True] * 6
    assert cursors[str(ordinary)] == before_ordinary  # positive control: an ordinary entry is left alone
    assert result.status == "idle" and "prompt" not in captured
    assert "halted 6 tracked" in (miner.miner_dir() / "miner.log").read_text(encoding="utf-8")


def test_a_tracked_own_session_that_grew_is_not_mined(tmp_path, home, transcripts, monkeypatch):
    """A tracked file read from its cursor onward shows the walk only the tail,
    where no first prompt is. It must be halted before that read."""
    prompt = overseer_prompts(tmp_path)["phase-b"]
    own = write_session(transcripts, OVERSEER_FOLDER, "sess-overseer-grew", own_session_lines(prompt))
    ordinary = write_session(transcripts, ORDINARY_FOLDER, "sess-ordinary-grew", ordinary_session_lines())
    track_at_end(own)
    track_at_end(ordinary)
    append(own, user_row(f"{OWN_TAIL} later turn", **TYPED_ROW), assistant_row("ok"))
    append(ordinary, user_row(f"{ORDINARY_TAIL} later turn", **TYPED_ROW), assistant_row("ok"))
    captured = shim_reader(monkeypatch)

    result = miner.run(home)

    assert result.status == "ok" and result.sessions_scanned == 1
    assert f"{ORDINARY_TAIL} later turn" in captured["prompt"]  # positive control: grown files are read
    assert f"{OWN_TAIL} later turn" not in captured["prompt"]
    cursors = miner._load_cursors()
    assert cursors[str(own)].get("halt") is True and not cursors[str(ordinary)].get("halt")


def test_the_check_of_tracked_sessions_runs_once_per_header_list(tmp_path, home, transcripts, monkeypatch):
    """Reading the head of every tracked file is a one-time cost, not nightly
    I/O: a second mine reads none. Changing the header list makes the check
    run again, so a header added later reaches the files already tracked --
    the way this bug arose."""
    own = write_session(transcripts, OVERSEER_FOLDER, "sess-overseer", own_session_lines(overseer_prompts(tmp_path)["phase-a"]))
    ordinary = write_session(transcripts, ORDINARY_FOLDER, "sess-ordinary", ordinary_session_lines())
    future = write_session(
        transcripts, ORDINARY_FOLDER, "sess-future-agent",
        [user_row("You are the self-learn future agent. Work.", **SDK_ROW), assistant_row(OWN_TAIL)],
    )
    for path in (own, ordinary, future):
        track_at_end(path)
    shim_reader(monkeypatch)
    opened: list[Path] = []
    real_open = Path.open

    def spying_open(self, *args, **kwargs):
        if self.suffix == ".jsonl":
            opened.append(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spying_open)
    real_read_text = Path.read_text

    def spying_read_text(self, *args, **kwargs):
        if self.suffix == ".jsonl":
            opened.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spying_read_text)

    miner.run(home)
    assert own in opened and ordinary in opened  # positive control: the first mine did read the heads
    assert miner._load_cursors()[str(own)].get("halt") is True
    assert not miner._load_cursors()[str(future)].get("halt")  # not yet a self-learn header

    opened.clear()
    miner.run(home)
    assert opened == []  # the second mine read no transcript

    monkeypatch.setattr(miner, "SELF_PROMPT_HEADERS", (*miner.SELF_PROMPT_HEADERS, "You are the self-learn future agent."))
    opened.clear()
    miner.run(home)
    assert future in opened  # the changed list is checked again
    assert miner._load_cursors()[str(future)].get("halt") is True


def test_adding_a_header_checks_the_tracked_files_once_more(tmp_path, home, transcripts, monkeypatch):
    """Intended: the header list's fingerprint changes whenever the list does,
    so the pass that halts tracked sessions runs once more. Here the list is
    the one the miner carried before the worker's repair pass was added, already
    stamped in the cursor file, and a tracked repair-pass session is waiting."""
    repair = write_session(
        transcripts, WORKER_FOLDER, "sess-worker-repair",
        own_session_lines(worker_prompts(tmp_path, home)["repair-pass"]),
    )
    track_at_end(repair)
    previous_list = (
        "You are the self-learn routing analyst worker.",
        "You are the self-learn transcript miner.",
        *steward_prompt.SESSION_OPENINGS,
        *overseer_run.SESSION_OPENINGS,
    )
    previous = hashlib.sha256("\n".join(previous_list).encode("utf-8")).hexdigest()[:16]
    assert miner._headers_fingerprint() != previous  # positive control: the list did change
    cursors = miner._load_cursors()
    cursors["__self_prompt_headers__"] = previous
    miner._save_cursors(cursors)
    shim_reader(monkeypatch)

    miner.run(home)

    cursors = miner._load_cursors()
    assert cursors[str(repair)].get("halt") is True
    assert cursors["__self_prompt_headers__"] == miner._headers_fingerprint()


def test_a_tracked_session_whose_file_is_gone_is_left_alone(tmp_path, home, transcripts, monkeypatch):
    """Claude Code deletes old transcripts; a cursor entry may outlive its file."""
    gone = transcripts / OVERSEER_FOLDER / "sess-gone.jsonl"
    cursors = miner._load_cursors()
    cursors[str(gone)] = {"lines": 2, "size": 100}
    miner._save_cursors(cursors)
    shim_reader(monkeypatch)
    assert miner.run(home).status == "idle"
    assert miner._load_cursors()[str(gone)] == {"lines": 2, "size": 100}


# ------------------------------------------------- first-time activation


def test_first_activation_halts_existing_own_sessions(tmp_path, home, transcripts, monkeypatch):
    """The forward-only seeding already halts a history that carries a
    self-learn marker anywhere; the steward's and overseer's openings are
    markers too."""
    miner._save_cursors({})  # a machine that has never mined
    prompts = overseer_prompts(tmp_path)
    steward_texts = steward_prompts(tmp_path, home)
    own = [
        write_session(transcripts, OVERSEER_FOLDER, "sess-overseer", own_session_lines(prompts["phase-b"])),
        write_session(transcripts, STEWARD_FOLDER, "sess-steward", own_session_lines(steward_texts["per-packet"])),
    ]
    ordinary = write_session(transcripts, ORDINARY_FOLDER, "sess-ordinary", ordinary_session_lines())
    shim_reader(monkeypatch)

    assert miner.run(home).status == "initialized"

    cursors = miner._load_cursors()
    assert [cursors[str(p)].get("halt") for p in own] == [True, True]
    assert not cursors[str(ordinary)].get("halt")  # positive control: the seeding did record it
    assert str(ordinary) in cursors
    # the seeding already checked every file against this header list: the
    # next mine has nothing to catch up on
    assert cursors[miner._HEADERS_CHECKED_KEY] == miner._headers_fingerprint()


# ---------------------------------------- the pins on the prompts' openings


def test_the_miner_takes_its_headers_from_the_prompts():
    openings = (*worker.SESSION_OPENINGS, *steward_prompt.SESSION_OPENINGS, *overseer_run.SESSION_OPENINGS)
    assert openings  # an empty tuple would pass the subset check below for nothing
    assert set(openings) <= set(miner.SELF_PROMPT_HEADERS)


def test_every_real_prompt_begins_with_its_declared_opening(tmp_path, home):
    for name, text in overseer_prompts(tmp_path).items():
        assert text.startswith(overseer_run.SESSION_OPENINGS), name
    steward_texts = steward_prompts(tmp_path, home)
    now, legacy = steward_prompt.SESSION_OPENINGS
    assert steward_texts["per-packet"].startswith(now)
    assert steward_texts["repair-turn"].startswith(now)
    assert steward_texts["whole-brief"].startswith(legacy)
    assert now != legacy
    worker_texts = worker_prompts(tmp_path, home)
    normal, repair = worker.SESSION_OPENINGS
    assert worker_texts["normal-pass"].startswith(normal)
    assert worker_texts["repair-pass"].startswith(repair)
    assert normal != repair
