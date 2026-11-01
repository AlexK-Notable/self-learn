"""ask_runner.py — the inbox's "ask about this" turns and the login check
(attention round, design r2 §3.3 "Streaming to the page", "Timeouts",
"Stop", "Concurrency with the host's jobs"; contracts §4.7 and §4.8).

One ask turn is one ``self-learn ask <id> --message-file - --stream``
subprocess. Its stdout is NDJSON (§4.8); each line is relayed as an SSE
envelope ``{"type": "ask", "item": <id>, <the CLI event's fields>}``
through the app's :class:`self_learn_ui.sse.AppEventHub`, and kept in an
in-memory buffer so a page reopened mid-turn shows the text so far.

This runner is deliberately NOT the :class:`self_learn_ui.runner.VerbRunner`:
that one runs one verb at a time server-wide, and an answer can take
minutes. A click on an option must never wait behind a model call (design
r2 critique 17), so ask turns and ``attention check-login`` run here:

- at most one turn per item (a second start is refused: the route's 409);
- at most :data:`MAX_TURNS_IN_FLIGHT` across the UI;
- a watchdog: the turn's own ``ask.timeout_secs`` plus 30 s, then SIGTERM
  to the verb's process group, then SIGKILL after 5 s;
- Stop: the person's Stop leaves the verb's stop marker
  (``self_learn.ask.request_stop``) BEFORE the signal, so the verb records
  "stopped by you"; an unmarked SIGTERM (the watchdog, a restart) is
  recorded as what it is.

:class:`FakeAskRunner` is the scripted twin for tests and for the walk
world (``SELF_LEARN_UI_FAKE_ASK=1``, §4.7 "Sandbox switch"). It never
spawns anything. With ``seal=True`` (the walk world only) it writes the
rows the real verb would write, into the scratch ledger, so the page reads
back a real transcript; it still makes no model call.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import uuid
from abc import ABC, abstractmethod
from asyncio import subprocess as asyncio_subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import uilog
from .runner import resolve_self_learn_argv_prefix

__all__ = [
    "AskRunner",
    "AskTurn",
    "FAKE_ASK_ENV",
    "FakeAskRunner",
    "LoginCheck",
    "MAX_TURNS_IN_FLIGHT",
    "RealAskRunner",
    "SANDBOX_SCRIPT",
    "build_ask_runner",
]

#: §4.7 "Sandbox switch": the walk world sets it; nothing else may.
FAKE_ASK_ENV = "SELF_LEARN_UI_FAKE_ASK"
#: §3.3: at most two turns in flight across the UI.
MAX_TURNS_IN_FLIGHT = 2
#: §3.3 "Timeouts": the UI's watchdog is the turn's own timeout plus this.
WATCHDOG_GRACE_SECS = 30.0
#: Then SIGTERM, then SIGKILL after this.
KILL_GRACE_SECS = 5.0
#: ``attention check-login`` is one tiny turn bounded at 120 s inside the
#: CLI; the UI's own bound sits above it.
CHECK_LOGIN_TIMEOUT_SECS = 150.0
_DEFAULT_ASK_TIMEOUT_SECS = 300.0


@dataclass
class AskTurn:
    """One in-flight turn's state, as the page needs it on a reload."""

    item: str
    message: str
    started: float
    text: str = ""
    tool: str | None = None
    drafts: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    finished: bool = False

    def view(self) -> dict[str, Any]:
        return {"item": self.item, "message": self.message, "text": self.text,
                "tool": self.tool, "drafts": list(self.drafts)}

    def absorb(self, event: dict) -> None:
        self.events.append(event)
        ev = event.get("ev")
        if ev == "delta" and isinstance(event.get("text"), str):
            self.text += event["text"]
        elif ev == "done" and isinstance(event.get("text"), str):
            self.text = event["text"]
        elif ev == "tool":
            target = event.get("target")
            name = str(event.get("name") or "")
            self.tool = f"{_tool_words(name)} {target}" if target else _tool_words(name)
        elif ev == "draft":
            self.drafts.append({k: event.get(k) for k in ("draft_id", "option", "text")})


