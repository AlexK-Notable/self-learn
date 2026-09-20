"""Sizing knobs (2026-09-20): how much goes into one model call is a
setting, not a constant in the code.

Five numbers moved into the settings registry on that day -- the worker's
lessons per call, the miner's three input sizes, and the miner reader's
timeout -- behind one helper, `settings.sizing_knob`, so the next one is
a few lines. Two things are checked here: the helper itself, and that a
value written in `config.yaml` really reaches the code that uses it
(a registered setting nothing reads is worse than a constant).
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from self_learn import miner, settings, worker
from self_learn.ledger_ops import create_record
from support import commit_all, make_behavior, make_home

KNOBS = (
    "worker.batch_cap",
    "miner.message_chars",
    "miner.session_chars",
    "miner.run_chars",
    "miner.reader_timeout_secs",
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    for name in KNOBS:
        monkeypatch.delenv(settings.by_name(name).env_var, raising=False)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


@pytest.fixture()
def elsewhere(tmp_path, monkeypatch):
    """Point SELF_LEARN_HOME at an empty directory, so the ledger a test
    passes by argument is the only way its config.yaml can be reached."""
    other = tmp_path / "elsewhere.d"
    other.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(other))
    return other


def configure(home, section: str, **values) -> None:
    """Write `section`'s keys into the ledger's config.yaml and commit it."""
    lines = [f"{section}:"] + [f"  {key}: {value}" for key, value in values.items()]
    (home / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    commit_all(home, f"config: {section}")


# ------------------------------------------------------------ the helper


def test_a_knob_takes_its_section_key_env_var_and_kind_from_its_name_and_default():
    knob = settings.sizing_knob("overseer.cases_per_call", default=12, description="d")
    assert (knob.config_section, knob.config_key) == ("overseer", "cases_per_call")
    assert knob.env_var == "SELF_LEARN_OVERSEER_CASES_PER_CALL"
    assert knob.kind == "int"
    assert knob.direction == "config-first"
    assert settings.sizing_knob("a.b", default=1.5, description="d").kind == "float"
    assert settings.sizing_knob("a.b", default=3, description="d", env_var="OLD_NAME").env_var == "OLD_NAME"


@pytest.mark.parametrize("name", ["nodot", ".key", "section."])
def test_a_knob_name_must_be_section_dot_key(name):
    with pytest.raises(ValueError):
        settings.sizing_knob(name, default=1, description="d")


@pytest.mark.parametrize("default", [0, -1, 0.0, True])
def test_a_knob_default_must_be_a_number_above_zero(default):
    with pytest.raises(ValueError):
        settings.sizing_knob("a.b", default=default, description="d")


def test_the_five_knobs_are_registered_with_the_numbers_the_code_had():
    expected = {
        "worker.batch_cap": 15,
        "miner.message_chars": 2_000,
        "miner.session_chars": 60_000,
        "miner.run_chars": 400_000,
        "miner.reader_timeout_secs": 900.0,
    }
    assert {name: settings.by_name(name).default for name in KNOBS} == expected
    # the module constants are copies of those defaults, not second literals
    assert worker.BATCH_CAP == 15
    assert (miner.MAX_TEXT_CHARS, miner.MAX_DIGEST_CHARS, miner.MAX_PROMPT_DIGESTS_CHARS) == (2_000, 60_000, 400_000)
    assert miner.INVOKE_TIMEOUT_SECS == 900.0


@pytest.mark.parametrize("name", KNOBS)
def test_a_value_that_is_not_above_zero_is_refused_and_the_default_stands(home, name):
    setting = settings.by_name(name)
    for bad in ("0", "-4", "banana"):
        configure(home, setting.config_section, **{setting.config_key: bad})
        value, source = settings.resolve_setting(home, setting)
        assert (value, source) == (setting.default, "default"), bad


def test_the_typed_readers_refuse_a_setting_of_another_kind(home):
    assert settings.resolve_int(home, "worker.batch_cap") == 15
    assert settings.resolve_float(home, "miner.reader_timeout_secs") == 900.0
    assert settings.resolve_float(home, "worker.batch_cap") == 15.0  # an int reads as a float
    with pytest.raises(TypeError):
        settings.resolve_int(home, "miner.reader_timeout_secs")
    with pytest.raises(TypeError):
        settings.resolve_float(home, "miner.enabled")
    with pytest.raises(KeyError):
        settings.resolve_int(home, "no.such_setting")


# ------------------------------------------- each knob reaches its use site


def test_the_worker_takes_as_many_lessons_per_call_as_config_says(home, elsewhere):
    for i in range(6):
        create_record(
            home,
            make_behavior(record_id=f"lrn-000000{i:02x}", created_at=f"2026-07-{1 + i:02d}T00:00:00Z"),
        )
    commit_all(home, "six pending")
    batch, leftovers, _total, _per_bucket = worker._enumerate(home)
    assert (len(batch), leftovers) == (6, 0)  # positive control: all six are eligible under the default 15
    configure(home, "worker", batch_cap=4)
    assert worker.batch_cap(home) == 4
    batch, leftovers, _total, _per_bucket = worker._enumerate(home)
    assert (len(batch), leftovers) == (4, 2)


def test_every_digest_limit_is_a_registered_miner_setting_with_the_same_default():
    for f in dataclasses.fields(miner.DigestLimits):
        assert settings.by_name(f"miner.{f.name}").default == f.default, f.name


def test_the_miner_reads_all_three_input_sizes_from_config(home, elsewhere):
    assert miner.digest_limits(home) == miner.DigestLimits(2_000, 60_000, 400_000)
    configure(home, "miner", message_chars=300, session_chars=5_000, run_chars=90_000)
    assert miner.digest_limits(home) == miner.DigestLimits(300, 5_000, 90_000)


def _user(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}})


def _slice(tmp_path, name: str, lines: list[str]) -> miner.SessionSlice:
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return miner.SessionSlice(path=path, session_id=name, project="-home-u-proj", start_line=0, lines=lines)


def test_a_message_is_clipped_at_the_message_limit(tmp_path):
    s = _slice(tmp_path, "sess-long-message", [_user("HEAD" + "m" * 1_000 + "TAIL")])
    whole, _halt = miner.digest_transcript(s)
    assert whole is not None and "[clipped]" not in whole  # positive control: 1,008 characters fit the default 2,000
    clipped, _halt = miner.digest_transcript(s, miner.DigestLimits(message_chars=100))
    assert clipped is not None and "[clipped]" in clipped
    assert "HEAD" in clipped and "TAIL" in clipped and len(clipped) < 300


def test_a_session_is_clipped_at_the_session_limit(tmp_path):
    s = _slice(tmp_path, "sess-many-messages", [_user(f"message number {i} " + "s" * 80) for i in range(40)])
    whole, _halt = miner.digest_transcript(s)
    assert whole is not None and "session digest clipped" not in whole  # positive control
    clipped, _halt = miner.digest_transcript(s, miner.DigestLimits(session_chars=500))
    assert clipped is not None and clipped.endswith("…[session digest clipped]")
    header, _, body = clipped.partition("\n")
    assert header.startswith("=== session sess-many-messages")
    assert len(body) == 500 + len("\n…[session digest clipped]")


@pytest.fixture()
def mining(home, tmp_path, monkeypatch):
    """A transcripts root the miner will scan and a stand-in for the model
    call that records each prompt. Returns (write_session, prompts)."""
    root = tmp_path / "transcripts"
    (root / "-home-u-proj").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    miner._save_cursors({"__initialized__": "test-fixture"})
    prompts: list[str] = []

    def reader(h, prompt):
        prompts.append(prompt)
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps({"candidates": [], "fires": []}), encoding="utf-8")
        return out

    monkeypatch.setattr(miner, "_invoke_reader", reader)

    def write_session(name: str, lines: list[str]) -> None:
        (root / "-home-u-proj" / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return write_session, prompts


def test_a_real_run_clips_messages_and_sessions_at_the_sizes_in_config(home, mining):
    """The two sizes `run` does not apply itself: it hands them to
    `digest_transcript`. Without that hand-off a config value would be read
    and then used by nothing."""
    write_session, prompts = mining
    write_session("sess-long-message", [_user("HEAD" + "m" * 1_000 + "TAIL")])
    write_session("sess-many-messages", [_user(f"message number {i} " + "s" * 80) for i in range(40)])
    assert miner.run(home).status == "ok"
    assert "sess-long-message" in prompts[0] and "sess-many-messages" in prompts[0]
    assert "[clipped]" not in prompts[0] and "session digest clipped" not in prompts[0]  # positive control: defaults clip neither

    write_session("sess-long-message-2", [_user("HEAD" + "m" * 1_000 + "TAIL")])
    write_session("sess-many-messages-2", [_user(f"message number {i} " + "s" * 80) for i in range(40)])
    configure(home, "miner", message_chars=200, session_chars=1_500)
    assert miner.run(home).status == "ok"
    assert "sess-long-message-2" in prompts[1] and "sess-many-messages-2" in prompts[1]
    assert "m …[clipped]… m" in prompts[1]  # the 1,008-character message, cut to 200
    assert "…[session digest clipped]" in prompts[1]  # the ~4,000-character session, cut to 1,500


def test_a_run_stops_adding_sessions_at_the_run_limit(home, mining):
    write_session, prompts = mining
    for name in ("sess-one", "sess-two", "sess-three"):
        write_session(name, [_user(f"{name} says " + "r" * 400)])
    configure(home, "miner", run_chars=1_000)  # each digest is ~460 characters: two fit, the third waits
    assert miner.run(home).status == "ok"
    entry = miner.read_journal(limit=1)[-1]
    assert (entry["sessions_scanned"], entry["deferred_files"]) == (2, 1)
    assert sum(f"=== session {n} " in prompts[0] for n in ("sess-one", "sess-two", "sess-three")) == 2
    # the session that waited is picked up by the next run, not lost
    assert miner.run(home).status == "ok"
    entry = miner.read_journal(limit=1)[-1]
    assert (entry["sessions_scanned"], entry["deferred_files"]) == (1, 0)


def test_the_reader_timeout_is_read_from_config(home, elsewhere, monkeypatch):
    assert miner.reader_timeout_secs(home) == 900.0
    monkeypatch.setenv("SELF_LEARN_READER_TIMEOUT_SECS", "120")
    assert miner.reader_timeout_secs(home) == 120.0
    configure(home, "miner", reader_timeout_secs=45)
    assert miner.reader_timeout_secs(home) == 45.0  # config.yaml outranks the env var
