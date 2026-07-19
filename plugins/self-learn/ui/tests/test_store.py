"""store.py — the pane transcript persistence store (task U22; 09 §11
Y-28, 10 §3 U22 row). Covers: incremental per-block append + flush (the
SIGKILL-survival property), read reconstruction, start_new archiving
(§6), continue_existing (resume, never archived), the size cap's
truncated marker (refuse-not-corrupt), corrupt/partial JSONL degradation
(fresh-start-not-500), retention pruning (age + byte bounds), and the
unwritable-cache-dir degradation leg. Also covers CacheSdkSessionStore's
append/load round-trip (Tier 2's duck-typed SessionStore adapter).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from self_learn_ui.store import (
    RETENTION_AGE_DAYS,
    RETENTION_BYTE_BOUND,
    SIZE_CAP_BYTES,
    CacheSdkSessionStore,
    PaneTranscriptStore,
    slug_for_session_key,
)


def _store(tmp_path: Path) -> PaneTranscriptStore:
    return PaneTranscriptStore(tmp_path / "panes")


# --------------------------------------------------------------- slugging


def test_slug_bare_record_id_passes_through() -> None:
    assert slug_for_session_key("lrn-aa000001") == "lrn-aa000001"


def test_slug_bucket_key_encoded() -> None:
    assert slug_for_session_key("bucket:project/foo") == "bucket__project__foo"


# ----------------------------------------------------------- write + read


def test_write_then_read_round_trips_blocks_and_result(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.start_new("lrn-aa000001", record_id_or_bucket="lrn-aa000001", bucket_dir=str(tmp_path / "bucket"))
    s.append_block("lrn-aa000001", kind="text", html="<p>hi</p>")
    s.append_block("lrn-aa000001", kind="tool", tool_name="Read", tool_target="/x/y")
    s.append_result(
        "lrn-aa000001",
        status="success",
        cost_usd=0.02,
        turns=3,
        error=None,
        cap_hit=False,
        session_id="sid-1",
    )

    snap = s.read_snapshot("lrn-aa000001")
    assert snap is not None
    assert [b.kind for b in snap.blocks] == ["text", "tool"]
    assert snap.blocks[0].html == "<p>hi</p>"
    assert snap.blocks[1].tool_name == "Read"
    assert snap.blocks[1].tool_target == "/x/y"
    assert snap.result is not None
    assert snap.result.status == "success"
    assert snap.result.session_id == "sid-1"
    assert snap.sdk_session_id == "sid-1"
    assert snap.bucket_dir == str(tmp_path / "bucket")
    assert snap.terminal_status is None
    assert snap.truncated is False
    assert snap.corrupt is False


def test_missing_file_reads_none(tmp_path: Path) -> None:
    s = _store(tmp_path)
    assert s.read_snapshot("lrn-never-opened") is None


def test_append_before_start_new_is_a_silent_no_op(tmp_path: Path) -> None:
    """A caller invariant violation (append without a header) degrades
    silently — never raises — per Y-28 §7."""
    s = _store(tmp_path)
    s.append_block("lrn-orphan", kind="text", html="x")
    assert s.read_snapshot("lrn-orphan") is None


# ---------------------------------------------- SIGKILL / no-flush-hook leg


def test_sigkill_leg_finalized_blocks_survive_a_fresh_store_instance(tmp_path: Path) -> None:
    """The load-bearing durability test (Y-28 §7 MUST): drop the writer
    with NO close/shutdown/flush call — a bare Python object drop is the
    closest unit-test analog to SIGKILL/exit-143 (no teardown, no flush
    hook fires) — and a FRESH store instance over the SAME dir must still
    reconstruct every block that was appended. This is the test that
    would fail if durability were buffer-and-flush-at-teardown rather
    than per-block append+flush()."""
    panes_dir = tmp_path / "panes"
    writer = PaneTranscriptStore(panes_dir)
    writer.start_new("lrn-aa000001", record_id_or_bucket="lrn-aa000001", bucket_dir="/x")
    writer.append_block("lrn-aa000001", kind="text", html="<p>one</p>")
    writer.append_block("lrn-aa000001", kind="tool", tool_name="Edit", tool_target="/x/f.md")
    del writer  # no shutdown/close/flush call anywhere — simulates SIGKILL

    reader = PaneTranscriptStore(panes_dir)
    snap = reader.read_snapshot("lrn-aa000001")
    assert snap is not None
    assert [b.kind for b in snap.blocks] == ["text", "tool"]
    assert snap.blocks[0].html == "<p>one</p>"


# --------------------------------------------------------- start-fresh / resume


def test_start_new_archives_prior_transcript(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.start_new("lrn-a", record_id_or_bucket="lrn-a", bucket_dir="/x")
    s.append_block("lrn-a", kind="text", html="first life")
    s.start_new("lrn-a", record_id_or_bucket="lrn-a", bucket_dir="/x")

    fresh = s.read_snapshot("lrn-a")
    assert fresh is not None and len(fresh.blocks) == 0
    archived = list((tmp_path / "panes" / "archive").glob("*.jsonl"))
    assert len(archived) == 1
    assert "first life" in archived[0].read_text(encoding="utf-8")


def test_continue_existing_never_archives(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.start_new("lrn-a", record_id_or_bucket="lrn-a", bucket_dir="/x")
    s.append_block("lrn-a", kind="text", html="turn one")
    s.continue_existing("lrn-a")
    s.append_block("lrn-a", kind="text", html="turn two")

    snap = s.read_snapshot("lrn-a")
    assert snap is not None
    assert [b.html for b in snap.blocks] == ["turn one", "turn two"]
    assert not (tmp_path / "panes" / "archive").is_dir() or not list(
        (tmp_path / "panes" / "archive").glob("*.jsonl")
    )


def test_continue_existing_on_a_never_opened_key_starts_one_defensively(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.continue_existing("lrn-never-seen")
    s.append_block("lrn-never-seen", kind="text", html="ok")
    snap = s.read_snapshot("lrn-never-seen")
    assert snap is not None and len(snap.blocks) == 1


# --------------------------------------------------------------- size cap


def test_size_cap_writes_truncated_marker_and_never_raises(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.start_new("lrn-big", record_id_or_bucket="lrn-big", bucket_dir="/x")
    chunk = "x" * 5000
    for _ in range(SIZE_CAP_BYTES // 5000 + 5):
        s.append_block("lrn-big", kind="text", html=chunk)  # must never raise

    snap = s.read_snapshot("lrn-big")
    assert snap is not None
    assert snap.truncated is True
    path = tmp_path / "panes" / "lrn-big.jsonl"
    assert path.stat().st_size <= SIZE_CAP_BYTES + 5000  # one marker line over the cap, bounded


def test_size_cap_stops_appending_further_lines_once_capped(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.start_new("lrn-big2", record_id_or_bucket="lrn-big2", bucket_dir="/x")
    chunk = "x" * 5000
    for _ in range(SIZE_CAP_BYTES // 5000 + 5):
        s.append_block("lrn-big2", kind="text", html=chunk)
    size_at_cap = (tmp_path / "panes" / "lrn-big2.jsonl").stat().st_size
    s.append_block("lrn-big2", kind="text", html="more after cap")
    assert (tmp_path / "panes" / "lrn-big2.jsonl").stat().st_size == size_at_cap


# ------------------------------------------------------- corrupt/degraded


def test_corrupt_line_yields_valid_prefix_and_corrupt_flag(tmp_path: Path) -> None:
    panes_dir = tmp_path / "panes"
    panes_dir.mkdir(parents=True)
    path = panes_dir / "lrn-bad.jsonl"
    path.write_text(
        json.dumps({"t": "header", "schema": 1, "session_key": "lrn-bad", "bucket_dir": "/x"}) + "\n"
        + json.dumps({"t": "block", "kind": "text", "html": "ok"}) + "\n"
        + "NOT JSON AT ALL\n"
    )
    s = _store(tmp_path)
    snap = s.read_snapshot("lrn-bad")
    assert snap is not None
    assert snap.corrupt is True
    assert len(snap.blocks) == 1
    assert snap.blocks[0].html == "ok"


def test_missing_header_treated_as_no_history(tmp_path: Path) -> None:
    panes_dir = tmp_path / "panes"
    panes_dir.mkdir(parents=True)
    (panes_dir / "lrn-nohdr.jsonl").write_text(json.dumps({"t": "block", "kind": "text", "html": "x"}) + "\n")
    s = _store(tmp_path)
    snap = s.read_snapshot("lrn-nohdr")
    assert snap is None


def test_wrong_schema_version_treated_as_corrupt_no_history(tmp_path: Path) -> None:
    panes_dir = tmp_path / "panes"
    panes_dir.mkdir(parents=True)
    (panes_dir / "lrn-oldschema.jsonl").write_text(
        json.dumps({"t": "header", "schema": 999, "session_key": "lrn-oldschema"}) + "\n"
    )
    s = _store(tmp_path)
    assert s.read_snapshot("lrn-oldschema") is None


def test_empty_file_treated_as_no_history(tmp_path: Path) -> None:
    panes_dir = tmp_path / "panes"
    panes_dir.mkdir(parents=True)
    (panes_dir / "lrn-empty.jsonl").write_text("")
    s = _store(tmp_path)
    assert s.read_snapshot("lrn-empty") is None


# --------------------------------------------------------- unwritable dir


def test_unwritable_cache_dir_disables_persistence_never_raises(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    os.chmod(blocked, 0o400)
    try:
        s = PaneTranscriptStore(blocked / "panes")
        s.start_new("lrn-x", record_id_or_bucket="lrn-x", bucket_dir="/x")  # must not raise
        assert s.enabled is False  # discovered lazily, on the first real write attempt
        s.append_block("lrn-x", kind="text", html="y")  # must not raise
        assert s.read_snapshot("lrn-x") is None
    finally:
        os.chmod(blocked, 0o700)


def test_enabled_true_until_first_write_attempted(tmp_path: Path) -> None:
    """Laziness pin: `enabled` is optimistic pre-write — a store whose
    dir was never touched (e.g. constructed but never used, the
    create_app()-time case) has made no claim about writability yet."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    os.chmod(blocked, 0o400)
    try:
        s = PaneTranscriptStore(blocked / "panes")
        assert s.enabled is True  # nothing tried yet
        assert s.read_snapshot("lrn-never-touched") is None  # a pure read: never mkdirs
        assert s.enabled is True  # still untested — read_snapshot never calls _ensure_dir
    finally:
        os.chmod(blocked, 0o700)


