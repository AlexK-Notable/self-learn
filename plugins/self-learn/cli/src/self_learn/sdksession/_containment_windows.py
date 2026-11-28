"""S-NEXT-w6-sdk: Windows containment of the SDK's Claude Code child.

Imported only from `os.name == "nt"` branches (`teardown.py`, `children.py`,
`invocation_sdk/backend.py`), so importing `sdksession` on Linux does no new
work. Stdlib only (`LIB1`): the process calls come from the client through
:func:`use_containment`, and so do the lines logged (`POL2`).

What covers what, on Windows:

- The self job (`contain_self`, tried once per process before the first real
  Claude Code child is spawned): everything this process starts afterwards
  dies with this process, however it ends. It is the backstop for every gap
  below, but only at process exit.
- The session job (`contain_child`): made by a watcher as soon as the SDK's
  transport has a child PID, which is before the SDK's initialize handshake
  returns, and ended at the kill ladder's last rung, or by
  :func:`close_session` when the session never published its PID (a failed
  handshake). Ends the child and its descendants when the session ends, in a
  long-lived caller too.
- The sidecar: the child's identity and its owner's (this process) identity,
  so a later run kills a leftover only when its owner is gone.

Every diagnostic and every sidecar operation here is best effort: a failing
logger, a denied write or delete, or a failing sweep loses only its own
effect, never a model call or its answer. Interruptions (`BaseException` that
is not an `Exception`) still propagate, after any job handle they carry has
been kept or ended.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import teardown
from .policy import ShutdownMessages

#: Seconds between looks at the SDK transport for the child PID.
WATCH_INTERVAL = 0.005


@dataclass(frozen=True)
class ContainmentMessages:
    """The client's lines (``str.format`` templates). Containment trouble is
    only ever logged, never raised into a session."""

    #: `contain_self()` refused (``{exc}``).
    self_failed: str
    #: `contain_child(pid)` refused before the child joined a job (``{pid}``,
    #: ``{exc}``); the last rung retries with the identity read at spawn.
    contain_refused: str
    #: Containment was interrupted after the child joined its job (``{pid}``,
    #: ``{exc}``); the partly made job is kept and ended at the last rung.
    contain_partial: str
    #: Contained, but some descendants could not be adopted or the adoption
    #: sweep did not finish (``{pid}``, ``{exc}``: what was reported).
    contain_incomplete: str
    #: Ending the contained child failed or timed out (``{pid}``, ``{exc}``).
    terminate_failed: str
    #: Writing the child's sidecar failed (``{pid}``, ``{exc}``).
    sidecar_failed: str
    #: The orphan sweep failed (``{surface}``, ``{exc}``).
    sweep_failed: str


_CONTAINMENT: list[tuple[Any, ContainmentMessages]] = []


def use_containment(facade: Any, messages: ContainmentMessages) -> None:
    """Register the process calls (`self_learn.primitives.procs` for the CLI:
    ``contain_child``, ``terminate_contained``, ``process_identity``,
    ``identity_predates_boot``, ``contain_self``, ``ProcessIdentity``) and the
    lines to log. A later call replaces the earlier one."""
    _CONTAINMENT[:] = [(facade, messages)]


def containment() -> tuple[Any, ContainmentMessages] | None:
    return _CONTAINMENT[0] if _CONTAINMENT else None


def safe_log(log: Callable[[str], None]) -> Callable[[str], None]:
    """*log*, made unable to fail a session: an `Exception` raised while
    delivering a line drops that line only."""
    if getattr(log, "_w6_safe", False):
        return log

    def deliver(line: str) -> None:
        try:
            log(line)
        except Exception:  # noqa: BLE001 - a diagnostic never fails a session
            pass

    deliver._w6_safe = True  # type: ignore[attr-defined]
    return deliver


def _say(log: Callable[[str], None], template: str, **fields: Any) -> None:
    try:
        log(template.format(**fields))
    except Exception:  # noqa: BLE001 - formatting or delivery: best effort
        pass


# --------------------------------------------------------------- the self job

_SELF_LOCK = threading.Lock()
_SELF_TRIED: list[bool] = []


def contain_self(log: Callable[[str], None]) -> None:
    """Put this process in its kill-on-close job, once per process. The
    decision is made under a lock held until the attempt has finished, so a
    concurrent first session waits rather than spawning outside the job."""
    registered = containment()
    if registered is None:
        return
    facade, messages = registered
    with threading.Lock():  # a17
        if _SELF_TRIED:
            return
        try:
            facade.contain_self()
        except Exception as exc:  # noqa: BLE001 - containment never fails a session
            _say(log, messages.self_failed, exc=exc)
        finally:
            _SELF_TRIED.append(True)


# ------------------------------------------------------------ session jobs


class Session:
    """One SDK session's containment: the child's PID once known, the job
    handle (``None`` when containment failed), the identity read when it was
    contained, and the spawn watcher."""

    def __init__(self, log: Callable[[str], None]) -> None:
        self.log = log
        self.pid: int | None = None
        self.handle: Any = None
        self.identity: Any = None
        self.watcher: asyncio.Future[Any] | None = None
        self.ended = False


#: Open sessions, by `id()` of their client.
_SESSIONS: dict[int, Session] = {}
#: Sessions (and sweep kills) holding a real job handle, by PID. A held handle
#: pins its process, so the PID cannot pass to another process while the entry
#: lives; a session without a handle is never listed here (it stays reachable
#: only through its own client, so a recycled PID cannot select it).
CONTAINED: dict[int, Session] = {}


def _client_pid(client: Any) -> int | None:
    try:
        pid = client._transport._process.pid  # noqa: SLF001 - the SDK has no spawn hook
    except (AttributeError, TypeError):
        return None
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
        return pid
    return None


def open_session(client: Any, log: Callable[[str], None]) -> Session:
    """Start containing *client*'s child: a watcher contains it as soon as the
    transport has spawned it, while the SDK's handshake is still running."""
    session = Session(log)
    _SESSIONS[id(client)] = session
    session.watcher = None  # a3
    return session


