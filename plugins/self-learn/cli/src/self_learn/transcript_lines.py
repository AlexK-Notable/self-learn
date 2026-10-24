"""Physical JSONL rows and translation of pre-newline-count pointers.

Do not use universal-newline text I/O before this splitter: a bare CR is
JSON whitespace, not a row boundary. CRLF's CR is retained for json.loads.
"""

from collections.abc import Sequence

FORMAT = "newline-v1"


def split(text: str, *, complete: bool = False) -> list[str]:
    """Split on LF only; omit the trailing empty slot, or a torn tail."""
    rows = text.split("\n")
    if complete or rows[-1] == "":
        rows.pop()
    return rows


def legacy_line(rows: Sequence[str], number: int) -> int | None:
    """Physical row containing an old splitlines-numbered position."""
    end = 0
    for physical, raw in enumerate(rows, 1):
        end += len((raw + "\n").splitlines())
        if number <= end:
            return physical if number > 0 else None
    return None


def legacy_cursor(rows: Sequence[str], count: int) -> int:
    """Translate a consumed legacy prefix, leaving incomplete rows unread.

    Old cursors end at physical boundaries. If a damaged cursor ends inside
    a row, keep that row unread. Preserve overrun on a truncated file rather
    than silently rewinding the cursor to its current end.
    """
    end = 0
    for physical, raw in enumerate(rows):
        end += len((raw + "\n").splitlines())
        if end > count:
            return physical
    return len(rows) + max(0, count - end)
