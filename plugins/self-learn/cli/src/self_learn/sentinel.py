"""Autosync pause sentinel (T7).

Contract (08 §1 Sentinel + Sentinel-scoping pins; 02 §3; doc 13 §6):

- Path: ``${XDG_CACHE_HOME:-~/.cache}/self-learn/autosync-pause`` —
  resolved from the environment at every call so tests can redirect it.
  GLOBAL, deliberately NOT home-namespaced (unlike the worker cache,
  H-4): the sentinel is a cross-repo pause contract — it exists to pause
  a HOST's autosync during the seconds of a canon apply+commit, and any
  host's sync script must be able to find it without knowing which
  ledger home is applying.
- Content: an informational ``pid=<pid> host=<host> started=<iso>``
  line, plus (M-E) a second ``token=<hex>`` line recording the random
  ownership token this process minted when it created the file — see
  "Ownership" below. Content is otherwise informational ONLY —
  **liveness rides the file's mtime**: the sentinel is *live* iff its
  mtime is younger than the 2 h TTL. A stale sentinel is ignored and may
  be deleted/overwritten by either side.
- Heartbeat: every mutating CLI invocation re-touches the live sentinel
  (no daemon). Expiry therefore means a *dead* holder, not a long one.
- Self-hold scoping (08 §1 Sentinel-scoping pin): a bare resolution verb
  self-holds and releases only a sentinel it created. :func:`hold` records
  ownership on the returned handle — a pre-existing LIVE sentinel (e.g.
  the slash review's whole-batch hold) is left alone (``owned=False``) and
  merely heartbeated by the verbs running under it; release-if-owned is a
  no-op on such a handle.

Ownership (M-E, closing audit C11): pre-M-E, :func:`hold` was
check-then-write — two processes could both observe "no live sentinel"
and both write, each believing ``owned=True`` — and
:meth:`SentinelHold.release` trusted only that local (possibly wrong)
boolean, so a displaced loser could delete the actual winner's file.
Fixed two ways, both scoped to a per-file ``<sentinel>.lock`` taken with
:mod:`fcntl` ``flock``:

- :func:`hold` takes the lock for exactly the bounded critical section
  that decides "is the existing file live?" and, if not (missing or
  stale — the TTL-takeover case), publishes the replacement atomically
  (temp file + :func:`os.replace`) carrying a freshly minted random
  token, all before releasing the lock. Only one process can be inside
  that section at a time, so the old two-writer race cannot recur
  between two processes running this code. The lock is bounded
  (``LOCK_EX | LOCK_NB`` polled against a short deadline) and never
  raises: on contention or timeout ``hold()`` degrades to the same safe
  answer as a live foreign sentinel (``owned=False``) rather than
  blocking a caller that has never had to catch a sentinel exception.
- :meth:`SentinelHold.release` re-takes the same lock and re-reads the
  token CURRENTLY on disk before deleting anything, deleting only when
  it still matches the token this handle was given at creation. A
  handle's local ``owned=True`` is therefore never, by itself, enough to
  delete — the file has to still be provably this handle's file at the
  moment of deletion, which closes the "boolean release" half of C11
  (a delayed or duplicated release can no longer remove a *different*,
  legitimate holder's sentinel).

Rollout: an old-format file — written by a pre-M-E process, a single
``pid=… host=… started=…`` line with no ``token=`` line — is read
exactly like any other live foreign sentinel: :func:`hold` sees it is
live and leaves it alone (``owned=False``), never adopts it, and never
parses a token out of it (there isn't one). Old and new processes may
therefore coexist: the two-writer race this move closes is specifically
between two processes running THIS code, and stays open for as long as
any old-format (pre-restart) holder is itself live — closing fully only
once every long-lived process has restarted onto this code (a host-owner
step; nothing in this module restarts anything).

The main-repo side of the contract (``claude-skills-sync`` exiting 0 while
the sentinel is live) is T12, on master — not here.
"""

from __future__ import annotations

import fcntl
import os
import secrets
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

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

#: Bounded wait for the per-file ownership lock (M-E). Sentinel critical
#: sections are a stat plus, at most, a one-file rename — never a git
#: operation — so a few seconds is generous; see :func:`_lock_section`
#: for why a timeout degrades rather than raises.
_LOCK_TIMEOUT_SECONDS = 5.0

#: Prefix of the (M-E) ownership-token line. A private on-disk detail —
#: never parsed by anything outside this module (UI observers read only
#: the path and the mtime; see ``ledger.sentinel_mtime`` /
#: ``models._sentinel_live``).
_TOKEN_PREFIX = "token="


def sentinel_path() -> Path:
    """The pinned sentinel location, XDG-resolved at call time. Global —
    NOT home-namespaced (doc 13 §6: a cross-repo pause contract)."""
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    return base / "self-learn" / "autosync-pause"


def _lock_path(path: Path) -> Path:
    """Where the ownership lock for *path* lives — a sibling file, never
    itself read for liveness or content (only ever ``flock``ed)."""
    return path.parent / f"{path.name}.lock"


def sentinel_line(now: datetime | None = None) -> str:
    """The one informational line: ``pid=<pid> host=<host>
    started=<iso>``. Unchanged by M-E — the token that makes a hold
    provable lives on its OWN line (see :func:`hold`), so anything that
    only ever wanted the old single-line shape (this function, and the
    UI test that builds a raw file straight from it) keeps working
    unmodified."""
    now = now if now is not None else datetime.now(timezone.utc)
    started = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"pid={os.getpid()} host={socket.gethostname()} started={started}\n"


