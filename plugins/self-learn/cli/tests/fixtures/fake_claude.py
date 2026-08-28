#!/usr/bin/env python3
"""U-sdk §3.10 `Fake-2` — a `SELF_LEARN_SDK_CLI_PATH`-shimmed fake `claude`
binary, ported from the UI's fixture of the same name
(`plugins/self-learn/ui/tests/fixtures/fake_claude.py`): the control
protocol ports verbatim (argv accepted and ignored; the first stdin
`control_request` with `subtype == "initialize"` answered immediately;
any other `control_request` gets a generic success reply so
`interrupt()` never hangs; a `{"type": "user"}` message's content string
selects a scenario; EOF exits 0). NO network access, NO real model,
anywhere in this file.

This unit's OWN scenario set (`Fake-2`'s table) plus a permission
round-trip: `ok_write` emits a real `can_use_tool` control_request (the
CLI-initiated direction — the SDK receives it FROM the child's stdout and
answers on the child's stdin) for a `Write` on a path read from
`FAKE_CLAUDE_WRITE_TARGET` (falling back to a fixed path), so the charter
callback actually runs end-to-end. Reading uses `sys.stdin.readline()`
exclusively (never `for line in sys.stdin:`), because a scenario that
blocks on a NESTED read (waiting for that control_response) would
otherwise desync against the outer loop's iterator read-ahead buffer.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
from pathlib import Path

SESSION_ID = "fake-session-1"


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def emit_raw(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def read_line() -> str | None:
    """Blocking single-line read; `None` on EOF. `main()` and the
    scenarios that need a nested read (the permission round-trip) both
    use ONLY this, never the file's iterator protocol."""
    raw = sys.stdin.readline()
    if raw == "":
        return None
    return raw


def assistant_message(text: str, uuid: str, content: list[dict] | None = None) -> dict:
    return {
        "type": "assistant",
        "uuid": uuid,
        "session_id": SESSION_ID,
        "parent_tool_use_id": None,
        "message": {
            "id": "msg_1",
            "model": "claude-sonnet-5",
            "stop_reason": "end_turn",
            "usage": {},
            "content": content if content is not None else [{"type": "text", "text": text}],
        },
    }


def user_tool_result(tool_use_id: str, uuid: str, *, content: str, is_error: bool) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "session_id": SESSION_ID,
        "parent_tool_use_id": None,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": is_error,
                }
            ],
        },
    }


def result_message(
    *,
    is_error: bool,
    subtype: str,
    uuid: str,
    errors: list[str] | None = None,
    result: str | None = None,
) -> dict:
    msg: dict = {
        "type": "result",
        "uuid": uuid,
        "subtype": subtype,
        "duration_ms": 10,
        "duration_api_ms": 8,
        "is_error": is_error,
        "num_turns": 1,
        "session_id": SESSION_ID,
        "total_cost_usd": 0.001,
    }
    if errors:
        msg["errors"] = errors
    if result is not None:
        msg["result"] = result
    return msg


def _request_permission(tool_name: str, tool_input: dict, tool_use_id: str) -> dict:
    """Emits a `can_use_tool` control_request (CLI -> SDK direction) and
    blocks for the matching `control_response`. Any OTHER line seen while
    waiting (there should not be one, in these scenarios) is ignored
    rather than wedging the fake."""
    request_id = f"perm-{tool_use_id}"
    emit(
        {
            "type": "control_request",
            "request_id": request_id,
            "request": {
                "subtype": "can_use_tool",
                "tool_name": tool_name,
                "input": tool_input,
                "tool_use_id": tool_use_id,
                "permission_suggestions": [],
            },
        }
    )
    while True:
        line = read_line()
        if line is None:
            return {}
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("type") == "control_response":
            response = data.get("response", {})
            if response.get("request_id") == request_id:
                return response.get("response", {}) or {}
        # a stray control_request (not expected here) or anything else:
        # keep waiting for our own response rather than mis-handling it.


def _scenario_ok_text() -> None:
    # `M41`/`E-7`: the assistant text and the `ResultMessage.result` are
    # DELIBERATE SENTINELS, not the same string -- E-7's branch order
    # (branch 1, `ResultMessage.result`, wins over branch 2, the final
    # AssistantMessage's text) is untestable if the two happen to match.
    emit(assistant_message("ASSISTANT-SENTINEL", "u1"))
    emit(result_message(is_error=False, subtype="success", uuid="u2", result="RESULT-SENTINEL"))


def _scenario_ok_blocks_only() -> None:
    emit(assistant_message("Hello from blocks", "u1"))
    emit(result_message(is_error=False, subtype="success", uuid="u2"))


