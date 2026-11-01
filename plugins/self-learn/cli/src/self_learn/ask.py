"""The inbox's "ask about this" agent (attention round, design r2 §3.3;
contracts §4.6, §4.8, §4.10; the user's answer 10, decisions C5 and C8).

    self-learn ask <id> --message-file PATH|- [--stream] [--json]
        0 answered | 2 unknown id | 3 agent unavailable (login/environment
        hold) | 4 would spend money | 5 timeout | 6 turn cap | 7 interrupted
        (SIGTERM) | 1 other failure | 64 usage, a secret in the message, or
        an agent's shell

One question about one inbox item is one seam session on the eighth
surface, ``ask``. The session runs in the item's agent workspace,
``<cache>/workspace/<item-id>/`` (``packet.json`` and ``packet.md`` are
written there first), and continues the item's earlier Claude Code session
(``SessionSpec.resume_session_id``, from ``state.json``) so the agent keeps
what it already read. When that session is gone it starts a fresh one and
gives it the last rows of the item's ledger transcript instead.

**Read-only, four layers.** The ask containment has no write scope and
refuses Bash, Grep, Write, Edit, NotebookEdit, Task, WebFetch and
WebSearch (``invocation.containment_for``); its reads are fenced to the
read roots below, never inside a denied path, never a file whose name or
resolved name is a secret name (``attention_packet.SECRET_DENY``, imported,
never copied); its own tools (MCP server ``selflearn_ask``) read, with two
exceptions -- ``probe`` runs a fixed allowlist of read-only commands, and
``draft_reply`` seals one draft row in its handler; and the session loads
no user settings, hooks, MCP servers or memory.

**Subscription only (C8).** :func:`billing_route` says whether a session
started with an environment would bill money: a provider other than
``anthropic``, an ``ANTHROPIC_API_KEY`` or ``ANTHROPIC_AUTH_TOKEN``, or
``CLAUDE_CODE_USE_BEDROCK``/``CLAUDE_CODE_USE_VERTEX``. The verb checks the
session's FINAL environment (the seam policy's variables over this
process's) before any spawn and refuses with exit 4.

**Records.** The person's question is sealed into the item's workspace
transcript (``workspace.append``) before the model is called; the answer,
each draft and any note after. While the ledger is STOPPED the rows wait in
``pending.jsonl`` and the turn still runs. A message holding a secret is
refused before anything is written or spawned; the answer is scanned again
before it is sealed, and every streamed delta is scanned before it is
relayed (the last :data:`HOLDBACK` characters wait for the next delta).

**Who may ask.** The ask box is the person's: a question is sealed as
their typing (``role: user, origin: typed``). From an agent's shell the
verb refuses (exit 64), so an agent's words are never recorded as theirs.

No test crosses the real model boundary: every test drives this module
through ``invocation.FakeBackend`` (:data:`_backend`).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import fcntl
import fnmatch
import hashlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from . import attention, attention_packet, invocation, model_failures, settings, workspace
from .invocation import failure_class
from .invocation.contract import McpTool, McpToolset, ToolReply
from .ledger import resolve_home
from .primitives import chrono, fsops

__all__ = [
    "ASK_DOCTRINE",
    "SESSION_OPENING",
    "SERVER",
    "add_parser",
    "billing_route",
    "build_toolset",
    "check_login",
    "read_roots",
    "run_ask",
    "spec_billing",
]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNKNOWN = 2
EXIT_UNAVAILABLE = 3
EXIT_MONEY = 4
EXIT_TIMEOUT = 5
EXIT_TURN_CAP = 6
EXIT_INTERRUPTED = 7
EXIT_USAGE = 64

#: The fixed first line of an ask session's first prompt, followed by the
#: item id and a period. `miner.SELF_PROMPT_HEADERS` carries this text, so
#: the nightly miner halts these sessions like the steward's.
SESSION_OPENING = "self-learn ask-about-this session for "
#: The agent's own tools' MCP server.
SERVER = "selflearn_ask"
#: The most of `packet.md` a first prompt carries.
PACKET_PROMPT_MAX = 48_000
#: A fresh session that replaces a lost one is given this many earlier
#: transcript rows, at most this many characters.
REINJECT_ROWS = 12
REINJECT_MAX = 12_000
#: The streamed text not yet relayed: a secret split across two deltas is
#: caught before any of it leaves.
HOLDBACK = 256
#: Tool output bounds.
SEARCH_MAX_LINES = 200
SEARCH_MAX_FILES = 20_000
SEARCH_MAX_FILE_BYTES = 2 * 1024 * 1024
LIST_MAX_ENTRIES = 500
PROBE_MAX_CHARS = 8_000
PROBE_TIMEOUT_SECS = 5.0
STATEMENTS_MAX = 40
CONTEXT_MAX_CHARS = 2_000
HISTORY_MAX = 20
#: The least time a later attempt of one turn is started with (gate r1
#: MINOR 3): every attempt of a turn shares one deadline of
#: ``ask.timeout_secs``, so the UI's watchdog (that timeout plus 30 s)
#: never fires on a turn that is still within its own bound.
MIN_ATTEMPT_SECS = 30.0
#: The note a SIGTERM leaves when it arrives after the turn's own deadline:
#: then it is the UI's watchdog, not the person's Stop.
OVERRAN_NOTE = "stopped: the turn ran past its time limit"
#: The note of the person's own Stop: sealed only when the page wrote the
#: item's :func:`stop_marker` during this turn before it signalled.
STOPPED_NOTE = "stopped by you"
#: The note of any other SIGTERM before the deadline (gate r2 MINOR 1): a
#: UI service stop or restart, a logout, a shutdown. systemd signals every
#: process of the UI's cgroup, so it reaches the verb directly; nothing
#: the person did is recorded.
INTERRUPTED_NOTE = "stopped before it answered"
#: The file the page's Stop writes in the item's agent workspace before it
#: signals the verb's process group (:func:`request_stop`).
STOP_MARKER = "stop-requested"

#: The clock of a turn's deadline; a test replaces it.
_clock = time.monotonic

#: A private key's PEM block (gate r1 MINOR 4). The secret scan's
#: ``private-key`` rule matches the header line only, and a body's short
#: last line passes every other rule, so the whole block -- to its END
#: line, or to the end of the text while no END has come -- is withheld
#: as one span. With no END, only a header that ends its line (as every
#: real key's does, also inside a string's escaped ``\n``) opens a block:
#: a header named inside a sentence keeps the words after it (gate r2
#: NIT 3), and the scan still withholds the header itself.
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"(?:.*?-----END [A-Z ]*PRIVATE KEY-----|(?=[ \t]*(?:\r?\n|(?:\\r)?\\n|\Z)).*\Z)", re.S)
_PEM_WITHHELD = "[redacted: private-key]"


def redact(text: str) -> str:
    """*text* with every secret-scan hit swapped for ``[redacted: <rule>]``
    and every private-key block withheld whole. What this module shows or
    seals goes through here, never through ``redact_text`` alone."""
    return attention_packet.redact_text(_PEM_BLOCK.sub(_PEM_WITHHELD, text))

ASK_DOCTRINE = """\
You are the "ask about this" agent in self-learn's inbox. One person, the owner of this machine,
is deciding one item and asks you about it. The item's full packet is in your first message and in
packet.md in your working directory; read it again whenever you are unsure what the item says.

- You can read; you can never change anything. You have no shell and no write tools. Never say you
  did or will do something to their system, the ledger or a repository.
