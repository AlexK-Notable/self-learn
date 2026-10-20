"""The session miner's spine: the user message of one session's call
(new-miner plan §3.2; the old U4 spec §5.3 it amends).

The spine is the whole session, from line 1 to the end of the judged range,
as the model first reads it:

1. two fixed lines, :data:`SESSION_OPENINGS`, so both miners halt the
   session miner's own transcripts (the first through the self-prompt
   header rule, the second through the self-learn command-tag rule:
   ``miner.halt_point``);
2. a header: the session id, project folder, first ``cwd``, the number of
   typed turns, the judged range and the subagent logs found;
3. every typed turn ``T<k>`` the person typed, in full, as ``YOU:`` --
   typed turns are never shortened ("all of my reponses from a given
   conversation should always be presented");
4. after each typed turn, its stretch: turns another agent wrote
   (``AGENT-WRITTEN``), relayed messages (``RELAY``), the agent's last
   message (``AGENT``), all in line order, then ``FACTS`` counted by code;
5. rule-situation flags, each under the stretch it matched.

Units. Lines are the session file's 1-based physical lines, numbered as
:mod:`refs` numbers them (``refs._lines``: ``str.splitlines()``), so a line
on the spine is the line a ref names. ``T<k>`` is
``mining.contract.typed_turn_lines`` -- the one definition -- computed with
the run's sends (``provenance.SentIndex``), so a turn an agent wrote (role
``agent``, refs rule 10) is never ``YOU:`` and never a ``T<k>``; it shows in
its stretch as ``AGENT-WRITTEN``. A compact-provenance note is a relay
(refs rule 7a) and never ``YOU:``. Stretch ``k`` is everything after
``T<k>`` up to ``T<k+1>`` (stretch 0 is everything before ``T1``).

Everything entering the spine passes :func:`scan.redact` ("redact at the
tip"), piece by piece, before any shortening (a cut never splits a secret
the scan would have caught whole).

This module reads transcripts only; it writes nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Container, Iterable, Sequence

from .. import provenance, refs
from ..scan import redact
from . import contract

__all__ = [
    "AGENT_WRITTEN_CHARS",
    "CHARS_PER_TOKEN",
    "DEFAULT_SPINE_TOKENS",
    "FACTS_MAX",
    "RELAYS_PER_STRETCH",
    "RELAY_CHARS",
    "SESSION_OPENINGS",
    "Session",
    "Spine",
    "SpineFlag",
    "build_spine",
    "estimate_tokens",
    "judged_range",
    "read_session",
    "skip_reason",
    "subagent_launches",
]

#: The spine's two fixed opening lines. The first is the old miner's own
#: self-prompt header (``miner.SELF_PROMPT_HEADERS[0]``); the second is a
#: self-learn command tag (``miner._COMMAND_SPAN_RE`` matches it). Either
#: one alone makes ``miner.halt_point`` halt a transcript that opens with
#: the spine: the header when the spine is the first typed text, the tag
#: when Claude Code puts its own text ahead of it.
SESSION_OPENINGS: tuple[str, str] = (
    "You are the self-learn transcript miner.",
    "<command-name>self-learn:session-miner</command-name>",
)

#: ``estimate_tokens`` divides characters by this (old spec D10: 2.1 was
#: measured on the steward brief; 2.5 errs toward shortening).
CHARS_PER_TOKEN = 2.5
#: ``miner.spine_tokens``' default (plan §3.2).
DEFAULT_SPINE_TOKENS = 20_000
#: A stretch's FACTS line is at most this long.
FACTS_MAX = 600
#: A relayed message shows its first this-many characters ...
RELAY_CHARS = 200
#: ... and a stretch shows at most this many relays (the last ones: what
#: the person's next turn answers).
RELAYS_PER_STRETCH = 3
#: A turn another agent wrote is shown whole up to this length, and longer
#: ones as their first and last half of it, marked -- the rule the budget
#: applies to an agent message of a new stretch.
AGENT_WRITTEN_CHARS = 2_400
#: How many edited files and failed tool results FACTS names.
FACTS_FILES = 5
FACTS_FAILURES = 5

#: The budget's shortening steps (old spec §5.3), head and tail kept.
_MINED_KEEP = 400
_NEW_KEEP = 1_200

_EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
_LAUNCH_TOOLS = ("Task", "Agent")
_INTERRUPT = "[Request interrupted"


def estimate_tokens(text: str) -> int:
    """``ceil(len(text) / 2.5)`` (old spec D10), in integers."""
    return math.ceil(len(text) * 2 / 5) if text else 0


# ------------------------------------------------------------- the session


@dataclass(frozen=True)
class Session:
    """One session file, read once: its lines as :mod:`refs` numbers them,
    and one parsed entry (or None) per line."""

    path: Path
    session_id: str
    project_dir: str
    lines: tuple[str, ...]
    entries: tuple[dict[str, Any] | None, ...]

    @property
    def file(self) -> str:
        """The path relative to its transcript root: ``<project>/<session>.jsonl``."""
        return str(PurePosixPath(self.project_dir) / self.path.name)

    @property
    def subagent_dir(self) -> Path:
        return self.path.parent / self.session_id / "subagents"


def read_session(path: Path | str) -> Session:
    """Read ``path`` through :mod:`refs`' own line reader, so a line number
    here is a line number there."""
    p = Path(path)
    lines = refs._lines(p)  # pyright: ignore[reportPrivateUsage]
    return Session(
        path=p,
        session_id=p.stem,
        project_dir=p.parent.name,
        lines=lines,
        entries=tuple(refs._entry(raw) for raw in lines),  # pyright: ignore[reportPrivateUsage]
    )


def judged_range(start_line: int, n_lines: int, end: int | None) -> tuple[int, int] | None:
    """The 1-based, inclusive judged lines of a ``miner.SessionSlice``
    (``start_line`` = ``s.start_line``, ``n_lines`` = ``len(s.lines)``) cut
    at ``miner.halt_point(s).end`` (relative to ``s.lines``); None when
    nothing is left to judge (a whole-session halt, or an empty slice)."""
    take = n_lines if end is None else min(end, n_lines)
    if take <= 0:
        return None
    return start_line + 1, start_line + take


# --------------------------------------------------------------- subagents


def _first_user_text(path: Path) -> str | None:
    try:
        lines = refs._lines(path)  # pyright: ignore[reportPrivateUsage]
    except OSError:
        return None
    for raw in lines:
        e = refs._entry(raw)  # pyright: ignore[reportPrivateUsage]
        if e is not None and e.get("type") == "user":
            text = refs._raw_text(e)  # pyright: ignore[reportPrivateUsage]
            if text.strip():
                return text
    return None


def subagent_launches(session: Session, last_line: int | None = None) -> dict[str, int | None]:
    """``{subagent id: the line of the tool use that launched it}`` for every
    log under ``<session>/subagents/``; None when the launch is not found
    within lines 1..``last_line``.

    Linked first by the launch's tool result, whose ``toolUseResult.agentId``
    names the log (key names read from a current transcript, 2026-10-19);
    otherwise by the log's first user text equalling the launch's
    ``input.prompt`` (old spec §5.5, the fallback)."""
    d = session.subagent_dir
    ids = sorted(p.name[len("agent-") : -len(".jsonl")] for p in d.glob("agent-*.jsonl")) if d.is_dir() else []
    if not ids:
        return {}
    stop = len(session.entries) if last_line is None else min(last_line, len(session.entries))
    launch_line: dict[str, int] = {}  # tool_use id -> line
    prompts: dict[str, int] = {}  # launch prompt -> first line
    by_result: dict[str, int] = {}
    for i, e in enumerate(session.entries[:stop], 1):
        if e is None:
            continue
        for b in refs._blocks(e):  # pyright: ignore[reportPrivateUsage]
            if e.get("type") == "assistant" and b.get("type") == "tool_use" and b.get("name") in _LAUNCH_TOOLS:
                launch_line[str(b.get("id"))] = i
                inp = b.get("input")
                prompt = inp.get("prompt") if isinstance(inp, dict) else None
                if isinstance(prompt, str):
                    prompts.setdefault(prompt, i)
            elif e.get("type") == "user" and b.get("type") == "tool_result":
                at = launch_line.get(str(b.get("tool_use_id")))
                tur = e.get("toolUseResult")
                aid = tur.get("agentId") if isinstance(tur, dict) else None
                if at is not None and isinstance(aid, str):
                    by_result.setdefault(aid, at)
    out: dict[str, int | None] = {}
    for sid in ids:
        if sid in by_result:
            out[sid] = by_result[sid]
            continue
        first = _first_user_text(d / f"agent-{sid}.jsonl")
        out[sid] = prompts.get(first) if first is not None else None
    return out


# ---------------------------------------------------------------- planning


def _assistant_text(e: dict[str, Any]) -> str:
    return "\n".join(
        str(b.get("text", ""))
        for b in refs._blocks(e)  # pyright: ignore[reportPrivateUsage]
        if b.get("type") == "text" and str(b.get("text", "")).strip()
    )


def _moment_uuids(
    session: Session, first: int, last: int, typed: Sequence[int]
) -> list[tuple[int, str | None]]:
    """(line, uuid) of every typed turn and assistant text entry in the
    judged lines: the moments the judged-uuid store tracks."""
    typed_set = set(typed)
    out: list[tuple[int, str | None]] = []
    for i in range(first, last + 1):
        e = session.entries[i - 1]
        if e is None:
            continue
        if i in typed_set or (e.get("type") == "assistant" and _assistant_text(e)):
            uid = e.get("uuid")
            out.append((i, uid if isinstance(uid, str) else None))
    return out


def skip_reason(
    session: Session,
    first_line: int,
    last_line: int,
    *,
    judged_uuids: Container[str] = frozenset(),
    sent: provenance.SentIndex | None = None,
) -> str | None:
    """Why a session (not halted: ``miner.halt_point`` decides that first)
    is not called, in the plan's order (§3.1), or None:

    - ``no-typed-turns``: no line 1..``last_line`` is a typed turn (the
      person never typed; program-run sessions are shelved);
    - ``no-marker``: no ``user`` row carries Claude Code's typed-turn marker;
    - ``nothing-new``: the judged lines hold no typed turn and no assistant
      text entry whose uuid is not already judged."""
    entries = session.entries[:last_line]
    typed = contract.typed_turn_lines(entries, sent=sent)
    if not typed:
        return "no-typed-turns"
    if not contract.has_typed_turn_marker(entries):
        return "no-marker"
    moments = _moment_uuids(session, first_line, last_line, typed)
    if not any(uid is None or uid not in judged_uuids for _line, uid in moments):
        return "nothing-new"
    return None


# ------------------------------------------------------------- the spine


@dataclass(frozen=True)
class SpineFlag:
    """A rule-situation flag to place under stretch ``turn`` (the flags
    module finds them; the spine only shows them). ``body`` is the rule's
    text as the model should read it (``Trigger: … — Instruction: …``)."""

    record: str
    scope: str
    turn: int
    basis: str
    body: str


@dataclass(frozen=True)
class Spine:
    """A rendered spine and what the engine and the checker need about it."""

    text: str
    session: Session
    first_line: int
    last_line: int
    #: ``T<k>`` is at line ``typed_lines[k - 1]``.
    typed_lines: tuple[int, ...]
    #: The ``k`` of every typed turn shown as new.
    new_turns: tuple[int, ...]
    #: ``stretch_new[k]``: stretch ``k`` holds a judged line not yet judged.
    stretch_new: tuple[bool, ...]
    #: ``{subagent id: launch line or None}``.
    subagents: dict[str, int | None]
    flags: tuple[SpineFlag, ...]
    tokens_est: int
    over_budget: bool
    redactions: int
    #: Uuids of the typed turns and assistant text entries in the judged
    #: lines: what the engine adds to the judged-uuid store once this
    #: session's output has landed (never earlier).
    moment_uuids: frozenset[str] = field(default_factory=frozenset)

    @property
    def first_turn(self) -> int | None:
        return self.new_turns[0] if self.new_turns else None

    @property
    def last_turn(self) -> int | None:
        return self.new_turns[-1] if self.new_turns else None

    def stretch_of(self, line: int) -> int:
        """The stretch a line belongs to (a typed turn's own line is its stretch)."""
        return contract.turn_of(self.typed_lines, line)


class _Piece:
    """One shortenable message on the spine."""

    def __init__(self, label: str, line: int, text: str, stretch: int, new: bool) -> None:
        self.label, self.line, self.stretch, self.new = label, line, stretch, new
        self.full = text
        self.text = text

    def render(self) -> str:
        return f"{self.label} (L{self.line}): {self.text}"

    def shorten(self, keep: int) -> int:
        """Keep the first and last ``keep`` characters of the full text;
        returns how many characters the rendering lost."""
        n = len(self.full)
        if n <= 2 * keep:
            return 0
        before = len(self.text)
        marker = f"[shortened from {n} chars — open_stretch(after_turn={self.stretch}) shows it whole]"
        self.text = f"{self.full[:keep]} {marker} {self.full[n - keep:]}"
        return max(0, before - len(self.text))


class _Facts:
    def __init__(self, parts: list[str], stretch: int, new: bool) -> None:
        self.parts, self.stretch, self.new = parts, stretch, new
        self.short = False

    def render(self) -> str:
        body = " · ".join(self.parts[:1] if self.short else self.parts)
        line = f"FACTS: {body}"
        return line if len(line) <= FACTS_MAX else line[: FACTS_MAX - 1] + "…"


class _Redactor:
    def __init__(self) -> None:
        self.hits = 0

    def __call__(self, text: str) -> str:
        out, hits = redact(text)
        self.hits += len(hits)
        return out


def _rel(path: str, cwd: str | None) -> str:
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1 :]
    return path