def _scenario_ok_write() -> None:
    target = os.environ.get("FAKE_CLAUDE_WRITE_TARGET", "/tmp/example/pending/lrn-abc.md")
    tool_name = os.environ.get("FAKE_CLAUDE_WRITE_TOOL", "Write")
    tool_use_id = "toolu_1"
    response = _request_permission(tool_name, {"file_path": target}, tool_use_id)
    allowed = response.get("behavior") == "allow"
    emit(
        assistant_message(
            "",
            "u1",
            content=[
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": {"file_path": target},
                }
            ],
        )
    )
    emit(
        user_tool_result(
            tool_use_id,
            "u2",
            content="ok" if allowed else response.get("message", "permission denied"),
            is_error=not allowed,
        )
    )
    emit(result_message(is_error=False, subtype="success", uuid="u3"))


def _scenario_reader_write() -> None:
    """U-sdkr T2-c -- the reader's `sdk`-leg artifact producer. Unlike
    `ok_write`, this ACTUALLY WRITES `FAKE_CLAUDE_WRITE_TARGET` to disk
    when (and only when) the charter's response allows it -- `ok_write`
    never writes, so a reader test built on it would assert
    `_invoke_reader(...) is None` on every sdk leg and pass for the wrong
    reason. `FAKE_CLAUDE_WRITE_BODY` defaults to a minimal valid reader
    artifact; `FAKE_CLAUDE_RESULT_IS_ERROR`/`FAKE_CLAUDE_RESULT_TEXT`
    (default a sentinel distinct from anything else this scenario emits,
    `MAJOR-3`) drive the terminating `ResultMessage` independently of the
    write outcome, so an `rc != 0` leg needs no second scenario."""
    target = os.environ.get("FAKE_CLAUDE_WRITE_TARGET", "/tmp/example/spool/mine-output.json")
    body = os.environ.get("FAKE_CLAUDE_WRITE_BODY", '{"candidates": [], "fires": []}')
    tool_use_id = "toolu_reader_1"
    response = _request_permission("Write", {"file_path": target}, tool_use_id)
    allowed = response.get("behavior") == "allow"
    if allowed:
        with open(target, "w", encoding="utf-8") as f:
            f.write(body)
    emit(
        assistant_message(
            "",
            "u1",
            content=[
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": "Write",
                    "input": {"file_path": target},
                }
            ],
        )
    )
    emit(
        user_tool_result(
            tool_use_id,
            "u2",
            content="ok" if allowed else response.get("message", "permission denied"),
            is_error=not allowed,
        )
    )
    is_error = os.environ.get("FAKE_CLAUDE_RESULT_IS_ERROR") == "1"
    result_text = os.environ.get("FAKE_CLAUDE_RESULT_TEXT", "READER-SDK-RESULT-SENTINEL")
    emit(
        result_message(
            is_error=is_error,
            subtype="error_during_execution" if is_error else "success",
            uuid="u3",
            result=result_text,
        )
    )


def _next_invocation() -> int:
    """`FK3-b` (`V-2`) -- reads an invocation counter from the file named
    by `FAKE_CLAUDE_CALLS`, increments it, and returns the new (1-based)
    value. Each fake invocation is a fresh process with no surviving
    in-memory state, so the counter has to live on disk -- the same
    `CTR` / `CLAUDE_SHIM_SCRIPT_$N` shape `shims.py`'s bash worker shim
    already uses. No counter file configured -> always `1`."""
    path = os.environ.get("FAKE_CLAUDE_CALLS")
    if not path:
        return 1
    try:
        with open(path, "r", encoding="utf-8") as fh:
            n = int(fh.read().strip()) + 1
    except (OSError, ValueError):
        n = 1
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(n))
    return n