- Answer from the packet first. When it does not settle the question, look further with your tools
  (record, case, statements, words_in_context, report, ledger_history, status, item, search,
  list_dir, probe, settings_hooks) or Read/Glob inside the ledger, self-learn's cache, the self-learn
  checkout, the person's always-loaded Claude files (~/.claude/CLAUDE.md, rules, hooks), the
  registered projects' canon files and the item's own paths. probe shows what is running and
  installed. Say where you looked, by id or path, and say plainly when something is outside what you
  can see.
- Lead with the answer, in plain words, briefly. Separate what the record shows from what you infer,
  and label a guess as a guess.
- Quote the person's recorded words exactly, with the statement id. Never put your own paraphrase
  in quotation marks.
- Do not decide for them and do not push. If they ask what you would do, give the recommendation
  and the strongest reason against it.
- If they want help wording an answer, call draft_reply with the text (and the option id when it
  matches an offered option). You never send anything; they may edit or send your draft, and it is
  recorded as your draft, not as their words.
- Never tell them to run self-learn commands or edit files to answer; the page has buttons and a
  reply box. The only commands you may give them are the ones only they can run (logging in, a sudo
  command), exactly as the packet states them.
- Never print a credential, token or key, even if a file you read contains one.
- If a question is not about this item, answer briefly only when it bears on this decision.
"""

#: Tests inject `invocation.FakeBackend` here; `None` is the real seam.
_backend: Any = None


# ===================================================================== #
# The money guard (C8)
# ===================================================================== #

_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})


def billing_route(env: Mapping[str, str], *, provider: str = "anthropic") -> str | None:
    """``None`` when a session started with environment *env* would run on
    the person's Claude subscription; otherwise the reason it would bill
    money, naming what would bill. *env* is the session's FINAL
    environment (:func:`spec_billing` builds it); *provider* is the
    resolved provider, ``anthropic`` when the caller has none."""
    if provider != "anthropic":
        return (f"the model provider is {provider}, which bills an account, not your Claude "
                "subscription")
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if str(env.get(key) or "").strip():
            return (f"{key} is set, and Claude Code bills that key before it uses your "
                    "subscription login")
    for key, who in (("CLAUDE_CODE_USE_BEDROCK", "Amazon Bedrock"),
                     ("CLAUDE_CODE_USE_VERTEX", "Google Vertex AI")):
        if str(env.get(key) or "").strip().lower() not in _FALSE_VALUES:
            return f"{key} is set, so Claude Code would bill {who}"
    return None


def spec_billing(spec: invocation.SessionSpec) -> str | None:
    """:func:`billing_route` over *spec*'s final environment: the seam
    policy's variables (the producer's own and the provider's,
    ``CliSessionPolicy.env``) merged over this process's environment, as
    the SDK merges them when it starts Claude Code; and the provider
    resolved for the spec's ledger. Called before any spawn."""
    from . import provider as provider_mod
    from .invocation_sdk import backend as sdk_backend

    try:
        policy_env = sdk_backend.CliSessionPolicy(spec).env()
    except provider_mod.ProviderRefused as exc:
        return f"the model provider is bedrock ({exc})"
    try:
        resolved = provider_mod.resolve(spec.settings_home, spec.surface).provider
    except Exception:  # noqa: BLE001 -- an unreadable provider is not a subscription
        return "the model provider could not be read, so the bill could not be checked"
    return billing_route({**os.environ, **policy_env}, provider=resolved)


# ===================================================================== #
# The read fence
# ===================================================================== #


def checkout_root() -> Path | None:
    """The self-learn checkout this code runs from: the directory holding
    ``docs/`` and ``plugins/`` above this module, or ``None`` for an
    installed copy outside a checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "docs").is_dir() and (parent / "plugins").is_dir():
            return parent
    return None


def read_roots(home: Path, look_at: list[str] | tuple[str, ...] = ()) -> tuple[str, ...]:
    """The ask agent's read roots (design r2 §3.3): the ledger, the cache,
    the self-learn checkout, the registered projects' canon read roots,
    the person's always-loaded Claude files, and the packet's kept
    ``look_at`` paths. ``~/.claude/settings.json`` is never one."""
    from . import hosts

    out: list[str] = [str(home), str(attention.cache_dir(home))]
    root = checkout_root()
    if root is not None:
        out.append(str(root))
    try:
        out += [str(p) for p in hosts.canon_read_roots(hosts.load_hosts(home))]
    except Exception:  # noqa: BLE001 -- an unreadable registry adds no root
        pass
    claude = Path.home() / ".claude"
    out += [str(claude / "CLAUDE.md"), str(claude / "rules"), str(claude / "hooks")]
    out += [str(p) for p in look_at]
    return tuple(dict.fromkeys(out))


def read_denied(home: Path) -> tuple[str, ...]:
    """Other runs' kept sessions, and every :data:`SECRET_DENY` path."""
    return (str(attention.cache_dir(home) / "sessions"), *attention_packet.deny_paths(home))


class _Fence:
    """The own tools' copy of the charter's read fence: the same roots,
    denied paths and denied names, resolved once."""

    def __init__(self, roots: tuple[str, ...], denied: tuple[str, ...], cwd: Path) -> None:
        self.roots = tuple(Path(r).resolve() for r in roots)
        self.denied = tuple(Path(r).resolve() for r in denied)
        self.cwd = cwd

    @staticmethod
    def _inside(target: Path, roots: tuple[Path, ...]) -> bool:
        return any(target == root or root in target.parents for root in roots)

    def denied_path(self, path: Path) -> bool:
        return self._inside(path, self.denied)

    def readable(self, path: Path) -> bool:
        """A file this fence lets the agent read: inside a root, outside
        every denied path, and neither its name nor its resolved name a
        secret name."""
        real = path.resolve()
        return (
            self._inside(real, self.roots) and not self.denied_path(real)
            and not attention_packet.denied_name(path.name)
            and not attention_packet.denied_name(real.name)
        )

    def check(self, raw: object) -> Path:
        """The resolved path *raw* names, or :class:`_Refused` saying why."""
        if not isinstance(raw, str) or not raw.strip():
            raise _Refused("name a path")
        named = Path(raw).expanduser()
        if ".." in named.parts:
            raise _Refused(f"{raw} climbs with '..'")
        if not named.is_absolute():
            named = self.cwd / named
        real = named.resolve()
        if self.denied_path(real):
            raise _Refused(f"{raw} is not readable here (a secret or another run's session)")
        if not self._inside(real, self.roots):
            raise _Refused(f"{raw} is outside what this agent can read")
        return real


class _Refused(ValueError):
    """A tool call the agent can correct; its message is the reply."""


# ===================================================================== #
# The emitter: NDJSON with rolling redaction
# ===================================================================== #


