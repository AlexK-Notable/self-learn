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

from self_learn import cli, domain
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.records import Record
from support import days_ago, force_past_deferred, make_behavior, make_env

CLI_SRC = Path(__file__).resolve().parent.parent / "src" / "self_learn"
UI_SRC = Path(__file__).resolve().parent.parent.parent / "ui" / "src" / "self_learn_ui"


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
        counts via ``domain.is_queued``."""
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

    @pytest.mark.parametrize(
        "relpath",
        [
            "domain.py",
            "primitives/chrono.py",
            "ledger_ops.py",
            "report.py",
            "worker.py",
            "compilers.py",
            "verbs.py",
        ],
    )
    def test_cli_tree_has_zero_hits(self, relpath):
        path = CLI_SRC / relpath
        assert path.is_file(), f"expected {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert _bare_subtraction_days_hits(tree) == []

    def test_ui_models_has_zero_hits(self):
        path = UI_SRC / "models.py"
        assert path.is_file(), f"expected {path}"
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
