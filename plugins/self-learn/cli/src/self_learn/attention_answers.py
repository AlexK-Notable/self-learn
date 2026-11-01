"""What the person's answer in the inbox does (attention round, design r2
§3.4; contracts §4.4, §4.6).

The verbs the inbox's buttons and reply box run, and their library halves:

* :func:`answer` (``self-learn attention answer``): an option click, words
  typed in the reply box, an agent's draft sent from the page, or (from an
  agent's shell) the person's words relayed with the transcript line they
  were typed on. Every form is recorded honestly (§3.4.1): typed words are a
  statement citing the item's workspace transcript row (``workspace:<id>#T<n>``);
  a click, an agent draft (sent as is or edited) and a reply that holds 40
  or more characters of the agent's own text are **choices**
  (``attention/choices.jsonl``), never the person's words. Only a click on
  an option whose ``effect`` is ``approve`` approves a plan (critique 1).
* :func:`run` (``attention run``): an approved plan is carried out by an
  interactive Claude Code session in a terminal the person can see, launched
  with ``systemd-run --user`` and handed :data:`RUN_BRIEF`. Never from an
  agent's shell, never when the session would bill money.
* :func:`fix` (``attention fix``): "Restart self-learn" on a ``broken.host``
  item: ``systemctl --user reset-failed`` then ``restart`` of
  ``self-learn-host.service`` only.
* :func:`stop` (``attention stop``, follow-ups 2): "Stop it" on approved
  work a session claimed in the terminal the page opened: stops that unit
  and clears the claim, so the person can change their answer.
* :func:`claim` / :func:`done` (``attention claim|done``): the carrying-out
  session's own verbs.
* :func:`undo` (``attention undo [--redo]``): the one-step inverse of a
  decided item (§3.4.6).

Agent shells (``settings.agent_caller()``) are held to §3.4.1's Trust rules:
nothing an agent's shell records may read as the person's own act.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import attention, attribution, cases, consent, gitops, intents, settings, statements, workspace
from .primitives import chrono, fsops

__all__ = [
    "AnswerError",
    "AnswerResult",
    "PASTE_MATCH_CHARS",
    "RAN_SUDO_OPTION",
    "RUN_BRIEF",
    "RunResult",
    "answer",
    "append_outcome",
    "billing_route",
    "claim",
    "done",
    "fix",
    "outcomes_path",
    "redo_offered",
    "resolve_terminal",
    "run",
    "stop",
    "undo",
]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNKNOWN = 2
EXIT_REFUSED = 3
EXIT_MONEY = 4
EXIT_NO_TERMINAL = 5
EXIT_HELD = 10
EXIT_USAGE = 64

#: §3.4.1: a reply holding a whitespace-normalised run of this many
#: characters that also appears in one of the item's agent rows is the
#: agent's draft, edited and sent by the person (critique 21).
PASTE_MATCH_CHARS = 40
#: The "I ran it" button on an ``awaiting-sudo`` item, sent as an option.
RAN_SUDO_OPTION = "opt-ran-sudo"
RAN_SUDO_LABEL = "I ran it"
#: The unit name prefix of a launched session (``self-learn-run-<12 hex>``).
RUN_UNIT_PREFIX = attention.RUN_UNIT_PREFIX
LAUNCH_TIMEOUT_SECS = 10
FIX_TIMEOUT_SECS = 10
STOP_TIMEOUT_SECS = 10
HOST_UNIT = attention.HOST_UNIT
#: §3.4.7's terminal fallbacks, in order: the binary and the argv that
#: follows it before the command.
TERMINAL_FALLBACKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("alacritty", ("-e",)),
    ("ghostty", ("-e",)),
    ("kitty", ()),
    ("foot", ()),
    ("wezterm", ("start", "--")),
)

#: §3.4.7, frozen. ``{id}`` is the approved item's id, ``{title}`` its title.
RUN_BRIEF = """\
self-learn: the user approved this change in self-learn's inbox ({id}, "{title}") and opened this session to carry it out. They can see this terminal.
1. Claim it: self-learn attention claim {id} --session "$CLAUDE_CODE_SESSION_ID"
2. Read the plan: self-learn attention packet {id} --json   (its checks, steps, files and the user's conditions)
3. Run every check first. If any check fails, change nothing and run:
   self-learn attention done {id} --failed --session "$CLAUDE_CODE_SESSION_ID" --note "<what you found>"
4. Never run sudo. Any sudo steps were the user's, and they are already done.
5. Carry out the steps, honouring the user's conditions. If a step fails, stop and report it with --failed as in 3.
6. When finished: self-learn attention done {id} --session "$CLAUDE_CODE_SESSION_ID" --note "<what you did>"
"""

_TRANSCRIPT_REF_RE = re.compile(r"^transcript:.+#L\d+$")
_OWN_SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
#: Decided kinds with a one-click inverse (§3.4.6).
UNDO_KINDS = frozenset({
    "decided.hook-activated", "decided.registration", "decided.skill", "decided.grant-use",
    "decided.withdrawn",
})


class AnswerError(Exception):
    """A verb here refused; nothing was recorded unless the message says so."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class AnswerResult:
    """What :func:`answer` recorded (the ``--json`` object, §4.6)."""

    item: str
    statement: str | None = None
    choice: str | None = None
    state: str | None = None
    transcript_row: int | None = None
    run: dict[str, Any] | None = None
    recorded_as: str = ""
    warnings: list[str] = field(default_factory=list)
    registration: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "item": self.item, "statement": self.statement, "choice": self.choice,
            "state": self.state, "transcript_row": self.transcript_row, "run": self.run,
            "recorded_as": self.recorded_as, "warnings": list(self.warnings),
            "registration": self.registration,
        }


@dataclass
class RunResult:
    """What :func:`run` did: its exit code and the sentence for the page."""

    exit: int
    message: str
    unit: str | None = None
    brief: str | None = None
    argv: list[str] | None = None
    #: Follow-ups 2 (gap 3): the command a person runs in a terminal of
    #: their own when none was found (exit 5), alone, so a page copies it
    #: without parsing :attr:`message`; ``None`` otherwise.
    command: str | None = None

    def to_json(self) -> dict[str, Any]:
        """``attention run --json`` and the answer verb's ``run``:
        ``{exit, message, command, brief}``."""
        return {"exit": self.exit, "message": self.message, "command": self.command,
                "brief": self.brief}


# ------------------------------------------------------------------ helpers


def _agent() -> bool:
    return settings.agent_caller()


def _actor() -> str:
    """Who is acting: ``agent`` in an agent's shell, else ``human`` (the
    page's verb runner runs in the person's UI service)."""
    return "agent" if _agent() else "human"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _cache(home: Path) -> Path:
    return attention.cache_dir(home)


def _ledger_stopped(home: Path) -> bool:
    """Whether a ledger write stopped half-way (an intent marked STOPPED):
    every ledger write is refused until it is cleared, so an answer is
    refused before anything is written (exit 10) rather than half-kept."""
    folder = home / ".intents"
    try:
        paths = sorted(folder.glob("*.json")) if folder.is_dir() else []
    except OSError:
        return False
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("stopped"), dict):
            return True
    return False


def _held() -> AnswerError:
    return AnswerError(
        "a ledger write stopped half-way and is not repaired yet, so nothing can be recorded "
        "now; nothing was written (the inbox's 'self-learn is broken' item says what to do)",
        EXIT_HELD,
    )


def outcomes_path(home: Path | str) -> Path:
    return Path(home) / "attention" / "outcomes.jsonl"


def append_outcome(home: Path | str, row: dict) -> str:
    """Append one ``attention/outcomes.jsonl`` row (§4.4: approved work done
    or failed) under the ledger lock and commit it. Returns its id."""
    home = Path(home)
    if row.get("result") not in ("done", "failed"):
        raise AnswerError(f"an outcome is done or failed, got {row.get('result')!r}", EXIT_USAGE)
    rule = workspace.secret_rule(row.get("note")) if isinstance(row.get("note"), str) else None
    if rule is not None:
        raise AnswerError(f"the note matched the secret scan ({rule}); nothing was recorded",
                          EXIT_USAGE)
    target = outcomes_path(home)
    full = {"id": "out-" + uuid.uuid4().hex[:8], "at": chrono.now_iso(), **row}
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
        prior = target.read_text(encoding="utf-8") if target.exists() else ""
        if prior and not prior.endswith("\n"):
            prior += "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        fsops.atomic_write(target, prior + json.dumps(full, sort_keys=True) + "\n", fsync=True)
        gitops.stage_and_commit(
            home, [target],
            f"self-learn: attention outcome {full['id']} ({full['result']} on {full.get('item')})",
            full.get("note") if isinstance(full.get("note"), str) else None,
        )
    return str(full["id"])


def _seal(home: Path, item: dict, row: dict) -> int:
    """One workspace row for *item*; its ``t``. A STOPPED ledger keeps it on
    this machine (``workspace.append``'s pending file) and is refused here,
    because the statement and the choice that cite it could not be written."""
    sealed = workspace.append(
        home, item["id"], [row],
        header={"item_kind": item.get("kind"), "subject": item.get("subject"),
                "title": item.get("title")},
    )
    if not sealed:
        raise _held()
    return sealed[0]


