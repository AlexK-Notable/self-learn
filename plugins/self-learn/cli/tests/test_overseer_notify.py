"""O-6: code-classified, coalesced overseer notification guards."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from self_learn.overseer import notify


# The real companion script invokes each of these.  Keeping this list in the
# CLI harness prevents a hermetic PATH from accidentally testing a missing
# utility instead of the notification behavior.
_REQUIRED_REAL_BINS = (
    "bash",
    "env",
    "readlink",
    "dirname",
    "timeout",
    "notify-send",
)


@pytest.mark.parametrize(
    ("outcomes", "threshold", "expected"),
    [
        ([{"hook_activated": True}, {"always_loaded_user_scope": True}], 3, "hook-activated"),
        ([{"always_loaded_user_scope": True}, {"verb": "retire"}] * 3, 1, "always-loaded-user-scope"),
        ([{"verb": "reject"}, {"verb": "replace"}, {"verb": "retire"}, {"verb": "reject"}], 3, "broad-removal"),
        ([{"close_call": True}], 3, "close-call"),
        ([{"verb": "route"}], 3, "routine"),
    ],
)
def test_o6_cue_precedence_is_code_owned(outcomes, threshold, expected):
    assert notify.classify(outcomes, broad_removal_threshold=threshold) == expected


def _spawns(monkeypatch):
    calls = []
    monkeypatch.delenv("SELF_LEARN_NO_NOTIFY", raising=False)
    monkeypatch.setattr(notify.worker, "_notifications_suppressed", lambda actual: False)
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/shim/self-learn-notify")
    monkeypatch.setattr(notify.subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs)))
    return calls


def test_o6_hook_cue_message_names_record_and_deactivate_command(monkeypatch, tmp_path):
    """The cue wording survives; since the attention round only a
    credentials hold spawns, so the cue is exercised under that kind."""
    home = tmp_path / "ledger"
    home.mkdir()
    calls = _spawns(monkeypatch)

    notify.send(home, "hook-activated", "overseer applied: 1 examined", ["lrn-0123abcd"],
                kind="hold.credentials")

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:2] == ["/shim/self-learn-notify", "--line"]
    assert "critical" in argv[2].lower()
    assert "self-learn hook deactivate lrn-0123abcd" in argv[2]
    assert argv[3:] == ["--page", "/inbox"]
    assert kwargs["start_new_session"] is True


def test_only_a_credentials_hold_pops_up_and_it_opens_the_inbox(monkeypatch, tmp_path):
    """Attention round test 2 (design r2 §3.9, answer 1): `notify.send` with
    `kind="hold.credentials"` spawns once (the control, asserted first), and
    its action opens `self-learn-ui-open --page /inbox`. Any other kind, or
    none, spawns nothing. Mutation: default the kind to credentials."""
    home = tmp_path / "ledger"
    home.mkdir()
    calls = _spawns(monkeypatch)
    notify.send(home, "routine", "the steward is held — log in", ["run-1"], kind="hold.credentials")
    assert len(calls) == 1
    assert calls[0][0] == ["/shim/self-learn-notify", "--line", "the steward is held — log in",
                           "--page", "/inbox"]
    for kind in ("hold.money", "broken.host", "decided.hook-activated", "silent"):
        notify.send(home, "hook-activated", "x", ["lrn-0123abcd"], kind=kind)
    notify.send(home, "routine", "no kind given", ["run-2"])
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("cause", "kind"),
    [
        ("Failed to authenticate: OAuth session expired and could not be refreshed", "hold.credentials"),
        ("API Error: 401 invalid x-api-key", "hold.credentials"),
        ("Your credit balance is too low", "silent"),
        ("Please update Claude Code", "silent"),
        ("something odd", "silent"),
    ],
)
def test_hold_kind_is_credentials_only_for_a_login_step(cause, kind):
    assert notify.hold_kind(cause) == kind


def test_o6_cli_harness_accounts_for_every_companion_binary():
    missing = [name for name in _REQUIRED_REAL_BINS if shutil.which(name) is None]
    assert missing == []
