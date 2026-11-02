"""Keep model-only dependencies out of fresh read-command processes."""

import subprocess
import sys

_LOADED = (
    "loaded = sorted(n for n in sys.modules "
    "if n.split('.')[0] in ('claude_agent_sdk', 'jsonschema')); "
)


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", "import sys; " + code],
        capture_output=True,
        text=True,
    )


def test_the_filter_sees_both_modules_when_they_are_loaded():
    # Positive control: if a module were renamed, the absence check below
    # would pass without looking at anything.
    result = _run(
        "import claude_agent_sdk, jsonschema; " + _LOADED
        + "assert {n.split('.')[0] for n in loaded} == "
        "{'claude_agent_sdk', 'jsonschema'}, loaded"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_import_does_not_load_sdk():
    result = _run(
        "import self_learn.cli; "
        "assert callable(self_learn.cli.main); " + _LOADED
        + "assert not loaded, loaded"
    )
    assert result.returncode == 0, result.stdout + result.stderr
