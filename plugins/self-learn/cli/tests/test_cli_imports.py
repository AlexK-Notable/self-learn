"""Keep model-only dependencies out of fresh read-command processes."""

import subprocess
import sys


def test_cli_import_does_not_load_sdk():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import self_learn.cli; "
            "assert callable(self_learn.cli.main); "
            "loaded = sorted(n for n in sys.modules "
            "if n.split('.')[0] in ('claude_agent_sdk', 'jsonschema')); "
            "assert not loaded, loaded",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
