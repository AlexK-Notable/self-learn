"""Sprint 2 M-V (sdk-lifecycle, 2026-09-04) -- delegation parity for
`invocation_sdk.lifecycle`/`invocation_sdk.events` over
`sdksession.children`/`sdksession.events`.

New file: imports nothing from an armor-pinned test file (this repo's
`CLAUDE.md` lists `support.py`/`conftest.py`/`backends.py`/
`test_invocation.py`/`test_worker.py`/`test_repair.py`/`test_attrib.py`/
`test_route_cli.py`/`test_composer.py`/`test_u_fake.py`, plus
`test_invocation_sdk.py` itself as Behaviour-pinned) -- only production
modules are imported here.

Each test below drives the PRODUCTION `invocation_sdk` adapter function
and the PRODUCTION `sdksession` library function it now delegates to,
side by side, against the SAME `worker.cache_dir()`, and asserts the
files they produce are byte-identical (not merely "equal after
parsing") and at the path the pre-move implementation would have used
(`_sidecar_path`/`_event_log_path`, still pinned by other tests). This
is also the mutation witness the build report cites: if
`invocation_sdk/events.py`'s hardcoded `log_kind="tool-events"` drifted
to a different literal, `_event_log_path`'s hardcoded `"tool-events"`
segment would no longer match what the adapter actually wrote, and the
byte/path comparisons below would fail outright (`FileNotFoundError` or
a stale-file mismatch) rather than silently passing. The companion
witness -- restoring a direct `write_text`/`unlink` call in
`invocation_sdk/lifecycle.py` reddens `test_pl3` -- lives in
`test_invocation_sdk.py`'s own retargeted node and is verified by
mutation in the build report, not duplicated here.
"""

from __future__ import annotations

import os
from pathlib import Path

from self_learn import worker
from self_learn.invocation_sdk import events as events_mod
from self_learn.invocation_sdk import lifecycle as lifecycle_mod
from self_learn.sdksession import children as sdk_children
from self_learn.sdksession import events as sdk_events


def _make_home(tmp_path: Path, monkeypatch, name: str) -> Path:
    """Same convention `test_invocation_sdk.py`'s `EV5`/`EV6` setup
    uses: an explicit, existing home plus an explicit cache namespace,
    so `worker.cache_dir()` resolves somewhere this test controls."""
    home = tmp_path / f"{name}-home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / f"{name}-xdg"))
    return home


# ===================================================================== #
# Sidecar: `lifecycle.write_sidecar/read_sidecar/clear_sidecar` (the
# adapter) vs. `sdksession.children`'s functions (the library), called
# directly, against the same cache dir.
# ===================================================================== #


def test_sidecar_adapter_matches_the_library_called_directly_byte_for_byte(tmp_path, monkeypatch):
    _make_home(tmp_path, monkeypatch, "sidecar")
    cache = worker.cache_dir()
    monkeypatch.setattr(sdk_children.time, "time", lambda: 1_726_000_000.0)

    # via the adapter (invocation_sdk.lifecycle)
    lifecycle_mod.write_sidecar("surf-a", 4242, "claude")
    path_a = lifecycle_mod._sidecar_path("surf-a")

    # via the library, called directly, same inputs, a different
    # surface (so both files exist at once and neither call clobbers
    # the other's path).
    sdk_children.write_sidecar(cache, "surf-b", 4242, "claude")
    path_b = sdk_children.sidecar_path(cache, "surf-b")

    # Paths: the adapter's own path helper agrees with the library's
    # unkeyed path formula (F-2's `session_key=None` shape).
    assert path_a == sdk_children.sidecar_path(cache, "surf-a")

    # Bytes: with `started_at` frozen, the SAME pid/cli produce
    # byte-identical JSON regardless of which entry point wrote it --
    # the adapter's write IS the library's write, not a parallel
    # reimplementation that happens to agree today.
    assert path_a.read_bytes() == path_b.read_bytes()

    # Read: the adapter reads back exactly what it wrote, and reads
    # back exactly what the library wrote directly at the SAME
    # (unkeyed) path formula.
    expected = {"pid": 4242, "started_at": 1_726_000_000.0, "cli": "claude"}
    assert lifecycle_mod.read_sidecar("surf-a") == expected
    assert sdk_children.read_sidecar(cache, "surf-b") == expected
    assert lifecycle_mod.read_sidecar("surf-b") == expected  # cross-entry-point read

    # Clear: the adapter's unlink is the library's unlink -- one clears
    # via each entry point, both files are gone.
    lifecycle_mod.clear_sidecar("surf-a")
    assert not path_a.exists()
    sdk_children.clear_sidecar(cache, "surf-b")
    assert not path_b.exists()


