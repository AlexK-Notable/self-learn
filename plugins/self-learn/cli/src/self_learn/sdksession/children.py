"""U-engine sdksession — `children.py` (spec §4.2): `child_pid_of`
(`K-3`), the pid sidecar (`K-4`), and the scoped orphan sweep (`K-5`).

Every function takes `cache_dir: Path` as a PARAMETER -- never reads it
via an upward `worker.cache_dir()` import (`LIB1`/§4.3). `sweep_orphans`
takes `pid_alive` and `messages` as parameters too, for the same reason
(`LIB2`: no `os.environ`; `POL2`: no message literal in library code).

`F-2` (§4.6): the sidecar is keyed by `surface` AND an optional
`session_key` -- when `session_key` is `None` the filename SHAPE is
byte-identical to the pre-`U-engine` single-sidecar-per-surface layout,
which is what keeps `invocation_sdk/lifecycle.py`'s thin wrappers
(called with an explicit `session_key=None`, matching the armor-pinned
tests' existing 1/3-arg call shapes) behaviourally unchanged. A caller that
DOES pass distinct `session_key`s per session (a future multi-session
consumer) gets `MS3`'s proven property: two live sessions on one
surface produce two distinct sidecar files, and `sweep_orphans` globs
and judges every sidecar for a surface independently.

`F-4` (§4.6): the staleness anchor is a PARAMETER
(`process_start: float`), never an import-time module global.
`default_process_start()` is the CLI's convenience default -- computed
on its OWN first call, not at import (§2.9's G-1 disposition).

Import-bounded: stdlib only.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import teardown
from .policy import ShutdownMessages

__all__ = [
    "child_pid_of",
    "clear_sidecar",
    "default_process_start",
    "read_sidecar",
    "sidecar_path",
    "sweep_orphans",
    "write_sidecar",
]


def child_pid_of(client: Any) -> int | None:
    """`K-3` -- DEFENSIVE: walks private attributes and returns `None`
    on ANY failure, never raising. `client` is typed `Any` deliberately
    -- this module may not import `claude_agent_sdk`."""
    try:
        return client._transport._process.pid  # noqa: SLF001 - deliberate, defensive
    except (AttributeError, TypeError):
        return None


def sidecar_path(cache_dir: Path, surface: str, session_key: str | None = None) -> Path:
    """`K-4`/`F-2` -- `session_key=None` reproduces the pre-`U-engine`
    filename byte-for-byte (`f"{surface}.sdk-child.pid"`); a given key
    scopes the file to that one session."""
    if session_key is None:
        return cache_dir / f"{surface}.sdk-child.pid"
    return cache_dir / f"{surface}.sdk-child.{session_key}.pid"


def write_sidecar(
    cache_dir: Path, surface: str, pid: int, cli: str, *, session_key: str | None = None
) -> None:
    """`K-4` -- written as soon as the child pid is known. Carries more
    than a bare pid: a bare pid is a pid-reuse foot-gun -- a sweep that
    trusts one can SIGKILL an unrelated process that inherited the
    number."""
    path = sidecar_path(cache_dir, surface, session_key)
    path.write_text(
        json.dumps({"pid": pid, "started_at": time.time(), "cli": cli}),
        encoding="utf-8",
    )


def read_sidecar(cache_dir: Path, surface: str, session_key: str | None = None) -> dict[str, Any] | None:
    path = sidecar_path(cache_dir, surface, session_key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear_sidecar(cache_dir: Path, surface: str, session_key: str | None = None) -> None:
    """`K-4`/`K-5` -- unlinked whether the session succeeded, failed, or
    timed out; also the ONE call site the orphan sweep uses once it is
    done with a sidecar it read."""
    sidecar_path(cache_dir, surface, session_key).unlink(missing_ok=True)


_process_start_cache: list[float] = []


def default_process_start() -> float:
    """`F-4`/G-1's disposition -- resolved on its OWN first call in this
    process, never at module import time, and cached for the rest of
    the process once resolved."""
    if not _process_start_cache:
        _process_start_cache.append(time.time())
    return _process_start_cache[0]


def _sweep_one(
    cache_dir: Path,
    surface: str,
    session_key: str | None,
    record: dict[str, Any],
    *,
    log: Callable[[str], None],
    pid_alive: Callable[[int], bool],
    process_start: float,
    messages: ShutdownMessages,
) -> None:
    pid = record.get("pid")
    started_at = record.get("started_at")
    cli = record.get("cli")
    if not isinstance(pid, int) or not isinstance(started_at, (int, float)):
        clear_sidecar(cache_dir, surface, session_key)
        if messages.orphan_malformed is not None:
            log(messages.orphan_malformed(surface))
        return
    if not pid_alive(pid):
        clear_sidecar(cache_dir, surface, session_key)
        if messages.orphan_no_live_process is not None:
            log(messages.orphan_no_live_process(surface, pid))
        return
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        clear_sidecar(cache_dir, surface, session_key)
        if messages.orphan_uncorroborated is not None:
            log(messages.orphan_uncorroborated(surface, pid))
        return
    first = raw.split(b"\x00")[0].decode("utf-8", "replace")
    basename = os.path.basename(first)
    cli_basename = os.path.basename(cli) if isinstance(cli, str) else None
    matches = basename == "claude" or (cli_basename is not None and basename == cli_basename)
    if not matches:
        clear_sidecar(cache_dir, surface, session_key)
        if messages.orphan_cmdline_mismatch is not None:
            log(messages.orphan_cmdline_mismatch(surface, pid))
        return
    if not (started_at < process_start):
        clear_sidecar(cache_dir, surface, session_key)
        if messages.orphan_not_stale is not None:
            log(messages.orphan_not_stale(surface, pid))
        return
    # gate r1 N-3: `teardown.kill_child` looked up at CALL time (an
    # attribute access on the `teardown` module object here) rather
    # than bound to a local name at import -- `lifecycle.kill_child`
    # (invocation_sdk) already does this for the identical reason,
    # documented in ITS OWN docstring: so a test's `monkeypatch.
    # setattr(lifecycle_mod, "kill_child", ...)` still intercepts
    # the real call site. A name bound at import (the previous
    # shape here) is not interceptable through the module it is
    # imported into -- observed live during this fold: a
    # message-rendering harness's neuter of `lifecycle.kill_child`
    # silently missed this call, and its subprocess took a real
    # SIGKILL (rc=137).
    teardown.kill_child(pid, log, pid_alive)
    clear_sidecar(cache_dir, surface, session_key)
    if messages.orphan_killed is not None:
        log(messages.orphan_killed(surface, pid))


def sweep_orphans(
    cache_dir: Path,
    surface: str,
    log: Callable[[str], None],
    *,
    pid_alive: Callable[[int], bool],
    messages: ShutdownMessages,
    process_start: float | None = None,
) -> None:
    """`K-5` -- before connecting, judge every sidecar recorded for this
    surface (`F-2`: there may be more than one) on its own three
    corroborating checks. Any check that cannot be performed means DO
    NOT kill -- unlink the sidecar and log one line. Silent when there
    is nothing to sweep (`O-quiet`).

    `process_start` defaults to :func:`default_process_start` (`F-4`);
    a caller may pass an explicit anchor (`MS5`)."""
    anchor = default_process_start() if process_start is None else process_start
    unkeyed = sidecar_path(cache_dir, surface, None)
    if unkeyed.is_file():
        record = read_sidecar(cache_dir, surface, None)
        if record is not None:
            _sweep_one(
                cache_dir, surface, None, record,
                log=log, pid_alive=pid_alive, process_start=anchor, messages=messages,
            )
    prefix = f"{surface}.sdk-child."
    for path in sorted(cache_dir.glob(f"{surface}.sdk-child.*.pid")):
        session_key = path.name[len(prefix) : -len(".pid")]
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            continue
        if not isinstance(record, dict):
            path.unlink(missing_ok=True)
            continue
        _sweep_one(
            cache_dir, surface, session_key, record,
            log=log, pid_alive=pid_alive, process_start=anchor, messages=messages,
        )