# --------------------------------------------------------------------- #
# U-cleanup-A RO-1/RO-2/RO-3/RO-4 -- per-invocation capture and the
# bash-shim-script interpreter. Additive only (`R2-N1`-style: no existing
# scenario or env var loses meaning). `main()` computes ONE invocation
# number per process for argv/prompt capture (`_CURRENT_INVOCATION`),
# taken BEFORE scenario dispatch (argv capture runs before any scenario
# is even selected). For every scenario EXCEPT `ok_write_real`, this is
# a REAL, counter-incrementing `_next_invocation()` call -- most
# scenarios never touch the counter themselves, so if `main()` only
# peeked, the on-disk counter would never advance and every invocation
# in a multi-call test would collide on the same `n` (measured:
# `test_fake_argv_per_call_ro1`'s second `argv.<n>` file never got
# written under a peek-only `main()`). `ok_write_real` (armored,
# byte-pinned, `git show c3b48e7`) is the ONE exception: it calls the
# real `_next_invocation()` internally itself for its own
# `FAKE_CLAUDE_WRITE_BODY_<n>` numbering, so a second real call from
# `main()` for that scenario would double-increment the on-disk counter
# per real child invocation, desyncing `FAKE_CLAUDE_WRITE_BODY_<n>`
# lookups from the actual call number -- `main()` peeks INSTEAD of
# calling real for exactly that one scenario, known ahead of dispatch
# via `FAKE_CLAUDE_FORCE_SCENARIO` (readable before any stdin is read).
# `_scenario_shim_script` reads the peeked/real `_CURRENT_INVOCATION`
# global directly rather than calling `_next_invocation()` a second
# time -- see `main()`'s own inline comment (the code, not this one, is
# the authority on the exact mechanism).
#
# Gate note (code gate r1, 8uvjHmdKaUd6PI3tSyB-F, NIT-1/NIT-2): the
# "double-increment" this fixes is NOT a pre-existing bug carried
# forward from before this build. At `ed1882f` (this build's base),
# `main()` never called `_next_invocation()` at all -- the only caller
# was `_scenario_ok_write_real` itself. It is a defect the RO-1/RO-2
# work (per-invocation argv/prompt capture) would have INTRODUCED, and
# was caught and avoided while building it, not a latent bug this build
# discovered. No scenario's semantics changed as a result: `ok_write_
# real` still gets its number from its own real call, `shim_script`
# reads the number `main()` took, every other scenario ignores the
# counter entirely. NIT-2: the peek-vs-real guard above keys ONLY on
# `FAKE_CLAUDE_FORCE_SCENARIO == "ok_write_real"` -- a future test that
# selects the `ok_write_real` scenario by PROMPT CONTENT instead of the
# force-scenario env var would fall into the `_next_invocation()` branch
# and re-introduce the double-increment for that one call. Latent only:
# every current call site uses the force-scenario env var.
# --------------------------------------------------------------------- #

_CURRENT_INVOCATION: int = 1


def _peek_invocation() -> int:
    """The read half of `_next_invocation()`, without the write-back --
    reports what the NEXT real `_next_invocation()` call would return,
    without consuming it. Used only for `main()`'s pre-dispatch argv/
    prompt numbering (see the module comment above); any scenario that
    needs a real, counter-incrementing invocation number still calls
    `_next_invocation()` itself."""
    path = os.environ.get("FAKE_CLAUDE_CALLS")
    if not path:
        return 1
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return int(fh.read().strip()) + 1
    except (OSError, ValueError):
        return 1


def _capture_argv_per_call(n: int) -> None:
    """RO-1 -- `FAKE_CLAUDE_CALLS_DIR/argv.<n>`, NUL-separated (same
    encoding as `FAKE_CLAUDE_ARGV_LOG` / `write_worker_claude_shim`'s
    `calls_dir/argv.$N`). Never truncates a PRIOR call's file -- each `n`
    gets its own path. Inert when `FAKE_CLAUDE_CALLS_DIR` is unset."""
    calls_dir = os.environ.get("FAKE_CLAUDE_CALLS_DIR")
    if not calls_dir:
        return
    Path(calls_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(calls_dir) / f"argv.{n}", "w", encoding="utf-8", newline="") as f:
        for arg in sys.argv[1:]:
            f.write(arg + "\0")


def _capture_prompt_per_call(n: int, content: str) -> None:
    """RO-2 -- `FAKE_CLAUDE_CALLS_DIR/prompt.<n>`, the exact `content`
    string of the one `{"type": "user"}` message this invocation
    received (the wire-level prompt, `worker.build_argv`-era `prompt.$N`
    counterpart). Inert when `FAKE_CLAUDE_CALLS_DIR` is unset."""
    calls_dir = os.environ.get("FAKE_CLAUDE_CALLS_DIR")
    if not calls_dir:
        return
    Path(calls_dir).mkdir(parents=True, exist_ok=True)
    (Path(calls_dir) / f"prompt.{n}").write_text(content, encoding="utf-8")


class _ShimScriptError(RuntimeError):
    """Raised when `_parse_shim_script` meets a bash idiom outside its
    known subset -- fails LOUDLY (an `error_unknown_scenario`-shaped
    result) rather than silently doing nothing, so a migrated test that
    needs a wider idiom is caught at the fake CLI, not misread as green."""


