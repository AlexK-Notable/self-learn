"""What kind of model-side failure a failed call was (2026-09-27, fail-state
audit finding 4).

Every failed model call used to reach the steward and the overseer as the
same `exit` failure and cost an attempt, whatever it was: a safety-classifier
flag, a rate limit, an overloaded API, or a Claude Code too old for the
model. Only the detail text told them apart. This is the ONE place that
reads it.

Classes:

* ``transient`` -- overloaded (529), a server error (5xx), a rate limit
  (429), a network failure. Retried once within the same attempt.
* ``safeguard`` -- the API's safety classifier flagged the conversation
  ("safeguards flagged this message"). Counted like ``content``; the user
  will accept a fallback model only as a last resort (2026-09-27 13:30), so
  there is no retry and no other model.
* ``environment`` -- the model or the installed Claude Code cannot run the
  call at all: an unsupported model or Claude Code version, authentication,
  a model or binary not found, a refused provider. Held: not an attempt.
* ``content`` -- Claude Code stopped the session at its own turn or spend
  limit. Counted as always.
* ``unclassified`` -- anything else (a timeout, an unrecognised message).
  Counted as always: only a failure recognised by its detail changes what a
  runner does.

Stdlib-only, like the rest of this package.
"""

from __future__ import annotations

import re

__all__ = [
    "FAILURE_CLASSES",
    "classify",
    "outcome_class",
    "detail_tag",
]

FAILURE_CLASSES = ("transient", "safeguard", "environment", "content", "unclassified")

_CONTENT_SUBTYPES = frozenset({"error_max_turns", "error_max_budget_usd"})

_SAFEGUARD = re.compile(r"safeguards? flagged|flagged by (?:our|the) safeguards", re.I)

_ENVIRONMENT = re.compile(
    r"does not support (?:this|the) model"
    r"|not supported by (?:this|the) (?:version|model)"
    r"|unsupported model"
    r"|claude code (?:version )?[0-9][0-9.]* (?:does not|is too old|is not supported)"
    r"|please (?:update|upgrade) claude code"
    r"|authentication(?:_error| error| failed)"
    r"|invalid (?:x-)?api[ -]?key"
    r"|oauth token (?:has )?expired"
    r"|please run /login"
    r"|not_found_error"
    r"|model not found"
    r"|credit balance is too low"
    r"|api error:? *(?:401|403|404)\b",
    re.I,
)

_TRANSIENT = re.compile(
    r"overloaded"
    r"|\b529\b"
    r"|rate[ _-]?limit"
    r"|too many requests"
    r"|api error:? *(?:429|5[0-9][0-9])\b"
    r"|internal server error"
    r"|service unavailable"
    r"|bad gateway"
    r"|gateway timeout"
    r"|econnreset|econnrefused|etimedout|eai_again|enotfound"
    r"|socket hang up"
    r"|fetch failed"
    r"|network error"
    r"|connection (?:error|reset|refused|closed)",
    re.I,
)

_TAG = re.compile(r"\[([a-z][a-z0-9_]{1,63})\]")


def classify(failure: str | None, detail: str | None, result_subtype: str | None = None) -> str | None:
    """The class of one failed call, or ``None`` for a call that did not
    fail. *failure* is the outcome's `failure` kind, *detail* its message,
    *result_subtype* the SDK result message's subtype when there is one."""
    if failure is None:
        return None
    text = detail or ""
    if result_subtype in _CONTENT_SUBTYPES:
        return "content"
    if _SAFEGUARD.search(text):
        return "safeguard"
    if failure in ("not-found", "unavailable") or _ENVIRONMENT.search(text):
        return "environment"
    if _TRANSIENT.search(text):
        return "transient"
    return "unclassified"


def outcome_class(outcome: object) -> str | None:
    """The class an outcome carries (`SdkOutcome.failure_class`), or the one
    :func:`classify` reads off its fields -- a fake or a plain `Outcome`
    carries none of its own."""
    if getattr(outcome, "ok", False):
        return None
    carried = getattr(outcome, "failure_class", None)
    if isinstance(carried, str) and carried in FAILURE_CLASSES:
        return carried
    failure = getattr(outcome, "failure", None)
    detail = getattr(outcome, "detail", None)
    subtype = getattr(outcome, "result_subtype", None)
    return classify(
        failure if isinstance(failure, str) else "exit",
        detail if isinstance(detail, str) else None,
        subtype if isinstance(subtype, str) else None,
    )


def detail_tag(detail: str | None) -> str | None:
    """The API's bracketed tag in a failure message (the safety classifier
    names what it flagged this way, e.g. ``[reasoning_extraction]``), or
    ``None``."""
    match = _TAG.search(detail or "")
    return match.group(1) if match else None
