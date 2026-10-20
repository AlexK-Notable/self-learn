"""One halt predicate both miners share (new-miner plan §3.1, unit R0c).

`miner.halt_point` makes the three halt decisions that used to live inline in
`miner.digest_transcript`, without building a digest: a first typed turn that
opens with a self-prompt header halts the whole session, so does a first typed
turn that is a scheduled job nobody asked to have mined, and any self-learn
command tag in a user text turn ends the slice there. The new miner's session
planner needs the halt and the end of the judged range without a digest; the
old miner's digest needs the same answer. One function gives it to both.

The refactor changes no behaviour. The second half of this file holds the
proof: a synthetic fixture set whose digests were recorded from
`digest_transcript` at master `ee314c5`, before the predicate existed
(`fixtures/golden/miner-digests-ee314c5.json`), and must come out
byte-identical now. Regenerating that file from the current code would defeat
it; it changes only with a deliberate change to what the digest says.

Every fixture here is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import miner, provenance

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "miner-digests-ee314c5.json"

SELF_HEADER = "You are the self-learn transcript miner."
COMMAND = "<command-name>/self-learn:review</command-name> run it"
JOB = '<scheduled-task name="news-digest" file="/x/scheduled-tasks/news-digest/SKILL.md">\nSummarise the news.'

ORCH = "aaaaaaaa-0000-0000-0000-000000000001"  # the session that sends
WORKER = "bbbbbbbb-0000-0000-0000-000000000002"  # the session typed into
BRIEF = "Read /work/repo/misc/BRIEF.md in full and do exactly what it says; report when done."


# ------------------------------------------------------------ row builders


def _ts(sec: int) -> str:
    return f"2026-10-19T12:{sec // 60:02d}:{sec % 60:02d}.000Z"


def u(text: str, sec: int = 1, **extra) -> str:
    """A turn a person typed (Claude Code's markers on one)."""
    e = {
        "type": "user", "uuid": f"u-{sec}", "sessionId": WORKER, "timestamp": _ts(sec),
        "origin": {"kind": "human"}, "promptSource": "typed",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    e.update(extra)
    return json.dumps(e)


def u_str(text: str, sec: int = 1) -> str:
    """A user turn whose content is a bare string."""
    return json.dumps({"type": "user", "uuid": f"u-{sec}", "sessionId": WORKER, "timestamp": _ts(sec),
                       "origin": {"kind": "human"}, "message": {"role": "user", "content": text}})


def sdk(text: str) -> str:
    """A prompt a program sent (no `origin`)."""
    return json.dumps({"type": "user", "promptSource": "sdk",
                       "message": {"role": "user", "content": [{"type": "text", "text": text}]}})


def a(text: str, sec: int = 2) -> str:
    return json.dumps({"type": "assistant", "uuid": f"a-{sec}", "sessionId": WORKER, "timestamp": _ts(sec),
                       "message": {"content": [{"type": "text", "text": text}]}})


def tool(command: str, tid: str) -> str:
    return json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}]}})


def result(tid: str, text: str, is_error: bool = False, extra_text: str | None = None) -> str:
    blocks: list[dict] = [{"type": "tool_result", "tool_use_id": tid, "is_error": is_error,
                           "content": [{"type": "text", "text": text}]}]
    if extra_text is not None:
        blocks.append({"type": "text", "text": extra_text})
    return json.dumps({"type": "user", "message": {"role": "user", "content": blocks}})


def blank_user() -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "   "}]}})


def slice_of(name: str, lines: list[str], start: int = 0) -> miner.SessionSlice:
    """A slice of `lines` from `start`; the path is never read."""
    return miner.SessionSlice(path=Path("fixture") / f"{name}.jsonl", session_id=name, project="-work-repo",
                              start_line=start, lines=lines[start:])


def sent_brief() -> provenance.SentIndex:
    """One herdr send from another session, holding BRIEF, just before second 10."""
    raw = f'herdr agent prompt w "{BRIEF}"'
    return provenance.SentIndex([provenance.Send(provenance._epoch(_ts(8)), ORCH, raw, provenance.fold(raw))])  # pyright: ignore[reportPrivateUsage]


