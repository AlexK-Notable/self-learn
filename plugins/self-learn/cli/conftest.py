"""Isolate tests from the developer's git config and Windows profile.

pytest loads this before ``tests/conftest.py`` (which is byte-pinned by
``tests/test_armor.py``), for every run: the suite runner, a single file,
and every CLI subprocess a test spawns, since those inherit ``os.environ``.

Only the tests are exempted. The product, and the developer's own shell,
keep reading ``~/.gitconfig`` as before.
"""

import os
from pathlib import Path

import pytest

from _test_home_floor import home_floor, start_session_home_floor

if os.name == "nt":
    _session_profile, _close_home_floor = start_session_home_floor()

    def pytest_configure(config):
        config.add_cleanup(_close_home_floor)
else:
    _session_profile = None

try:
    from self_learn.settings import AGENT_CALLER_MARKERS
except ModuleNotFoundError as exc:
    if os.name != "nt" or exc.name != "fcntl":
        raise
    # The Windows home-floor canaries can run while gitops requires fcntl.
    AGENT_CALLER_MARKERS = ()

os.environ["GIT_CONFIG_GLOBAL"] = str(Path(__file__).parent / "tests" / "gitconfig.test")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"


@pytest.fixture(autouse=True)
def _human_config_caller(monkeypatch):
    """Ordinary tests model a human; agent-specific tests opt in explicitly."""
    for marker in AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)


@pytest.fixture
def home_floor_installer():
    return home_floor


@pytest.fixture(scope="session")
def windows_session_profile():
    return _session_profile
