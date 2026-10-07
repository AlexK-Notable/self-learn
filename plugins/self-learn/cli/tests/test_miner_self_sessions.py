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

The tests of what a session's first turn does (the digest tests and the whole
night's run on new files) name nothing this unit added, so they run, and fail,
against the code before it. The tests of the tracked-session pass, of the
first-activation stamp, and the pin tests at the bottom name the new functions
and constants.
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

#: The order `steward_prompt._ordered_blocks` returned the seven blocks in at
#: faa1853's parent (`git show faa1853^:.../steward_prompt.py`).
BLOCK_ORDER_BEFORE_0926 = (
    "containment", "method", "user_model", "conditions", "open_cases", "briefs", "output_contract",
)

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


def steward_context(tmp_path):
    return steward_prompt.RunContext(
        run_id="run-test1",
        stage_dir=tmp_path / "stage",
        packet_index=1,
        packet_count=1,
        last_run_at=None,
        verbs_the_runner_executes=("case record", "batch"),
    )


def steward_prompts(tmp_path, home) -> dict[str, str]:
    context = steward_context(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", context, [])
    spec = steward._session_spec(home, tmp_path / "run-dir", packet.per_packet, label="steward-t")
    return {
        # the user message since 2026-09-26: the part of the brief a run does NOT share
        "per-packet": packet.per_packet,
        # before that date (faa1853) the whole brief was the user message, its
        # blocks in the order `_ordered_blocks` then returned them: containment
        # FIRST, then the method
        "whole-brief-before-0926": "\n\n".join(
            f"=== {name} ===\n{dict(packet.blocks)[name]}" for name in BLOCK_ORDER_BEFORE_0926
        ),
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


@pytest.mark.parametrize("kind", ["per-packet", "whole-brief-before-0926", "repair-turn"])
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


def test_a_program_run_session_that_is_not_self_learns_is_still_mined(tmp_path, home, transcripts, monkeypatch):
    """The user wants sessions a program ran (rows with `promptSource: "sdk"`
    and no `origin`) mined, unless they are self-learn's own agents. The halt
    reads the prompt's opening, never that marker."""
    prompt = "Summarise the release notes below in three bullets and fix the typo in the README."
    path = write_session(transcripts, ORDINARY_FOLDER, "sess-program", [user_row(prompt, **SDK_ROW), assistant_row(ORDINARY_TAIL)])
    digest, halt = miner.digest_transcript(slice_of(path))
    assert halt is False and digest is not None and ORDINARY_TAIL in digest
    # a whole night: a new program-run session is read, a tracked one that grew is read
    tracked = write_session(transcripts, ORDINARY_FOLDER, "sess-program-tracked", [user_row(prompt, **SDK_ROW), assistant_row("first")])
    track_at_end(tracked)
    append(tracked, user_row(f"{ORDINARY_TAIL} second turn", **SDK_ROW), assistant_row("ok"))
    captured = shim_reader(monkeypatch)
    result = miner.run(home)
    assert result.status == "ok" and result.sessions_scanned == 2
    assert f"{ORDINARY_TAIL} second turn" in captured["prompt"] and prompt in captured["prompt"]
    cursors = miner._load_cursors()
    assert not cursors[str(path)].get("halt") and not cursors[str(tracked)].get("halt")


def test_a_session_that_opens_with_the_method_block_is_not_halted(tmp_path, home, transcripts, monkeypatch):
    """No steward session ever began with the method block (it came second, then
    moved to the appended system prompt). A person who pastes the shared brief
    as their first message is an ordinary session, and is mined."""
    method = dict(steward_prompt.assemble(home, tmp_path / "cache", steward_context(tmp_path), []).blocks)["method"]
    pasted = f"=== method ===\n{method}\n\nwhat do you make of section 4?"
    path = write_session(transcripts, ORDINARY_FOLDER, "sess-pasted-method", [user_row(pasted, **TYPED_ROW), assistant_row(ORDINARY_TAIL)])
    digest, halt = miner.digest_transcript(slice_of(path))
    assert halt is False and digest is not None and "what do you make of section 4?" in digest
    # and the pass over tracked files leaves it alone too
    track_at_end(path)
    shim_reader(monkeypatch)
    miner.run(home)
    assert not miner._load_cursors()[str(path)].get("halt")
    assert miner._load_cursors()[miner._HEADERS_CHECKED_KEY] == miner._headers_fingerprint()  # positive control: the pass ran


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
        write_session(transcripts, STEWARD_FOLDER, "sess-steward-old", own_session_lines(steward_texts["whole-brief-before-0926"])),
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
    previous_list = (  # the list as it stood before the worker's repair pass was added
        "You are the self-learn routing analyst worker.",
        "You are the self-learn transcript miner.",
        "=== containment ===",
        "=== method ===",
        "You are the self-learn overseer",
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


def test_a_malformed_row_never_stops_the_sweep(tmp_path, home, transcripts, monkeypatch):
    """A row of an odd shape is "no text here", never an exception: one such row
    in one file must not stop the pass, keep it from stamping its fingerprint
    (every later mine would crash the same way), or hide the self-learn prompts
    that follow it."""
    prompt = overseer_prompts(tmp_path)["phase-a"]
    odd_rows = [
        json.dumps({"type": "user", "message": "a string where a message goes"}),
        json.dumps({"type": "user", "message": ["not", "a", "message"]}),
        json.dumps({"type": "user", "message": {"content": 7}}),
        "[" * 100_000 + "]" * 100_000,  # valid JSON, too deep for the parser
        "not json at all",
        json.dumps(["a", "list", "row"]),
    ]
    odd_then_own = write_session(transcripts, OVERSEER_FOLDER, "sess-odd-then-own", [*odd_rows, *own_session_lines(prompt)])
    odd_then_ordinary = write_session(transcripts, ORDINARY_FOLDER, "sess-odd-then-ordinary", [*odd_rows, *ordinary_session_lines()])
    clean_own = write_session(transcripts, OVERSEER_FOLDER, "sess-clean-own", own_session_lines(prompt))
    clean_ordinary = write_session(transcripts, ORDINARY_FOLDER, "sess-clean-ordinary", ordinary_session_lines())
    for path in (odd_then_own, odd_then_ordinary, clean_own, clean_ordinary):
        track_at_end(path)
    shim_reader(monkeypatch)

    assert miner.run(home).status == "idle"

    cursors = miner._load_cursors()
    assert cursors[miner._HEADERS_CHECKED_KEY] == miner._headers_fingerprint()
    assert cursors[str(clean_own)].get("halt") is True  # positive control: the pass did its work
    assert cursors[str(odd_then_own)].get("halt") is True  # the odd rows are skipped, the prompt behind them is seen
    assert not cursors[str(odd_then_ordinary)].get("halt")
    assert not cursors[str(clean_ordinary)].get("halt")


def test_a_row_that_is_not_utf8_does_not_hide_the_prompt_behind_it(tmp_path, home, transcripts, monkeypatch):
    """Bytes that are not UTF-8 are read as replacement characters: the file is
    still checked, and the pass still stamps its fingerprint."""
    own = transcripts / OVERSEER_FOLDER / "sess-bad-bytes.jsonl"
    own.write_bytes(b"\xff\xfe not text \x80\n" + "\n".join(own_session_lines(overseer_prompts(tmp_path)["phase-a"])).encode("utf-8") + b"\n")
    cursors = miner._load_cursors()  # tracked at its end by hand: `track_at_end` reads strictly
    cursors[str(own)] = {"lines": 3, "size": own.stat().st_size}
    miner._save_cursors(cursors)
    shim_reader(monkeypatch)

    assert miner.run(home).status == "idle"

    cursors = miner._load_cursors()
    assert cursors[str(own)].get("halt") is True
    assert cursors[miner._HEADERS_CHECKED_KEY] == miner._headers_fingerprint()


def test_a_tracked_file_that_cannot_be_checked_is_checked_again_next_run(tmp_path, home, transcripts, monkeypatch):
    """A file the pass cannot read (a permission error, or any failure of its
    own) is simply not halted this time. The pass does not stamp its
    fingerprint, so the next mine checks again; and it logs a count, never a
    path or any transcript text."""
    prompt = overseer_prompts(tmp_path)["phase-a"]
    unreadable = write_session(transcripts, OVERSEER_FOLDER, "sess-unreadable", own_session_lines(prompt))
    broken = write_session(transcripts, OVERSEER_FOLDER, "sess-broken", own_session_lines(prompt))
    fine = write_session(transcripts, OVERSEER_FOLDER, "sess-fine", own_session_lines(prompt))
    for path in (unreadable, broken, fine):
        track_at_end(path)
    shim_reader(monkeypatch)
    real = miner._first_user_text

    def failing(path):
        if path == unreadable:
            raise PermissionError(13, "Permission denied")
        if path == broken:
            raise RuntimeError(f"unexpected failure with {OWN_TAIL} in it")
        return real(path)

    monkeypatch.setattr(miner, "_first_user_text", failing)

    assert miner.run(home).status == "idle"

    cursors = miner._load_cursors()
    assert cursors[str(fine)].get("halt") is True  # positive control: one bad file does not stop the others
    assert not cursors[str(unreadable)].get("halt") and not cursors[str(broken)].get("halt")
    assert cursors.get(miner._HEADERS_CHECKED_KEY) != miner._headers_fingerprint()  # not stamped
    log_text = (miner.miner_dir() / "miner.log").read_text(encoding="utf-8")
    assert "2 tracked sessions could not be checked" in log_text
    assert OWN_TAIL not in log_text and str(unreadable) not in log_text and "sess-broken" not in log_text

    monkeypatch.setattr(miner, "_first_user_text", real)  # the failures pass
    assert miner.run(home).status == "idle"

    cursors = miner._load_cursors()
    assert cursors[str(unreadable)].get("halt") is True and cursors[str(broken)].get("halt") is True
    assert cursors[miner._HEADERS_CHECKED_KEY] == miner._headers_fingerprint()


def test_a_tracked_session_whose_file_is_gone_is_left_alone(tmp_path, home, transcripts, monkeypatch):
    """Claude Code deletes old transcripts; a cursor entry may outlive its file,
    and a file that is gone is nothing to check again."""
    gone = transcripts / OVERSEER_FOLDER / "sess-gone.jsonl"
    cursors = miner._load_cursors()
    cursors[str(gone)] = {"lines": 2, "size": 100}
    miner._save_cursors(cursors)
    shim_reader(monkeypatch)
    assert miner.run(home).status == "idle"
    assert miner._load_cursors()[str(gone)] == {"lines": 2, "size": 100}
    assert miner._load_cursors()[miner._HEADERS_CHECKED_KEY] == miner._headers_fingerprint()


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
    (opening,) = steward_prompt.SESSION_OPENINGS
    assert steward_texts["per-packet"].startswith(opening)
    assert steward_texts["repair-turn"].startswith(opening)
    assert steward_texts["whole-brief-before-0926"].startswith(opening)
    worker_texts = worker_prompts(tmp_path, home)
    normal, repair = worker.SESSION_OPENINGS
    assert worker_texts["normal-pass"].startswith(normal)
    assert worker_texts["repair-pass"].startswith(repair)
    assert normal != repair


def test_a_row_whose_message_is_not_a_dict_never_stops_the_digest(tmp_path, transcripts):
    """Orchestrator fold, 2026-10-06 (gate-l9 R2's sibling): the nightly loop
    calls `digest_transcript` with no error handling, so one user or assistant
    row whose `message` is not a dict must be skipped, never raised on -- it
    would otherwise stop every mine at the same row, night after night. The
    rest of the session is still read (positive control)."""
    path = write_session(
        transcripts,
        ORDINARY_FOLDER,
        "sess-odd-rows",
        [
            user_row("please fix the failing test", **TYPED_ROW),
            json.dumps({"type": "user", "message": "not a dict"}),
            json.dumps({"type": "user", "message": ["also", "not", "a", "dict"]}),
            json.dumps({"type": "assistant", "message": "not a dict either"}),
            assistant_row(ORDINARY_TAIL),
        ],
    )
    digest, halt = miner.digest_transcript(slice_of(path))
    assert halt is False
    assert digest is not None and ORDINARY_TAIL in digest
