"""The session engine is the only engine (the digest engine was retired on
2026-11-12), and the miner behaviours that used to be tested through the
digest run, tested through the session run.

No model is called: ``session_shim.shim_reader`` stands in for the seam.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from self_learn import cli, miner, settings
from test_session_shim import shim_reader
from self_learn.ledger_ops import create_record
from support import commit_all, make_behavior, make_home

FOLDER = "-home-u-proj"
TYPED_ROW = {"entrypoint": "cli", "promptSource": "typed", "origin": {"kind": "human"}}


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "claude-dir"))


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


@pytest.fixture()
def transcripts(tmp_path, monkeypatch):
    root = tmp_path / "transcripts"
    (root / FOLDER).mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    miner._save_cursors({"__initialized__": "test-fixture"})
    return root


def typed(text):
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **TYPED_ROW}
    )


def agent(text):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


def write_session(root, name, lines):
    path = root / FOLDER / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------- the engine setting


def test_the_default_engine_is_session(home):
    s = settings.by_name("miner.engine")
    assert s.default == "session" and settings.MINER_ENGINES == ("session",)
    assert settings.resolve_setting(home, s) == ("session", "default")


def test_a_config_saying_digest_runs_the_session_path_and_doctor_says_it_once(home, transcripts, monkeypatch, capsys):
    (home / "config.yaml").write_text("miner:\n  engine: digest\n", encoding="utf-8")
    commit_all(home, "config: an old engine value")
    s = settings.by_name("miner.engine")
    assert settings.resolve_setting(home, s)[0] == "session"  # reads as session

    write_session(transcripts, "sess-old-config", [typed("please fix the parser"), agent("fixed the parser")])
    prompts = shim_reader(monkeypatch)
    result = miner.run(home)
    assert result.status == "ok"
    assert "SESSION sess-old-config" in prompts[0]  # a session-engine call was made
    assert miner.read_journal(1)[-1]["engine"] == "session"

    assert cli.main(["doctor", "settings"]) == 0
    rows = [ln for ln in capsys.readouterr().out.splitlines() if " miner.engine " in ln]
    assert len(rows) == 1 and rows[0].startswith("doctor: WARN")
    assert "retired on 2026-11-12" in rows[0] and "runs as session" in rows[0]


def test_a_config_saying_session_reads_clean_in_doctor(home, capsys):
    (home / "config.yaml").write_text("miner:\n  engine: session\n", encoding="utf-8")
    commit_all(home, "config: session")
    assert cli.main(["doctor", "settings"]) == 0
    rows = [ln for ln in capsys.readouterr().out.splitlines() if " miner.engine " in ln]
    assert len(rows) == 1 and rows[0].startswith("doctor: INFO") and "retired" not in rows[0]


def test_engine_digest_is_refused_by_the_cli_and_the_library(home, monkeypatch, capsys):
    with pytest.raises(ValueError, match="only the session engine exists"):
        miner.run(home, engine="digest")
    called = []
    monkeypatch.setattr(miner, "run", lambda *a, **k: called.append(1))
    assert cli.main(["mine", "run", "--engine", "digest"]) == cli.EXIT_USAGE
    assert "the digest engine was retired on 2026-11-12" in capsys.readouterr().err
    assert called == []


def test_config_set_refuses_digest_in_a_sentence(home):
    with pytest.raises(settings.InvalidSettingValueError) as err:
        settings.config_set(home, "miner.engine", "digest")
    assert "session" in str(err.value) and "retired" in str(err.value)


# ------------------------------------- behaviours once tested via the digest run


def test_halt_persists_across_slices(home, transcripts, monkeypatch):
    """A review session still being written when the miner runs stays excluded
    when its tail arrives in the next run's slice."""
    p = write_session(
        transcripts,
        "sess-split",
        [typed("real work"), typed("<command-name>/self-learn:review</command-name> go")],
    )
    prompts = shim_reader(monkeypatch)
    assert miner.run(home).status == "ok"
    assert "real work" in prompts[0]  # positive control: the first run judged the session
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(agent("Card 1: verbatim lesson text that must never be mined") + "\n")
    result = miner.run(home)
    assert result.status == "idle"  # the halted file is skipped without being read
    assert prompts[1].strip() == ""