def _tool_words(name: str) -> str:
    """``mcp__selflearn_ask__case`` -> "reading case"; Read -> "reading"."""
    short = name.rsplit("__", 1)[-1] if name else "a tool"
    if short in ("Read", "Glob", "list_dir", "search"):
        return "looking at"
    return f"reading {short}"


@dataclass(frozen=True)
class LoginCheck:
    """``attention check-login``'s outcome: its exit code and its words."""

    exit_code: int
    message: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


Publish = Callable[[dict], None]


class AskRunner(ABC):
    """The seam both runners satisfy. ``publish`` relays one SSE envelope
    (the app's ``AppEventHub.publish_nowait``)."""

    def __init__(self, *, publish: Publish) -> None:
        self._publish = publish
        self._turns: dict[str, AskTurn] = {}

    # -- state

    @property
    def busy(self) -> bool:
        """Any turn in flight: the idle monitor's ask leg (§3.3, ``idle.py``)."""
        return any(not t.finished for t in self._turns.values())

    def in_flight(self, item_id: str) -> dict | None:
        turn = self._turns.get(item_id)
        return turn.view() if turn is not None and not turn.finished else None

    def refusal(self, item_id: str) -> str | None:
        """Why a new turn on *item_id* cannot start now, or ``None``."""
        turn = self._turns.get(item_id)
        if turn is not None and not turn.finished:
            return "Still answering your last question."
        live = sum(1 for t in self._turns.values() if not t.finished)
        if live >= MAX_TURNS_IN_FLIGHT:
            return ("Two questions are already being answered on other items; ask again "
                    "when one finishes.")
        return None

    def _relay(self, turn: AskTurn, event: dict) -> None:
        turn.absorb(event)
        self._publish({**event, "type": "ask", "item": turn.item})

    def _begin(self, item_id: str, message: str) -> AskTurn:
        turn = AskTurn(item=item_id, message=message, started=asyncio.get_running_loop().time())
        self._turns[item_id] = turn
        return turn

    def _end(self, turn: AskTurn, exit_code: int | None) -> None:
        turn.finished = True
        self._publish({"type": "ask", "item": turn.item, "ev": "end", "exit": exit_code})

    # -- the three operations

    @abstractmethod
    async def start(self, item_id: str, message: str, *, header: dict | None = None) -> str | None:
        """Start one turn. Returns ``None`` when it started, else the
        refusal in words (the route answers 409 with it)."""

    @abstractmethod
    async def stop(self, item_id: str) -> bool:
        """The person's Stop. ``False`` when nothing was in flight."""

    @abstractmethod
    async def check_login(self) -> LoginCheck:
        """``self-learn attention check-login``, never behind the verb runner."""

    async def shutdown(self) -> None:  # noqa: B027 - optional hook
        """Stop every turn (the app is shutting down)."""


# ===================================================================== #
# The real runner
# ===================================================================== #


def _signal_group(pid: int, sig: int) -> bool:
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        return False
    return True