#: `write.PATH <<'MARKER'\ncontent\nMARKER`-shaped heredoc (the shape both
#: `test_worker.shim_writes` and `test_repair._write_script` emit,
#: independently, via `cat > PATH <<'MARKER'`) -- lazy content match so
#: two heredocs concatenated by `\n` (`f"{good}\n{bad}"`) are each found.
_HEREDOC_RE = re.compile(r"cat > (\S+) <<'(\w+)'\n(.*?)\2", re.DOTALL)
#: `printf '<content>' > PATH` -- the other write idiom several ad hoc
#: `script`/`script1`/`good`/`bad` local variables build directly (never
#: via `shim_writes`/`_write_script`), e.g. `test_worker.py`'s
#: `f"printf 'destination: bogus\\n' > {bad}"`. Single-quoted content
#: only (matches every measured site); `\n`/`\t`/`\\` are the only
#: printf escapes actually used, so only those are interpreted.
_PRINTF_RE = re.compile(r"printf '((?:[^'\\]|\\.)*)' > (\S+)")
#: `echo '<content>' > PATH` / `echo bareword > PATH` -- the third write
#: idiom (`test_miner.py::test_artifact_contract_sweeps_strays`'s stray-
#: artifact/output shim: `echo stray > path`, `echo '{"candidates": []...'
#: > path`). Plain `echo` (no `-e`) does not interpret backslash escapes,
#: so unlike `_PRINTF_RE` the content is taken verbatim; `echo` always
#: appends its own trailing newline, added here to match.
_ECHO_RE = re.compile(r"echo (?:'([^']*)'|(\S+)) > (\S+)")
#: `cat <<'MARKER'\ncontent\nMARKER` -- the SAME heredoc shape as
#: `_HEREDOC_RE` but with no `> PATH` redirect, so its content is
#: printed to the shim's own stdout instead of written to a file. This
#: is `_shim_env`'s (`test_composer.py`) analyst-driving idiom: the OLD
#: bash `claude` shim ran the whole script via `bash -c`, and ITS
#: combined stdout WAS the (then-real) CLI's own final text answer --
#: `analyst.analyze()` parses `outcome.stdout` as YAML on success. Under
#: sdk there is no such direct stdout-of-the-child-process mapping, so
#: `_scenario_shim_script` treats a `("print", content)` op as the text
#: to carry on `ResultMessage.result` instead (see `_scenario_analyst_
#: result`'s own `result=` kwarg, `E-7` branch 1). Applied AFTER
#: `_HEREDOC_RE` has already consumed every `cat > PATH <<'MARKER'`
#: write, so only the no-target form remains to match here.
_PRINT_HEREDOC_RE = re.compile(r"cat <<'(\w+)'\n(.*?)\1", re.DOTALL)
_RM_RE = re.compile(r"(?<![\w/])rm -f (\S+)")
_TOUCH_RE = re.compile(r"(?<![\w/])touch (\S+)")
#: `mv SRC DST`, bare or as `git -C DIR mv SRC DST` (both spellings
#: appear TOGETHER, joined by ` || `, as a git-mv-with-plain-fallback
#: idiom -- `test_repair.py::test_b6`'s "orphaned record mid-run"). Both
#: spellings match on the trailing `mv (\S+) (\S+)`; the interpreter
#: applies the SAME (src, dst) pair once per match, tolerating a repeat
#: (the second alternative's src no longer exists once the first
#: already moved it -- `_scenario_shim_script` skips a missing src).
_MV_RE = re.compile(r"(?<![\w/-])mv (\S+) (\S+?)(?:\s+2>/dev/null|$|\s*\|\|)", re.MULTILINE)
#: Statement separators / prefixes that are semantically inert once every
#: write is applied unconditionally into an already-existing tree
#: (`_ShimScriptError`'s fallback checks the RESIDUE against this, not
#: the whole script, so it only has to recognise glue, not content).
_INERT_RESIDUE_RE = re.compile(
    r"^[\s&]*(mkdir -p \S+[\s&]*)*(echo\b.*)?(cat > /dev/null \|\| true)?[\s&]*$",
    re.DOTALL,
)