def _clip(text: str, cap: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= cap else text[: cap - 1] + "…"


def _facts(
    session: Session,
    lines: Iterable[int],
    cwd: str | None,
    subagents: dict[str, int | None],
) -> list[str]:
    """The stretch's facts, counted by code (old spec §5.3 item 4)."""
    calls = 0
    edited: list[str] = []
    failed: list[str] = []
    uses: dict[str, tuple[str, str, str | None]] = {}  # tool_use id -> (name, shape, retry key)
    clusters: dict[str, list[int]] = {}  # retry key -> [uses, errors]
    launched: list[int] = []
    interrupted = compacted = False
    for i in lines:
        e = session.entries[i - 1]
        if e is None:
            continue
        if e.get("isCompactSummary") is True:
            compacted = True
        etype = e.get("type")
        for b in refs._blocks(e):  # pyright: ignore[reportPrivateUsage]
            bt = b.get("type")
            if etype == "assistant" and bt == "tool_use":
                calls += 1
                name = str(b.get("name", "?"))
                raw_inp = b.get("input")
                inp: dict[str, Any] = raw_inp if isinstance(raw_inp, dict) else {}
                key = None
                shape = name
                if name == "Bash":
                    cmd = str(inp.get("command", ""))
                    shape = f"Bash `{_clip(cmd, 80)}`"
                    key = "Bash:" + " ".join(cmd.split()[:2])  # miner._norm_command's shape
                    clusters.setdefault(key, [0, 0])[0] += 1
                elif name in _EDIT_TOOLS:
                    target = inp.get("file_path") or inp.get("notebook_path")
                    if isinstance(target, str) and target:
                        rel = _rel(target, cwd)
                        if rel not in edited:
                            edited.append(rel)
                        shape = f"{name} {_clip(rel, 80)}"
                elif name in _LAUNCH_TOOLS:
                    launched.append(i)
                uses[str(b.get("id"))] = (name, shape, key)
            elif etype == "user" and bt == "tool_result":
                use = uses.get(str(b.get("tool_use_id")))
                if b.get("is_error") is True:
                    if use is not None and use[2] is not None:
                        clusters[use[2]][1] += 1
                    failed.append(f"{use[1] if use else 'tool'} (L{i})")
            elif etype == "user" and bt == "text" and str(b.get("text", "")).lstrip().startswith(_INTERRUPT):
                interrupted = True
    parts: list[str] = []
    if calls:
        parts.append(f"{calls} tool call{'s' if calls != 1 else ''}")
    if edited:
        more = f" +{len(edited) - FACTS_FILES} more" if len(edited) > FACTS_FILES else ""
        parts.append("edited: " + ", ".join(edited[:FACTS_FILES]) + more)
    if failed:
        more = f" +{len(failed) - FACTS_FAILURES} more" if len(failed) > FACTS_FAILURES else ""
        parts.append("FAILED: " + ", ".join(failed[:FACTS_FAILURES]) + more)
    retries = [
        f"{k} ×{n} ({errs} error{'s' if errs != 1 else ''})"
        for k, (n, errs) in sorted(clusters.items())
        if n >= 3 and errs >= 1
    ]
    if retries:
        parts.append("retries: " + ", ".join(retries))
    if launched:
        ids = sorted(sid for sid, at in subagents.items() if at in launched)
        unlinked = len(launched) - len({subagents[s] for s in ids})
        shown = ", ".join(ids) + (f" +{unlinked} not linked" if unlinked > 0 and ids else "")
        parts.append(f"subagents: {shown}" if ids else f"subagents: {len(launched)} launched, not linked")
    if interrupted:
        parts.append("interrupted")
    if compacted:
        parts.append("compacted")
    return parts


def _is_shown_relay(e: dict[str, Any], text: str) -> bool:
    """A relay worth a ``RELAY`` line: a ``user`` row with text that is not
    a harness envelope, skill text or reminder (``isMeta``), compaction
    summary or compact-provenance note."""
    if e.get("type") != "user" or not text.strip():
        return False
    if e.get("isMeta") is True or e.get("isCompactSummary") is True or refs.is_compact_provenance_note(e):
        return False
    return not text.lstrip().startswith(refs._HARNESS_ENVELOPES)  # pyright: ignore[reportPrivateUsage]


def build_spine(
    session: Session,
    first_line: int,
    last_line: int,
    *,
    sent: provenance.SentIndex | None = None,
    judged_uuids: Container[str] = frozenset(),
    spine_tokens: int = DEFAULT_SPINE_TOKENS,
    flags: Sequence[SpineFlag] = (),
) -> Spine:
    """Render the spine of ``session`` judged over lines ``first_line`` to
    ``last_line`` (1-based, inclusive; the session is shown from line 1 to
    ``last_line`` and never past it).

    A typed turn is new when its line is judged and its uuid is not in
    ``judged_uuids``; a stretch when one of its judged lines holds an entry
    whose uuid is not. ``sent`` is the run's sends (``refs.sent_index``):
    without it, only tagged and accepted-suggestion turns are recognised as
    agent-written. Over ``spine_tokens`` (estimated, :func:`estimate_tokens`)
    the spine shortens, in this order and until it fits: agent messages of
    already-mined stretches to their first and last 400 characters, longest
    first; facts of already-mined stretches to their first part; agent
    messages of new stretches to their first and last 1,200, longest first.
    Typed turns are never shortened; a spine still over budget is sent
    anyway with ``over_budget`` set."""
    if not 1 <= first_line <= last_line <= len(session.lines):
        raise ValueError(
            f"judged lines {first_line}..{last_line} do not fit a {len(session.lines)}-line session"
        )
    red = _Redactor()
    entries = session.entries[:last_line]
    typed = tuple(contract.typed_turn_lines(entries, sent=sent))
    subagents = subagent_launches(session, last_line)
    cwd = next((e["cwd"] for e in entries if e is not None and isinstance(e.get("cwd"), str) and e["cwd"]), None)

    def judged(i: int) -> bool:
        return first_line <= i <= last_line

    def fresh(i: int) -> bool:
        e = session.entries[i - 1]
        uid = e.get("uuid") if e is not None else None
        return judged(i) and not (isinstance(uid, str) and uid in judged_uuids)

    bounds = [0, *typed, last_line + 1]  # stretch k spans (bounds[k], bounds[k+1])
    stretch_lines = [range(bounds[k] + 1, bounds[k + 1]) for k in range(len(typed) + 1)]
    stretch_new = tuple(any(fresh(i) for i in r) for r in stretch_lines)
    new_turns = tuple(k for k, line in enumerate(typed, 1) if fresh(line))

    # -- header
    ids = sorted(subagents)
    if not new_turns:
        new_part = "no typed turn is new"
    elif len(new_turns) == 1:
        new_part = f"T{new_turns[0]} is new"
    else:
        new_part = f"T{new_turns[0]}–T{new_turns[-1]} are new"
    out: list[Any] = [
        SESSION_OPENINGS[0],
        SESSION_OPENINGS[1],
        red(
            f"SESSION {session.session_id} · project {session.project_dir} · cwd {cwd or 'unknown'}"
            f" · {len(typed)} typed turn{'s' if len(typed) != 1 else ''}"
        ),
        red(
            f"judged: L{first_line}–L{last_line}; {new_part} · subagent logs: "
            + (", ".join(ids) if ids else "none")
        ),
    ]
    pieces: list[_Piece] = []
    facts_all: list[_Facts] = []
    by_stretch: dict[int, list[SpineFlag]] = {}
    for f in flags:
        by_stretch.setdefault(f.turn, []).append(f)

    for k in range(len(typed) + 1):
        if k:
            line = typed[k - 1]
            e = session.entries[line - 1]
            assert e is not None
            state = "new" if k in new_turns else "already mined"
            out.append(f"T{k} · L{line} · {state}")
            out.append("YOU: " + red(refs._raw_text(e)))  # pyright: ignore[reportPrivateUsage]
        new = stretch_new[k]
        shown: list[Any] = []
        relays: list[_Piece] = []
        last_agent: tuple[int, str] | None = None
        for i in stretch_lines[k]:
            e = session.entries[i - 1]
            if e is None:
                continue
            if e.get("type") == "assistant":
                text = _assistant_text(e)
                if text:
                    last_agent = (i, text)
                continue
            role = refs.role_of(e, sent=sent)
            text = refs._raw_text(e)  # pyright: ignore[reportPrivateUsage]
            if role == "agent" and text.strip():
                p = _Piece("AGENT-WRITTEN", i, red(text), k, new)
                p.shorten(AGENT_WRITTEN_CHARS // 2)  # always: an agent's brief can be very long
                pieces.append(p)
                shown.append(p)
            elif role == "relay" and _is_shown_relay(e, text):
                relays.append(_Piece("RELAY", i, _clip(red(text), RELAY_CHARS), k, new))
        shown.extend(relays[-RELAYS_PER_STRETCH:])
        if last_agent is not None:
            p = _Piece("AGENT", last_agent[0], red(last_agent[1]), k, new)
            pieces.append(p)
            shown.append(p)
        shown.sort(key=lambda p: p.line)
        if k == 0 and shown:
            out.append("BEFORE T1:")
        out.extend(shown)
        parts = [red(x) for x in _facts(session, stretch_lines[k], cwd, subagents)]
        if parts:
            fx = _Facts(parts, k, new)
            facts_all.append(fx)
            out.append(fx)
        for f in by_stretch.get(k, []):
            out.append(
                red(f"FLAG {f.record} ({f.scope}) matched this stretch [{f.basis}] — {f.body}")
            )

    def render() -> str:
        return "\n".join(x if isinstance(x, str) else x.render() for x in out) + "\n"

    budget_chars = math.floor(spine_tokens * CHARS_PER_TOKEN)
    text = render()
    if len(text) > budget_chars:
        total = len(text)
        steps: list[tuple[list[Any], Any]] = [
            (sorted((p for p in pieces if not p.new), key=lambda p: -len(p.full)), _MINED_KEEP),
            ([fx for fx in facts_all if not fx.new], None),
            (sorted((p for p in pieces if p.new), key=lambda p: -len(p.full)), _NEW_KEEP),
        ]
        for items, keep in steps:
            for item in items:
                if total <= budget_chars:
                    break
                if keep is None:
                    before = len(item.render())
                    item.short = True
                    total -= before - len(item.render())
                else:
                    total -= item.shorten(keep)
        text = render()
    tokens = estimate_tokens(text)
    moments = _moment_uuids(session, first_line, last_line, typed)
    return Spine(
        text=text,
        session=session,
        first_line=first_line,
        last_line=last_line,
        typed_lines=typed,
        new_turns=new_turns,
        stretch_new=stretch_new,
        subagents=subagents,
        flags=tuple(flags),
        tokens_est=tokens,
        over_budget=tokens > spine_tokens,
        redactions=red.hits,
        moment_uuids=frozenset(uid for _line, uid in moments if uid is not None),
    )