def _new_token() -> str:
    """A fresh random ownership token (M-E) — unguessable enough that
    two independent :func:`hold` calls never collide, and the only thing
    :meth:`SentinelHold.release` will ever accept as proof this handle's
    file is still on disk."""
    return secrets.token_hex(8)


def _read_token(path: Path) -> str | None:
    """The ownership token recorded in the sentinel currently at *path*,
    or ``None`` for a missing/unreadable file, or an old-format file
    that predates tokens entirely (rollout: never treated as ours)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith(_TOKEN_PREFIX):
            value = line[len(_TOKEN_PREFIX):]
            return value or None
    return None


def is_live(path: Path | None = None, *, now: datetime | None = None) -> bool:
    """Live iff the file exists and its mtime is younger than the TTL."""
    path = path if path is not None else sentinel_path()
    try:
        mtime = path.stat().st_mtime
    except (FileNotFoundError, NotADirectoryError):
        return False
    now_ts = (now if now is not None else datetime.now(timezone.utc)).timestamp()
    return (now_ts - mtime) < SENTINEL_TTL_SECONDS


@contextmanager
def _lock_section(path: Path, timeout: float = _LOCK_TIMEOUT_SECONDS) -> Iterator[bool]:
    """Exclusive ``flock`` on ``<path>.lock``, held for exactly the
    critical section beneath it — never longer (mirrors
    :func:`gitops._flock_lock`'s idiom: bounded ``LOCK_EX | LOCK_NB``
    polled against a deadline, not an indefinite blocking wait).

    Scoping the lock to the critical section rather than to the whole
    life of a :class:`SentinelHold` matters for a real calling pattern
    (``worker.py``'s crash-recovery re-``hold()``): ``flock`` locks are
    per *open file description*, not per process, so a second ``hold()``
    call in the SAME process — issued before the first handle is ever
    explicitly released — must not self-conflict against a lock its own
    earlier call is still notionally holding. Releasing before returning
    means there is nothing left to conflict with.

    Yields whether the lock was actually acquired. On contention or
    timeout it yields ``False`` rather than raising: a sentinel hold is
    advisory (gitops.py's own words), and every existing call site
    treats :func:`hold`/:meth:`SentinelHold.release` as never-raising —
    degrading to the same safe answer as "someone else holds this live"
    keeps that true."""
    lock_path = _lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        deadline = time.monotonic() + timeout
        acquired = False
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
        try:
            yield acquired
        finally:
            if acquired:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


@dataclass
class SentinelHold:
    """Handle returned by :func:`hold`; carries the ownership fact that
    scopes :meth:`release` (release only what this process created), plus
    (M-E) the token :func:`hold` minted for it iff it created the file."""

    path: Path
    owned: bool
    token: str | None = None

    def release(self) -> bool:
        """Delete the sentinel iff this handle created it AND the file
        currently on disk still carries the token :func:`hold` minted
        for it. True iff deleted.

        The token re-check (under a fresh lock, read fresh from disk) is
        the C11 fix for release: a handle's own ``owned=True`` records
        only what was true at HOLD time, and by itself is not proof the
        file on disk right now is still this handle's — a legitimate TTL
        takeover could have landed since. Trusting the boolean alone is
        exactly the bug (a stale/displaced handle deletes a different,
        current owner's file); comparing the token closes it."""
        if not self.owned or self.token is None:
            return False
        with _lock_section(self.path) as acquired:
            if not acquired:
                return False
            if _read_token(self.path) != self.token:
                return False
            try:
                self.path.unlink()
            except FileNotFoundError:
                return False
            return True


def hold() -> SentinelHold:
    """Take the pause sentinel, respecting another holder.

    - No sentinel, or a STALE one (mtime ≥ TTL): (over)write our info
      line plus a fresh ownership token, atomically (temp + rename) →
      ``owned=True``. The liveness check and the publish happen inside
      one lock acquisition (M-E: "TTL takeover as one locked decision"),
      so two processes racing this call can no longer both win it.
    - A LIVE sentinel already exists (another flow — e.g. the slash
      review's batch hold — OR a pre-M-E old-format holder, which reads
      identically: live, and never ours): leave it untouched →
      ``owned=False``. Callers still :func:`heartbeat` per mutating
      invocation.
    """
    path = sentinel_path()
    with _lock_section(path) as acquired:
        if not acquired or is_live(path):
            return SentinelHold(path=path, owned=False)
        token = _new_token()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".{path.name}.{os.getpid()}.{token}.tmp"
        tmp.write_text(
            sentinel_line() + f"{_TOKEN_PREFIX}{token}\n", encoding="utf-8"
        )
        os.replace(tmp, path)
        return SentinelHold(path=path, owned=True, token=token)


def heartbeat(path: Path | None = None) -> bool:
    """Re-touch the live sentinel's mtime (THE heartbeat — every mutating
    invocation calls this). A stale or missing sentinel is left alone
    (never resurrect a dead hold). True iff touched. Format- and
    ownership-agnostic, unchanged by M-E: observers (``ledger.py``,
    ``models.py``) read only this mtime, never the token."""
    path = path if path is not None else sentinel_path()
    if not is_live(path):
        return False
    os.utime(path, None)
    return True


def release(hold: SentinelHold) -> bool:
    """Function-form of :meth:`SentinelHold.release`."""
    return hold.release()
