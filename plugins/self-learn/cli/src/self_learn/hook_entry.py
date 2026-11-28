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


_TIMEOUT = 4
_SURROGATE_ESCAPES = re.compile(
    r"\\\\|\\u[dD][89aAbB][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}"
    r"|\\u[dD][89a-fA-F][0-9a-fA-F]{2}"
)


def _jq_surrogate(match: re.Match[str]) -> str:
    escape = match[0]
    if len(escape) != 6:  # Escaped backslash or a complete surrogate pair.
        return escape
    if escape[3].lower() in "89ab":
        raise ValueError("unpaired high surrogate")
    return r"\ufffd"  # jq substitutes U+FFFD for an isolated low surrogate.


def _documents(data: bytes) -> list[Any]:
    # The Bash hooks use jq on a stream and strip NULs in command substitutions.
    text = data.replace(b"\0", b"").decode("utf-8")
    # Validate even unselected strings and members hidden by duplicate keys.
    text = _SURROGATE_ESCAPES.sub(_jq_surrogate, text)
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
    if home_state != "ok":
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
    if stopped:
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
    if notices:
        yield (
            "self-learn notices for this project — yours to carry out in this session "
            "(no sudo needed): do it, then `self-learn notice done <id>`"
        )
        yield notices
        more = _select(documents, "project_notices_more", 0)
        if _positive(more):
            yield f"self-learn: {more} more notice(s) for this project — self-learn notice list"


def _write(data: bytes) -> None:
    if data and sys.stdout is not None:
        # Bound to ``out``: the lock invariant's walker reads ``.write`` on any
        # receiver it does not know as a byte stream as ``Record.write``.
        out = sys.stdout.buffer
        out.write(data)


def _degraded(reason: str) -> None:
    _write(f"⚠️  self-learn: pending-count check skipped — {reason}\n".encode("utf-8"))


def _run_cli(command: list[str], watchdog: str | None):
    # GNU timeout owns a separate deadline that survives the hook's death.
    # Its short KILL grace also covers a CLI that ignores the initial TERM.
    if watchdog is not None:
        command = [watchdog, "--kill-after=0.2", str(_TIMEOUT), *command]
    return procs.run_bounded(command, timeout=_TIMEOUT, binary=True)


def _session_start(executable: str, watchdog: str | None) -> None:
    try:
        result = _run_cli([executable, "status", "--fast"], watchdog)
    except procs.BoundedTimeout:
        _degraded("self-learn status timed out after 4s")
        return
    except (OSError, ValueError, MemoryError):
        return

    if result.returncode == 124:
        _degraded("self-learn status timed out after 4s")
        return
    try:
        output = b"".join(f"{line}\n".encode("utf-8") for line in _status_lines(_documents(result.stdout)))
    except (TypeError, ValueError, RecursionError, MemoryError):
        return  # A failed status JSON query leaves the hook quiet.
    _write(output)


def _read_observed(executable: str, watchdog: str | None) -> None:
    if sys.stdin is None:
        return
    try:
        documents = _documents(sys.stdin.buffer.read())
        paths = (_field(_field(doc, "tool_input"), "file_path") for doc in documents)
        path = _lines(value for value in paths if _default(value, None) is not None)
        match_path = path.replace("\\", "/") if os.name == "nt" else path
        if not fnmatchcase(match_path, "*/references/*.md"):
            return
        session = _select(documents, "session_id")
        args = [executable, "telemetry", "read-observed", "--path", path, "--session", session]
        if len(documents) == 1 and "agent_id" in documents[0]:
            args.append("--subagent")
        _run_cli(args, watchdog)
    except (procs.BoundedTimeout, OSError, TypeError, ValueError, RecursionError, MemoryError):
        pass  # This observer must never interrupt a Read.


def _find_self_learn() -> str | None:
    if os.name != "nt":
        executable = shutil.which("self-learn")
        if executable is not None:
            return executable
        # Bash command -v reports a non-executable PATH file when no
        # executable is found. GNU timeout then fails quietly at launch.
        for entry in os.get_exec_path():
            candidate = os.path.join(entry or os.curdir, "self-learn")
            if os.path.exists(candidate) and not os.path.isdir(candidate):
                return candidate
        return None

    # Windows shutil.which can look in the current directory for bare names.
    # Hooks run in the session's project, so only use the configured PATH.
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


#: The evaluate path's bounds (fix round 1, m3). Claude Code's hook input
#: carries a Write's whole file, so the input limit is generous; a rule file
#: is a few kilobytes. Reading stdin must finish within ``_READ_S``, and
#: everything, reading included, within ``_TOTAL_S`` (the entry's timeout
#: is 5 s). Past any bound the REGISTERED policy applies.
_MAX_INPUT = 64 * 1024 * 1024
_MAX_RULE = 1024 * 1024
_READ_S = 2.0
_TOTAL_S = 4.0


def _silence(stream) -> None:
    """Point a stream whose write failed (a closed or broken pipe) at the
    null device, so neither a retry nor the interpreter's flush at exit
    fails again and changes the exit status."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, stream.fileno())
        os.close(devnull)
    except (OSError, ValueError, AttributeError):
        pass


def _emit(stream, data: bytes) -> None:
    """Best-effort output for the evaluate path: the decision's exit status
    never depends on whether its output could be written (M6)."""
    if not data or stream is None:
        return
    try:
        out = stream.buffer
        out.write(data)
        out.flush()
    except (OSError, ValueError, AttributeError):
        _silence(stream)


def _refuse(mode: str, rid: str | None, why: str) -> int:
    """The registered policy for a rule that cannot decide this call: a
    deny registration blocks with a line saying why; a warn registration
    stays silent, as its script would. The mode is the REGISTRATION's,
    never the rule file's (M5)."""
    if mode == "warn":
        return 0
    who = f"self-learn {rid}" if rid else "self-learn"
    _emit(sys.stderr, f"{who}: {why} — failing closed\n".encode("utf-8"))
    return 2


