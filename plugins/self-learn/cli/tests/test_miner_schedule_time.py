"""`miner.schedule_time`: the local time of day the nightly mine pass starts.

The due check is driven with a fake clock (epoch seconds built from a local
date), never the real one. The jitter (up to 15 minutes, per day), the
once-a-day rule and the catch-up after a sleep are the old ones; these tests
only move the time they are measured from.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from self_learn import serve, settings
from support import make_home

DAY = (2026, 11, 12)  # an ordinary day, far from any clock change in most zones


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.delenv("SELF_LEARN_MINER_SCHEDULE_TIME", raising=False)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


@pytest.fixture()
def cache_dir(tmp_path):
    d = tmp_path / "serve-cache"
    d.mkdir()
    return d


def at(hour: int, minute: int = 0, day=DAY) -> float:
    """Epoch seconds of a local wall-clock time."""
    return time.mktime((day[0], day[1], day[2], hour, minute, 0, 0, 0, -1))


def set_time(home: Path, value: str) -> None:
    (home / "config.yaml").write_text(f"miner:\n  schedule_time: '{value}'\n", encoding="utf-8")


def due(home, cache_dir, now) -> bool:
    return serve._mine_is_due(cache_dir, now, home=home)  # pyright: ignore[reportPrivateUsage]


# ------------------------------------------------------------------ the setting


def test_the_default_is_the_old_constant(home):
    s = settings.by_name("miner.schedule_time")
    assert s.default == "03:30" and s.tier == "A"
    assert (serve.MINE_HOUR, serve.MINE_MINUTE) == (3, 30)
    assert settings.resolve_setting(home, s) == ("03:30", "default")


@pytest.mark.parametrize("bad", ["25:00", "3:30", "03:60", "noon", "", "03.30", "0330", "24:00", "03:30pm"])
def test_a_value_that_is_not_a_time_of_day_is_refused_in_a_sentence(home, bad):
    with pytest.raises(settings.InvalidSettingValueError) as err:
        settings.config_set(home, "miner.schedule_time", bad)
    assert "miner.schedule_time" in str(err.value) and "24-hour HH:MM" in str(err.value)
    assert not (home / "config.yaml").exists() or "schedule_time" not in (home / "config.yaml").read_text()


@pytest.mark.parametrize("good", ["00:00", "03:30", "22:15", "23:59"])
def test_a_time_of_day_is_accepted_and_read_back(home, good):
    settings.config_set(home, "miner.schedule_time", good)
    assert settings.resolve_setting(home, settings.by_name("miner.schedule_time"))[0] == good


def test_a_hand_edited_bad_value_reads_as_the_default_and_does_not_break_the_check(home, cache_dir):
    set_time(home, "later")
    assert settings.resolve_setting(home, settings.by_name("miner.schedule_time"))[0] == "03:30"
    assert serve._mine_clock(home) == (3, 30)  # pyright: ignore[reportPrivateUsage]
    assert due(home, cache_dir, at(4, 0))  # the default's night


def test_the_setting_has_plain_words_in_the_time_group():
    from self_learn import settings_plain

    words = settings_plain.plain_for("miner.schedule_time")
    assert words.group == "time" and "HH:MM" in words.plain and words.label


# ------------------------------------------------------------------ the due time


def test_the_target_follows_the_setting_and_keeps_its_jitter(home):
    for value, hour, minute in (("03:30", 3, 30), ("22:15", 22, 15), ("00:05", 0, 5)):
        set_time(home, value)
        target = serve._target_for(at(12), home)  # pyright: ignore[reportPrivateUsage]
        base = at(hour, minute)
        assert base <= target <= base + serve.MINE_JITTER_SECS, value
    # no home: the shipped default, as before
    assert at(3, 30) <= serve._target_for(at(12)) <= at(3, 30) + serve.MINE_JITTER_SECS  # pyright: ignore[reportPrivateUsage]


def test_a_later_time_is_not_due_before_it_and_due_after_it(home, cache_dir):
    set_time(home, "05:00")
    assert not due(home, cache_dir, at(3, 40))  # the old night: not due any more
    assert not due(home, cache_dir, at(4, 59))
    assert not due(home, cache_dir, at(5, 0) - 1)
    assert due(home, cache_dir, at(5, 16))  # past the 15-minute jitter: due


def test_the_default_is_due_in_its_own_night_and_not_before(home, cache_dir):
    assert not due(home, cache_dir, at(3, 29))  # positive control: the old time still holds
    assert due(home, cache_dir, at(3, 46))


def test_a_change_made_after_today_s_target_was_cached_takes_effect_at_once(home, cache_dir):
    assert due(home, cache_dir, at(4, 0))  # caches today's 03:30 target
    state = json.loads(serve._schedule_state_path(cache_dir).read_text())  # pyright: ignore[reportPrivateUsage]
    assert state["at"] == "03:30"
    set_time(home, "05:00")
    assert not due(home, cache_dir, at(4, 0))  # no restart, the cache did not pin the old time
    assert json.loads(serve._schedule_state_path(cache_dir).read_text())["at"] == "05:00"  # pyright: ignore[reportPrivateUsage]
    assert due(home, cache_dir, at(5, 16))


def test_a_state_file_from_before_the_setting_still_reads(home, cache_dir):
    old_target = at(3, 40)
    serve._schedule_state_path(cache_dir).write_text(  # pyright: ignore[reportPrivateUsage]
        json.dumps({"day": time.strftime("%Y-%m-%d", time.localtime(at(12))), "target": old_target}), encoding="utf-8"
    )
    assert serve._today_mine_target(cache_dir, at(12), home) == old_target  # pyright: ignore[reportPrivateUsage]
    assert serve._today_mine_target(cache_dir, at(12)) == old_target  # pyright: ignore[reportPrivateUsage]


def test_a_caller_without_home_does_not_overwrite_the_mine_s_cached_target(home, cache_dir):
    set_time(home, "05:00")
    target = serve._today_mine_target(cache_dir, at(12), home)  # pyright: ignore[reportPrivateUsage]
    assert serve._today_mine_target(cache_dir, at(12)) == target  # pyright: ignore[reportPrivateUsage]
    assert json.loads(serve._schedule_state_path(cache_dir).read_text())["at"] == "05:00"  # pyright: ignore[reportPrivateUsage]


def test_it_still_runs_once_a_day_and_catches_up_after_a_sleep(home, cache_dir, monkeypatch):
    set_time(home, "05:00")
    monkeypatch.setattr(serve.miner, "last_run_iso", lambda: None)
    assert due(home, cache_dir, at(11, 0))  # slept through the night: due at the first tick after it
    target = serve._today_mine_target(cache_dir, at(11, 0), home)  # pyright: ignore[reportPrivateUsage]
    from datetime import datetime

    monkeypatch.setattr(serve.miner, "last_run_iso", lambda: datetime.fromtimestamp(target + 60).isoformat())
    assert not due(home, cache_dir, at(11, 30))  # it ran after the target: not again today


def test_config_outranks_the_env_var_as_for_every_miner_setting(home, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_SCHEDULE_TIME", "01:00")
    s = settings.by_name("miner.schedule_time")
    assert settings.resolve_setting(home, s) == ("01:00", "env:SELF_LEARN_MINER_SCHEDULE_TIME")
    set_time(home, "05:00")
    assert settings.resolve_setting(home, s) == ("05:00", "config:miner.schedule_time")
