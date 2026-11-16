"""S-160 observed review transcript corroboration, not local-forger resistance.

The SDK records init and every assistant message, including tool use. The caller
stores those observations while holding the ledger lock, independent of cache
retention. Neither a model-request flag nor an index-only stamp is evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

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


def verify(home: Path, row: dict, *, notices: list[str] | None = None) -> str | None:
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
        from .script_screen import screen
        checked = screen(raw.decode())
        if not checked.ok:
            raise ValueError("screen refused: " + "; ".join(checked.rules))
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
        # The review commit is mandatory, even when native evidence exists.
        verify_commit(home, row, raw, data)
        evidence = review.get("corroboration") or {}
        if evidence.get("kind") == "native":
            path = native_path(home, review["session"])
            if str(path) != evidence.get("path"):
                raise ValueError("native transcript location mismatch")
            try:
                digest = native_digest(path, review["session"], row["version"], result)
            except OSError:
                if notices is not None:
                    notices.append("review transcript no longer present; verified from the ledger review commit")
            else:
                if digest != evidence["sha256"]:
                    raise ValueError("native transcript evidence changed")
        elif evidence.get("kind") != "git":
            raise ValueError("approval lacks independent corroboration")
    except Exception as exc:
        return f"unverified: {type(exc).__name__}: {exc}"
    return None


def native_digest(path: Path, session: str, version: str, expected: dict) -> str:
    """Hash actual CLI assistant lines, not self-learn's reconstructed messages."""
    lines = []
    messages: list[dict] = [{"type": "init", "model": MODEL, "session": session}]
    for line in path.read_bytes().splitlines(keepends=True):
        entry = json.loads(line)
        if entry.get("type") != "assistant":
            continue
        if entry.get("sessionId") != session:
            raise ValueError("native transcript session mismatch")
        message = entry["message"]
        content = message["content"]
        messages.append({"type": "assistant", "model": message.get("model"),
            "text": "".join(b.get("text", "") for b in content if b.get("type") == "text"),
            "tool_use": any(b.get("type") == "tool_use" for b in content)})
        lines.append(line)
    if inspect(messages, session=session, version=version) != expected:
        raise ValueError("native transcript verdict mismatch")
    return hashlib.sha256(b"".join(lines)).hexdigest()


def native_path(home: Path, session: str) -> Path:
    """Only the review cwd's transcript; never scan other projects."""
    from . import session_copies
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}", session):
        raise ValueError("invalid review session id")
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(home.resolve()))
    return session_copies.claude_projects_dir().resolve() / slug / (session + ".jsonl")


def corroboration(home: Path, row: dict, result: dict) -> dict:
    session = result["session"]
    path = native_path(home, session)
    try:
        expected = {key: result[key] for key in ("verdict", "reasons", "changes", "version")}
        return {"kind": "native", "path": str(path), "sha256": native_digest(path, session, row["version"], expected)}
    except OSError:
        return {"kind": "git"}


def verify_commit(home: Path, row: dict, raw: bytes, transcript: bytes) -> None:
    from . import gitops
    from .skill_scripts import INDEX, _held
    review = row["review"]
    subject = f"self-learn: script review {row['id']}: approve"
    candidates = gitops._git_ok(home, "log", "--format=%H", "--fixed-strings", "--grep=" + subject, "--", INDEX).stdout.splitlines()
    for commit in candidates:
        message = gitops._git_ok(home, "show", "-s", "--format=%B", commit).stdout
        if message.splitlines()[0] != subject or not all(t in message.splitlines() for t in (
            "Script-Version: " + row["version"], "Script-Session: " + review["session"])):
            continue
        stored = json.loads(gitops._git_ok(home, "show", commit + ":" + INDEX).stdout)
        saved = next((r for r in stored["scripts"] if r["id"] == row["id"]), {})
        if any(saved.get(k) != row.get(k) for k in ("skill", "name", "version", "script_sha256", "usage", "review")) or saved.get("state") != "approved":
            continue
        previous = gitops._git(home, "show", commit + "^:" + INDEX)
        if previous.returncode == 0 and any(r.get("id") == row["id"] and (r.get("review") or {}).get("verdict") == "approve" for r in json.loads(previous.stdout)["scripts"]):
            continue
        held = _held(home, row).relative_to(home).as_posix()
        if not all(gitops._git_ok(home, "rev-parse", commit + ":" + path).stdout.strip() ==
            hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            for path, data in ((held, raw), (str(Path(held).parent / "review.jsonl"), transcript))):
            continue
        return
    raise ValueError("approval absent from a matching self-learn review commit")
