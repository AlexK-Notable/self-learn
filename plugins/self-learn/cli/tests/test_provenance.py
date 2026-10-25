"""Who wrote a turn recorded as typed (``self_learn.provenance``; ``refs``
role rule 10; 02-schema.md "Transcript refs", 2026-10-19).

Synthetic transcripts only, written under ``tmp_path``: no real session
content belongs in this public repository. Every "is not the person's"
assertion is paired with a positive control on the same fixture: the same
turn without the sign reads as ``user``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import miner, provenance, refs
from self_learn.mining import contract
from support import make_home

ORCH = "aaaaaaaa-0000-0000-0000-000000000001"  # the session that sends
WORKER = "bbbbbbbb-0000-0000-0000-000000000002"  # the session typed into
PROJ = "-work-repo"
BRIEF = "Read /work/repo/misc/BRIEF.md in full and do exactly what it says; report when done."
TAGGED = f"<agent-message>\n{BRIEF}\n</agent-message>"


def _ts(sec: int) -> str:
    return f"2026-10-19T12:{sec // 60:02d}:{sec % 60:02d}.000Z"


def typed(text, sec, session=WORKER, **extra):
    e = {"type": "user", "uuid": f"u-{session[:4]}-{sec}", "sessionId": session, "timestamp": _ts(sec),
         "origin": {"kind": "human"}, "promptSource": "typed",
         "message": {"role": "user", "content": text}}
    e.update(extra)
    return e


def pasted(text):
    return f'<pasted_content id="p1">\n{text}\n</pasted_content id="p1">'


def bash(command, sec, session=ORCH):
    return {"type": "assistant", "uuid": f"a-{session[:4]}-{sec}", "sessionId": session, "timestamp": _ts(sec),
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{sec}", "name": "Bash", "input": {"command": command}}]}}


def asst(text, sec, session=WORKER):
    return {"type": "assistant", "uuid": f"a-{session[:4]}-{sec}", "sessionId": session, "timestamp": _ts(sec),
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def write(root: Path, session: str, entries: list, proj: str = PROJ) -> Path:
    d = root / proj
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{session}.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return p


def index(*sends):
    return provenance.SentIndex(
        provenance.Send(provenance._epoch(_ts(sec)), session, raw, provenance.fold(raw))  # pyright: ignore[reportPrivateUsage]
        for sec, session, raw in sends
    )


# ------------------------------------------------------------ sign 1: the tag


def test_a_whole_agent_message_is_tagged_bare_or_inside_a_paste():
    assert provenance.is_tagged(TAGGED)
    assert provenance.is_tagged(pasted(TAGGED))
    assert provenance.is_tagged(f"  \n{TAGGED}\n  ")


def test_a_person_writing_beside_an_agent_message_is_not_tagged():
    assert provenance.is_tagged(pasted(TAGGED))  # positive control
    assert not provenance.is_tagged(f"{pasted(TAGGED)}\nwhat do you make of this?")
    assert not provenance.is_tagged(f"{TAGGED}\nI agree with the brief above.")
    assert not provenance.is_tagged(f"see this: {TAGGED}")
    assert not provenance.is_tagged(f"{TAGGED}\nand mine:\n{TAGGED}")  # two messages, a person between them
    assert not provenance.is_tagged(BRIEF)


@pytest.mark.parametrize("wrap", [lambda t: t, pasted], ids=["bare", "pasted"])
def test_role_of_calls_a_tagged_typed_turn_agent(wrap):
    assert refs.role_of(typed(wrap(BRIEF), 10)) == "user"  # positive control
    assert refs.role_of(typed(wrap(TAGGED), 10)) == "agent"


def test_rule_10_reaches_unmarked_rows_and_queued_commands():
    old = {"type": "user", "message": {"role": "user", "content": TAGGED}}  # rule 8: no marker at all
    assert refs.role_of({**old, "message": {"role": "user", "content": BRIEF}}) == "user"
    assert refs.role_of(old) == "agent"
    queued = {"type": "attachment", "attachment": {"type": "queued_command", "prompt": BRIEF,
                                                   "origin": {"kind": "human"}}}
    assert refs.role_of(queued) == "user"
    assert refs.role_of({**queued, "attachment": {**queued["attachment"], "prompt": TAGGED}}) == "agent"


def test_rule_10_never_turns_a_relay_into_an_agent():
    notification = typed(TAGGED, 10, origin={"kind": "task-notification"})
    assert refs.role_of(notification) == "relay"
    assert refs.role_of(typed(TAGGED, 10, isMeta=True)) == "relay"


# --------------------------------------------- sign 2: an accepted suggestion


def test_an_accepted_suggestion_is_agent():
    assert refs.role_of(typed("run the tests again", 10)) == "user"
    assert refs.role_of(typed("run the tests again", 10, promptSource="suggestion_accepted")) == "agent"


# ------------------------------------------------------------ sign 3: a send


def test_a_turn_another_session_sent_just_before_is_agent():
    sent = index((8, ORCH, f'herdr agent prompt w1:p2 "{BRIEF}"'))
    assert refs.role_of(typed(BRIEF, 10)) == "user"  # no index: only signs 1 and 2
    assert refs.role_of(typed(BRIEF, 10), sent=index()) == "user"
    assert refs.role_of(typed(BRIEF, 10), sent=sent) == "agent"
    assert refs.role_of(typed(pasted(BRIEF), 10), sent=sent) == "agent"


def test_a_send_matches_only_from_another_session_inside_the_window():
    w = provenance.SEND_WINDOW_SECS
    cmd = f'herdr agent prompt w1:p2 "{BRIEF}"'
    turn = typed(BRIEF, 3000)
    assert refs.role_of(turn, sent=index((3000 - w, ORCH, cmd))) == "agent"  # positive control: the edge
    assert refs.role_of(turn, sent=index((3000 - w - 1, ORCH, cmd))) == "user"  # sent too long before
    assert refs.role_of(turn, sent=index((3000 + provenance.SEND_SKEW_SECS + 1, ORCH, cmd))) == "user"  # after
    assert refs.role_of(turn, sent=index((2990, WORKER, cmd))) == "user"  # the session itself


def test_the_turn_must_be_whole_inside_the_send():
    sent = index((8, ORCH, f'herdr agent prompt w1:p2 "{BRIEF}"'))
    assert refs.role_of(typed(BRIEF, 10), sent=sent) == "agent"  # positive control
    assert refs.role_of(typed(BRIEF + " Also fix the README while you are there.", 10), sent=sent) == "user"


def test_a_short_turn_must_be_a_whole_quoted_argument():
    turn = typed("1", 10)
    assert refs.role_of(turn, sent=index((8, ORCH, "herdr pane send-text w1:p2 '1'"))) == "agent"
    assert refs.role_of(turn, sent=index((8, ORCH, "herdr pane read w1:p1 --lines 10"))) == "user"
    yes = typed("yes", 10)
    assert refs.role_of(yes, sent=index((8, ORCH, 'herdr agent prompt w "yes"'))) == "agent"
    assert refs.role_of(yes, sent=index((8, ORCH, 'echo yesterday; herdr agent prompt w "go"'))) == "user"


def test_a_short_turn_quoted_inside_json_is_a_quoted_argument():
    """A Codex ``function_call`` carries its command as JSON, so the quotes
    around a short argument arrive escaped."""
    raw = json.dumps({"cmd": 'herdr agent prompt w1:p2 "yes"'})
    assert '"yes"' not in raw and "'yes'" not in raw  # only the escaped form is present
    assert refs.role_of(typed("yes", 10), sent=index((8, ORCH, raw))) == "agent"


def test_quoting_and_escapes_fold_away():
    multi = "First line of the brief, long enough to be matched as a whole.\nSecond line: don't stop."
    shell = "herdr agent prompt w 'First line of the brief, long enough to be matched as a whole.\nSecond line: don'\\''t stop.'"
    codex = json.dumps({"cmd": f"herdr agent prompt w {json.dumps(multi)}"})
    assert refs.role_of(typed(multi, 10), sent=index((8, ORCH, shell))) == "agent"
    assert refs.role_of(typed(multi, 10), sent=index((8, ORCH, codex))) == "agent"


# ------------------------------------------------------------- the sweep


def test_sweep_reads_herdr_calls_from_claude_and_codex(tmp_path):
    claude = tmp_path / "home" / ".claude" / "projects"
    write(claude, ORCH, [bash(f'herdr agent prompt w1:p2 "{BRIEF}"', 8), bash("ls -la", 9)])
    codex_brief = "A brief sent from a Codex session through a python helper that calls herdr."
    codex_dir = tmp_path / "home" / ".codex" / "sessions" / "2026" / "10" / "19"
    codex_dir.mkdir(parents=True)
    call = {"type": "response_item", "timestamp": _ts(20), "payload": {
        "type": "custom_tool_call", "name": "exec",
        "input": f"subprocess.run(['herdr','agent','prompt','w1:p3',{codex_brief!r}])"}}
    (codex_dir / "rollout-2026-10-19T12-00-00-x.jsonl").write_text(json.dumps(call) + "\n", encoding="utf-8")
    dirs = provenance.sender_dirs([claude])
    assert dirs == [claude, tmp_path / "home" / ".codex" / "sessions",
                    tmp_path / "home" / ".hermes",
                    tmp_path / "home" / ".gemini" / "antigravity-cli" / "brain",
                    tmp_path / "home" / ".pi" / "agent" / "sessions"]
    sent = provenance.sweep(dirs)
    assert len(sent) == 2  # the `ls` call carries no herdr
    assert refs.role_of(typed(BRIEF, 10), sent=sent) == "agent"
    assert refs.role_of(typed(codex_brief, 22), sent=sent) == "agent"


def test_only_a_call_that_mentions_herdr_is_a_send(tmp_path):
    """A row whose prose names herdr but whose tool call does not hand
    anything to it sends nothing."""
    root = tmp_path / "projects"
    row = bash(f"echo '{BRIEF}' > notes.txt", 8)
    row["message"]["content"].insert(0, {"type": "text", "text": "Before I use herdr, a note to myself."})
    write(root, ORCH, [row])
    assert len(provenance.sweep([root])) == 0
    write(root, ORCH, [bash(f"herdr agent prompt w1:p2 '{BRIEF}'", 8)])  # positive control
    assert len(provenance.sweep([root])) == 1


def test_a_codex_function_call_is_read_from_its_arguments(tmp_path):
    codex_dir = tmp_path / "sessions"
    codex_dir.mkdir()
    brief = "A brief a Codex session sent through a function_call to herdr, long enough."
    call = {"type": "response_item", "timestamp": _ts(20), "payload": {
        "type": "function_call", "name": "exec_command",
        "arguments": json.dumps({"cmd": f"herdr agent prompt w1:p3 {json.dumps(brief)}"})}}
    (codex_dir / "rollout-2026-10-19T12-00-00-y.jsonl").write_text(json.dumps(call) + "\n", encoding="utf-8")
    sent = provenance.sweep([codex_dir])
    assert len(sent) == 1
    assert refs.role_of(typed(brief, 22), sent=sent) == "agent"


def test_sender_dirs_adds_codex_only_beside_a_claude_projects_folder(tmp_path):
    other = tmp_path / "transcripts"
    assert provenance.sender_dirs([other]) == [other]
    assert provenance.sweep([tmp_path / "missing"]).__len__() == 0


def test_a_file_that_grows_is_read_again(tmp_path):
    root = tmp_path / "projects"
    path = write(root, ORCH, [bash("ls", 1)])
    assert len(provenance.sweep([root])) == 0
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(bash(f'herdr agent prompt w1:p2 "{BRIEF}"', 8)) + "\n")
    assert len(provenance.sweep([root])) == 1


# --------------------------------------------- the consumers: refs, contract


def test_resolve_and_excerpt_carry_rule_10_from_the_roots_they_read(tmp_path):
    root = tmp_path / "projects"
    write(root, ORCH, [bash(f'herdr agent prompt w1:p2 "{BRIEF}"', 8)])
    write(root, WORKER, [typed("please look at the failing build first", 2), asst("on it", 3),
                         typed(pasted(BRIEF), 10), asst("reading the brief", 11)])
    assert refs.resolve(WORKER, 1, roots=[root]).role == "user"  # positive control: the person's turn
    ref = refs.resolve(WORKER, 3, roots=[root])
    assert ref.role == "agent"
    roles = {r.line: r.role for r, _t in refs.excerpt(refs.resolve(WORKER, 4, roots=[root]), 3, 0, roots=[root])}
    assert roles[1] == "user" and roles[3] == "agent"


def test_resolve_without_the_send_reads_the_brief_as_the_persons(tmp_path):
    """The same worker file with no sender under the roots: the history
    sign has nothing to match, so the brief stays ``user`` (why the
    consumers must sweep)."""
    root = tmp_path / "projects"
    write(root, WORKER, [typed(pasted(BRIEF), 10)])
    assert refs.resolve(WORKER, 1, roots=[root]).role == "user"


def test_a_quote_in_another_sessions_agent_turn_is_still_found(tmp_path):
    """``check_quote``'s other-session search reads the person's and the
    assistant's turns; an agent-written turn stays searchable under its new
    role, and the corrected ref says who wrote it."""
    root = tmp_path / "projects"
    write(root, ORCH, [asst("nothing relevant here", 1, session=ORCH)])
    write(root, WORKER, [typed(TAGGED, 10)])
    ref = refs.resolve(ORCH, 1, roots=[root])
    v = refs.check_quote(ref, "do exactly what it says", roots=[root])
    assert (v.outcome, v.ref.session, v.ref.role) == ("other_session", WORKER, "agent")


def test_a_sent_turn_found_in_another_session_says_agent(tmp_path):
    """The other-session ref is built against the same roots, so it carries
    the send sign too (the turn here is untagged)."""
    root = tmp_path / "projects"
    sender = "dddddddd-0000-0000-0000-000000000004"  # in another project: outside the quote search
    write(root, sender, [bash(f'herdr agent prompt w1:p2 "{BRIEF}"', 8, session=sender)], proj="-elsewhere")
    write(root, ORCH, [asst("nothing relevant here", 1, session=ORCH)])
    write(root, WORKER, [typed(BRIEF, 10)])
    v = refs.check_quote(refs.resolve(ORCH, 1, roots=[root]), "do exactly what it says", roots=[root])
    assert (v.outcome, v.ref.session, v.ref.role) == ("other_session", WORKER, "agent")




def test_typed_turn_lines_leaves_out_turns_an_agent_wrote():
    entries = [typed("the person's first turn", 2), typed(TAGGED, 5), typed(BRIEF, 10), typed("ok, thanks", 12)]
    assert contract.typed_turn_lines(entries) == [1, 3, 4]
    sent = index((8, ORCH, f'herdr agent prompt w "{BRIEF}"'))
    assert contract.typed_turn_lines(entries, sent=sent) == [1, 4]


def test_roles_name_agent():
    assert "agent" in refs.ROLES


# ------------------------------------------------------------ the live miner


def _slice(path: Path) -> miner.SessionSlice:
    lines = path.read_text(encoding="utf-8").splitlines()
    return miner.SessionSlice(path=path, session_id=path.stem, project=path.parent.name, start_line=0, lines=lines)


def test_digest_labels_each_turn_by_who_wrote_it(tmp_path):
    headless = {"type": "user", "promptSource": "sdk", "message": {"role": "user", "content": "Summarise the changelog."}}
    path = write(tmp_path / "t", WORKER, [
        headless, typed("the person typed this", 2), typed(TAGGED, 4), typed(BRIEF, 10), asst("done", 11)])
    digest, halt = miner.digest_transcript(_slice(path))
    assert digest is not None and not halt
    assert "[relay L1] Summarise the changelog." in digest
    assert "[user L2] the person typed this" in digest
    assert "[agent L3] <agent-message>" in digest
    side = write(tmp_path / "t", "cccccccc-0000-0000-0000-000000000003", [typed("a sidechain turn", 3, isSidechain=True)])
    side_digest, _ = miner.digest_transcript(_slice(side))
    assert side_digest is not None and "[subagent L1] a sidechain turn" in side_digest
    assert f"[user L4] {BRIEF}" in digest  # positive control for the next line
    digest, _ = miner.digest_transcript(_slice(path), sent=index((8, ORCH, f'herdr agent prompt w "{BRIEF}"')))
    assert digest is not None and f"[agent L4] {BRIEF}" in digest


def test_the_reader_is_told_only_a_user_line_is_the_persons(tmp_path):
    prompt, _corrupt = miner._compose_prompt(make_home(tmp_path), ["(digest)"], tmp_path / "out.json")  # pyright: ignore[reportPrivateUsage]
    assert "Only a [user] line is the user's own words." in prompt
    rubric = " ".join(miner._rubric()[0].split())  # pyright: ignore[reportPrivateUsage]
    assert "Only a `[user]` line is the user's own words;" in rubric


def test_a_miner_run_sweeps_the_transcripts_for_sends(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    root = tmp_path / "transcripts"
    write(root, ORCH, [typed("send the brief to the worker", 1, session=ORCH),
                       bash(f'herdr agent prompt w1:p2 "{BRIEF}"', 8), asst("sent", 9, session=ORCH)])
    write(root, WORKER, [typed(BRIEF, 10), asst("reading the brief", 11)])
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    miner._save_cursors({"__initialized__": "test-fixture"})  # pyright: ignore[reportPrivateUsage]
    captured: dict = {}

    def fake(h, prompt):
        captured["prompt"] = prompt
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps({"candidates": [], "fires": []}), encoding="utf-8")
        return out

    monkeypatch.setattr(miner, "_invoke_reader", fake)
    result = miner.run(home)
    assert result.status == "ok"
    assert "[user L1] send the brief to the worker" in captured["prompt"]  # positive control
    assert f"[agent L1] {BRIEF}" in captured["prompt"]
    assert f"[user L1] {BRIEF}" not in captured["prompt"]