class RealAskRunner(AskRunner):
    """Spawns the CLI verb per turn (production)."""

    def __init__(
        self,
        *,
        home: Path,
        publish: Publish,
        argv_prefix: list[str] | None = None,
        env: dict[str, str] | None = None,
        ask_timeout: float | None = None,
        watchdog_grace: float = WATCHDOG_GRACE_SECS,
        kill_grace: float = KILL_GRACE_SECS,
    ) -> None:
        super().__init__(publish=publish)
        self._home = Path(home)
        self._argv_prefix = argv_prefix if argv_prefix is not None else resolve_self_learn_argv_prefix(env)
        self._env = env
        self._ask_timeout = ask_timeout
        self._watchdog_grace = watchdog_grace
        self._kill_grace = kill_grace
        self._procs: dict[str, asyncio_subprocess.Process] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._login_lock = asyncio.Lock()

    def _full_env(self) -> dict[str, str]:
        full = dict(self._env if self._env is not None else os.environ)
        full["SELF_LEARN_HOME"] = str(self._home)
        return full

    def _turn_timeout(self) -> float:
        if self._ask_timeout is not None:
            return self._ask_timeout
        try:
            from self_learn import settings

            value, _source = settings.resolve_setting(self._home, settings.by_name("ask.timeout_secs"))
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
        except Exception:  # noqa: BLE001 - the default bound still applies
            pass
        return _DEFAULT_ASK_TIMEOUT_SECS

    async def start(self, item_id: str, message: str, *, header: dict | None = None) -> str | None:
        refused = self.refusal(item_id)
        if refused is not None:
            return refused
        turn = self._begin(item_id, message)
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._argv_prefix, "ask", item_id, "--message-file", "-", "--stream",
                env=self._full_env(), stdin=asyncio_subprocess.PIPE,
                stdout=asyncio_subprocess.PIPE, stderr=asyncio_subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            self._relay(turn, {"ev": "error", "code": "failed",
                               "message": f"the ask agent could not be started: {exc}", "fix": None})
            self._end(turn, None)
            return None
        self._procs[item_id] = proc
        assert proc.stdin is not None
        proc.stdin.write(message.encode("utf-8"))
        try:
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        proc.stdin.close()
        self._tasks[item_id] = asyncio.ensure_future(self._drive(turn, proc))
        return None

    async def _drive(self, turn: AskTurn, proc: asyncio_subprocess.Process) -> None:
        deadline = self._turn_timeout() + self._watchdog_grace
        terminal_seen = False
        try:
            try:
                async with asyncio.timeout(deadline):
                    terminal_seen = await self._pump(turn, proc)
            except TimeoutError:
                uilog.log(f"ask {turn.item}: watchdog after {deadline:.0f}s; terminating")
                await self._terminate(proc)
                terminal_seen = await self._pump(turn, proc, drain_only=True) or terminal_seen
            code = await proc.wait()
            stderr = b""
            if proc.stderr is not None:
                try:
                    stderr = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
                except (TimeoutError, OSError):
                    stderr = b""
            if not terminal_seen and code != 0:
                tail = stderr.decode("utf-8", "replace").strip()[-600:]
                self._relay(turn, {
                    "ev": "error", "code": "interrupted" if code in (-15, -9, 7) else "failed",
                    "message": tail or f"the ask agent stopped (exit {code})", "fix": None,
                })
            self._end(turn, code)
        except asyncio.CancelledError:
            await self._terminate(proc)
            self._end(turn, None)
            raise
        finally:
            self._procs.pop(turn.item, None)
            self._tasks.pop(turn.item, None)

    async def _pump(self, turn: AskTurn, proc: asyncio_subprocess.Process, *,
                    drain_only: bool = False) -> bool:
        """Relay stdout lines until EOF; ``True`` once a ``done`` or
        ``error`` event was relayed."""
        terminal = False
        assert proc.stdout is not None
        while True:
            try:
                line = (await asyncio.wait_for(proc.stdout.readline(), timeout=self._kill_grace * 2)
                        if drain_only else await proc.stdout.readline())
            except TimeoutError:
                return terminal
            if not line:
                return terminal
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or not isinstance(event.get("ev"), str):
                continue
            self._relay(turn, event)
            if event["ev"] in ("done", "error"):
                terminal = True

    async def _terminate(self, proc: asyncio_subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        if not _signal_group(proc.pid, signal.SIGTERM):
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=self._kill_grace)
            return
        except TimeoutError:
            pass
        _signal_group(proc.pid, signal.SIGKILL)
        try:
            await asyncio.wait_for(proc.wait(), timeout=self._kill_grace)
        except TimeoutError:
            pass

    async def stop(self, item_id: str) -> bool:
        proc = self._procs.get(item_id)
        if proc is None or proc.returncode is not None:
            return False
        try:
            from self_learn import ask as sl_ask

            sl_ask.request_stop(self._home, item_id)
        except Exception as exc:  # noqa: BLE001 - the stop still happens, unmarked
            uilog.log(f"ask {item_id}: stop marker not written ({exc}); stopping anyway")
        await self._terminate(proc)
        return True

    async def check_login(self) -> LoginCheck:
        if self._login_lock.locked():
            return LoginCheck(75, "A login check is already running.")
        async with self._login_lock:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self._argv_prefix, "attention", "check-login", env=self._full_env(),
                    stdin=asyncio_subprocess.DEVNULL, stdout=asyncio_subprocess.PIPE,
                    stderr=asyncio_subprocess.PIPE, start_new_session=True,
                )
            except OSError as exc:
                return LoginCheck(1, f"the login check could not be started: {exc}")
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=CHECK_LOGIN_TIMEOUT_SECS)
            except TimeoutError:
                await self._terminate(proc)
                return LoginCheck(1, f"the login check took longer than {CHECK_LOGIN_TIMEOUT_SECS:.0f}s")
            code = proc.returncode if proc.returncode is not None else 1
            words = (out if code == 0 else err or out).decode("utf-8", "replace").strip()
            return LoginCheck(code, words)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


