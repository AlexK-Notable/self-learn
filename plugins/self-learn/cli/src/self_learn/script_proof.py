"""S-160 observed review transcript corroboration, not local-forger resistance.

The SDK records init and every assistant message, including tool use. The caller
stores those observations while holding the ledger lock, independent of cache
retention. Neither a model-request flag nor an index-only stamp is evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MODEL = "claude-fable-5-2"


def verdict(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4].strip()
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("verdict") not in {"approve", "reject"}:
        raise ValueError("invalid review verdict")
    if set(data) != {"verdict", "reasons", "changes", "version"}:
        raise ValueError("unexpected review fields; session metadata is backend-owned")
    for name in ("reasons", "changes"):
        if not isinstance(data.get(name), list) or any(not isinstance(x, str) or not x.strip() for x in data[name]):
            raise ValueError("invalid review " + name)
    if not data["reasons"] or data["verdict"] == "reject" and not data["changes"]:
        raise ValueError("review reasons/required changes missing")
    return data


def inspect(messages: list[dict] | tuple[dict, ...], *, session: str, version: str) -> dict:
    init = [m for m in messages if m.get("type") == "init"]
    assistants = [m for m in messages if m.get("type") == "assistant"]
    if not session or not init or not assistants:
        raise ValueError("review transcript lacks init/assistant/session evidence")
    if any(m.get("model") != MODEL for m in (*init, *assistants)):
        raise ValueError("review transcript model is missing or not Fable")
    if any(m.get("session") != session for m in init):
        raise ValueError("review transcript session mismatch")
    if any(m.get("tool_use") is not False for m in assistants):
        raise ValueError("review transcript has tool use or lacks tool evidence")
    result = verdict(assistants[-1].get("text", ""))
    if result.get("version") != version:
        raise ValueError("review verdict does not name this exact version")
    return result


def encode(messages: tuple[dict, ...]) -> bytes:
    return ("".join(json.dumps(m, sort_keys=True, ensure_ascii=False) + "\n" for m in messages)).encode()


def verify(home: Path, row: dict) -> str | None:
    """Read-only; returns an explanation instead of vouching for a broken row."""
    from .skill_scripts import _held, _safe, version
    try:
        review = row.get("review") or {}
        if review.get("verdict") != "approve" or review.get("model") != MODEL or review.get("version") != row["version"]:
            raise ValueError("approval stamp is missing or inconsistent")
        proof = review.get("proof") or {}
        if not proof.get("init") or not proof.get("assistant") or any(m != MODEL for values in proof.values() for m in values):
            raise ValueError("approval model observations are missing or inconsistent")
        source = _held(home, row)
        _safe(home, source)
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["script_sha256"] or version(raw.decode(), row["usage"]) != row["version"]:
            raise ValueError("held bytes do not match approval")
        # Never accept an arbitrary path supplied by an edited index.
        path = source.parent / "review.jsonl"
        if review.get("transcript") != str(path.relative_to(home)):
            raise ValueError("approval transcript location mismatch")
        _safe(home, path)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != review.get("transcript_sha256"):
            raise ValueError("approval transcript hash mismatch")
        result = inspect([json.loads(line) for line in data.splitlines()], session=review["session"], version=row["version"])
        if result["verdict"] != "approve" or result["reasons"] != review["reasons"]:
            raise ValueError("approval transcript verdict mismatch")
    except Exception as exc:
        return f"unverified: {type(exc).__name__}: {exc}"
    return None
