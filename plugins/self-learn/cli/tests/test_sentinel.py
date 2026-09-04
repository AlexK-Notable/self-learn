"""T7 sentinel: hold / heartbeat / release on the XDG-resolved pause file
(08 §1 Sentinel + Sentinel-scoping pins; 02 §3 mtime-TTL contract)."""

import os
import re
import time
from pathlib import Path

import pytest

from self_learn import sentinel

LINE_RE = re.compile(
    r"pid=\d+ host=\S+ started=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\n"
)
TOKEN_LINE_RE = re.compile(r"token=[0-9a-f]+\n")


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Never touch the real ~/.cache: XDG-redirect every test."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


def age(path: Path, seconds: float) -> None:
    """Backdate the sentinel's mtime by ``seconds``."""
    past = time.time() - seconds
    os.utime(path, (past, past))


class TestPath:
    def test_resolves_xdg_cache_home(self, cache_dir):
        # doc 13 §6: the cache namespace dropped the host it no longer
        # belongs to — no "claude-skills" segment.
        assert sentinel.sentinel_path() == (
            cache_dir / "self-learn" / "autosync-pause"
        )

    def test_defaults_to_home_dot_cache(self, monkeypatch):
        monkeypatch.delenv("XDG_CACHE_HOME")
        assert sentinel.sentinel_path() == (
            Path("~/.cache").expanduser() / "self-learn" / "autosync-pause"
        )


class TestHold:
    def test_creates_file_with_info_line_and_ownership_token(self):
        """M-E: a fresh hold publishes the info line PLUS a token line —
        the token is what makes the hold provable to a later `release`
        (C11 fix), not just the local `owned` flag."""
        hold = sentinel.hold()
        assert hold.owned
        assert hold.token is not None
        text = hold.path.read_text(encoding="utf-8")
        info_line, token_line = text.splitlines(keepends=True)
        assert LINE_RE.fullmatch(info_line)
        assert TOKEN_LINE_RE.fullmatch(token_line)
        assert f"pid={os.getpid()} " in info_line
        assert token_line == f"token={hold.token}\n"

    def test_preexisting_live_sentinel_left_alone(self):
        path = sentinel.sentinel_path()
        path.parent.mkdir(parents=True)
        other = "pid=99999 host=elsewhere started=2026-07-13T00:00:00Z\n"
        path.write_text(other, encoding="utf-8")

        hold = sentinel.hold()
        assert not hold.owned
        assert hold.token is None
        assert path.read_text(encoding="utf-8") == other  # untouched

    def test_preexisting_live_old_format_file_reads_as_unowned(self):
        """Rollout pin (M-E): an old-format file — no `token=` line at
        all, exactly what a pre-M-E process writes — is read exactly
        like any other live foreign sentinel: live, and never adopted."""
        path = sentinel.sentinel_path()
        path.parent.mkdir(parents=True)
        old_format = "pid=99999 host=elsewhere started=2026-07-13T00:00:00Z\n"
        path.write_text(old_format, encoding="utf-8")

        hold = sentinel.hold()
        assert not hold.owned
        assert hold.token is None
        assert path.read_text(encoding="utf-8") == old_format  # untouched

    def test_stale_sentinel_is_overwritten_and_owned(self):
        first = sentinel.hold()
        first.path.write_text(
            "pid=99999 host=elsewhere started=2026-07-13T00:00:00Z\n",
            encoding="utf-8",
        )
        age(first.path, sentinel.SENTINEL_TTL_SECONDS + 60)

        hold = sentinel.hold()
        assert hold.owned
        assert f"pid={os.getpid()} " in hold.path.read_text(encoding="utf-8")


class TestLiveness:
    def test_live_under_ttl(self):
        hold = sentinel.hold()
        assert sentinel.is_live(hold.path)

    def test_dead_at_ttl(self):
        hold = sentinel.hold()
        age(hold.path, sentinel.SENTINEL_TTL_SECONDS + 1)
        assert not sentinel.is_live(hold.path)

    def test_missing_file_is_not_live(self):
        assert not sentinel.is_live()


class TestHeartbeat:
    def test_retouches_live_sentinel(self):
        hold = sentinel.hold()
        age(hold.path, 600)
        before = hold.path.stat().st_mtime
        assert sentinel.heartbeat()
        assert hold.path.stat().st_mtime > before

    def test_never_resurrects_a_stale_sentinel(self):
        hold = sentinel.hold()
        age(hold.path, sentinel.SENTINEL_TTL_SECONDS + 60)
        before = hold.path.stat().st_mtime
        assert not sentinel.heartbeat()
        assert hold.path.stat().st_mtime == before

    def test_missing_file_is_a_noop(self):
        assert not sentinel.heartbeat()


class TestRelease:
    def test_own_hold_releases(self):
        hold = sentinel.hold()
        assert hold.release()
        assert not hold.path.exists()

    def test_foreign_live_hold_is_never_deleted(self):
        path = sentinel.sentinel_path()
        path.parent.mkdir(parents=True)
        path.write_text(
            "pid=99999 host=elsewhere started=2026-07-13T00:00:00Z\n",
            encoding="utf-8",
        )
        hold = sentinel.hold()  # owned=False
        assert not hold.release()
        assert path.exists()

    def test_release_function_form(self):
        hold = sentinel.hold()
        assert sentinel.release(hold)
        assert not hold.path.exists()

    def test_release_refuses_when_disk_token_no_longer_matches(self):
        """C11's release half, proved directly: a handle whose local
        ``owned`` is (still) True must NOT be enough to delete — the
        file currently on disk has to still carry ITS token. Simulates
        a legitimate TTL takeover landing between this hold and this
        release (a different process's fresh publish); a release keyed
        only on the boolean would delete that other holder's live file,
        which is exactly the bug this move closes."""
        hold = sentinel.hold()
        assert hold.owned
        hold.path.write_text(
            sentinel.sentinel_line() + "token=0000000000000000\n",
            encoding="utf-8",
        )

        assert not hold.release()
        assert hold.path.exists()  # never deletes someone else's file
