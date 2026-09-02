"""ledger.py's CLI-invocation half (list/status/report/mine status),
driven against a REAL throwaway SELF_LEARN_HOME with the real
``self-learn`` binary (10 §0 rule 7's uv path dep — cheap, honest).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from self_learn_ui import ledger
from self_learn_ui.models import CliRead

from support import make_behavior, make_env, seed_record


@pytest.fixture
def sandbox(tmp_path):
    return make_env(tmp_path, skills=("s",))


def _ok_data(read: CliRead) -> Any:
    assert read.ok is True
    assert read.data is not None
    return read.data


class TestListItems:
    def test_empty_ledger(self, sandbox):
        read = ledger.list_items(sandbox.ledger, env=sandbox.env)
        assert read.ok is True
        assert read.error is None
        assert read.data == []

    def test_records_present(self, sandbox):
        seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000001"))
        items = _ok_data(ledger.list_items(sandbox.ledger, env=sandbox.env))
        (item,) = items
        assert item["id"] == "lrn-aa000001"
        assert item["bucket"] == "s"
        assert item["host_registered"] is True

    def test_include_deferred_flag_threads_through(self, sandbox):
        seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000002"))
        # defer it via the real CLI verb so ledger.py's --include-deferred
        # flag is exercised against real queue-membership logic, not a stub.
        subprocess.run(
            ["self-learn", "defer", "lrn-aa000002", "--until", "2099-01-01"],
            env=sandbox.env,
            check=True,
            capture_output=True,
        )
        default_read = ledger.list_items(sandbox.ledger, env=sandbox.env)
        assert default_read.data == []  # hidden — deferred_until is future
        included = _ok_data(
            ledger.list_items(sandbox.ledger, include_deferred=True, env=sandbox.env)
        )
        assert len(included) == 1
        assert included[0]["id"] == "lrn-aa000002"


class TestStatus:
    def test_shape(self, sandbox):
        seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000003"))
        data = _ok_data(ledger.status(sandbox.ledger, env=sandbox.env))
        assert data["total_pending"] == 1
        assert "worker_last_run" in data
        assert "buckets" in data


class TestReport:
    def test_shape(self, sandbox):
        data = _ok_data(ledger.report(sandbox.ledger, env=sandbox.env))
        assert "recurrence_suspects" in data
        assert "open_followups" in data
        assert "routed_live" in data


class TestMineStatus:
    def test_shape_never_ran(self, sandbox):
        data = _ok_data(ledger.mine_status(sandbox.ledger, env=sandbox.env))
        # a missing run marker counts as infinitely old (miner.stale()'s
        # own documented rule) — never-ran is stale, not a quiet False.
        assert data == {"last_run": None, "stale": True, "runs": []}


class TestCliFailureSurfaces:
    def test_missing_home_is_an_explicit_error_never_empty_success(
        self, tmp_path, sandbox
    ):
        """08 §1 home-state gate: a nonexistent SELF_LEARN_HOME must not
        read as '0 pending, all fine' — the CLI itself exits non-zero
        with a loud message, and ledger.py must surface that message
        rather than silently returning an empty list."""
        missing = tmp_path / "does-not-exist"
        read = ledger.list_items(missing, env=sandbox.env)
        assert read.ok is False
        assert read.data is None
        assert read.error is not None
        assert "does-not-exist" in read.error or "ledger home" in read.error

    def test_binary_not_found_surfaces_as_error(self, sandbox, monkeypatch):
        # Point resolution at a nonexistent binary: subprocess.run raises
        # FileNotFoundError (a real OSError) — exercised for real, not
        # mocked at the subprocess layer.
        monkeypatch.setattr(
            ledger, "_self_learn_bin", lambda: "definitely-not-a-real-binary"
        )
        read = ledger.list_items(sandbox.ledger, env=sandbox.env)
        assert read.ok is False
        assert read.error is not None
        assert "failed to start" in read.error


class TestSelfLearnBinResolution:
    """Coordinator's "MINE" item (code-gate review r1 2026-09-01):
    `ledger._self_learn_bin` used to have NO env override at all and
    resolved via `shutil.which("self-learn")` against the raw process
    `PATH` unconditionally — a test process invoked in some
    non-canonical way could silently land on PRODUCTION's real
    `~/bin/self-learn` instead of this worktree's own venv binary
    (measured: 10 of 11 `test_settings_route.py` tests 503'd this way).
    `conftest.py`'s `_pin_self_learn_cli_bin` autouse fixture now pins
    `SELF_LEARN_UI_CLI_BIN` to this package's own venv binary for every
    test in this package; this is the POSITIVE CONTROL proving that pin
    actually reaches `_self_learn_bin` and resolves inside the current
    venv, not just that the env var is set somewhere."""

    def test_resolves_inside_the_current_venv(self):
        resolved = ledger._self_learn_bin()
        venv_bin_dir = Path(sys.executable).parent
        assert Path(resolved).parent == venv_bin_dir
        assert Path(resolved).is_file()

    def test_matches_the_pinned_env_var_verbatim(self, monkeypatch):
        # Repin to a value this test controls directly — proves
        # `_self_learn_bin` reads SELF_LEARN_UI_CLI_BIN (the override),
        # not just that it happens to land somewhere plausible.
        monkeypatch.setenv("SELF_LEARN_UI_CLI_BIN", "/not/a/real/path/self-learn")
        assert ledger._self_learn_bin() == "/not/a/real/path/self-learn"

    def test_falls_back_to_which_when_unpinned(self, monkeypatch):
        # The negative control: with the override absent, resolution
        # still falls through to shutil.which/sys.executable-relative,
        # unchanged from before this fix -- still resolves to a real,
        # existing file, just via the OLD path.
        monkeypatch.delenv("SELF_LEARN_UI_CLI_BIN", raising=False)
        resolved = ledger._self_learn_bin()
        assert resolved
        assert Path(resolved).is_file()