def test_first_run_initializes_forward_only(home, transcripts, monkeypatch):
    """Night one seeds cursors at EOF and mines nothing; later appends are judged."""
    miner._save_cursors({})  # a fresh machine: not initialized
    old = write_session(transcripts, "sess-history", [typed("old lesson-rich work"), agent("done")])
    write_session(
        transcripts,
        "sess-live-review",
        [typed("work"), typed("<command-name>/self-learn:review</command-name> go")],
    )
    prompts = shim_reader(monkeypatch)
    assert miner.run(home).status == "initialized"
    assert prompts[0].strip() == ""  # nothing was sent
    assert miner.read_journal()[-1]["files_seeded"] == 2
    assert miner.initialized()
    halted = [k for k, v in miner._load_cursors().items() if isinstance(v, dict) and v.get("halt")]
    assert any("sess-live-review" in k for k in halted)
    assert miner.run(home).status == "idle"
    with open(old, "a", encoding="utf-8") as fh:
        fh.write(typed("fresh correction after init") + "\n" + agent("noted") + "\n")
    assert miner.run(home).status == "ok"
    assert "fresh correction after init" in prompts[2]
    assert "· already mined\nYOU: old lesson-rich work" in prompts[2]  # earlier text is context only


def test_watchdog_cooldown_after_a_crashed_run(home, transcripts, monkeypatch):
    """A crashing run must not turn every CLI invocation into a fresh attempt:
    attempts have their own cool-down."""
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "1")
    write_session(transcripts, "sess-cool", [typed("work")])

    def boom(*a, **k):
        raise RuntimeError("engine blew up")

    monkeypatch.setattr(miner, "_run_session_engine", boom)
    assert miner.run(home).status == "failed"
    assert not (miner.miner_dir() / "miner.last-run").is_file()  # the stale alarm stays intact
    spawned = []
    monkeypatch.setattr(miner, "_spawn_run", lambda h, **kw: spawned.append(h) or 1)
    assert miner.maybe_kick(home) == "cooling"
    assert spawned == []
    old = time.time() - miner.ATTEMPT_COOLDOWN_SECS - 60
    os.utime(miner.miner_dir() / "miner.last-attempt", (old, old))
    assert miner.maybe_kick(home) == "spawned"


def test_cli_mine_run_and_status(home, transcripts, monkeypatch, capsys):
    write_session(transcripts, "sess-cli", [typed("work"), agent("done")])
    shim_reader(monkeypatch)
    monkeypatch.setattr(miner.worker, "kick", lambda h, **kw: "disabled")
    assert cli.main(["mine", "run", "--trigger", "timer"]) == 0
    assert "mine run: ok" in capsys.readouterr().out
    assert cli.main(["mine", "status"]) == 0
    assert "trigger=timer" in capsys.readouterr().out
    assert cli.main(["mine", "status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["runs"][-1]["status"] == "ok" and data["stale"] is False


def test_an_open_canary_is_caught_by_a_landed_record_that_matches_it(home):
    miner.plant_canary("always run go vet before committing Go changes", expect="go vet")
    rid = _land_record(home, "always run go vet before committing Go changes")
    miner._score_canaries(home, [rid], set())
    assert miner.read_canaries_summary() == {"planted": 1, "caught": 1, "missed": 0, "open": []}


def test_a_canary_whose_session_was_mined_without_a_match_is_missed(home, monkeypatch):
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-canary-src")
    miner.plant_canary("prefer editing files over rewriting them whole")
    rid = _land_record(home, "an unrelated lesson about rsync flags")
    miner._score_canaries(home, [rid], {"sess-canary-src"})
    summary = miner.read_canaries_summary()
    assert summary["missed"] == 1 and summary["caught"] == 0 and summary["open"] == []


def _land_record(home, title):
    """A pending record the way teach writes one; returns its id."""
    record = make_behavior(trigger=title)
    create_record(home, record)
    return record.id
