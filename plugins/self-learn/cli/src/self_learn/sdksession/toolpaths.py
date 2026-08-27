"""U-engine sdksession — `toolpaths.py` (spec §4.2, §2.2a's second
skeleton-identical (1.000) pair): the write-tool target-path extraction
shared by both charters. `AGR1` proves both charters resolve the same
target through this ONE function; the charters themselves (deny-by-
default policy, `CharterPaths`, the write-scope matching) stay put --
this module owns nothing but "which `tool_input` key names the path".

Import-bounded: stdlib only.
"""

from __future__ import annotations

from typing import Any

__all__ = ["TARGET_PATH_KEYS", "extract_target_path"]

#: The order both charters already probed in, ported verbatim (CLI
#: `charter.py`'s `P`, UI `charter.py`'s `_PATH_KEYS`).
TARGET_PATH_KEYS = ("file_path", "path", "notebook_path")


def extract_target_path(tool_input: dict[str, Any]) -> str | None:
    """Ported verbatim from both charters' `_extract_target_path`: the
    first `TARGET_PATH_KEYS` entry present as a non-empty `str`, else
    `None`."""
    for key in TARGET_PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None
