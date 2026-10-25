"""Stored-citation recovery must preserve the file, row and evidence witness."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from self_learn import miner, refs, session_copies, steward_inputs, transcript_lines
from self_learn.mining import check, spine
from self_learn.records import Record
from test_transcript_lines import put, row


def test_fresh_checker_does_not_accept_legacy_row_as_exact(tmp_path):
    root, path = put(tmp_path, [row(1, "first\u2028turn"),
                               row(2, "please always run the linter"), {"type": "last-prompt"}])
    checker = check._Checker(spine.build_spine(spine.read_session(path), 1, 3),
                             [root], frozenset(), frozenset())
    good, _ = checker.quoted({"line": 2, "quote": "please always run the linter"})
    assert good["verdict"] == "exact"
    ref = refs.resolve("session", 3, roots=[root])
    assert refs.check_quote(ref, "please always run the linter", roots=[root], stored=False).outcome == "nearby"
    with pytest.raises(check._Fail, match="quote-not-found") as failure:
        checker.quoted({"line": 3, "quote": "please always run the linter"})
    assert "another role" in failure.value.detail


def test_checker_never_records_moved_exact_on_original_row(tmp_path, monkeypatch):
    root, path = put(tmp_path, [row(1, "opening"), row(2, "cited words"), row(3, "different words")])
    checker = check._Checker(spine.build_spine(spine.read_session(path), 1, 3),
                             [root], frozenset(), frozenset())
    target = refs.resolve("session", 2, roots=[root])
    monkeypatch.setattr(refs, "check_quote", lambda *a, **kw: refs.Verdict("exact", target))
    evidence, found = checker.quoted({"line": 3, "quote": "cited words"})
    assert found.line == evidence["ref"]["line"] == 2
    assert evidence["verdict"] == "nearby" and evidence["corrected_from"] == 3
    assert evidence["quote"] == "cited words"


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("has_uuid", [False, True])
def test_selected_copy_survives_every_read_and_pack(tmp_path, legacy, has_uuid):
    target = row(2, "intended words")
    if not has_uuid:
        target.pop("uuid")
    root, path = put(tmp_path / "a", [row(1, "a\u2028b"), target, row(3, "other")])
    other, _ = put(tmp_path / "b", [row(1, "elsewhere"), row(20, "wrong second"),
                                   row(30, "wrong third"), row(40, "longer copy")])
    roots = [other, root]
    line = 3 if legacy else 2
    stored = refs.Ref("session", "project", line, None, None, None, "user")
    resolved = refs.resolve("session", line, quote="intended words", roots=roots)
    assert resolved.line == 2 and refs.locate(resolved, roots=roots) == path
    assert refs.locate(stored, quote="intended words", roots=roots) == path
    followed = refs.follow(stored, quote="intended words", roots=roots)
    assert followed.uuid == ("u-2" if has_uuid else None)
    assert refs.locate(followed, roots=roots) == path
    assert refs.entry_text(stored, quote="intended words", roots=roots) == "intended words"
    assert refs.excerpt(stored, 0, 0, quote="intended words", roots=roots) == [(followed, "intended words")]
    verdict = refs.check_quote(stored, "intended words", roots=roots)
    assert (verdict.outcome, verdict.ref.line) == ("exact", 2)
    # Copy selection is transient; persisted refs keep their public schema.
    assert set(followed.to_dict()) == {"session", "project_dir", "line", "uuid", "entry_ts", "cwd", "role"}
    record = Record.create(type="behavior", scope="user", source="session", kind="anti-pattern",
                           trigger="Editing a file", instruction="Run the linter", evidence=[
                               {"origin": stored.origin, "quote": "intended words"}])
    items, stats = steward_inputs.evidence_pack(record, roots=roots, budget=10000)
    assert stats["items"] == stats["excerpted"] == 1
    assert items[0].verdict == "exact" and items[0].ref.line == 2
    assert next(text for ref, text in items[0].excerpt if ref.line == 2) == "intended words"


@pytest.mark.parametrize("api", ["entry_text", "excerpt", "check_quote"])
@pytest.mark.parametrize("quote", [None, "intended words"])
def test_missing_uuid_remains_unresolved(tmp_path, api, quote):
    root, _ = put(tmp_path, [row(1, "a\u2028b"), row(2, "intended words"), row(3, "different")])
    assert refs.resolve("session", uuid="u-2", roots=[root]).line == 2
    stored = refs.Ref("session", "project", 3, "missing", None, None, "user")
    with pytest.raises(refs.RefError):
        refs.resolve("session", 3, uuid="missing", roots=[root])
    with pytest.raises(refs.RefError):
        if api == "check_quote":
            refs.check_quote(stored, quote or "different", roots=[root])
        else:
            getattr(refs, api)(stored, quote=quote, roots=[root])


def test_uuid_at_preferred_row_wins_duplicate_uuid(tmp_path):
    root, _ = put(tmp_path, [row(1, "earlier copy"), row(1, "preferred copy")])
    ref = refs.resolve("session", 2, uuid="u-1", roots=[root])
    assert ref.line == 2 and refs.entry_text(ref, roots=[root]) == "preferred copy"


def test_legacy_cursor_keeps_truncation_overrun():
    rows = [json.dumps(row(1, "a\u2028b"), ensure_ascii=False), json.dumps(row(2, "tail"))]
    assert transcript_lines.legacy_cursor(rows, 3) == 2
    assert transcript_lines.legacy_cursor(rows, 7) == 6


def test_streaming_readers_keep_bare_cr_and_replacement_decoding(tmp_path):
    path = tmp_path / "session.jsonl"
    opening = miner.SELF_PROMPT_HEADERS[0]
    raw = json.dumps(row(1, opening)).replace(', "type"', ',\r"type"').encode()
    path.write_bytes(raw + b'\n' + json.dumps(row(2, "later")).encode() + b'\n')
    assert miner._first_user_text_of(miner._complete_lines(path)) == opening
    assert miner._first_user_text(path) == opening
    assert session_copies._counts(path) == ({"user": 2}, {})
    path.write_bytes(b'{"type":"user",\r"message":{"content":"replacement \xff"}}\n')
    assert miner._first_user_text(path) == "replacement \ufffd"
    assert session_copies._counts(path) == ({"user": 1}, {})


def test_marked_waiting_cursors_need_no_read_and_omit_false_halt(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "ledger"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    _, path = put(tmp_path, [row(1, "first"), row(2, "second")])
    current = {"lines": 2, "size": path.stat().st_size, "line_format": "newline-v1"}
    miner._save_cursors({str(path): current})
    assert miner._load_cursors()[str(path)] == current and path.is_file()
    reads = []
    original = miner._complete_lines
    monkeypatch.setattr(miner, "_complete_lines", lambda p: reads.append(p) or original(p))
    pending = SimpleNamespace(doc={"transcript": str(path), "cursor": dict(current, halt=False)})
    assert miner._settle_waiting_cursors([pending]) == 0
    assert reads == []
    miner._save_cursors({str(path): dict(current, lines=1)})
    assert miner._settle_waiting_cursors([pending]) == 1
    assert miner._load_cursors()[str(path)] == current
    assert reads == []


def test_fire_pack_follows_moment_uuid(tmp_path):
    root, _ = put(tmp_path, [row(1, "a\u2028b"), row(2, "the observed action"), row(3, "different action")])
    rendered, stats = steward_inputs.fire_pack([{
        "nonce": "synthetic-event", "origin": "transcript:session#L3",
        "moment": "u-2", "outcome": "suspected-violation"}], roots=[root], budget=10000)
    assert "event synthetic-event" in rendered and stats["excerpted"] == 1
    assert "ref: session session | folder project | line 2 | uuid u-2" in rendered


def test_null_quote_uses_verbatim_in_pack(tmp_path):
    root, _ = put(tmp_path, [row(1, "a\u2028b"), row(2, "stored words"), row(3, "wrong")])
    record = Record.create(type="behavior", scope="user", source="session", kind="anti-pattern",
                           trigger="Editing a file", instruction="Run the linter", evidence=[{
                               "origin": "transcript:session#L3", "quote": None, "verbatim": "stored words"}])
    items, stats = steward_inputs.evidence_pack(record, roots=[root], budget=10000)
    assert stats["items"] == stats["excerpted"] == 1
    assert items[0].verdict == "exact" and items[0].ref.line == 2
    assert items[0].quote == "stored words"


def test_locate_never_promises_a_row_past_eof(tmp_path):
    root, _ = put(tmp_path, [row(1, "real row")])
    ref = refs.resolve("session", 1, roots=[root])
    assert refs.entry_text(ref, roots=[root]) == "real row"
    stale = replace(ref, line=20)
    with pytest.raises(refs.RefError):
        refs.locate(stale, roots=[root])
    assert check._matches_raw("real row", stale, [root]) is False
    assert refs.entry_text(stale, roots=[root]) == "real row"
