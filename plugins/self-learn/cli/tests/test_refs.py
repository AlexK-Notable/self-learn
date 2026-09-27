"""U1 · the checked pointer (``self_learn.refs``; 02-schema.md "Transcript refs").

Synthetic transcripts only, written under ``tmp_path``: no real session
content belongs in this public repository. The fake secret is assembled
at run time so no literal in this file is secret-shaped.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from self_learn import refs
from self_learn.refs import Ref, RefError

SID = "11111111-2222-3333-4444-555555555555"
FORK = "66666666-7777-8888-9999-000000000000"
OTHER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
REPO = "-work-repo"
WT = "-work-repo--claude-worktrees-lane"


# ------------------------------------------------------------ builders


def _ts(n: int) -> str:
    return f"2026-09-01T10:{n // 60:02d}:{n % 60:02d}.000Z"


def user(text, n, **extra):
    e = {"type": "user", "uuid": f"u-{n}", "timestamp": _ts(n), "cwd": "/work/repo",
         "message": {"role": "user", "content": text}}
    e.update(extra)
    return e


def typed(text, n):
    return user(text, n, origin={"kind": "human"}, promptSource="typed")


def asst(text, n, **extra):
    e = {"type": "assistant", "uuid": f"a-{n}", "timestamp": _ts(n), "cwd": "/work/repo",
         "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    e.update(extra)
    return e


def result(text, n):
    return user([{"type": "tool_result", "tool_use_id": f"t{n}", "content": text}], n)


def filler(n):
    return asst(f"filler entry number {n}", n)


def write(root: Path, proj: str, session: str, entries: list, *, sub: str | None = None) -> Path:
    d = root / proj
    path = d / f"{session}.jsonl" if sub is None else d / session / "subagents" / sub
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


@pytest.fixture
def roots(tmp_path):
    return [tmp_path / "projects", tmp_path / "archive"]


# --------------------------------------------------------------- roles


def test_every_role_including_relay_and_subagent(roots):
    entries = [
        typed("please rename the module", 1),                                   # L1 user (marker)
        asst("renaming it now", 2),                                             # L2 assistant
        result("renamed 3 files", 3),                                           # L3 tool_result
        user("<task-notification>agent done</task-notification>", 4,
             origin={"kind": "task-notification"}, promptSource="system"),      # L4 relay (origin.kind)
        user("skill body text", 5, isMeta=True),                                # L5 relay (isMeta)
        user("summary of the earlier conversation", 6, isCompactSummary=True),  # L6 relay
        user("a program's prompt", 7, promptSource="sdk"),                      # L7 relay (promptSource)
        user("<local-command-stdout>Compacted</local-command-stdout>", 8),      # L8 relay (envelope)
        user("an older typed turn with no marker", 9),                          # L9 user (structural)
        {"type": "attachment", "uuid": "at-10", "timestamp": _ts(10),
         "attachment": {"type": "queued_command", "prompt": "also do the docs",
                        "origin": {"kind": "human"}}},                          # L10 user (queued)
        {"type": "attachment", "uuid": "at-11", "timestamp": _ts(11),
         "attachment": {"type": "total_tokens_reminder", "content": "tokens"}},  # L11 relay
        asst("sidechain text", 12, isSidechain=True),                            # L12 subagent
        user("a coordinator's message", 13, origin={"kind": "coordinator"}),     # L13 relay
    ]
    write(roots[0], REPO, SID, entries)
    want = ["user", "assistant", "tool_result", "relay", "relay", "relay", "relay", "relay",
            "user", "user", "relay", "subagent", "relay"]
    got = [refs.resolve(SID, i, roots=roots).role for i in range(1, len(entries) + 1)]
    assert got == want
    # entry text of attachments: the queued prompt, the reminder content
    assert refs.entry_text(refs.resolve(SID, 10, roots=roots), roots=roots) == "also do the docs"
    assert refs.check_quote(refs.resolve(SID, 11, roots=roots), "tokens", roots=roots).outcome == "exact"

    write(roots[0], REPO, SID, [asst("inside the subagent", 1)], sub="agent-abc.jsonl")
    sub = refs.resolve(SID, 1, subagent_file="subagents/agent-abc.jsonl", roots=roots)
    assert (sub.role, sub.subagent_file, sub.project_dir) == ("subagent", "subagents/agent-abc.jsonl", REPO)
    # found by uuid alone when no top-level copy holds it
    assert refs.resolve(SID, uuid="a-1", roots=roots).subagent_file == "subagents/agent-abc.jsonl"


def test_ref_fields_come_from_the_entry_and_round_trip(roots):
    write(roots[0], REPO, SID, [filler(1), typed("the typed turn", 7)])
    ref = refs.resolve(SID, 2, roots=roots)
    assert (ref.uuid, ref.entry_ts, ref.cwd, ref.project_dir, ref.line) == ("u-7", _ts(7), "/work/repo", REPO, 2)
    assert Ref.from_dict(json.loads(json.dumps(ref.to_dict()))) == ref
    assert ref.origin == f"transcript:{SID}#L2"
    with pytest.raises(ValueError):
        Ref(SID, REPO, 1, None, None, None, "person")


# ------------------------------------------------------------ resolver


def test_resolver_picks_the_real_file_over_a_stub(roots):
    write(roots[0], REPO, SID, [{"type": "bridge-session", "sessionId": SID}])  # 1-line stub
    write(roots[0], WT, SID, [filler(i) for i in range(1, 11)])                  # the real file
    assert refs.resolve(SID, 5, roots=roots).project_dir == WT
    assert refs.resolve(SID, roots=roots).project_dir == WT  # no line: the largest
    assert refs.resolve(SID, uuid="a-9", roots=roots).line == 9
    with pytest.raises(RefError):
        refs.resolve(SID, 50, roots=roots)
    with pytest.raises(RefError):
        refs.resolve("99999999-0000-0000-0000-000000000000", 1, roots=roots)


def test_resolver_prefers_the_copy_holding_the_uuid_then_the_earlier_root(roots):
    entries = [filler(i) for i in range(1, 6)]
    write(roots[1], WT, SID, entries)                         # archive copy, another folder
    write(roots[0], REPO, SID, entries)                       # same-size live copy
    assert refs.resolve(SID, 3, roots=roots).project_dir == REPO  # earlier root wins the tie
    # a larger copy that does NOT hold the uuid loses to one that does
    write(roots[0], WT, SID, [filler(i) for i in range(100, 130)])
    ref = refs.resolve(SID, 3, uuid="a-3", roots=roots)
    assert (ref.project_dir, ref.line) == (REPO, 3)


def test_transcript_roots_is_a_registry_setting(monkeypatch, tmp_path):
    default = refs.transcript_roots(tmp_path)
    assert default == [Path("~/.claude/projects").expanduser(), Path("~/.claude/archive/sessions").expanduser()]
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPT_ROOTS", os.pathsep.join(["/x/one", "~/two"]))
    assert refs.transcript_roots(tmp_path) == [Path("/x/one"), Path("~/two").expanduser()]


# --------------------------------------------------------- quote check


@pytest.fixture
def session(roots):
    entries = [filler(i) for i in range(1, 121)]
    entries[9] = asst("The build “failed” because the `cache` was **stale** — twice.", 10)
    entries[12] = asst("the retry loop never stopped on its own", 13)
    entries[79] = asst("nobody checked the lock file before merging", 80)
    entries[99] = asst("First part of a longer thought, then more words.", 100)
    entries[104] = asst("A second part that sits somewhere else.", 105)
    write(roots[0], REPO, SID, entries)
    return refs.resolve(SID, 10, roots=roots)


def test_exact_and_normalised(session, roots):
    v = refs.check_quote(session, "because the `cache` was **stale**", roots=roots)
    assert (v.outcome, v.ref) == ("exact", session)
    v = refs.check_quote(session, 'the build "failed" because   the cache was stale - twice', roots=roots)
    assert (v.outcome, v.ref) == ("normalised", session)
    # a changed word never normalises
    assert refs.check_quote(session, "the build failed because the cache was old", roots=roots).outcome == "not_found"


def test_nearby_and_elsewhere_return_corrected_refs(session, roots):
    v = refs.check_quote(session, "the retry loop never stopped", roots=roots)
    assert (v.outcome, v.ref.line, v.ref.uuid) == ("nearby", 13, "a-13")
    v = refs.check_quote(session, "nobody checked the lock file", roots=roots)
    assert (v.outcome, v.ref.line) == ("elsewhere_in_file", 80)


def test_stitched(session, roots):
    v = refs.check_quote(session, "First part of a longer thought… A second part that sits", roots=roots)
    assert v.outcome == "stitched"
    assert [p.line for p in v.pieces] == [100, 105]
    # "..." counts too; a piece found nowhere makes it not_found
    assert refs.check_quote(session, "First part of a longer thought... sits somewhere else", roots=roots).outcome == "stitched"
    assert refs.check_quote(session, "First part of a longer thought... an invented tail", roots=roots).outcome == "not_found"


def test_other_session_in_the_project_family_ignores_tool_result_echoes(session, roots):
    write(roots[0], WT, OTHER, [filler(1), asst("the flag was set in the wrong session", 2)])
    v = refs.check_quote(session, "the flag was set in the wrong session", roots=roots)
    assert (v.outcome, v.ref.session, v.ref.line, v.ref.project_dir) == ("other_session", OTHER, 2, WT)
    # a later session that merely READ the quote back (a tool result) is not the moment
    write(roots[0], REPO, FORK, [result("pending: the user said a phrase nobody said here", 1)])
    assert refs.check_quote(session, "a phrase nobody said here", roots=roots).outcome == "not_found"
    # outside the family: never searched
    write(roots[0], "-elsewhere", "bbbbbbbb-0000-0000-0000-000000000000", [asst("an unrelated project line", 1)])
    assert refs.check_quote(session, "an unrelated project line", roots=roots).outcome == "not_found"
    # the cap bounds the search
    assert refs.check_quote(session, "the flag was set in the wrong session", roots=roots,
                            other_session_cap=0).outcome == "not_found"


# ---------------------------------------------------------- duplicates


def test_same_uuid_in_a_forked_copy_is_one_moment(roots):
    shared = typed("the moment both files copy", 5)
    write(roots[0], REPO, SID, [filler(1), filler(2), shared])
    write(roots[0], REPO, FORK, [filler(3), shared])
    a, b = refs.resolve(SID, 3, roots=roots), refs.resolve(FORK, 2, roots=roots)
    other = refs.resolve(SID, 1, roots=roots)
    assert a != b and refs.same_moment(a, b) and not refs.same_moment(a, other)
    assert refs.dedupe([a, other, b]) == [a, other]
    no_uuid = Ref(SID, REPO, 1, None, None, None, "relay")
    assert not refs.same_moment(no_uuid, no_uuid)
    assert refs.dedupe([no_uuid, no_uuid]) == [no_uuid, no_uuid]


# ------------------------------------------------------------- excerpt


def test_excerpt_bounds(roots):
    entries = [asst(f"entry {i}", i) for i in range(1, 21)]
    entries[8] = {"type": "last-prompt", "uuid": "lp"}           # L9: no text, skipped
    entries[9] = asst("long words " * 500, 10)                           # L10: the ref, long
    write(roots[0], REPO, SID, entries)
    ref = refs.resolve(SID, 10, roots=roots)
    got = refs.excerpt(ref, before=2, after=3, entry_chars=100, total_chars=10_000, roots=roots)
    assert [r.line for r, _ in got] == [7, 8, 10, 11, 12, 13]
    assert got[2][0] == ref and "…[clipped]…" in got[2][1] and len(got[2][1]) <= 100
    assert all(r.role == "assistant" for r, _ in got)
    small = refs.excerpt(ref, before=2, after=3, entry_chars=100, total_chars=115, roots=roots)
    assert [r.line for r, _ in small] == [10, 11, 12]  # farthest dropped first, the ref kept


def test_secret_in_an_entry_comes_back_redacted(roots):
    token = "ghp_" + "Zq9" * 12
    write(roots[0], REPO, SID, [filler(1), result(f"env dump: GH={token} done", 2), filler(3)])
    ref = refs.resolve(SID, 2, roots=roots)
    texts = [t for _, t in refs.excerpt(ref, 1, 1, roots=roots)]
    assert any("env dump" in t for t in texts)  # positive control: the entry is there
    assert not any(token in t for t in texts)
    assert "[redacted:github-token]" in texts[1]
    assert token not in refs.entry_text(ref, roots=roots)
    assert refs.check_quote(ref, "env dump", roots=roots).outcome == "exact"  # matching uses raw text