def _ask_rows(home: Path) -> list[dict]:
    from .overseer import conversation

    try:
        return conversation._load_questions(home)  # noqa: SLF001
    except Exception:  # noqa: BLE001 -- an unreadable index is no ask here
        return []


def _ask_row(home: Path, subject: object) -> dict | None:
    if not isinstance(subject, str) or not subject.startswith("q-"):
        return None
    return next((row for row in _ask_rows(home) if row.get("id") == subject), None)


def _option_view(option: dict, recommend: object) -> dict:
    return {
        "id": option.get("id"), "label": option.get("label"),
        "effect": option.get("effect", "other"), "confirm": bool(option.get("confirm", False)),
        "note": "required" if option.get("note") == "required" else None,
        "recommended": isinstance(recommend, dict) and recommend.get("option") == option.get("id"),
        "via": "answer",
    }


def _items(home: Path) -> list[dict]:
    return attention.collect(home, all_items=True)


def _answered_ask_item(home: Path, item_id: str) -> dict | None:
    """An ask the person already answered is no longer listed, but it stays
    in the overseer's index until its next weekly run: until then a later
    answer still appends ("change my answer", §3.4.4, latest wins)."""
    for row in _ask_rows(home):
        if row.get("kind") != "ask" or not isinstance(row.get("id"), str):
            continue
        kind, key = attention.classify(row)
        if attention.item_id(kind, row["id"]) != item_id:
            continue
        options = [_option_view(o, row.get("recommend")) for o in row.get("options") or []
                   if isinstance(o, dict) and o.get("id")]
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else None
        return {
            "id": item_id, "kind": kind, "class": "needs-you" if key else "decided",
            "because": key, "subject": row["id"], "title": " ".join(str(row.get("text")).split()),
            "state": "answered", "refs": [row["id"], *(row.get("cases") or [])],
            "options": options, "_plan": plan, "_ask": row, "_question": row.get("text"),
        }
    return None


def _find(home: Path, item_id: str, items: list[dict] | None = None) -> dict | None:
    items = _items(home) if items is None else items
    found = next((item for item in items if item["id"] == item_id), None)
    if found is not None:
        return found
    return _answered_ask_item(home, item_id)


def _approved_for(items: list[dict], item_id: str, home: Path | None = None) -> dict | None:
    """The approved item *item_id* names: itself, or the approved item that
    replaced the needs-you item *item_id* when it was approved; or, while
    the ledger is STOPPED, a ``broken.stopped`` item whose approval is held
    on this machine (:func:`_held_approval`)."""
    for item in items:
        if item["kind"] == "approved.pending" and (
            item["id"] == item_id or item.get("_source_item") == item_id
        ):
            return item
    held = _held_approval(home, item_id) if home is not None else None
    if held is not None:
        found = next((i for i in items if i["id"] == item_id and i["kind"] == "broken.stopped"), None)
        if found is not None:
            return found
        # Once the session cleared the intent the item is gone (its condition
        # ended); `done` still needs it, to commit the held click and the
        # outcome.
        subject = str(held.get("subject") or "")
        return {
            "id": item_id, "kind": "broken.stopped", "class": "needs-you", "subject": subject,
            "title": "A ledger write stopped half-way and self-learn could not repair it",
            "state": "approved", "refs": [],
            "_plan": attention._plan_for(attention.PLAN_BROKEN_STOPPED, subject),  # noqa: SLF001
        }
    return None


def _held_path(home: Path, item_id: str) -> Path:
    return _cache(home) / "attention" / "held-approvals" / f"{item_id}.json"