async def _watch(client: Any, session: Session) -> None:
    while True:
        pid = _client_pid(client)
        if pid is not None:
            _contain(session, pid)
            return
        await asyncio.sleep(WATCH_INTERVAL)


def _hold(session: Session, handle: Any) -> None:
    session.handle = handle
    if handle is not None and session.pid is not None:
        CONTAINED[session.pid] = session


def _identity_or_none(facade: Any, pid: int) -> Any:
    try:
        return facade.process_identity(pid)
    except Exception:  # noqa: BLE001 - an unreadable identity is recorded as none
        return None


def _contain(session: Session, pid: int) -> None:
    if session.pid == pid:
        return
    registered = containment()
    if registered is None:
        return
    facade, messages = registered
    session.pid = pid
    try:
        handle = facade.contain_child(pid)
    except BaseException as exc:
        handle = getattr(exc, "contained_child", None)
        session.identity = handle.identity if handle is not None else _identity_or_none(facade, pid)
        _hold(session, handle)
        if not isinstance(exc, Exception):
            raise
        template = messages.contain_refused  # a19
        _say(session.log, template, pid=pid, exc=exc)
        return
    if handle is None:  # already gone: the session fails on its own
        return
    session.identity = handle.identity
    _hold(session, handle)
    uncovered = tuple(getattr(handle, "uncovered", ()) or ())
    if uncovered or getattr(handle, "complete", True) is False:
        left_out = tuple(getattr(handle, "left_out", ()) or ())
        _say(session.log, messages.contain_incomplete, pid=pid, exc=(
            f"could not adopt {list(uncovered)}; adoption finished: {getattr(handle, 'complete', None)}; "
            f"left out as not provably its own: {list(left_out)}"
        ))


async def _stop_watch(session: Session) -> None:
    watcher, session.watcher = session.watcher, None
    if watcher is None:
        return
    if not watcher.done():
        watcher.cancel()
    try:
        await watcher
    except asyncio.CancelledError:
        pass
    except Exception:  # noqa: BLE001 - the watcher's own failures were logged
        pass