# ===================================================================== #
# Event log: `events.write_event_log`/`prune_event_logs` (the adapter)
# vs. `sdksession.events`'s functions (the library), called directly.
# ===================================================================== #


def test_write_event_log_adapter_matches_the_library_called_directly_byte_for_byte(tmp_path, monkeypatch):
    _make_home(tmp_path, monkeypatch, "evlog")
    cache = worker.cache_dir()

    events_a = sdk_events.EventLog()
    events_a.add_tool_use("b1", "Read", {"note": "a"})
    events_a.add_denial("Write", "outside stage")

    # via the adapter (invocation_sdk.events)
    events_mod.write_event_log("surf-a", "run-1", meta={"tag": "a"}, events=events_a)
    path_a = events_mod._event_log_path("surf-a", "run-1")

    # via the library, called directly, same inputs, a different
    # surface -- `log_kind="tool-events"` must be the exact literal the
    # adapter hardcodes, or these two paths/contents diverge.
    events_b = sdk_events.EventLog()
    events_b.add_tool_use("b1", "Read", {"note": "a"})
    events_b.add_denial("Write", "outside stage")
    sdk_events.write_event_log(
        cache, "surf-b", "run-1", log_kind="tool-events", meta={"tag": "a"}, events=events_b
    )
    path_b = sdk_events.event_log_path(cache, "surf-b", "run-1", log_kind="tool-events")

    assert path_a == cache / "surf-a.tool-events.run-1.jsonl"
    assert path_a.is_file() and path_b.is_file()
    assert path_a.read_bytes() == path_b.read_bytes()


def test_prune_event_logs_adapter_matches_the_library_called_directly(tmp_path, monkeypatch):
    home = _make_home(tmp_path, monkeypatch, "prune")
    cache = worker.cache_dir()
    monkeypatch.setenv("SELF_LEARN_SDK_EVENT_LOGS", "2")

    def _seed(surface: str) -> None:
        for i in range(4):
            p = cache / f"{surface}.tool-events.run-{i}.jsonl"
            p.write_text("{}", encoding="utf-8")
            os.utime(p, (i, i))

    _seed("surf-a")
    _seed("surf-b")

    # via the adapter: reads `SELF_LEARN_SDK_EVENT_LOGS` -> keep=2
    # through `settings.resolve_setting`, then (this move's short
    # circuit) delegates the actual walk to the library.
    events_mod.prune_event_logs("surf-a")
    # via the library, called directly with the SAME keep the adapter
    # resolved -- the exact retention walk, exercised with no adapter
    # in between.
    sdk_events.prune_event_logs(cache, "surf-b", log_kind="tool-events", keep=2)

    remaining_a = sorted(
        p.name.removeprefix("surf-a.") for p in cache.glob("surf-a.tool-events.*.jsonl")
    )
    remaining_b = sorted(
        p.name.removeprefix("surf-b.") for p in cache.glob("surf-b.tool-events.*.jsonl")
    )
    assert remaining_a == remaining_b == ["tool-events.run-2.jsonl", "tool-events.run-3.jsonl"]
    assert home.is_dir()  # sanity: this test's own home was actually used


def test_prune_event_logs_adapter_short_circuits_when_nothing_is_due(tmp_path, monkeypatch):
    """The adapter's local `cache.glob(...)` count-and-skip (see
    `events.py`'s `prune_event_logs` docstring) must be a true no-op,
    not merely "happens to leave the right files": with fewer files
    than `keep`, NOTHING is unlinked and the delegate is never reached
    with a `keep` that would have mattered."""
    _make_home(tmp_path, monkeypatch, "prune-noop")
    cache = worker.cache_dir()
    monkeypatch.setenv("SELF_LEARN_SDK_EVENT_LOGS", "5")

    for i in range(2):
        p = cache / f"surf-a.tool-events.run-{i}.jsonl"
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (i, i))

    events_mod.prune_event_logs("surf-a")

    remaining = sorted(p.name for p in cache.glob("surf-a.tool-events.*.jsonl"))
    assert remaining == ["surf-a.tool-events.run-0.jsonl", "surf-a.tool-events.run-1.jsonl"]
