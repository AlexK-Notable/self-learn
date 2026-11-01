"""The workspace transcript of one inbox item (attention round, design r2
§3.4.2; contract §4.4).

``<ledger>/attention/workspace/<item-id>.jsonl``: append-only JSON Lines,
committed. Row 0 is a header; every later row is one exchange on the item's
decision workspace page: the person's typed question or reply, a clicked
option, the ask agent's answer or draft, a system note. Each row carries
``t``, its number, allocated under the ledger lock.

    {"t":0,"kind":"header","item":"att-…","item_kind":"…","subject":"…","title":"…","at":"…"}
    {"t":1,"at":"…","role":"user","origin":"typed","kind":"question","text":"…"}
    {"t":2,"at":"…","role":"agent","origin":"agent","kind":"answer","text":"…", …}

The one writer is :func:`append`. It takes :func:`intents.ledger_write`,
numbers the rows under the lock, secret-scans each (a hit replaces the text
by ``null`` and names the rule in ``redacted``), and commits. When the
ledger is STOPPED (``LedgerStoppedError``), it keeps the rows in
``<cache>/workspace/<item-id>/pending.jsonl`` with ``"t": null`` instead;
the next append that gets the lock seals them first, in order, and removes
the file. A pending row cannot be cited (it has no ``t``).

The ref kind is ``workspace:<item-id>#T<n>`` (:data:`REF_RE`). A statement
may cite a row only when it is the person's typing (``role: user``,
``origin: typed``; rule 11 of 02-schema §3a.6), checked by
``statements._check_evidence`` through :func:`resolve`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import gitops, intents
from .primitives import chrono, fsops
from .scan import scan as secret_scan

__all__ = [
    "ITEM_ID_RE",
    "REF_RE",
    "append",
    "excerpt",
    "pending_path",
    "redact",
    "resolve",
    "rows",
    "secret_rule",
    "transcript_path",
]

ITEM_ID_RE = re.compile(r"^att-[0-9a-f]{12}$")
REF_RE = re.compile(r"^workspace:(att-[0-9a-f]{12})#T(\d+)$")
#: The text-bearing fields of a row that are secret-scanned.
_TEXT_FIELDS = ("text", "draft_text")


class WorkspaceError(ValueError):
    """A malformed item id or row; nothing written."""


def transcript_path(home: Path | str, item_id: str) -> Path:
    return Path(home) / "attention" / "workspace" / f"{item_id}.jsonl"


def _cache_dir(home: Path | str) -> Path:
    from . import serve  # lazy: serve imports most of the package

    return serve.cache_dir_readonly(Path(home))


def pending_path(home: Path | str, item_id: str) -> Path:
    return _cache_dir(home) / "workspace" / item_id / "pending.jsonl"


def _check_id(item_id: str) -> str:
    if not isinstance(item_id, str) or ITEM_ID_RE.fullmatch(item_id) is None:
        raise WorkspaceError(f"workspace: malformed item id {item_id!r}")
    return item_id


def secret_rule(text: str | None) -> str | None:
    """The first secret-scan rule *text* trips, or ``None``. A caller that
    must refuse a person's message before any model call or write (the ask
    verb) asks this first."""
    if not text:
        return None
    hits = secret_scan(text)
    return hits[0].rule if hits else None


def redact(row: dict) -> dict:
    """*row* with every text field that trips the secret scan replaced by
    ``null`` and the rule named in ``redacted``."""
    out = dict(row)
    for field in _TEXT_FIELDS:
        rule = secret_rule(out.get(field)) if isinstance(out.get(field), str) else None
        if rule is not None:
            out[field] = None
            out["redacted"] = rule
    return out


def _read_jsonl(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _keep_pending(home: Path, item_id: str, rows_: list[dict]) -> None:
    """Rows sealed while the ledger is STOPPED: appended to the item's
    ``pending.jsonl`` under the XDG cache, ``"t": null``. Never a repo's
    truth (the lock invariant's ``NOT_REPO_TRUTH``); :func:`append` moves
    them into the ledger once it can take the lock."""
    target = pending_path(home, item_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    prior = target.read_text(encoding="utf-8") if target.exists() else ""
    lines = "".join(json.dumps({**row, "t": None}, sort_keys=True) + "\n" for row in rows_)
    fsops.atomic_write(target, prior + lines, fsync=False)


def append(
    home: Path | str, item_id: str, rows_: list[dict], *, header: dict | None = None
) -> list[int]:
    """Seal *rows_* into item *item_id*'s workspace transcript and commit;
    return their ``t`` numbers. Each row gets ``at`` when it has none.

    *header* (``item_kind``, ``subject``, ``title``) is written as row 0
    when the transcript does not exist yet. Rows kept earlier while the
    ledger was STOPPED are sealed first, in their order. Under a STOPPED
    ledger the rows go to the pending file and ``[]`` is returned."""
    home = Path(home)
    _check_id(item_id)
    now = chrono.now_iso()
    fresh = [redact({"at": now, **row}) for row in rows_]
    for row in fresh:
        if row.get("kind") == "header":
            raise WorkspaceError("workspace: a header row is written by append itself")
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            target = transcript_path(home, item_id)
            existing = _read_jsonl(target)
            pending_file = pending_path(home, item_id)
            pending = _read_jsonl(pending_file)
            out_rows: list[dict] = []
            next_t = max((int(r["t"]) for r in existing if isinstance(r.get("t"), int)), default=-1) + 1
            if not existing:
                out_rows.append({
                    "t": 0, "kind": "header", "item": item_id,
                    "item_kind": (header or {}).get("item_kind"),
                    "subject": (header or {}).get("subject"),
                    "title": (header or {}).get("title"),
                    "at": now,
                })
                next_t = 1
            for row in pending:
                out_rows.append({**{k: v for k, v in row.items() if k != "t"}, "t": next_t})
                next_t += 1
            sealed: list[int] = []
            for row in fresh:
                out_rows.append({**{k: v for k, v in row.items() if k != "t"}, "t": next_t})
                sealed.append(next_t)
                next_t += 1
            prior = target.read_text(encoding="utf-8") if target.exists() else ""
            if prior and not prior.endswith("\n"):
                prior += "\n"
            body = "".join(json.dumps(row, sort_keys=True) + "\n" for row in out_rows)
            target.parent.mkdir(parents=True, exist_ok=True)
            fsops.atomic_write(target, prior + body, fsync=True)
            first, last = out_rows[0]["t"], out_rows[-1]["t"]
            gitops.stage_and_commit(
                home, [target],
                f"self-learn: workspace {item_id} T{first}" + (f"-T{last}" if last != first else ""),
                None,
            )
            if pending:
                pending_file.unlink(missing_ok=True)
            return sealed
    except intents.LedgerStoppedError:
        _keep_pending(home, item_id, fresh)
        return []


def rows(home: Path | str, item_id: str, *, pending: bool = True) -> list[dict]:
    """The item's sealed rows in order, then (with *pending*) the rows kept
    on this machine while the ledger was STOPPED (``"t": null``)."""
    _check_id(item_id)
    out = _read_jsonl(transcript_path(home, item_id))
    if pending:
        out += [{**row, "t": None} for row in _read_jsonl(pending_path(home, item_id))]
    return out


def _parse_ref(ref: str) -> tuple[str, int] | None:
    match = REF_RE.fullmatch(ref or "")
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def resolve(home: Path | str, ref: str) -> dict | None:
    """The SEALED row ``workspace:<item-id>#T<n>`` names, or ``None`` when
    the ref is malformed or no sealed row has that number (a pending row
    has none, so it never resolves)."""
    parsed = _parse_ref(ref)
    if parsed is None:
        return None
    item_id, number = parsed
    for row in _read_jsonl(transcript_path(home, item_id)):
        if row.get("t") == number:
            return row
    return None


_ROLE_LABELS = {"user": "you", "agent": "agent", "system": "self-learn"}


def _line(row: dict) -> str:
    who = _ROLE_LABELS.get(str(row.get("role")), str(row.get("role")))
    kind = row.get("kind") or ""
    text: Any = row.get("text")
    if text is None and row.get("redacted"):
        text = f"[redacted: {row['redacted']}]"
    if text is None and row.get("option"):
        text = f"(chose {row['option']})"
    return f"T{row.get('t')} {who} ({row.get('origin')}, {kind}): {text if text is not None else ''}"


def excerpt(home: Path | str, ref: str, before: int = 3, after: int = 3) -> str | None:
    """The rows around the row *ref* names, roles labelled, one per line
    (the workspace sibling of ``refs.excerpt``); ``None`` when *ref* does
    not resolve. The header row is never shown."""
    parsed = _parse_ref(ref)
    if parsed is None:
        return None
    item_id, number = parsed
    sealed = [r for r in _read_jsonl(transcript_path(home, item_id)) if r.get("kind") != "header"]
    index = next((i for i, row in enumerate(sealed) if row.get("t") == number), None)
    if index is None:
        return None
    window = sealed[max(0, index - before): index + after + 1]
    return "\n".join(_line(row) for row in window)