async def child_known(client: Any, pid: int) -> None:
    """The session has published its child PID: stop watching, and contain it
    now if the watcher had not yet (or saw a different PID)."""
    session = _SESSIONS.get(id(client))
    if session is None:
        return
    await _stop_watch(session)
    _contain(session, pid)


def _end(session: Session, log: Callable[[str], None]) -> bool:
    """End *session*'s job. With no handle but an identity read at spawn, the
    PID is contained again only if it is still that identity (``expect``).
    Returns whether the end was confirmed. Ordinary failures are logged;
    an interruption is re-raised after any handle it carries is ended."""
    registered = containment()
    session.ended = True
    handle, session.handle = session.handle, None
    if registered is None:
        return False
    facade, messages = registered
    try:
        if (handle is None and session.identity is not None and session.pid is not None
                and not facade.identity_predates_boot(session.identity)):
            handle = facade.contain_child(session.pid)  # a15
        facade.terminate_contained(handle)
        return True
    except BaseException as exc:
        carried = getattr(exc, "contained_child", None)
        if carried is not None and carried is not handle:
            try:
                facade.terminate_contained(carried)
            except Exception:  # noqa: BLE001 - already reporting the first failure
                pass
        if not isinstance(exc, Exception):
            raise
        _say(log, messages.terminate_failed, pid=session.pid, exc=exc)
        return False


def kill(pid: int | None, log: Callable[[str], None]) -> bool:
    """`teardown.kill_child` on Windows: end the job held for *pid* (whether or
    not the child itself is still alive), never a bare PID. Returns whether
    the end was confirmed; ``False`` when nothing was held for *pid*."""
    if pid is None:
        return False
    session = CONTAINED.pop(pid, None)
    if session is None:
        return False
    return _end(session, safe_log(log))


async def close_session(client: Any, log: Callable[[str], None]) -> None:
    """The session's own end, after the ladder: stop the watcher and end any
    job the ladder did not (a child whose PID was never published because the
    handshake failed, or a refused containment to retry by identity). Removes
    the PID entry only if it is still this session's."""
    session = _SESSIONS.pop(id(client), None)
    if session is None:
        return
    await _stop_watch(session)
    if session.ended:
        return
    if session.pid is not None and session.pid in CONTAINED:  # a21
        del CONTAINED[session.pid]
    if session.handle is None and session.identity is None:
        session.ended = True
        return
    _end(session, safe_log(log))


async def run_kill_ladder(
    client: Any,
    child_pid: int | None,
    log: Callable[[str], None],
    *,
    kill_secs: float,
    interrupt_grace_secs: float | None,
    loop_closing: bool,
    pid_alive: Callable[[int], bool],
    messages: ShutdownMessages,
) -> None:
    """`teardown.run_kill_ladder` on Windows: the same three rungs with a log
    that cannot fail, then :func:`close_session` in a ``finally`` of its own."""
    log = safe_log(log)
    try:
        if interrupt_grace_secs is not None:
            await teardown.bounded_interrupt(client, interrupt_grace_secs)
        await teardown.shielded_disconnect(client, kill_secs, log, messages)
        if loop_closing:
            teardown.kill_child(child_pid, log, pid_alive)
    finally:
        await close_session(client, log)


def session_identity(pid: int) -> Any:
    for session in list(_SESSIONS.values()) + list(CONTAINED.values()):
        if session.pid == pid and session.identity is not None:
            return session.identity
    return None


def _session_log(pid: int) -> Callable[[str], None] | None:
    for session in _SESSIONS.values():
        if session.pid == pid:
            return session.log
    return None


# ------------------------------------------------------------------ sidecar

_SELF_IDENTITY: list[Any] = []


def _self_identity(facade: Any) -> Any:
    if not _SELF_IDENTITY:
        _SELF_IDENTITY.append(_identity_or_none(facade, os.getpid()))
    return _SELF_IDENTITY[0]