class _Emitter:
    """One turn's events on stdout, one JSON object per line, flushed per
    line. Text deltas pass :meth:`delta`: the whole answer so far is
    scanned and redacted, and only the new part of the redacted text, less
    its last :data:`HOLDBACK` characters, is relayed. If redaction ever
    rewrites text already relayed, deltas stop and ``done`` carries the
    whole redacted answer."""

    def __init__(self, out: TextIO, *, stream: bool) -> None:
        self._out = out
        self._stream = stream
        self._lock = threading.Lock()
        self._raw = ""
        self._shown = ""
        self._diverged = False
        self.events: list[dict] = []

    def event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(event)
            if self._stream:
                # One write of the whole line, then a flush.
                print(json.dumps(event, ensure_ascii=False) + "\n", file=self._out, end="",
                      flush=True)

    def reset_text(self) -> None:
        with self._lock:
            self._raw, self._shown, self._diverged = "", "", False

    def delta(self, text: str) -> None:
        with self._lock:
            self._raw += text
            redacted = redact(self._raw)
            if self._diverged or not redacted.startswith(self._shown):
                self._diverged = True
                return
            upto = len(redacted) - HOLDBACK
            if upto <= len(self._shown):
                return
            new = redacted[len(self._shown):upto]
            self._shown = redacted[:upto]
        self.event({"ev": "delta", "text": new})

    def finish_text(self) -> None:
        """Relay what the hold-back kept, at the end of the turn."""
        with self._lock:
            redacted = redact(self._raw)
            if self._diverged or not redacted.startswith(self._shown):
                return
            new = redacted[len(self._shown):]
            self._shown = redacted
        if new:
            self.event({"ev": "delta", "text": new})

    def on_event(self, event: dict[str, Any]) -> None:
        """`SessionSpec.on_event`: deltas through the redaction; a tool use
        with its target scanned; tool results stay inside (a draft is
        relayed by its own handler)."""
        kind = event.get("ev")
        if kind == "delta" and isinstance(event.get("text"), str):
            self.delta(event["text"])
        elif kind == "tool":
            target = event.get("target")
            self.event({
                "ev": "tool", "name": str(event.get("name") or ""),
                "target": redact(target) if isinstance(target, str) else None,
            })


# ===================================================================== #
# The agent's own tools
# ===================================================================== #

_STMT_ID_RE = re.compile(r"stmt-[0-9a-f]{8}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_OPTION_ID_RE = re.compile(r"opt-[a-z0-9-]{1,48}")
#: `probe`'s allowlist (design r2 §3.3): each form is an argv list with a
#: validated target, never a shell. A target never starts with `-`, so it
#: can never be read as a flag (`--system` is refused by shape).
_UNIT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9@._-]{0,127}\.(?:service|socket|timer|target|path)")
_PKG_RE = re.compile(r"[a-z0-9][a-z0-9@._+-]{0,127}")
_PROBES: dict[str, tuple[re.Pattern[str], Callable[[str], list[str]]]] = {
    "systemctl show": (_UNIT_RE, lambda t: [
        "systemctl", "--user", "show", t,
        "--property=ActiveState,SubState,LoadState,FragmentPath,DropInPaths,"
        "ActiveEnterTimestamp,NRestarts,Result"]),
    "systemctl is-active": (_UNIT_RE, lambda t: ["systemctl", "--user", "is-active", t]),
    "systemctl status": (_UNIT_RE, lambda t: [
        "systemctl", "--user", "status", t, "--no-pager", "--lines=0"]),
    "journalctl": (_UNIT_RE, lambda t: [
        "journalctl", "--user", "-u", t, "-n", "200", "--no-pager", "-o", "short-iso"]),
    "pacman -Q": (_PKG_RE, lambda t: ["pacman", "-Q", t]),
}


def probe_argv(command: object, target: object) -> list[str]:
    """The argv of one allowlisted probe, or :class:`_Refused`."""
    if not isinstance(command, str) or command not in _PROBES:
        raise _Refused(f"probe: {command!r} is not an allowed command; allowed: "
                       + ", ".join(sorted(_PROBES)))
    shape, build = _PROBES[command]
    if not isinstance(target, str) or shape.fullmatch(target) is None:
        raise _Refused(f"probe: {target!r} is not a valid target for {command}")
    return build(target)


def _run_probe(argv: list[str]) -> str:
    """Run one allowlisted probe: argv, no shell, a minimal environment, a
    5-second bound. Module level so a test can replace it."""
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(Path.home())}
    for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECS, env=env,
            stdin=subprocess.DEVNULL, shell=False, check=False,
        )
    except FileNotFoundError:
        return f"{argv[0]}: not installed here"
    except subprocess.TimeoutExpired:
        return f"{argv[0]}: no answer within {PROBE_TIMEOUT_SECS:g} s"
    return f"exit {done.returncode}\n{done.stdout}{done.stderr}"