def _parse_shim_script(script: str) -> list[tuple[str, str, str] | tuple[str, str]]:
    """RO-3 -- interprets the bounded bash-idiom subset `shim_writes`/
    `_write_script`/`_defect_script` and their direct callers actually
    emit (measured: heredoc writes, `printf`/`echo` single-line writes,
    `rm -f`, `touch`, `mkdir -p` glue, `&&`/newline joiners, bare
    `cat > /dev/null || true` noise). Returns an ordered list of
    `("write", path, content)` / `("remove", path)` / `("touch", path)` /
    `("move", src, dst)` / `("print", content)` ops. Multiple ops from ONE
    script (`f"{a}\\n{b}"`) preserve source order. Anything left over that
    is not accounted-for glue raises `_ShimScriptError` -- see its own
    docstring."""
    ops: list[tuple[str, str, str] | tuple[str, str]] = []
    residue = script
    for m in _HEREDOC_RE.finditer(script):
        path, _marker, content = m.group(1), m.group(2), m.group(3)
        ops.append(("write", path, content))
        residue = residue.replace(m.group(0), "", 1)
    for m in _PRINT_HEREDOC_RE.finditer(residue):
        _marker, content = m.group(1), m.group(2)
        ops.append(("print", content))
        residue = residue.replace(m.group(0), "", 1)
    for m in _PRINTF_RE.finditer(residue):
        raw_content, path = m.group(1), m.group(2)
        content = raw_content.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
        ops.append(("write", path, content))
    residue = _PRINTF_RE.sub("", residue)
    for m in _ECHO_RE.finditer(residue):
        quoted, bare, path = m.group(1), m.group(2), m.group(3)
        content = (quoted if quoted is not None else bare) + "\n"
        ops.append(("write", path, content))
    residue = _ECHO_RE.sub("", residue)
    for m in _MV_RE.finditer(residue):
        ops.append(("move", m.group(1), m.group(2)))
    residue = _MV_RE.sub("", residue)
    for m in _RM_RE.finditer(residue):
        ops.append(("remove", m.group(1)))
    residue = _RM_RE.sub("", residue)
    for m in _TOUCH_RE.finditer(residue):
        ops.append(("touch", m.group(1)))
    residue = _TOUCH_RE.sub("", residue)
    # `git -C DIR` glue left behind once its trailing `mv ...` was
    # consumed above (the git-mv alternative of the `||` fallback).
    residue = re.sub(r"(?<![\w/])git -C \S+\s*", "", residue)
    residue = re.sub(r"\|\|", "", residue)
    if not _INERT_RESIDUE_RE.match(residue):
        raise _ShimScriptError(
            f"fake_claude._parse_shim_script: unrecognised bash idiom in residue {residue!r} "
            f"(full script: {script!r}) -- the U-cleanup-A interpreter supports heredoc, "
            "printf, and echo writes, rm -f, touch, mv, mkdir -p glue, and bare "
            "cat>/dev/null||true noise only."
        )
    return ops


def _scenario_shim_script() -> None:
    """RO-3/RO-4 -- the sdk-side replacement for the bash worker/repair
    shim's `CLAUDE_SHIM_SCRIPT[_<n>]` + `CLAUDE_SHIM_EXIT[_<n>]` pair.
    Selected via `FAKE_CLAUDE_FORCE_SCENARIO=shim_script` (a real
    `worker.run()` prompt cannot content-match a fixed `SCENARIOS` key,
    same reasoning as `ok_write_real`'s docstring). Numbered env var wins,
    falling back to the unnumbered form -- identical fallback shape to
    `write_worker_claude_shim`'s own `SCRIPT_VAR`/`EXIT_VAR` bash. EVERY
    op in the script applies unconditionally, not gated on the charter
    (`R2-N3`, see the inline comment below) -- `RO-3`'s multi-target
    obligation. `CLAUDE_SHIM_SLEEP_<n>` (no unnumbered fallback, matching
    the bash shim) sleeps before emitting a result -- used by the `sdk`
    leg's own real wall-clock timeout guard, not this fake blocking
    forever. A nonzero exit code terminates the PROCESS itself
    (`sys.exit`, after flushing) so the SDK's real `ProcessError` leg
    fires, exactly the `CliBackend` parity `CLAUDE_SHIM_EXIT_<n>` gave
    the bash leg."""
    # `main()` already did the real, counter-incrementing read for THIS
    # scenario (it peeks only for `ok_write_real`, see the module
    # comment above `_CURRENT_INVOCATION`'s definition) -- a second real
    # call here would double-increment, the same bug that call caused
    # for `ok_write_real` before this file's own fix.
    n = _CURRENT_INVOCATION
    script = os.environ.get(f"CLAUDE_SHIM_SCRIPT_{n}") or os.environ.get("CLAUDE_SHIM_SCRIPT", "")
    exit_code = int(os.environ.get(f"CLAUDE_SHIM_EXIT_{n}") or os.environ.get("CLAUDE_SHIM_EXIT", "0"))
    sleep_s = os.environ.get(f"CLAUDE_SHIM_SLEEP_{n}")
    if sleep_s:
        time.sleep(float(sleep_s))
    try:
        ops = _parse_shim_script(script) if script else []
    except _ShimScriptError as exc:
        emit(
            result_message(
                is_error=True, subtype="error_unknown_scenario", uuid="u-shim-err", errors=[str(exc)]
            )
        )
        return

    # `R2-N3` (measured while migrating `test_repair.py`'s foreign-file
    # tests): the BASH shim never gated its writes on the charter at all
    # -- it IS the whole "claude" process, so a `cat > path` inside it
    # runs unconditionally, same as a concurrent, un-sandboxed producer
    # would. Several migrated tests (`_foreign_script`'s "a concurrent
    # attended session" writes) rely EXACTLY on that bypass -- they write
    # OUTSIDE the batch invocation's own containment on purpose, to
    # simulate a different actor. Gating this scenario's writes on
    # `can_use_tool` (as `ok_write_real` correctly does for the CH/WS
    # charter-enforcement tests) would silently deny them and is not
    # equivalent to what the shim ever did. So `shim_script` applies every
    # op UNCONDITIONALLY -- charter enforcement is tested elsewhere
    # (`ok_write`/`ok_write_real`, `CH1`-`CH13`), never through this
    # scenario. A `tool_use`/`tool_result` pair is still emitted (for
    # `EventLog` realism) but never blocks on `_request_permission`.
    # U-corrob 2026-08-27: one pair per write op -- the announce-only-
    # first form made a correct multi-write run report a MISMATCH.
    writes = [op for op in ops if op[0] == "write"]
    for i, write_op in enumerate(writes, 1):
        target = write_op[1]
        tool_use_id = f"toolu_shim_{n}_{i}"
        emit(assistant_message("", f"u1-{i}", content=[
            {"type": "tool_use", "id": tool_use_id, "name": "Write", "input": {"file_path": target}}]))
        emit(user_tool_result(tool_use_id, f"u2-{i}", content="ok", is_error=False))
    for op in ops:
        if op[0] == "write":
            _, path, content = op
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
        elif op[0] == "remove":
            Path(op[1]).unlink(missing_ok=True)
        elif op[0] == "touch":
            p = Path(op[1])
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                os.utime(p, None)
            else:
                p.write_text("", encoding="utf-8")
        elif op[0] == "move":
            _, src, dst = op
            src_p = Path(src)
            if src_p.exists():
                Path(dst).parent.mkdir(parents=True, exist_ok=True)
                src_p.replace(dst)

    # `print` ops (`_PRINT_HEREDOC_RE`) carry no filesystem side effect --
    # their content becomes `ResultMessage.result`, the analyst-driving
    # idiom `_shim_env` (`test_composer.py`) needs (see that regex's own
    # comment). Concatenated in source order, matching what sequential
    # `cat <<MARKER` calls would print to one real stdout stream.
    print_text = "".join(op[1] for op in ops if op[0] == "print")

    if exit_code != 0:
        sys.stdout.flush()
        sys.exit(exit_code)
    if print_text:
        emit(result_message(is_error=False, subtype="success", uuid="u3", result=print_text))
    else:
        emit(result_message(is_error=False, subtype="success", uuid="u3"))


