"""FW-53: :func:`existing_origins`' decode-safety parity between a
`RecordError` (malformed frontmatter) and a `UnicodeDecodeError` (bad
bytes) — both are "unparseable", and the module's own docstring commits
to a raw-text regex fallback for either rather than losing the dedupe key
or crashing the caller. This is the sweep's THIRD site (after
`_ledger_index`/`_canon_index`): `existing_origins` sits at the very top
of the miner's `_reconcile_and_land`, called on every productive run.
"""

from pathlib import Path

from self_learn.import_common import existing_origins
from support import make_behavior, make_home


def _pending_path(home: Path, record_id: str) -> Path:
    d = home / "skills" / "s" / "pending"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{record_id}.md"


def test_undecodable_record_does_not_crash_and_still_yields_its_origin(tmp_path):
    home = make_home(tmp_path)
    record = make_behavior(record_id="lrn-0badbeef")
    record.append_evidence({"session": "sess-x", "ts": "2026-01-01T00:00:00Z",
                             "origin": "transcript:sess-x#L1"})
    path = _pending_path(home, record.id)
    record.write(path)
    # Corrupt the file AFTER writing valid content: a torn trailing write
    # (crash mid-append) is exactly the shape a real corruption takes —
    # the origin line stays intact, only the tail is garbage.
    good_bytes = path.read_bytes()
    path.write_bytes(good_bytes + b"\xff\xfe garbage tail, not UTF-8\n")

    origins = existing_origins(home)  # must not raise UnicodeDecodeError

    assert "transcript:sess-x#L1" in origins


def test_undecodable_record_never_crashes_alongside_a_good_record(tmp_path):
    """The dedupe sweep must not lose a REAL record's origin just because
    a DIFFERENT file in the same sweep is corrupt (skip one, keep going)."""
    home = make_home(tmp_path)
    good = make_behavior(record_id="lrn-00009999")
    good.append_evidence({"session": "sess-good", "ts": "2026-01-01T00:00:00Z",
                           "origin": "transcript:sess-good#L1"})
    good.write(_pending_path(home, good.id))

    _pending_path(home, "lrn-0badbeef").write_bytes(
        b"---\ntype: behavior\nid: lrn-0badbeef\n---\n\xff\xfe garbage\n"
    )

    origins = existing_origins(home)

    assert "transcript:sess-good#L1" in origins