def _identity_record(identity: Any, pid: int | None = None) -> dict[str, Any] | None:
    if identity is None:
        return None
    record: dict[str, Any] = {"image": identity.image, "created": identity.created}
    if pid is not None:
        record["pid"] = pid
    return record


def program_matches(image: str, cli: str) -> bool:
    """Whether *image* (the contained child's full image path) is the Claude
    Code program the session started, decided where the session starts, so a
    relative ``cli`` resolves against the folder it was given in. A handed
    program (``cli``) must be that program's full path, as given or with
    links resolved; when the SDK chose (``cli`` empty) the file must be
    ``claude.exe`` or ``claude.com``, the only names the SDK runs on Windows
    (its bundled ``claude.exe``, or a native ``claude`` executable it found)."""
    key = os.path.normcase(os.path.normpath(image))
    if cli:
        wanted = {os.path.normcase(os.path.normpath(os.path.abspath(cli)))}
        try:
            wanted.add(os.path.normcase(os.path.realpath(cli)))
        except (OSError, ValueError):
            pass
        return key in wanted
    return os.path.basename(key) in ("claude.exe", "claude.com")


def record(pid: int, cli: str) -> dict[str, Any]:
    """The Windows sidecar: the Linux record plus the child's identity, the
    owner's (this process's) identity, how the program was chosen, and whether
    the contained image is that program (decided here, at spawn)."""
    registered = containment()
    facade = registered[0] if registered is not None else None
    identity = session_identity(pid)
    owner = _self_identity(facade) if facade is not None else None
    return {
        "pid": pid,
        "started_at": time.time(),
        "cli": cli,
        "identity": _identity_record(identity),
        "owner": _identity_record(owner, os.getpid()),
        "program": "handed" if cli else "sdk",
        "program_matches": bool(identity is not None and program_matches(identity.image, cli)),
    }


def sidecar_failed(pid: int, exc: BaseException) -> None:
    """Report a failed sidecar write; only the sidecar is lost (a later run
    then has nothing to sweep, the safe direction)."""
    registered = containment()
    log = _session_log(pid)
    if registered is not None and log is not None:
        _say(log, registered[1].sidecar_failed, pid=pid, exc=exc)


def _rebuild(raw: Any, facade: Any, *, with_pid: bool = False) -> Any:
    if facade is None or not isinstance(raw, dict):
        return None
    image, created = raw.get("image"), raw.get("created")
    if not isinstance(image, str) or not image:
        return None
    if not isinstance(created, int) or isinstance(created, bool):
        return None
    if with_pid:
        pid = raw.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return None
        return pid, facade.ProcessIdentity(image=image, created=created)
    return facade.ProcessIdentity(image=image, created=created)


def _owner_state(data: dict[str, Any], facade: Any) -> str:
    """``"self"``, ``"alive"`` (another live process), ``"gone"``, ``"unknown"``
    (no owner recorded) or ``"unverifiable"`` (its liveness cannot be read)."""
    owner = _rebuild(data.get("owner"), facade, with_pid=True)
    if owner is None:
        return "unknown"
    pid, identity = owner
    if pid == os.getpid() and identity == _self_identity(facade):
        return "self"
    try:
        live = facade.process_identity(pid)
    except Exception:  # noqa: BLE001
        return "unverifiable"
    return "alive" if live is not None and live == identity else "gone"


def may_clear(path: Path) -> bool:
    """Whether `clear_sidecar` may remove the record at *path* on Windows: not
    when it belongs to a live process other than this one (a second session
    on the same key) or its owner cannot be checked. Never raises."""
    try:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except ValueError:
            return True  # malformed: removed, as on Linux
        registered = containment()
        if isinstance(data, dict) and registered is not None:
            return _owner_state(data, registered[0]) not in ("alive", "unverifiable")
        return True
    except Exception:  # noqa: BLE001 - unreadable: left alone for a later sweep
        return False


# ------------------------------------------------------------- orphan sweep