def _scenario_ok_write_real() -> None:
    """`FK3-a`/`FK3-b`/`FK3-c` (`V-2`) -- like `_scenario_ok_write`, but
    actually WRITES the target file, iff the charter's response
    `behavior == "allow"`: writing unconditionally would make the file's
    existence say nothing about the charter, which is exactly the
    property `WS6` and `RP4` are built to observe. The body is selected
    PER INVOCATION (`FK3-b`): `_next_invocation` reads a counter file
    named by `FAKE_CLAUDE_CALLS`, and the body comes from
    `FAKE_CLAUDE_WRITE_BODY_<n>`, falling back to `FAKE_CLAUDE_WRITE_BODY`
    -- so a worker run that reaches a repair round (two fake spawns) can
    script two DIFFERENT bodies, one per round. Target:
    `FAKE_CLAUDE_WRITE_TARGET` (`FK3-c`) -- the same knob
    `_scenario_ok_write` already reads; no new target knob."""
    n = _next_invocation()
    target = os.environ.get("FAKE_CLAUDE_WRITE_TARGET", "/tmp/example/pending/lrn-abc.md")
    tool_name = os.environ.get("FAKE_CLAUDE_WRITE_TOOL", "Write")
    tool_use_id = "toolu_1"
    response = _request_permission(tool_name, {"file_path": target}, tool_use_id)
    allowed = response.get("behavior") == "allow"
    if allowed:
        body = os.environ.get(f"FAKE_CLAUDE_WRITE_BODY_{n}") or os.environ.get(
            "FAKE_CLAUDE_WRITE_BODY", ""
        )
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(body)
    emit(
        assistant_message(
            "",
            "u1",
            content=[
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": {"file_path": target},
                }
            ],
        )
    )
    emit(
        user_tool_result(
            tool_use_id,
            "u2",
            content="ok" if allowed else response.get("message", "permission denied"),
            is_error=not allowed,
        )
    )
    emit(result_message(is_error=False, subtype="success", uuid="u3"))


