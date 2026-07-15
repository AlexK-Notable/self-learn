"""Suite-wide defaults.

The M2 worker is kick-driven: real `teach`/`import` end by spawning a
detached coalescing run. Tests must never leak detached processes, so
auto-kick is disabled globally here; worker tests opt back in (or drive
`worker.kick`/`worker.run` directly) by clearing/overriding the env var.
Coalesce sleep is zeroed for the same reason.
"""

import pytest


@pytest.fixture(autouse=True)
def _worker_test_defaults(monkeypatch):
    monkeypatch.setenv("SELF_LEARN_WORKER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_COALESCE_SECS", "0")