def _held_approval(home: Path, item_id: str) -> dict | None:
    try:
        data = json.loads(_held_path(home, item_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_held_approval(home: Path, item_id: str, choice_row: dict) -> None:
    """``<cache>/attention/held-approvals/<id>.json``: the person's approve
    click on a ``broken.stopped`` item, kept on this machine because the
    ledger is STOPPED and no choice can be committed. ``done`` commits it
    (before its outcome) once the intent is cleared. Cache, never ledger
    truth."""
    target = _held_path(home, item_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(target, json.dumps(choice_row, sort_keys=True) + "\n", fsync=False)


def _clear_held_approval(home: Path, item_id: str) -> None:
    """Remove a held approval once ``done`` committed it (cache only)."""
    _held_path(home, item_id).unlink(missing_ok=True)


def _code_kind_for_subject(subject: str) -> str:
    return "broken.job" if subject.startswith("job:") else "broken.stopped"


def _options_for(item: dict, ask_row: dict | None) -> list[dict]:
    options = [dict(o) for o in item.get("options") or []]
    if item["kind"] == "approved.pending":
        # Follow-ups 2 (gap 2): the approved item's own options are the
        # page's changes of mind (no approval, `disabled` while claimed,
        # "Stop it"); what an answer may choose is still every option the
        # ask offered, and a live claim is checked in `answer` itself.
        if ask_row is not None:
            options = [_option_view(o, ask_row.get("recommend"))
                       for o in ask_row.get("options") or [] if isinstance(o, dict) and o.get("id")]
        else:
            options = [dict(o) for o in attention.KINDS[_code_kind_for_subject(
                str(item.get("subject")))].options]
    if item.get("state") == "awaiting-sudo":
        options.append({
            "id": RAN_SUDO_OPTION, "label": RAN_SUDO_LABEL, "effect": "ran-sudo",
            "confirm": False, "note": None, "recommended": False, "via": "answer",
        })
    return options


def _plan_of(item: dict, ask_row: dict | None) -> dict | None:
    plan = item.get("_plan")
    if isinstance(plan, dict):
        return plan
    if ask_row is not None and isinstance(ask_row.get("plan"), dict):
        return ask_row["plan"]
    return None


def _sudo_steps(plan: dict | None) -> tuple[list[dict], list[dict]]:
    steps = [s for s in (plan or {}).get("steps") or [] if isinstance(s, dict)]
    return [s for s in steps if s.get("sudo") is True], [s for s in steps if s.get("sudo") is not True]


def _paste_match(text: str, agent_texts: list[str]) -> str | None:
    """The agent row whose text shares a whitespace-normalised run of
    :data:`PASTE_MATCH_CHARS` characters with *text*, or ``None``."""
    reply = _norm(text)
    if len(reply) < PASTE_MATCH_CHARS:
        return None
    for original in agent_texts:
        theirs = _norm(original)
        if len(theirs) < PASTE_MATCH_CHARS:
            continue
        for start in range(len(reply) - PASTE_MATCH_CHARS + 1):
            if reply[start:start + PASTE_MATCH_CHARS] in theirs:
                return original
    return None


def _conflict_statements(ask_row: dict | None) -> list[str]:
    named = (ask_row or {}).get("statements")
    if isinstance(named, list) and len(named) == 2 and all(isinstance(s, str) for s in named):
        return list(named)
    return []


def _answers_for(item: dict, ask_row: dict | None, *, for_choice: bool) -> dict:
    """What an answer to *item* answers (``answers`` on its statement or
    choice; §3.4.4)."""
    kind = item["kind"]
    subject = str(item.get("subject"))
    question = (ask_row or {}).get("text") or item.get("_question")
    named = _conflict_statements(ask_row)
    if ask_row is not None and ask_row.get("because") == "conflict" and named:
        return {"kind": "conflict" if for_choice else "instruction",
                "ref": f"conflict:{named[0]}+{named[1]}", "text": question}
    if ask_row is not None or kind.startswith("ask.") or kind == "decided.ask-default":
        return {"kind": "question", "ref": subject, "text": question}
    if kind == "decided.reading":
        return {"kind": "proposition", "ref": subject, "text": None}
    if kind.startswith("decided."):
        case = next((r for r in item.get("refs") or [] if isinstance(r, str)
                     and r.startswith("case-")), None)
        return {"kind": "instruction", "ref": case or subject, "text": item.get("title")}
    return {"kind": "instruction", "ref": subject, "text": item.get("title")}


def _prove(home: Path, item: dict, option: dict, session: str | None) -> str:
    """§3.4.1: from an agent's shell an approve or register option needs the
    person's typed yes, proved in the agent's own session: the last row they
    typed there is a plain yes, and the assistant's visible text just before
    it names the item id and the option's label. Returns the transcript
    line of the yes; raises (exit 64) when it is not proved."""
    own = (os.environ.get(_OWN_SESSION_ENV) or "").strip()
    named = (session or "").strip()
    if own and named and named != own:
        raise AnswerError(
            "--session names a session other than this shell's own, and a yes is proved only "
            "in the session it was typed in", EXIT_USAGE,
        )
    chosen = named or own
    if not chosen:
        raise AnswerError(
            "this is an agent's shell with no session to check the person's yes in; pass "
            "--session <the session id they typed the yes in>", EXIT_USAGE,
        )
    label = str(option.get("label") or "")
    proof = consent.prove_typed_yes(
        home, chosen,
        must_name=[
            (item["id"], lambda asked: consent.names_id(asked, item["id"])),
            (f"the option «{label}»",
             lambda asked: bool(label) and _norm(label).casefold() in _norm(asked).casefold()),
        ],
    )
    if not proof.ok or proof.ref is None:
        raise AnswerError(
            f"{option.get('effect')} option {option.get('id')} from an agent's shell needs the "
            f"person's typed yes: {proof.problem or 'no transcript line'}. Nothing was "
            "recorded; ask them in one message that names the item id and the option, and "
            "answer again once they typed yes, or have them click it in the inbox",
            EXIT_USAGE,
        )
    return proof.ref


def _current_cases(home: Path, case_ids: list[str]) -> list[str]:
    from .overseer import conversation

    links = conversation.superseded_links(home)
    out: list[str] = []
    for case_id in case_ids:
        current = conversation.current_case(home, case_id, links)
        if current not in out:
            out.append(current)
    return out


def _observe_all(home: Path, case_ids: list[str], text: str, ref: str, warnings: list[str]) -> list[str]:
    observed: list[str] = []
    for case_id in case_ids:
        try:
            cases.observe(home, case_id, "statement", text=text, by=_actor(), ref=ref)
            observed.append(case_id)
        except (cases.CaseError, gitops.GitOpsError, OSError) as exc:
            warnings.append(f"the answer is recorded, but {case_id} could not be told: {exc}")
    return observed


def _conflict_side(option: dict | None) -> str:
    """Which statement a conflict option keeps: ``newer``, ``older`` or
    ``both``. The overseer is told to label a conflict's options "Keep the
    newer one: …" / "Keep the older one: …" (``overseer.run``'s prompt), so
    the side is read from the option's id and label; anything else is
    both."""
    if option is None:
        return "both"
    words = f"{option.get('id')} {option.get('label')}".casefold()
    newer, older = "newer" in words, "older" in words
    if newer and not older:
        return "newer"
    if older and not newer:
        return "older"
    return "both"


def _conflict_losers(home: Path, named: list[str], side: str) -> list[str]:
    """The statements the person ruled against: the newer one when the
    older holds, the older one when the newer is right, both otherwise."""
    rows = {row.get("id"): row for row in statements.list_statements(home)}
    first, second = named
    a_at, b_at = str((rows.get(first) or {}).get("at") or ""), str((rows.get(second) or {}).get("at") or "")
    newer, older = (first, second) if a_at > b_at else (second, first)
    if side == "older":
        return [newer]
    if side == "newer":
        return [older]
    return [first, second]


def _cases_citing(home: Path, statement_ids: list[str]) -> list[str]:
    out: list[str] = []
    for row in cases.list_cases(home, only_ok=True):
        if row.get("superseded_by"):
            continue
        refs = row.get("dependency_refs") or []
        if any(sid in refs for sid in statement_ids) and row.get("case") not in out:
            out.append(str(row["case"]))
    return out


# ------------------------------------------------------------------ answer


def answer(
    home: Path | str,
    item_id: str,
    *,
    option: str | None = None,
    text: str | None = None,
    draft_id: str | None = None,
    ref: str | None = None,
    session: str | None = None,
    confirm: bool = False,
    note: str | None = None,
    launch: bool = True,
) -> AnswerResult:
    """``self-learn attention answer`` (design r2 §3.4.1, §3.4.4). Raises
    :class:`AnswerError` with the exit code of §4.6 when refused; nothing is
    recorded then, except where the message says otherwise."""
    home = Path(home)
    agent = _agent()
    if isinstance(text, str) and not text.strip():
        text = None
    if option is None and text is None and draft_id is None:
        raise AnswerError("answer needs --option, --text-file or --draft", EXIT_USAGE)
    if agent:
        markers = ", ".join(settings.agent_caller_markers())
        if draft_id is not None:
            raise AnswerError(
                "--draft is refused from an agent's shell: an agent's draft is accepted only "
                f"by the person, on the page (agent shell detected: {markers})", EXIT_USAGE,
            )
        if ref is None or text is None:
            raise AnswerError(
                "from an agent's shell every answer is the person's own words relayed: pass "
                "--ref transcript:<session>#L<n> (the line they typed them on) and --text-file "
                f"holding those words (agent shell detected: {markers})", EXIT_USAGE,
            )
        if _TRANSCRIPT_REF_RE.fullmatch(ref) is None:
            raise AnswerError(f"--ref must be transcript:<session>#L<n>, got {ref!r}", EXIT_USAGE)
        if not (note or "").strip():
            raise AnswerError(
                "from an agent's shell this verb needs --note TEXT saying why; the ledger "
                f"records it as By: agent (agent shell detected: {markers})", EXIT_USAGE,
            )
    elif ref is not None:
        raise AnswerError(
            "--ref is for an agent relaying the person's words from its own session; in your "
            "own terminal or on the page your words are recorded as typed", EXIT_USAGE,
        )
    if text is not None and (rule := workspace.secret_rule(text)) is not None:
        raise AnswerError(
            f"the reply matched the secret scan ({rule}); nothing was recorded. Leave the "
            "secret out and send it again", EXIT_USAGE,
        )
    stopped = _ledger_stopped(home)
    items = _items(home)
    item = _find(home, item_id, items)
    if item is None:
        raise AnswerError(f"unknown or closed item {item_id}", EXIT_UNKNOWN)
    if stopped:
        # Nothing can be committed while a ledger write is STOPPED. The one
        # answer that must still work then is the person's "Have an agent
        # look at it" on the item that says so (§3.4.8): it is held on this
        # machine and launched; `done` commits it once the intent is cleared.
        if (item["kind"] == "broken.stopped" and option is not None and not agent
                and text is None and draft_id is None):
            return _approve_while_stopped(home, item, option)
        raise _held()
    ask_row = item.get("_ask") if isinstance(item.get("_ask"), dict) else _ask_row(
        home, item.get("subject"))
    if item["kind"].startswith("decided.") and item["kind"] != "decided.ask-default":
        # A decided item's subject can still name an indexed ask (an approved
        # plan the agent finished, a withdrawn ask): words on it are an
        # overturn of the decision (§3.4.4, "After an approved item is done,
        # a new answer is an overturn"), never an answer to the ask.
        ask_row = None
    options = _options_for(item, ask_row)

    # -- the origin (§3.4.1's order)
    draft_row: dict | None = None
    draft_text: str | None = None
    if draft_id is not None:
        draft_row = next(
            (row for row in workspace.rows(home, item["id"], pending=False)
             if row.get("kind") == "draft" and row.get("role") == "agent"
             and row.get("draft_id") == draft_id and isinstance(row.get("t"), int)),
            None,
        )
        if draft_row is None or not isinstance(draft_row.get("text"), str):
            raise AnswerError(f"--draft {draft_id} names no sealed draft of {item['id']}", EXIT_USAGE)
        sealed_text: str = draft_row["text"]
        draft_text = sealed_text
        if text is None:
            text = sealed_text
        origin = "draft-accepted" if text.strip() == sealed_text.strip() else "draft-edited"
        if option is None and isinstance(draft_row.get("option"), str):
            option = draft_row["option"]
    elif agent:
        origin = "relayed"
    elif text is not None:
        agent_texts = [
            str(row["text"]) for row in workspace.rows(home, item["id"], pending=False)
            if row.get("role") == "agent" and row.get("kind") in ("answer", "draft")
            and isinstance(row.get("text"), str)
        ]
        draft_text = _paste_match(text, agent_texts)
        origin = "draft-edited" if draft_text is not None else "typed"
    else:
        origin = "clicked"

    # -- the option
    chosen: dict | None = None
    if option is not None:
        chosen = next((o for o in options if o.get("id") == option), None)
        if chosen is None:
            offered = ", ".join(str(o.get("id")) for o in options) or "none"
            raise AnswerError(
                f"{item['id']} offers no option {option!r} (it offers: {offered})", EXIT_REFUSED,
            )
        if chosen.get("disabled"):
            raise AnswerError(f"{option} is not available now: {chosen['disabled']}", EXIT_REFUSED)
        via = str(chosen.get("via") or "answer")
        if via not in ("answer", "refreeze --keep", "refreeze --restore"):
            raise AnswerError(
                f"{option} ({chosen.get('label')}) is not an answer: the page runs it "
                f"(`self-learn attention {via.split()[0]}`)", EXIT_REFUSED,
            )
        if chosen.get("note") == "required" and not (text or "").strip():
            raise AnswerError(
                f"«{chosen.get('label')}» needs a note saying what you want; nothing was "
                "recorded", EXIT_REFUSED,
            )
        # A register option always asks once more (§0 call 3: it writes
        # another repo's history or registers a host), whatever the ask says.
        if (chosen.get("confirm") or chosen.get("effect") == "register") and not confirm:
            raise AnswerError(
                f"«{chosen.get('label')}» asks once more before it acts; send it again with "
                "--confirm", EXIT_REFUSED,
            )
        if item["kind"] == "approved.pending" and chosen.get("effect") != "approve":
            # "The answer stays changeable until it is carried out" (design
            # r2 §0 call 3, §1.3): only a session that claimed the work is
            # carrying it out. Unclaimed (not launched, refused, or a
            # terminal closed before it claimed), the new answer stands and
            # a later claim is refused.
            holder = attention._claim(home, item["id"], _now())  # noqa: SLF001
            if holder is not None:
                raise AnswerError(
                    f"session {holder.get('session')} claimed this change at {holder.get('at')} "
                    "and is carrying it out now, so a different answer cannot stop it from "
                    "here; tell that session in its terminal. Nothing was recorded",
                    EXIT_REFUSED,
                )
        if chosen.get("effect") == "ran-sudo" and item.get("state") != "awaiting-sudo":
            raise AnswerError(f"{item['id']} is not waiting for sudo steps", EXIT_REFUSED)
        if via.startswith("refreeze") and agent:
            raise AnswerError(
                "keeping or restoring a hand-edited case is the person's own click; refused "
                "from an agent's shell", EXIT_USAGE,
            )
    effect = (chosen or {}).get("effect")
    if effect == "ran-sudo":
        origin = "clicked" if origin == "typed" else origin

    # -- the proof (an agent relaying an approve or register click)
    proof_ref: str | None = None
    if agent and effect in ("approve", "register") and chosen is not None:
        proof_ref = _prove(home, item, chosen, session)
    authority = (
        attribution.Authority("typed-yes", proof_ref, f"Answers: {item['id']}")
        if proof_ref is not None else None
    )

    result = AnswerResult(item=item["id"])

    # -- what the option does before anything is recorded (a refused act
    #    leaves the question open, nothing recorded: S-103's order)
    if effect == "register":
        if ask_row is None or not ask_row.get("register"):
            raise AnswerError(f"{option} registers nothing: the ask carries no register",
                              EXIT_REFUSED)
        from .overseer import conversation

        try:
            sentence, _registered = conversation._register_core(  # noqa: SLF001
                home, ask_row, consent=authority,
            )
        except conversation.ConversationError as exc:
            raise AnswerError(str(exc).replace("overseer respond: ", ""), EXIT_REFUSED) from exc
        result.registration = sentence
    if chosen is not None and str(chosen.get("via")).startswith("refreeze"):
        try:
            cases.refreeze(
                home, str(item.get("subject")), keep=chosen.get("via") == "refreeze --keep",
                note=f"From the inbox: {chosen.get('label')}",
            )
        except cases.RefreezeError as exc:
            raise AnswerError(str(exc), EXIT_REFUSED) from exc

    # -- the transcript row
    row: dict[str, Any] = {
        "role": "user", "origin": origin,
        "kind": "ran-sudo" if effect == "ran-sudo" else "reply",
        "text": text if effect != "ran-sudo" else None,
        "option": chosen.get("id") if chosen else None,
        "draft_id": draft_id, "draft_text": draft_text if origin.startswith("draft-") else None,
        "ref": ref,
    }
    t = _seal(home, item, row)
    result.transcript_row = t
    message_ref = f"workspace:{item['id']}#T{t}"

    # -- the person's words (typed, or relayed by an agent)
    if text is not None and origin in ("typed", "relayed") and effect != "ran-sudo":
        source = {"message_ref": message_ref if origin == "typed" else ref, "surface": "inbox"}
        result.statement = statements.add(
            home, verbatim=text, source=source, recorded_by=_actor(),
            answers=_answers_for(item, ask_row, for_choice=False), scope={"level": "user", "host": None},
        )

    # -- the choice (a click, a draft, a relayed click, "I ran it")
    if chosen is not None or origin.startswith("draft-"):
        how = (
            "ran-sudo" if effect == "ran-sudo" else
            origin if origin in ("draft-accepted", "draft-edited", "relayed") else "clicked"
        )
        offered_by = (
            "agent" if how.startswith("draft-") and draft_id is not None
            else "overseer" if ask_row is not None else "system"
        )
        choice_row = {
            "item": item["id"], "item_kind": item["kind"], "subject": item.get("subject"),
            "how": how, "option": chosen.get("id") if chosen else None,
            "label": chosen.get("label") if chosen else None,
            "effect": effect if effect in ("approve", "decline", "other", "register") else None,
            "text": text if effect != "ran-sudo" else None,
            "draft_id": draft_id, "draft_text": draft_text if how.startswith("draft-") else None,
            "offered_by": offered_by, "answers": _answers_for(item, ask_row, for_choice=True),
            "source": {"message_ref": message_ref}, "statement": result.statement,
            "proof": proof_ref, "recorded_by": _actor(), "note": note,
        }
        from .overseer import conversation

        with attribution.acting(authority):
            result.choice = conversation.record_choice(home, choice_row)
        if item["kind"] == "approved.pending" and effect != "approve":
            # Gate r2 NIT 2: the claim was read before this commit, and a
            # launched session may have claimed in between. `claim` reads
            # the items again after writing its claim, so at least one side
            # sees the other: if this one does, say so and name the session.
            late = attention._claim(home, item["id"], _now())  # noqa: SLF001
            if late is not None:
                result.warnings.append(
                    f"session {late.get('session')} claimed this change at {late.get('at')}, "
                    "just as your answer was recorded. If it saw your answer when it "
                    "claimed, it has already let go and changes nothing; if its terminal "
                    "shows it carrying out the earlier approval, tell it there"
                )

    # -- what it does downstream (§3.4.4)
    decided_by = result.choice or result.statement
    plan = _plan_of(item, ask_row)
    result.state = _downstream(home, item, ask_row, chosen, plan, decided_by, result,
                               launch=launch, origin=origin)
    result.recorded_as = (
        "as your words" if origin == "typed" and result.choice is None
        else "as your choice of the offered option, with your words" if origin == "typed"
        else "as your choice of the offered option" if origin == "clicked"
        else "as the agent's draft, accepted by you" if origin == "draft-accepted"
        else "as the agent's draft, edited and sent by you" if origin == "draft-edited"
        else "as your words, relayed by an agent from your session"
    )
    return result


def _downstream(
    home: Path, item: dict, ask_row: dict | None, chosen: dict | None, plan: dict | None,
    decided_by: str | None, result: AnswerResult, *, launch: bool, origin: str,
) -> str:
    """Case observations, approval and launch; returns the item's state."""
    kind = item["kind"]
    effect = (chosen or {}).get("effect")
    warnings = result.warnings
    if decided_by is None:
        return str(item.get("state") or "open")
    # A conflict between two statements (§3.4.4): the losing side's cases.
    named = _conflict_statements(ask_row)
    if ask_row is not None and ask_row.get("because") == "conflict" and named:
        side = _conflict_side(chosen)
        losers = _conflict_losers(home, named, side)
        conflict = f"conflict:{named[0]}+{named[1]}"
        _observe_all(home, _cases_citing(home, losers),
                     f"user ruled on {conflict} in the inbox", decided_by, warnings)
        return "answered"
    if effect in ("approve", "ran-sudo") and plan is not None:
        return _approve(home, item, plan, result, launch=launch, ran_sudo=effect == "ran-sudo")
    if kind == "approved.pending" and effect is None:
        # Words on approved work change nothing; a different option (no live
        # claim, checked in `answer`) falls through and answers the ask.
        return str(item.get("state"))
    if _overturns(kind, ask_row):
        # A decided item, overturned (§3.4.4): every case it cites is told,
        # so the steward re-decides it (§3.4.5). Checked before the plan
        # rule below: a finished approval keeps its plan, and a new answer
        # on it is an overturn, not an undecided reply.
        refs = [r for r in item.get("refs") or [] if isinstance(r, str) and r.startswith("case-")]
        if not refs and isinstance(item.get("_case"), str):
            refs = [item["_case"]]
        _observe_all(home, _current_cases(home, refs),
                     f"user overturned {item['id']} in the inbox", decided_by, warnings)
        return str(item.get("state") or "done")
    if plan is not None and effect is None:
        # Words alone, an agent draft sent with no option, or a reply that
        # pastes the agent's text, on an item with a plan, decide nothing
        # (§1.3, §2.3(b)): recorded, the overseer reads them, the item stays
        # open, and no case is told (nothing was decided to re-decide on).
        return "open"
    if ask_row is not None:
        q_id = str(ask_row["id"])
        stead = kind == "decided.ask-default"
        text = f"user answered {q_id}" + (" after its default was applied" if stead else "")
        _observe_all(home, _current_cases(home, [c for c in ask_row.get("cases") or []
                                                 if isinstance(c, str)]),
                     text, decided_by, warnings)
        return "done" if stead else "answered"
    if kind == "conflict.case-tampered":
        return "resolved"
    return str(item.get("state") or "done")


def _overturns(kind: str, ask_row: dict | None) -> bool:
    """Whether an answer on a *kind* item is an overturn in words (§3.4.4):
    every decided kind except a reading (corrected as a proposition) and a
    stead ask whose ask is still indexed (answered as the question)."""
    if not kind.startswith("decided.") or kind == "decided.reading":
        return False
    return kind != "decided.ask-default" or ask_row is None


def _approve(home: Path, item: dict, plan: dict | None, result: AnswerResult, *,
             launch: bool, ran_sudo: bool) -> str:
    """An approve click (or "I ran it") on an item with a plan (§3.4.7):
    ``awaiting-sudo`` when sudo steps are the person's to run first;
    otherwise approved, and launched from a person's shell."""
    sudo, rest = _sudo_steps(plan)
    approved_id = attention.item_id("approved.pending", str(item.get("subject")))
    if sudo and not ran_sudo:
        return "awaiting-sudo"
    if ran_sudo and not rest:
        append_outcome(home, {
            "item": approved_id, "subject": item.get("subject"), "result": "done",
            "note": "you ran the sudo steps", "session": None, "by": "human" if not _agent() else "agent",
        })
        return "done"
    if _agent():
        brief = _write_brief(home, approved_id, str(item.get("title") or ""))
        result.run = {
            "exit": None,
            "message": (
                "approved; nothing was launched from an agent's shell. The session the person "
                f"typed the yes in may carry it out itself by following {brief}, or they click "
                "Run it now in the inbox"
            ),
        }
        return "approved"
    if not launch:
        return "approved"
    outcome = _run_item(home, approved_id)
    result.run = outcome.to_json()
    return "running" if outcome.exit == EXIT_OK else "approved"


def _approve_while_stopped(home: Path, item: dict, option: str) -> AnswerResult:
    """A ``broken.stopped`` item's agent option, clicked while the ledger is
    STOPPED: the choice row is held in the cache, the transcript row is kept
    pending by ``workspace.append``, and the session is launched on the
    item itself. Its ``claim`` is a cache write and its ``done`` commits the
    held choice, then the outcome, once the session cleared the intent."""
    chosen = next((o for o in _options_for(item, None) if o.get("id") == option), None)
    if chosen is None or chosen.get("effect") != "approve":
        raise _held()
    choice_row = {
        "id": "chc-" + uuid.uuid4().hex[:8], "at": chrono.now_iso(), "item": item["id"],
        "item_kind": item["kind"], "subject": item.get("subject"), "how": "clicked",
        "option": option, "label": chosen.get("label"), "effect": "approve", "text": None,
        "draft_id": None, "draft_text": None, "offered_by": "system",
        "answers": {"kind": "instruction", "ref": item.get("subject"), "text": item.get("title")},
        "source": {"message_ref": None}, "statement": None, "proof": None,
        "recorded_by": "human", "note": "held on this machine while the ledger was STOPPED",
    }
    _write_held_approval(home, item["id"], choice_row)
    _try_seal(home, item, {"role": "user", "origin": "clicked", "kind": "reply", "text": None,
                           "option": option})
    result = AnswerResult(item=item["id"], choice=choice_row["id"],
                          recorded_as="as your choice of the offered option")
    outcome = _run_item(home, item["id"])
    result.run = outcome.to_json()
    result.state = "running" if outcome.exit == EXIT_OK else "approved"
    result.warnings.append(
        "the ledger is STOPPED, so your click is kept on this machine; it is committed when "
        "the agent clears the stopped write and reports done"
    )
    return result


# ------------------------------------------------------------------ run


def billing_route(env: Mapping[str, str], *, provider: str = "anthropic") -> str | None:
    """Whether a session started with *env* would bill money (C8), through
    the ask lane's ``ask.billing_route`` when that module is present, else
    the same rules here (§3.3): a provider other than anthropic, a set
    ``ANTHROPIC_API_KEY``/``ANTHROPIC_AUTH_TOKEN``, or Bedrock/Vertex
    switched on. ``None`` means the person's subscription."""
    import importlib

    try:
        route = getattr(importlib.import_module("self_learn.ask"), "billing_route", None)
    except ImportError:
        route = None
    if callable(route):
        reason = route(env)
        if isinstance(reason, str):
            return reason
    if provider != "anthropic":
        return f"the model provider is {provider}, which bills an account, not your subscription"
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if str(env.get(key) or "").strip():
            return f"{key} is set, and Claude Code bills that key before it uses your login"
    for key in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        if str(env.get(key) or "").strip().lower() not in ("", "0", "false", "no", "off"):
            return f"{key} is set, so Claude Code would bill that cloud account"
    return None


def _provider(home: Path) -> str:
    from . import provider as provider_mod

    try:
        return provider_mod.resolve(home, "steward").provider
    except Exception:  # noqa: BLE001 -- an unreadable provider is checked by the env rules
        return "anthropic"


def resolve_terminal(home: Path) -> list[str] | None:
    """§3.4.7: the terminal argv prefix: ``attention.terminal``, else
    ``$TERMINAL -e``, else the first of :data:`TERMINAL_FALLBACKS` on PATH."""
    try:
        value, _source = settings.resolve_setting(home, settings.by_name("attention.terminal"))
    except Exception:  # noqa: BLE001 -- an unreadable setting falls through to the rest
        value = ""
    if isinstance(value, str) and value.strip():
        try:
            words = shlex.split(value)
        except ValueError:
            words = []
        if words and shutil.which(words[0]):
            return words
    terminal = (os.environ.get("TERMINAL") or "").strip()
    if terminal:
        try:
            words = shlex.split(terminal)
        except ValueError:
            words = []
        if words and shutil.which(words[0]):
            return [*words, "-e"]
    for binary, rest in TERMINAL_FALLBACKS:
        if shutil.which(binary):
            return [binary, *rest]
    return None


def _brief_text(approved_id: str, title: str) -> str:
    return RUN_BRIEF.format(id=approved_id, title=" ".join(title.split()).replace('"', "'"))


def _write_brief(home: Path, approved_id: str, title: str) -> Path:
    """``<cache>/attention/runs/<id>/brief.md`` (cache, never ledger truth)."""
    target = _cache(home) / "attention" / "runs" / approved_id / "brief.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(target, _brief_text(approved_id, title), fsync=False)
    return target


def _write_run_record(home: Path, item_id: str, unit: str) -> None:
    """``<cache>/attention/runs/<id>.json`` ``{unit, at}`` (cache only)."""
    target = _cache(home) / "attention" / "runs" / f"{item_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(target, json.dumps({"unit": unit, "at": chrono.now_iso()}) + "\n", fsync=False)


def _launch(home: Path, argv: list[str]) -> tuple[bool, str]:
    """Run ``systemd-run`` with *argv* after it; ``(ok, detail)``."""
    binary = shutil.which("systemd-run")
    if binary is None:
        return False, "systemd-run is not on PATH"
    try:
        proc = subprocess.run(
            [binary, *argv], capture_output=True, text=True, timeout=LAUNCH_TIMEOUT_SECS,
            check=False, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"systemd-run failed: {exc}"
    if proc.returncode != 0:
        return False, f"systemd-run exited {proc.returncode}: {str(proc.stderr or proc.stdout or '').strip()[:400]}"
    return True, ""


def _working_directory(plan: dict | None) -> str:
    home_dir = os.path.expanduser("~")
    cwd = (plan or {}).get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        expanded = os.path.expanduser(cwd.strip())
        if os.path.isabs(expanded) and os.path.isdir(expanded):
            return expanded
    return home_dir


def run(home: Path | str, item_id: str, *, login: bool = False) -> RunResult:
    """``self-learn attention run <id> [--login]`` (§3.4.7, §3.4.8). Never
    raises for a refusal: the exit code and the page's sentence come back."""
    return _run_item(home, item_id, login=login)


def _run_item(home: Path | str, item_id: str, *, login: bool = False) -> RunResult:
    """:func:`run`'s body. This module's own launches (an approve click,
    an agent option clicked while STOPPED) call it by this name: a bare
    ``run(...)`` reads to the bounded-children gate as ``from subprocess
    import run`` (``test_bounded_children.py``), which it cannot tell apart."""
    home = Path(home)
    if _agent():
        return RunResult(EXIT_USAGE, (
            "refused from an agent's shell: a launch acts on the person's click. An agent the "
            "person approved the change in carries it out in its own session, by the brief"
        ))
    items = _items(home)
    if login:
        item = next((i for i in items if i["id"] == item_id), None)
        if item is None:
            return RunResult(EXIT_UNKNOWN, f"unknown item {item_id}")
        if item["kind"] != "hold.credentials" or item.get("class") != "needs-you":
            return RunResult(EXIT_REFUSED, "--login opens a login terminal only for an open "
                                           "log-in item")
        terminal = resolve_terminal(home)
        if terminal is None:
            return RunResult(EXIT_NO_TERMINAL, "no terminal found: open one yourself, run "
                                               "`claude`, then type /login", command="claude")
        unit = RUN_UNIT_PREFIX + item_id[len("att-"):]
        argv = ["--user", "--collect", "--quiet", f"--unit={unit}",
                f"--working-directory={_working_directory(None)}", "--", *terminal, "claude"]
        ok, detail = _launch(home, argv)
        if not ok:
            return RunResult(EXIT_REFUSED, f"the login terminal did not open: {detail}")
        _write_run_record(home, item_id, unit)
        _try_seal(home, item, {"role": "user", "origin": "clicked", "kind": "run", "text": None,
                               "option": "opt-login"})
        return RunResult(EXIT_OK, "A terminal is open running claude: type /login there.",
                         unit=unit, argv=argv)
    item = _approved_for(items, item_id, home)
    if item is None:
        other = next((i for i in items if i["id"] == item_id), None)
        finished = _done_for(items, item_id)
        if other is None and finished is not None:
            # Contract §4.6: 3 is "not approved (... done ...)". The approved
            # item's id is gone once its work is done (the done item has its
            # own id), so the done item is looked up by where it came from.
            return RunResult(EXIT_REFUSED, (
                f"{item_id} is already done ({finished['id']}); there is nothing to run. To "
                "change what was done, answer on that item in your own words"
            ))
        if other is None:
            return RunResult(EXIT_UNKNOWN, f"unknown item {item_id}")
        state = other.get("state")
        return RunResult(EXIT_REFUSED, (
            "the sudo steps come first: run them, then click I ran it" if state == "awaiting-sudo"
            else f"{item_id} is not approved (it is {state}); approve it first"
        ))
    claim_row = attention._claim(home, item["id"], _now())  # noqa: SLF001
    if claim_row is not None:
        return RunResult(EXIT_REFUSED, (
            f"a session ({claim_row.get('session')}) is carrying it out now"
        ))
    reason = billing_route(dict(os.environ), provider=_provider(home))
    if reason is not None:
        return RunResult(EXIT_MONEY, f"not launched: it would spend money ({reason}); nothing was sent")
    brief = _write_brief(home, item["id"], str(item.get("title") or ""))
    first_line = _brief_text(item["id"], str(item.get("title") or "")).splitlines()[0]
    message = f"{first_line} Read {brief} and follow it."
    terminal = resolve_terminal(home)
    if terminal is None:
        command = f"claude {shlex.quote(message)}"
        return RunResult(EXIT_NO_TERMINAL, (
            f"no terminal found. The brief is at {brief}; open a terminal and run: {command}"
        ), brief=str(brief), command=command)
    unit = RUN_UNIT_PREFIX + item["id"][len("att-"):]
    plan = item.get("_plan") if isinstance(item.get("_plan"), dict) else None
    argv = ["--user", "--collect", "--quiet", f"--unit={unit}",
            f"--working-directory={_working_directory(plan)}", "--", *terminal, "claude", message]
    ok, detail = _launch(home, argv)
    if not ok:
        return RunResult(EXIT_REFUSED, f"the terminal did not open: {detail}", brief=str(brief))
    _write_run_record(home, item["id"], unit)
    _try_seal(home, item, {"role": "user", "origin": "clicked", "kind": "run", "text": None,
                           "option": None})
    return RunResult(EXIT_OK, f"Running in a terminal (started {chrono.now_iso()}).",
                     unit=unit, brief=str(brief), argv=argv)


def _done_for(items: list[dict], item_id: str) -> dict | None:
    """The ``decided.approved-done`` item that *item_id* (the done item,
    the approved item it replaced, or the needs-you item before that)
    names, or ``None``."""
    for item in items:
        if item["kind"] != "decided.approved-done":
            continue
        approved_id = attention.item_id("approved.pending", str(item.get("subject")))
        if item_id in (item["id"], approved_id, item.get("_source_item")):
            return item
    return None


def _try_seal(home: Path, item: dict, row: dict) -> int | None:
    """A transcript row that records an act already done: a STOPPED ledger
    keeps it on this machine instead of failing the act."""
    try:
        sealed = workspace.append(
            home, item["id"], [row],
            header={"item_kind": item.get("kind"), "subject": item.get("subject"),
                    "title": item.get("title")},
        )
    except (gitops.GitOpsError, OSError):
        return None
    return sealed[0] if sealed else None


# ------------------------------------------------------------------ fix


def fix(home: Path | str, item_id: str, option: str) -> str:
    """``self-learn attention fix <id> --option opt-restart`` (§3.4.8):
    ``systemctl --user reset-failed`` then ``restart``, for
    ``self-learn-host.service`` only, each bounded to 10 s."""
    home = Path(home)
    if _agent():
        raise AnswerError(
            "refused from an agent's shell: restarting self-learn from the inbox is the "
            "person's click", EXIT_USAGE,
        )
    item = _find(home, item_id)
    if item is None:
        raise AnswerError(f"unknown item {item_id}", EXIT_UNKNOWN)
    if item["kind"] != "broken.host" or option != "opt-restart":
        raise AnswerError(f"{item_id} has no option {option!r} to fix with", EXIT_REFUSED)
    binary = shutil.which("systemctl")
    if binary is None:
        raise AnswerError("systemctl is not on PATH", EXIT_REFUSED)
    for verb in ("reset-failed", "restart"):
        try:
            proc = subprocess.run(
                [binary, "--user", verb, HOST_UNIT], capture_output=True, text=True,
                timeout=FIX_TIMEOUT_SECS, check=False, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AnswerError(f"systemctl --user {verb} {HOST_UNIT} failed: {exc}", EXIT_REFUSED) from exc
        if proc.returncode != 0:
            raise AnswerError(
                f"systemctl --user {verb} {HOST_UNIT} exited {proc.returncode}: "
                f"{str(proc.stderr or proc.stdout or '').strip()[:400]}", EXIT_REFUSED,
            )
    _try_seal(home, item, {"role": "user", "origin": "clicked", "kind": "fix", "text": None,
                           "option": option})
    return f"{HOST_UNIT} restarted; the item ends when its heartbeat is fresh again"


# ------------------------------------------------------------------ stop


#: A unit `attention run` launched, as a cgroup path segment
#: (``RUN_UNIT_PREFIX`` + 12 hex + ``.service``).
_RUN_UNIT_SEGMENT_RE = re.compile(r"^(self-learn-run-[0-9a-f]{12})\.service$")
#: Where the claiming process's cgroup is read (a test points it elsewhere).
_CGROUP_PATH = Path("/proc/self/cgroup")
#: ``systemctl is-active`` answers that mean the unit still runs.
_STILL_RUNNING = frozenset({"active", "activating", "deactivating", "reloading", "refreshing"})
STOPPED_MESSAGE = (
    "Stopped. The terminal opened for this work is closed, so its session can change nothing "
    "more. A step it was in the middle of stopped where it was and was not undone, and "
    "anything it had already changed stays changed. Your approval still stands but nothing is "
    "carrying it out: choose a different answer, or Run it now to start again."
)
ALREADY_CLOSED_MESSAGE = (
    "The terminal opened for this work had already closed, so its session could change "
    "nothing more; its hold on the work is cleared. Anything it changed before it closed "
    "stays changed. Your approval still stands but nothing is carrying it out: choose a "
    "different answer, or Run it now to start again."
)


def _unit_state(binary: str, unit: str) -> str:
    try:
        proc = subprocess.run(
            [binary, "--user", "is-active", unit], capture_output=True, text=True,
            timeout=STOP_TIMEOUT_SECS, check=False, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AnswerError(f"systemctl --user is-active {unit} failed: {exc}", EXIT_REFUSED) from exc
    return str(proc.stdout or "").strip() or "unknown"


def _mark_run_stopped(home: Path, item_id: str, record: dict) -> None:
    """The run record (cache) gains ``stopped_at``: the reader then counts
    the launch as stopped, not running."""
    target = _cache(home) / "attention" / "runs" / f"{item_id}.json"
    fsops.atomic_write(target, json.dumps({**record, "stopped_at": chrono.now_iso()}) + "\n",
                       fsync=False)


def stop(home: Path | str, item_id: str) -> str:
    """``self-learn attention stop <id>`` (follow-ups 2, gap 2): the page's
    "Stop it" on approved work a session has claimed. A new answer is
    refused while a live claim holds the work (:func:`answer`), because a
    different answer cannot reach a session already carrying it out; this
    is the one honest way to change course then. It acts only on a claim
    made in the terminal this page launched (``attention.stoppable``): it
    stops that unit (``systemctl --user stop``, bounded), checks it no
    longer runs, marks the launch stopped and clears the claim (both
    cache), and seals a workspace row ``kind: stop``. It undoes nothing the
    session already did, and the approval stands until the person answers
    otherwise. Refused from an agent's shell (64): it acts on the person's
    click. Exits 2 when *item_id* is not approved work, 3 when nothing
    holds a claim, the claim is a session the page did not open, or the
    unit would not stop."""
    home = Path(home)
    if _agent():
        raise AnswerError(
            "refused from an agent's shell: stopping work the person approved is the person's "
            "click", EXIT_USAGE,
        )
    item = _approved_for(_items(home), item_id)
    if item is None or item["kind"] != "approved.pending":
        raise AnswerError(f"{item_id} is not approved work being carried out", EXIT_UNKNOWN)
    claim_row = attention._claim(home, item["id"], _now())  # noqa: SLF001
    if claim_row is None:
        raise AnswerError(
            "no session has claimed it, so there is nothing to stop: a different answer is "
            "taken now, and a session that tries to claim the work afterwards is refused and "
            "changes nothing", EXIT_REFUSED,
        )
    record = attention._run_record(home, item["id"])  # noqa: SLF001
    # Gate r1 F1/F2: only a claim made from inside the unit the page
    # launched for THIS approval (this item's own unit name) is stoppable.
    # Any other claim is left exactly as it is: the page cannot stop that
    # session, so it never releases its hold either.
    if record is None or not attention.stoppable(
        record, claim_row, item_id=item["id"], approved_at=item.get("_approved_at"),
    ):
        raise AnswerError(
            f"{attention.NOT_OURS_REASON} (session {claim_row.get('session')}); the page cannot "
            "stop it, and its hold on the work stays", EXIT_REFUSED,
        )
    unit = attention.run_unit(item["id"])
    binary = shutil.which("systemctl")
    if binary is None:
        raise AnswerError("systemctl is not on PATH", EXIT_REFUSED)
    message = ALREADY_CLOSED_MESSAGE
    if _unit_state(binary, unit) in _STILL_RUNNING:
        try:
            subprocess.run(
                [binary, "--user", "stop", unit], capture_output=True, text=True,
                timeout=STOP_TIMEOUT_SECS, check=False, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AnswerError(f"systemctl --user stop {unit} failed: {exc}", EXIT_REFUSED) from exc
        state = _unit_state(binary, unit)
        if state in _STILL_RUNNING:
            raise AnswerError(
                f"{unit} did not stop (systemd says it is {state}); nothing else was changed",
                EXIT_REFUSED,
            )
        message = STOPPED_MESSAGE
    _mark_run_stopped(home, item["id"], record)
    _clear_claim(home, item["id"])
    _try_seal(home, item, {"role": "user", "origin": "clicked", "kind": "stop", "text": None,
                           "option": None})
    return message


# ------------------------------------------------------------------ claim and done


def _claim_path(home: Path, item_id: str) -> Path:
    return _cache(home) / "attention" / "claims" / f"{item_id}.json"


def caller_unit() -> str | None:
    """Gate r1 F1: the ``self-learn-run-<12 hex>`` unit this process runs
    in, read from its cgroup (``/proc/self/cgroup``: a session ``attention
    run`` launched, and every command it runs, live in that transient
    unit's cgroup), or ``None`` when it runs anywhere else or the file
    cannot be read. A claim records it, so "Stop it" can tell the terminal
    the page opened from any other session."""
    try:
        # Gate r2 R2-1: a path that is not UTF-8 never fails the claim;
        # a run unit name is ASCII, so a replaced byte cannot fake one.
        text = _CGROUP_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        path = line.split(":", 2)[-1]
        for segment in reversed(path.split("/")):
            match = _RUN_UNIT_SEGMENT_RE.fullmatch(segment)
            if match is not None:
                return match.group(1)
    return None


def _write_claim(home: Path, item_id: str, session: str) -> None:
    """``<cache>/attention/claims/<id>.json`` (cache only; 2-hour TTL):
    ``{session, at, unit}``, ``unit`` the caller's own run unit or null
    (gate r1 F1)."""
    target = _claim_path(home, item_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(
        target,
        json.dumps({"session": session, "at": chrono.now_iso(), "unit": caller_unit()}) + "\n",
        fsync=False,
    )


def _clear_claim(home: Path, item_id: str) -> None:
    """Remove a claim once its work is done (cache only)."""
    _claim_path(home, item_id).unlink(missing_ok=True)


def _approved_or_refuse(home: Path, item_id: str, code: int = EXIT_UNKNOWN) -> dict:
    item = _approved_for(_items(home), item_id, home)
    if item is None:
        raise AnswerError(
            f"{item_id} is not an approved change waiting to be carried out (it is done, or the "
            "person changed their answer before it was claimed); change nothing", code,
        )
    return item


def claim(home: Path | str, item_id: str, session: str) -> dict:
    """``attention claim <id> --session ID`` (§3.4.7): the carrying-out
    session says it is on it. Another session's live claim refuses (3)."""
    home = Path(home)
    session = (session or "").strip()
    if not session:
        raise AnswerError("claim needs --session (your $CLAUDE_CODE_SESSION_ID)", EXIT_USAGE)
    item = _approved_or_refuse(home, item_id)
    current = attention._claim(home, item["id"], _now())  # noqa: SLF001
    if current is not None and current.get("session") != session:
        raise AnswerError(
            f"{item['id']} is claimed by session {current.get('session')} (since "
            f"{current.get('at')}); one session carries it out", EXIT_REFUSED,
        )
    _write_claim(home, item["id"], session)
    # Gate r2 NIT 2: the person may have changed their answer between the
    # read above and the write. `answer` reads the claim again after its
    # commit; reading the items again here means one side always sees the
    # other. Changed: the claim goes, and the session changes nothing.
    try:
        _approved_or_refuse(home, item["id"])
    except AnswerError:
        _clear_claim(home, item["id"])
        raise
    return item


def done(home: Path | str, item_id: str, *, session: str, note: str | None,
         failed: bool = False) -> str:
    """``attention done <id> --note TEXT --session ID [--failed]`` (§3.4.7):
    only the session holding the live claim closes the work. Appends an
    ``attention/outcomes.jsonl`` row; ``--failed`` returns the item to the
    person with the reason first among its evidence, and the approval no
    longer stands."""
    home = Path(home)
    if not (note or "").strip():
        raise AnswerError("done needs --note saying what you did or found", EXIT_USAGE)
    stopped = _ledger_stopped(home)
    if stopped and not (failed and _held_approval(home, item_id) is not None):
        raise _held()
    item = _approved_or_refuse(home, item_id)
    current = attention._claim(home, item["id"], _now())  # noqa: SLF001
    session = (session or "").strip()
    if current is None or current.get("session") != session:
        claimant = (
            f"session {current.get('session')} holds the claim" if current is not None
            else "no session holds a live claim (run `attention claim` first)"
        )
        raise AnswerError(f"{item['id']}: {claimant}; nothing was recorded", EXIT_REFUSED)
    if stopped:
        # Gate r1 NIT 8: "Have an agent look at it" on a STOPPED ledger, and
        # the session decided not to clear the intent. Nothing can be
        # committed, and nothing was: the click was only held on this
        # machine. The held click and the claim are dropped, so the item is
        # the person's again at once (not "running" until the claim lapses),
        # and the session's finding is kept as a pending transcript row.
        _clear_held_approval(home, item["id"])
        _clear_claim(home, item["id"])
        _try_seal(home, item, {
            "role": "system", "origin": "system", "kind": "note",
            "text": "The agent stopped and changed nothing more: " + str(note),
        })
        return "nothing committed (the ledger is STOPPED); the item is yours again"
    held = _held_approval(home, item["id"])
    if held is not None:
        from .overseer import conversation

        conversation.record_choice(home, held)
        _clear_held_approval(home, item["id"])
    outcome = append_outcome(home, {
        "item": item["id"], "subject": item.get("subject"),
        "result": "failed" if failed else "done", "note": note, "session": session,
        "by": _actor(),
    })
    _clear_claim(home, item["id"])
    _try_seal(home, item, {
        "role": "system", "origin": "system", "kind": "note",
        "text": ("The agent stopped and changed nothing more: " if failed
                 else "Carried out by an agent: ") + str(note),
    })
    return outcome


# ------------------------------------------------------------------ undo


def redo_offered(home: Path | str, item_id: str) -> bool:
    """Whether the item's last undo/redo row is an undo (so redo is what the
    page offers next)."""
    try:
        rows = workspace.rows(home, item_id)
    except Exception:  # noqa: BLE001
        return False
    acts = [r.get("kind") for r in rows if r.get("kind") in ("undo", "redo")]
    return bool(acts) and acts[-1] == "undo"


def _authorized(home: Path, surface: str, note: str | None) -> attribution.Authority | None:
    from . import grants

    try:
        return grants.authorize(home, surface, note=note)
    except grants.GrantError as exc:
        raise AnswerError(f"{surface}: {exc}", exc.exit_code) from exc


def _run_argv(home: Path, argv: list[str], *, note: str, no_push: bool) -> str:
    """Run one inverse (or redo) of a decided item, given as the argv after
    ``self-learn`` (``attention._grant_use_undo``'s form), through the
    library function of that verb. Person-only verbs run under
    ``grants.authorize`` from an agent's shell, and are themselves a grant
    use then."""
    from . import grant_uses, hosts, skill_writer
    from .skill_writer import rename as rename_skill  # as skill_cli: not a Path.rename

    words = [w for w in argv]
    if words[:2] == ["config", "set"] and len(words) >= 3:
        name = words[2]
        value = words[4] if len(words) >= 5 and words[3] == "--" else (words[3] if len(words) >= 4 else "")
        verb, args = "config set", [name, value]
    elif words[:2] == ["config", "unset"] and len(words) >= 3:
        name, verb, args = words[2], "config unset", [words[2]]
    elif words[:2] == ["host", "remove"] and len(words) >= 3:
        verb, args = "host remove", words[2:]
    elif words[:2] == ["host", "add"] and len(words) >= 3:
        verb, args = "host add", words[2:]
    elif words[:2] == ["host", "set-mode"] and len(words) >= 4:
        verb, args = "host set-mode", words[2:]
    elif words[:2] == ["skill", "retire"] and len(words) >= 3:
        verb, args = "skill retire", words[2:]
    elif words[:2] == ["skill", "rename"] and len(words) >= 4:
        verb, args = "skill rename", words[2:]
    elif words[:2] == ["skill", "write"] and len(words) >= 5 and words[3] == "--from":
        # The redo of a written skill (gate r1 MINOR 6): its grant-use row
        # keeps `<name> --from <folder>` (`skill_cli._use_args`).
        verb, args = "skill write", words[2:5]
    elif words[:2] == ["skill", "veto"] and len(words) >= 3:
        verb, args = "skill veto", words[2:]
    else:
        raise AnswerError(f"no inverse can be run for `self-learn {' '.join(words)}`", EXIT_REFUSED)
    granted = _authorized(home, verb, note)
    prior: Any = None
    if verb.startswith("config"):
        from . import cli as cli_mod  # lazy: cli imports this module through attention_cli

        prior = cli_mod._config_prior(home, args[0])  # noqa: SLF001
    use = grant_uses.GrantUse(home, verb, list(args), prior=prior) if granted is not None else None
    kind = "skills-root" if "--skills-root" in args else "project"
    path = args[0] if args else ""
    by = "agent" if granted else "human"
    files: Any = None
    if verb == "skill write":
        if not Path(args[2]).is_absolute():
            # Gate r2 NIT 4: `skill_cli._use_args` keeps `--from` as typed;
            # a relative folder would resolve against this process's working
            # directory, not the one the write ran in, and could name a
            # different folder of the same name.
            raise AnswerError(
                f"the skill cannot be written again: its draft folder was recorded as "
                f"{args[2]}, relative to a shell this page cannot know; nothing was run. Say "
                "in your own words what you want instead", EXIT_REFUSED,
            )
        try:
            files = skill_writer.read_draft_dir(args[2])
        except (ValueError, OSError) as exc:
            raise AnswerError(
                f"the skill cannot be written again: its draft folder {args[2]} cannot be read "
                f"({exc}); nothing was run. Say in your own words what you want instead",
                EXIT_REFUSED,
            ) from exc
    try:
        with attribution.acting(granted, use=use):
            if verb == "config set":
                settings.config_set(home, args[0], args[1], note=note)
            elif verb == "config unset":
                settings.config_unset(home, args[0], note=note)
            elif verb == "host remove":
                hosts.host_remove(home, path, registration=kind, note=note)
            elif verb == "host add":
                mode = args[args.index("--mode") + 1] if "--mode" in args else "plain"
                hosts.host_add(home, path, kind, mode=mode, note=note)
            elif verb == "host set-mode":
                hosts.host_set_mode(home, path, args[1], registration=kind, note=note)
            elif verb == "skill retire":
                outcome = skill_writer.retire(home, args[0], case=None, by=by, no_push=no_push)
                if not outcome.ok:
                    if use is not None:
                        use.applies = False
                    raise AnswerError(f"skill retire refused: {'; '.join(outcome.problems)}",
                                      EXIT_REFUSED)
            elif verb == "skill write":
                written = skill_writer.write(home, args[0], files, case=None, by=by,
                                             no_push=no_push)
                if not written.ok:
                    if use is not None:
                        use.applies = False
                    raise AnswerError(f"skill write refused: {'; '.join(written.problems)}",
                                      EXIT_REFUSED)
            elif verb == "skill veto":
                from . import skill_requests

                rename_to = args[args.index("--rename-to") + 1] if "--rename-to" in args[:-1] else None
                vetoed = skill_requests.veto(
                    home, args[0], by=by, rename_to=rename_to, no_push=no_push,
                    grant=granted.ref if granted is not None and granted.kind == "grant" else None,
                )
                if not vetoed.ok:
                    if use is not None:
                        use.applies = False
                    raise AnswerError(f"skill veto refused: {'; '.join(vetoed.problems)}",
                                      EXIT_REFUSED)
            else:
                outcome2 = rename_skill(home, args[0], args[1], case=None,
                                               by=by, no_push=no_push)
                if not outcome2.ok:
                    if use is not None:
                        use.applies = False
                    raise AnswerError(f"skill rename refused: {'; '.join(outcome2.problems)}",
                                      EXIT_REFUSED)
    except (hosts.HostsError, settings.SettingsError) as exc:
        raise AnswerError(f"{verb} refused: {exc}", EXIT_REFUSED) from exc
    return f"self-learn {verb} {' '.join(args)}".strip()


def undo(home: Path | str, item_id: str, *, redo: bool = False, note: str | None = None,
         no_push: bool = False) -> str:
    """``self-learn attention undo <id> [--redo]`` (§3.4.6). Returns what
    was run. From an agent's shell it needs ``--note`` and is stamped ``By:
    agent`` (its own act); from the page it is the person's, noted "undone
    from the inbox"."""
    from . import ledger_ops, verbs
    from .overseer import conversation

    home = Path(home)
    agent = _agent()
    if agent and not (note or "").strip():
        raise AnswerError(
            "from an agent's shell undo needs --note TEXT saying why; the ledger records it as "
            f"By: agent (agent shell detected: {', '.join(settings.agent_caller_markers())})",
            EXIT_USAGE,
        )
    reason = (note or "").strip() or ("redone from the inbox" if redo else "undone from the inbox")
    if _ledger_stopped(home):
        raise _held()
    item = _find(home, item_id)
    if item is None:
        raise AnswerError(f"unknown item {item_id}", EXIT_UNKNOWN)
    kind = item["kind"]
    if kind not in UNDO_KINDS:
        raise AnswerError(
            f"{item_id} ({kind}) has no one-click inverse; tell it in your own words instead",
            EXIT_REFUSED,
        )
    try:
        if kind == "decided.hook-activated":
            lesson = str(item.get("_lesson") or "")
            verb_fn = verbs.hook_activate if redo else verbs.hook_deactivate
            verb_fn(home, lesson, no_push=no_push, by="agent" if agent else None, note=reason)
            did = f"hook {'activate' if redo else 'deactivate'} {lesson}"
        elif kind == "decided.registration":
            registration = item.get("_registration") or {}
            path, reg_kind = str(registration.get("path")), str(registration.get("kind"))
            flag = "--skills-root" if reg_kind == "skills-root" else "--project"
            argv = (["host", "add", path, *(["--skills-root"] if reg_kind == "skills-root" else []),
                     "--mode", "plain"] if redo else ["host", "remove", path, flag])
            did = _run_argv(home, argv, note=reason, no_push=no_push)
        elif kind == "decided.skill":
            argv_raw = item.get("_undo_verb")
            if redo or not isinstance(argv_raw, list):
                raise AnswerError("a skill decision is redone in words only", EXIT_REFUSED)
            did = _run_argv(home, [str(a) for a in argv_raw], note=reason, no_push=no_push)
        elif kind == "decided.grant-use":
            row = item.get("_grant_use") or {}
            if redo:
                argv = [*str(row.get("verb") or "").split(), *[str(a) for a in row.get("args") or []]]
                if argv[:2] == ["config", "set"] and len(argv) == 4:
                    argv = [*argv[:3], "--", argv[3]]
            else:
                raw = item.get("_undo_verb")
                if not isinstance(raw, list):
                    raise AnswerError(f"{item_id} has no recorded inverse", EXIT_REFUSED)
                argv = [str(a) for a in raw]
            did = _run_argv(home, argv, note=reason, no_push=no_push)
        else:  # decided.withdrawn
            if redo:
                raise AnswerError("a reopened question has no redo", EXIT_REFUSED)
            conversation.reopen(home, str(item.get("subject")))
            did = f"reopened {item.get('subject')}"
    except verbs.VerbError as exc:
        raise AnswerError(f"{exc}", EXIT_REFUSED) from exc
    except conversation.ConversationError as exc:
        raise AnswerError(f"{exc}", EXIT_REFUSED) from exc
    except ledger_ops.LedgerOpsError as exc:
        # Integration of 2026-10-31c (found by the ui-workspace lane in its
        # walk world): an inverse whose record is gone (RecordNotFound) is
        # refused in words, never an unhandled traceback.
        raise AnswerError(f"the inverse could not be run: {exc}", EXIT_REFUSED) from exc
    _try_seal(home, item, {"role": "user" if not agent else "agent",
                           "origin": "clicked" if not agent else "agent",
                           "kind": "redo" if redo else "undo", "text": None, "option": None})
    return did