def _scenario_error_result() -> None:
    # `FAKE_CLAUDE_ERROR_TEXT` (U-cleanup-A addition, additive/optional):
    # overrides the hardcoded "boom" errors-list content, default
    # unchanged -- lets a caller control the LENGTH/text of the rendered
    # `exited` detail (e.g. to exercise `detail_cap`/`detail_strip`,
    # `test_lg5`'s migrated form), without touching any existing
    # `error_result`-driving test that doesn't set the var.
    error_text = os.environ.get("FAKE_CLAUDE_ERROR_TEXT", "boom")
    emit(assistant_message("trying...", "u1"))
    emit(result_message(is_error=True, subtype="error_during_execution", uuid="u2", errors=[error_text]))


def _scenario_no_result() -> None:
    emit(assistant_message("partial, then nothing", "u1"))
    sys.stdout.flush()
    sys.exit(0)  # clean exit -- EOF on the SDK's read side, deliberately
    # no ResultMessage ever emitted.


def _scenario_hard_exit() -> None:
    emit(assistant_message("about to die", "u1"))
    sys.stdout.flush()
    os._exit(1)  # noqa: SLF001 - deliberate hard kill, no cleanup, no result


def _scenario_hang() -> None:
    time.sleep(3600)


def _scenario_hang_sigterm_ignored() -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(3600)


def _scenario_malformed_line() -> None:
    emit(assistant_message("before", "u1"))
    # Not JSON, and does not start with "{" -- the SDK's own transport
    # layer skips this silently and keeps reading.
    emit_raw("not json output from a misbehaving build")
    emit(assistant_message("after", "u2"))
    emit(result_message(is_error=False, subtype="success", uuid="u3"))


def _scenario_unknown_message_type() -> None:
    """`M42`/`OU8`: `malformed_line` is skipped by the SDK's OWN
    transport layer before any message object is ever constructed --
    `O-drain`'s "every other message type is tolerated by skipping" is
    about a message that DOES reach `client.receive_response()` as a
    real, parsed object our drain's `if/elif` chain does not explicitly
    branch on. A `stream_event` line is exactly that: a message type the
    SDK's parser recognizes and constructs (`StreamEvent`), which
    `receive_response()` forwards like any other message ahead of the
    terminating `ResultMessage`, and which this unit's drain must
    silently skip rather than raise on."""
    emit(
        {
            "type": "stream_event",
            "uuid": "u-se1",
            "session_id": SESSION_ID,
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "partial"}},
        }
    )
    emit(assistant_message("after the stream event", "u1"))
    emit(result_message(is_error=False, subtype="success", uuid="u2", result="after the stream event"))


def _fake_claude_out_text() -> str:
    """`FK-c` -- `FAKE_CLAUDE_OUT` is the sdk leg's `CLAUDE_SHIM_OUT`."""
    out_path = os.environ.get("FAKE_CLAUDE_OUT", "")
    return Path(out_path).read_text(encoding="utf-8") if out_path else ""


def _scenario_analyst_result() -> None:
    """`FK-a` -- `E-7` branch 1 (`ResultMessage.result` wins)."""
    emit(assistant_message("ANALYST-ASSISTANT-SENTINEL", "u1"))
    emit(result_message(is_error=False, subtype="success", uuid="u2", result=_fake_claude_out_text()))


def _scenario_analyst_blocks() -> None:
    """`FK-b` -- `E-7` branch 2: split across two `TextBlock`s, no
    `ResultMessage.result` -- makes the `"".join(...)` observable."""
    text = _fake_claude_out_text()
    mid = len(text) // 2
    content = [{"type": "text", "text": text[:mid]}, {"type": "text", "text": text[mid:]}]
    emit(assistant_message("", "u1", content=content))
    emit(result_message(is_error=False, subtype="success", uuid="u2"))


SCENARIOS = {
    "ok_text": _scenario_ok_text,
    "ok_blocks_only": _scenario_ok_blocks_only,
    "ok_write": _scenario_ok_write,
    "ok_write_real": _scenario_ok_write_real,
    "error_result": _scenario_error_result,
    "no_result": _scenario_no_result,
    "hard_exit": _scenario_hard_exit,
    "hang": _scenario_hang,
    "hang_sigterm_ignored": _scenario_hang_sigterm_ignored,
    "malformed_line": _scenario_malformed_line,
    "unknown_message_type": _scenario_unknown_message_type,
    "reader_write": _scenario_reader_write,
    "analyst_result": _scenario_analyst_result,
    "analyst_blocks": _scenario_analyst_blocks,
    "shim_script": _scenario_shim_script,
}


def _respond_control_success(request_id: str, response: dict | None = None) -> None:
    emit(
        {
            "type": "control_response",
            "response": {"subtype": "success", "request_id": request_id, "response": response or {}},
        }
    )