def _git_log(home: Path, argv_tail: list[str]) -> str:
    """The one git reader of this module: a read-only ``git log``."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat"}
    try:
        done = subprocess.run(
            ["git", "-C", str(home), "log", *argv_tail], capture_output=True, text=True,
            timeout=10, env=env, stdin=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git log failed: {type(exc).__name__}"
    return done.stdout if done.returncode == 0 else f"git log failed: {done.stderr.strip()[:300]}"


def _json(value: object) -> str:
    return redact(json.dumps(value, ensure_ascii=False, indent=1, default=str))


def _schema(properties: dict[str, dict], required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


_STR = {"type": "string"}


class AskTools:
    """The ask agent's own tools for one item. Each tool is a plain
    synchronous method returning text or raising :class:`_Refused`;
    :meth:`toolset` wraps them as async ``McpTool`` handlers that work in
    a thread (`asyncio.to_thread`)."""

    def __init__(
        self, home: Path, item: dict, *, roots: tuple[str, ...], denied: tuple[str, ...],
        cwd: Path, emitter: _Emitter | None = None,
    ) -> None:
        self.home = home
        self.item = item
        self.fence = _Fence(roots, denied, cwd)
        self.emitter = emitter
        self.sealed: list[int] = []
        self.drafts: list[dict] = []

    # -- the ledger

    def record(self, args: dict) -> str:
        from .ledger_ops import LedgerOpsError, find_record_path
        from .records import Record

        lesson_id = str(args.get("id") or "")
        try:
            record = Record.from_path(find_record_path(self.home, lesson_id))
        except (LedgerOpsError, OSError, ValueError) as exc:
            raise _Refused(f"record: no lesson {lesson_id!r} ({type(exc).__name__})") from None
        routing = record.routing if isinstance(record.routing, dict) else {}
        return _json({
            "id": lesson_id, "status": record.status,
            "placement": routing.get("destination"), "routing": routing,
            "text": record.body,
        })

    def case(self, args: dict) -> str:
        from . import cases

        case_id = str(args.get("id") or "")
        try:
            view = cases.show(self.home, case_id, evidence_only=False)
            text = view.to_text()
            frontmatter = view.frontmatter
        except Exception as exc:  # noqa: BLE001 -- a tampered or missing case
            try:
                path = cases._case_path_for_id(self.home, case_id)  # noqa: SLF001
                raw = path.read_bytes()[: attention_packet.MAX_CASE_FILE_BYTES]
            except Exception:  # noqa: BLE001
                raise _Refused(f"case: no case {case_id!r}") from None
            text = (f"(this case failed its freeze-hash check or could not be parsed: "
                    f"{type(exc).__name__}; shown as the file is now)\n"
                    + raw.decode("utf-8", errors="replace"))
            frontmatter = {}
        line = [case_id]
        successor = frontmatter.get("superseded_by")
        while isinstance(successor, str) and successor and len(line) < 10 and successor not in line:
            line.append(successor)
            try:
                successor = cases.show(self.home, successor, evidence_only=False).frontmatter.get(
                    "superseded_by")
            except Exception:  # noqa: BLE001 -- the line ends at a case it cannot read
                break
        predecessor = frontmatter.get("supersedes")
        text += "\n\nLine of successors: " + " -> ".join(line)
        if predecessor:
            text += f"\nSupersedes: {predecessor}"
        return redact(text)

    def statements(self, args: dict) -> str:
        from . import statements as statements_mod

        since = args.get("since") if isinstance(args.get("since"), str) else None
        rows = statements_mod.list_statements(self.home, since=since)
        ids = args.get("ids")
        if isinstance(ids, list) and ids:
            wanted = {str(i) for i in ids}
            rows = [r for r in rows if r.get("id") in wanted]
        query = args.get("query")
        if isinstance(query, str) and query.strip():
            needle = query.strip().lower()
            rows = [r for r in rows if needle in str(r.get("verbatim") or "").lower()]
        rows = rows[-STATEMENTS_MAX:]
        return _json([{
            "id": r.get("id"), "at": r.get("at"), "verbatim": r.get("verbatim"),
            "answers": r.get("answers"), "recorded_by": r.get("recorded_by"),
            "ref": (r.get("source") or {}).get("message_ref"),
        } for r in rows])

    def words_in_context(self, args: dict) -> str:
        from . import statements as statements_mod

        statement_id = str(args.get("statement_id") or "")
        if _STMT_ID_RE.fullmatch(statement_id) is None:
            raise _Refused(f"words_in_context: {statement_id!r} is not a statement id")
        row = next((r for r in statements_mod.list_statements(self.home)
                    if r.get("id") == statement_id), None)
        if row is None:
            raise _Refused(f"words_in_context: no statement {statement_id}")
        ref = str((row.get("source") or {}).get("message_ref") or "")
        text: str | None
        if ref.startswith("workspace:"):
            text = workspace.excerpt(self.home, ref)
        elif ref.startswith("transcript:"):
            from . import refs

            try:
                session, number = ref[len("transcript:"):].rsplit("#L", 1)
                roots = refs.transcript_roots(self.home)
                resolved = refs.resolve(session, line=int(number), roots=roots)
                lines = refs.excerpt(resolved, roots=roots, total_chars=CONTEXT_MAX_CHARS)
                text = "\n".join(f"{r.role}: {t}" for r, t in lines)
            except Exception as exc:  # noqa: BLE001 -- the transcript may be gone
                raise _Refused(f"words_in_context: the transcript could not be read "
                               f"({type(exc).__name__})") from None
        else:
            raise _Refused(f"words_in_context: {statement_id} has no transcript or workspace ref")
        if text is None:
            raise _Refused(f"words_in_context: {ref} did not resolve")
        text = redact(text)
        if len(text) > CONTEXT_MAX_CHARS:
            text = text[: CONTEXT_MAX_CHARS - 1] + "…"
        return f"{statement_id} ({ref}):\n{text}"

    def report(self, args: dict) -> str:
        date = args.get("date")
        folder = self.home / "overseer"
        if isinstance(date, str) and date:
            if _DATE_RE.fullmatch(date) is None:
                raise _Refused("report: date is YYYY-MM-DD")
            path = folder / f"{date}-report.md"
        else:
            path = folder / "latest-report.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            raise _Refused(f"report: no report at {path}") from None
        return redact(text[:40_000])

    def ledger_history(self, args: dict) -> str:
        from .ledger_ops import LedgerOpsError, find_record_path

        target = str(args.get("path_or_id") or "").strip()
        limit = args.get("limit")
        count = min(int(limit), HISTORY_MAX) if isinstance(limit, int) and limit > 0 else HISTORY_MAX
        fmt = ["-n", str(count), "--format=%h %aI %s%n%(trailers:unfold)%n"]
        path: Path | None = None
        if target.startswith("/") or target.startswith("~"):
            real = Path(target).expanduser().resolve()
            if not (real == self.home.resolve() or self.home.resolve() in real.parents):
                raise _Refused("ledger_history: the path must be inside the ledger")
            path = real
        elif target.startswith("lrn-"):
            try:
                path = find_record_path(self.home, target)
            except (LedgerOpsError, OSError, ValueError):
                path = None
        elif target.startswith("case-"):
            from . import cases

            try:
                path = cases._case_path_for_id(self.home, target)  # noqa: SLF001
            except Exception:  # noqa: BLE001
                path = None
        if path is not None:
            out = _git_log(self.home, [*fmt, "--", str(path)])
        elif re.fullmatch(r"[A-Za-z0-9@._-]{3,80}", target):
            out = _git_log(self.home, [*fmt, "--fixed-strings", f"--grep={target}"])
        else:
            raise _Refused("ledger_history: name a ledger path or an id")
        return redact(out.strip() or "(no commits)")

    def status(self, args: dict) -> str:
        del args
        from . import cli

        return _json(cli.status_fast_data(self.home))

    def item_summary(self, args: dict) -> str:
        item_id = str(args.get("id") or "")
        try:
            packet = attention_packet.build(self.home, item_id)
        except attention_packet.UnknownItem:
            raise _Refused(f"item: no inbox item {item_id!r}") from None
        return _json({
            "item": packet.get("item"), "question": packet.get("question"),
            "why_you": packet.get("why_you"), "meanwhile": packet.get("meanwhile"),
            "recommendation": packet.get("recommendation"),
            "options": [{"id": o.get("id"), "label": o.get("label"), "does": o.get("does")}
                        for o in packet.get("options") or []],
            "decided": packet.get("decided"), "answer": packet.get("answer"),
            "evidence": [{"kind": e.get("kind"), "id": e.get("id") or e.get("path")}
                         for e in packet.get("evidence") or []],
        })

    # -- files

    def search(self, args: dict) -> str:
        try:
            regex = re.compile(str(args.get("pattern") or ""))
        except re.error as exc:
            raise _Refused(f"search: bad pattern ({exc})") from None
        if not regex.pattern:
            raise _Refused("search: give a pattern")
        base = self.fence.check(args.get("path"))
        glob = args.get("glob") if isinstance(args.get("glob"), str) else None
        hits: list[str] = []
        skipped = 0
        files = 0

        def scan_file(path: Path) -> bool:
            nonlocal skipped, files
            if glob and not fnmatch.fnmatch(path.name, glob):
                return False
            if not self.fence.readable(path) or not path.resolve().is_file():
                skipped += 1
                return False
            files += 1
            try:
                if path.stat().st_size > SEARCH_MAX_FILE_BYTES:
                    return False
                data = path.read_bytes()
            except OSError:
                return False
            if b"\0" in data[:8192]:
                return False
            in_key = False
            for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                # A private key's lines, BEGIN to END, are withheld whole:
                # the scan alone catches the header and the long body lines,
                # never a short last one.
                key_line = in_key or _PEM_BEGIN.search(line) is not None
                if key_line:
                    in_key = _PEM_END.search(line) is None
                if regex.search(line):
                    shown = _PEM_WITHHELD if key_line else redact(line[:400])
                    hits.append(f"{path}:{number}: {shown}")
                    if len(hits) >= SEARCH_MAX_LINES:
                        return True
            return False

        if base.is_file():
            scan_file(base)
        else:
            for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
                here = Path(dirpath)
                dirnames[:] = sorted(
                    d for d in dirnames
                    if not self.fence.denied_path((here / d).resolve())
                    and not attention_packet.denied_name(d)
                )
                stop = False
                for name in sorted(filenames):
                    if files >= SEARCH_MAX_FILES:
                        stop = True
                        break
                    if scan_file(here / name):
                        stop = True
                        break
                if stop:
                    break
        head = (f"{len(hits)} matching line(s) in {files} file(s) read"
                + (f"; {skipped} file(s) not readable here were skipped" if skipped else "")
                + (f"; stopped at {SEARCH_MAX_LINES} lines" if len(hits) >= SEARCH_MAX_LINES else ""))
        return head + ("\n" + "\n".join(hits) if hits else "")

    def list_dir(self, args: dict) -> str:
        base = self.fence.check(args.get("path"))
        if not base.is_dir():
            raise _Refused(f"list_dir: {base} is not a directory")
        entries: list[dict] = []
        try:
            children = sorted(os.scandir(base), key=lambda e: e.name)
        except OSError as exc:
            raise _Refused(f"list_dir: cannot list {base} ({type(exc).__name__})") from None
        for child in children[:LIST_MAX_ENTRIES]:
            path = Path(child.path)
            try:
                info = os.lstat(path)
            except OSError:
                continue
            kind = ("symlink" if child.is_symlink() else "dir" if child.is_dir(follow_symlinks=False)
                    else "file" if child.is_file(follow_symlinks=False) else "other")
            entry: dict[str, Any] = {
                "name": child.name, "type": kind,
                "mtime": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(
                    timespec="seconds"),
            }
            if kind == "symlink":
                try:
                    entry["target"] = os.readlink(path)
                except OSError:
                    entry["target"] = None
            secret = (attention_packet.denied_name(child.name)
                      or self.fence.denied_path(path.resolve()))
            if secret:
                entry["readable"] = False
            else:
                entry["size"] = info.st_size
            entries.append(entry)
        more = len(children) - LIST_MAX_ENTRIES
        return _json({"path": str(base), "entries": entries,
                      "more": more if more > 0 else 0})

    def probe(self, args: dict) -> str:
        argv = probe_argv(args.get("command"), args.get("target"))
        out = _run_probe(argv)
        if len(out) > PROBE_MAX_CHARS:
            out = out[:PROBE_MAX_CHARS] + "\n… (cut at 8,000 characters)"
        return redact(f"$ {' '.join(argv)}\n{out}")

    def settings_hooks(self, args: dict) -> str:
        del args
        path = Path.home() / ".claude" / "settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _json({"hooks": None, "note": f"no {path}"})
        except (OSError, ValueError) as exc:
            raise _Refused(f"settings_hooks: {path} could not be read ({type(exc).__name__})") from None
        hooks = data.get("hooks") if isinstance(data, dict) else None
        return _json({"hooks": hooks})

    # -- the one sealing tool

    def draft_reply(self, args: dict) -> str:
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise _Refused("draft_reply: give the draft's text")
        option = args.get("option")
        offered = {str(o.get("id")) for o in self.item.get("options") or [] if o.get("id")}
        if option in ("", None):
            option = None
        elif not isinstance(option, str) or option not in offered:
            raise _Refused(f"draft_reply: {option!r} is not an offered option; offered: "
                           + (", ".join(sorted(offered)) or "none"))
        draft_id = "drf-" + uuid.uuid4().hex[:8]
        row = {"role": "agent", "origin": "agent", "kind": "draft", "draft_id": draft_id,
               "option": option, "text": text}
        sealed = workspace.append(self.home, str(self.item["id"]), [row],
                                  header=_header(self.item))
        self.sealed += sealed
        shown = redact(text)
        self.drafts.append({"draft_id": draft_id, "option": option, "text": shown})
        if self.emitter is not None:
            self.emitter.event({"ev": "draft", "draft_id": draft_id, "option": option,
                                "text": shown})
        kept = "sealed" if sealed else "kept on this machine until the ledger is repaired"
        return (f"draft {draft_id} offered to the person ({kept}); they may edit it or send it, "
                "and it is recorded as your draft")

    # -- the toolset

    _TOOLS: tuple[tuple[str, str, dict, str], ...] = (
        ("record", "A lesson's full text, status, placement and destination.",
         _schema({"id": _STR}, ("id",)), "record"),
        ("case", "A case file (full view) and its line of successors.",
         _schema({"id": _STR}, ("id",)), "case"),
        ("statements", "The person's recorded statements (verbatim, id, date, what each "
         "answers), at most 40; filter by ids, a text query, or since a date.",
         _schema({"ids": {"type": "array", "items": _STR}, "query": _STR, "since": _STR}),
         "statements"),
        ("words_in_context", "The transcript or workspace lines around one statement, roles "
         "labelled, at most 2,000 characters.",
         _schema({"statement_id": _STR}, ("statement_id",)), "words_in_context"),
        ("report", "An overseer weekly report (the latest by default).",
         _schema({"date": _STR}), "report"),
        ("ledger_history", "The ledger's git log subjects and trailers for one ledger path or "
         "id (at most 20 commits); never file text or a diff.",
         _schema({"path_or_id": _STR, "limit": {"type": "integer"}}, ("path_or_id",)),
         "ledger_history"),
        ("status", "self-learn's status (the data of `status --json --fast`).",
         _schema({}), "status"),
        ("item", "Another inbox item's packet summary.",
         _schema({"id": _STR}, ("id",)), "item_summary"),
        ("search", "Python-regex search of files under a path inside your read roots; secret "
         "files, other runs' sessions and binary files are skipped; at most 200 lines.",
         _schema({"pattern": _STR, "path": _STR, "glob": _STR}, ("pattern", "path")),
         "search"),
        ("list_dir", "One directory's entries inside your read roots: name, type, size, mtime "
         "and symlink target.", _schema({"path": _STR}, ("path",)), "list_dir"),
        ("probe", "One read-only system command: 'systemctl show', 'systemctl is-active', "
         "'systemctl status' or 'journalctl' with a user unit name (e.g. foo.service), or "
         "'pacman -Q' with a package name.",
         _schema({"command": {"type": "string", "enum": sorted(_PROBES)}, "target": _STR},
                 ("command", "target")), "probe"),
        ("settings_hooks", "The hooks key of ~/.claude/settings.json, and nothing else.",
         _schema({}), "settings_hooks"),
        ("draft_reply", "Offer the person a draft reply (and the option id when it matches an "
         "offered option). It is recorded as your draft; you never send anything.",
         _schema({"text": _STR, "option": _STR}, ("text",)), "draft_reply"),
    )

    def toolset(self) -> McpToolset:
        def wrap(method: Callable[[dict], str]):
            async def handler(args: dict[str, Any]) -> ToolReply:
                try:
                    return ToolReply(await asyncio.to_thread(method, args))
                except _Refused as exc:
                    return ToolReply(str(exc), is_error=True)
            return handler

        return McpToolset(server=SERVER, tools=tuple(
            McpTool(name=name, description=description, input_schema=schema,
                    handler=wrap(getattr(self, attr)), read_only=(name != "draft_reply"))
            for name, description, schema, attr in self._TOOLS
        ))


def build_toolset(home: Path, item: dict, *, roots: tuple[str, ...], denied: tuple[str, ...],
                  cwd: Path, emitter: _Emitter | None = None) -> tuple[AskTools, McpToolset]:
    tools = AskTools(home, item, roots=roots, denied=denied, cwd=cwd, emitter=emitter)
    return tools, tools.toolset()


def allowed_tools(toolset: McpToolset) -> str:
    return ",".join(("Read", "Glob", *toolset.qualified_names))


def ask_containment(
    home: Path, toolset: McpToolset, look_at: list[str] | tuple[str, ...] = (),
) -> invocation.Containment:
    """The ask session's containment (design r2 §3.3, layer 1): Read, Glob
    and the own tools allowed; the refused tools fixed by
    `containment_for`; no write scope; reads fenced to :func:`read_roots`,
    never inside :func:`read_denied`, never a secret file name."""
    return invocation.containment_for(
        "ask", allowed_tools=allowed_tools(toolset), read_roots=read_roots(home, look_at),
        read_denied=read_denied(home), read_denied_names=attention_packet.SECRET_DENY.names,
    )


# ===================================================================== #
# The verb
# ===================================================================== #


class _Interrupted(BaseException):
    """SIGTERM during a turn (the page's Stop, the watchdog, or a service
    stop; the note tells them apart). A BaseException, so no
    `except Exception` on the way up mistakes it for a failure; the seam's
    `finally` still runs its kill ladder and clears the sidecar."""


def _header(item: dict) -> dict:
    return {"item_kind": item.get("kind"), "subject": item.get("subject"),
            "title": item.get("title")}


def workspace_dir(home: Path, item_id: str) -> Path:
    return attention.cache_dir(home) / "workspace" / item_id


def _volatile_free(packet: dict) -> dict:
    """*packet* without what changes on every turn (its time, the
    conversation's count, the size line), so a digest names real changes."""
    out = {k: v for k, v in packet.items() if k not in ("generated_at", "conversation", "limits")}
    item = out.get("item")
    if isinstance(item, dict):
        out["item"] = {k: v for k, v in item.items() if k not in ("conversation", "seen")}
    return out


def packet_digest(packet: dict) -> str:
    return hashlib.sha256(
        json.dumps(_volatile_free(packet), sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _changed_fields(old: dict | None, new: dict) -> list[str]:
    if not isinstance(old, dict):
        return []
    a, b = _volatile_free(old), _volatile_free(new)
    return sorted(k for k in set(a) | set(b)
                  if json.dumps(a.get(k), sort_keys=True) != json.dumps(b.get(k), sort_keys=True))


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_cache(path: Path, text: str) -> None:
    """The one writer of this module's files, all under the XDG cache: the
    item's agent workspace (``packet.json``, ``packet.md``,
    ``state.json``) and ``attention/login-ok.json``. Never ledger truth."""
    fsops.atomic_write(path, text, fsync=False)


def _write_json(path: Path, data: dict) -> None:
    _write_cache(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _drop_cache(path: Path) -> None:
    """The one remover of this module's cache files: the item's
    :data:`STOP_MARKER`. Never ledger truth."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def stop_marker(home: Path, item_id: str) -> Path:
    return workspace_dir(home, item_id) / STOP_MARKER


def request_stop(home: Path, item_id: str) -> None:
    """The person pressed Stop on *item_id*'s turn. The page (``AskRunner``)
    calls this before it sends SIGTERM to the verb's process group; only
    then does the verb seal :data:`STOPPED_NOTE`. A SIGTERM without it is
    not theirs (a restart, a logout, a shutdown) and seals
    :data:`INTERRUPTED_NOTE`. An id that is not an inbox item id is ignored
    (ask-agent gate r3 NIT 2, at integration): the path is built from it."""
    if workspace.ITEM_ID_RE.fullmatch(item_id or "") is None:
        return
    path = stop_marker(home, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_cache(path, chrono.now_iso() + "\n")


def _take_stop(path: Path) -> bool:
    """Whether the person's Stop marker is present; it is removed."""
    present = path.exists()
    _drop_cache(path)
    return present


def _fallback_packet(home: Path, item_id: str, why: str) -> dict | None:
    item = attention.find(home, item_id)
    if item is None:
        return None
    public = attention.public(item)
    return {"packet_version": attention_packet.PACKET_VERSION, "generated_at": chrono.now_iso(),
            "item": public, "question": public.get("title"), "why_you": None,
            "meanwhile": public.get("meanwhile"), "recommendation": None,
            "options": public.get("options") or [], "alternatives": [], "plan": None,
            "decided": None, "undo": None, "evidence": [], "more": [], "pointers": [],
            "look_at": [], "conversation": public.get("conversation"), "answer": public.get("answer"),
            "limits": {"bytes": 0, "truncated": [f"the full packet could not be built: {why}"]}}


def _render_rows(rows: list[dict]) -> str:
    labels = {"user": "the person", "agent": "you", "system": "self-learn"}
    lines: list[str] = []
    for row in rows:
        text = row.get("text")
        if text is None and row.get("redacted"):
            text = f"[redacted: {row['redacted']}]"
        if text is None and row.get("option"):
            text = f"(chose {row['option']})"
        lines.append(f"[{labels.get(str(row.get('role')), row.get('role'))}, {row.get('kind')}] "
                     f"{text if text is not None else ''}")
    out = "\n".join(lines)
    return out[-REINJECT_MAX:]


def _first_prompt(item_id: str, packet_md: str, message: str, earlier: list[dict]) -> str:
    parts = [f"{SESSION_OPENING}{item_id}.", "", packet_md[:PACKET_PROMPT_MAX].rstrip(), ""]
    if earlier:
        parts += ["Earlier in this conversation (from the record):",
                  _render_rows(earlier[-REINJECT_ROWS:]), ""]
    parts.append(f"The person asks: {message}")
    return "\n".join(parts)


_RESUME_GONE = re.compile(
    r"no conversation found|conversation[^\n]{0,40}not found|session[^\n]{0,40}not found"
    r"|could not resume|cannot resume|unable to resume|failed to resume", re.I)


def _resume_failed(outcome: object) -> bool:
    if getattr(outcome, "ok", False):
        return False
    return bool(_RESUME_GONE.search(str(getattr(outcome, "detail", "") or "")))


def _resume_dead(outcome: object) -> bool:
    """A resumed attempt that failed with no turn made and an
    ``unclassified`` failure: the session it named cannot be continued
    (gone, pruned, unloadable), whatever Claude Code's words for it. A
    timeout, a login or network failure, or a turn that ran keeps it."""
    if getattr(outcome, "ok", False) or getattr(outcome, "failure", None) == "timeout":
        return False
    if getattr(outcome, "turns", None):
        return False
    return failure_class.outcome_class(outcome) == "unclassified"


def _bounded(spec: invocation.SessionSpec, deadline: float) -> invocation.SessionSpec:
    """*spec* with only the time left before the turn's *deadline*."""
    return dataclasses.replace(spec, timeout=max(deadline - _clock(), 1.0))


def _resolve_timeout(home: Path) -> float:
    value, _source = settings.resolve_setting(home, settings.by_name("ask.timeout_secs"))
    return float(value) if isinstance(value, (int, float)) and value > 0 else 300.0


def _model(home: Path) -> str | None:
    from . import provider

    try:
        return provider.model_for("ask", home=home)
    except Exception:  # noqa: BLE001 -- only the start event names it
        return None


class _TurnLock:
    """At most one turn per item: a non-blocking ``flock`` on the item's
    workspace folder."""

    def __init__(self, folder: Path) -> None:
        self._path = folder / "turn.lock"
        self._fd: int | None = None

    def acquire(self) -> bool:
        self._fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._fd)
            self._fd = None
            return False
        return True

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


def _seal(home: Path, item: dict, rows: list[dict]) -> list[int]:
    return workspace.append(home, str(item["id"]), rows, header=_header(item))


def _fail(emitter: _Emitter, err: TextIO, code: str, message: str, exit_code: int,
          *, fix: str | None = None) -> int:
    emitter.event({"ev": "error", "code": code, "message": message, "fix": fix})
    print(f"self-learn ask: {message}" + (f" -- {fix}" if fix else ""), file=err)
    return exit_code


def run_ask(home: Path, item_id: str, message: str, *, stream: bool = False,
            out: TextIO | None = None, err: TextIO | None = None) -> tuple[int, _Emitter]:
    """One turn of the item's conversation. Returns the exit code and the
    emitter (its ``events`` are every event of the turn, streamed or
    not)."""
    out_: TextIO = sys.stdout if out is None else out
    err_: TextIO = sys.stderr if err is None else err
    return _run_ask(home, item_id, message, stream=stream, out=out_, err=err_)


def _run_ask(home: Path, item_id: str, message: str, *, stream: bool, out: TextIO,
             err: TextIO) -> tuple[int, _Emitter]:
    # One deadline for the whole turn, every attempt included, counted from
    # the verb's start as the UI's watchdog counts from its spawn.
    started = _clock()
    emitter = _Emitter(out, stream=stream)
    if settings.agent_caller():
        return _fail(
            emitter, err, "failed",
            "refused: the ask box is the person's, and a question is recorded as their typing; "
            "an agent asks with its own tools (agent shell detected: "
            f"{', '.join(settings.agent_caller_markers())})", EXIT_USAGE), emitter
    message = message.strip()
    if not message:
        return _fail(emitter, err, "failed", "the message is empty", EXIT_USAGE), emitter
    rule = workspace.secret_rule(message)
    if rule is not None:
        return _fail(emitter, err, "secret",
                     f"the message looks like it holds a secret ({rule}); nothing was sent or "
                     "recorded", EXIT_USAGE), emitter
    if workspace.ITEM_ID_RE.fullmatch(item_id or "") is None:
        return _fail(emitter, err, "failed", f"unknown item {item_id!r}", EXIT_UNKNOWN), emitter
    try:
        packet = attention_packet.build(home, item_id)
    except attention_packet.UnknownItem:
        return _fail(emitter, err, "failed", f"unknown or expired item {item_id}",
                     EXIT_UNKNOWN), emitter
    except Exception as exc:  # noqa: BLE001 -- the agent can still answer from the item
        fallback = _fallback_packet(home, item_id, f"{type(exc).__name__}: {exc}")
        if fallback is None:
            return _fail(emitter, err, "failed", f"unknown or expired item {item_id}",
                         EXIT_UNKNOWN), emitter
        packet = fallback
    item = dict(packet.get("item") or {})
    item.setdefault("id", item_id)

    folder = workspace_dir(home, item_id)
    folder.mkdir(parents=True, exist_ok=True)
    previous_packet = _read_json(folder / "packet.json")
    packet_md = attention_packet.render_md(packet)
    _write_json(folder / "packet.json", packet)
    _write_cache(folder / "packet.md", packet_md)

    roots = read_roots(home, list(packet.get("look_at") or []))
    denied = read_denied(home)
    tools, toolset = build_toolset(home, item, roots=roots, denied=denied, cwd=folder,
                                   emitter=emitter)
    containment = ask_containment(home, toolset, list(packet.get("look_at") or []))
    sidecar_key = item_id[len("att-"):]
    model = _model(home)
    timeout_secs = _resolve_timeout(home)
    deadline = started + timeout_secs
    log_lines: list[str] = []
    base_spec = invocation.SessionSpec(
        surface="ask", prompt="", cwd=folder, timeout=timeout_secs,
        containment=containment, log=log_lines.append, label="", doctrine=ASK_DOCTRINE,
        ledger_home=home, extra_env=invocation.NO_AUTO_MEMORY_ENV, transcript_group=item_id,
        mcp_toolset=toolset, sidecar_key=sidecar_key, skip_orphan_sweep=True,
        on_event=emitter.on_event,
    )
    reason = spec_billing(base_spec)
    if reason is not None:
        return _fail(emitter, err, "money",
                     f"not asked: {reason}. Nothing was sent; the ask agent runs only on your "
                     "Claude subscription", EXIT_MONEY), emitter

    lock = _TurnLock(folder)
    if not lock.acquire():
        return _fail(emitter, err, "busy", "a question about this item is already being "
                     "answered", EXIT_FAILED), emitter
    # A Stop marker left from an earlier turn (one that ended as the page
    # wrote it) is not this turn's.
    marker = stop_marker(home, item_id)
    _drop_cache(marker)
    # SIGTERM (the page's Stop) interrupts the model call only; the handler
    # is put back before anything is sealed after it.
    handler_box: list[Any] = []

    def _restore_term() -> None:
        while handler_box:
            previous = handler_box.pop()
            signal.signal(signal.SIGTERM, previous if previous is not None else signal.SIG_DFL)

    try:
        from . import gitops

        try:
            question_t = _seal(home, item, [{"role": "user", "origin": "typed",
                                             "kind": "question", "text": message}])
        except gitops.GitOpsError as exc:
            return _fail(emitter, err, "failed", f"the question could not be recorded ({exc}); "
                         "nothing was sent", EXIT_FAILED), emitter
        sealed = list(question_t)
        state = _read_json(folder / "state.json") or {}
        session_id = state.get("session_id") if isinstance(state.get("session_id"), str) else None
        digest = packet_digest(packet)
        # The record before this question: every row but the header and the
        # question itself (the last pending row while the ledger is STOPPED).
        shown_rows = [r for r in workspace.rows(home, item_id) if r.get("kind") != "header"]
        earlier = ([r for r in shown_rows if r.get("t") not in question_t] if question_t
                   else shown_rows[:-1])
        if session_id is not None:
            changed = (_changed_fields(previous_packet, packet)
                       if state.get("packet_digest") != digest else [])
            note = (f"The item changed since your last answer: {', '.join(changed)}. packet.md "
                    "holds the current version.\n\n" if changed else "")
            prompt = f"{note}The person asks: {message}"
            spec = dataclasses.replace(base_spec, prompt=prompt, resume_session_id=session_id)
            resumed, reinjected = True, False
        else:
            spec = dataclasses.replace(
                base_spec, prompt=_first_prompt(item_id, packet_md, message, earlier))
            resumed, reinjected = False, bool(earlier)
        turn = question_t[0] if question_t else None
        emitter.event({"ev": "start", "item": item_id, "turn": turn, "session": session_id,
                       "resumed": resumed, "reinjected": reinjected, "model": model})

        def _on_term(signum, frame):  # noqa: ARG001 -- signal handler signature
            raise _Interrupted()

        if threading.current_thread() is threading.main_thread():
            handler_box.append(signal.signal(signal.SIGTERM, _on_term))
        try:
            from .invocation_sdk import lifecycle

            lifecycle.sweep_orphan("ask", sidecar_key, log_lines.append)
            outcome = invocation.write_session(_bounded(spec, deadline), backend=_backend)
            if (resumed and _resume_failed(outcome)
                    and deadline - _clock() >= MIN_ATTEMPT_SECS):
                emitter.reset_text()
                spec = dataclasses.replace(
                    base_spec, prompt=_first_prompt(item_id, packet_md, message, earlier),
                    resume_session_id=None)
                resumed, reinjected, session_id = False, True, None
                emitter.event({"ev": "start", "item": item_id, "turn": turn, "session": None,
                               "resumed": False, "reinjected": True, "model": model})
                outcome = invocation.write_session(_bounded(spec, deadline), backend=_backend)
            if (model_failures.should_retry(outcome)
                    and deadline - _clock()
                    >= model_failures.TRANSIENT_BACKOFF_SECS + MIN_ATTEMPT_SECS):
                model_failures.backoff()
                emitter.reset_text()
                # The page starts the bubble again (gate r1 NIT 7).
                emitter.event({"ev": "start", "item": item_id, "turn": turn,
                               "session": session_id if resumed else None,
                               "resumed": resumed, "reinjected": reinjected, "model": model})
                outcome = invocation.write_session(_bounded(spec, deadline), backend=_backend)
        except _Interrupted:
            _restore_term()
            # The person's Stop leaves its marker before the signal (gate r2
            # MINOR 1); past the turn's own deadline an unmarked SIGTERM is
            # the UI's watchdog; before it, a service stop or restart, a
            # logout or a shutdown. Only the first is the person's act.
            if _take_stop(marker):
                note = STOPPED_NOTE
            elif _clock() >= deadline:
                note = OVERRAN_NOTE
            else:
                note = INTERRUPTED_NOTE
            sealed += tools.sealed
            sealed += _seal(home, item, [{"role": "system", "origin": "system", "kind": "note",
                                          "text": note}])
            _save_state(folder, state, session_id, digest)
            return _fail(emitter, err, "interrupted", note, EXIT_INTERRUPTED), emitter
        _restore_term()
        sealed += tools.sealed
        new_session = getattr(outcome, "session_id", None)
        if resumed and _resume_dead(outcome):
            # The resumed session failed before any turn for no reason the
            # classifier knows (gate r1 MINOR 2): never resume it again; the
            # next question starts afresh from the record.
            session_id = None
        elif isinstance(new_session, str) and new_session:
            session_id = new_session
        if outcome.ok:
            emitter.finish_text()
            raw = outcome.stdout or ""
            shown = redact(raw)
            row: dict[str, Any] = {"role": "agent", "origin": "agent", "kind": "answer",
                                   "text": shown, "model": model, "session": session_id,
                                   "status": "ok"}
            if shown != raw:
                row["redacted"] = workspace.secret_rule(raw) or "secret"
            answer_t = _seal(home, item, [row])
            sealed += answer_t
            _save_state(folder, state, session_id, digest, answered=True)
            emitter.event({"ev": "done", "turn": answer_t[0] if answer_t else None,
                           "text": shown, "session": session_id, "sealed": sealed})
            if not stream:
                print(shown, file=out)
            return EXIT_OK, emitter
        code, exit_code, text, fix = _failure(outcome, home)
        sealed += _seal(home, item, [{"role": "system", "origin": "system", "kind": "note",
                                      "text": text}])
        _save_state(folder, state, session_id, digest)
        return _fail(emitter, err, code, text, exit_code, fix=fix), emitter
    finally:
        _restore_term()
        _drop_cache(marker)
        lock.release()


def _save_state(folder: Path, state: dict, session_id: str | None, digest: str, *,
                answered: bool = False) -> None:
    turns = int(state.get("turns") or 0) + (1 if answered else 0)
    _write_json(folder / "state.json", {"session_id": session_id, "packet_digest": digest,
                                        "turns": turns, "last_at": chrono.now_iso()})


def _failure(outcome: object, home: Path) -> tuple[str, int, str, str | None]:
    """``(error code, exit code, the system note, fix)`` of a failed turn."""
    detail = str(getattr(outcome, "detail", "") or "")
    if getattr(outcome, "failure", None) == "timeout":
        seconds = _resolve_timeout(home)
        return ("timeout", EXIT_TIMEOUT,
                f"the agent did not answer within {seconds:g} s; ask again, or ask something "
                "narrower", None)
    if getattr(outcome, "result_subtype", None) == "error_max_turns":
        return ("turn-cap", EXIT_TURN_CAP,
                "the agent stopped at its turn limit before answering; ask something narrower",
                None)
    klass = failure_class.outcome_class(outcome)
    cause = redact(detail.strip()[:300]) or "the model call failed"
    if klass == "environment":
        fix = failure_class.hold_fix(detail)
        code = "login" if fix in (failure_class.LOGIN_FIX, failure_class.API_KEY_FIX) else "failed"
        return code, EXIT_UNAVAILABLE, f"the agent could not answer: {cause}", fix
    return "failed", EXIT_FAILED, f"the agent could not answer: {cause}", None


# ===================================================================== #
# check-login (`self-learn attention check-login`)
# ===================================================================== #


def login_ok_path(home: Path) -> Path:
    return attention.cache_dir(home) / "attention" / "login-ok.json"


def check_login(home: Path, *, out: TextIO | None = None, err: TextIO | None = None) -> int:
    """One one-turn ``ask``-surface session ("Reply with OK.", one turn, no
    tools). On success it writes ``login-ok.json``, which ends an open
    ``hold.credentials`` item at once. 0 login works | 3 login broken (the
    fix is printed) | 4 would spend money | 1 any other failure."""
    out_: TextIO = sys.stdout if out is None else out
    err_: TextIO = sys.stderr if err is None else err
    return _check_login(home, out=out_, err=err_)


def _check_login(home: Path, *, out: TextIO, err: TextIO) -> int:
    folder = attention.cache_dir(home) / "workspace" / "check-login"
    folder.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []
    containment = invocation.containment_for(
        "ask", allowed_tools="", read_roots=(str(folder),), read_denied=read_denied(home),
        read_denied_names=attention_packet.SECRET_DENY.names,
    )
    spec = invocation.SessionSpec(
        surface="ask", prompt="Reply with OK.", cwd=folder, timeout=min(_resolve_timeout(home), 120.0),
        containment=containment, log=log_lines.append, ledger_home=home, max_turns=1,
        extra_env=invocation.NO_AUTO_MEMORY_ENV, transcript_group="check-login",
        sidecar_key="check-login", skip_orphan_sweep=True,
    )
    reason = spec_billing(spec)
    if reason is not None:
        print(f"self-learn attention check-login: not checked: {reason}. Nothing was sent.",
              file=err)
        return EXIT_MONEY
    from .invocation_sdk import lifecycle

    lifecycle.sweep_orphan("ask", "check-login", log_lines.append)
    outcome = invocation.write_session(spec, backend=_backend)
    if outcome.ok:
        target = login_ok_path(home)
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_json(target, {"at": chrono.now_iso()})
        print("attention check-login: the login works; held jobs run on their next schedule",
              file=out)
        return EXIT_OK
    _code, exit_code, text, fix = _failure(outcome, home)
    if exit_code == EXIT_UNAVAILABLE:
        print(f"self-learn attention check-login: {text}" + (f" -- fix: {fix}" if fix else ""),
              file=err)
        return EXIT_UNAVAILABLE
    print(f"self-learn attention check-login: {text}", file=err)
    return EXIT_FAILED


# ===================================================================== #
# CLI
# ===================================================================== #


def add_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "ask", help="ask the inbox's read-only agent about one item (the person's question)",
    )
    parser.add_argument("id", metavar="ID")
    parser.add_argument("--message-file", required=True, dest="message_file",
                        help="the question, from a file or - for stdin")
    parser.add_argument("--stream", action="store_true",
                        help="NDJSON events on stdout as they come")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="one JSON object at the end: the done or error event")
    parser.set_defaults(_ask_dispatch=dispatch)
    return parser


def dispatch(args) -> int:
    home = resolve_home()
    try:
        if args.message_file == "-":
            message = sys.stdin.read()
        else:
            message = Path(args.message_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"self-learn ask: cannot read the message: {exc}", file=sys.stderr)
        return EXIT_USAGE
    # --json without --stream: the turn's own lines are not shown, only the
    # final object below; they go to an in-memory sink (one turn's text), so
    # nothing is opened for writing (the raw-write gate).
    sink: TextIO = sys.stdout if not args.as_json or args.stream else io.StringIO()
    try:
        code, emitter = run_ask(home, args.id, message, stream=args.stream, out=sink)
    finally:
        if sink is not sys.stdout:
            sink.close()
    if args.as_json and not args.stream:
        final = next((e for e in reversed(emitter.events) if e.get("ev") in ("done", "error")),
                     {"ev": "error", "code": "failed", "message": "no result", "fix": None})
        print(json.dumps({**final, "exit": code}, ensure_ascii=False))
    return code
