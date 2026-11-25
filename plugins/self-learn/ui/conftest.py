"""Install the shared Windows profile floor before importing UI tests."""

import os
from pathlib import Path
from runpy import run_path

import pytest

# This helper lives in the sibling test tree, outside the installed CLI package.
_home_floor = run_path(str(Path(__file__).resolve().parents[1] / "cli" / "_test_home_floor.py"))

if os.name == "nt":
    _session_profile, _close_home_floor = _home_floor["start_session_home_floor"]()

    def pytest_configure(config):
        config.add_cleanup(_close_home_floor)
else:
    _session_profile = None


@pytest.fixture
def home_floor_installer():
    return _home_floor["home_floor"]


@pytest.fixture(scope="session")
def windows_session_profile():
    return _session_profile
