"""Sweep 2, R4 (2026-09-27): one record file whose frontmatter does not
load costs that file, never the run around it.

Before the fix `Record.from_text` let the loader's own exception (ruamel's
`YAMLError`, a `ValueError` from an impossible date, a `TypeError` from a
list where a scalar belongs) escape unwrapped, so every reader that catches
`RecordError` -- the miner's prompt and landing, the worker before its model
call, `recompile` -- crashed its whole run on one such file. Each test here
seeds one good record beside the bad file and asserts the good one still
comes through (the positive control), then that the bad one is skipped and,
where the reader has a channel for it, named.
"""

from __future__ import annotations

import pytest

from self_learn import import_common, miner, verbs, worker
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import FrontmatterLoadError, Record, RecordError, ValidationError
from support import commit_all, make_behavior, make_env, proposal_dict


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER", "0")


#: A token that must never be echoed back by an error message: the loader's
#: own text quotes the source, which can hold anything a lesson holds.
_SECRETISH = "zq" + "Xv7" + "Lw9" + "Kp"

#: Every shape probed on 2026-09-27, each a different loader exception.
_BAD_HEADERS = {
    "unclosed-bracket": f"---\nid: [{_SECRETISH}\n---\n\nbody\n",
    "duplicate-key": f"---\nid: {_SECRETISH}\nid: {_SECRETISH}\n---\n\nbody\n",
    "conflict-markers": (
        f"---\n<<<<<<< Updated upstream\nid: {_SECRETISH}\n=======\n---\n\nbody\n"
    ),
    "impossible-date": f"---\ncreated: 2026-13-45\nnote: {_SECRETISH}\n---\n\nbody\n",
    "bad-int-tag": f"---\nid: !!int {_SECRETISH}\n---\n\nbody\n",
    "tab-indent": f"---\na: 1\n\tb: {_SECRETISH}\n---\n\nbody\n",
}


def _good_text() -> str:
    return make_behavior(record_id="lrn-9e000001").to_text()


def test_a_good_record_still_parses():
    """Positive control for the wrap below: the same entry point on a
    well-formed record returns it."""
    assert Record.from_text(_good_text()).id == "lrn-9e000001"


@pytest.mark.parametrize("shape", sorted(_BAD_HEADERS))
def test_a_header_that_does_not_load_is_a_record_error(shape):
    with pytest.raises(FrontmatterLoadError) as info:
        Record.from_text(_BAD_HEADERS[shape])
    assert isinstance(info.value, ValidationError)
    assert isinstance(info.value, RecordError)
    assert "frontmatter does not load" in str(info.value)
    # never the file's own text
    assert _SECRETISH not in str(info.value)


@pytest.mark.parametrize("key,value", [("status", "[x]"), ("type", "{a: 1}")])
def test_a_value_of_the_wrong_type_is_a_record_error(key, value):
    """The same crash class one step later: a list or mapping where a
    scalar belongs reached a set-membership check and raised TypeError."""
    lines = _good_text().split("\n")
    out = [f"{key}: {value}" if line.startswith(f"{key}:") else line for line in lines]
    assert out != lines  # the key really was replaced
    with pytest.raises(ValidationError, match="wrong type"):
        Record.from_text("\n".join(out))


def _ledger_with_one_bad_resolved(tmp_path, monkeypatch, *, routed_good: bool = False):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    home = env.ledger
    good = make_behavior(record_id="lrn-9e000001")
    create_record(home, good)  # pending, fine
    if routed_good:
        create_record(home, make_behavior(record_id="lrn-9e000002"))
        write_proposal(home, "lrn-9e000002", proposal_dict(scope="skill:s"))
        commit_all(home, "seed routed")
        verbs.route(home, "lrn-9e000002", dest="skill-md", no_push=True)
    resolved = home / "skills" / "s" / "resolved"
    resolved.mkdir(exist_ok=True)
    bad = resolved / "lrn-9e0000ff.md"
    bad.write_text(_BAD_HEADERS["unclosed-bracket"], encoding="utf-8")
    commit_all(home, "one resolved file that does not load")
    return env, bad