# ===================================================================== #
# The scripted fake
# ===================================================================== #


#: The walk world's scripted answer (``SELF_LEARN_UI_FAKE_ASK=1``). It says
#: what it is, so a walker never mistakes it for a real agent's reading.
SANDBOX_ANSWER = (
    "(Sandbox: this answer is scripted. No model was called.)\n\n"
    "From the packet: this item is waiting on you, and nothing has changed while it waits. "
    "A real agent would answer from the evidence on this page first, then read further "
    "(the case, your recorded words, the files the change would touch) and say where it "
    "looked.\n\nI drafted a reply below that you can edit and send."
)
SANDBOX_DRAFT = "Yes, but only if it does not restart my desktop session."


def _sandbox_script() -> list[dict]:
    chunks = [SANDBOX_ANSWER[i:i + 48] for i in range(0, len(SANDBOX_ANSWER), 48)]
    return [
        {"ev": "start", "turn": None, "session": None, "resumed": False, "reinjected": False,
         "model": "sandbox-fake"},
        {"ev": "tool", "name": "Read", "target": "packet.md"},
        *({"ev": "delta", "text": c} for c in chunks),
        {"ev": "draft", "draft_id": None, "option": None, "text": SANDBOX_DRAFT},
        {"ev": "done", "turn": None, "text": SANDBOX_ANSWER, "session": None, "sealed": []},
    ]


SANDBOX_SCRIPT = _sandbox_script()


