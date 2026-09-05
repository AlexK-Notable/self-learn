"""primitives.truncate -- ONE "keep the newest bytes" log truncator
(Sprint 1 M-J, plan v2 SS2 M-J).

``worker.py``'s ``_truncate_oldest`` and the UI's ``uilog.py`` carried
byte-identical copies of this function (the UI's own docstring already
names the rule this violates: "IMPORT, never shell or reimplement" --
this was the one reimplementation that rule had not yet caught). One
copy here; both call sites keep their own names as thin facades
(``worker._truncate_oldest`` is additionally STRUCTURALLY required to
keep that exact name -- ``tests/test_lock_invariant.py`` enumerates it
by name in its ``NOT_REPO_TRUTH`` exemption table)."""

from __future__ import annotations

from pathlib import Path


def truncate_oldest(path: Path, cap: int) -> None:
    """If *path* exceeds *cap* bytes, drop whole lines from the START
    until it fits, keeping the newest content (a log's most recent
    lines matter more than its oldest). Silent on any ``OSError`` -- a
    log a caller cannot read/write must never fail the operation it is
    merely recording."""
    try:
        if path.stat().st_size <= cap:
            return
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        keep: list[str] = []
        size = 0
        for line in reversed(lines):
            size += len(line.encode("utf-8"))
            if size > cap:
                break
            keep.append(line)
        path.write_text("".join(reversed(keep)), encoding="utf-8")
    except OSError:
        pass
