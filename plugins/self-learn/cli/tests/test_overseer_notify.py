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


def test_o6_hook_cue_message_names_record_and_deactivate_command(monkeypatch, tmp_path):
    home = tmp_path / "ledger"
    home.mkdir()
    calls = []
    monkeypatch.delenv("SELF_LEARN_NO_NOTIFY", raising=False)
    monkeypatch.setattr(notify.worker, "_notifications_suppressed", lambda actual: False)
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/shim/self-learn-notify")
    monkeypatch.setattr(notify.subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs)))

    notify.send(home, "hook-activated", "overseer applied: 1 examined", ["lrn-0123abcd"])

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:2] == ["/shim/self-learn-notify", "--line"]
    assert "critical" in argv[2].lower()
    assert "lrn-0123abcd" in argv[2]
    assert "self-learn hook deactivate lrn-0123abcd" in argv[2]
    assert argv[3:] == ["--ids", "lrn-0123abcd"]
    assert kwargs["start_new_session"] is True


def test_o6_cli_harness_accounts_for_every_companion_binary():
    missing = [name for name in _REQUIRED_REAL_BINS if shutil.which(name) is None]
    assert missing == []