# ----------------------------------------------------------- the predicate


def test_no_halt_control():
    """An ordinary session: no halt, no cut. Also the positive control for
    every halt below: the same builders, minus the halting turn."""
    s = slice_of("plain", [u("please fix the parser"), a("done"), u("thanks", 3)])
    assert miner.halt_point(s) == miner.HaltPoint(end=None, halt=False, reason=None)
    assert s.halt_reason is None  # the predicate reads the slice, never writes it


def test_a_self_prompt_first_turn_halts_the_whole_session():
    s = slice_of("own", [a("stray assistant line first", 1), u(f"{SELF_HEADER} Digests below.", 2), a("ok", 3)])
    assert miner.halt_point(s) == miner.HaltPoint(end=0, halt=True, reason=miner.HALT_SELF_PROMPT)
    # control: the header later in the session is not an opening
    later = slice_of("own-later", [u("hello"), u(f"{SELF_HEADER} Digests below.", 2)])
    assert miner.halt_point(later).halt is False


def test_a_skipped_scheduled_job_first_turn_halts_the_whole_session():
    s = slice_of("job", [u(JOB), a("summary")])
    assert miner.halt_point(s) == miner.HaltPoint(end=0, halt=True, reason=miner.HALT_SCHEDULED_JOB)
    # control: the same job, named for mining, is not halted
    assert miner.halt_point(s, mined_scheduled=frozenset({"news-digest"})).halt is False


def test_a_self_learn_command_tag_ends_the_slice_at_its_line():
    lines = [u("normal work before"), a("ok"), u(COMMAND, 3), a("Card 1 of 3"), u("route it", 5)]
    s = slice_of("cmd", lines)
    assert miner.halt_point(s) == miner.HaltPoint(end=2, halt=True, reason=miner.HALT_SELF_COMMAND)
    # the end is an index into the slice's lines, so a slice that starts later
    # ends at the same transcript line
    assert miner.halt_point(slice_of("cmd", lines, start=1)).end == 1


def test_a_command_tag_in_the_first_turn_ends_the_slice_at_that_turn():
    s = slice_of("cmd-first", [a("stray", 1), u(COMMAND, 2), a("Card 1")])
    assert miner.halt_point(s) == miner.HaltPoint(end=1, halt=True, reason=miner.HALT_SELF_COMMAND)


def test_the_first_turn_checks_come_before_the_command_tag():
    """A self-prompt that also carries a command tag is the self-prompt halt
    (the order `digest_transcript` always had)."""
    s = slice_of("own-and-cmd", [u(f"{SELF_HEADER}\n{COMMAND}")])
    assert miner.halt_point(s).reason == miner.HALT_SELF_PROMPT


def test_first_typed_turn_is_the_first_user_row_with_text_whoever_wrote_it():
    """Blank turns, tool results, malformed rows and assistant rows are not the
    first typed turn; a relay or agent-written row is (S-90 left halts
    reading every user text turn)."""
    filler = ["not json", json.dumps([1, 2]), blank_user(), result("t1", "out"), a("hi")]
    assert miner.halt_point(slice_of("f1", [*filler, u(f"{SELF_HEADER} x", 5)])).reason == miner.HALT_SELF_PROMPT
    assert miner.halt_point(slice_of("f2", [*filler, sdk(f"{SELF_HEADER} x")])).reason == miner.HALT_SELF_PROMPT
    # a relay row first, then the header: the relay was the first typed turn
    assert miner.halt_point(slice_of("f3", [sdk("Summarise the changelog."), u(f"{SELF_HEADER} x", 5)])).halt is False


def test_first_typed_turn_is_counted_within_the_slice():
    """The slice's first user text turn is its "first typed turn", as in
    `digest_transcript` today (the whole-file passes,
    `halt_tracked_self_sessions` and its scheduled twin, look at the file's
    first turn)."""
    lines = [u("hello"), a("ok"), u(f"{SELF_HEADER} x", 3)]
    assert miner.halt_point(slice_of("slice", lines)).halt is False
    assert miner.halt_point(slice_of("slice", lines, start=2)).reason == miner.HALT_SELF_PROMPT