def test_lazy_callable_panes_dir_not_resolved_until_first_real_touch(tmp_path: Path) -> None:
    """The production wiring (pane.build_pane_manager) passes a zero-arg
    callable so cache_dir() is never resolved at create_app() time —
    this pins that a bare construction resolves nothing."""
    calls = []

    def resolver() -> Path:
        calls.append(1)
        return tmp_path / "lazily-resolved-panes"

    s = PaneTranscriptStore(resolver)
    assert calls == []  # constructing the store must not resolve the path
    assert s.read_snapshot("lrn-x") is None  # a read resolves it (needs the path to check)
    assert calls == [1]
    assert s.read_snapshot("lrn-y") is None  # resolved once, cached thereafter
    assert calls == [1]


# ------------------------------------------------------------- retention


def test_prune_by_age_evicts_stale_files(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.start_new("lrn-old", record_id_or_bucket="lrn-old", bucket_dir="/x")
    path = tmp_path / "panes" / "lrn-old.jsonl"
    old_time = time.time() - (RETENTION_AGE_DAYS + 1) * 86400
    os.utime(path, (old_time, old_time))
    s.prune()
    assert not path.is_file()


def test_prune_by_age_keeps_fresh_files(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.start_new("lrn-fresh", record_id_or_bucket="lrn-fresh", bucket_dir="/x")
    s.prune()
    assert (tmp_path / "panes" / "lrn-fresh.jsonl").is_file()


def test_prune_by_bytes_evicts_oldest_first(tmp_path: Path) -> None:
    s = _store(tmp_path)
    big_html = "x" * (300 * 1024)
    for i in range(3):
        key = f"lrn-{i:08d}"
        s.start_new(key, record_id_or_bucket=key, bucket_dir="/x")
        s.append_block(key, kind="text", html=big_html)
        time.sleep(0.01)

    # Force the total over the byte bound artificially by monkeypatching
    # the constant would require importing module internals; instead
    # shrink the effective bound by writing enough data directly.
    import self_learn_ui.store as store_mod

    original_bound = store_mod.RETENTION_BYTE_BOUND
    try:
        store_mod.RETENTION_BYTE_BOUND = 400 * 1024  # smaller than all 3 files combined
        s.prune()
    finally:
        store_mod.RETENTION_BYTE_BOUND = original_bound

    remaining = sorted((tmp_path / "panes").glob("lrn-*.jsonl"))
    # The oldest (lrn-00000000) should be evicted first.
    assert not (tmp_path / "panes" / "lrn-00000000.jsonl").is_file()
    assert (tmp_path / "panes" / "lrn-00000002.jsonl").is_file()


# ------------------------------------------------------ CacheSdkSessionStore


async def test_sdk_session_store_append_then_load_round_trips(tmp_path: Path) -> None:
    adapter = CacheSdkSessionStore(tmp_path / "sdk-sessions")
    key = {"project_key": "/home/x/proj", "session_id": "sess-1"}
    await adapter.append(key, [{"type": "assistant", "uuid": "u1"}, {"type": "user", "uuid": "u2"}])
    loaded = await adapter.load(key)
    assert loaded == [{"type": "assistant", "uuid": "u1"}, {"type": "user", "uuid": "u2"}]


async def test_sdk_session_store_load_unknown_key_returns_none(tmp_path: Path) -> None:
    adapter = CacheSdkSessionStore(tmp_path / "sdk-sessions")
    loaded = await adapter.load({"project_key": "p", "session_id": "never-appended"})
    assert loaded is None


async def test_sdk_session_store_project_key_sanitized_to_safe_path(tmp_path: Path) -> None:
    """project_key defaults to a sanitized cwd per the SDK's own
    docstring — this adapter must never let arbitrary characters (path
    separators, etc.) escape the root dir."""
    adapter = CacheSdkSessionStore(tmp_path / "sdk-sessions")
    key = {"project_key": "/etc/../weird key!!", "session_id": "sess-2"}
    await adapter.append(key, [{"type": "x"}])
    loaded = await adapter.load(key)
    assert loaded == [{"type": "x"}]
    # Nothing escaped the root.
    for p in (tmp_path / "sdk-sessions").rglob("*.jsonl"):
        assert (tmp_path / "sdk-sessions") in p.resolve().parents


# --------------------------------------------------------------------
# U22-fix (live-DoD BLOCKER, 2026-07-19): materialize_resume_session()
# ONLY calls SessionStore.list_subkeys() when the SDK's OWN
# _store_implements() probe reports the store overrides it — and that
# probe compares method objects by IDENTITY against SessionStore's own
# default, NOT by calling the method. A store that defines its own
# `list_subkeys` stub (even one that just `raise NotImplementedError`)
# therefore reads as "implemented," and materialize_resume_session then
# calls it and gets a genuine NotImplementedError — surfacing to the
# human as exactly the live-trial failure text. These tests drive the
# REAL SDK functions (imported as shipped, never reimplemented) against
# CacheSdkSessionStore to pin the fix at the boundary that actually
# broke, not just at a unit level.
# --------------------------------------------------------------------


def test_store_implements_reports_false_for_undefined_optional_methods() -> None:
    """The root-cause pin: CacheSdkSessionStore must NOT override
    list_sessions/list_session_summaries/delete/list_subkeys — inherited
    unchanged from SessionStore, so the SDK's own identity-based
    _store_implements() probe reads them as absent. append/load ARE
    overridden and must read as present."""
    from claude_agent_sdk._internal.session_store_validation import _store_implements

    adapter = CacheSdkSessionStore(Path("/tmp/does-not-need-to-exist"))
    assert _store_implements(adapter, "append") is True
    assert _store_implements(adapter, "load") is True
    assert _store_implements(adapter, "list_sessions") is False
    assert _store_implements(adapter, "list_session_summaries") is False
    assert _store_implements(adapter, "delete") is False
    assert _store_implements(adapter, "list_subkeys") is False


async def test_real_sdk_materialize_resume_session_succeeds_multi_turn(tmp_path: Path) -> None:
    """Drives claude_agent_sdk's REAL materialize_resume_session() (the
    exact function the live-trial Resume click ran into) against a
    CacheSdkSessionStore mirroring a MULTI-TURN session (three append
    batches, mimicking three turns' worth of transcript entries) —
    reproduces the live failure shape when reverted (see the module
    docstring above) and pins the fix: materialization must succeed and
    write a resumable temp CLAUDE_CONFIG_DIR with the full merged
    transcript.

    KILL-VERIFY (manual, recorded in the U22-fix report): reintroducing
    a `list_subkeys` stub that raises NotImplementedError on
    CacheSdkSessionStore reddens this test with
    'SessionStore.list_subkeys() for session <id> failed during resume
    materialization:' — the exact live-trial alert text.
    """
    import uuid

    from claude_agent_sdk import ClaudeAgentOptions
    from claude_agent_sdk._internal.session_resume import materialize_resume_session
    from claude_agent_sdk._internal.sessions import project_key_for_directory

    store = CacheSdkSessionStore(tmp_path / "sdk-sessions")
    session_id = str(uuid.uuid4())
    cwd = tmp_path / "bucket"
    cwd.mkdir()
    project_key = project_key_for_directory(str(cwd))
    key = {"project_key": project_key, "session_id": session_id}

    # Three turns' worth of mirrored entries, appended in separate
    # batches (matching the SDK's own ~100ms-cadence append() calls
    # during a real streaming session — never one giant batch).
    await store.append(key, [{"type": "user", "uuid": "turn1-u", "message": "hello"}])
    await store.append(key, [{"type": "assistant", "uuid": "turn1-a", "message": "hi there"}])
    await store.append(key, [{"type": "user", "uuid": "turn2-u", "message": "continue"}])
    await store.append(key, [{"type": "assistant", "uuid": "turn2-a", "message": "continuing"}])
    await store.append(key, [{"type": "user", "uuid": "turn3-u", "message": "one more"}])
    await store.append(key, [{"type": "assistant", "uuid": "turn3-a", "message": "done"}])

    options = ClaudeAgentOptions(cwd=str(cwd), session_store=store, resume=session_id)
    result = await materialize_resume_session(options)  # must NOT raise RuntimeError

    assert result is not None
    assert result.resume_session_id == session_id
    assert result.config_dir.is_dir()
    materialized = list((result.config_dir / "projects").rglob(f"{session_id}.jsonl"))
    assert len(materialized) == 1
    lines = materialized[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6  # all three turns' worth of entries, in order
    uuids = [json.loads(line)["uuid"] for line in lines]
    assert uuids == ["turn1-u", "turn1-a", "turn2-u", "turn2-a", "turn3-u", "turn3-a"]

    await result.cleanup()
    assert not result.config_dir.exists()


async def test_real_sdk_materialize_resume_session_none_for_never_appended_key(tmp_path: Path) -> None:
    """An honest 'nothing to resume' — no entries for the id — falls
    through to None (the SDK's own documented degrade), never raises."""
    import uuid

    from claude_agent_sdk import ClaudeAgentOptions
    from claude_agent_sdk._internal.session_resume import materialize_resume_session

    store = CacheSdkSessionStore(tmp_path / "sdk-sessions")
    cwd = tmp_path / "bucket"
    cwd.mkdir()
    options = ClaudeAgentOptions(cwd=str(cwd), session_store=store, resume=str(uuid.uuid4()))
    result = await materialize_resume_session(options)
    assert result is None
