"""U-fake §3.3 -- the two bash `claude`-shim script builders, extracted
verbatim from `test_worker.py`'s and `test_route_cli.py`'s fixtures so a
Wave-2 `["cli", "sdk"]` contract test can call them from inside a
`params=` fixture body -- which cannot itself request another fixture,
so the script text has to be a function a fixture CALLS rather than a
string literal reachable only by requesting that one fixture (§1.2).

Plain functions, not fixtures (`D-8`, `SH4`): a `@pytest.fixture` here
could not be called from inside the `params=["cli", "sdk"]` fixture body
that is T2's whole shape.

Both builders write the executable into an ALREADY-EXISTING directory
and return its path, including the `chmod`; neither creates its own
directory (`SH-d`) -- the caller is the one that knows whether the
directory is shared.

Leaf-level (`SH-b`): imports nothing from `self_learn` and nothing from
any `test_*` module.
"""

from __future__ import annotations

import stat
from pathlib import Path

__all__ = ["write_worker_claude_shim", "write_analyst_claude_shim"]


def write_worker_claude_shim(
    shims_dir: Path, *, counter: Path, log: Path, prompt_log: Path, calls_dir: Path
) -> Path:
    """The worker's multi-invocation-observable `claude` shim
    (`test_worker.py::claude_cli_shim_worker`'s own docstring, U-repair
    F5) -- script bytes only (§3.3.1); `shims_dir` and the paths it
    interpolates are the caller's."""
    shim = shims_dir / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'CTR="{counter}"\n'
        'N=$(( $(cat "$CTR" 2>/dev/null || echo 0) + 1 ))\n'
        'echo "$N" > "$CTR"\n'
        f'printf \'%s\\0\' "$@" >> "{log}"\n'
        f'printf \'%s\\0\' "$@" >> "{calls_dir}/argv.$N"\n'
        # the prompt rides STDIN (audit 2026-07-15: argv caps at 128 KiB)
        f'cat > "{calls_dir}/prompt.$N" || true\n'
        f'cat "{calls_dir}/prompt.$N" >> "{prompt_log}" || true\n'
        'SCRIPT_VAR="CLAUDE_SHIM_SCRIPT_$N"\n'
        'SCRIPT="${!SCRIPT_VAR-}"\n'
        'if [ -z "$SCRIPT" ]; then SCRIPT="${CLAUDE_SHIM_SCRIPT-}"; fi\n'
        'if [ -n "$SCRIPT" ]; then bash -c "$SCRIPT"; fi\n'
        'SLEEP_VAR="CLAUDE_SHIM_SLEEP_$N"\n'
        'SLEEP="${!SLEEP_VAR-}"\n'
        'if [ -n "$SLEEP" ]; then sleep "$SLEEP"; fi\n'
        'EXIT_VAR="CLAUDE_SHIM_EXIT_$N"\n'
        'EXIT="${!EXIT_VAR-}"\n'
        'if [ -z "$EXIT" ]; then EXIT="${CLAUDE_SHIM_EXIT-0}"; fi\n'
        'exit "$EXIT"\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return shim


#: The analyst's stdout-shaped `claude` shim's script bytes, verbatim
#: from `test_route_cli.py`'s module-level `CLAUDE_SHIM` constant.
#: `pwd -P` (U-analyst A5): `-P` matters -- bash seeds `$PWD` from the
#: inherited environment, so the plain builtin can report the parent's
#: directory instead of the subprocess's actual one. Inert for every
#: caller that doesn't read `CLAUDE_SHIM_CWD`.
_ANALYST_SHIM_SCRIPT = """#!/usr/bin/env bash
printf '%s\\0' "$@" > "$CLAUDE_SHIM_LOG"
pwd -P > "$CLAUDE_SHIM_CWD"
cat "$CLAUDE_SHIM_OUT"
exit "${CLAUDE_SHIM_EXIT-0}"
"""


def write_analyst_claude_shim(shim_dir: Path) -> Path:
    """The analyst's stdout-shaped `claude` shim
    (`test_route_cli.py::claude_cli_shim_analyst`) -- script bytes only
    (§3.3.2); `shim_dir` is the caller's."""
    shim = shim_dir / "claude"
    shim.write_text(_ANALYST_SHIM_SCRIPT, encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return shim