def test_a_command_tag_in_an_assistant_row_does_not_halt():
    s = slice_of("cmd-asst", [u("what is this?"), a(COMMAND)])
    assert miner.halt_point(s).halt is False


# ------------------------------------- byte-identical digests (master ee314c5)


def fixture_cases() -> list[tuple[str, miner.SessionSlice, dict]]:
    """(name, slice, digest_transcript kwargs). The golden file holds what
    `digest_transcript` returned for each at master `ee314c5`."""
    retry = []
    for i in range(3):
        retry += [tool("make build --fast", f"r{i}"), result(f"r{i}", "boom\nline2\nline3", is_error=(i < 2))]
    ordinary = [u("please fix the flaky test"), tool("uv run pytest -q", "t1"),
                result("t1", "\n".join(f"noise {i}" for i in range(40))), a("The root cause was a stale fixture.", 4)]
    sends_session = [sdk("Summarise the changelog."), u("the person typed this", 2),
                     u(f"<agent-message>\n{BRIEF}\n</agent-message>", 4), u(BRIEF, 10), a("done", 11)]
    cmd = [u("normal work before"), tool("ls", "t1"), result("t1", "a\nb"), a("ok"),
           u(COMMAND, 5), a("Card 1 of 3"), u("route it", 7), a("Card 2 of 3")]
    cases: list[tuple[str, miner.SessionSlice, dict]] = [
        ("empty", slice_of("empty", []), {}),
        ("no-text", slice_of("no-text", ["not json", blank_user(), json.dumps({"type": "user", "message": "str"})]), {}),
        ("ordinary", slice_of("ordinary", ordinary), {}),
        ("ordinary-from-line-2", slice_of("ordinary-from-line-2", ordinary, start=1), {}),
        ("retry-cluster", slice_of("retry-cluster", [*retry, u("ugh, again", 9)]), {}),
        ("string-content", slice_of("string-content", [u_str("string-content user turn")]), {}),
        ("text-beside-result", slice_of("text-beside-result", [tool("ls", "t9"), result("t9", "x", extra_text="and look")]), {}),
        ("roles-no-sends", slice_of("roles-no-sends", sends_session), {}),
        ("roles-with-sends", slice_of("roles-with-sends", sends_session), {"sent": sent_brief()}),
        ("sidechain", slice_of("sidechain", [u("a sidechain turn", isSidechain=True)]), {}),
        ("clipped", slice_of("clipped", [u("x" * 400), a("y" * 400)]),
         {"limits": miner.DigestLimits(message_chars=100, session_chars=150)}),
        ("self-prompt", slice_of("self-prompt", [a("stray"), u(f"{SELF_HEADER} Digests below."), a("ok")]), {}),
        ("self-prompt-sdk", slice_of("self-prompt-sdk", [sdk(f"{SELF_HEADER} Digests below."), a("ok")]), {}),
        ("self-prompt-later", slice_of("self-prompt-later", [u("hello"), u(f"{SELF_HEADER} x"), a("ok")]), {}),
        ("self-prompt-in-later-slice", slice_of("self-prompt-in-later-slice", [u("hello"), a("ok"), u(f"{SELF_HEADER} x"), a("tail")], start=2), {}),
        ("self-prompt-and-command", slice_of("self-prompt-and-command", [u(f"{SELF_HEADER}\n{COMMAND}")]), {}),
        ("scheduled", slice_of("scheduled", [u(JOB), a("summary")]), {}),
        ("scheduled-mined", slice_of("scheduled-mined", [u(JOB), a("summary")]), {"mined_scheduled": frozenset({"news-digest"})}),
        ("scheduled-other-mined", slice_of("scheduled-other-mined", [u(JOB), a("summary")]), {"mined_scheduled": frozenset({"other"})}),
        ("scheduled-later", slice_of("scheduled-later", [u("hello"), u(JOB), a("summary")]), {}),
        ("scheduled-then-command", slice_of("scheduled-then-command", [u(JOB), a("summary"), u(COMMAND), a("card")]),
         {"mined_scheduled": frozenset({"news-digest"})}),
        ("command", slice_of("command", cmd), {}),
        ("command-with-sends", slice_of("command-with-sends", [*sends_session, u(COMMAND, 12), a("card")]), {"sent": sent_brief()}),
        ("command-first-line", slice_of("command-first-line", [u(COMMAND), a("Card 1")]), {}),
        ("command-after-assistant", slice_of("command-after-assistant", [a("stray"), u(COMMAND), a("Card 1")]), {}),
        ("command-beside-result", slice_of("command-beside-result", [u("go"), tool("ls", "t2"), result("t2", "x", extra_text=COMMAND), a("card")]), {}),
        ("command-in-assistant", slice_of("command-in-assistant", [u("what is this?"), a(COMMAND)]), {}),
    ]
    return cases


