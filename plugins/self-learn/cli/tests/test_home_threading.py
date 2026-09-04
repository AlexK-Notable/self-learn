"""M-P — explicit-home threading (sprint 1 lane L4, audit A14/A13 Python
half): `worker.cache_dir`, `miner.transcripts_root`, the newly-extracted
`miner.miner_enabled` (extracted from `miner.stale`'s inline check), and
`worker._notifications_suppressed` each now accept an optional `home`
parameter defaulting to `ledger.resolve_home()` when omitted, so a
caller that already holds an explicit `home` can pass it through
instead of these helpers silently re-deriving one from the ambient
`SELF_LEARN_HOME` — which, whenever the two disagree, meant an
explicit-home invocation could read or write under a DIFFERENT home
than the one it was actually given (the defect this move closes).

Each function gets ONE hostile-ambient test (Home A passed explicitly
while `SELF_LEARN_HOME` names a different Home B — every read must stay
under A, never silently fall back to B) and ONE positive control (the
bare, no-`home` call still uses the ambient home, unchanged from before
this move) — the positive control exists so a regression that makes the
explicit-`home` path a silent no-op cannot hide behind the
hostile-ambient assertion alone (a stub that ignores `home` entirely
and always reads ambient would fail the hostile test, but a stub that
ONLY ever reads ambient regardless of the argument would too — the
positive control instead catches the opposite mistake: a `home` param
that is required, never defaulting to ambient when omitted).

Also covers the one caller-side fix this move makes: `serve.run_forever`
now threads its own `home` into `worker.cache_dir(home)` for its
`cache_dir=None` fallback (previously the bare, ambient
`worker.cache_dir()`).

`worker._autokick_disabled` (already threads `home`; both callers,
`kick` and the follow-on gate in `run`, already pass it) and
`sdksession/children.py` (its functions already take `cache_dir` as a
parameter, never resolve one via an upward `worker.cache_dir()` import)
were VERIFIED against this move's defect class and found already
correct — no code change and no new test for either here; existing
coverage (`test_settings.py::test_worker_autokick_disabled_reads_
config`) already exercises the former.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from self_learn import miner, serve, worker

from test_settings import _write_config  # noqa: F401 -- imported by name, suite convention


# ===================================================================== #
# worker.cache_dir(home)
# ===================================================================== #


def test_cache_dir_hostile_ambient_follows_the_explicit_home(tmp_path, monkeypatch):
    """Home A passed explicitly while `SELF_LEARN_HOME` names Home B —
    the returned namespace must be Home A's digest, never Home B's."""
    home_a = tmp_path / "home-a"
    home_b = tmp_path / "home-b"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    resolved = worker.cache_dir(home_a)
    digest_a = hashlib.sha256(str(home_a).encode("utf-8")).hexdigest()[:8]
    digest_b = hashlib.sha256(str(home_b).encode("utf-8")).hexdigest()[:8]
    assert resolved.name == f"home-{digest_a}"
    assert resolved.name != f"home-{digest_b}"


def test_cache_dir_positive_control_bare_call_uses_the_ambient_home(tmp_path, monkeypatch):
    """No `home` passed — the pre-existing, unchanged behaviour: the
    ambient `SELF_LEARN_HOME` supplies the namespace."""
    home_b = tmp_path / "home-b"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    resolved = worker.cache_dir()
    digest_b = hashlib.sha256(str(home_b).encode("utf-8")).hexdigest()[:8]
    assert resolved.name == f"home-{digest_b}"


# ===================================================================== #
# miner.transcripts_root(home)
# ===================================================================== #


def test_transcripts_root_hostile_ambient_reads_homes_own_config(tmp_path, monkeypatch):
    home_a = tmp_path / "home-a"
    home_b = tmp_path / "home-b"
    monkeypatch.delenv("SELF_LEARN_TRANSCRIPTS_DIR", raising=False)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    _write_config(home_a, "miner", "transcripts_dir", str(tmp_path / "transcripts-a"))
    _write_config(home_b, "miner", "transcripts_dir", str(tmp_path / "transcripts-b"))
    assert miner.transcripts_root(home_a) == tmp_path / "transcripts-a"
    assert miner.transcripts_root(home_b) == tmp_path / "transcripts-b"


def test_transcripts_root_positive_control_bare_call_uses_the_ambient_home(tmp_path, monkeypatch):
    home_b = tmp_path / "home-b"
    monkeypatch.delenv("SELF_LEARN_TRANSCRIPTS_DIR", raising=False)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    _write_config(home_b, "miner", "transcripts_dir", str(tmp_path / "transcripts-b"))
    assert miner.transcripts_root() == tmp_path / "transcripts-b"


# ===================================================================== #
# miner.miner_enabled(home) -- extracted from miner.stale()'s inline check
# ===================================================================== #


def test_miner_enabled_hostile_ambient_reads_homes_own_config(tmp_path, monkeypatch):
    home_a = tmp_path / "home-a"
    home_b = tmp_path / "home-b"
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    _write_config(home_a, "miner", "enabled", False)
    _write_config(home_b, "miner", "enabled", True)
    assert miner.miner_enabled(home_a) is False
    assert miner.miner_enabled(home_b) is True


def test_miner_enabled_positive_control_bare_call_uses_the_ambient_home(tmp_path, monkeypatch):
    home_b = tmp_path / "home-b"
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    _write_config(home_b, "miner", "enabled", False)
    assert miner.miner_enabled() is False


def test_stale_still_calls_miner_enabled_bare_unchanged_by_the_extraction(tmp_path, monkeypatch):
    """The extraction must not change `stale()`'s own observable
    behaviour: it is still called with zero arguments, reading the
    ambient home exactly as the inline check did before extraction."""
    home = tmp_path / "home"
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _write_config(home, "miner", "enabled", False)
    assert miner.stale() is False  # disabled miner never alarms, regardless of last-run age


# ===================================================================== #
# worker._notifications_suppressed(home)
# ===================================================================== #


def test_notifications_suppressed_hostile_ambient_reads_homes_own_config(tmp_path, monkeypatch):
    home_a = tmp_path / "home-a"
    home_b = tmp_path / "home-b"
    monkeypatch.delenv("SELF_LEARN_NO_NOTIFY", raising=False)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    _write_config(home_a, "worker", "no_notify", True)
    _write_config(home_b, "worker", "no_notify", False)
    assert worker._notifications_suppressed(home_a) is True
    assert worker._notifications_suppressed(home_b) is False


def test_notifications_suppressed_positive_control_bare_call_uses_the_ambient_home(
    tmp_path, monkeypatch
):
    home_b = tmp_path / "home-b"
    monkeypatch.delenv("SELF_LEARN_NO_NOTIFY", raising=False)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    _write_config(home_b, "worker", "no_notify", True)
    assert worker._notifications_suppressed() is True


# ===================================================================== #
# serve.run_forever's cache_dir=None fallback -- the one caller-side fix
# ===================================================================== #


def test_run_forever_cache_dir_none_resolves_from_home_not_the_ambient_env(tmp_path, monkeypatch):
    """M-P closes the one caller-side instance of this defect the audit
    found: `run_forever`'s `cache_dir=None` fallback used to call bare
    `worker.cache_dir()` (the ambient home) even though `run_forever`
    already holds its own explicit `home`. `_run_tick` is monkeypatched
    out (a real tick can spawn real miner/worker work) so this isolates
    exactly the one fixed line — which `cache_dir` `run_forever` resolves
    and hands to its own tick loop."""
    home_a = tmp_path / "home-a"
    home_b = tmp_path / "home-b"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    captured: list[Path] = []

    def _fake_tick(home, cache_dir, **kwargs):
        captured.append(cache_dir)
        return []

    monkeypatch.setattr(serve, "_run_tick", _fake_tick)
    serve.run_forever(home_a, tick_secs=0.01, max_ticks=1)
    assert captured == [worker.cache_dir(home_a)]
    assert captured[0] != worker.cache_dir()  # the ambient (home_b) cache dir
