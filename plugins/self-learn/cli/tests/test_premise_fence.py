"""No premise probe reads the kept copies of model sessions (premises design
lane P7; S-NEXT-probes-chain; 02 §3a.10.2).

The steward's session may not read `<cache>/sessions/` (its
`Containment.read_denied`). Its `premise_probe` tool used to ignore that
fence, so a `file-match contains` was a yes/no oracle on another run's
session copy. Now the tool honours the session's fence, and the nightly
sweep and the `premises` verb's apply-time probes honour the same
directory (`premise_sweep.fenced_roots`), so a premise written into it
cannot leak a bit a night either.

Every ledger and cache is a scratch sandbox (`XDG_CACHE_HOME` points into
`tmp_path`); no command runs and no model is called.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from self_learn import premise_sweep, premises, steward, verbs
from self_learn.premise_tool import PremiseProbeTool
from self_learn.premises import ProbeEnv
from support import commit_all, make_behavior, make_env, make_home

T0 = datetime(2026, 10, 31, 3, 30, tzinfo=timezone.utc).timestamp()
SECRET_WORD = "zebra-quartz"


def no_command_env(tmp_path: Path) -> ProbeEnv:
    def runner(argv, env, timeout):
        raise AssertionError(f"no command may run: {argv}")

    return ProbeEnv(home=tmp_path, path_env="/nonexistent-bin", runner=runner, runtime_dir=None)


@pytest.fixture
def fenced(tmp_path, monkeypatch):
    """A scratch ledger, its cache's sessions folder with one session copy
    in it, and a file of the same text outside the fence."""
    root = os.path.realpath(tmp_path.parent)
    if premises.credential_path_problem(root, reads_content=True) is not None:
        pytest.skip(f"the temporary root {root} sits under a path premises refuse")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    (sessions,) = premise_sweep.fenced_roots(home)
    copy = Path(sessions) / "steward" / "run-0000" / "session.jsonl"
    copy.parent.mkdir(parents=True)
    copy.write_text(f'{{"text": "{SECRET_WORD}"}}\n')
    outside = tmp_path / "outside" / "notes.txt"
    outside.parent.mkdir()
    outside.write_text(f"{SECRET_WORD}\n")
    return home, copy, outside


def contains(path: Path) -> dict:
    return {"kind": "file-match", "path": str(path), "contains": SECRET_WORD}


class TestTheTool:
    def test_a_probe_into_the_fenced_root_is_refused(self, fenced, tmp_path):
        home, copy, outside = fenced
        tool = PremiseProbeTool(
            home, env=no_command_env(tmp_path), denied_roots=premise_sweep.fenced_roots(home),
        )
        allowed = tool.dispatch({"probe": contains(outside)})
        assert not allowed.is_error and '"present"' in allowed.text  # control: the probe works
        refused = tool.dispatch({"probe": contains(copy)})
        assert "state: unavailable" in refused.text
        assert "may not read" in refused.text
        assert "present" not in refused.text and "absent" not in refused.text

    def test_every_kind_that_touches_a_path_is_fenced(self, fenced, tmp_path):
        home, copy, _outside = fenced
        tool = PremiseProbeTool(
            home, env=no_command_env(tmp_path), denied_roots=premise_sweep.fenced_roots(home),
        )
        for probe in (
            {"kind": "path", "path": str(copy)},
            {"kind": "path", "path": str(copy.parent / "no-such-session.jsonl")},
            {"kind": "json-key", "path": str(copy), "key": "text"},
            {"kind": "git-file", "repo": str(copy.parent), "path": "a.txt", "lines": "1-1"},
        ):
            text = tool.dispatch({"probe": probe}).text
            assert "may not read" in text, (probe, text)

    def test_a_link_into_the_fenced_root_is_refused_like_the_root(self, fenced, tmp_path):
        home, copy, _outside = fenced
        link_dir = tmp_path / "innocent"
        link_dir.symlink_to(copy.parent)
        tool = PremiseProbeTool(
            home, env=no_command_env(tmp_path), denied_roots=premise_sweep.fenced_roots(home),
        )
        text = tool.dispatch({"probe": contains(link_dir / copy.name)}).text
        assert "may not read" in text, text

    def test_the_stewards_session_tool_honours_its_read_fence(self, fenced, tmp_path):
        home, copy, outside = fenced
        spec = steward._session_spec(home, tmp_path / "run", "a brief", label="t")
        assert spec.containment.read_denied == premise_sweep.fenced_roots(home)  # one directory
        assert spec.mcp_toolset is not None
        (tool,) = spec.mcp_toolset.tools
        allowed = asyncio.run(tool.handler({"probe": contains(outside)}))
        assert '"present"' in allowed.text  # control
        refused = asyncio.run(tool.handler({"probe": contains(copy)}))
        assert "may not read" in refused.text, refused.text


class TestTheOtherWaysIn:
    def test_the_sweep_does_not_read_a_written_premise_into_the_fence(self, tmp_path, monkeypatch):
        root = os.path.realpath(tmp_path.parent)
        if premises.credential_path_problem(root, reads_content=True) is not None:
            pytest.skip(f"the temporary root {root} sits under a path premises refuse")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        e = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
        (sessions,) = premise_sweep.fenced_roots(e.ledger)
        copy = Path(sessions) / "s.jsonl"
        copy.parent.mkdir(parents=True)
        copy.write_text(SECRET_WORD)
        resolved = e.ledger / "skills" / "s" / "resolved"
        resolved.mkdir(parents=True, exist_ok=True)
        record = make_behavior(scope="skill:s", record_id="lrn-0000d001")
        record.set_routing({"routed_at": "2026-09-22T06:24:50Z", "destination": "skill-md", "by": "human"})
        record.set_status("routed")
        record.set_premises([
            {"id": "p1", "claim": "fenced", "probe": {"kind": "path", "path": str(copy)}},
            {"id": "p2", "claim": "control", "probe": {"kind": "path", "path": str(tmp_path)}},
        ])
        record.write(resolved / "lrn-0000d001.md")
        commit_all(e.ledger, "seed")
        cache = tmp_path / "cache"
        premise_sweep.run(
            e.ledger, cache, now=T0, env=no_command_env(tmp_path), claude_dir=tmp_path / "no-claude",
        )
        history = premise_sweep.read_history(cache)
        assert history[("lrn-0000d001", "p2")][-1]["shown"] == "dir"  # control: probes ran
        fenced_row = history[("lrn-0000d001", "p1")][-1]
        assert fenced_row["state"] == premises.OBS_UNAVAILABLE
        assert "may not read" in fenced_row["reason"]

    def test_the_premises_verbs_probes_are_fenced(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        home = make_home(tmp_path)
        env = verbs._premise_probe_env(home)
        assert env.denied_roots == premise_sweep.fenced_roots(home)
        assert env.ledger_home == home


class TestTheEnv:
    def test_an_injected_envs_own_roots_are_kept(self, tmp_path):
        base = ProbeEnv(home=tmp_path, denied_roots=("/a",))
        tool = PremiseProbeTool(tmp_path, env=base, denied_roots=("/b",))
        assert tool.probe_env().denied_roots == ("/a", "/b")
        assert base.denied_roots == ("/a",)

    def test_a_sibling_with_a_shared_prefix_is_not_fenced(self, tmp_path):
        fence = tmp_path / "sessions"
        sibling = tmp_path / "sessions-other" / "f.txt"
        sibling.parent.mkdir()
        sibling.write_text(SECRET_WORD)
        env = ProbeEnv(home=tmp_path, path_env="/nonexistent-bin", denied_roots=(str(fence),))
        obs = premises.run_probe(contains(sibling), env)
        assert obs.state == premises.OBS_OK and obs.shown == premises.PRESENT, obs
