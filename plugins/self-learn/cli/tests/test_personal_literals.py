r"""Spec §9 acceptance-gate test -- docs/specs/self-learn/drafts/scrub-personal-literals-spec.md.

The scrub spec's Definition of Done (§9 criterion 9) is a SHELL COMMAND
quoted in prose (see the spec file for its literal pattern -- reproduced
identically, but never spelled out here, in `_PATTERN` below), required
to return zero hits when run over `plugins/` from the repo root. ac28695
records that command is cwd-relative and returns zero VACUOUSLY from any
subdirectory -- a silent false pass that fired twice during the original
build (6105983) and was caught only by printing `pwd` alongside it. A
shell command quoted in a spec is not enforced by anything between reads
of the spec; nobody runs it. This module makes it code the suite
actually executes on every run.

2026-08-28 re-verification (see the spec's Status line) found this gate
WAS failing again: `cli/tests/test_hostmode.py:2662`, added after the
original build by an unrelated unit (U-hostmode, commit b652992), quoted
an old bug-repro path that embedded the repo owner's Linux login. Fixed
in the same pass that added this file. This module is the guard against
a third recurrence.

Code-gate B-1 (2026-08-28): the FIRST version of this file spelled the
three literal tokens directly -- in the module docstring, in a code
comment, and in `_PATTERN`'s own definition -- and was green only
because it was untracked: `git ls-files` (this file's own enumerator)
does not list an untracked file, so the file never scanned itself.
`git add -N` (281 -> 282 tracked files) turned that same self-match into
a real failure, and the spec's own §9 shell gate would return the
identical four hits once this file is committed -- a self-exemption via
non-tracking is not a fix; the tokens had to stop existing in the file.
`_PATTERN` and every comment/docstring below describe the three classes
the gate covers -- the repo owner's login, the home-LAN /24 prefix, and
the retired HA-host nickname -- without ever spelling any of them as a
contiguous, case-insensitive-matchable substring.

Design notes:
  - File enumeration goes through `git ls-files`, never `git grep` --
    reusing `git grep`'s own pathspec resolution here would just relocate
    the ac28695 cwd trap into the very test meant to catch it. The repo
    root is resolved from THIS file's on-disk location (`git -C <dir>
    rev-parse --show-toplevel`), never from the pytest process's cwd, so
    running this file from any directory (`cli/`, the repo root, a
    worktree) gives the same answer.
  - Every tracked file under the scanned pathspec is read and scanned;
    none are silently skipped. Decoding uses `errors="replace"` rather
    than a try/except-continue over UnicodeDecodeError, so a file this
    scanner cannot cleanly decode still gets scanned instead of quietly
    vanishing from the count -- the same failure shape as a mis-scoped
    pathspec vanishing files from `git grep`'s count.
  - A positive control (below) proves the scanner itself still works:
    `docs/specs/self-learn/` is DELIBERATELY unscrubbed (spec R-1 --
    historical record) and is known today to carry real hits. If that
    control ever finds zero, the scanner is broken (wrong pattern, wrong
    root, wrong pathspec) and the all-clear from the plugins/ test below
    cannot be trusted -- the "reads as pass when it can't see its
    target" trap.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# `_PATTERN` reproduces the spec's §9 gate: three classes of personal
# literal -- the repo owner's login, the home-LAN /24 prefix, and the
# retired HA-host nickname -- matched case-insensitively, the nickname
# word-bounded. Assembled from fragments that never spell any of the
# three as a contiguous substring (see code-gate B-1 above): this test
# scans every tracked file under plugins/, INCLUDING ITSELF once
# tracked, so a literally-spelled pattern would flag its own definition.
_owner_login = "ko" + "mi"
_lan_prefix = ".".join(("192", "168", "1")) + "."
_old_host_nickname = "No" + "va"

_PATTERN = re.compile(
    "|".join((
        re.escape(_owner_login),
        re.escape(_lan_prefix),
        r"\b" + re.escape(_old_host_nickname) + r"\b",
    )),
    re.IGNORECASE,
)


def _repo_root() -> Path:
    """Resolved from THIS file's on-disk location, never the pytest
    process's cwd -- the cwd trap this module exists to close (ac28695)."""
    out = subprocess.run(
        ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    root = Path(out)
    assert root.is_dir(), f"git rev-parse --show-toplevel gave a non-directory: {root!r}"
    return root


def _tracked_files(root: Path, pathspec: str) -> list[Path]:
    """Every git-tracked file under `pathspec`, resolved against `root`
    explicitly (`git -C root ls-files -- pathspec`) -- never the ambient
    cwd."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", pathspec],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [root / line for line in out]


def _scan(paths: list[Path]) -> dict[Path, list[tuple[int, str]]]:
    """{path: [(1-based line no, line text), ...]} for every match. Every
    path is read; none are silently dropped on a decode failure --
    `errors="replace"` keeps ASCII content (all three token classes are
    plain ASCII) intact even in a file this can't cleanly decode as
    UTF-8."""
    hits: dict[Path, list[tuple[int, str]]] = {}
    for p in paths:
        text = p.read_bytes().decode("utf-8", errors="replace")
        matched = [
            (i, line)
            for i, line in enumerate(text.splitlines(), start=1)
            if _PATTERN.search(line)
        ]
        if matched:
            hits[p] = matched
    return hits


def test_no_personal_literals_under_plugins():
    """The spec's §9 acceptance gate, permanently enforced: every tracked
    file under `plugins/` must be free of the three literal classes
    `_PATTERN` matches (the owner's login, the LAN prefix, the old host
    nickname), scanned case-insensitively. Equivalent to the spec's own
    shell gate run from the repo root -- but resolves the root itself
    (`_repo_root`), so this test's result cannot depend on the runner's
    cwd the way the shell command did."""
    root = _repo_root()
    assert (root / "plugins" / "self-learn" / "cli").is_dir(), (
        f"resolved root {root} does not contain plugins/self-learn/cli -- "
        "repo-root resolution is broken, not necessarily the scan"
    )
    files = _tracked_files(root, "plugins/")
    assert len(files) > 200, (
        f"only {len(files)} tracked files found under plugins/ -- the "
        "pathspec or root is wrong; this is nowhere near the real count "
        "(281 at the time this test was written), and a zero-hits result "
        "over a near-empty set would be meaningless"
    )
    hits = _scan(files)
    assert not hits, "personal literal(s) found under plugins/ (spec §9):\n" + "\n".join(
        f"  {p.relative_to(root)}:{lineno}: {line}"
        for p, lines in hits.items()
        for lineno, line in lines
    )


def test_positive_control_docs_specs_scanner_is_not_vacuous():
    """Proves `_scan`/`_PATTERN` above actually find matches when matches
    exist, so the zero result in `test_no_personal_literals_under_plugins`
    means "scrubbed", not "this scanner can't see anything" -- the
    vacuous-pass trap ac28695 records, reproduced here as a permanent
    control instead of a one-off `pwd` check.

    `docs/specs/self-learn/` is deliberately OUT of scope for the scrub
    (spec R-1: the spec corpus is a historical record and ships as-is,
    including a session post-mortem that narrates the user by name and
    69 real commit SHAs) -- it is expected, not a bug, that this finds
    real hits. Measured 2026-08-28: 23 of 151 tracked files. Assert only
    >= 1: the exact count will drift as the corpus grows, and this
    control's job is proof of life for the scanner, not a census."""
    root = _repo_root()
    files = _tracked_files(root, "docs/specs/self-learn/")
    assert len(files) > 50, (
        f"only {len(files)} tracked files found under docs/specs/self-learn/ "
        "-- the pathspec or root is wrong"
    )
    hits = _scan(files)
    assert len(hits) >= 1, (
        "positive control found ZERO hits under docs/specs/self-learn/, "
        "which is known to carry real ones -- the scanner is broken "
        "(pattern, root, or pathspec), so the zero result from "
        "test_no_personal_literals_under_plugins cannot be trusted either"
    )