def _read_input(deadline: float) -> bytes | None:
    """stdin, read in a helper thread so a caller that holds the pipe open
    cannot keep the hook waiting: ``None`` when it did not reach EOF by
    *deadline* or exceeded :data:`_MAX_INPUT`."""
    import threading
    import time

    box: dict[str, bytes | None] = {}

    def read() -> None:
        try:
            box["data"] = sys.stdin.buffer.read(_MAX_INPUT + 1) if sys.stdin is not None else b""
        except (OSError, ValueError):
            box["data"] = b""  # unreadable input is empty input: a deny rule fails closed

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(max(0.0, deadline - time.monotonic()))
    data = box.get("data")
    if data is None or len(data) > _MAX_INPUT:
        return None
    return data


def _is_link(path: str) -> bool:
    if os.name == "nt":
        from pathlib import Path

        from .primitives import fsops

        return fsops.is_link(Path(path))
    return os.path.islink(path)


def _evaluate(argv: list[str]) -> int:
    """``self-learn-hook evaluate --rule <file> --mode deny|warn --record <id>``:
    decide one tool call (the hook input on stdin) the way the rule's
    generated script would, through :mod:`hook_rules`. Deny: exit 2, the
    message on stderr. Warn: the structured line on stdout, exit 0. Allow:
    silence, exit 0.

    The registration carries the expected mode and record (fix round 1,
    M5): a rule file that is missing, a link, too large, damaged (its digest
    fails) or another record's or mode's applies the REGISTERED policy, so a
    damaged file cannot choose its own mode. A registration without
    ``--mode`` is treated as deny. Never imports the ledger or the SDK: it
    runs on every matching tool call."""
    import time

    started = time.monotonic()
    parser = argparse.ArgumentParser(prog="self-learn-hook evaluate")
    parser.add_argument("--rule", required=True)
    parser.add_argument("--mode", choices=("deny", "warn"), default="deny")
    parser.add_argument("--record", default=None)
    args = parser.parse_args(argv)
    mode, rid, rule_path = args.mode, args.record, args.rule
    try:
        data = _read_input(started + _READ_S)
        if data is None:
            return _refuse(mode, rid, f"hook input not read within {_READ_S:g}s "
                                      f"or over {_MAX_INPUT} bytes")
        from . import hook_rules

        if _is_link(rule_path):
            return _refuse(mode, rid, f"guard rule {rule_path} is a link, not self-learn's file")
        try:
            with open(rule_path, "rb") as fh:
                raw = fh.read(_MAX_RULE + 1)
        except OSError as exc:
            return _refuse(mode, rid, f"guard rule {rule_path} cannot be read: {exc.strerror or exc}")
        if len(raw) > _MAX_RULE:
            return _refuse(mode, rid, f"guard rule {rule_path} is over {_MAX_RULE} bytes")
        try:
            rule = hook_rules.load_rule(raw)
        except hook_rules.RuleError as exc:
            return _refuse(mode, rid, f"guard rule {rule_path} cannot be used ({exc})")
        if rule.mode != mode or (rid is not None and rule.record_id != rid):
            return _refuse(mode, rid, f"guard rule {rule_path} is {rule.record_id}'s {rule.mode} "
                                      f"rule, not the registered {rid or '?'} {mode} rule")
        remaining = _TOTAL_S - (time.monotonic() - started)
        decision = hook_rules.evaluate(
            rule, data, deadline_s=max(0.0, min(hook_rules.MATCH_DEADLINE_S, remaining))
        )
        code = decision.exit_code
        _emit(sys.stdout, decision.stdout)
        _emit(sys.stderr, decision.stderr.encode("utf-8"))
        return code
    except Exception as exc:  # noqa: BLE001 - a guard decides every call, never a traceback
        return _refuse(mode, rid, f"guard rule {rule_path}: evaluator error {type(exc).__name__}")


def main() -> int:
    if sys.argv[1:2] == ["evaluate"]:
        code = _evaluate(sys.argv[2:])
        # No interpreter shutdown: the stdin reader thread may still be
        # blocked on a caller that holds the pipe open (m3), which aborts
        # finalization, and no stream is flushed a second time (M6). Every
        # byte the decision writes was already flushed by ``_emit``.
        os._exit(code)
    parser = argparse.ArgumentParser(prog="self-learn-hook")
    parser.add_argument("event", choices=("session-start", "read-observed"))
    session_start = parser.parse_args().event == "session-start"
    executable = _find_self_learn()
    if not executable:
        if session_start:
            _degraded("self-learn is not on PATH")
        return 0

    watchdog = None
    if os.name != "nt":
        # Preserve the legacy Linux dependency guards. The native Windows
        # entry point needs neither jq nor GNU timeout.
        watchdog = shutil.which("timeout")
        for name, program in (("jq", shutil.which("jq")), ("timeout", watchdog)):
            if program is None:
                if session_start:
                    _degraded(f"{name} is not on PATH")
                return 0
        if not session_start and not shutil.which("cat"):
            return 0

    if session_start:
        _session_start(executable, watchdog)
    else:
        _read_observed(executable, watchdog)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
