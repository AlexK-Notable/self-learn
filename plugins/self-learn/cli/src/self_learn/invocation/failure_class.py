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
  Authentication is a login that no longer works: an expired or revoked
  OAuth session ("Failed to authenticate: OAuth session expired and could
  not be refreshed", run-c5fa4e3c0a78, 2026-10-30, which read as
  ``unclassified`` and cost an attempt before S-95), an invalid key
  or token, or no login at all. It is the one class that tells the user: the
  runners' environment hold (``model_failures.HELD_ENVIRONMENT``) notifies
  once per distinct cause, and only they can log in again.
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
    "is_login_failure",
    "LOGIN_FIX",
    "API_KEY_FIX",
    "hold_fix",
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
    r"|failed to authenticate"
    r"|invalid (?:x-)?api[ -]?key"
    r"|oauth (?:session|token)\b[^.\n]{0,60}\b(?:expired|invalid|revoked)"
    r"|invalid (?:bearer|access) token"
    r"|not (?:logged|signed) in\b"
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

#: The login half of ``_ENVIRONMENT``: a failure only the user can cure by
#: logging in again (S-115: the steward's hold notice names that fix
#: for these causes, and only for these).
_LOGIN = re.compile(
    r"authentication(?:_error| error| failed)"
    r"|failed to authenticate"
    r"|oauth (?:session|token)\b[^.\n]{0,60}\b(?:expired|invalid|revoked)"
    r"|invalid (?:bearer|access) token"
    r"|not (?:logged|signed) in\b"
    r"|please run /login"
    r"|api error:? *401\b",
    re.I,
)

_TAG = re.compile(r"\[([a-z][a-z0-9_]{1,63})\]")


def is_login_failure(detail: str | None) -> bool:
    """Whether a failure's text says the login no longer works (an expired or
    revoked OAuth session, failed authentication, no login at all). The cure
    is the user's: run ``claude`` and ``/login``."""
    return bool(_LOGIN.search(detail or ""))


#: The one step a person takes for a login that no longer works. Every
#: surface that names a fix for an environment hold takes it from here.
LOGIN_FIX = "run `claude`, then `/login`"

#: A rejected API key (gate r1 MINOR 1 of S-NEXT-followups): the login
#: step it had before the map was unified, and the other way it happens --
#: an exported ANTHROPIC_API_KEY, which Claude Code prefers over the login.
#: Checked before the login itself, because the API's own wording for it
#: (`authentication_error ... invalid x-api-key`) is also a login failure.
_API_KEY = re.compile(r"invalid (?:x-)?api[ -]?key", re.I)
API_KEY_FIX = LOGIN_FIX + "; if ANTHROPIC_API_KEY is exported, it may be the wrong key"

#: The other environment causes and their one step, after the key and
#: the login. First match wins: a model-not-found cause that also says
#: "update" is still a model-name problem.
_OTHER_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    # A 403 is not a login `_LOGIN` names, but its step is the same one it
    # had before the map was unified (gate r1 MINOR 1): log in again.
    (re.compile(r"api error:? *403\b", re.I), LOGIN_FIX),
    (re.compile(r"credit balance", re.I), "add credit to the Anthropic account"),
    (re.compile(r"not[ _]found|\b404\b", re.I), "check the configured model name"),
    (re.compile(r"update|upgrade|version|too old|does not support|unsupported|not supported", re.I),
     "update Claude Code (`claude update`)"),
)


def hold_fix(cause: str | None) -> str | None:
    """The one step only the person can take for an environment *cause*
    (the steward's hold, S-115): :data:`API_KEY_FIX` for a rejected API
    key, :data:`LOGIN_FIX` for what :func:`is_login_failure` says, else
    the first of ``_OTHER_FIXES`` that matches, else ``None`` for a cause the classifier has no step
    for. The single cause-to-step map: the hold notification and the
    session-start nudge both read it."""
    if _API_KEY.search(cause or ""):
        return API_KEY_FIX
    if is_login_failure(cause):
        return LOGIN_FIX
    for pattern, fix in _OTHER_FIXES:
        if pattern.search(cause or ""):
            return fix
    return None


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
