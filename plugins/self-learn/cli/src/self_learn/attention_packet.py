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
call, writes nothing to the ledger, and never runs git.

**One deny list** (:data:`SECRET_DENY`) serves this packet's ``look_at``
filter and the ask agent's read fence; the ask lane imports it and never
copies it.
"""

from __future__ import annotations

import fnmatch
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    "DenyList",
    "UnknownItem",
    "build",
    "deny_paths",
    "denied_name",
    "filter_look_at",
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
    """*text* with every secret-scan hit replaced by ``[redacted: <rule>]``."""
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


def _lesson(home: Path, lesson_id: str, limits: _Limits, where: str) -> dict | None:
    from .ledger_ops import LedgerOpsError, find_record_path
    from .records import Record

    try:
        record = Record.from_path(find_record_path(home, lesson_id))
    except (LedgerOpsError, OSError, ValueError):
        return None
    body = record.body
    title = next((ln.lstrip("# ").strip() for ln in body.splitlines() if ln.strip()), lesson_id)
    routing = record.routing or {}
    return {
        "kind": "lesson", "id": lesson_id, "title": limits.clip(title, f"{where}.title", 300),
        "text": limits.clip(body, f"{where}.text"), "status": record.status,
        "placement": routing.get("destination") if isinstance(routing, dict) else None,
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
        return None, f"not read ({type(exc).__name__})"
    if text is None:
        return None, "the ref did not resolve"
    return limits.clip(text, f"{where}.context", MAX_CONTEXT_CHARS), None


def _statement(home: Path, row: dict, limits: _Limits, where: str, deadline: float) -> dict:
    ref = str((row.get("source") or {}).get("message_ref") or "")
    context, note = _context(home, ref, limits, where, deadline)
    return {
        "kind": "statement", "id": row.get("id"), "at": row.get("at"),
        "verbatim": limits.clip(row.get("verbatim"), f"{where}.verbatim"),
        "answers": row.get("answers"), "ref": ref or None, "context": context,
        "context_note": note,
    }


def _case(home: Path, case_id: str, limits: _Limits, where: str) -> dict | None:
    from . import cases

    try:
        view = cases.show(home, case_id, evidence_only=False)
    except Exception:  # noqa: BLE001 -- a missing or tampered case is no entry
        return None
    sections = view.sections
    decision = next((v for k, v in sections.items() if "decision" in k.lower()), None)
    because = next((v for k, v in sections.items() if "reason" in k.lower() or "why" in k.lower()), None)
    question = next(iter(sections.values()), None)
    body = "\n\n".join(f"## {k}\n{v}" for k, v in sections.items())
    return {
        "kind": "case", "id": case_id,
        "question": limits.clip(question, f"{where}.question", 600),
        "decision": limits.clip(decision, f"{where}.decision", 1200),
        "because": limits.clip(because, f"{where}.because", 1200),
        "excerpt": limits.clip(body, f"{where}.excerpt"),
    }


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


def _file(path: str, limits: _Limits, where: str) -> dict:
    p = Path(path)
    if p.is_dir():
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
    return {"kind": "file", "path": path, "excerpt": excerpt,
            "truncated": bool(truncated or (excerpt or "").endswith("…"))}


def _evidence(home: Path, item: dict, limits: _Limits, look_at: list[str]) -> list[dict]:
    """Every evidence entry for *item*, before the count cap."""
    from . import statements as statements_mod

    deadline = time.monotonic() + CONTEXT_BUDGET_SECS
    out: list[dict] = []
    seeded = item.get("_evidence") or []
    out.extend(e for e in seeded if isinstance(e, dict))
    failed = item.get("_failed")
    if isinstance(failed, dict):
        out.append({"kind": "fact", "label": "the carrying-out agent found",
                    "value": limits.clip(failed.get("note"), "evidence.failed")})
    hold = item.get("_hold")
    if isinstance(hold, dict):
        out.append({"kind": "hold", **hold})
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
    for ref in refs_:
        where = f"evidence[{len(out)}]"
        if ref.startswith("lrn-"):
            entry = _lesson(home, ref, limits, where)
        elif ref.startswith("stmt-") and ref in stmt_rows:
            entry = _statement(home, stmt_rows[ref], limits, where, deadline)
        elif ref.startswith("case-"):
            entry = _case(home, ref, limits, where)
        else:
            entry = None
        if entry is not None:
            out.append(entry)
    for row in stmt_rows.values():
        answers = row.get("answers")
        if isinstance(answers, dict) and answers.get("ref") in answering:
            out.append(_statement(home, row, limits, f"evidence[{len(out)}]", deadline))
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
}


def _does(option: dict) -> str:
    via = option.get("via")
    if isinstance(via, str) and via in _VIA_DOES:
        return _VIA_DOES[via]
    return _EFFECT_DOES.get(str(option.get("effect")), _EFFECT_DOES["other"])


def _plan(item: dict) -> dict | None:
    plan = item.get("_plan")
    if not isinstance(plan, dict):
        return None
    steps = [dict(s) for s in plan.get("steps") or [] if isinstance(s, dict)]
    return {
        "summary": plan.get("summary"), "cwd": plan.get("cwd"),
        "checks": [dict(c) for c in plan.get("checks") or [] if isinstance(c, dict)],
        "steps": steps, "files": [dict(f) for f in plan.get("files") or [] if isinstance(f, dict)],
        "sudo": any(s.get("sudo") is True for s in steps),
        "money": item.get("because") == "money" or bool(plan.get("money")),
        "conditions": item.get("_conditions") or plan.get("conditions"),
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


def build(home: Path | str, item_id: str) -> dict:
    """The packet of item *item_id* (contract §4.3). Raises
    :class:`UnknownItem` for an id no item has."""
    home = Path(home)
    items = attention.collect(home, all_items=True)
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        raise UnknownItem(item_id)
    limits = _Limits()
    look_at, dropped = filter_look_at(home, list(item.get("_look_at") or []))
    limits.truncated.extend(f"look_at: {d}" for d in dropped)
    evidence = _evidence(home, item, limits, look_at)
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
        "plan": _plan(item),
        "decided": (
            {k: (limits.clip(v, f"decided.{k}", 2000) if isinstance(v, str) else v)
             for k, v in decided.items()} if isinstance(decided, dict) else None
        ),
        "undo": {"label": undo.get("label"), "redo_label": undo.get("redo_label")} if isinstance(undo, dict) else None,
        "evidence": evidence,
        "more": more,
        "pointers": _pointers(home, item),
        "look_at": look_at,
        "conversation": conversation,
        "answer": item.get("answer"),
        "limits": {"bytes": 0, "truncated": limits.truncated},
    }
    return _fit(packet)


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
    return out


def _size(packet: dict) -> int:
    return len(json.dumps(packet, ensure_ascii=False).encode("utf-8"))


def _fit(packet: dict) -> dict:
    """Cut the largest evidence texts until the whole JSON is at most
    :data:`MAX_BYTES`, naming each cut; then fill ``limits.bytes``."""
    truncated: list[str] = packet["limits"]["truncated"]
    fields = ("text", "excerpt", "context", "verbatim", "script_excerpt")
    guard = 0
    while _size(packet) > MAX_BYTES and guard < 200:
        guard += 1
        best: tuple[int, int, str] | None = None
        for index, entry in enumerate(packet["evidence"]):
            for name in fields:
                value = entry.get(name)
                if isinstance(value, str) and (best is None or len(value) > best[0]):
                    best = (len(value), index, name)
        if best is None or best[0] <= 200:
            if packet["evidence"]:
                dropped = packet["evidence"].pop()
                packet["more"].append(_evidence_ref(dropped))
                truncated.append(f"evidence[{len(packet['evidence'])}] moved to more[] (size)")
                continue
            break
        length, index, name = best
        entry = packet["evidence"][index]
        entry[name] = entry[name][: max(200, length // 2)].rstrip() + "…"
        where = f"evidence[{index}].{name}"
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
