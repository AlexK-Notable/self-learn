"""Code-owned notification cue selection for overseer runs (O-6), and the
one popup self-learn still shows: a login hold (attention round, answer 1)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from .. import worker
from ..invocation import failure_class

_REMOVAL_VERBS = frozenset({"reject", "retire", "replace", "supersede"})


def classify(
    outcomes: Iterable[Mapping[str, Any]], *, broad_removal_threshold: int
) -> str:
    """Choose exactly one cue from applied result facts, in priority order."""
    rows = list(outcomes)
    if any(bool(row.get("hook_activated")) for row in rows):
        return "hook-activated"
    if any(bool(row.get("always_loaded_user_scope")) for row in rows):
        return "always-loaded-user-scope"
    removals = sum(1 for row in rows if row.get("verb") in _REMOVAL_VERBS)
    if removals > broad_removal_threshold:
        return "broad-removal"
    if any(bool(row.get("close_call")) for row in rows):
        return "close-call"
    return "routine"


def _line(cue: str, summary: str, ids: list[str]) -> str:
    if cue == "hook-activated":
        record = ids[0] if ids else "unknown record"
        return (
            f"CRITICAL — {summary}; hook activated for {record}. "
            f"Deactivate with: self-learn hook deactivate {record}"
        )
    if cue == "always-loaded-user-scope":
        return f"ATTENTION — user-scope always-loaded surface changed; {summary}"
    if cue == "broad-removal":
        return f"ATTENTION — broad catalogue removal; {summary}"
    if cue == "close-call":
        return f"ATTENTION — close call flagged for review; {summary}"
    return summary


#: The one kind of event that may still interrupt the user with a popup
#: (answer 1, attention design r2 §3.9): self-learn cannot work at all until
#: the user signs in again. Everything else waits in the tray's inbox.
POPUP_KIND = "hold.credentials"

#: Where the popup's "Open" action lands: the inbox, where the login item is
#: selected first (`self-learn-ui-open --page`, design r2 §4.7).
POPUP_PAGE = "/inbox"


def hold_kind(cause: str | None) -> str:
    """The notification kind for an environment-hold *cause*: ``POPUP_KIND``
    when the one step left is a login (`failure_class.hold_fix` gives
    ``LOGIN_FIX`` or ``API_KEY_FIX``), else ``"silent"``. The steward, the
    overseer and `serve` each send their hold once per distinct cause and
    pass this kind, so only a login hold can pop up."""
    fix = failure_class.hold_fix(cause)
    if fix in (failure_class.LOGIN_FIX, failure_class.API_KEY_FIX):
        return POPUP_KIND
    return "silent"


def with_hold_fix(text: str, cause: str | None) -> str:
    """*text* followed by the person's one step for an environment-hold
    *cause* (`failure_class.hold_fix`), when it has one: the login popup
    says what to type (answer 10's low barrier; gate r1 NIT 2 of the
    surfaces lane). The steward words its own through
    `steward.hold_notice_text`; the overseer and `serve` use this."""
    fix = failure_class.hold_fix(cause)
    return f"{text} To fix it: {fix}." if fix else text


def send(
    home: Path, cue: str, summary: str, ids: list[str], *, kind: str = "silent"
) -> None:
    """Detach one bounded companion-script popup, best effort, and only for
    ``kind == POPUP_KIND`` (answer 1). Every other kind spawns nothing: what
    it would have said is an item in the inbox the tray icon opens.

    The popup's action opens ``self-learn-ui-open --page /inbox``."""
    if kind != POPUP_KIND:
        return
    if worker._notifications_suppressed(home):
        return
    helper = shutil.which("self-learn-notify")
    line = _line(cue, summary, ids)
    if not helper:
        worker.log("notify: self-learn-notify not on PATH — notification skipped")
        return
    # The detached helper owns the action wait.  Its two notify-send legs are
    # both wrapped by ``timeout --kill-after=5 40`` and branch on action output.
    try:
        subprocess.Popen(
            [helper, "--line", line, "--page", POPUP_PAGE],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        worker.log("notify: failed to spawn self-learn-notify")
