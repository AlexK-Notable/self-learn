"""The context packet of one inbox item (attention round, design r2 §3.2;
contract §4.3).

Everything the decision workspace and the "ask about this" agent need for
one item, built by code: the item, the question in plain words, why it
needs the user, what happens meanwhile, the recommendation and the
alternatives, the plan an agent would carry out, what was decided and its
undo, the evidence assembled in place (lessons, the user's statements with
their transcript or workspace context, cases, the report, files, holds,
grants, facts), pointers to look further, the conversation's state, the
latest answer, and the cuts made to fit the bounds.

:func:`build` reads the ledger and cache files only. It makes no model
call, writes nothing to the ledger, and never runs git. One read of the
ledger's history is handed in by the verb that builds the packet
(follow-ups 2, gap 1): a ``conflict.case-tampered`` item's ``case_edit``
shows what the case said when it was decided through the caller's
*decided_reader* (``cases.decided_text``); without one it says the decided
text was not looked up.

**One deny list** (:data:`SECRET_DENY`) serves this packet's ``look_at``
filter and the ask agent's read fence; the ask lane imports it and never
copies it.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import attention
from .primitives import chrono
from .scan import scan as secret_scan

__all__ = [
    "MAX_BYTES",
    "MAX_CONTEXT_CHARS",
    "MAX_EVIDENCE",
    "MAX_LOOK_AT",
    "MAX_TEXT_CHARS",
    "PACKET_VERSION",
    "SECRET_DENY",
    "DecidedReader",
    "DenyList",
    "UnknownItem",
    "build",
    "deny_paths",
    "denied_name",
    "filter_look_at",
    "plain_reason",
    "redact_text",
    "render_md",
]

PACKET_VERSION = 1
MAX_BYTES = 64 * 1024
MAX_TEXT_CHARS = 4000
MAX_CONTEXT_CHARS = 1200
MAX_EVIDENCE = 12
MAX_LOOK_AT = 5
CONTEXT_BUDGET_SECS = 1.5


class UnknownItem(LookupError):
    """No item has that id (the CLI's exit 2)."""


@dataclass(frozen=True)
class DenyList:
    """Paths (templates: ``~``, ``<cache>``, ``$XDG_RUNTIME_DIR``) and
    basename globs (case-insensitive) that never reach a packet or the ask
    agent. :func:`deny_paths` resolves the templates for one home."""

    paths: tuple[str, ...]
    names: tuple[str, ...]


SECRET_DENY = DenyList(
    paths=(
        "~/.ssh", "~/.gnupg", "~/.claude/.credentials.json", "~/.config/gh", "~/.config/bws",
        "~/.local/share/keyrings", "<cache>/ui-token", "$XDG_RUNTIME_DIR/self-learn",
    ),
    names=(
        "*.env", ".env*", "*credential*", "*token*", "*secret*", "id_*", "*.pem", "*.key",
        ".mcp.json", ".netrc", "hosts.yml",
    ),
)


def deny_paths(home: Path | str) -> tuple[str, ...]:
    """:data:`SECRET_DENY`'s paths, absolute, for *home*'s cache. A
    ``$XDG_RUNTIME_DIR`` template with the variable unset is left out."""
    cache = str(attention.cache_dir(home))
    out: list[str] = []
    for template in SECRET_DENY.paths:
        if template.startswith("$XDG_RUNTIME_DIR"):
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            if not runtime:
                continue
            template = runtime + template[len("$XDG_RUNTIME_DIR"):]
        path = template.replace("<cache>", cache)
        out.append(str(Path(path).expanduser()))
    return tuple(out)


def denied_name(name: str) -> bool:
    """Whether basename *name* matches a :data:`SECRET_DENY` name glob."""
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, glob.lower()) for glob in SECRET_DENY.names)


def _under(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)


def filter_look_at(home: Path | str, paths: list[object]) -> tuple[list[str], list[str]]:
    """``(kept, dropped)`` of an item's ``look_at`` paths (§3.2): a path is
    kept only when it is absolute and exists; neither it nor its resolved
    target is under a deny path or has a deny name; it is not ``/`` or
    ``$HOME``; and it is at least two components deep (below ``$HOME`` when
    it is under it, else from ``/``). At most :data:`MAX_LOOK_AT` are kept.
    Each dropped entry names the path and why."""
    denied = deny_paths(home)
    user_home = str(Path.home())
    kept: list[str] = []
    dropped: list[str] = []
    for raw in paths:
        text = str(raw) if isinstance(raw, str) else repr(raw)
        if not isinstance(raw, str) or not raw.startswith("/"):
            dropped.append(f"{text}: not an absolute path")
            continue
        path = os.path.normpath(raw)
        real = os.path.realpath(path)
        if not os.path.exists(path):
            dropped.append(f"{text}: does not exist")
            continue
        if path in ("/", user_home) or real in ("/", user_home):
            dropped.append(f"{text}: the whole of / or $HOME")
            continue
        if _under(path, denied) or _under(real, denied):
            dropped.append(f"{text}: under a secret path")
            continue
        if denied_name(os.path.basename(path)) or denied_name(os.path.basename(real)):
            dropped.append(f"{text}: a secret file name")
            continue
        depth_of = path[len(user_home):] if _under(path, (user_home,)) else path
        if len([part for part in depth_of.split("/") if part]) < 2:
            dropped.append(f"{text}: too shallow (at least two components deep)")
            continue
        if len(kept) >= MAX_LOOK_AT:
            dropped.append(f"{text}: over the limit of {MAX_LOOK_AT} paths")
            continue
        kept.append(path)
    return kept, dropped


def redact_text(text: str) -> str:
    """*text* with every secret-scan hit swapped for ``[redacted: <rule>]``."""
    hits = secret_scan(text)
    if not hits:
        return text
    out: list[str] = []
    cursor = 0
    for hit in hits:
        if hit.start < cursor:
            continue
        out.append(text[cursor:hit.start])
        out.append(f"[redacted: {hit.rule}]")
        cursor = hit.end
    out.append(text[cursor:])
    return "".join(out)


class _Limits:
    def __init__(self) -> None:
        self.truncated: list[str] = []

    def clip(self, text: object, where: str, limit: int = MAX_TEXT_CHARS) -> str | None:
        if text is None:
            return None
        value = redact_text(str(text))
        if len(value) > limit:
            self.truncated.append(where)
            value = value[: limit - 1].rstrip() + "…"
        return value


# ------------------------------------------------------------------ evidence


#: Walk fixes, item 6: the most sightings a lesson entry lists.
MAX_SIGHTINGS = 10


