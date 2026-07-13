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
        assert sentinel.sentinel_path() == (
            cache_dir / "claude-skills" / "self-learn" / "autosync-pause"
        )

    def test_defaults_to_home_dot_cache(self, monkeypatch):
        monkeypatch.delenv("XDG_CACHE_HOME")
        assert sentinel.sentinel_path() == (
            Path("~/.cache").expanduser()
            / "claude-skills"
            / "self-learn"
            / "autosync-pause"
        )


class TestHold:
    def test_creates_file_with_one_info_line(self):
        hold = sentinel.hold()
        assert hold.owned
        text = hold.path.read_text(encoding="utf-8")
        assert LINE_RE.fullmatch(text)
        assert f"pid={os.getpid()} " in text

    def test_preexisting_live_sentinel_left_alone(self):
        path = sentinel.sentinel_path()
        path.parent.mkdir(parents=True)
        other = "pid=99999 host=elsewhere started=2026-07-13T00:00:00Z\n"
        path.write_text(other, encoding="utf-8")

        hold = sentinel.hold()
        assert not hold.owned
        assert path.read_text(encoding="utf-8") == other  # untouched

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
