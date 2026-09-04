"""Autosync pause sentinel (T7).

Contract (08 §1 Sentinel + Sentinel-scoping pins; 02 §3; doc 13 §6):

- Path: ``${XDG_CACHE_HOME:-~/.cache}/self-learn/autosync-pause`` —
  resolved from the environment at every call so tests can redirect it.
  GLOBAL, deliberately NOT home-namespaced (unlike the worker cache,
  H-4): the sentinel is a cross-repo pause contract — it exists to pause
  a HOST's autosync during the seconds of a canon apply+commit, and any
  host's sync script must be able to find it without knowing which
  ledger home is applying.
- Content: exactly one informational line ``pid=<pid> host=<host>
  started=<iso>``. Content is informational ONLY — **semantics ride the
  file's mtime**: the sentinel is *live* iff its mtime is younger than the
  2 h TTL. A stale sentinel is ignored and may be deleted/overwritten by
  either side.
- Heartbeat: every mutating CLI invocation re-touches the live sentinel
  (no daemon). Expiry therefore means a *dead* holder, not a long one.
- Self-hold scoping (08 §1 Sentinel-scoping pin): a bare resolution verb
  self-holds and releases only a sentinel it created. :func:`hold` records
  ownership on the returned handle — a pre-existing LIVE sentinel (e.g.
  the slash review's whole-batch hold) is left alone (``owned=False``) and
  merely heartbeated by the verbs running under it; release-if-owned is a
  no-op on such a handle.

The main-repo side of the contract (``claude-skills-sync`` exiting 0 while
the sentinel is live) is T12, on master — not here.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .primitives import chrono

__all__ = [
    "SENTINEL_TTL_SECONDS",
    "SentinelHold",
    "heartbeat",
    "hold",
    "is_live",
    "release",
    "sentinel_line",
    "sentinel_path",
]

#: 02 §3: live iff mtime age < 2 h.
SENTINEL_TTL_SECONDS = 2 * 60 * 60


def sentinel_path() -> Path:
    """The pinned sentinel location, XDG-resolved at call time. Global —
    NOT home-namespaced (doc 13 §6: a cross-repo pause contract)."""
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    return base / "self-learn" / "autosync-pause"


def sentinel_line(now: datetime | None = None) -> str:
    """The one info line: ``pid=<pid> host=<host> started=<iso>``."""
    now = now if now is not None else datetime.now(timezone.utc)
    started = now.strftime(chrono.ISO_FORMAT)
    return f"pid={os.getpid()} host={socket.gethostname()} started={started}\n"


def is_live(path: Path | None = None, *, now: datetime | None = None) -> bool:
    """Live iff the file exists and its mtime is younger than the TTL."""
    path = path if path is not None else sentinel_path()
    try:
        mtime = path.stat().st_mtime
    except (FileNotFoundError, NotADirectoryError):
        return False
    now_ts = (now if now is not None else datetime.now(timezone.utc)).timestamp()
    return (now_ts - mtime) < SENTINEL_TTL_SECONDS


@dataclass
class SentinelHold:
    """Handle returned by :func:`hold`; carries the ownership fact that
    scopes :meth:`release` (release only what this process created)."""

    path: Path
    owned: bool

    def release(self) -> bool:
        """Delete the sentinel iff this handle created it. True iff deleted."""
        if not self.owned:
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        return True


def hold() -> SentinelHold:
    """Take the pause sentinel, respecting another holder.

    - No sentinel, or a STALE one (mtime ≥ TTL): (over)write our info line
      → ``owned=True``.
    - A LIVE sentinel already exists (another flow — e.g. the slash
      review's batch hold): leave it untouched → ``owned=False``. Callers
      still :func:`heartbeat` per mutating invocation.
    """
    path = sentinel_path()
    if is_live(path):
        return SentinelHold(path=path, owned=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sentinel_line(), encoding="utf-8")
    return SentinelHold(path=path, owned=True)


def heartbeat(path: Path | None = None) -> bool:
    """Re-touch the live sentinel's mtime (THE heartbeat — every mutating
    invocation calls this). A stale or missing sentinel is left alone
    (never resurrect a dead hold). True iff touched."""
    path = path if path is not None else sentinel_path()
    if not is_live(path):
        return False
    os.utime(path, None)
    return True


def release(hold: SentinelHold) -> bool:
    """Function-form of :meth:`SentinelHold.release`."""
    return hold.release()
