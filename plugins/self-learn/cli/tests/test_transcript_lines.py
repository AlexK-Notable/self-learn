"""LF citations and cursor migration; all transcripts here are synthetic."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from self_learn import miner, refs, steward_inputs, transcript_lines
from self_learn.mining import check, compare, spine, tools


def row(n, text, role="user"):
    return {"uuid": f"u-{n}", "type": role, "message": {"content": text}}


def put(tmp_path, rows):
    root = tmp_path / "projects"
    path = root / "project" / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return root, path


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085", ""])
def test_physical_rows_reach_refs_spine_checker_and_comparison(tmp_path, separator):
    root, path = put(tmp_path, [row(1, "first" + separator + "turn"), row(2, "target"),
                                row(3, "last", "assistant")])
    found = refs.resolve("session", 2, roots=[root])
    assert (found.line, found.uuid, found.role) == (2, "u-2", "user")
    assert refs.entry_text(refs.resolve("session", 1, roots=[root]), roots=[root]) == "first" + separator + "turn"
    session = spine.read_session(path)
    assert len(session.lines) == 3 and session.entries[1]["uuid"] == "u-2"
    assert tools.read_entries(path)[1]["uuid"] == "u-2"
    sp = spine.build_spine(session, 2, 3)
    checker = check._Checker(sp, [root], frozenset(), frozenset())
    assert checker.resolve({"line": 2}).uuid == "u-2"
    info = compare.scan_file(path, [2])
    assert info.n_lines == 3 and info.at[2] == ("u-2", "user")


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
def test_old_citations_follow_quote_or_uuid_without_changing_history(tmp_path, separator):
    root, _ = put(tmp_path, [row(1, "a" + separator + "b"), row(2, "intended words"),
                             row(3, "wrong row", "assistant")])
    old_origin = "transcript:session#L3"
    intended = refs.resolve("session", 3, quote="intended words", roots=[root])
    assert (intended.line, intended.uuid, intended.role) == (2, "u-2", "user")
    assert refs.resolve("session", 3, uuid="u-2", roots=[root]) == intended
    # Neither match/no witness means the new truth; if both match new wins.
    assert refs.resolve("session", 3, roots=[root]).uuid == "u-3"
    assert refs.resolve("session", 3, quote="missing", roots=[root]).uuid == "u-3"
    assert refs.resolve("session", 3, quote="row", roots=[root]).uuid == "u-3"
    stored = replace(intended, line=3, role="assistant")
    before = stored.to_dict()
    assert refs.entry_text(stored, roots=[root]) == "intended words"
    assert refs.excerpt(stored, before=0, after=0, roots=[root]) == [(intended, "intended words")]
    assert refs.check_quote(stored, "intended words", roots=[root]).ref == intended
    assert stored.to_dict() == before
    for item in ({"origin": old_origin, "quote": "intended words"},
                 {"ref": old_origin, "quote": "intended words"},
                 {"source": {"message_ref": old_origin}, "verbatim": "intended words"},
                 {"ref": before, "quote": "intended words"}):
        snapshot = json.dumps(item, sort_keys=True)
        cited, followed, failed = steward_inputs._cited_ref(item, [root])
        assert cited == old_origin and followed == intended and failed == ""
        assert json.dumps(item, sort_keys=True) == snapshot
    # A legacy count can exceed EOF; UUID-less excerpts still use the quote.
    tail = refs.resolve("session", 4, quote="wrong row", roots=[root])
    assert tail.uuid == "u-3"
    old_tail = replace(tail, line=4, uuid=None)
    assert refs.excerpt(old_tail, before=0, after=0, quote="wrong row", roots=[root])[0][0].line == 3
    assert refs.entry_text(old_tail, quote="wrong row", roots=[root]) == "wrong row"
    # Both candidate rows hold this quote: prefer the newline row.
    put(tmp_path, [row(1, "a" + separator + "b"), row(2, "shared"), row(3, "shared", "assistant")])
    assert refs.resolve("session", 3, quote="shared", roots=[root]).uuid == "u-3"


def test_only_lf_ends_a_row_and_torn_tail_stays_unread(tmp_path):
    path = tmp_path / "session.jsonl"
    # Bare CR outside a JSON string is legal whitespace, not another line.
    path.write_bytes(b'{"type":"user",\r"uuid":"one"}\r\n{"uuid":"two"}\n{"uuid":')
    assert len(refs._lines(path)) == 3
    assert miner._complete_lines(path) == ['{"type":"user",\r"uuid":"one"}\r', '{"uuid":"two"}']
    assert refs._entry(refs._lines(path)[0])["uuid"] == "one"
    assert [e["uuid"] if e else None for e in tools.read_entries(path)] == ["one", "two", None]
    assert [e["uuid"] for e in tools.read_entries(path, end=1)] == ["one"]
    assert transcript_lines.split("") == []
    assert transcript_lines.split("\n\n") == ["", ""]
    path.write_bytes(b'{"uuid":"tail"}')
    assert len(refs._lines(path)) == 1
    assert miner._complete_lines(path) == []


def test_subagent_old_citation_follows_through_pack_and_excerpt(tmp_path):
    root, path = put(tmp_path, [row(1, "main session")])
    sub = path.parent / "session" / "subagents" / "agent-child.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in
                           [row(10, "first\u2028message"), row(11, "subagent report", "assistant")]))
    origin = "transcript:session/subagents/agent-child.jsonl#L3"
    cited, ref, failed = steward_inputs._cited_ref({"origin": origin, "quote": "subagent report"}, [root])
    assert cited == origin and failed == "" and ref is not None
    assert (ref.line, ref.uuid, ref.role, ref.subagent_file) == (2, "u-11", "subagent", "subagents/agent-child.jsonl")
    stored = replace(ref, line=3)
    assert refs.excerpt(stored, before=0, after=0, roots=[root]) == [(ref, "subagent report")]


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085", ""])
def test_legacy_walk_preserves_position_and_marks_new_advances(tmp_path, monkeypatch, separator):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "ledger"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    root, path = put(tmp_path, [row(1, "read" + separator + "already"), row(2, "also read")])
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    prefix = path.read_text()
    legacy = {"lines": len(prefix.splitlines()), "size": path.stat().st_size}
    miner._save_cursors({str(path): legacy})
    cursor_bytes = miner._cursors_path().read_bytes()
    assert miner.walk() == []  # positive control: existing prefix consumed
    with path.open("a") as fh:
        fh.write(json.dumps(row(3, "new turn")) + "\n" + '{"uuid":')
    (part,) = miner.walk()
    assert part.start_line == 2 and [json.loads(x)["uuid"] for x in part.lines] == ["u-3"]
    assert miner._cursors_path().read_bytes() == cursor_bytes  # read-time only
    miner._advance_cursors([(part, False)])
    saved = miner._load_cursors()[str(path)]
    assert saved["lines"] == 3 and saved["line_format"] == "newline-v1"
    with path.open("a") as fh:
        fh.write('"four"}\n')
    (part,) = miner.walk()
    assert part.start_line == 3 and len(part.lines) == 1 and json.loads(part.lines[0])["uuid"] == "four"
    # First activation writes new-format counts, too.
    miner.initialize_cursors()
    assert miner._load_cursors()[str(path)]["line_format"] == "newline-v1"
    assert miner.walk() == []


def test_waiting_replay_compares_converted_cursors_and_never_rewrites_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "ledger"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    root, path = put(tmp_path, [row(1, "a\u2028b\u2029c\u0085d"), row(2, "read"), row(3, "new")])
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    rows = miner._complete_lines(path)
    # Old current count 4 means physical row 1; new pending count 2 must advance.
    miner._save_cursors({str(path): {"lines": 4, "size": 1}})
    pending = {"transcript": str(path), "cursor": {"lines": 2, "size": 2, "halt": False,
                                                   "line_format": "newline-v1"}}
    before = json.dumps(pending)
    assert miner._settle_waiting_cursors([SimpleNamespace(doc=pending)]) == 1
    assert miner._load_cursors()[str(path)]["lines"] == 2
    assert json.dumps(pending) == before
    # Legacy pending count 5 is the SAME row 2, not row 5; must not advance.
    pending["cursor"] = {"lines": 5, "size": 2, "halt": False}
    assert miner._settle_waiting_cursors([SimpleNamespace(doc=pending)]) == 0
    (part,) = miner.walk()
    assert part.start_line == 2 and json.loads(part.lines[0])["uuid"] == "u-3"
    # Crash before either advance: the legacy pending answer alone restores row 2.
    miner._save_cursors({})
    assert miner._settle_waiting_cursors([SimpleNamespace(doc=pending)]) == 1
    saved = miner._load_cursors()[str(path)]
    assert (saved["lines"], saved["line_format"]) == (2, "newline-v1")
    assert miner._newline_cursor(saved, rows)["lines"] == 2
