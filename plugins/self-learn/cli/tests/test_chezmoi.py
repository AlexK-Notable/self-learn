"""chezmoi.py — the guarded user-scope compile flow (T6), now capability-
gated (C2: chezmoi HARD dependency -> DETECTED capability).

Everything runs through a PATH-shimmed fake ``chezmoi`` that records each
invocation's argv to a log file and simulates drift / dirty / clean /
managed-vs-unmanaged via env vars — the module under test invokes the real
binary name through PATH. ``source-path`` is the managed/unmanaged
discriminator (rc 0 = managed, nonzero = unmanaged); its own exit code is
governed independently by ``CHEZMOI_SHIM_SOURCE_RC`` so that a generic
``CHEZMOI_SHIM_EXIT`` override (used to simulate a genuine invocation
failure downstream) does not also flip the capability probe.
"""

import os
import stat

import pytest

from self_learn.chezmoi import (
    USER_SCOPE_ABSENT,
    USER_SCOPE_MANAGED,
    USER_SCOPE_UNMANAGED,
    ChezmoiAbort,
    ChezmoiError,
    compile_user_scope,
    user_scope_capability,
)
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.records import Record

SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CHEZMOI_SHIM_LOG"
case "$1" in
  source-path)
    printf '%s' "${2:-}"
    exit "${CHEZMOI_SHIM_SOURCE_RC-0}"
    ;;
  diff)
    printf '%s' "${CHEZMOI_SHIM_DIFF-}"
    ;;
  git)
    if [ "$3" = "status" ]; then
      printf '%s' "${CHEZMOI_SHIM_STATUS-}"
    fi
    ;;
  re-add)
    if [ -n "${CHEZMOI_SHIM_READD_RC-}" ]; then
      exit "$CHEZMOI_SHIM_READD_RC"
    fi
    ;;
