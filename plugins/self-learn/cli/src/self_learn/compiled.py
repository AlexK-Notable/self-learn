"""U-hostmode §4.5/§4.5a: the compile record — a ledger-side integrity
instrument for one host TARGET's managed region, and the six-case
predicate that reads it.

**Why this exists** (§3.2/§3.3): the git-mode dirty gate
(``gitops.paths_dirty``) is per-FILE and structurally blind to a
COMMITTED hand edit inside the managed markers — ``git status`` reports
nothing, so the next regeneration silently destroys the edit. The compile
record is STRICTER for the region self-learn actually owns: it hashes the
managed/pointer/reference/script region itself, so a committed in-marker
edit hashes to a number matching neither the expectation nor the
"state this write was based on", and the predicate refuses.

**Location.** ``<home>/compiled/<slug>.yaml``, one file per host, written
for BOTH modes (REC4) — only the plain-host GATE differs by mode
(git hosts keep ``paths_dirty`` as their gate; the record is written
there too, and additionally refuses on an ``edited``/``unknown``
verdict, §4.5a's "real hazard on a git host as well").

**Shape**, per target key::

    host: /home/user/notes
    mode: plain
    targets:
      CLAUDE.md:
        region: managed
        sha256: 9f2c...            # the region THIS write leaves behind
        based_on_sha256: 41ab...   # the region OBSERVED at pre-flight;
                                    # null when it was absent (fresh/missing)
        bytes: 1590
        at: 2026-08-27T04:11:52Z
        by: route lrn-4f911239

**The predicate is six cases** (§4.5a) — read :func:`verdict_for`'s
docstring for the table. ``based_on_sha256`` is the OBSERVED pre-flight
hash, never the previous expectation (REC13/H-2: with the previous
expectation, two consecutive unlanded host-phase applies would verdict
``edited`` and both ``route`` and ``recompile`` would refuse to repair
their own stale output — a real defect this unit shipped once and pins a
mutation against, M47).

This module performs NO git operations and commits nothing — it only
computes hashes and writes/reads the record FILE. The caller (verbs.py)
decides when the write happens relative to a ledger commit (REC9: inside
the resolution's own commit, via ``_ledger_write`` / ``_commit_ledger``,
never a second one)."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .compilers import BEGIN_MARKER, END_MARKER, POINTER_BEGIN_MARKER, POINTER_END_MARKER
from .primitives import chrono, fsops, yamlio

__all__ = [
    "REGION_KINDS",
    "REFUSING_VERDICTS",
    "CompiledRecordError",
    "adopt_entry",
    "compiled_record_path",
    "entry_for",
    "load_record",
    "region_bytes",
    "region_key",
    "sha256_hex",
    "verdict_for",
    "write_entry",
]

#: §4.5: the four region kinds this record covers. ``paths:`` frontmatter
#: and new-skill scaffolds are deliberately OUT (§8 OUT-6/OUT-7) — they
#: already have their own agreement predicates.
REGION_KINDS = ("managed", "pointer", "reference", "script")

#: §4.5a: the two verdicts that CAN refuse a route/recompile — but
#: whether ``unknown`` actually does is MODE-scoped (see :func:`refuses`):
#: on a git host, an as-yet-untracked-by-the-record but COMMITTED region
#: is not inherently suspicious (git's own history is its provenance,
#: and ``gitops.paths_dirty`` already refuses an UNCOMMITTED one) — only
#: a plain host, which has no other trust source, treats "no record yet,
#: content already present" as a hazard worth naming.
REFUSING_VERDICTS = ("edited", "unknown")


def refuses(verdict: str, mode: str) -> bool:
    """Whether *verdict* should REFUSE a route/recompile for a host in
    *mode*, per REC5's table — six verdicts (:func:`verdict_for`), mode-
    scoped in exactly two places:

    ``"edited"`` (region matches neither the record's expectation nor
    its prior observation) always refuses, in EITHER mode — REC2/REC4:
    the record is the only instrument that sees a committed in-marker
    hand edit, a real hazard on a git host too.

    ``"unknown"`` (no record at all yet, region already present — REC5
    row 2) is mode-split. It does NOT refuse in GIT mode: git's own
    commit history is that content's provenance, and an uncommitted
    foreign version is already caught by `_abort_if_dirty` — refusing on
    first contact there would regress every registered git host's first
    post-upgrade route, the opposite of MODE1/UN1's byte-identical
    promise. It DOES refuse in PLAIN mode (code gate r1 B-1) — a plain
    host has no OTHER trust source, so "no record, content already
    present" is a real hazard, not a benign artifact (closes the hole
    where two different ledger homes routing the SAME physical plain
    target could both silently succeed, the second overwriting bytes the
    first's record never accounted for — `TestB1Rec5RowTwoUnknownRefuses
    PlainMode`, `test_hostmode.py`).

    THIS function's contract stops there — a caller may still avoid ever
    reaching a `True` return for "unknown" in plain mode: code gate r2
    M-3 gives REC5 a seventh row, checked by the CALLER
    (`verbs._abort_if_region_unsound`) BEFORE it consults this function
    at all — when the on-disk region is byte-for-byte what self-learn's
    own compiler currently renders for that target (the ordinary shape
    of every host routed to before compile records existed), the caller
    ADOPTS instead of asking `refuses` to gate anything: one notice
    line, the record entry gets written by that same call, no refusal
    ever happens. Only a genuine byte MISMATCH — foreign content, not
    merely a missing receipt — reaches `refuses("unknown", "plain")` at
    all, and `recompile --adopt` remains the named repair for exactly
    that case."""
    return verdict == "edited" or (verdict == "unknown" and mode == "plain")


class CompiledRecordError(Exception):
    """compiled/<slug>.yaml is malformed, or a region's markers are
    broken (mirrors ``compilers.CompileError``'s shape; kept as a
    separate class so this module has no import-time dependency the
    other direction — ``compilers.py`` is explicitly untouchable, §9)."""


def compiled_record_path(home: Path | str, slug: str) -> Path:
    return Path(home) / "compiled" / f"{slug}.yaml"


def _yaml() -> YAML:
    return yamlio.rt_yaml(default_flow_style=False)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now_iso() -> str:
    return chrono.now_iso()


def region_bytes(text: str, kind: str) -> bytes | None:
    """The region substring for *kind*, as UTF-8 bytes exactly as they
    would be written — or ``None`` when the region is ABSENT (no marker
    pair found; the caller reads ``None`` as "missing" in the predicate).
    ``kind in ("reference", "script")`` has no markers: the region IS the
    whole file, so the caller passes the whole text and gets it back
    encoded, never ``None`` (a missing reference/script FILE is instead
    represented by the caller never calling this — see ``verdict_for``'s
    ``observed_hash=None`` path, driven by the file's own existence).

    Raises :class:`CompiledRecordError` on a malformed marker pair — same
    shape ``compilers.compile_managed_text`` itself raises for, kept as a
    distinct exception type so this module never imports the other
    direction."""
    if kind == "managed":
        begin, end = BEGIN_MARKER, END_MARKER
    elif kind == "pointer":
        begin, end = POINTER_BEGIN_MARKER, POINTER_END_MARKER
    elif kind in ("reference", "script"):
        return text.encode("utf-8")
    else:
        raise CompiledRecordError(f"unknown region kind {kind!r}")
    begins = text.count(begin)
    ends = text.count(end)
    if begins == 0 and ends == 0:
        return None
    if begins == 1 and ends == 1:
        begin_at = text.index(begin)
        end_at = text.index(end)
        if end_at < begin_at:
            raise CompiledRecordError(
                f"broken {kind} markers: end marker precedes begin marker"
            )
        return text[begin_at : end_at + len(end)].encode("utf-8")
    raise CompiledRecordError(
        f"broken {kind} markers: expected exactly one begin/end pair, "
        f"found {begins} begin / {ends} end"
    )


def region_key(host_path: Path | str, target: Path) -> str:
    """The record's per-target key: the path relative to the host when
    the target sits inside it (the common case — matches §4.5's own
    example, ``CLAUDE.md:``), else the resolved absolute path (a
    reference target may live under a ``refs_dir`` the "host" concept
    does not directly contain)."""
    try:
        return str(Path(target).resolve().relative_to(Path(host_path).resolve()))
    except ValueError:
        return str(Path(target).resolve())


def load_record(home: Path | str, slug: str) -> dict:
    """Parse ``<home>/compiled/<slug>.yaml`` — ``{}`` when absent, never
    an error (a host with no record yet is the ordinary "fresh" case)."""
    path = compiled_record_path(home, slug)
    if not path.is_file():
        return {}
    try:
        data = _yaml().load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        raise CompiledRecordError(f"unparseable {path}: {exc}") from exc
    return dict(data) if data else {}


def entry_for(record_data: dict, key: str) -> dict | None:
    targets = record_data.get("targets") or {}
    entry = targets.get(key)
    return dict(entry) if entry else None


def verdict_for(entry: dict | None, observed_hash: str | None) -> str:
    """§4.5a's six-case predicate, exactly:

    | entry    | region on disk | verdict            |
    |----------|-----------------|--------------------|
    | absent   | absent          | ``fresh``          |
    | absent   | present         | ``unknown``         (REFUSE)
    | present  | == sha256       | ``clean``          |
    | present  | absent          | ``missing``        |
    | present  | == based_on     | ``stale``          |
    | present  | matches neither | ``edited``          (REFUSE)

    ``entry`` is this target's stored entry (``None`` = "entry absent");
    ``observed_hash`` is the region's sha256 as OBSERVED ON DISK right
    now (``None`` = "region absent"). Refusing verdicts are named in
    :data:`REFUSING_VERDICTS`."""
    if entry is None:
        return "fresh" if observed_hash is None else "unknown"
    if observed_hash is None:
        return "missing"
    if observed_hash == entry.get("sha256"):
        return "clean"
    if entry.get("based_on_sha256") is not None and observed_hash == entry.get("based_on_sha256"):
        return "stale"
    return "edited"


def write_entry(
    home: Path | str,
    slug: str,
    key: str,
    *,
    region: str,
    sha256: str,
    based_on_sha256: str | None,
    nbytes: int,
    by: str,
    host: str,
    mode: str,
) -> Path:
    """Update ``<home>/compiled/<slug>.yaml``'s ``targets[key]`` entry and
    WRITE the file to disk. Commits NOTHING — the caller stages/commits
    this path as part of ITS OWN ledger commit (REC9). ``ruamel`` round
    trip (``typ="rt"``, the discipline ``records.py``/``hosts._yaml()``
    already use) preserves any foreign key a human or a future unit adds
    to this file (REC8)."""
    path = compiled_record_path(home, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    y = _yaml()
    if path.is_file():
        data = y.load(path.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    data["host"] = host
    data["mode"] = mode
    targets = data.get("targets")
    if targets is None:
        targets = {}
        data["targets"] = targets
    targets[key] = {
        "region": region,
        "sha256": sha256,
        "based_on_sha256": based_on_sha256,
        "bytes": nbytes,
        "at": _now_iso(),
        "by": by,
    }
    buf = io.StringIO()
    y.dump(data, buf)
    # Sprint 2 M-I (D6): the compiled-record class -- atomic + fsync'd,
    # symlinks refused.
    fsops.atomic_write(path, buf.getvalue(), preserve_mode=True, fsync=True)
    return path


def delete_entry(home: Path | str, slug: str, key: str) -> Path | None:
    """The removal twin of :func:`write_entry` (U-hostmode gate r1 fold,
    D-3 completion): drop ``targets[key]`` entirely when the region it
    described no longer exists — a hook script just removed, or any
    other region a verb's own write leaves genuinely ABSENT. A stale
    entry left behind for a key that no longer resolves to anything
    would misread as ``edited`` (REC5's "entry present + region absent"
    row) the next time ANYTHING checks this key, refusing a legitimate
    future write over content that is not a hand edit at all — it is
    simply gone, on purpose. Deleting the entry instead leaves the next
    check reading ``unknown``/``fresh`` off a clean slate.

    ``None`` (no-op, nothing written) when the record file does not
    exist yet, or the key was never in it — both are already the state
    this call is trying to reach, so there is nothing to change on
    disk."""
    path = compiled_record_path(home, slug)
    if not path.is_file():
        return None
    y = _yaml()
    data = y.load(path.read_text(encoding="utf-8")) or {}
    targets = data.get("targets") or {}
    if key not in targets:
        return None
    del targets[key]
    buf = io.StringIO()
    y.dump(data, buf)
    fsops.atomic_write(path, buf.getvalue(), preserve_mode=True, fsync=True)
    return path


def adopt_entry(
    home: Path | str,
    slug: str,
    key: str,
    *,
    region: str,
    observed_hash: str,
    nbytes: int,
    host: str,
    mode: str,
) -> Path:
    """``recompile --adopt`` (§4.5a): re-record the ON-DISK region as
    authoritative — ``sha256`` AND ``based_on_sha256`` both become the
    observed hash, clearing an ``edited``/``unknown`` refusal. The one
    human decision the refusal names; ``--force`` is deliberately absent
    (REC11)."""
    return write_entry(
        home,
        slug,
        key,
        region=region,
        sha256=observed_hash,
        based_on_sha256=observed_hash,
        nbytes=nbytes,
        by="recompile --adopt",
        host=host,
        mode=mode,
    )
