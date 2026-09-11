"""S3 ITEM 2 — `procs.run_bounded(binary=...)`, the byte-exact seam.

`run_bounded`'s existing contract (pass-through, `check=True`, the
whole-process-group kill on timeout) is proven in
`test_bounded_children.py` and untouched by this move. This file covers
only what `binary=` adds: `text_mode = not isinstance(input, (bytes,
bytearray))` (`procs.py`, pre-`binary=`) can never produce bytes output
for a caller that passes no `input` — e.g. `intents._head_show`'s
`git show HEAD:<relpath>`, which needs the child's raw stdout bytes for
a sha256 compare and must never let a text codec touch them. `binary=`
forces bytes regardless of `input`, and the child's whole process group
still dies on timeout in that mode too — not some narrower binary-only
path.

Mutation-verified per this repo's own review bar: every assertion below
that could pass by construction has a paired control proving it would
have failed against the pre-`binary=` behavior.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from self_learn import intents
from self_learn.primitives import procs
from support import commit_all, init_repo

_RAW_NON_UTF8 = b"\xff\xfe\x00\x01\xfd"


def test_binary_true_returns_bytes_stdout_even_with_no_input():
    result = procs.run_bounded(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'hi')"],
        timeout=10,
        binary=True,
    )
    assert isinstance(result.stdout, bytes)
    assert result.stdout == b"hi"


def test_positive_control_binary_false_default_returns_str_stdout_with_no_input():
    """Proves the assertion above is discriminating (bytes vs. str), not
    vacuously true because `run_bounded` always returns bytes."""
    result = procs.run_bounded([sys.executable, "-c", "print('hi')"], timeout=10)
    assert isinstance(result.stdout, str)


def test_binary_true_with_str_input_raises_valueerror_naming_binary():
    """Fold r1 MINOR-1: `binary=True` forces bytes I/O — a `str` `input`
    under it used to reach `Popen`/`communicate` and blow up on a raw
    stdlib `TypeError` out of `memoryview` (text can't be written to a
    binary-mode stdin pipe). Failing loudly, and by name, at the top of
    `run_bounded` beats that. Positive control in the same test: the
    guard is scoped to `str` specifically, not to `input` being
    non-`None` in general — the same call with `bytes` `input` still
    works."""
    with pytest.raises(ValueError, match="binary"):
        procs.run_bounded(
            [sys.executable, "-c", "pass"], timeout=10, binary=True, input="a str"
        )

    result = procs.run_bounded(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
        timeout=10,
        binary=True,
        input=b"x",
    )
    assert result.stdout == b"x"


def test_byte_exact_git_show_of_a_non_utf8_blob(tmp_path):
    """The acceptance criterion this move exists for: a committed blob
    whose bytes are not valid UTF-8 (a plausible real git object —
    `_head_show` exists precisely because compiled/binary content can
    land in the ledger) comes back byte-for-byte through `binary=True`."""
    repo = tmp_path / "repo"
    init_repo(repo)
    blob = repo / "binary.dat"
    blob.write_bytes(_RAW_NON_UTF8)
    commit_all(repo, "seed non-utf8 blob")

    result = procs.run_bounded(
        ["git", "-C", str(repo), "show", "HEAD:binary.dat"],
        timeout=10,
        binary=True,
    )
    assert result.stdout == _RAW_NON_UTF8


def test_mutation_control_forcing_text_mode_breaks_on_the_same_blob(tmp_path):
    """Mutation control: reverting to the pre-`binary=` inference (text
    mode, since there is no `input`) against the SAME non-UTF-8 content
    breaks — proven empirically here, not asserted in the abstract —
    which is exactly the gap `binary=True` above closes."""
    repo = tmp_path / "repo"
    init_repo(repo)
    blob = repo / "binary.dat"
    blob.write_bytes(_RAW_NON_UTF8)
    commit_all(repo, "seed non-utf8 blob")

    with pytest.raises(UnicodeDecodeError):
        procs.run_bounded(
            ["git", "-C", str(repo), "show", "HEAD:binary.dat"], timeout=10
        )


def test_intents_head_show_itself_returns_exact_bytes_for_a_non_utf8_blob(tmp_path):
    """The acceptance criterion as stated (assess-robustness-followups.md
    §ITEM 2, 2c-1): not `run_bounded` in isolation (the test above already
    covers that) but the actual CALLER this seam exists for —
    `intents._head_show` — against the same non-UTF-8 content. Mutation
    verified by hand while building this lane: dropping `binary=True` from
    `_head_show`'s call reddens this test with `UnicodeDecodeError` (the
    same failure `test_mutation_control_forcing_text_mode_breaks_on_the_
    same_blob` proves at the primitive level); reverted by inverse edit,
    `sha256sum` matched the pre-mutation hash of `intents.py` exactly, then
    re-ran green — see the build report for the recorded hashes."""
    repo = tmp_path / "repo"
    init_repo(repo)
    blob = repo / "binary.dat"
    blob.write_bytes(_RAW_NON_UTF8)
    commit_all(repo, "seed non-utf8 blob")

    assert intents._head_show(repo, "binary.dat") == _RAW_NON_UTF8


def _proc_is_dead(pid: int) -> bool:
    """Absent, or a zombie, both mean dead — `os.kill(pid, 0)` alone is
    NOT enough: if this test process (or pytest) is a subreaper, a
    killed grandchild becomes ITS zombie and `kill(pid, 0)` keeps
    succeeding until someone waits on it. Mirrors
    `test_bounded_children.py`'s own helper of the same name."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return True
    state = stat.rsplit(")", 1)[1].split()[0]
    return state == "Z"


_SPAWNS_A_GRANDCHILD_SCRIPT = """
import signal, subprocess, sys, time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
grandchild = subprocess.Popen(
    [sys.executable, "-c",
     "import signal, time\\n"
     "signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n"
     "time.sleep(60)\\n"],
)
with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write(str(grandchild.pid))
    f.flush()
time.sleep(60)
"""


def test_timeout_kills_the_whole_process_group_in_binary_mode_too(tmp_path):
    """Acceptance criterion 2: a wedged child (the shape `_head_show` is
    now exposed to, since it routes through `run_bounded`) whose
    grandchild outlives a plain `proc.kill()` still dies under
    `os.killpg` when `binary=True` — the kill path is not gated on
    `text_mode`. Same construction as
    `test_bounded_children.py::test_timeout_kills_the_whole_process_
    group_a_grandchild_dies_too`, with `binary=True` added; mutation
    verified by hand (dropping the `killpg` leg in `procs.py` while
    building this lane left the grandchild alive past the timeout — see
    the build report)."""
    pidfile = tmp_path / "gpid.txt"
    script = tmp_path / "child.py"
    script.write_text(_SPAWNS_A_GRANDCHILD_SCRIPT, encoding="utf-8")

    with pytest.raises(procs.BoundedTimeout):
        procs.run_bounded(
            [sys.executable, str(script), str(pidfile)], timeout=1.5, binary=True
        )

    deadline = time.monotonic() + 10
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pidfile.exists(), "the child never got to spawn+record its grandchild"
    gpid = int(pidfile.read_text(encoding="utf-8").strip())

    deadline = time.monotonic() + 10
    dead = False
    while time.monotonic() < deadline:
        if _proc_is_dead(gpid):
            dead = True
            break
        time.sleep(0.05)
    assert dead, (
        f"grandchild pid {gpid} was still alive after run_bounded's timeout — "
        "killing only the immediate child leaves orphaned descendants running, "
        "even in binary mode"
    )
