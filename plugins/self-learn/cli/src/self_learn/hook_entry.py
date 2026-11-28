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


def _write_err(text: str) -> None:
    if text and sys.stderr is not None:
        # Bound to ``out`` for the lock invariant's walker (see ``_write``).
        out = getattr(sys.stderr, "buffer", None)
        if out is not None:
            out.write(text.encode("utf-8"))
            sys.stderr.flush()
        else:
            sys.stderr.write(text)


def _declared(raw: bytes | None) -> tuple[str | None, str | None]:
    """The mode and record id a rule file says it has, read without
    trusting it (its digest may not match). ``(None, None)`` when the
    bytes are not a JSON object."""
    try:
        data = json.loads(raw) if raw is not None else None
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    mode = data.get("mode") if data.get("mode") in ("deny", "warn") else None
    rid = data.get("record_id")
    rid = rid if isinstance(rid, str) and re.fullmatch(r"lrn-[0-9a-f]{8}", rid) else None
    return mode, rid


def _unusable(raw: bytes | None, rule: str, why: str) -> int:
    """A rule that cannot be loaded or evaluated: a deny rule (or one whose
    mode cannot be read) blocks the call with a line saying so; a rule that
    declares itself a warning stays silent, as its script would."""
    mode, rid = _declared(raw)
    if mode == "warn":
        return 0
    who = f"self-learn {rid}" if rid else "self-learn"
    _write_err(f"{who}: guard rule {rule} cannot be used ({why}) — failing closed\n")
    return 2


def _evaluate(argv: list[str]) -> int:
    """``self-learn-hook evaluate --rule <file>``: decide one tool call (the
    hook input on stdin) the way the rule's generated script would, through
    :mod:`hook_rules`. Deny: exit 2, the message on stderr. Warn: the
    structured line on stdout, exit 0. Allow: silence, exit 0. Never imports
    the ledger or the SDK: it runs on every matching tool call."""
    parser = argparse.ArgumentParser(prog="self-learn-hook evaluate")
    parser.add_argument("--rule", required=True)
    rule_path = parser.parse_args(argv).rule
    raw: bytes | None = None
    try:
        data = b""
        if sys.stdin is not None:
            try:
                data = sys.stdin.buffer.read()
            except (OSError, ValueError):
                data = b""  # unreadable input is empty input: a deny rule fails closed
        from . import hook_rules

        try:
            with open(rule_path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            return _unusable(None, rule_path, f"cannot read it: {exc.strerror or exc}")
        try:
            rule = hook_rules.load_rule(raw)
        except hook_rules.RuleError as exc:
            return _unusable(raw, rule_path, str(exc))
        decision = hook_rules.evaluate(rule, data)
        _write(decision.stdout)
        _write_err(decision.stderr)
        if sys.stdout is not None:
            sys.stdout.flush()
        return 1 if decision.exit_code == 2 else decision.exit_code
    except Exception as exc:  # noqa: BLE001 - a guard decides every call, never a traceback
        return _unusable(raw, rule_path, f"evaluator error: {type(exc).__name__}")


def main() -> int:
    if sys.argv[1:2] == ["evaluate"]:
        return _evaluate(sys.argv[2:])
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
