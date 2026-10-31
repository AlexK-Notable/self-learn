"""S-95 (2026-10-30): an expired login is an `environment`
failure, not `unclassified`.

Live evidence: the steward's run `run-c5fa4e3c0a78` failed with the model
log "run: claude exited 1: Failed to authenticate: OAuth session expired
and could not be refreshed" and recorded failure_class `unclassified`: the
attempt was counted and the user was never told to log in. The shared
classifier (`invocation.failure_class`) is the one place every runner reads
-- the steward, the overseer, the worker and the miner -- and its
`environment` class is the one that holds the run and notifies the user
once per distinct cause (`model_failures.HELD_ENVIRONMENT`).

Synthetic messages shaped like the live one; no model call, no ledger.
"""

from __future__ import annotations

import pytest

from self_learn import model_failures
from self_learn.invocation import failure_class
from self_learn.invocation.contract import Outcome

LIVE = "run: claude exited 1: Failed to authenticate: OAuth session expired and could not be refreshed"


def _failed(detail: str) -> Outcome:
    return Outcome(ok=False, rc=1, stdout="", detail=detail, failure="exit")


@pytest.mark.parametrize(
    "detail",
    [
        LIVE,
        "Failed to authenticate",
        "OAuth session expired and could not be refreshed",
        "OAuth session was revoked",
        "OAuth token is invalid",
        "API Error: 401 invalid bearer token",
        "Not logged in",
        "Not logged in - Please run /login",
    ],
)
def test_an_authentication_failure_is_classified_environment(detail):
    assert failure_class.classify("exit", detail) == "environment"
    assert failure_class.outcome_class(_failed(detail)) == "environment"
    assert model_failures.failure_fields(_failed(detail))["failure_class"] == "environment"


@pytest.mark.parametrize(
    "detail, expected",
    [
        # negative controls: the classes this change must not move
        ("the call timed out after 600 seconds", "unclassified"),
        ("API Error: 529 overloaded_error", "transient"),
        ("API Error: 429 rate limit exceeded", "transient"),
        ("safeguards flagged this message", "safeguard"),
        ("authentication_error: invalid x-api-key", "environment"),
        ("OAuth token has expired", "environment"),
        # a sentence that merely mentions OAuth is not a login failure
        ("the session ended: the OAuth client replied normally", "unclassified"),
    ],
)
def test_other_failures_keep_their_class(detail, expected):
    assert failure_class.classify("exit", detail) == expected


def test_the_live_message_reads_as_an_environment_hold_cause():
    """The user is told once per cause: the cause is the message's first
    sentence, so it names the login and not just "claude exited 1"."""
    cause = model_failures.hold_cause(_failed(LIVE))
    assert "Failed to authenticate" in cause
    assert "OAuth session expired" in cause