class FakeAskRunner(AskRunner):
    """Scripted playback. Records every start (``calls``), stop
    (``stops``) and login check (``login_checks``); publishes ``script`` in
    order. ``hold=True`` keeps each turn in flight until :meth:`release`
    or :meth:`stop` (tests 6 and 7). ``seal=True`` with ``home`` writes the
    rows the real verb writes (the walk world only)."""

    def __init__(
        self,
        *,
        publish: Publish,
        script: list[dict] | None = None,
        hold: bool = False,
        login: LoginCheck | None = None,
        home: Path | None = None,
        seal: bool = False,
    ) -> None:
        super().__init__(publish=publish)
        self.script = list(script) if script is not None else list(SANDBOX_SCRIPT)
        self.hold = hold
        self.login = login if login is not None else LoginCheck(
            0, "attention check-login: the login works; held jobs run on their next schedule")
        self.home = Path(home) if home is not None else None
        self.seal = seal
        self.calls: list[tuple[str, str]] = []
        self.stops: list[str] = []
        self.login_checks = 0
        self._release: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def start(self, item_id: str, message: str, *, header: dict | None = None) -> str | None:
        refused = self.refusal(item_id)
        if refused is not None:
            return refused
        self.calls.append((item_id, message))
        turn = self._begin(item_id, message)
        self._release[item_id] = asyncio.Event()
        self._tasks[item_id] = asyncio.ensure_future(self._play(turn, header))
        return None

    def release(self, item_id: str) -> None:
        event = self._release.get(item_id)
        if event is not None:
            event.set()

    async def wait(self, item_id: str) -> None:
        task = self._tasks.get(item_id)
        if task is not None:
            await task

    async def _seal(self, item_id: str, rows: list[dict], header: dict | None) -> list[int]:
        if not (self.seal and self.home is not None):
            return []
        from self_learn import workspace

        return await asyncio.to_thread(workspace.append, self.home, item_id, rows, header=header)

    async def _play(self, turn: AskTurn, header: dict | None) -> None:
        stopped = False
        try:
            await self._seal(turn.item, [{"role": "user", "origin": "typed", "kind": "question",
                                          "text": turn.message}], header)
            drafts: list[dict] = []
            for event in self.script:
                if event.get("ev") in ("done", "error") and self.hold:
                    await self._release[turn.item].wait()
                    if turn.item in self.stops:
                        stopped = True
                        break
                event = dict(event)
                if event.get("ev") == "draft":
                    event["draft_id"] = event.get("draft_id") or "drf-" + uuid.uuid4().hex[:8]
                    drafts.append(event)
                self._relay(turn, event)
                await asyncio.sleep(0)
            if stopped:
                await self._seal(turn.item, [{"role": "system", "origin": "system", "kind": "note",
                                              "text": "stopped by you"}], None)
                self._relay(turn, {"ev": "error", "code": "interrupted", "message": "stopped by you",
                                   "fix": None})
                self._end(turn, 7)
                return
            answer = next((e.get("text") for e in self.script if e.get("ev") == "done"), None)
            rows: list[dict] = []
            if isinstance(answer, str):
                rows.append({"role": "agent", "origin": "agent", "kind": "answer", "text": answer,
                             "model": "sandbox-fake", "session": None, "status": "ok"})
            rows += [{"role": "agent", "origin": "agent", "kind": "draft",
                      "draft_id": d["draft_id"], "option": d.get("option"), "text": d.get("text")}
                     for d in drafts]
            if rows:
                await self._seal(turn.item, rows, None)
            self._end(turn, 0)
        except asyncio.CancelledError:
            self._end(turn, None)
            raise

    async def stop(self, item_id: str) -> bool:
        turn = self._turns.get(item_id)
        if turn is None or turn.finished:
            return False
        self.stops.append(item_id)
        self.release(item_id)
        return True

    async def check_login(self) -> LoginCheck:
        self.login_checks += 1
        if self.seal and self.home is not None and self.login.ok:
            from self_learn import ask as sl_ask
            from self_learn.primitives import chrono

            target = sl_ask.login_ok_path(self.home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"at": chrono.now_iso()}) + "\n", encoding="utf-8")
        return self.login

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()


def build_ask_runner(*, home: Path, publish: Publish, environ: dict[str, str] | None = None) -> AskRunner:
    """The app's runner: the real one, or (``SELF_LEARN_UI_FAKE_ASK=1``,
    the walk world only) the scripted fake writing into that world's
    scratch ledger. Logs one line when the fake is on (§4.7)."""
    e = os.environ if environ is None else environ
    if e.get(FAKE_ASK_ENV) == "1":
        uilog.log(f"{FAKE_ASK_ENV}=1: every ask answers from a scripted fake; no model is called")
        return FakeAskRunner(publish=publish, home=home, seal=True)
    return RealAskRunner(home=home, publish=publish)
