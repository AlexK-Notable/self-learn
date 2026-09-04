"""tests/test_domain.py -- self_learn.domain (Sprint 1 M-B, plan v2 §2):

- the three predicates (``is_queued``, ``is_canon_live``,
  ``record_age_days``) against Record AND mapping inputs;
- the cross-surface fixture: one expired deferral, aged 40 days, counted
  and aged IDENTICALLY by ``status --json``, ``list --json``,
  ``report --json`` and ``status --json --fast`` (closes A1/A2/B-3: a
  literal ``record.status == "pending"`` check used to undercount an
  expired-but-still-``deferred`` record against every queue-based
  surface — measured live, before this module existed, as
  ``metrics.pending_total == 9`` next to ``total_pending == 10`` in the
  SAME ``status --json`` payload);
- the consumer-dependency scan (every migrated consumer imports
  ``domain``, never a second inline definition of one of its three
  questions);
- the ``.days``-after-a-bare-subtraction scan (A1's exact shape), with a
  positive control proving the detector is not vacuous;
- the import-cycle check: ``domain`` depends on nothing but ``records``
  and ``primitives.chrono`` — not ``ledger_ops``, not ``compilers``, not
  ``report``.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import cli, domain, report
from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import create_record, find_record_path, is_unanalyzed, queue
from self_learn.records import Record
from support import days_ago, force_past_deferred, iso, make_behavior, make_env, make_home

CLI_SRC = Path(__file__).resolve().parent.parent / "src" / "self_learn"
UI_SRC = Path(__file__).resolve().parent.parent.parent / "ui" / "src" / "self_learn_ui"


def _all_source_files() -> list[Path]:
    """M-B fold r1, MINOR-1: a full walk of both trees' SOURCE (not
    test) directories, used by both the widened ``.days`` scan and the
    new canon-live-shape scan below -- a file-list-scoped parametrize
    (naming only the modules the brief already knew about) is exactly
    the blind-spot class M-J fold r1's facade scan was already caught
    making. Measured before adopting this (2026-09, this fold): zero
    ``.days``-after-subtraction hits anywhere in either tree today, so
    no allowlist is needed for that scan."""
    return sorted(CLI_SRC.rglob("*.py")) + sorted(UI_SRC.rglob("*.py"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


# ------------------------------------------------------------- is_queued


class TestIsQueued:
    def test_fresh_pending_record_is_queued(self):
        now = datetime.now(timezone.utc)
        record = make_behavior(record_id="lrn-aa000001", created_at=days_ago(1))
        assert domain.is_queued(record, now) is True

    def test_future_deferred_record_is_not_queued(self):
        now = datetime.now(timezone.utc)
        record = make_behavior(record_id="lrn-aa000002", created_at=days_ago(1))
        record.set_status("deferred")
        record.set_deferred_until("2099-01-01")
        assert domain.is_queued(record, now) is False

    def test_expired_deferred_record_is_queued(self):
        # THE fix's core claim: a lapsed deferral is queued even though
        # ``status`` still literally says "deferred" — membership is
        # computed, never read off the status string (02 §2).
        now = datetime.now(timezone.utc)
        record = make_behavior(record_id="lrn-aa000003", created_at=days_ago(40))
        record.set_status("deferred")
        record.set_deferred_until("2020-01-01")
        assert domain.is_queued(record, now) is True

    def test_resolved_status_record_is_not_queued(self):
        now = datetime.now(timezone.utc)
        record = make_behavior(record_id="lrn-aa000004", created_at=days_ago(1))
        record.set_status("rejected")
        assert domain.is_queued(record, now) is False

    def test_mapping_form_expired_deferral_matches_record_form(self):
        """``worker.fast_status`` never loads a full Record — it reads the
        YAML frontmatter dict directly. Mapping and Record forms must
        agree bit-for-bit on the same facts."""
        now = datetime.now(timezone.utc)
        mapping = {
            "status": "deferred",
            "deferred_until": "2020-01-01",
            "created_at": days_ago(40),
        }
        assert domain.is_queued(mapping, now) is True

    def test_mapping_without_status_fails_closed(self):
        # Decision recorded in the build report: no silent "assume
        # pending" default. A status-less mapping is excluded, same as
        # every other unparseable/corrupt-frontmatter case in this
        # codebase — never silently "probably pending".
        now = datetime.now(timezone.utc)
        assert domain.is_queued({"deferred_until": None}, now) is False


# ---------------------------------------------------------- is_canon_live


class TestIsCanonLive:
    def test_routed_unsuperseded_is_live(self):
        record = make_behavior(record_id="lrn-bb000001")
        record.set_status("routed")
        assert domain.is_canon_live(record) is True

    def test_routed_but_superseded_by_is_not_live(self):
        # Defence-in-depth: no live call path sets both fields together
        # today (supersede_record always flips status to "superseded" in
        # the SAME resolve_record call — measured against ledger_ops.py),
        # but the predicate must not silently trust ``status`` alone.
        record = make_behavior(record_id="lrn-bb000002")
        record.set_status("routed")
        record.set_superseded_by("lrn-bb000009")
        assert domain.is_canon_live(record) is False

    def test_superseded_status_is_not_live(self):
        record = make_behavior(record_id="lrn-bb000003")
        record.set_status("superseded")
        record.set_superseded_by("canon")
        assert domain.is_canon_live(record) is False

    def test_pending_record_is_not_live(self):
        record = make_behavior(record_id="lrn-bb000004")
        assert domain.is_canon_live(record) is False


# ------------------------------------------------------- record_age_days


class TestRecordAgeDays:
    def test_full_timestamp_floor(self):
        now = datetime.now(timezone.utc)
        record = make_behavior(record_id="lrn-cc000001", created_at=days_ago(40))
        assert domain.record_age_days(record, now) == 40

    def test_unparseable_created_at_is_zero_not_none(self):
        now = datetime.now(timezone.utc)
        assert domain.record_age_days({"created_at": "not-a-date"}, now) == 0

    def test_mapping_form_matches_record_form(self):
        now = datetime.now(timezone.utc)
        created = days_ago(40)
        record = make_behavior(record_id="lrn-cc000002", created_at=created)
        mapping = {"created_at": created}
        assert domain.record_age_days(mapping, now) == domain.record_age_days(
            record, now
        )

    def test_full_timestamp_floor_disagrees_with_date_truncation(self):
        """M-B fold r1, MAJOR-1: the age half had no regression test --
        A1's exact truncation (worker.py's own pre-M-B comment:
        ``str(created_at)[:10]``, parsing only the DATE portion before
        computing age) is silently reintroducible in ``record_age_days``
        with every other test staying green. A bare ``.days``-vs-
        ``total_seconds()//86400`` swap on the SAME two full-precision
        datetimes is mathematically inert for a non-negative delta
        (``timedelta.days`` already floors exactly like
        ``total_seconds()//86400`` when both operands carry full
        precision -- verified, not assumed) and cannot redden anything;
        this guard instead targets the REAL A1 shape, string-truncating
        ``created_at`` to its date before parsing.

        ``then`` carries a LATE time-of-day (23:00) so date-truncation
        rounds it DOWN to midnight, adding apparent age. ``now`` is 40
        days minus 10 seconds after ``then`` -- a few seconds shy of a
        full 40th day. Full-timestamp floor: 39 (correct -- not yet a
        full 40 days elapsed). Date-truncated: 40 (Jan 1 -> Feb 10 is 40
        CALENDAR days regardless of time-of-day). These disagree -- see
        the mutation-control test directly below, which reintroduces the
        truncated shape and confirms it produces 40, not 39."""
        then = datetime(2026, 1, 1, 23, 0, 0, tzinfo=timezone.utc)
        now = then + timedelta(days=40) - timedelta(seconds=10)
        record = make_behavior(record_id="lrn-cc000003", created_at=iso(then))
        assert domain.record_age_days(record, now) == 39

    def test_mutation_reintroducing_date_truncation_breaks_the_floor(
        self, monkeypatch
    ):
        """Positive control for the guard above: patches
        ``primitives.chrono.age_days`` to the A1-buggy date-truncated
        shape (``(now.date() - then.date()).days``) and confirms
        ``record_age_days`` now returns the WRONG answer (40, not 39)
        for the exact boundary case above -- proving the guard is not
        vacuous. ``domain.py`` calls ``chrono.age_days(...)`` via
        module-attribute lookup, so patching the module's function
        reaches ``record_age_days`` without touching ``domain.py``
        itself."""
        import self_learn.primitives.chrono as chrono_mod

        def _buggy_age_days(then, now):
            if then is None:
                return 0
            return max(0, (now.date() - then.date()).days)

        monkeypatch.setattr(chrono_mod, "age_days", _buggy_age_days)
        then = datetime(2026, 1, 1, 23, 0, 0, tzinfo=timezone.utc)
        now = then + timedelta(days=40) - timedelta(seconds=10)
        record = make_behavior(record_id="lrn-cc000004", created_at=iso(then))
        assert domain.record_age_days(record, now) == 40  # the buggy answer


# ------------------------------------------- cross-surface 40-day fixture


class TestCrossSurfaceExpiredDeferralFixture:
    """9 fresh pending records + 1 expired deferral aged 40 days. Before
    M-B: ``status --json``'s own ``metrics.pending_total`` (9) disagreed
    with its OWN ``total_pending`` (10) inside the SAME payload — measured
    live against this exact fixture shape prior to the fix."""

    @pytest.fixture
    def fixture_home(self, env):
        home = env.ledger
        for i in range(9):
            create_record(
                home,
                make_behavior(record_id=f"lrn-aa{i:06d}", created_at=days_ago(1)),
            )
        rid = "lrn-bb000001"
        create_record(home, make_behavior(record_id=rid, created_at=days_ago(40)))
        force_past_deferred(home, rid, "2020-01-01")
        return home

    def test_status_json_pending_total_and_metrics_agree(self, fixture_home, capsys):
        assert cli.main(["status", "--json"]) == 0
        import json

        payload = json.loads(capsys.readouterr().out)
        assert payload["total_pending"] == 10
        assert payload["metrics"]["pending_total"] == 10
        assert payload["metrics"]["pending_over_30d_pct"] == 10.0
        bucket = next(b for b in payload["buckets"] if b["bucket"] == "s")
        assert bucket["oldest_days"] == 40

    def test_list_json_count_and_age_agree(self, fixture_home, capsys):
        import json

        assert cli.main(["list", "--json"]) == 0
        items = json.loads(capsys.readouterr().out)
        assert len(items) == 10
        expired = next(i for i in items if i["id"] == "lrn-bb000001")
        assert expired["age_days"] == 40
        assert expired["status"] == "deferred"

    def test_status_fast_total_and_age_agree(self, fixture_home, capsys):
        import json

        assert cli.main(["status", "--fast"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["total_pending"] == 10
        assert payload["oldest_days"] == 40

    def test_report_json_recognizes_the_expired_deferral(self, fixture_home, capsys):
        """``report --json`` never surfaces ``pending_total`` (only
        ``status --json`` embeds ``ledger_metrics`` — confirmed by
        reading ``cli.py``'s two call sites): its own vocabulary for this
        record is the ``deferred`` list's ``overdue_days``, which must be
        positive — i.e. report's data agrees the deferral has lapsed,
        consistent with every queue-based surface counting the record."""
        import json

        assert cli.main(["report", "--json"]) == 0
        facts = json.loads(capsys.readouterr().out)
        entry = next(d for d in facts["deferred"] if d["id"] == "lrn-bb000001")
        assert entry["overdue_days"] > 0

    def test_all_four_surfaces_agree_on_the_count(self, fixture_home, capsys):
        """The tightest single assertion: FIVE independently-computed
        counts of "how many records are queued/tracked", all equal —
        including ``report --json``'s own tally (M-B gap closed in
        M-J, per code-gate review: the report leg previously lived in
        a separate test and asserted no count of its own). ``report``
        never surfaces a queue-membership predicate directly, but its
        per-bucket ``counts`` Counter increments unconditionally on
        every record's ``status`` (``counts[record.status] += 1``,
        report.py) — for this fixture (9 pending + 1 deferred, no other
        statuses), summing bucket "s"'s counts is report's own
        equivalent tally of the same 10 records every other surface
        counts via ``domain.is_queued``.

        M-B fold r1, NIT-4: the AGE was previously asserted separately
        in three different tests above, never cross-checked against
        each other in ONE test. Joined here: ``status --json``'s
        bucket ``oldest_days``, ``list --json``'s per-record
        ``age_days``, and ``status --fast``'s ``oldest_days`` — all
        three are ``domain.record_age_days``-derived and must agree.
        ``report --json`` has NO per-record age field for a deferred
        entry (measured: its ``deferred`` list carries only
        ``id``/``bucket``/``until``/``overdue_days`` — ``overdue_days``
        is DEFERRAL-relative, i.e. days since ``deferred_until``
        [2020-01-01 in this fixture], not CREATION-relative like the
        other three's 40 — so it cannot join the same equality set
        without fabricating a field report.py doesn't have. It stays a
        separate ``> 0`` check below, honestly labeled."""
        import json

        assert cli.main(["status", "--json"]) == 0
        status_payload = json.loads(capsys.readouterr().out)

        assert cli.main(["list", "--json"]) == 0
        list_items = json.loads(capsys.readouterr().out)

        assert cli.main(["status", "--fast"]) == 0
        fast_payload = json.loads(capsys.readouterr().out)

        assert cli.main(["report", "--json"]) == 0
        report_facts = json.loads(capsys.readouterr().out)
        report_bucket = next(b for b in report_facts["buckets"] if b["bucket"] == "s")
        report_total = sum(report_bucket["counts"].values())
        overdue = next(
            d["overdue_days"]
            for d in report_facts["deferred"]
            if d["id"] == "lrn-bb000001"
        )

        counts = {
            "status.total_pending": status_payload["total_pending"],
            "status.metrics.pending_total": status_payload["metrics"]["pending_total"],
            "list.count": len(list_items),
            "status_fast.total_pending": fast_payload["total_pending"],
            "report.bucket_counts_total": report_total,
        }
        assert len(set(counts.values())) == 1, counts
        assert counts["list.count"] == 10

        status_bucket = next(
            b for b in status_payload["buckets"] if b["bucket"] == "s"
        )
        list_expired = next(i for i in list_items if i["id"] == "lrn-bb000001")
        ages = {
            "status.bucket_oldest_days": status_bucket["oldest_days"],
            "list.expired_age_days": list_expired["age_days"],
            "status_fast.oldest_days": fast_payload["oldest_days"],
        }
        assert len(set(ages.values())) == 1, ages
        assert ages["status.bucket_oldest_days"] == 40
        assert overdue > 0


# ------------------------------------------------- consumer-dependency scan


#: Every module the brief names as a M-B consumer of ``domain`` — no
#: second inline definition of is-queued/is-canon-live/age anywhere else.
_CONSUMERS = {
    "ledger_ops.py": CLI_SRC / "ledger_ops.py",
    "report.py": CLI_SRC / "report.py",
    "worker.py": CLI_SRC / "worker.py",
    "compilers.py": CLI_SRC / "compilers.py",
    "verbs.py": CLI_SRC / "verbs.py",
    # M-B fold r1, NIT-1: two more real consumers found by grepping the
    # canon-liveness SHAPE directly (`status == "routed"`/`!=` paired
    # with `superseded_by is`/`is not None`) rather than trusting the
    # brief's original consumer list -- both re-derived is_canon_live
    # inline before this fold (reachability.py once, selfcheck.py three
    # times: two `continue`-guards + one `live = ...` assignment).
    "reachability.py": CLI_SRC / "reachability.py",
    "selfcheck.py": CLI_SRC / "selfcheck.py",
    "ui/models.py": UI_SRC / "models.py",
}


def _imports_domain(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # ``from . import domain`` / ``from self_learn import domain``
            if any(alias.name == "domain" for alias in node.names):
                return True
        if isinstance(node, ast.Import):
            # ``import self_learn.domain as sl_domain``
            if any(
                alias.name == "self_learn.domain" or alias.name.endswith(".domain")
                for alias in node.names
            ):
                return True
    return False


class TestConsumerDependency:
    @pytest.mark.parametrize("name", sorted(_CONSUMERS))
    def test_consumer_imports_domain(self, name):
        path = _CONSUMERS[name]
        # A missing target must never read as pass (lrn-6d21607e class):
        # fail loudly, not silently skip a consumer that moved/vanished.
        assert path.is_file(), f"expected consumer file at {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert _imports_domain(tree), f"{name} does not import self_learn.domain"

    def test_the_detector_itself_is_not_vacuous(self):
        """Positive control: a module that does NOT import domain must
        fail the check above (proven by removing the import from
        worker.py and re-running this file — see the build report for
        the exact before/after)."""
        tree = ast.parse("import os\n", filename="<memory>")
        assert _imports_domain(tree) is False


# ------------------------------------------------- canon-live shape scan


def _is_status_eq_routed(node: ast.AST):
    if (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "status"
        and len(node.ops) == 1
        and isinstance(node.ops[0], (ast.Eq, ast.NotEq))
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value == "routed"
    ):
        return type(node.ops[0])
    return None


def _is_superseded_by_is_none(node: ast.AST):
    if (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "superseded_by"
        and len(node.ops) == 1
        and isinstance(node.ops[0], (ast.Is, ast.IsNot))
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value is None
    ):
        return type(node.ops[0])
    return None


def _canon_live_shape_hits(tree: ast.Module) -> list[int]:
    """``domain.is_canon_live``'s exact shape (M-B fold r1, NIT-1): a
    BoolOp pairing ``status == "routed"``/``!= "routed"`` with
    ``superseded_by is None``/``is not None`` — the inline
    re-derivation found at 6 sites outside ``domain.py`` (the brief's
    consumer list named none of them; found by grepping this shape
    directly, not by reading the gate report). AST-based, not text
    grep, so a comment/docstring MENTIONING the shape (this file's own
    docstrings, e.g.) never false-positives — same discipline as
    :func:`_bare_subtraction_days_hits` above."""
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or len(node.values) != 2:
            continue
        left, right = node.values
        status_op = _is_status_eq_routed(left) or _is_status_eq_routed(right)
        supers_op = _is_superseded_by_is_none(left) or _is_superseded_by_is_none(
            right
        )
        if status_op is None or supers_op is None:
            continue
        if (
            isinstance(node.op, ast.And)
            and status_op is ast.Eq
            and supers_op is ast.Is
        ):
            hits.append(node.lineno)
        elif (
            isinstance(node.op, ast.Or)
            and status_op is ast.NotEq
            and supers_op is ast.IsNot
        ):
            hits.append(node.lineno)
    return hits


class TestCanonLiveShapeScan:
    """M-B fold r1, NIT-1 (root cause): the consumer-dependency scan
    above only proves a file IMPORTS ``domain`` — it cannot catch a
    file that imports domain for an unrelated reason while STILL
    re-deriving ``is_canon_live`` inline nearby (the same blind-spot
    class M-J fold r1's facade scan was caught making: list
    membership, never shape, was checked). This scan inspects the
    actual predicate SHAPE across every source file in both trees."""

    def test_positive_control_the_pattern_is_detected(self):
        """Reproduces ``selfcheck.py:889``'s EXACT pre-fold line,
        byte-for-byte."""
        tree = ast.parse(
            'live = record.status == "routed" and record.superseded_by is None\n',
            filename="<memory>",
        )
        assert _canon_live_shape_hits(tree) == [1]

    def test_negated_form_is_also_detected(self):
        """The ``continue``-guard form found at the other 5 sites
        (reachability.py, selfcheck.py x2, report.py x2)."""
        tree = ast.parse(
            'if record.status != "routed" or record.superseded_by is not None:\n'
            "    continue\n",
            filename="<memory>",
        )
        assert _canon_live_shape_hits(tree) == [1]

    @pytest.mark.parametrize(
        "path",
        [p for p in _all_source_files() if p.name != "domain.py"],
        ids=str,
    )
    def test_tree_has_zero_hits_outside_domain_py(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert _canon_live_shape_hits(tree) == []


# --------------------------------------------- .days-after-subtraction scan


def _bare_subtraction_days_hits(tree: ast.Module) -> list[int]:
    """A19/A1's exact shape: ``(a - b).days`` — a bare timedelta
    subtraction's ``.days`` attribute, which truncates toward zero
    against whatever precision the OPERANDS happened to carry (the bug
    this whole module exists to close). AST-based, not a text grep, so a
    docstring/comment MENTIONING ``.days`` never false-positives."""
    hits = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "days"
            and isinstance(node.value, ast.BinOp)
            and isinstance(node.value.op, ast.Sub)
        ):
            hits.append(node.lineno)
    return hits


class TestDaysAfterSubtractionScan:
    def test_positive_control_the_pattern_is_detected(self):
        tree = ast.parse("age = (now - then).days\n", filename="<memory>")
        assert _bare_subtraction_days_hits(tree) == [1]

    @pytest.mark.parametrize("path", _all_source_files(), ids=str)
    def test_tree_has_zero_hits(self, path):
        """M-B fold r1, MINOR-1: widened from a parametrized relpath
        list (only the modules the brief already knew about) to a full
        walk of both trees' source directories — see
        :func:`_all_source_files`'s docstring for why."""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert _bare_subtraction_days_hits(tree) == []


# --------------------------------------------------------- import-cycle check


class TestImportCycleCheck:
    def test_domain_module_imports_nothing_but_records_and_chrono(self):
        path = CLI_SRC / "domain.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
                elif node.level:
                    # ``from .primitives import chrono`` -> level=1,
                    # module="primitives"; ``from .records import ...``
                    # -> level=1, module="records".
                    for alias in node.names:
                        modules.add(alias.name)
        forbidden = {"ledger_ops", "compilers", "report"}
        assert not (modules & forbidden), modules

    def test_fresh_interpreter_import_never_pulls_in_the_cyclic_modules(self):
        """``python -c "import self_learn.domain"`` from a FRESH
        interpreter — proves the import graph at RUNTIME, not just the
        AST of domain.py itself (a deferred/function-local import
        elsewhere in domain.py would dodge the AST check above)."""
        probe = (
            "import sys; import self_learn.domain; "
            "hits = [m for m in sys.modules "
            "if m.startswith('self_learn.') "
            "and m.split('.')[-1] in ('ledger_ops', 'compilers', 'report')]; "
            "print(','.join(sorted(hits)))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=str(CLI_SRC.parent),
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "", proc.stdout



# ------------------------------------ queue()/is_unanalyzed() status gate


class TestQueueStatusGateTightening:
    """M-B fold r1, NIT-3: ``ledger_ops.queue``/``is_unanalyzed``
    migrated from ``_deferred_hidden`` (deferral-only — ``_load_pending``
    already scopes by FILE LOCATION, never by the frontmatter ``status``
    field) to ``domain.is_queued``, which ALSO gates on ``status in
    DRAFT_STATUSES`` — a status check the old code never had. Measured
    via ``git diff`` against the pre-move commit: the old body was
    exactly ``[e for e in entries if not _deferred_hidden(e.record,
    now)]``; the new body is ``[e for e in entries if
    domain.is_queued(e.record, now)]``. The commit body never called
    this out. Intentional tightening, not a redesign: it is the SAME
    defense-in-depth ``domain.is_canon_live`` already applies elsewhere,
    and it is exactly what keeps ``queue()``/``is_unanalyzed()``
    agreeing with every OTHER surface's ``domain.is_queued`` count — the
    whole point of this move. Pinned here, not reverted."""

    def test_queue_excludes_a_pending_file_whose_status_has_drifted(
        self, tmp_path
    ):
        home = make_home(tmp_path)
        path = create_record(home, make_behavior(record_id="lrn-aa000001"))
        # Drift the status directly (never through a verb — resolve_record
        # always relocates the file out of pending/ in the SAME call, so
        # this exact state is unreachable via normal verbs; it models a
        # corrupted/hand-edited frontmatter, the case domain.is_queued's
        # status gate exists to fail closed against).
        drifted = Record.from_path(path)
        drifted.set_status("routed")
        drifted.write(path)

        (bucket,) = [b for b in discover_buckets(home) if b.name == "s"]
        assert queue(bucket) == []

    def test_is_unanalyzed_excludes_the_same_drifted_entry(self, tmp_path):
        home = make_home(tmp_path)
        path = create_record(home, make_behavior(record_id="lrn-aa000002"))
        drifted = Record.from_path(path)
        drifted.set_status("routed")
        drifted.write(path)

        (bucket,) = [b for b in discover_buckets(home) if b.name == "s"]
        entries = queue(bucket, include_deferred=True)
        assert [e.record.id for e in entries] == ["lrn-aa000002"]
        assert is_unanalyzed(entries[0]) is False

    def test_mutation_reverting_to_deferred_only_check_would_include_it(
        self, tmp_path, monkeypatch
    ):
        """Positive control: patches ``domain.is_queued`` to the OLD
        deferral-only shape (never checking ``status`` at all) and
        confirms the drifted record WOULD have been included — proving
        this guard is not vacuous."""
        import self_learn.domain as domain_mod
        from self_learn.primitives import chrono as chrono_helper

        def _deferral_only(record, now):
            until = chrono_helper.to_dt(record.deferred_until)
            return until is None or until <= now

        monkeypatch.setattr(domain_mod, "is_queued", _deferral_only)

        home = make_home(tmp_path)
        path = create_record(home, make_behavior(record_id="lrn-aa000003"))
        drifted = Record.from_path(path)
        drifted.set_status("routed")
        drifted.write(path)

        (bucket,) = [b for b in discover_buckets(home) if b.name == "s"]
        assert [e.record.id for e in queue(bucket)] == ["lrn-aa000003"]


# ------------------------------------------- report.gather canon-live gate


class TestReportGatherCanonLiveGating:
    """M-B fold r1, NIT-2: ``report.gather``'s ``destinations`` Counter
    and ``routed_live`` list are built by ONE shared ``if`` gate.
    Migrating that gate from ``record.status == "routed"`` to
    ``domain.is_canon_live(record)`` (measured via ``git diff`` against
    the pre-move commit) tightened BOTH outputs together: a record
    whose ``status`` field somehow drifted to ``"routed"`` while
    ``superseded_by`` is already set (unreachable via any live verb —
    ``resolve_record``/``supersede_record`` always flip both fields in
    the SAME call — but ``is_canon_live``'s own docstring calls this
    "defence in depth against any record whose two fields ever drift")
    is now EXCLUDED from both, where the old ``status == "routed"``
    check alone would have included it. Pinned here (the tightening is
    correct — the same defense-in-depth ``is_canon_live`` already
    applies everywhere else, and it keeps ``destinations``/
    ``routed_live`` agreeing with every other consumer's canon-liveness
    accounting), not reverted."""

    def test_a_drifted_routed_record_is_excluded_from_both_outputs(
        self, tmp_path
    ):
        home = make_home(tmp_path)
        path = create_record(home, make_behavior(record_id="lrn-aa000001"))
        record = Record.from_path(path)
        record.set_status("routed")
        record.set_routing(
            {
                "routed_at": "2026-01-01T00:00:00Z",
                "destination": "skill-md",
                "by": "test",
            }
        )
        record.set_superseded_by("lrn-bb000009")  # the drift NIT-2 targets
        record.write(path)

        facts = report.gather(home, claude_dir=tmp_path / "empty-claude")
        assert facts["destinations"] == {}
        assert facts["routed_live"] == []

    def test_mutation_reverting_to_status_only_check_would_include_it(
        self, tmp_path, monkeypatch
    ):
        """Positive control: patches ``domain.is_canon_live`` (as seen
        by ``report.py``'s ``domain.is_canon_live(record)`` call) to
        the OLD status-only gate and confirms the SAME drifted record
        above WOULD have been counted — proving the pin is not
        vacuous."""
        import self_learn.domain as domain_mod

        monkeypatch.setattr(
            domain_mod, "is_canon_live", lambda record: record.status == "routed"
        )

        home = make_home(tmp_path)
        path = create_record(home, make_behavior(record_id="lrn-aa000003"))
        record = Record.from_path(path)
        record.set_status("routed")
        record.set_routing(
            {
                "routed_at": "2026-01-01T00:00:00Z",
                "destination": "skill-md",
                "by": "test",
            }
        )
        record.set_superseded_by("lrn-bb000009")
        record.write(path)

        facts = report.gather(home, claude_dir=tmp_path / "empty-claude")
        assert facts["destinations"] == {"skill-md": 1}
        assert [r["id"] for r in facts["routed_live"]] == ["lrn-aa000003"]
