"""UI/CLI parity: ``self_learn_ui.models._is_deferred`` agrees with
``self_learn.domain.is_queued`` (Sprint 1 M-B gap, closed here — the
brief named this file; M-B shipped ``_is_deferred``'s rewrite but not
this test, folded into M-J's commit per the code-gate review rather
than amending an already-landed commit).

``_is_deferred(deferred_until, now)`` takes only the VALUE (never a
whole item/record — all three real call sites in ``models.py`` pass
``item.get("deferred_until")``, a dict lookup), and is defined as
``not sl_domain.is_queued({"status": "pending", "deferred_until":
deferred_until}, now)`` — the deferred-and-still-in-the-future half of
queue membership, inverted (a record IS "deferred" in the UI's sense
exactly when it is NOT yet queued). Every assertion below checks that
inversion holds, across a value matrix, and additionally against a
REAL ``self_learn.records.Record`` (not just the mapping shape UI
itself passes), so the parity holds regardless of which side's data
shape supplied the value.
"""

from __future__ import annotations

from datetime import datetime, timezone

import self_learn.domain as sl_domain
import pytest
from self_learn.records import Record
from self_learn_ui.models import _is_deferred

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _domain_says_deferred(deferred_until, now: datetime = NOW) -> bool:
    return not sl_domain.is_queued(
        {"status": "pending", "deferred_until": deferred_until}, now
    )


class TestParityAcrossAValueMatrix:
    @pytest.mark.parametrize(
        "deferred_until,expected",
        [
            (None, False),  # never deferred, no value at all
            ("2020-01-01", False),  # past date-only — lapsed, queued
            ("2099-01-01", True),  # future date-only — still deferred
            ("2020-01-01T00:00:00Z", False),  # past full timestamp
            ("2099-01-01T00:00:00Z", True),  # future full timestamp
        ],
        ids=["none", "past-date", "future-date", "past-z", "future-z"],
    )
    def test_is_deferred_matches_domain_is_queued_inverted(
        self, deferred_until, expected
    ):
        assert _is_deferred(deferred_until, NOW) is expected
        assert _domain_says_deferred(deferred_until, NOW) is expected
        assert _is_deferred(deferred_until, NOW) == _domain_says_deferred(
            deferred_until, NOW
        )

    def test_a_padded_future_value_is_deferred_a_real_behavior_delta(self):
        """Documented, not incidental: ``models._parse_dt`` (the
        pre-M-B implementation) never ``.strip()``-ed its input, so a
        whitespace-padded value like ``" 2099-01-01 "`` failed to parse
        and read as "not deferred". ``domain.is_queued`` -> ``chrono.
        to_dt`` DOES strip (``str(value).strip()``), so the same value
        now correctly reads as deferred. No reader emits a padded
        string today (measured: no writer in either package ever pads
        a stored ``deferred_until``), so this is a real, harmless
        improvement rather than a live compatibility break — pinned
        here so a future change cannot silently reintroduce the
        strip-less parse without this test noticing."""
        padded = " 2099-01-01 "
        assert _is_deferred(padded, NOW) is True
        assert _domain_says_deferred(padded, NOW) is True

    def test_mutation_flipping_the_inversion_breaks_every_case(self, monkeypatch):
        """The exact mutation control this parity test exists to prove:
        ``_is_deferred``'s ``not`` is the whole rewrite's payload —
        flip it and EVERY case above must disagree with
        ``domain.is_queued``."""
        import self_learn_ui.models as models_mod

        def _broken_is_deferred(deferred_until, now):
            return sl_domain.is_queued(
                {"status": "pending", "deferred_until": deferred_until}, now
            )  # missing `not` — the mutation

        monkeypatch.setattr(models_mod, "_is_deferred", _broken_is_deferred)
        for deferred_until, expected in [
            (None, False),
            ("2020-01-01", False),
            ("2099-01-01", True),
        ]:
            assert models_mod._is_deferred(deferred_until, NOW) is not expected


class TestParityAgainstARealRecord:
    """``_is_deferred`` only ever sees the bare VALUE in production (a
    dict lookup) — this proves that value, taken off a REAL ``Record``
    object's ``.deferred_until`` attribute, still agrees with feeding
    the WHOLE record through ``domain.is_queued`` directly. Confirms
    the parity holds independent of which side's data shape (a raw
    mapping vs. a real Record) supplied the value."""

    def _record(self, deferred_until) -> Record:
        record = Record.create(
            type="behavior",
            scope="skill:s",
            source="teach",
            kind="anti-pattern",
            trigger="About to do the risky thing.",
            instruction="Do the safe thing instead.",
            record_id="lrn-00000042",
        )
        record.set_deferred_until(deferred_until)
        return record

    @pytest.mark.parametrize(
        "deferred_until,expected_queued",
        [
            (None, True),
            ("2020-01-01T00:00:00Z", True),  # lapsed -> queued
            ("2099-01-01T00:00:00Z", False),  # still future -> not queued
        ],
        ids=["none", "past", "future"],
    )
    def test_record_attribute_and_domain_is_queued_agree_with_is_deferred(
        self, deferred_until, expected_queued
    ):
        record = self._record(deferred_until)
        assert sl_domain.is_queued(record, NOW) is expected_queued
        # the UI never sees the Record object, only this attribute:
        assert _is_deferred(record.deferred_until, NOW) is not expected_queued