def test_miner_prompt_indexes_skip_and_name_the_file(tmp_path, monkeypatch):
    env, bad = _ledger_with_one_bad_resolved(tmp_path, monkeypatch, routed_good=True)
    corrupt: list = []
    ledger_index = miner._ledger_index(env.ledger, corrupt)
    canon_index = miner._canon_index(env.ledger, corrupt)
    # positive control: the good records are indexed
    assert "lrn-9e000001" in ledger_index
    assert "lrn-9e000002" in canon_index
    assert "lrn-9e0000ff" not in ledger_index + canon_index
    # named, once per sweep, through the journal's `corrupt_records` channel
    assert corrupt == [bad, bad]


def test_miner_landing_readers_skip_the_file(tmp_path, monkeypatch):
    env, _bad = _ledger_with_one_bad_resolved(tmp_path, monkeypatch)
    assert miner._find_record(env.ledger, "lrn-9e0000ff") is None
    found = miner._find_record(env.ledger, "lrn-9e000001")
    assert found is not None and found[0].id == "lrn-9e000001"
    assert isinstance(import_common.existing_origins(env.ledger), set)


def test_worker_run_reaches_its_model_call_and_names_the_file(tmp_path, monkeypatch):
    env, bad = _ledger_with_one_bad_resolved(tmp_path, monkeypatch)
    calls: list = []
    monkeypatch.setattr(worker, "_invoke_claude", lambda *a, **k: calls.append(1))
    worker._UNREADABLE_LOGGED.clear()
    assert worker._enumerate(env.ledger)[0], "the pending record must be queued"
    worker.run(env.ledger, no_push=True)
    assert calls, "the worker must get past the bad file to its model call"
    log_text = worker._p("worker.log").read_text(encoding="utf-8")
    assert f"skipped unreadable record {bad}" in log_text


def test_recompile_repairs_the_good_target_and_names_the_bad_file(tmp_path, monkeypatch):
    env, bad = _ledger_with_one_bad_resolved(tmp_path, monkeypatch, routed_good=True)
    skill_md = env.host / "plugins/s-plugin/skills/s/SKILL.md"
    text = skill_md.read_text()
    assert "lrn-9e000002" in text
    skill_md.write_text(text[: text.index(BEGIN_MARKER)] + BEGIN_MARKER + "\n" + END_MARKER + "\n")
    commit_all(env.host, "drift")
    result = verbs.recompile(env.ledger, no_push=True)
    assert "lrn-9e000002" in skill_md.read_text()  # repaired
    assert any(str(bad) in w and "not readable as a record" in w for w in result.warnings)


def test_the_analyst_shared_candidate_pool_skips_without_writing_worker_log(
    tmp_path, monkeypatch
):
    """The candidate pool is shared with the analyst's single-record path,
    which LG7 forbids from growing worker.log: it skips the bad file
    silently (worker.run names it through the recurrence pass)."""
    env, _bad = _ledger_with_one_bad_resolved(tmp_path, monkeypatch, routed_good=True)
    worker._UNREADABLE_LOGGED.clear()
    entry = worker._enumerate(env.ledger)[0][0]
    log_path = worker._p("worker.log")
    before = log_path.read_bytes() if log_path.exists() else b""
    # every pool member that shares a token scores: the positive control
    # below then shows exactly what the pool holds
    monkeypatch.setattr(worker, "pair_similarity", lambda *a, **k: 1.0)
    candidates = worker.cluster_candidates(env.ledger, [entry])
    # positive control: the good routed record is still in the pool
    assert "lrn-9e000002" in repr(candidates[entry.record.id])
    after = log_path.read_bytes() if log_path.exists() else b""
    assert after == before