def _sections(body: str) -> dict[str, str]:
    """A record body's ``## Name`` sections, name -> text."""
    from .primitives import text as text_mod

    out: dict[str, str] = {}
    matches = list(text_mod.HEADING_RE.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[m.group(1)] = body[m.end():end].strip()
    return out


def _sightings(record: Any, limits: _Limits, where: str) -> list[dict]:
    """Walk fixes, item 6: each time the lesson was seen (its frontmatter
    ``evidence``: a session and time with the quote, or an origin with a
    note), newest first, so a claim like "came up at least twice" can be
    checked in place."""
    rows = [dict(e) for e in getattr(record, "evidence", ()) or () if isinstance(e, dict)]
    rows.sort(key=lambda e: str(e.get("ts") or ""), reverse=True)
    out: list[dict] = []
    for index, entry in enumerate(rows[:MAX_SIGHTINGS]):
        out.append({
            "at": entry.get("ts") if isinstance(entry.get("ts"), str) else None,
            "session": entry.get("session") if isinstance(entry.get("session"), str) else None,
            "origin": entry.get("origin") if isinstance(entry.get("origin"), str) else None,
            "quote": limits.clip(entry.get("quote") or entry.get("note"),
                                 f"{where}.seen[{index}]", 400),
        })
    return out


def _lesson(home: Path, lesson_id: str, limits: _Limits, where: str) -> dict | None:
    from .ledger_ops import LedgerOpsError, find_record_path
    from .records import Record

    try:
        record = Record.from_path(find_record_path(home, lesson_id))
    except (LedgerOpsError, OSError, ValueError):
        return None
    body = record.body
    sections = _sections(body)
    # Walk fixes, item 6: the title is what the lesson is about (its
    # trigger, or its fact), never the first heading's name ("Trigger").
    lead = sections.get("Trigger") or sections.get("Fact")
    title = (
        " ".join(lead.split()) if lead
        else next((ln.lstrip("# ").strip() for ln in body.splitlines() if ln.strip()), lesson_id)
    )
    routing = record.routing or {}
    sightings = getattr(record, "sightings", None)
    return {
        "kind": "lesson", "id": lesson_id, "title": limits.clip(title, f"{where}.title", 300),
        "text": limits.clip(body, f"{where}.text"), "status": record.status,
        "placement": routing.get("destination") if isinstance(routing, dict) else None,
        "trigger": limits.clip(sections.get("Trigger"), f"{where}.trigger", 1000),
        "instruction": limits.clip(sections.get("Instruction"), f"{where}.instruction", 1000),
        "fact": limits.clip(sections.get("Fact"), f"{where}.fact", 1000),
        "sightings": sightings if isinstance(sightings, int) else None,
        "seen": _sightings(record, limits, where),
    }


def _context(home: Path, ref: str, limits: _Limits, where: str, deadline: float) -> tuple[str | None, str | None]:
    """The role-labelled lines around a statement's ref, or why not."""
    if time.monotonic() > deadline:
        return None, "not read (time budget)"
    try:
        if ref.startswith("workspace:"):
            from . import workspace

            text = workspace.excerpt(home, ref)
        elif ref.startswith("transcript:"):
            from . import refs

            session, number = ref[len("transcript:"):].rsplit("#L", 1)
            roots = refs.transcript_roots(home)
            resolved = refs.resolve(session, line=int(number), roots=roots)
            lines = refs.excerpt(resolved, roots=roots, total_chars=MAX_CONTEXT_CHARS * 2)
            text = "\n".join(f"{r.role}: {t}" for r, t in lines)
        else:
            return None, "no context for this kind of ref"
    except Exception as exc:  # noqa: BLE001 -- context is a courtesy
        return None, _context_problem(exc)
    if text is None:
        return None, "not found: the place it points to is not there any more"
    return limits.clip(text, f"{where}.context", MAX_CONTEXT_CHARS), None


def _context_problem(exc: Exception) -> str:
    """Walk fixes, item 6: why a statement's conversation was not shown, in
    plain words (the page prints "The conversation around it was <this>."),
    never an exception's class name."""
    from . import refs

    if isinstance(exc, refs.RefError):
        return ("not found on this machine: the conversation file it came from was moved or "
                "deleted (the words themselves are kept)")
    if isinstance(exc, OSError):
        return "not readable here (the file could not be opened)"
    return "not read (it could not be parsed)"


def _statement(home: Path, row: dict, limits: _Limits, where: str, deadline: float) -> dict:
    ref = str((row.get("source") or {}).get("message_ref") or "")
    context, note = _context(home, ref, limits, where, deadline)
    return {
        "kind": "statement", "id": row.get("id"), "at": row.get("at"),
        "verbatim": limits.clip(row.get("verbatim"), f"{where}.verbatim"),
        "answers": row.get("answers"), "ref": ref or None, "context": context,
        "context_note": note,
    }


#: The most of a case file read directly (a tampered case, below).
MAX_CASE_FILE_BYTES = 256 * 1024


def _line_value(text: str | None, key: str) -> str | None:
    """The value of the first ``- <key>: value`` line in *text*."""
    prefix = f"- {key}:"
    for line in (text or "").splitlines():
        if line.strip().startswith(prefix):
            return line.strip()[len(prefix):].strip() or None
    return None


def _case_links(frontmatter: dict, sections: dict[str, str]) -> list[str]:
    """The lessons (frontmatter ``records``) and statements (section 4,
    ``- statements: [...]``) a case names, in that order."""
    from . import cases

    out = [str(r) for r in frontmatter.get("records") or [] if isinstance(r, str)]
    for line in (sections.get("Dependencies") or "").splitlines():
        if line.strip().startswith("- statements:"):
            out += [s for s in cases._parse_bracket_list(line.strip())  # noqa: SLF001
                    if s.startswith("stmt-")]
    return list(dict.fromkeys(out))


def _case_entry(case_id: str, sections: dict[str, str], body: str, limits: _Limits,
                where: str) -> dict:
    decision = sections.get("Decision")
    return {
        "kind": "case", "id": case_id,
        "question": limits.clip(
            _line_value(sections.get("Identity and scope"), "question"), f"{where}.question", 600),
        "decision": limits.clip(decision, f"{where}.decision", 1200),
        # Humane UI lane 3 (proposal §4): the decision's own fields, so a
        # page tells the case once (Question, Decision in words, Because)
        # instead of printing the section's list as one paragraph.
        "verb": _line_value(decision, "verb"),
        "confidence": _line_value(decision, "confidence"),
        "because": limits.clip(_line_value(decision, "because"), f"{where}.because", 1200),
        "excerpt": limits.clip(body, f"{where}.excerpt"),
    }


def _case(home: Path, case_id: str, limits: _Limits, where: str) -> tuple[dict | None, list[str]]:
    """The case's entry (its full, freeze-checked view) and the lessons and
    statements it names. A missing case, or one whose freeze hash fails,
    is no entry here: :func:`_evidence` then reads a tampered case's text
    through :func:`_edited_case`."""
    from . import cases

    try:
        view = cases.show(home, case_id, evidence_only=False)
    except Exception:  # noqa: BLE001 -- a missing or tampered case is no entry
        return None, []
    sections = view.sections
    body = "\n\n".join(f"## {k}\n{v}" for k, v in sections.items())
    return _case_entry(case_id, sections, body, limits, where), _case_links(view.frontmatter, sections)


def _case_file_now(
    home: Path, case_id: str,
) -> tuple[Path, dict, str, str | None, dict[str, str]] | None:
    """A case file as it is now, read directly (no git, at most
    :data:`MAX_CASE_FILE_BYTES`): ``(path, frontmatter, body, frozen
    sections 1-4 or None when the headings no longer parse, sections)``, or
    ``None`` for a missing case. Its frontmatter or headings may be what
    was edited, so each part that does not parse is left empty."""
    from . import cases

    try:
        path = cases._case_path_for_id(home, case_id)  # noqa: SLF001
        with path.open("rb") as fh:
            raw = fh.read(MAX_CASE_FILE_BYTES)
    except Exception:  # noqa: BLE001 -- a missing case is no entry
        return None
    text = raw.decode("utf-8", errors="replace")
    frontmatter: dict = {}
    sections: dict[str, str] = {}
    frozen: str | None = None
    try:
        frontmatter, body = cases._split_frontmatter(text)  # noqa: SLF001
    except Exception:  # noqa: BLE001 -- the frontmatter itself may be what was edited
        body = text
    try:
        frozen, _rest = cases._split_frozen(body)  # noqa: SLF001
        sections = cases._parse_sections(body)  # noqa: SLF001
    except Exception:  # noqa: BLE001 -- the headings may be what was edited
        frozen = None
    return path, frontmatter, body, frozen, sections


#: A reader of a case's decided text (``cases.decided_text``): the packet
#: never runs git itself, so the verb that builds it hands one in.
DecidedReader = Callable[[Path, str], "dict[str, Any] | None"]
#: The most changed passages a ``case_edit`` lists, and each one's length.
MAX_CASE_CHANGES = 12
MAX_CHANGE_CHARS = 1200


def _changes(decided: str, now: str, limits: _Limits) -> list[dict]:
    """The passages where *now* differs from *decided*, line by line, each
    ``{"was": decided lines, "now": the file's lines}`` (an empty side is
    ``""``: lines added or taken out), at most :data:`MAX_CASE_CHANGES`."""
    import difflib

    old, new = decided.splitlines(), now.splitlines()
    out: list[dict] = []
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if len(out) == MAX_CASE_CHANGES:
            limits.truncated.append(f"case_edit.changes: more than {MAX_CASE_CHANGES} passages")
            break
        where = f"case_edit.changes[{len(out)}]"
        out.append({
            "was": limits.clip("\n".join(old[i1:i2]), f"{where}.was", MAX_CHANGE_CHARS),
            "now": limits.clip("\n".join(new[j1:j2]), f"{where}.now", MAX_CHANGE_CHARS),
        })
    return out


def _case_edit(home: Path, item: dict, limits: _Limits,
               decided_reader: DecidedReader | None) -> dict | None:
    """Follow-ups 2 (gap 1): on a ``conflict.case-tampered`` page, what
    the case said when it was decided beside what the file says now, and
    the passages that differ, so the person sees the edit before choosing
    keep or restore. The decided text comes from *decided_reader* (the
    ``attention packet`` and ``ask`` verbs pass ``cases.decided_text``,
    the same lookup ``refreeze --restore`` uses); this module runs no git.
    Without a reader, or when it finds no decided commit or fails, the
    block says so in ``note`` and ``decided`` is ``None``."""
    if item["kind"] != "conflict.case-tampered":
        return None
    case_id = str(item.get("subject"))
    now = _case_file_now(home, case_id)
    now_text = None if now is None else (now[3] if now[3] is not None else now[2])
    decided: dict | None = None
    decided_text: str | None = None
    note: str | None = None
    if decided_reader is None:
        note = "the decided text was not looked up here"
    else:
        found: dict[str, Any] | None = None
        try:
            found = decided_reader(home, case_id)
        except Exception as exc:  # noqa: BLE001 -- the page still works without it
            note = f"the ledger's history could not be read ({type(exc).__name__})"
        else:
            if found is None:
                note = ("no commit of this case holds the text it was decided with, so it "
                        "cannot be shown, and restoring it would be refused")
        if isinstance(found, dict) and isinstance(found.get("text"), str):
            decided_text = str(found["text"])
            decided = {
                "text": limits.clip(decided_text, "case_edit.decided.text"),
                "commit": str(found.get("commit") or "")[:12] or None,
                "committed_at": found.get("committed_at"),
                "truncated": bool(found.get("truncated")),
            }
    changes: list[dict] = []
    if decided_text is not None and now_text is not None:
        # Compared whole (both secret-scanned), then each passage clipped.
        changes = _changes(redact_text(decided_text), redact_text(now_text), limits)
    return {
        "case": case_id,
        "decided": decided,
        "now": limits.clip(now_text, "case_edit.now"),
        "changes": changes,
        "note": note,
    }


def _edited_case(home: Path, case_id: str, limits: _Limits, where: str, fact_where: str, *,
                 own_item: str | None, on_own_page: bool) -> tuple[list[dict], list[str]]:
    """A case whose freeze hash fails, read as the file is now (gate r1
    MAJOR 2): ``cases.show`` refuses it, yet that edit is exactly what a
    ``conflict.case-tampered`` page asks the person about, and an ask that
    cites the case must not lose the case and the lesson behind it (gate
    r2 MINOR 1). A plain file read (no git), size-capped and
    secret-scanned like every excerpt; the excerpt is sections 1-4, the
    frozen span the hash covers. Returns the case entry and a fact naming
    the mismatch, and the case's links. On any page but the case's own
    ``conflict.case-tampered`` item (*own_item*, its id when the inbox has
    one), the fact says that item is where the edit is asked about."""
    from . import cases

    now = _case_file_now(home, case_id)
    if now is None:
        return [], []
    path, frontmatter, body, frozen, sections = now
    entry = _case_entry(case_id, sections, frozen if frozen is not None else body, limits, where)
    decided = str(frontmatter.get("decided_sha256") or "")
    now = cases._hash_frozen(frozen) if frozen is not None else None  # noqa: SLF001
    if now is None:
        value = (f"the case file {path} no longer has the shape self-learn wrote (its section "
                 "headings or frontmatter were changed), so its freeze hash cannot be checked; "
                 "the case entry shows the file as it is now")
    else:
        value = (f"sections 1-4 of {path} no longer match the hash taken when the case was "
                 f"decided (decided {decided[:12] or 'missing'}, now {now[:12]}); the case entry "
                 "shows them as they are now, not as they were decided")
    if not on_own_page:
        value += ("; what it says may not be what was decided" + (
            f". Its own inbox item ({own_item}, \"A parked case file was edited by hand after it "
            "was decided\") asks you whether to keep the edit or restore the decided version"
            if own_item else ""))
    fact = {"kind": "fact", "label": "the case file was edited after it was decided",
            "value": limits.clip(value, f"{fact_where}.value", 1200)}
    return [entry, fact], _case_links(frontmatter, sections)


def _report(home: Path, date: str | None, limits: _Limits, where: str) -> dict | None:
    folder = home / "overseer"
    path = folder / f"{date}-report.md" if date else folder / "latest-report.md"
    if not path.is_file():
        path = folder / "latest-report.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    wanted = ("## Decided in the user's stead", "## Hooks", "## User model")
    parts: list[str] = []
    for heading in wanted:
        start = text.find(heading)
        if start < 0:
            continue
        end = text.find("\n## ", start + len(heading))
        parts.append(text[start: end if end > 0 else len(text)].strip())
    return {
        "kind": "report", "date": date or path.stem.split("-report")[0],
        "section": ", ".join(h.lstrip("# ") for h in wanted),
        "excerpt": limits.clip("\n\n".join(parts) or text, f"{where}.excerpt"),
    }


def _display_path(path: str) -> str:
    """Walk fixes, item 6: a path as a person reads it, the home folder
    written ``~``, whole (never cut)."""
    try:
        home = str(Path.home())
    except RuntimeError:
        return path
    if home and home != "/" and (path == home or path.startswith(home.rstrip("/") + "/")):
        return "~" + path[len(home.rstrip("/")):]
    return path


def _file(path: str, limits: _Limits, where: str) -> dict:
    p = Path(path)
    is_dir = p.is_dir()
    if is_dir:
        try:
            names = sorted(child.name + ("/" if child.is_dir() else "") for child in p.iterdir())
        except OSError as exc:
            names = [f"(cannot list: {exc})"]
        shown = [n for n in names if not denied_name(n.rstrip("/"))]
        text = "\n".join(shown[:200])
        truncated = len(shown) > 200
    else:
        try:
            raw = p.read_bytes()[: MAX_TEXT_CHARS * 2]
            text = raw.decode("utf-8", errors="replace")
        except OSError as exc:
            text = f"(cannot read: {exc})"
        truncated = p.stat().st_size > len(text) if p.exists() else False
    excerpt = limits.clip(text, f"{where}.excerpt")
    return {"kind": "file", "path": path, "display": _display_path(path), "is_dir": is_dir,
            "excerpt": excerpt, "truncated": bool(truncated or (excerpt or "").endswith("…"))}


def _hook(home: Path, lesson_id: str, limits: _Limits, where: str) -> dict | None:
    """The hook a lesson compiled to: its script (an excerpt, read from the
    skills root where ``routing.hook.script_path`` points) and its
    registration (the rest of ``routing.hook``)."""
    from . import hosts
    from .ledger_ops import LedgerOpsError, find_record_path
    from .records import Record

    try:
        record = Record.from_path(find_record_path(home, lesson_id))
    except (LedgerOpsError, OSError, ValueError):
        return None
    meta = (record.routing or {}).get("hook") if isinstance(record.routing, dict) else None
    if not isinstance(meta, dict):
        return None
    script: str | None = None
    rel = meta.get("script_path")
    try:
        root = hosts.load_hosts(home).skills_root
    except Exception:  # noqa: BLE001
        root = None
    if isinstance(rel, str) and root is not None:
        path = Path(root).expanduser() / rel
        if path.is_file() and not denied_name(path.name):
            try:
                script = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                script = None
    registration = {k: v for k, v in meta.items() if k not in ("script", "script_path")}
    sections = _sections(record.body)
    return {
        "kind": "hook", "record": lesson_id,
        # Walk fixes, item 6: what the hook is for leads, before its script.
        "trigger": limits.clip(sections.get("Trigger"), f"{where}.trigger", 1000),
        "instruction": limits.clip(sections.get("Instruction"), f"{where}.instruction", 1000),
        "script_excerpt": limits.clip(script if script is not None else meta.get("script"),
                                      f"{where}.script_excerpt"),
        "registration": limits.clip(json.dumps(registration, sort_keys=True, default=str),
                                    f"{where}.registration", 1200),
    }


def _evidence(home: Path, item: dict, limits: _Limits, look_at: list[str],
              tampered: dict[str, str] | None = None) -> list[dict]:
    """Every evidence entry for *item*, before the count cap. *tampered*
    maps a case id to its ``conflict.case-tampered`` item's id."""
    from . import statements as statements_mod

    deadline = time.monotonic() + CONTEXT_BUDGET_SECS
    out: list[dict] = []
    for entry in item.get("_evidence") or []:
        if not isinstance(entry, dict):
            continue
        where = f"evidence[{len(out)}]"
        out.append({
            key: (limits.clip(value, f"{where}.{key}", MAX_CONTEXT_CHARS if key == "context"
                              else MAX_TEXT_CHARS) if isinstance(value, str) else value)
            for key, value in entry.items()
        })
    failed = item.get("_failed")
    if isinstance(failed, dict):
        out.append({"kind": "fact", "label": "the carrying-out agent found",
                    "value": limits.clip(failed.get("note"), "evidence.failed")})
    hold = item.get("_hold")
    if isinstance(hold, dict):
        out.append({"kind": "hold", **{
            k: limits.clip(v, f"evidence.hold.{k}", 1000) if isinstance(v, str) else v
            for k, v in hold.items()
        }})
    grant_use = item.get("_grant_use")
    stmt_rows = {row.get("id"): row for row in statements_mod.list_statements(home)}
    if isinstance(grant_use, dict):
        statement = stmt_rows.get(grant_use.get("statement"))
        out.append({
            "kind": "grant", "id": None, "statement": grant_use.get("statement"),
            "verbatim": limits.clip((statement or {}).get("verbatim"), "evidence.grant.verbatim"),
            "verb": f"self-learn {grant_use.get('verb')} {' '.join(map(str, grant_use.get('args') or []))}".strip(),
        })
    refs_ = [r for r in item.get("refs") or [] if isinstance(r, str)]
    answering = {r for r in refs_ if r.startswith("q-") or r.startswith("conflict:")}
    # Gate r1 MAJOR 1: a case ref is expanded in place into the lessons and
    # statements the case names (its frontmatter `records`, its section-4
    # `statements`), right after it, so an ask shows the lesson it is about
    # and the user's earlier words, not the case alone. Each ref is shown
    # once; the 12-entry cap and `more[]` bound the size.
    queue = list(dict.fromkeys(refs_))
    done: set[str] = set()
    position = 0
    while position < len(queue):
        ref = queue[position]
        position += 1
        if ref in done:
            continue
        done.add(ref)
        where = f"evidence[{len(out)}]"
        linked: list[str] = []
        entries: list[dict | None]
        if ref.startswith("lrn-"):
            entries = [_lesson(home, ref, limits, where)]
        elif ref.startswith("stmt-") and ref in stmt_rows:
            entries = [_statement(home, stmt_rows[ref], limits, where, deadline)]
        elif ref.startswith("case-"):
            entry, linked = _case(home, ref, limits, where)
            entries = [entry]
            if entry is None:
                # Gate r2 MINOR 1: on every page, not only the case's own,
                # a case that fails its freeze check is shown as edited, so
                # an ask citing it keeps the case and the lesson behind it.
                own = (tampered or {}).get(ref)
                edited, linked = _edited_case(
                    home, ref, limits, where, f"evidence[{len(out) + 1}]", own_item=own,
                    on_own_page=item["kind"] == "conflict.case-tampered" and own == item["id"])
                entries = [*edited]
        else:
            entries = []
        out.extend(e for e in entries if e is not None)
        # The case's own links follow it directly; one queued later moves up.
        fresh = [r for r in linked if r not in done]
        queue[position:] = [*fresh, *(r for r in queue[position:] if r not in fresh)]
    for row in stmt_rows.values():
        answers = row.get("answers")
        if row.get("id") in done:
            continue
        if isinstance(answers, dict) and answers.get("ref") in answering:
            done.add(str(row.get("id")))
            out.append(_statement(home, row, limits, f"evidence[{len(out)}]", deadline))
    _mark_conflict_sides(item, out)
    if item["kind"] == "decided.hook-activated" and isinstance(item.get("_lesson"), str):
        hook = _hook(home, item["_lesson"], limits, f"evidence[{len(out)}]")
        if hook is not None:
            # Walk fixes, item 6: the hook leads, and it opens with the
            # lesson's trigger and instruction; the lesson itself is not
            # repeated below the script.
            out[:] = [e for e in out if not (e.get("kind") == "lesson" and e.get("id") == item["_lesson"])]
            out.insert(0, hook)
    if item["kind"] == "decided.overseer-run":
        report = _report(home, (item.get("source") or {}).get("report"), limits, f"evidence[{len(out)}]")
        if report is not None:
            out.append(report)
    for path in look_at:
        out.append(_file(path, limits, f"evidence[{len(out)}]"))
    for fact in item.get("_facts") or []:
        if isinstance(fact, dict):
            value = fact.get("value")
            out.append({"kind": "fact", "label": fact.get("label"),
                        "value": limits.clip(value, "evidence.fact") if isinstance(value, str) else value})
    return out


def _mark_conflict_sides(item: dict, out: list[dict]) -> None:
    """Walk fixes, item 6: on a conflict between two statements, each
    quote says whether it is the newer or the older one (the words the
    options use), by when it was said: the same ``at`` field and ordering
    the answer verb uses when it observes the losing side
    (``attention_answers._conflict_losers``). On equal or unknown times the
    page marks neither, where the verb counts the second-named one as the
    newer (gate r1 F7): the page never claims an order it does not know."""
    raw = item.get("_ask")
    ask: dict = raw if isinstance(raw, dict) else {}
    named = ask.get("statements") if ask.get("because") == "conflict" else None
    if not (isinstance(named, list) and len(named) == 2):
        return
    quoted = {e.get("id"): e for e in out if e.get("kind") == "statement" and e.get("id") in named}
    if len(quoted) != 2:
        return
    first, second = (quoted[named[0]], quoted[named[1]])
    a_at, b_at = str(first.get("at") or ""), str(second.get("at") or "")
    if not a_at or not b_at or a_at == b_at:
        return
    newer, older = (first, second) if a_at > b_at else (second, first)
    newer["side"], older["side"] = "newer", "older"


def _evidence_ref(entry: dict) -> dict:
    return {"kind": entry.get("kind"), "id": entry.get("id") or entry.get("path") or entry.get("label")}


# ------------------------------------------------------------------ the rest


_EFFECT_DOES = {
    "approve": "approves the change; an agent carries it out in a terminal you can see",
    "decline": "nothing is changed; the overseer reads your answer",
    "register": "registers the repository as asked",
    "other": "records your choice; the overseer reads it",
}
_VIA_DOES = {
    "run --login": "opens a terminal running claude; type /login there",
    "check-login": "makes one tiny model call to check the login works again",
    "fix": "restarts self-learn's host service (systemctl --user restart)",
    "refreeze --keep": "keeps your edit: the case's freeze hash is taken from the file as it is",
    "refreeze --restore": "puts back the case as it was decided, from the ledger's history",
    "stop": ("closes the terminal carrying it out, so its session changes nothing more; a step "
             "it is in the middle of stops there and is not undone, and what it already changed "
             "stays changed. Then you can change your answer"),
}


def _does(option: dict) -> str:
    via = option.get("via")
    if isinstance(via, str) and via in _VIA_DOES:
        return _VIA_DOES[via]
    return _EFFECT_DOES.get(str(option.get("effect")), _EFFECT_DOES["other"])


def _clip_fields(rows: object, keys: tuple[str, ...], limits: _Limits, where: str) -> list[dict]:
    """Copies of the dict *rows* with each string under *keys* clipped
    (secret-scanned, at most :data:`MAX_TEXT_CHARS`, each cut named)."""
    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        index = len(out)
        out.append({
            k: (limits.clip(v, f"{where}[{index}].{k}") if k in keys and isinstance(v, str) else v)
            for k, v in row.items()
        })
    return out


def _plan(item: dict, limits: _Limits) -> dict | None:
    """The plan an agent would carry out. Every text in it (summary, each
    check's and step's ``say`` and ``command``, each file's ``content``,
    the conditions) is secret-scanned and capped like an excerpt (gate r1
    MINOR 3): the overseer wrote it, and a file's content may hold a
    secret or be large."""
    plan = item.get("_plan")
    if not isinstance(plan, dict):
        return None
    raw_steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    steps = _clip_fields(raw_steps, ("say", "command"), limits, "plan.steps")
    conditions = item.get("_conditions") or plan.get("conditions")
    return {
        "summary": limits.clip(plan.get("summary"), "plan.summary", 2000)
        if isinstance(plan.get("summary"), str) else plan.get("summary"),
        "cwd": plan.get("cwd"),
        "checks": _clip_fields(plan.get("checks"), ("say", "command"), limits, "plan.checks"),
        "steps": steps,
        "files": _clip_fields(plan.get("files"), ("content",), limits, "plan.files"),
        "sudo": any(s.get("sudo") is True for s in raw_steps),
        "money": item.get("because") == "money" or bool(plan.get("money")),
        "conditions": limits.clip(conditions, "plan.conditions", 2000)
        if isinstance(conditions, str) else conditions,
        # Walk 2 (D5): whose words the conditions are (the approval's
        # record: typed, relayed, draft-accepted, draft-edited, unknown).
        "conditions_how": item.get("_conditions_how") if isinstance(conditions, str) else None,
        "written_at": plan.get("written_at") or item.get("since"),
        "by": plan.get("by") or ("overseer" if item["source"]["by"] == "overseer" else "code"),
    }


def _agent_unavailable(items: list[dict]) -> str | None:
    """``login`` / ``money`` / ``None``: the cheap check (an open hold, the
    billing route), no model call."""
    kinds = {i["kind"] for i in items if i["class"] == "needs-you"}
    if "hold.credentials" in kinds:
        return "login"
    if "hold.money" in kinds or attention._billing_reason():  # noqa: SLF001
        return "money"
    return None


def _why_you(item: dict) -> str | None:
    if item["class"] == "decided":
        return "It was decided for you; look when you like, and undo or overturn it if it is wrong."
    if item["class"] == "approved":
        return "You approved it; it is being carried out."
    because = item.get("because")
    base = attention.KEY_WHY.get(str(because), "You asked to see this kind of item.")
    own = item.get("_why")
    return f"{base} {own}".strip() if isinstance(own, str) and own.strip() else base


def build(home: Path | str, item_id: str, *,
          decided_reader: DecidedReader | None = None) -> dict:
    """The packet of item *item_id* (contract §4.3). Raises
    :class:`UnknownItem` for an id no item has. *decided_reader*
    (``cases.decided_text``, passed by the ``attention packet`` and ``ask``
    verbs) fills ``case_edit.decided`` on a ``conflict.case-tampered`` item;
    this function itself never runs git (follow-ups 2, gap 1)."""
    home = Path(home)
    items = attention.collect(home, all_items=True)
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        raise UnknownItem(item_id)
    limits = _Limits()
    look_at, dropped = filter_look_at(home, list(item.get("_look_at") or []))
    limits.truncated.extend(f"look_at: {d}" for d in dropped)
    tampered = {str(i.get("subject")): str(i["id"]) for i in items
                if i.get("kind") == "conflict.case-tampered"}
    evidence = _evidence(home, item, limits, look_at, tampered)
    more: list[dict] = []
    if len(evidence) > MAX_EVIDENCE:
        more = [_evidence_ref(e) for e in evidence[MAX_EVIDENCE:]]
        limits.truncated.append(f"evidence: {len(evidence) - MAX_EVIDENCE} more entries in more[]")
        evidence = evidence[:MAX_EVIDENCE]
    options = [
        {k: v for k, v in {**o, "does": _does(o)}.items()} for o in item.get("options") or []
    ]
    recommend = item.get("_recommend") if isinstance(item.get("_recommend"), dict) else None
    recommended = next((o for o in options if o.get("recommended")), None)
    rec_option = (recommend or {}).get("option") or (recommended or {}).get("id")
    rec_label = next((o.get("label") for o in options if o.get("id") == rec_option), None)
    recommendation = (
        {"option": rec_option, "text": rec_label,
         "reasoning": limits.clip((recommend or {}).get("reasoning"), "recommendation.reasoning")}
        if rec_option else None
    )
    alternatives = [
        {"option": o.get("id"), "does": o.get("does")} for o in options if o.get("id") != rec_option
    ]
    decided = item.get("_decided")
    undo = item.get("undo")
    conversation: dict[str, Any] = dict(item.get("conversation") or {"turns": 0, "last_at": None})
    unavailable = _agent_unavailable(items)
    conversation["agent_available"] = unavailable is None
    conversation["agent_unavailable"] = unavailable
    packet: dict[str, Any] = {
        "packet_version": PACKET_VERSION,
        "generated_at": chrono.now_iso(),
        "item": attention.public(item),
        "question": limits.clip(item.get("_question") or item.get("title"), "question", 2000),
        "why_you": limits.clip(_why_you(item), "why_you", 2000),
        "meanwhile": limits.clip(item.get("meanwhile"), "meanwhile", 2000),
        "recommendation": recommendation,
        "options": options,
        "alternatives": alternatives,
        "plan": _plan(item, limits),
        "decided": (
            {k: (limits.clip(v, f"decided.{k}", 2000) if isinstance(v, str) else v)
             for k, v in decided.items()} if isinstance(decided, dict) else None
        ),
        "undo": {"label": undo.get("label"), "redo_label": undo.get("redo_label")} if isinstance(undo, dict) else None,
        "case_edit": _case_edit(home, item, limits, decided_reader),
        "run": _run_decisions(home, item, limits),
        "evidence": evidence,
        "more": more,
        "pointers": _pointers(home, item),
        "look_at": look_at,
        "conversation": conversation,
        "answer": item.get("answer"),
        "limits": {"bytes": 0, "truncated": limits.truncated},
    }
    return _fit(packet)


#: Humane UI lane 3: the most the ``run`` block of a nightly review may take
#: of the packet (gate r1 MAJOR 3). Its rows carry a title and a short
#: reason only; the page opens a case's full text on request, so the block
#: never crowds the evidence out of :data:`MAX_BYTES`.
MAX_RUN_BYTES = 12 * 1024
#: The longest title and reason a decision row carries, before the budget.
MAX_RUN_TITLE_CHARS = 160
MAX_RUN_REASON_CHARS = 200
#: ...and the shortest opening a reason settles for (see :func:`_first_sentence`).
MIN_REASON_CHARS = 60
#: A case whose apply did not happen (the run record's ``phase``): its
#: outcome is the steward's intent, never an effect (gate r1 MAJOR 1).
#: ``unfinished`` is the steward's own phase for a case it will drive again;
#: ``failed`` and ``stopped`` are taken as said, should a run ever write them.
NOT_CARRIED_OUT_PHASES = frozenset({"refused", "unfinished", "failed", "stopped"})
#: Why a decision was not carried out, as the row's ``not_done`` says it.
NOT_DONE_REASONS = ("refused", "unfinished", "failed", "stopped", "not-attempted")
#: The group a decision not carried out is counted in.
REFUSED_GROUP = "refused"

_PAREN_REF_RE = re.compile(
    r"\s*\((?=[^()]*\b(?:L\d{2,}|(?:case|lrn|stmt|um|op|q|grant|obs)-[0-9a-z]))[^()]*\)")
_BARE_REF_WORDS = (
    (re.compile(r"\bcase-[0-9a-f]{6,}\b"), "an earlier case"),
    (re.compile(r"\blrn-[0-9a-f]{6,}\b"), "a lesson"),
    (re.compile(r"\bstmt-[0-9a-f]{6,}\b"), "your statement"),
    (re.compile(r"\s*\bum-[0-9a-z]{3,}(?:@r\d+)?"), ""),
)
_LINE_REF_RE = re.compile(r"\s*\b(?:at |on |in )?L\d{2,}(?:-L?\d+)?\b")


def plain_reason(text: str | None) -> str | None:
    """*text* without its ids and transcript line references (gate r1 NIT 8):
    a parenthesis that holds one goes; a bare id reads as words ("an earlier
    case", "your statement"), a reading's id goes; "at L20505" goes. The
    case file keeps them."""
    if not text:
        return text
    out = _PAREN_REF_RE.sub("", text)
    for pattern, words in _BARE_REF_WORDS:
        out = pattern.sub(words, out)
    out = _LINE_REF_RE.sub("", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    out = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", out)
    return " ".join(out.split())


_plain_reason = plain_reason


def _first_sentence(text: str | None) -> str | None:
    """The opening of *text*: its first sentence, and the next ones while
    that is still shorter than :data:`MIN_REASON_CHARS` (a first sentence
    such as "Evidence check." says nothing alone); the whole of it when it
    has no sentence end."""
    if not text:
        return None
    flat = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+", flat)
    out = ""
    for part in parts:
        out = f"{out} {part}".strip()
        if len(out) >= MIN_REASON_CHARS:
            break
    return out


def _clip_plain(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _not_done(entry: object) -> str | None:
    """Why the run record says a case's apply did not happen, or ``None``
    when it did (gate r2 NIT E): its ``phase`` (one of
    :data:`NOT_CARRIED_OUT_PHASES`), or a result that applied nothing (and
    found nothing already applied) while it refused, stopped or never
    attempted something (``refused``, ``stopped``, ``not-attempted``)."""
    if not isinstance(entry, dict):
        return None
    phase = entry.get("phase")
    if phase in NOT_CARRIED_OUT_PHASES:
        return str(phase)
    result = entry.get("result")
    summary = result.get("summary") if isinstance(result, dict) else None
    if (isinstance(summary, dict) and summary.get("applied") == 0
            and not summary.get("already_applied")):
        for key, why in (("refused", "refused"), ("stopped", "stopped"),
                         ("not_attempted", "not-attempted")):
            count = summary.get(key)
            if isinstance(count, int) and count > 0:
                return why
    return None


def _carried_out(entry: object) -> bool:
    """Whether the run record says a case's apply happened."""
    return _not_done(entry) is None


def _fit_run(rows: list[dict]) -> dict[str, int]:
    """Shorten the rows in place until they take at most
    :data:`MAX_RUN_BYTES`: reasons to 120 characters, then titles to 100,
    then reasons to 60, then titles to 60, then no reasons. If that is still
    too much (a run of very many cases), drop rows -- always the last row of
    the group with the most rows (a tie spares the decisions not carried
    out), and never a group's last row, so every group keeps a line (gate r2
    MINOR B). Returns how many rows of each group were dropped; the counts
    still cover them."""
    def size() -> int:
        return len(json.dumps(rows, ensure_ascii=False).encode("utf-8"))

    dropped: dict[str, int] = {}
    for key, limit in (("reason", 120), ("title", 100), ("reason", 60), ("title", 60), ("reason", 0)):
        if size() <= MAX_RUN_BYTES:
            return dropped
        for row in rows:
            row[key] = None if limit == 0 else _clip_plain(row.get(key), limit)
    while rows and size() > MAX_RUN_BYTES:
        sizes: dict[str, int] = {}
        for row in rows:
            sizes[str(row.get("group"))] = sizes.get(str(row.get("group")), 0) + 1
        group = max(sizes, key=lambda g: (sizes[g], g != REFUSED_GROUP))
        if sizes[group] <= 1:
            break  # one line per group stays, whatever the budget
        index = max(i for i, row in enumerate(rows) if str(row.get("group")) == group)
        rows.pop(index)
        dropped[group] = dropped.get(group, 0) + 1
    return dropped


def _run_decisions(home: Path, item: dict, limits: _Limits) -> dict | None:
    """Humane UI lane 3 (proposal §4, contract §6; gate r1): a nightly
    review's decisions, one row per case the run wrote (its manifest's
    ``cases``; the item's title counts the same cases, so the two always
    agree), each with the lesson it is about, its outcome verb and that
    verb's group (:data:`self_learn.series.OUTCOME_GROUPS`), and the opening
    of its reason in plain words; plus the count per group. A case the run
    record says was not carried out (:func:`_not_done`) is counted under
    :data:`REFUSED_GROUP`, never under the group of what it meant to do, and
    its row says why (``not_done``). Rows not carried out come first; when
    the block is too big, :func:`_fit_run` drops rows from the largest group
    and ``omitted_groups`` says how many of each group are not listed.
    Read from the run's manifest and its committed case files; counted,
    never modelled; at most :data:`MAX_RUN_BYTES`. ``None`` for any other
    item."""
    if item.get("kind") != "decided.steward-run":
        return None
    from . import cases
    from .series import OUTCOME_GROUPS

    group_of = {verb: group for group, verbs in OUTCOME_GROUPS.items() for verb in verbs}
    counts = {g: 0 for g in OUTCOME_GROUPS}
    counts[REFUSED_GROUP] = 0
    manifest_path = item.get("_manifest_path")
    try:
        manifest = json.loads(Path(str(manifest_path)).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"decisions": [], "counts": counts, "other": 0, "omitted": 0, "omitted_groups": {},
                "error": "the run's record could not be read"}
    recipes = manifest.get("cases") if isinstance(manifest, dict) else None
    recipes = recipes if isinstance(recipes, dict) else {}
    case_ids = [c for c in recipes if isinstance(c, str) and c.startswith("case-")]
    other = 0
    rows: list[dict] = []
    for case_id in case_ids:
        try:
            text = cases._case_path_for_id(home, case_id).read_text(encoding="utf-8")  # noqa: SLF001
            frontmatter, body = cases._split_frontmatter(text)  # noqa: SLF001
        except Exception:  # noqa: BLE001 -- a missing case is a row without words
            frontmatter, body = {}, ""
        decision = _sections(body).get("Decision")
        verb = frontmatter.get("outcome") if isinstance(frontmatter.get("outcome"), str) else None
        verb = verb or _line_value(decision, "verb")
        not_done = _not_done(recipes.get(case_id))
        carried = not_done is None
        group = group_of.get(verb or "") if carried else REFUSED_GROUP
        if group is None:
            other += 1
        else:
            counts[group] += 1
        records = [str(r) for r in frontmatter.get("records") or [] if isinstance(r, str)]
        title = None
        if records:
            lesson = _lesson(home, records[0], _Limits(), "run")
            title = (lesson or {}).get("title")
        reason = _first_sentence(_plain_reason(_line_value(decision, "because")))
        rows.append({
            "case": case_id,
            "record": records[0] if records else None,
            "records": len(records),
            "title": _clip_plain(redact_text(title) if title else None, MAX_RUN_TITLE_CHARS),
            "verb": verb,
            "group": group,
            "carried_out": carried,
            "not_done": not_done,
            "reason": _clip_plain(redact_text(reason) if reason else None, MAX_RUN_REASON_CHARS),
        })
    # Gate r2 MINOR B: what was not carried out comes first, where a person
    # sees it without opening "Show all".
    order = {g: i for i, g in enumerate([REFUSED_GROUP, *OUTCOME_GROUPS])}
    rows.sort(key=lambda r: (order.get(str(r["group"]), len(order)), str(r["case"])))
    dropped = _fit_run(rows)
    return {"decisions": rows, "counts": counts, "other": other,
            "omitted": sum(dropped.values()), "omitted_groups": dropped, "error": None}


def _pointers(home: Path, item: dict) -> list[dict]:
    out: list[dict] = [{"label": "the case files", "path": str(home / "cases")}]
    out.append({"label": "a lesson's or case's history", "tool": "ledger_history"})
    if item["kind"].startswith("hold.") or item["kind"].startswith("broken."):
        cache = attention.cache_dir(home)
        out += [
            {"label": "the steward's journal", "path": str(cache / "steward" / "journal.jsonl")},
            {"label": "the overseer's journal", "path": str(cache / "overseer.journal")},
            {"label": "the host's heartbeat", "path": str(cache / "serve.heartbeat")},
        ]
    if item["kind"] == "decided.overseer-run":
        out.append({"label": "the weekly report", "path": str(home / "overseer" / "latest-report.md")})
    if item["kind"] == "conflict.case-tampered":
        from . import cases

        try:
            path = cases._case_path_for_id(home, str(item.get("subject")))  # noqa: SLF001
        except Exception:  # noqa: BLE001
            path = None
        if path is not None:
            rel = path.relative_to(home) if path.is_relative_to(home) else path
            # Gate r2 MINOR 2: `ledger_history` gives the commits' subjects
            # and trailers, never file text or a diff (design §3.3), so the
            # label promises only that.
            out.append({
                "label": f"the commits that touched {rel}: who changed it and when (subjects "
                         "and trailers only, not the text; an edit not yet committed shows in "
                         "no commit)",
                "tool": "ledger_history", "path": str(path),
            })
            # Follow-ups 2 (gap 1): the text itself, as decided, is the
            # `case` tool's (and this packet's `case_edit`).
            out.append({
                "label": "what the case said when it was decided, beside the file as it is now",
                "tool": "case",
            })
    return out


def _size(packet: dict) -> int:
    return len(json.dumps(packet, ensure_ascii=False).encode("utf-8"))


def _cut_candidates(packet: dict) -> list[tuple[dict, str, str]]:
    """Every text :func:`_fit` may halve: ``(container, key, where)`` for the
    evidence texts and the plan's step, check and file texts."""
    fields = ("text", "excerpt", "context", "verbatim", "script_excerpt")
    out: list[tuple[dict, str, str]] = [
        (entry, name, f"evidence[{index}].{name}")
        for index, entry in enumerate(packet["evidence"]) for name in fields
    ]
    plan = packet.get("plan")
    if isinstance(plan, dict):
        for group, keys in (("files", ("content",)), ("steps", ("command", "say")),
                            ("checks", ("command", "say"))):
            for index, row in enumerate(plan.get(group) or []):
                if isinstance(row, dict):
                    out += [(row, key, f"plan.{group}[{index}].{key}") for key in keys]
    edit = packet.get("case_edit")
    if isinstance(edit, dict):
        out.append((edit, "now", "case_edit.now"))
        if isinstance(edit.get("decided"), dict):
            out.append((edit["decided"], "text", "case_edit.decided.text"))
        for index, change in enumerate(edit.get("changes") or []):
            if isinstance(change, dict):
                out += [(change, key, f"case_edit.changes[{index}].{key}") for key in ("was", "now")]
    return out


def _fit(packet: dict) -> dict:
    """Cut the largest evidence and plan texts until the whole JSON is at
    most :data:`MAX_BYTES`, naming each cut; then fill ``limits.bytes``."""
    truncated: list[str] = packet["limits"]["truncated"]
    guard = 0
    while _size(packet) > MAX_BYTES and guard < 400:
        guard += 1
        best: tuple[int, dict, str, str] | None = None
        for container, name, where in _cut_candidates(packet):
            value = container.get(name)
            if isinstance(value, str) and (best is None or len(value) > best[0]):
                best = (len(value), container, name, where)
        if best is None or best[0] <= 200:
            if packet["evidence"]:
                dropped = packet["evidence"].pop()
                packet["more"].append(_evidence_ref(dropped))
                truncated.append(f"evidence[{len(packet['evidence'])}] moved to more[] (size)")
                continue
            break
        length, container, name, where = best
        container[name] = container[name][: max(200, length // 2)].rstrip() + "…"
        if where not in truncated:
            truncated.append(where)
    # Twice: the count's own digits change the size it counts.
    packet["limits"]["bytes"] = _size(packet)
    packet["limits"]["bytes"] = _size(packet)
    return packet


def render_md(packet: dict) -> str:
    """The packet as markdown (``packet.md`` in the ask agent's working
    directory): plain sections, the evidence in full."""
    item = packet.get("item") or {}
    lines = [f"# {item.get('title')}", "", f"Item: {item.get('id')} ({item.get('kind')}, "
             f"{item.get('class')})", ""]
    for key, label in (("question", "Question"), ("why_you", "Why it needs you"),
                       ("meanwhile", "Meanwhile")):
        if packet.get(key):
            lines += [f"## {label}", str(packet[key]), ""]
    if packet.get("recommendation"):
        rec = packet["recommendation"]
        lines += ["## Recommendation", f"{rec.get('text')} ({rec.get('option')})",
                  str(rec.get("reasoning") or ""), ""]
    if packet.get("options"):
        lines.append("## Options")
        lines += [f"- {o.get('id')}: {o.get('label')} — {o.get('does')}" for o in packet["options"]]
        lines.append("")
    if packet.get("plan"):
        lines += ["## Plan", "```json", json.dumps(packet["plan"], indent=2, ensure_ascii=False), "```", ""]
    if packet.get("decided"):
        lines += ["## Decided", "```json", json.dumps(packet["decided"], indent=2, ensure_ascii=False), "```", ""]
    edit = packet.get("case_edit")
    if isinstance(edit, dict):
        lines += [f"## The hand edit of {edit.get('case')}", ""]
        decided = edit.get("decided")
        if isinstance(decided, dict):
            lines += [f"### Sections 1-4 as decided (commit {decided.get('commit')}, "
                      f"{decided.get('committed_at')})", str(decided.get("text") or ""), ""]
        else:
            lines += [f"The decided text is not shown: {edit.get('note')}.", ""]
        lines += ["### Sections 1-4 as the file says now", str(edit.get("now") or ""), ""]
        for change in edit.get("changes") or []:
            lines += ["### A passage that differs", "Was decided:", str(change.get("was") or "(nothing)"),
                      "The file says now:", str(change.get("now") or "(nothing)"), ""]
    lines.append("## Evidence")
    for entry in packet.get("evidence") or []:
        lines += ["", f"### {entry.get('kind')} {entry.get('id') or entry.get('path') or entry.get('label') or ''}".rstrip()]
        for key, value in entry.items():
            if key in ("kind", "id"):
                continue
            if isinstance(value, str) and "\n" in value:
                lines += [f"{key}:", value]
            else:
                lines.append(f"{key}: {json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value}")
    if packet.get("more"):
        lines += ["", "## More (open with your tools)"]
        lines += [f"- {m.get('kind')} {m.get('id')}" for m in packet["more"]]
    if packet.get("pointers"):
        lines += ["", "## Where to look further"]
        lines += [f"- {p.get('label')}: {p.get('path') or p.get('tool')}" for p in packet["pointers"]]
    return "\n".join(lines) + "\n"