def _outcome(s: miner.SessionSlice, kwargs: dict) -> dict:
    digest, halt = miner.digest_transcript(s, **kwargs)
    return {"digest": digest, "halt": halt, "halt_reason": s.halt_reason}


def test_digests_are_byte_identical_to_master_ee314c5():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = fixture_cases()
    assert sorted(golden) == sorted(name for name, _s, _k in cases)  # every case is pinned
    # positive control: the set reaches every halt kind and a no-halt digest
    reasons = {g["halt_reason"] for g in golden.values()}
    assert {miner.HALT_SELF_PROMPT, miner.HALT_SCHEDULED_JOB, miner.HALT_SELF_COMMAND, None} <= reasons
    assert any(g["digest"] and not g["halt"] for g in golden.values())
    assert any(g["digest"] and g["halt"] for g in golden.values())
    for name, s, kwargs in cases:
        assert _outcome(s, kwargs) == golden[name], name


@pytest.mark.parametrize("name", [n for n, _s, _k in fixture_cases()])
def test_digest_agrees_with_the_predicate(name):
    """Whatever `digest_transcript` decides about halting is what
    `halt_point` decides, case by case."""
    _n, s, kwargs = next(c for c in fixture_cases() if c[0] == name)
    hp = miner.halt_point(s, mined_scheduled=kwargs.get("mined_scheduled", frozenset()))
    digest, halt = miner.digest_transcript(s, **kwargs)
    assert (halt, s.halt_reason) == (hp.halt, hp.reason)
    if hp.end == 0:
        assert digest is None


# ------------------------------------------- the compact-provenance note (R0a)

NOTE = "[compact-provenance note: written by a mod, not typed by the user]\n\nUnverified: " + COMMAND


def _note() -> str:
    """The mod's note as Claude Code stores it: origin-less, string content, marker first."""
    return json.dumps({"type": "user", "message": {"role": "user", "content": NOTE}})


def test_a_note_is_never_the_first_typed_turn():
    # Control first: the self-prompt alone halts.
    assert miner.halt_point(slice_of("np0", [sdk(SELF_HEADER)])).reason == miner.HALT_SELF_PROMPT
    stop = miner.halt_point(slice_of("np1", [_note(), sdk(SELF_HEADER)]))
    assert stop == miner.HaltPoint(0, True, miner.HALT_SELF_PROMPT)


def test_a_command_tag_quoted_in_a_note_does_not_halt():
    # Control first: the same text typed by the person halts at its line.
    assert miner.halt_point(slice_of("nc0", [u("hello"), u(NOTE, 3)])) == miner.HaltPoint(1, True, miner.HALT_SELF_COMMAND)
    s = slice_of("nc1", [u("hello"), _note(), a("ok", 4)])
    assert miner.halt_point(s) == miner.HaltPoint(None, False, None)
    digest, halt = miner.digest_transcript(s)
    assert halt is False and digest is not None and "ok" in digest
