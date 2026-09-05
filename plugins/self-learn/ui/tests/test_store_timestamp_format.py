"""M-J fold r2, MINOR-2: ``store.py``'s ``_now_iso`` migration (adopting
the shared ``primitives.chrono`` format -- second precision,
``Z``-suffixed, no microseconds/offset) changed the ON-DISK shape of
every timestamp ``store.py`` writes. The original M-J build's reader
check was scoped to the wrong module -- ``store.py`` itself, which
never re-parses its own timestamps (confirmed by its own docstring:
``created_at``/``updated_at`` are "opaque display strings here, never
re-parsed by this module"). The REAL reader is ``pane.py``'s
``_relative_time``, called against ``StoredSnapshot.updated_at``
(``pane.py:896,993``) -- found by tracing every consumer of the field
across the UI package (grepped ``.created_at``/``.updated_at`` and
``StoredBlock``/``StoredSnapshot`` usage; the CLI never reads a UI
store file at all -- confirmed, no import of ``self_learn_ui`` appears
anywhere under ``cli/src``, only in docstrings/comments naming it).

Deliberately NOT ``test_store.py``: that file belongs to another lane
this fold (only owned/new test files may gain tests) -- a new file
instead.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from self_learn_ui.pane import _relative_time
from self_learn_ui.store import PaneTranscriptStore

#: The one shape store.py's migrated ``_now_iso`` produces (mirrors
#: ``primitives.chrono.ISO_FORMAT`` byte-for-byte -- no cross-package
#: import here on purpose: this test pins the OUTPUT SHAPE store.py
#: commits to, not the CLI's source of truth for it).
_SECOND_PRECISION_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _store(tmp_path: Path) -> PaneTranscriptStore:
    return PaneTranscriptStore(tmp_path / "panes")


class TestWriterShape:
    def test_persisted_updated_at_is_second_precision_z_suffixed(self, tmp_path):
        s = _store(tmp_path)
        s.start_new(
            "lrn-aa000001",
            record_id_or_bucket="lrn-aa000001",
            bucket_dir=str(tmp_path / "bucket"),
        )
        snap = s.read_snapshot("lrn-aa000001")
        assert snap is not None
        assert _SECOND_PRECISION_Z.match(snap.updated_at), snap.updated_at

    def test_mutation_reverting_to_isoformat_would_fail_the_shape_check(self):
        """Positive control: the OLD store.py ``_now_iso`` body
        (``datetime.now(timezone.utc).isoformat()``) produces
        microseconds plus a ``+00:00`` offset, never a bare ``Z`` --
        proving the shape regex above is not vacuous."""
        old_shape = datetime.now(timezone.utc).isoformat()
        assert not _SECOND_PRECISION_Z.match(old_shape)


class TestReaderAcceptsBothShapes:
    """``pane._relative_time`` is the actual reader (found by tracing
    every consumer of ``StoredSnapshot.updated_at``, not assumed) --
    it must accept the NEW shape (what every timestamp written from
    now on looks like) AND the OLD shape (what a store file persisted
    BEFORE this migration still looks like on disk -- existing files
    are never rewritten retroactively)."""

    def test_accepts_the_new_second_precision_z_suffixed_shape(self):
        new_shape = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _relative_time(new_shape)
        assert result is not None
        assert result == "just now" or result.endswith(("m ago", "h ago", "d ago"))

    def test_accepts_the_old_isoformat_shape_from_pre_migration_files(self):
        """A file persisted BEFORE this migration still carries this
        exact shape on disk -- never rewritten retroactively -- so the
        reader must keep accepting it going forward, not just the new
        shape."""
        old_shape = datetime.now(timezone.utc).isoformat()  # microseconds + +00:00
        result = _relative_time(old_shape)
        assert result is not None

    def test_accepts_a_real_persisted_value_end_to_end(self, tmp_path):
        s = _store(tmp_path)
        s.start_new(
            "lrn-aa000002",
            record_id_or_bucket="lrn-aa000002",
            bucket_dir=str(tmp_path / "bucket"),
        )
        snap = s.read_snapshot("lrn-aa000002")
        assert snap is not None
        assert _relative_time(snap.updated_at) == "just now"

    def test_none_and_empty_are_still_handled(self):
        """Unrelated to the format migration, but the same function --
        confirms the None-guard wasn't disturbed by anything here."""
        assert _relative_time(None) is None
        assert _relative_time("") is None
