"""The steward's `premise_probe` tool shows a lesson's placement premises as
the last daily sweep judged them (premises design lane P2;
S-113; 02 §3a.10.2's `premise_probe` paragraph).

The reader, `premise_sweep.placement_reader`, reads the sweep's cache only.
Every cache here is written by the sweep's own row builder
(`premise_sweep._fact_row`) into a scratch directory; no probe, no
reachability derivation and no model call ever runs. Every ledger is a
scratch sandbox.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from self_learn import ledger_ops, premise_sweep, premises, reachability, steward
from self_learn.premise_sweep import _Fact, _fact_row
from self_learn.premise_tool import PremiseProbeTool
from self_learn.premises import ProbeEnv
from support import make_behavior, make_home

REACH, WRITABLE, INTACT = premises.PLACEMENT_PREMISE_IDS
D1, D2 = "2026-10-29T03:30:00Z", "2026-10-30T03:30:00Z"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc).timestamp()
ROUTED = "2026-09-22T06:24:50Z"
L = "lrn-0000c001"


def lesson(destination: str = "claude-md", routed_at: str = ROUTED, rid: str = L):
    record = make_behavior(record_id=rid)
    record.set_routing({"routed_at": routed_at, "destination": destination, "by": "human"})
    return record


def holds(pid: str, at: str, rid: str = L) -> dict:
    return _fact_row(_Fact(rid, pid, "holds", f"ok:{pid}", "reachable"), at)


def failing(pid: str, at: str, rid: str = L, value: str = "plain") -> dict:
    return _fact_row(
        _Fact(rid, pid, "failing", f"fail:{value}", "not writable",
              detail="the file is tracked by git in a plain host"),
        at,
    )


def unmeasured(pid: str, at: str, rid: str = L) -> dict:
    return _fact_row(_Fact(rid, pid, "unavailable", detail="claude-dir-absent"), at)


def store(cache: Path, rows: list[dict], *, last_sweep: str = D2) -> None:
    history: dict = {}
    for row in rows:
        history.setdefault((row["record"], row["premise"]), []).append(row)
    premise_sweep._store_history(cache, history)
    premise_sweep._store_state(cache, {"last_attempt_at": last_sweep, "last_finished_at": last_sweep})


def readings(cache: Path, record, now: float = NOW) -> dict:
    reader = premise_sweep.placement_reader(cache, now=lambda: now)
    return {r.premise_id: r for r in reader(Path("/nonexistent-ledger"), record)}


def no_probe_env(tmp_path: Path) -> ProbeEnv:
    def runner(argv, env, timeout):
        raise AssertionError(f"no command may run: {argv}")

    return ProbeEnv(home=tmp_path, path_env="/nonexistent-bin", runner=runner, runtime_dir=None)


class TestTheReader:
    def test_cached_rows_give_their_verdicts_with_the_sweeps_time(self, tmp_path):
        cache = tmp_path / "cache"
        store(cache, [
            holds(REACH, D1), holds(REACH, D2),
            failing(WRITABLE, D1), failing(WRITABLE, D2),
            holds(INTACT, D1), failing(INTACT, D2),
            unmeasured(REACH, D2, rid="lrn-0000c002"), unmeasured(WRITABLE, D2, rid="lrn-0000c002"),
        ])
        got = readings(cache, lesson())
        assert set(got) == {REACH, WRITABLE, INTACT}
        assert got[REACH].verdict == "holds"
        assert f"as of the sweep at {D2}" in got[REACH].detail
        assert got[WRITABLE].verdict == "moved"
        assert f"confirmed: failing on 2 sweeps running since {D1}" in got[WRITABLE].detail
        assert "tracked by git" in got[WRITABLE].detail
        assert got[INTACT].verdict == "moved"
        assert "first sight: the next sweep confirms it" in got[INTACT].detail
        other = readings(cache, lesson(destination="new-skill", rid="lrn-0000c002"))
        assert {r.verdict for r in other.values()} == {"unavailable"}
        assert "could not be measured" in other[REACH].detail and "claude-dir-absent" in other[REACH].detail

    def test_no_rows_is_unavailable_and_names_the_last_sweep(self, tmp_path):
        cache = tmp_path / "cache"
        store(cache, [], last_sweep=D2)
        got = readings(cache, lesson())
        assert got[REACH].verdict == "unavailable"
        assert f"no sweep has measured it yet; last sweep {D2}" in got[REACH].detail
        never = readings(tmp_path / "no-cache", lesson())
        assert "last sweep never" in never[REACH].detail

    def test_a_lesson_placed_again_after_its_rows_is_unavailable(self, tmp_path):
        cache = tmp_path / "cache"
        store(cache, [failing(WRITABLE, D1), failing(WRITABLE, D2)])
        assert readings(cache, lesson())[WRITABLE].verdict == "moved"  # control
        moved_again = readings(cache, lesson(routed_at="2026-10-30T09:00:00Z"))[WRITABLE]
        assert moved_again.verdict == "unavailable"
        assert "placed again" in moved_again.detail and "next sweep measures the new placement" in moved_again.detail

    def test_rows_from_before_a_reroute_never_count_toward_confirmation(self, tmp_path):
        cache = tmp_path / "cache"
        store(cache, [failing(WRITABLE, D1), failing(WRITABLE, D2)])
        between = readings(cache, lesson(routed_at="2026-10-29T12:00:00Z"))[WRITABLE]
        assert between.verdict == "moved" and "first sight" in between.detail

    def test_a_reading_older_than_48_hours_says_it_is_stale(self, tmp_path):
        cache = tmp_path / "cache"
        store(cache, [holds(REACH, D1), holds(REACH, D2)])
        fresh = readings(cache, lesson(), now=NOW)[REACH]
        assert "stale" not in fresh.detail  # control
        old = readings(cache, lesson(), now=NOW + 3 * 86400)[REACH]
        assert old.verdict == "holds" and f"stale: the sweep has not measured it since {D2}" in old.detail

    def test_a_lesson_without_placement_premises_has_none(self, tmp_path):
        cache = tmp_path / "cache"
        store(cache, [holds(REACH, D2)])
        assert readings(cache, lesson(destination="reference")) == {}


class TestThroughTheTool:
    def _tool(self, tmp_path, cache):
        home = make_home(tmp_path)
        return home, PremiseProbeTool(
            home, env=no_probe_env(tmp_path), placement=premise_sweep.placement_reader(cache, now=lambda: NOW),
        )

    def test_a_new_skill_lesson_has_no_intact_line_and_asking_for_it_is_refused(self, tmp_path):
        cache = tmp_path / "cache"
        store(cache, [holds(REACH, D2), holds(WRITABLE, D2), holds(INTACT, D2)])
        home, tool = self._tool(tmp_path, cache)
        ledger_ops.create_record(home, lesson(destination="new-skill"))
        reply = tool.dispatch({"lesson": L})
        assert not reply.is_error, reply.text
        assert f"{REACH}: holds" in reply.text and f"{WRITABLE}: holds" in reply.text
        assert INTACT not in reply.text
        refused = tool.dispatch({"lesson": L, "premise": INTACT})
        assert refused.is_error and f"{L} has no placement premise {INTACT}" in refused.text

    def test_the_answer_comes_from_the_cache_alone(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        store(cache, [failing(WRITABLE, D1), failing(WRITABLE, D2)])
        home, tool = self._tool(tmp_path, cache)
        ledger_ops.create_record(home, lesson())
        before = tool.dispatch({"lesson": L, "premise": WRITABLE}).text

        def boom(*a, **k):
            raise RuntimeError("live derivation must not run")

        monkeypatch.setattr(premise_sweep, "_placement_rows", boom)
        monkeypatch.setattr(reachability, "reachability_rows", boom)
        after = tool.dispatch({"lesson": L, "premise": WRITABLE})
        assert not after.is_error and after.text == before
        assert f"{WRITABLE}: moved" in after.text


class TestTheStewardsSession:
    def test_the_stewards_tool_answers_with_placement_readings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        ledger_ops.create_record(home, lesson())
        cache = premise_sweep.default_cache_dir(home)
        assert str(cache).startswith(str(tmp_path))  # control: a scratch cache
        store(cache, [holds(REACH, D2), failing(WRITABLE, D1), failing(WRITABLE, D2), holds(INTACT, D2)])
        spec = steward._session_spec(home, tmp_path / "run", "a brief", label="t")
        assert spec.mcp_toolset is not None
        (tool,) = spec.mcp_toolset.tools
        reply = asyncio.run(tool.handler({"lesson": L}))
        assert not reply.is_error, reply.text
        assert f"{WRITABLE}: moved" in reply.text
        assert "not available" not in reply.text