esac
exit "${CHEZMOI_SHIM_EXIT-0}"
"""

PRE = "# CLAUDE.md\n\nAuthored user conduct.\n"


def make_record():
    record = Record.create(
        type="behavior",
        scope="user",
        kind="surface-rule",
        source="teach",
        trigger="About to run sudo from a Claude session.",
        instruction="Tell the user the command instead; there is no tty.",
        record_id="lrn-5c0ffee1",
    )
    record.set_routing(
        {"routed_at": "2026-07-13T20:00:00Z", "destination": "claude-md", "by": "human"}
    )
    record.set_status("routed")
    return record


@pytest.fixture
def shim(tmp_path, monkeypatch):
    """Install the fake chezmoi first on PATH; return the argv-log reader."""
    bindir = tmp_path / "shim-bin"
    bindir.mkdir()
    fake = bindir / "chezmoi"
    fake.write_text(SHIM, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log = tmp_path / "chezmoi-argv.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CHEZMOI_SHIM_LOG", str(log))
    monkeypatch.delenv("CHEZMOI_SHIM_DIFF", raising=False)
    monkeypatch.delenv("CHEZMOI_SHIM_STATUS", raising=False)
    monkeypatch.delenv("CHEZMOI_SHIM_EXIT", raising=False)
    monkeypatch.delenv("CHEZMOI_SHIM_SOURCE_RC", raising=False)
    monkeypatch.delenv("CHEZMOI_SHIM_READD_RC", raising=False)

    def calls():
        return [line for line in log.read_text(encoding="utf-8").splitlines() if line]

    return calls


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "dot-claude" / "CLAUDE.md"
    path.parent.mkdir()
    path.write_text(PRE, encoding="utf-8")
    return path


class TestCleanPath:
    def test_full_argv_sequence_in_order(self, shim, target):
        result = compile_user_scope(target, [make_record()])
        assert result.committed
        assert result.synced
        assert result.sync_warning is None
        assert shim() == [
            f"source-path {target}",
            f"diff {target}",
            "git -- status --porcelain",
            f"re-add {target}",
            "git -- add -A",
            "git -- commit -m self-learn: update managed section in CLAUDE.md",
            "git -- push",
        ]

    def test_target_edited_with_managed_section(self, shim, target):
        compile_user_scope(target, [make_record()])
        text = target.read_text(encoding="utf-8")
        assert text.startswith(PRE)  # authored text preserved, section appended
        assert BEGIN_MARKER in text and END_MARKER in text
        assert (
            "- **When about to run sudo from a Claude session:** "
            "tell the user the command instead; there is no tty. *(lrn-5c0ffee1)*"
        ) in text

    def test_custom_commit_message(self, shim, target):
        compile_user_scope(
            target, [make_record()], commit_message="self-learn: route lrn-5c0ffee1 → claude-md"
        )
        assert "git -- commit -m self-learn: route lrn-5c0ffee1 → claude-md" in shim()

    def test_noop_compile_skips_readd_and_commit(self, shim, target):
        compile_user_scope(target, [make_record()])
        first_calls = shim()
        result = compile_user_scope(target, [make_record()])  # section already current
        assert not result.committed and not result.section.changed
        assert not result.synced and result.sync_warning is None
        assert shim() == first_calls + [
            f"source-path {target}",
            f"diff {target}",
            "git -- status --porcelain",
        ]


class TestDriftAbort:
    def test_aborts_before_any_edit(self, shim, target, monkeypatch):
        monkeypatch.setenv("CHEZMOI_SHIM_DIFF", "--- a/CLAUDE.md\n+++ b/CLAUDE.md\n")
        with pytest.raises(ChezmoiAbort) as excinfo:
            compile_user_scope(target, [make_record()])
        assert "fix drift / commit dotfiles first, or route to project scope" in str(
            excinfo.value
        )
        assert target.read_text(encoding="utf-8") == PRE  # untouched
        assert shim() == [f"source-path {target}", f"diff {target}"]  # stopped at step 1


class TestDirtyRepoAbort:
    def test_aborts_before_any_edit(self, shim, target, monkeypatch):
        monkeypatch.setenv("CHEZMOI_SHIM_STATUS", " M dot_zshrc\n")
        with pytest.raises(ChezmoiAbort) as excinfo:
            compile_user_scope(target, [make_record()])
        assert "fix drift / commit dotfiles first, or route to project scope" in str(
            excinfo.value
        )
        assert target.read_text(encoding="utf-8") == PRE  # untouched
        assert shim() == [
            f"source-path {target}",
            f"diff {target}",
            "git -- status --porcelain",
        ]  # stopped at step 2


class TestChezmoiCapability:
    """T-6: user_scope_capability unit — the three §3 detection states."""

    def test_absent_when_binary_missing(self, target, monkeypatch, tmp_path):
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert (
            user_scope_capability(target, chezmoi="chezmoi-definitely-absent")
            == USER_SCOPE_ABSENT
        )

    def test_unmanaged_when_source_path_nonzero(self, shim, target, monkeypatch):
        monkeypatch.setenv("CHEZMOI_SHIM_SOURCE_RC", "1")
        # Must not raise even though source-path exits nonzero — that is
        # the unmanaged SIGNAL, not an invocation failure.
        assert user_scope_capability(target) == USER_SCOPE_UNMANAGED

    def test_managed_when_source_path_zero(self, shim, target):
        assert user_scope_capability(target) == USER_SCOPE_MANAGED


class TestUnmanagedDegradesToSilentWrite:
    """T-2: present + unmanaged (§3 row 2) — write only, no sync, silent."""

    def test_writes_section_skips_preflight_and_sync(self, shim, target, monkeypatch):
        monkeypatch.setenv("CHEZMOI_SHIM_SOURCE_RC", "1")
        result = compile_user_scope(target, [make_record()])
        assert result.committed is False
        assert result.synced is False
        assert result.sync_warning is None
        text = target.read_text(encoding="utf-8")
        assert BEGIN_MARKER in text and END_MARKER in text
        calls = shim()
        assert calls == [f"source-path {target}"]  # never re-add on an unmanaged target
        assert not any(c.startswith("diff") for c in calls)
        assert not any(c.startswith("re-add") for c in calls)
        assert not any(c.startswith("git") for c in calls)


class TestAbsentDegradesToSilentWrite:
    """T-1 (replaces the old test_missing_binary_raises_chezmoi_error — C2
    inverts that expectation per DoD-8: absent now DEGRADES, not raises)."""

    def test_writes_section_without_raising(self, target, monkeypatch, tmp_path):
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        result = compile_user_scope(
            target, [make_record()], chezmoi="chezmoi-definitely-absent"
        )
        assert result.committed is False
        assert result.synced is False
        assert result.sync_warning is None
        text = target.read_text(encoding="utf-8")
        assert BEGIN_MARKER in text and END_MARKER in text
        assert (
            "- **When about to run sudo from a Claude session:** "
            "tell the user the command instead; there is no tty. *(lrn-5c0ffee1)*"
        ) in text


class TestBrokenSourceWarns:
    """T-4: present + managed + broken source (§3 row 4) — WRITE then WARN,
    never a raise, never a rollback."""

    def test_readd_failure_warns_without_raising(self, shim, target, monkeypatch):
        monkeypatch.setenv("CHEZMOI_SHIM_READD_RC", "1")
        result = compile_user_scope(target, [make_record()])
        assert result.committed is False
        assert result.synced is False
        assert result.sync_warning is not None
        assert "clobber" in result.sync_warning
        assert "recompile" in result.sync_warning
        text = target.read_text(encoding="utf-8")
        assert BEGIN_MARKER in text and END_MARKER in text  # write already landed
        calls = shim()
        assert calls == [
            f"source-path {target}",
            f"diff {target}",
            "git -- status --porcelain",
            f"re-add {target}",
        ]  # failure was at sync (re-add), not preflight


class TestInvocationFailures:
    def test_nonzero_exit_raises_chezmoi_error(self, shim, target, monkeypatch):
        monkeypatch.setenv("CHEZMOI_SHIM_EXIT", "1")
        with pytest.raises(ChezmoiError):
            compile_user_scope(target, [make_record()])
        assert target.read_text(encoding="utf-8") == PRE