def main() -> int:
    # `FK-d` -- when set, record OUR OWN argv, NUL-separated (same
    # encoding as `write_analyst_claude_shim`'s `printf '%s\0' "$@"`).
    # Inert when unset; runs BEFORE reading stdin.
    argv_log = os.environ.get("FAKE_CLAUDE_ARGV_LOG")
    if argv_log:
        with open(argv_log, "w", encoding="utf-8", newline="") as f:
            for arg in sys.argv[1:]:
                f.write(arg + "\0")
    # U-cleanup-A migration (`claude_cli_shim_analyst`'s `pwd -P` capture,
    # `test_route_cli.py`) -- the SDK's own resolved cwd for this child,
    # matching what `os.getcwd()` reports from inside the spawned process
    # (mirrors the bash shim's `pwd -P`).
    cwd_log = os.environ.get("FAKE_CLAUDE_CWD_LOG")
    if cwd_log:
        Path(cwd_log).write_text(os.getcwd() + "\n", encoding="utf-8")
    # RO-1 -- ONE invocation number per process, computed once so every
    # per-call capture/knob in THIS invocation (argv, prompt,
    # CLAUDE_SHIM_SCRIPT_<n>, CLAUDE_SHIM_EXIT_<n>) agrees on `n`. A REAL
    # (counter-incrementing) read here is what every OTHER scenario needs
    # -- most scenarios never touch `_next_invocation()` themselves, so
    # if main() only peeked, the on-disk counter would never actually
    # advance and every invocation in a multi-call test would collide on
    # the same `n` (measured: `test_fake_argv_per_call_ro1`'s second
    # `argv.<n>` file never got written under a peek-only main()).
    # `ok_write_real` (armored, `git show c3b48e7`) is the ONE exception:
    # it calls the real `_next_invocation()` internally for its own
    # `FAKE_CLAUDE_WRITE_BODY_<n>` numbering, so a real call here too
    # would double-increment for exactly that scenario -- known ahead of
    # dispatch via `FAKE_CLAUDE_FORCE_SCENARIO` (readable before any
    # stdin is read), so peek ONLY in that one case.
    global _CURRENT_INVOCATION
    if os.environ.get("FAKE_CLAUDE_FORCE_SCENARIO") == "ok_write_real":
        _CURRENT_INVOCATION = _peek_invocation()
    else:
        _CURRENT_INVOCATION = _next_invocation()
    _capture_argv_per_call(_CURRENT_INVOCATION)
    while True:
        raw_line = read_line()
        if raw_line is None:
            return 0
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        if data.get("type") == "control_request":
            request_id = data.get("request_id", "")
            _respond_control_success(request_id)
            continue

        if data.get("type") == "user":
            content = data.get("message", {}).get("content", "")
            # RO-2 -- per-invocation prompt capture, the exact wire-level
            # content this invocation received.
            _capture_prompt_per_call(_CURRENT_INVOCATION, content)
            # legacy single-file prompt log (`FAKE_CLAUDE_ARGV_LOG`'s own
            # counterpart) -- truncates every call, representing only the
            # LAST invocation; kept so the ~30 pre-existing single-
            # invocation callers of the migrated worker shim fixture that
            # read one fixed `prompt` path need no change (`RO-2`).
            prompt_log = os.environ.get("FAKE_CLAUDE_PROMPT_LOG")
            if prompt_log:
                Path(prompt_log).write_text(content, encoding="utf-8")
            # `MAJOR-2`: a REAL `worker.run()` prompt is a long, dynamic,
            # record-specific string that can never match a fixed
            # SCENARIOS key by exact equality -- so a test driving the
            # charter end-to-end through the real `SELF_LEARN_ENFORCE_SCOPE`
            # variable and the real prompt (rather than a hand-built
            # `SessionSpec`) needs a way to pick a canned scenario anyway.
            # `FAKE_CLAUDE_FORCE_SCENARIO`, when set, overrides content
            # matching unconditionally -- a test-fixture-only knob, no
            # production code reads it, and it changes nothing about which
            # scenarios exist or what they do.
            forced = os.environ.get("FAKE_CLAUDE_FORCE_SCENARIO")
            scenario = SCENARIOS.get(forced) if forced else SCENARIOS.get(content)
            if scenario is not None:
                scenario()
            else:
                emit(
                    result_message(
                        is_error=True,
                        subtype="error_unknown_scenario",
                        uuid="u-err",
                        errors=[f"fake_claude: no such scenario {content!r}"],
                    )
                )
            continue
        # Anything else on stdin is ignored -- this fake only understands
        # control_request/initialize and one user message per turn.


if __name__ == "__main__":
    sys.exit(main())
