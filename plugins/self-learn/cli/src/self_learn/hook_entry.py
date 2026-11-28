"""Console entry point for the shipped SessionStart and reference-read hooks."""

from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable
from typing import Any

from .primitives import procs


_WINDOWS_MUTATION = os.name == "nt"
_TIMEOUT = 9 if _WINDOWS_MUTATION else 4


def _documents(data: bytes) -> list[Any]:
    # The Bash hooks use jq on a stream and strip NULs in command substitutions.
    text = data.replace(b"\0", b"").decode("utf-8")
    decoder = json.JSONDecoder()
    documents = []
    pos = 0
    while pos < len(text):
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if pos < len(text):
            value, pos = decoder.raw_decode(text, pos)
            documents.append(value)
    return documents


def _field(value: Any, key: str) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value.get(key)


def _default(value: Any, fallback: Any) -> Any:
    # jq's // operator treats null and false as absent.
    return fallback if value is None or value is False else value


def _raw(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


def _lines(values: Iterable[Any]) -> str:
    return "\n".join(_raw(value) for value in values).replace("\0", "").rstrip("\n")


def _select(documents: list[Any], field: str, fallback: Any = None) -> str:
    values = (_default(_field(doc, field), fallback) for doc in documents)
    return _lines(value for value in values if value is not None)


def _safe(render: Callable[[], str], fallback: str = "") -> str:
    try:
        return render()
    except (TypeError, ValueError, RecursionError):
        return fallback


def _positive(text: str) -> int:
    # Bash's integer test accepts leading whitespace and a sign, but rejects
    # decimals and values outside the signed integer range.
    text = text.strip(" \t\r\n\v\f")
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        return 0
    try:
        value = int(text)
    except ValueError:
        return 0
    return value if 0 < value < 2**63 else 0


def _stopped_ids(documents: list[Any]) -> str:
    def join(ids: Any) -> str:
        if not isinstance(ids, list) or any(isinstance(item, (list, dict)) for item in ids):
            raise TypeError("expected an array of scalar intent IDs")
        return ", ".join("" if item is None else _raw(item) for item in ids)

    return _lines(join(_default(_field(doc, "intents_stopped"), [])) for doc in documents)


def _first_stopped_id(documents: list[Any]) -> str:
    def first(ids: Any) -> Any:
        if not isinstance(ids, list):
            raise TypeError("expected an array of intent IDs")
        return _default(ids[0], "?") if ids else "?"

    return _lines(first(_default(_field(doc, "intents_stopped"), [])) for doc in documents)


def _notices(documents: list[Any]) -> str:
    def values() -> Iterable[Any]:
        for doc in documents:
            notices = _default(_field(doc, "project_notices"), [])
            if isinstance(notices, dict):
                notices = notices.values()
            elif not isinstance(notices, list):
                raise TypeError("expected an array or object of notices")
            for notice in notices:
                line = _default(_field(notice, "line"), None)
                if line is not None:
                    yield line

    return _lines(values())


def _status_lines(documents: list[Any]) -> Iterable[str]:
    if not documents:
        return
    home_state = _select(documents, "home_state", "ok")
    if home_state != "ok" and not _WINDOWS_MUTATION:
        home = _select(documents, "home", "?")
        yield (
            f"⚠️  self-learn: ledger home {home} is {home_state} — no records are visible "
            "(this is NOT an empty ledger). Check $SELF_LEARN_HOME or clone/bootstrap "
            "the ledger repo; `self-learn status` explains."
        )
        return

    if _select(documents, "intents_probe") == "error":
        yield (
            "⚠️ self-learn: could not probe the ledger lock — a STOPPED intent may be hidden; "
            "run `self-learn status`"
        )

    count = _select(documents, "intents_stopped_count")
    stopped = _positive(count)
    if stopped and not _WINDOWS_MUTATION:
        ids = _safe(lambda: _stopped_ids(documents), "?")
        first_id = _safe(lambda: _first_stopped_id(documents), "?")
        plural = "s" if stopped != 1 else ""
        yield (
            f"🛑 self-learn: {count} STOPPED transaction intent{plural} ({ids}) — "
            "every ledger write refuses until cleared. Run "
            f"`self-learn reconcile --clear-intent {first_id}` after inspecting the offender."
        )

    unreadable = _select(documents, "total_unreadable")
    if _positive(unreadable):
        yield (
            f"⚠️  self-learn: {unreadable} unreadable record(s) in the queue — "
            "`self-learn status` names them"
        )

    notices = _safe(lambda: _notices(documents))
    if notices and not _WINDOWS_MUTATION:
        yield (
            "self-learn notices for this project — yours to carry out in this session "
            "(no sudo needed): do it, then `self-learn notice done <id>`"
        )
        yield notices
        more = _select(documents, "project_notices_more", 0)
        if _positive(more):
            yield f"self-learn: {more} more notice(s) for this project — self-learn notice list"


def _print_line(line: str) -> None:
    sys.stdout.buffer.write(line.encode("utf-8") + b"\n")


def _degraded(reason: str) -> None:
    _print_line(f"⚠️  self-learn: pending-count check skipped — {reason}")


def _session_start(executable: str) -> None:
    try:
        stdin = sys.stdin.buffer.read()
        if _WINDOWS_MUTATION:
            stdin += b"\n"
        result = procs.run_bounded(
            [executable, "status", "--fast"],
            timeout=_TIMEOUT,
            input=stdin,
            binary=True,
        )
    except procs.BoundedTimeout:
        _degraded("self-learn status timed out after 4s")
        return
    except (OSError, ValueError):
        return

    if _WINDOWS_MUTATION and not result.stdout:
        _print_line("status produced no output")
    if result.returncode == 124 and not _WINDOWS_MUTATION:
        _degraded("self-learn status timed out after 4s")
        return
    try:
        for line in _status_lines(_documents(result.stdout)):
            _print_line(line)
    except (TypeError, ValueError, RecursionError):
        if _WINDOWS_MUTATION:
            _print_line("malformed status output")


def _read_observed(executable: str) -> None:
    try:
        documents = _documents(sys.stdin.buffer.read())
        paths = (_field(_field(doc, "tool_input"), "file_path") for doc in documents)
        path = _lines(value for value in paths if _default(value, None) is not None)
        match_path = path.replace("\\", "/") if os.name == "nt" and not _WINDOWS_MUTATION else path
        if not fnmatchcase(match_path, "*/references/*.md"):
            if not _WINDOWS_MUTATION or "\\" in path:
                return
        if _WINDOWS_MUTATION and fnmatchcase(path, "*/references/*/*"):
            return
        session = _select(documents, "session_id", "unknown" if _WINDOWS_MUTATION else None)
        observed_path = path.replace("\\", "/") if _WINDOWS_MUTATION else path
        args = [executable, "telemetry", "read-observed", "--path", observed_path, "--session", session]
        if len(documents) == 1 and "agent_id" in documents[0] and (
            not _WINDOWS_MUTATION or documents[0]["agent_id"]
        ):
            args.append("--subagent")
        result = procs.run_bounded(args, timeout=_TIMEOUT, binary=True)
        if _WINDOWS_MUTATION:
            sys.stdout.buffer.write(result.stdout)
    except json.JSONDecodeError:
        if _WINDOWS_MUTATION:
            _print_line("malformed Read event")
    except (procs.BoundedTimeout, OSError, TypeError, ValueError, RecursionError):
        pass  # This observer must never interrupt a Read.


def _find_self_learn() -> str | None:
    if os.name != "nt":
        return shutil.which("self-learn")

    # Windows shutil.which can look in the current directory for bare names.
    # Hooks run in the session's project, so only use the configured PATH.
    cwd_executable = os.path.abspath("self-learn.exe")
    if _WINDOWS_MUTATION and os.path.isfile(cwd_executable):
        return cwd_executable
    current = os.path.normcase(os.path.realpath(os.curdir))
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        directory = os.path.realpath(entry)
        if os.path.normcase(directory) != current:
            executable = os.path.join(directory, "self-learn.exe")
            if os.path.isfile(executable):
                return executable
    return None


def main() -> int:
    parser = argparse.ArgumentParser(prog="self-learn-hook")
    parser.add_argument("event", choices=("session-start", "read-observed"))
    session_start = parser.parse_args().event == "session-start"
    executable = _find_self_learn()
    if not executable:
        if session_start or _WINDOWS_MUTATION:
            _degraded("self-learn is missing" if _WINDOWS_MUTATION else "self-learn is not on PATH")
        return 0

    if os.name != "nt":
        # Preserve the legacy Linux dependency guards. The native Windows
        # entry point needs neither jq nor GNU timeout.
        for name in ("jq", "timeout"):
            if not shutil.which(name):
                if session_start:
                    _degraded(f"{name} is not on PATH")
                return 0
        if not session_start and not shutil.which("cat"):
            return 0

    if session_start:
        _session_start(executable)
    else:
        _read_observed(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