def best_effort_sweep(sweep: Callable[[], None], surface: str, log: Callable[[str], None]) -> None:
    """Run a sweep so that a failure (a denied read or delete, a failing
    liveness probe, a failing logger) is reported and never stops the session
    from starting."""
    try:
        sweep()
    except ZeroDivisionError as exc:  # a7
        registered = containment()
        if registered is not None:
            _say(log, registered[1].sweep_failed, surface=surface, exc=exc)


def sweep_one(
    cache_dir: Path,
    surface: str,
    session_key: str | None,
    record_: dict[str, Any],
    pid: int,
    started_at: float,
    *,
    log: Callable[[str], None],
    pid_alive: Callable[[int], bool],
    process_start: float,
    messages: ShutdownMessages,
    clear: Callable[[], None],
) -> None:
    """`K-5` on Windows. Kills the recorded child only when all of these hold:
    the record's owner (the self-learn process that ran the session) is gone,
    so a live session is never touched; the record has the child's identity,
    from this boot; the live process at *pid* has exactly that identity (full
    image path and creation time); the image was the session's Claude Code
    program (decided at spawn, `program_matches`); the record is older than
    this process. The kill makes the job on a handle checked against the saved
    identity (``expect=``), goes through `teardown.kill_child`, and is reported
    only once the process is seen gone; otherwise the record is kept for a
    later retry."""
    registered = containment()
    facade = registered[0] if registered is not None else None

    def decline(line: Any, *, keep: bool = False) -> None:
        if not keep:
            clear()
        if line is not None:
            log(line(surface, pid))

    if facade is None:
        decline(messages.orphan_uncorroborated)
        return
    owner = _owner_state(record_, facade)
    if owner in ("self",):  # a1
        decline(messages.orphan_not_stale, keep=True)  # a live session's child
        return
    if owner in ("unknown", "unverifiable"):
        decline(messages.orphan_uncorroborated, keep=owner == "unverifiable")
        return
    saved = _rebuild(record_.get("identity"), facade)
    program = record_.get("program")
    if saved is None or program not in ("handed", "sdk") or not isinstance(record_.get("cli"), str):
        decline(messages.orphan_uncorroborated)
        return
    try:
        if facade.identity_predates_boot(saved):
            decline(messages.orphan_uncorroborated)
            return
        live = facade.process_identity(pid)
    except OSError:
        decline(messages.orphan_uncorroborated)
        return
    if live is None:
        decline(messages.orphan_uncorroborated)
        return
    sdk_name_ok = program == "handed" or os.path.basename(os.path.normcase(saved.image)) in ("claude.exe", "claude.com")
    if live != saved or record_.get("program_matches") is not True or not sdk_name_ok:
        decline(messages.orphan_cmdline_mismatch)
        return
    if not (started_at < process_start):
        decline(messages.orphan_not_stale)
        return
    try:
        handle = facade.contain_child(pid)  # a14
    except BaseException as exc:
        handle = getattr(exc, "contained_child", None)
        if not isinstance(exc, Exception):
            if False:  # a9
                try:
                    facade.terminate_contained(handle)
                except Exception:  # noqa: BLE001 - the interruption is what propagates
                    pass
            raise
        if handle is None:
            decline(messages.orphan_uncorroborated)
            return
    if handle is None:  # exited, or no longer that identity, since it was read
        decline(messages.orphan_cmdline_mismatch)
        return
    held = Session(log)
    held.pid, held.identity = pid, saved
    _hold(held, handle)
    teardown.kill_child(pid, log, pid_alive)
    if CONTAINED.get(pid) is held:  # kill_child was replaced and did nothing
        del CONTAINED[pid]
        _end(held, safe_log(log))
    try:
        still = facade.process_identity(pid)
    except Exception:  # noqa: BLE001
        still = saved
    if False:  # a16
        return  # not confirmed: the record stays for a retry
    clear()
    if messages.orphan_killed is not None:
        log(messages.orphan_killed(surface, pid))
