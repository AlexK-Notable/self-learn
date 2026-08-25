"""U-attrib acceptance criteria (docs/specs/self-learn/drafts/
u-attrib-producer-attribution-spec.md §4): NS1-6, GR1-4, IN1-11, RT1-8,
CP2-10, SW1-2, OB1-4, HY1-4 -- 47 of the spec's 49 criteria as pytest
functions. CP1 ("the whole shipped suite is green") and HY3 ("pyright is
clean") are both explicitly instrument-only in the spec's own words
("Broken: running it. No mutation is listed; the instrument is the
suite.") -- satisfied by the full `pytest`/`pyright` runs recorded in the
build report, not by a function here.

Fixtures reused from test_worker.py (`env`, `claude_shim`, `seed_pending`,
`shim_writes`, `PROPOSAL_YAML_TEMPLATE`, `_proposal_yaml`, `Env`) and
test_repair.py (`_valid_trace`, `_dump`, `_write_script`, `_record_for`,
`_stamp_sha`, `_foreign_script`, `_defect_script`, `_next_run_scripts`) --
imported by NAME, not redefined: pytest resolves a fixture by the name
bound in the requesting module's namespace regardless of which module
defines the function (test_repair.py's own docstring states this
convention first).

Every fixture below that says "the model writes X" means "the shim
writes X into `stage_dir()`"; every fixture that says "a concurrent
producer writes Y" means "the shim writes Y into a bucket's
`proposals/`, standing in for the attended session" (§4's own framing,
verbatim).
"""

from __future__ import annotations

import inspect
import json
import os
import re
from pathlib import Path

import pytest

from self_learn import cli, worker
from self_learn.ledger_ops import (
    ProposalError,
    create_record,
    read_proposal,
)
from self_learn.normalize import sha_anchor
from self_learn.records import Record

from support import commit_all, git, hook_proposal_fields, make_behavior, make_env, proposal_dict

from test_worker import (  # noqa: F401 -- fixtures resolved by name
    PROPOSAL_YAML_TEMPLATE,
    Env,
    claude_cli_shim_worker,
    env,
    seed_pending,
    shim_writes,
    _proposal_yaml,
)
from test_repair import (  # noqa: F401 -- fixtures/helpers resolved by name
    _defect_script,
    _dump,
    _foreign_script,
    _next_run_scripts,
    _record_for,
    _stamp_sha,
    _t4_missing_target,
    _t4_target_fixed,
    _valid_trace,
    _write_script,
)


_FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"


def _simple_shim(tmp_path, monkeypatch) -> None:
    """A minimal single-invocation driver (U-cleanup-A migration: was a
    bash PATH shim, `test_composer.py`'s own idiom before ITS migration)
    for the handful of criteria below that need a bespoke multi-bucket
    sandbox `claude_shim` cannot build (it is wired to the single-skill
    `env` fixture). Routes `worker.run()` through `SdkBackend` -> `tests/
    fixtures/fake_claude.py`'s `shim_script` scenario, which interprets
    the SAME `$CLAUDE_SHIM_SCRIPT` raw-text env-var idiom the bash shim
    used to run directly."""
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(_FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "shim_script")


#: A schema-valid but NON-matching record_sha for seeding a PRE-EXISTING
#: destination BEFORE a run starts. Using the record's real (matching)
#: sha there would make `is_unanalyzed` read the record as already
#: fresh and exclude it from the batch entirely -- silently breaking
#: every fixture that needs the record to BOTH already have a
#: valid-and-stamped destination AND still be something the model is
#: asked to analyze this window (measured: this is what IN4's "stale
#: stamped destination" shape describes, and every decline/foreign
#: fixture below that pre-seeds a destination needs the same shape).
#: 12 hex chars -- `sha_anchor()`'s own real output length
#: (`sha256:<12hex>`), deliberately SHORT of the secret scanner's
#: 48-char high-entropy-hex threshold (a pure pattern match, no real
#: entropy calculation -- a 64-char placeholder here would get any
#: fixture that lets this value reach a scanned file deleted as a scan
#: hit before the criterion ever gets to assert anything).
_STALE_SHA = "sha256:000000000000"


class _HomeOnly:
    """A stand-in with just a `.home` attribute -- all `_valid_trace`
    needs -- for the ad hoc multi-bucket sandboxes below that do not
    build a full test_worker.Env."""

    def __init__(self, home: Path) -> None:
        self.home = home


# ===================================================================== #
# NS -- the namespace
# ===================================================================== #


def test_ns1_stage_cleared_at_s1_and_litter_never_lands(env, claude_cli_shim_worker, monkeypatch):
    """NS1 -- the stage is cleared at S1, and its litter never lands.
    Broken: MA1 (drop the S1 clear) -- a crashed previous run's stale
    proposal would land as if THIS run's model wrote it."""
    rid = seed_pending(env)
    stage = worker.stage_dir()
    stage.mkdir(parents=True, exist_ok=True)
    stale_valid = stage / f"{rid}.yaml"
    stale_valid.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    junk = stage / "leftover-junk.txt"
    junk.write_text("litter from a crashed run\n", encoding="utf-8")

    result = worker.run(env.home)

    assert not stale_valid.exists()
    assert not junk.exists()
    assert not (env.proposals / f"{rid}.yaml").exists()
    assert rid not in result.proposed


def test_ns2_installs_at_resolved_destination_in_the_right_bucket(tmp_path, monkeypatch):
    """NS2 -- two batch records in two DIFFERENT buckets; each staged
    proposal lands at its own bucket's proposals/, stamped; both are
    named in `result.proposed` and both buckets in `result.buckets`.
    Broken: MA2 (a resolver that returns the first bucket for
    everything)."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    sandbox = make_env(tmp_path, skills=("s", "t"))
    home = sandbox.ledger
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _simple_shim(tmp_path, monkeypatch)

    rid_s, rid_t = "lrn-50000000", "lrn-50000001"
    create_record(home, make_behavior(scope="skill:s", record_id=rid_s))
    create_record(home, make_behavior(scope="skill:t", record_id=rid_t))
    commit_all(home, "seed two buckets")

    stub = _HomeOnly(home)
    data_s = _valid_trace(stub, scope="skill:s", destination="skill-md")
    data_t = _valid_trace(stub, scope="skill:t", destination="skill-md")
    staged_s = worker.stage_dir() / f"{rid_s}.yaml"
    staged_t = worker.stage_dir() / f"{rid_t}.yaml"
    script = "\n".join([
        _write_script(staged_s, _dump(data_s)),
        _write_script(staged_t, _dump(data_t)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)

    result = worker.run(home)

    landed_s = home / "skills" / "s" / "proposals" / f"{rid_s}.yaml"
    landed_t = home / "skills" / "t" / "proposals" / f"{rid_t}.yaml"
    assert landed_s.is_file()
    assert landed_t.is_file()
    assert read_proposal(landed_s).get("record_sha")
    assert read_proposal(landed_t).get("record_sha")
    assert set(result.proposed) == {rid_s, rid_t}
    assert set(result.buckets) == {"s", "t"}


def test_ns3_litter_is_not_output(env, claude_cli_shim_worker, monkeypatch):
    """NS3 -- a staged file with no destination is litter, not output.
    Broken: MA3 (a resolver that falls back to "some bucket" -- a
    single-bucket, end-to-end fixture cannot distinguish that fallback
    from the correct None: the fallback bucket IS the only bucket, so a
    fake id still fails the LATER "no pending record" check with the
    same observable outcome. The direct unit-level leg below is what
    actually pins the resolver's own return value)."""
    rid = seed_pending(env)  # a non-empty batch, but NOT the id staged below
    litter_id = "lrn-99999999"
    staged_litter = worker.stage_dir() / f"{litter_id}.yaml"
    empty_merge = worker.stage_dir() / "merge-99999999.yaml"
    script = "\n".join([
        _write_script(staged_litter, _dump(_valid_trace(env))),
        _write_script(empty_merge, _dump({"cluster_id": "merge-99999999", "records": []})),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)

    result = worker.run(env.home)

    assert not staged_litter.exists()
    assert not empty_merge.exists()
    assert f"{litter_id}.yaml" in result.invalid_deleted
    assert "merge-99999999.yaml" in result.invalid_deleted
    assert not any((env.home / "skills" / "s" / "proposals").glob("*"))
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert f"no batch record for {litter_id}" in log_text

    # the direct unit-level leg: the resolver itself returns None for a
    # non-batch id, regardless of how many buckets exist to "fall back"
    # to.
    batch, *_ = worker._enumerate(env.home)
    batch_by_id = worker._batch_by_id(batch)
    assert rid in batch_by_id  # sanity: the real id DOES resolve
    assert worker._resolve_destination(staged_litter, batch_by_id) is None


def test_ns4_prompt_tells_the_model_one_place_the_stage(env):
    """NS4 -- Broken: MA4 (leaves the old instruction beside the new
    one), MA5 (strips `bucket:` from the record block)."""
    seed_pending(env)
    batch, *_ = worker._enumerate(env.home)
    prompt, _roster = worker.compose_batch_prompt(env.home, batch)

    assert str(worker.stage_dir()) in prompt
    assert "proposals/lrn-" not in prompt
    assert "proposals/merge-" not in prompt
    assert "bucket:" in prompt
    assert (
        "cluster_id MUST equal the merge-<8 hex> token of the filename itself"
        in prompt
    )


def test_ns5_stage_is_not_a_ledger_path(env):
    """NS5 -- Broken: MA6 (stage under home/.worker-stage)."""
    stage = worker.stage_dir()
    home = env.home

    assert stage.is_relative_to(worker.cache_dir())
    assert not stage.is_relative_to(home)
    assert stage != home
    for bucket in worker.discover_buckets(home):
        pdir = bucket.path / "proposals"
        assert not stage.is_relative_to(pdir)
        assert not pdir.is_relative_to(stage)
        assert stage != pdir


def test_ns6_naming_contract_accepts_the_stage_and_nothing_looser(env):
    """NS6 -- four legs against `_check_proposal_file` (ST-f), plus the
    shipped `test_unexpected_artifacts` leg. Broken: MA34 (refuses 100%
    of the model's output), MA35 (accepts a staged subdirectory file)."""
    rid = seed_pending(env, "lrn-0000aaaa")
    rid2 = seed_pending(env, "lrn-0000bbbb")
    batch, *_ = worker._enumerate(env.home)
    batch_by_id = worker._batch_by_id(batch)
    stage = worker.stage_dir()
    stage.mkdir(parents=True, exist_ok=True)

    # (a) a staged lrn-<id>.yaml passes the shape test.
    lrn_path = stage / f"{rid}.yaml"
    lrn_path.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    dest_a = worker._resolve_destination(lrn_path, batch_by_id)
    v_a = worker._check_proposal_file(env.home, lrn_path, None, {}, dest_a)
    assert v_a.error is None

    # (b) a staged merge-<hex>.yaml passes the shape test.
    merge_path = stage / "merge-0000cccc.yaml"
    merge_path.write_text(
        _dump({
            "cluster_id": "merge-0000cccc",
            "records": [rid, rid2],
            "suggested_survivor": rid,
            "rationale": "same lesson",
            "model": "claude-sonnet-5",
            "analyzed_at": "2026-08-06T00:00:00Z",
        }),
        encoding="utf-8",
    )
    dest_b = worker._resolve_destination(merge_path, batch_by_id)
    v_b = worker._check_proposal_file(env.home, merge_path, None, {}, dest_b)
    assert v_b.error is None

    # (c) a staged file in a SUBDIRECTORY of the stage is refused.
    sub = stage / "sub"
    sub.mkdir()
    sub_path = sub / f"{rid}.yaml"
    sub_path.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    dest_c = worker._resolve_destination(sub_path, batch_by_id)
    v_c = worker._check_proposal_file(env.home, sub_path, None, {}, dest_c)
    assert v_c.error == "unexpected artifact outside the proposal naming contract"

    # (d) a staged notes.txt is refused with the same message.
    notes_path = stage / "notes.txt"
    notes_path.write_text("not a proposal\n", encoding="utf-8")
    v_d = worker._check_proposal_file(env.home, notes_path, None, {}, notes_path)
    assert v_d.error == "unexpected artifact outside the proposal naming contract"

    # shipped leg: a LEDGER path outside proposals/ is still refused (the
    # parent-directory check, isolated from the filename check above).
    outside = env.bucket / "lrn-0000aaaa.yaml"
    outside.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    v_e = worker._check_proposal_file(env.home, outside, None, {}, outside)
    assert v_e.error == "unexpected artifact outside the proposal naming contract"


# ===================================================================== #
# GR -- the grant
# ===================================================================== #


def test_gr1_settings_files_enforce_defaultmode(env):
    """GR1 -- both settings files carry `defaultMode: default`. Broken:
    MA7. Past tense per the spec: this failed on the shipped code before
    GR-a's hotfix; here it verifies the property SURVIVES this unit's
    relocation of both settings files."""
    batch_settings = worker.write_settings_file(env.home)
    repair_settings = worker.write_repair_settings_file(env.home, [])
    assert json.loads(batch_settings.read_text())["permissions"]["defaultMode"] == "default"
    assert json.loads(repair_settings.read_text())["permissions"]["defaultMode"] == "default"


def test_gr2_batch_invocation_granted_the_stage_and_nothing_else(env):
    """GR2 -- Broken: MA8 (allow list is stage + the three ledger
    globs -- "be safe, grant both", which silently restores the whole
    defect)."""
    settings = worker.write_settings_file(env.home)
    allow = json.loads(settings.read_text())["permissions"]["allow"]

    assert allow == worker.stage_permission_rules(env.home)
    assert len(allow) == 1
    assert str(worker.stage_dir()) in allow[0]
    for rule in allow:
        assert "proposals" not in rule
        assert str(env.host) not in rule
        assert ".self-learn" not in rule


def test_gr3_repair_invocation_is_exact_path_over_staged_paths(env):
    """GR3 -- Broken: MA9 (repair settings reuse `stage_permission_
    rules`, a glob over the whole stage instead of one rule per member of
    E)."""
    paths = [
        worker.stage_dir() / "lrn-aaaa0000.yaml",
        worker.stage_dir() / "lrn-bbbb0000.yaml",
    ]
    settings = worker.write_repair_settings_file(env.home, paths)
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]

    assert len(allow) == len(paths)
    for rule, p in zip(allow, sorted(paths)):
        assert rule == f"Edit(/{p})"
        assert "*" not in rule
        assert str(worker.stage_dir()) in rule
    assert data["permissions"]["defaultMode"] == "default"


def test_gr4_write_permission_rules_preserved_for_the_fallback(env, monkeypatch):
    """GR4 -- Broken: MA10 (delete `write_permission_rules` as dead
    code, removing the kill switch's target)."""
    rules = worker.write_permission_rules(env.home)
    assert rules == [
        f"Edit(/{env.home}/skills/**/proposals/**)",
        f"Edit(/{env.home}/projects/**/proposals/**)",
        f"Edit(/{env.home}/user/proposals/**)",
    ]
    monkeypatch.setenv("SELF_LEARN_STAGE", "0")
    settings = worker.write_settings_file(env.home)
    assert json.loads(settings.read_text())["permissions"]["allow"] == rules


# ===================================================================== #
# IN -- the install
# ===================================================================== #


def test_in1_ordinary_path_absent_destination(env, claude_cli_shim_worker, monkeypatch):
    """IN1 -- IN's positive control, RED-VERIFIED against MA11 (the
    over-tight twin that declines when the destination is absent, making
    every other IN criterion pass while landing nothing)."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    result = worker.run(env.home)

    dest = env.proposals / f"{rid}.yaml"
    assert dest.is_file()
    assert rid in result.proposed
    assert dest in result.touched
    assert result.committed
    assert f"{rid}.yaml" in git(env.home, "ls-files").stdout


def test_in2_concurrent_write_during_window_is_never_overwritten(env, claude_cli_shim_worker, monkeypatch):
    """IN2 -- THE FW-84 incident, and MA12 reproduces it (drop I-b's
    byte-identity leg)."""
    rid = seed_pending(env)
    dest = env.proposals / f"{rid}.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    original = dict(_valid_trace(env))
    original["record_sha"] = _STALE_SHA
    dest.write_text(_dump(original), encoding="utf-8")
    commit_all(env.home, f"seed stamped {rid}")

    concurrent = dict(_valid_trace(env))
    concurrent["rationale"] = "attended session, still working"
    concurrent["record_sha"] = _stamp_sha(env, rid)
    concurrent_text = _dump(concurrent)
    script = "\n".join([
        shim_writes(env, rid),
        _write_script(dest, concurrent_text),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)

    result = worker.run(env.home)

    assert dest.read_text(encoding="utf-8") == concurrent_text
    assert not (worker.stage_dir() / f"{rid}.yaml").exists()
    assert f"{rid}.yaml" in result.not_installed
    assert rid in result.foreign_left
    assert rid not in result.proposed
    assert f"{rid}.yaml" not in result.invalid_deleted
    assert dest not in result.touched
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "carries a matching record_sha — another producer wrote it; left untouched" in log_text


def test_in3_pre_window_unstamped_draft_is_not_overwritten(env, claude_cli_shim_worker, monkeypatch):
    """IN3 -- Broken: MA13 (drop I-b's record_sha leg -- the install
    then overwrites an attended draft the worker never even sees)."""
    rid = seed_pending(env)
    dest = env.proposals / f"{rid}.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    draft_text = _dump(_valid_trace(env))  # schema-valid, NO record_sha
    dest.write_text(draft_text, encoding="utf-8")
    commit_all(env.home, f"seed unstamped draft {rid}")

    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    result = worker.run(env.home)

    assert dest.read_text(encoding="utf-8") == draft_text
    assert not (worker.stage_dir() / f"{rid}.yaml").exists()
    assert f"{rid}.yaml" in result.not_installed
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "destination is an unstamped draft this run did not write" in log_text


def test_in4_stale_stamped_destination_is_overwritten(env, claude_cli_shim_worker, monkeypatch):
    """IN4 -- Broken: MA14 (require the destination's record_sha to
    MATCH -- declining the single most common eligibility path)."""
    rid = seed_pending(env)
    dest = env.proposals / f"{rid}.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    stale = dict(_valid_trace(env))
    stale["record_sha"] = "sha256:000000000000"  # stale, does not match
    dest.write_text(_dump(stale), encoding="utf-8")
    commit_all(env.home, f"seed stale stamped {rid}")

    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    result = worker.run(env.home)

    assert rid in result.proposed
    assert read_proposal(dest)["record_sha"] == _stamp_sha(env, rid)


def test_in5_a_decline_is_loud_counted_and_non_destructive(env, claude_cli_shim_worker, monkeypatch):
    """IN5 -- Broken: MA15 (delete the staged AND the destination on
    decline -- a 'clean up the conflict' edit that converts a refusal
    into the deletion this unit exists to prevent)."""
    rid_a = seed_pending(env, "lrn-0000aaaa")  # IN2's shape
    rid_b = seed_pending(env, "lrn-0000bbbb")  # IN3's shape

    dest_a = env.proposals / f"{rid_a}.yaml"
    dest_a.parent.mkdir(parents=True, exist_ok=True)
    stamped_a = dict(_valid_trace(env))
    stamped_a["record_sha"] = _STALE_SHA
    dest_a.write_text(_dump(stamped_a), encoding="utf-8")

    dest_b = env.proposals / f"{rid_b}.yaml"
    draft_b = _dump(_valid_trace(env))
    dest_b.write_text(draft_b, encoding="utf-8")
    commit_all(env.home, "seed both decline shapes")

    concurrent_a = dict(_valid_trace(env))
    concurrent_a["rationale"] = "attended session, still working"
    concurrent_a["record_sha"] = _stamp_sha(env, rid_a)
    script = "\n".join([
        shim_writes(env, rid_a),
        shim_writes(env, rid_b),
        _write_script(dest_a, _dump(concurrent_a)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)

    called: list[Path] = []
    real_rm = worker._git_rm_or_unlink

    def _spy_rm(home, path, result=None):
        called.append(path)
        return real_rm(home, path, result)

    monkeypatch.setattr(worker, "_git_rm_or_unlink", _spy_rm)
    result = worker.run(env.home)

    assert dest_a.exists()
    assert dest_b.exists()
    assert dest_b.read_text(encoding="utf-8") == draft_b
    assert {f"{rid_a}.yaml", f"{rid_b}.yaml"} <= set(result.not_installed)
    assert worker.staged_paths() == []
    assert dest_a not in called
    assert dest_b not in called


def test_in6_declines_do_not_fake_failure_or_success(env, claude_cli_shim_worker, monkeypatch):
    """IN6 -- Broken: MA16 (count every decline as progress -- a run
    whose only outcome is an abandoned draft blocking the queue then
    reports a successful status, hiding the IN3 residual behind green)."""
    # (a) fresh decline (Rule-F holds): status ok, foreign_left names it.
    rid_a = seed_pending(env, "lrn-0000aaaa")
    dest_a = env.proposals / f"{rid_a}.yaml"
    dest_a.parent.mkdir(parents=True, exist_ok=True)
    stamped_a = dict(_valid_trace(env))
    stamped_a["record_sha"] = _STALE_SHA
    dest_a.write_text(_dump(stamped_a), encoding="utf-8")
    commit_all(env.home, "seed fresh destination")
    concurrent_a = dict(_valid_trace(env))
    concurrent_a["rationale"] = "attended session, still working"
    concurrent_a["record_sha"] = _stamp_sha(env, rid_a)
    script_a = "\n".join([
        shim_writes(env, rid_a),
        _write_script(dest_a, _dump(concurrent_a)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script_a)
    result_a = worker.run(env.home)

    assert result_a.status == "ok"
    assert (worker.cache_dir() / "worker.last-run").is_file()
    assert result_a.proposed == []
    assert rid_a in result_a.foreign_left
    assert not (worker.cache_dir() / "worker.failures").exists()

    # (b) unstamped-draft decline (Rule-F does not hold): status failed.
    rid_b = seed_pending(env, "lrn-0000bbbb")
    dest_b = env.proposals / f"{rid_b}.yaml"
    dest_b.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    commit_all(env.home, "seed unstamped draft")
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid_b))
    result_b = worker.run(env.home)

    assert result_b.status == "failed"
    assert result_b.foreign_left == []


def test_in7_every_install_happens_under_the_lock(env):
    """IN7 -- Broken: MA17 (install from `_check_proposal_file` when a
    flag is set -- a static analyser cannot forgive it)."""
    src_check = inspect.getsource(worker._check_proposal_file)
    for forbidden in (
        "write_text(", ".unlink(", ".rename(", "_dump_yaml(",
        "stamp_proposal(", "shutil.copy", "_git_rm_or_unlink(",
    ):
        assert forbidden not in src_check, forbidden

    src_validate_written = inspect.getsource(worker._validate_written)
    assert "_install_staged(" in src_validate_written
    assert "validate_proposal(" not in src_validate_written


def test_in8_interrupted_install_is_recovered_not_stalled_forever(env, claude_cli_shim_worker, monkeypatch):
    """IN8 -- five-part crash fixture. Broken: MA36 (delete the
    destination too on a stamp exception), MA37 (drop I-c), MA38 (read +
    truncate IJ at S1), MA50 (a bare non-atomic write_text onto the
    destination)."""
    from self_learn import ledger_ops as _ledger_ops

    real_stamp = _ledger_ops.stamp_proposal

    def _boom(home, record_id):
        raise RuntimeError("simulated stamp crash")

    # (a) simulated crash: stamp_proposal raises on the FIRST call.
    rid = seed_pending(env, "lrn-0000aaaa")
    dest = env.proposals / f"{rid}.yaml"
    monkeypatch.setattr(worker, "stamp_proposal", _boom)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    worker.run(env.home)

    assert dest.is_file()
    landed_a = read_proposal(dest)
    assert landed_a.get("record_sha") is None
    journal = worker._read_install_journal()
    assert dest in journal
    assert journal[dest] == sha_anchor(dest.read_text(encoding="utf-8"))
    assert not (worker.stage_dir() / f"{rid}.yaml").exists()
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "installed but not stamped" in log_text

    # (b) recovery: a fresh staged proposal + a working stamp resumes
    # via I-c.
    monkeypatch.setattr(worker, "stamp_proposal", real_stamp)
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid))
    result_b = worker.run(env.home)

    assert rid in result_b.proposed
    assert dest not in worker._read_install_journal()
    log_text2 = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "resuming interrupted install" in log_text2

    # (c) no entry, no licence: unstamped-and-unchanged, NO IJ entry ->
    # declines.
    rid_c = seed_pending(env, "lrn-0000cccc")
    dest_c = env.proposals / f"{rid_c}.yaml"
    dest_c.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    commit_all(env.home, "seed unstamped no-entry destination")
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid_c))
    result_c = worker.run(env.home)
    assert f"{rid_c}.yaml" in result_c.not_installed
    assert rid_c not in result_c.proposed

    # (d) the kill-zone leg (r2 gate MAJOR 1): crash again, then a run
    # that FAILS INSIDE the model window (shim exits non-zero, nothing
    # staged) leaves the journal entry intact; the run AFTER recovers.
    rid_d = seed_pending(env, "lrn-0000dddd")
    dest_d = env.proposals / f"{rid_d}.yaml"
    monkeypatch.setattr(worker, "stamp_proposal", _boom)
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid_d))
    worker.run(env.home)
    monkeypatch.setattr(worker, "stamp_proposal", real_stamp)
    journal_d = worker._read_install_journal()
    assert dest_d in journal_d

    _next_run_scripts(claude_cli_shim_worker, monkeypatch, None, exits={1: 1})
    result_d_fail = worker.run(env.home)
    assert result_d_fail.status == "failed"
    assert dest_d in worker._read_install_journal()

    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid_d))
    result_d_recover = worker.run(env.home)
    assert rid_d in result_d_recover.proposed
    assert dest_d not in worker._read_install_journal()

    # (e) crash mid-copy (r3 gate MAJOR): os.replace raises, the temp is
    # written, the destination is untouched.
    rid_e = seed_pending(env, "lrn-0000eeee")
    dest_e = env.proposals / f"{rid_e}.yaml"
    assert not dest_e.exists()
    real_replace = os.replace

    def _boom_replace(src, dst):
        raise OSError("simulated os.replace crash")

    monkeypatch.setattr(os, "replace", _boom_replace)
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid_e))
    worker.run(env.home)

    assert not dest_e.exists()  # still absent -- the pre-install state
    tmp_e = dest_e.parent / f".install-{rid_e}.tmp"
    assert tmp_e.exists()

    monkeypatch.setattr(os, "replace", real_replace)
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid_e))
    result_e = worker.run(env.home)

    assert not tmp_e.exists()  # swept by the NEXT run's pass-1 cleanup
    assert rid_e in result_e.proposed
    assert dest_e.is_file()
    assert read_proposal(dest_e).get("record_sha") == _stamp_sha(env, rid_e)


def test_in9_matching_record_sha_installed_like_any_other(env, claude_cli_shim_worker, monkeypatch):
    """IN9 -- Broken: MA39 (keep the shipped `verdict.phi and not
    verdict.is_hook` skip -- the file then silently never lands, never
    stamps, never alarms, EVERY window; D6(i) cannot catch this)."""
    rid = seed_pending(env)
    data = dict(_valid_trace(env))
    data["record_sha"] = _stamp_sha(env, rid)  # the copy-the-sha shape
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        _write_script(worker.stage_dir() / f"{rid}.yaml", _dump(data)),
    )
    result = worker.run(env.home)

    dest = env.proposals / f"{rid}.yaml"
    assert rid in result.proposed
    assert dest in result.touched
    assert result.committed
    assert rid not in result.foreign_left
    assert read_proposal(dest)["record_sha"] == _stamp_sha(env, rid)


def test_in10_the_secret_carve_out_survives_on_both_sides(env, claude_cli_shim_worker, monkeypatch):
    """IN10 -- Broken: MA40 (skip the scan on the foreign pass -- a scan
    hit then reaches the remote through autosync)."""
    rid_a = seed_pending(env, "lrn-0000aaaa")  # (a) staged secret hit.
    rid_b = seed_pending(env, "lrn-0000bbbb")  # (b) foreign secret hit.

    secret_a = dict(_valid_trace(env))
    secret_a["rationale"] = "use password = hunter2secret9 for this"
    staged_a = worker.stage_dir() / f"{rid_a}.yaml"

    secret_b = dict(_valid_trace(env))
    secret_b["rationale"] = "use password = hunter2secret9 for this"
    secret_b["record_sha"] = _stamp_sha(env, rid_b)
    dest_b = env.proposals / f"{rid_b}.yaml"

    script = "\n".join([
        _write_script(staged_a, _dump(secret_a)),
        _write_script(dest_b, _dump(secret_b)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result = worker.run(env.home)

    assert not staged_a.exists()
    assert f"{rid_a}.yaml" in result.invalid_deleted
    assert not (env.proposals / f"{rid_a}.yaml").exists()

    assert not dest_b.exists()
    assert f"{rid_b}.yaml" in result.invalid_deleted
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert log_text.count("secret scan hit") >= 2


def test_in11_the_journal_is_not_an_overwrite_licence(env, claude_cli_shim_worker, monkeypatch):
    """IN11 -- r2 gate BLOCKER 1. Broken: MA49 (journal the destination
    only, with I-c treating it as I-a -- the FW-84 incident re-entering
    through the recovery machinery)."""
    from self_learn import ledger_ops as _ledger_ops

    real_stamp = _ledger_ops.stamp_proposal

    def _boom(home, record_id):
        raise RuntimeError("simulated stamp crash")

    rid = seed_pending(env)
    dest = env.proposals / f"{rid}.yaml"
    monkeypatch.setattr(worker, "stamp_proposal", _boom)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    worker.run(env.home)
    monkeypatch.setattr(worker, "stamp_proposal", real_stamp)

    journal = worker._read_install_journal()
    assert dest in journal
    pre_bytes = dest.read_text(encoding="utf-8")

    # the next run: the model writes a fresh staged proposal AND, in the
    # SAME window, the concurrent-producer shim rewrites dest -- the
    # attended session legitimately picking up the record while a stale
    # journal entry from the crashed round is still live.
    concurrent_data = dict(_valid_trace(env))
    concurrent_data["rationale"] = "attended session, replaces the crash residue"
    concurrent_data["record_sha"] = _stamp_sha(env, rid)
    concurrent_text = _dump(concurrent_data)
    script = "\n".join([shim_writes(env, rid), _write_script(dest, concurrent_text)])
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, script)
    result = worker.run(env.home)

    assert dest.read_text(encoding="utf-8") == concurrent_text
    assert dest.read_text(encoding="utf-8") != pre_bytes
    assert not (worker.stage_dir() / f"{rid}.yaml").exists()
    assert f"{rid}.yaml" in result.not_installed
    assert dest.exists()
    assert dest not in worker._read_install_journal()

    # positive control: the identical fixture WITHOUT the concurrent
    # rewrite installs normally via I-c.
    rid2 = seed_pending(env, "lrn-0000cccc")
    dest2 = env.proposals / f"{rid2}.yaml"
    monkeypatch.setattr(worker, "stamp_proposal", _boom)
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid2))
    worker.run(env.home)
    monkeypatch.setattr(worker, "stamp_proposal", real_stamp)
    assert dest2 in worker._read_install_journal()

    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid2))
    result2 = worker.run(env.home)
    assert rid2 in result2.proposed
    assert dest2 not in worker._read_install_journal()


# ===================================================================== #
# RT -- the retirements (FW-84's residual family)
# ===================================================================== #


def test_rt1_written_but_not_yet_validated_during_the_window_is_retired(env, claude_cli_shim_worker, monkeypatch):
    """RT1 -- replaces U-repair D1. Broken: MA18 (the candidate set takes
    the ledger's changes back), MA19 (the absent-from-snap0 comparison
    inverts)."""
    # variant 1: destination ABSENT at S1, created during the window.
    rid1 = seed_pending(env, "lrn-0000aaaa")
    dest1 = env.proposals / f"{rid1}.yaml"
    attended1_text = _dump(dict(_valid_trace(env)))  # unstamped
    script1 = "\n".join([shim_writes(env, rid1), _write_script(dest1, attended1_text)])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script1)
    worker.run(env.home)

    assert dest1.read_text(encoding="utf-8") == attended1_text
    assert read_proposal(dest1).get("record_sha") is None
    assert not (worker.stage_dir() / f"{rid1}.yaml").exists()

    # variant 2: a STALE STAMPED destination present at S1, replaced
    # during the window WITH ANOTHER stamped (but still non-matching)
    # draft -- carries a record_sha throughout, so this leg isolates
    # I-b's BYTE-IDENTITY term specifically (MA19's .get()-default trap
    # only bites when has_record_sha is already true; variant 1's
    # genuinely unstamped shape can never distinguish it, since
    # has_record_sha=False blocks I-b either way).
    rid2 = seed_pending(env, "lrn-0000bbbb")
    dest2 = env.proposals / f"{rid2}.yaml"
    stale2 = dict(_valid_trace(env))
    stale2["record_sha"] = "sha256:000000000000"
    dest2.write_text(_dump(stale2), encoding="utf-8")
    commit_all(env.home, "seed stale stamped")
    attended2 = dict(_valid_trace(env))
    # a 12-hex-char value -- sha_anchor()'s own real output length
    # (`sha256:<12hex>`); a 48+-char run trips the secret scanner's
    # high-entropy-hex rule (pure pattern match, no real entropy
    # calculation -- measured the hard way: "sha256:" + "1" * 64
    # deletes this exact fixture as a scan hit before RT1 ever gets to
    # assert anything about it).
    attended2["record_sha"] = "sha256:deadbeefcafe"
    attended2_text = _dump(attended2)
    script2 = "\n".join([shim_writes(env, rid2), _write_script(dest2, attended2_text)])
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, script2)
    worker.run(env.home)

    assert dest2.read_text(encoding="utf-8") == attended2_text
    assert read_proposal(dest2)["record_sha"] == "sha256:deadbeefcafe"
    assert not (worker.stage_dir() / f"{rid2}.yaml").exists()

    # variant 3: isolates MA19's OWN bug specifically. Variant 1's
    # unstamped shape can never distinguish it (has_record_sha=False
    # blocks I-b either way, .get() trap or not); variant 2's key IS
    # present in snap0 (just with different content), so `.get()`
    # returns the REAL stored digest there too -- the trap only fires
    # when the key is MISSING from snap0 entirely, which is exactly
    # "absent at S1, created during the window" WITH a record_sha this
    # time (the "unstamped" framing was never the load-bearing part of
    # I-a/I-b's absent-vs-present distinction; carrying a record_sha is
    # what the trap needs to be reachable through I-b instead of
    # falling through to the ordinary decline for an unrelated reason).
    rid3 = seed_pending(env, "lrn-0000cccc")
    dest3 = env.proposals / f"{rid3}.yaml"
    assert not dest3.exists()  # genuinely absent at S1
    attended3 = dict(_valid_trace(env))
    attended3["record_sha"] = "sha256:deadbeefcafe"
    attended3_text = _dump(attended3)
    script3 = "\n".join([shim_writes(env, rid3), _write_script(dest3, attended3_text)])
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, script3)
    worker.run(env.home)

    assert dest3.read_text(encoding="utf-8") == attended3_text
    assert not (worker.stage_dir() / f"{rid3}.yaml").exists()


def test_rt2_edited_after_validation_caught_mid_edit_is_retired(env, claude_cli_shim_worker, monkeypatch):
    """RT2 -- replaces U-repair D6(ii)/D6(iii). Broken: MA18 (widens S5's
    candidate set to include ledger paths again -- the mid-edit file is
    then deleted, U-repair's MAJOR 7 cell reopened). Run twice: a plain
    destination and a `destination: hook`."""
    for i, destination in enumerate(("skill-md", "hook")):
        suffix = "aaaa" if destination == "skill-md" else "cccc"
        rid_target = seed_pending(env, f"lrn-{i}000{suffix}"[:12])
        rid_repair = seed_pending(env, f"lrn-{i}001{suffix}"[:12])
        target_dest = env.proposals / f"{rid_target}.yaml"
        if destination == "hook":
            target_data = dict(_valid_trace(env, destination="hook", alternates=["claude-md"]))
            target_data.update(hook_proposal_fields())
        else:
            target_data = dict(_valid_trace(env))
        target_data["record_sha"] = _STALE_SHA
        target_dest.parent.mkdir(parents=True, exist_ok=True)
        target_dest.write_text(_dump(target_data), encoding="utf-8")
        commit_all(env.home, f"seed valid stamped {rid_target}")

        round1 = "\n".join([
            shim_writes(env, rid_target),
            _defect_script(env, rid_repair, _t4_missing_target(env, rid_repair)),
        ])
        base = claude_cli_shim_worker["count"]()
        monkeypatch.setenv(f"CLAUDE_SHIM_SCRIPT_{base + 1}", round1)
        # round 2 (repair): edits the LEDGER destination directly --
        # never the staged path -- leaving it mid-edit and schema-invalid.
        round2 = f"printf 'destination: bogus\\n' > {target_dest}"
        monkeypatch.setenv(f"CLAUDE_SHIM_SCRIPT_{base + 2}", round2)

        result = worker.run(env.home)

        assert target_dest.exists()
        assert target_dest.read_text(encoding="utf-8") == "destination: bogus\n"
        assert f"{rid_target}.yaml" not in result.invalid_deleted
        log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
        assert "repair rewrote a proposal that had already validated" not in log_text


def test_rt3_a_never_validated_attended_proposal_is_repair_eligible(env, claude_cli_shim_worker, monkeypatch):
    """RT3 -- replaces and INVERTS U-repair D8(iii). U-repair section 7.3
    pinned this file as a residual: handed to a second model under a
    write grant, a successful repair could land and commit it. That
    grant no longer exists at all -- the model has no write access to
    any ledger path -- so the residual is now a structural impossibility,
    not merely an undesired outcome. Broken: MA20 (build E from
    staged1 UNION foreign)."""
    rid_target = seed_pending(env, "lrn-0000aaaa")
    rid_batch = seed_pending(env, "lrn-0000bbbb")
    target_dest = env.proposals / f"{rid_target}.yaml"
    attended_text = _dump(_t4_missing_target(env, rid_target))
    target_dest.parent.mkdir(parents=True, exist_ok=True)
    target_dest.write_text(attended_text, encoding="utf-8")
    commit_all(env.home, "seed attended invalid unstamped proposal")

    round1 = _defect_script(env, rid_batch, _t4_missing_target(env, rid_batch))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)

    result = worker.run(env.home)

    assert target_dest.read_text(encoding="utf-8") == attended_text
    prompt2 = claude_cli_shim_worker["call_prompt"](2)
    assert prompt2, "the repair round did not fire -- nothing to pin"
    assert str(target_dest) not in prompt2
    assert f"{rid_target}.yaml" not in result.invalid_deleted


def test_rt4_e5_is_retired_and_nothing_regressed(env, claude_cli_shim_worker, monkeypatch):
    """RT4 -- Broken: MA21 (keep the E-5 clause -- a model that copies a
    record_sha into its own output loses its repair round for no
    reason)."""
    rid = seed_pending(env)
    defect = _t4_missing_target(env, rid)
    defect["record_sha"] = _stamp_sha(env, rid)  # the copy-the-sha shape
    # NOT `_defect_script` -- it unconditionally pops record_sha before
    # writing (round-1-shaped output, no model ever emits one), which
    # would silently discard the exact thing this criterion needs
    # preserved on the wire.
    staged_path = worker.stage_dir() / f"{rid}.yaml"
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _write_script(staged_path, _dump(defect)))
    fixed = _t4_target_fixed(env, rid)
    fixed.pop("record_sha", None)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, fixed))

    result = worker.run(env.home)

    prompt2 = claude_cli_shim_worker["call_prompt"](2)
    assert str(worker.stage_dir() / f"{rid}.yaml") in prompt2
    assert result.repair_eligible == 1
    assert rid in result.proposed


def test_rt5_e4_survives_as_a_litter_rule_not_a_provenance_rule(env):
    """RT5 -- Broken: MA22 (fold batch membership into `_repairable` --
    re-creating the composed-eligibility shape U-repair's delta-2 gate
    refused)."""
    litter_id = "lrn-88888888"
    err = f"no batch record for {litter_id}"
    assert worker._repairable(err) != "ELIGIBLE"
    # Table-E's rows still classify exactly as they did -- text-only.
    assert worker._repairable("gates.t4.depth_behind_rule.target: required") == "ELIGIBLE"
    assert worker._repairable("no pending record for lrn-00000000") != "ELIGIBLE"
    assert worker._repairable("gates.t3.roster_sha: dishonest") != "ELIGIBLE"


def test_rt6_no_uncommitted_model_authored_foreign_file(env, claude_cli_shim_worker, monkeypatch):
    """RT6 -- Broken: MA23 (append declined destinations to `touched` --
    committing bytes the worker did not write)."""
    rid1 = seed_pending(env, "lrn-0000aaaa")
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid1))
    result1 = worker.run(env.home)

    dest1 = env.proposals / f"{rid1}.yaml"
    assert dest1 in result1.touched
    assert result1.committed
    assert git(env.home, "status", "--porcelain").stdout.strip() == ""

    rid2 = seed_pending(env, "lrn-0000bbbb")
    dest2 = env.proposals / f"{rid2}.yaml"
    dest2.parent.mkdir(parents=True, exist_ok=True)
    stamped2 = dict(_valid_trace(env))
    stamped2["record_sha"] = _STALE_SHA
    dest2.write_text(_dump(stamped2), encoding="utf-8")
    commit_all(env.home, "seed fresh destination")
    concurrent2 = dict(_valid_trace(env))
    concurrent2["rationale"] = "attended session, still working"
    concurrent2["record_sha"] = _stamp_sha(env, rid2)
    # the concurrent producer commits its OWN write (an attended `route`
    # session publishes its own change) -- what RT6 checks is that the
    # WORKER leaves nothing uncommitted, not that a second producer's
    # own commit discipline is the worker's job.
    commit_script = f"git -C {env.home} add {dest2} && git -C {env.home} commit -q -m 'concurrent route'"
    script2 = "\n".join([
        shim_writes(env, rid2),
        _write_script(dest2, _dump(concurrent2)),
        commit_script,
    ])
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, script2)
    result2 = worker.run(env.home)

    assert dest2 not in result2.touched
    assert rid2 not in result2.proposed
    assert git(env.home, "status", "--porcelain").stdout.strip() == ""


def test_rt7_foreign_progress_without_any_staged_output_for_that_record(env, claude_cli_shim_worker, monkeypatch):
    """RT7 -- r1 gate BLOCKER 2, the world r1 had no criterion for.
    Broken: MA41 (populate foreign_left only from Install-1 declines --
    U-repair's D7 regression, re-introduced by the unit that claimed to
    preserve it)."""
    rid_a = seed_pending(env, "lrn-0000aaaa")
    seed_pending(env, "lrn-0000bbbb")  # B: model writes nothing valid either.
    dest_a = env.proposals / f"{rid_a}.yaml"
    complete_a = dict(_valid_trace(env))
    complete_a["record_sha"] = _stamp_sha(env, rid_a)
    complete_a_text = _dump(complete_a)
    # the model writes NOTHING to the stage at all -- the shim's ONLY
    # action is the concurrent producer's complete, valid, stamped write.
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", _write_script(dest_a, complete_a_text))

    result = worker.run(env.home)

    assert result.status == "ok"
    assert (worker.cache_dir() / "worker.last-run").is_file()
    assert rid_a in result.foreign_left
    assert result.foreign_seen >= 1
    assert result.proposed == []
    assert result.valid_landed == 0
    assert result.touched == []
    assert dest_a.read_text(encoding="utf-8") == complete_a_text
    assert not (worker.cache_dir() / "worker.failures").exists()
    assert result.followon is False


def test_rt8_no_model_authored_script_reaches_route_foreign_hook_left_alone(env, claude_cli_shim_worker, monkeypatch):
    """RT8 -- replaces U-repair D9. Broken: MA42 (skip the stamp when a
    staged hook proposal's record_sha already matches -- model-authored
    executable bytes then reach `route`, and `stamp_proposal`'s own
    stated guarantee becomes false)."""
    rid_a = seed_pending(env, "lrn-0000aaaa")
    record_a = _record_for(env, rid_a)
    hook_a = dict(_valid_trace(env, destination="hook", alternates=["claude-md"]))
    hook_a.update(hook_proposal_fields())
    hook_a["record_sha"] = _stamp_sha(env, rid_a)
    hook_a["script"] = "#!/bin/sh\necho model-authored-script\n"
    staged_a = worker.stage_dir() / f"{rid_a}.yaml"

    rid_b = seed_pending(env, "lrn-0000bbbb")
    dest_b = env.proposals / f"{rid_b}.yaml"
    hook_b = dict(_valid_trace(env, destination="hook", alternates=["claude-md"]))
    hook_b.update(hook_proposal_fields())
    hook_b["record_sha"] = _stamp_sha(env, rid_b)
    hook_b_text = _dump(hook_b)

    script = "\n".join([
        _write_script(staged_a, _dump(hook_a)),
        _write_script(dest_b, hook_b_text),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)

    result = worker.run(env.home)

    # (a) installed, RE-STAMPED -- the model's script is overwritten.
    assert rid_a in result.proposed
    landed_a = read_proposal(env.proposals / f"{rid_a}.yaml")
    from self_learn import ledger_ops as _ledger_ops

    expected_script = _ledger_ops._generate_hook_script(record_a, landed_a)
    assert landed_a["script"] == expected_script
    assert landed_a["script"] != "#!/bin/sh\necho model-authored-script\n"

    # (b) a FOREIGN hook proposal, no staged counterpart -- left alone.
    assert dest_b.read_text(encoding="utf-8") == hook_b_text
    assert rid_b not in result.proposed
    assert dest_b not in result.touched
    assert f"{rid_b}.yaml" in git(env.home, "status", "--porcelain").stdout


# ===================================================================== #
# CP -- compatibility with U-repair
#
# CP1 ("the whole shipped suite is green") is instrument-only in the
# spec's own words -- satisfied by the full pytest run, not a function
# here (see this file's module docstring).
# ===================================================================== #


def test_cp2_seq1_step_identities_and_log_lines_survive(env, claude_cli_shim_worker, monkeypatch):
    """CP2 -- Broken: MA24 (reword the invalid-output line for staged
    files -- the plausible edit that breaks review.md's and the UI's
    contract)."""
    rid_ok = seed_pending(env, "lrn-0000aaaa")
    rid_bad = seed_pending(env, "lrn-0000bbbb")
    bad_data = dict(_valid_trace(env))
    bad_data["destination"] = "not-a-real-destination"
    script = "\n".join([
        shim_writes(env, rid_ok),
        _write_script(worker.stage_dir() / f"{rid_bad}.yaml", _dump(bad_data)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result = worker.run(env.home)

    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert (
        f"run: ok — {len(result.proposed)} proposal(s), "
        f"{len(result.merge_proposed)} merge, {len(result.invalid_deleted)} invalid deleted"
    ) in log_text
    assert f"run: invalid worker output {rid_bad}.yaml deleted (" in log_text

    # a FAILED run: the only decline is an unstamped draft.
    rid_fail = seed_pending(env, "lrn-0000cccc")
    dest_fail = env.proposals / f"{rid_fail}.yaml"
    dest_fail.parent.mkdir(parents=True, exist_ok=True)
    dest_fail.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    commit_all(env.home, "seed unstamped draft")
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid_fail))
    worker.run(env.home)
    log_text2 = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: FAILED — " in log_text2

    # the orphan sweep: a TRACKED proposal with no matching pending
    # record is swept and its line logged.
    orphan = env.proposals / "lrn-0000dead.yaml"
    orphan.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    commit_all(env.home, "seed a tracked orphan proposal")
    rid_last = seed_pending(env, "lrn-0000ffff")
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, shim_writes(env, rid_last))
    worker.run(env.home)
    log_text3 = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: orphan proposal lrn-0000dead.yaml swept" in log_text3


def test_cp3_repair_round_works_end_to_end_over_staged_paths(env, claude_cli_shim_worker, monkeypatch):
    """CP3 -- Broken: MA25 (E computed over ledger paths -- the exact-
    path grants then name files the model cannot see, and the repair
    round silently repairs nothing while reporting a set)."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid)))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid)))

    result = worker.run(env.home)

    assert result.repair_attempted
    assert result.repair_eligible == 1
    assert result.repair_cleared == 1
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair round: 1 of 1 refusals cleared" in log_text
    assert rid in result.proposed


def test_cp4_the_setj_pin_still_binds(env, claude_cli_shim_worker, monkeypatch):
    """CP4 -- U-repair G1's fixture, relocated to the stage. Broken:
    MA26 (skip the Set-J comparison for staged paths -- Set-J guards the
    FIRST pass's judgment against the SECOND, both the model's)."""
    import copy

    from self_learn.ledger_ops import _validate_gates

    rid = seed_pending(env)
    bad = _t4_missing_target(env, rid)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, bad))
    flipped = copy.deepcopy(bad)
    flipped["gates"]["t4"]["depth_behind_rule"] = {"answer": "no", "evidence": None, "target": None}
    _validate_gates(flipped, record_text=_record_for(env, rid).to_text())  # sanity
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, flipped))

    result = worker.run(env.home)

    assert not (env.proposals / f"{rid}.yaml").exists()
    assert f"{rid}.yaml" in result.invalid_deleted
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    line = next(ln for ln in log_text.splitlines() if f"invalid worker output {rid}.yaml deleted" in ln)
    assert "repair changed a settled judgment" in line
    assert "gates.t4.depth_behind_rule.answer" in line


def test_cp5_containment_derivation_and_deletion_backstop_on_staged_files(env, claude_cli_shim_worker, monkeypatch):
    """CP5 -- four legs, the fourth newly reachable (r1 gate MAJOR 6).
    Broken: MA27 (install before validating, then delete on failure --
    unvalidated bytes briefly land in the ledger)."""
    rid_a = seed_pending(env, "lrn-0000aaaa")  # (i) fabricated RECORD quote.
    data_a = dict(_valid_trace(env))
    data_a["gates"]["t2"] = {
        "answer": "no",
        "evidence": "a fabricated quote never in the record",
        "match_path": None,
    }

    rid_b = seed_pending(env, "lrn-0000bbbb")  # (ii) laundered outcome.
    data_b = dict(_valid_trace(env))
    data_b["gates"]["outcome"] = "DEMAND"

    rid_c = seed_pending(env, "lrn-0000cccc")  # (iii) refused at S8.
    data_c = dict(_valid_trace(env))
    data_c["destination"] = "not-a-real-destination"

    rid_d = seed_pending(env, "lrn-0000dddd")  # (iv) matching sha + secret.
    data_d = dict(_valid_trace(env))
    data_d["record_sha"] = _stamp_sha(env, rid_d)
    data_d["rationale"] = "use password = hunter2secret9 for this"

    script = "\n".join([
        _write_script(worker.stage_dir() / f"{rid_a}.yaml", _dump(data_a)),
        _write_script(worker.stage_dir() / f"{rid_b}.yaml", _dump(data_b)),
        _write_script(worker.stage_dir() / f"{rid_c}.yaml", _dump(data_c)),
        _write_script(worker.stage_dir() / f"{rid_d}.yaml", _dump(data_d)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result = worker.run(env.home)

    for rid in (rid_a, rid_b, rid_c, rid_d):
        assert not (worker.stage_dir() / f"{rid}.yaml").exists()
        assert f"{rid}.yaml" in result.invalid_deleted
        assert not (env.proposals / f"{rid}.yaml").exists()
        assert (env.bucket / "pending" / f"{rid}.md").exists()
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    line_d = next(ln for ln in log_text.splitlines() if f"invalid worker output {rid_d}.yaml deleted" in ln)
    assert "secret scan hit" in line_d


def test_cp6_sentinel_reassert_still_happens_g8_unchanged(env, claude_cli_shim_worker, monkeypatch):
    """CP6 -- U-repair G8, unchanged. Broken: U-repair's M21, which must
    still redden (fully verified by the shipped, bucket-1, unmodified
    `test_repair.py::test_g8_sentinel_reasserted_after_the_last_
    invocation`; re-affirmed here at lighter weight)."""
    from self_learn import sentinel as sentinel_mod

    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    worker.run(env.home)
    hold = sentinel_mod.hold()
    assert hold.owned


def test_cp7_rule_f_predicate_is_unchanged(env):
    """CP7 -- Broken: MA28 (reduce Rule-F to F-b alone -- U-repair's
    D6(i) measured F-b alone is model-reachable, and Rule-F still
    decides progress accounting for real files)."""
    src = inspect.getsource(worker._check_proposal_file)
    assert 'record_sha_matches = data.get("record_sha") == sha_anchor(' in src
    assert "_roster_sha_dishonest(data, roster)" in src
    phi_lines = [ln.strip() for ln in src.splitlines() if ln.strip().startswith("phi = ")]
    assert phi_lines == ["phi = False", "phi = record_sha_matches"]
    assert not any("is_hook" in ln for ln in phi_lines)
    # Position, not just presence: F-b's assignment must come AFTER both
    # F-a checks textually, so it can only be reached once validate_proposal
    # and the roster-honesty check have both run without raising. A
    # mutation that hoists "phi = record_sha_matches" above those checks
    # (so phi leaks a stale True on a later exception, reducing Rule-F to
    # F-b alone) changes none of the text this test already checks above --
    # only the ORDER -- so it must be pinned here too.
    validate_call_pos = src.index("validate_proposal(")
    roster_check_pos = src.index("_roster_sha_dishonest(data, roster)")
    phi_fb_pos = src.index("phi = record_sha_matches")
    assert validate_call_pos < phi_fb_pos
    assert roster_check_pos < phi_fb_pos


def test_cp8_testworkercontainment_asserts_new_containment_and_h3(env):
    """CP8 -- fully verified by the shipped, relocated
    `test_hosting.py::TestWorkerContainment`. Broken: MA8, MA7."""
    settings = worker.write_settings_file(env.home)
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]
    assert allow == worker.stage_permission_rules(env.home)
    for rule in allow:
        assert str(env.host) not in rule
        assert ".self-learn" not in rule
    assert data["permissions"]["defaultMode"] == "default"


def test_cp9_the_merge_happy_path_installs_with_its_record_shas(env, claude_cli_shim_worker, monkeypatch):
    """CP9 -- r1 gate NOTE 1. Broken: MA43 (install merges by copying
    the staged bytes, like an lrn-* -- record_shas is resolved IN MEMORY
    at S4 and exists nowhere in the staged file, so the byte copy lands
    a merge proposal with no shas at all: dead at route --collapse)."""
    rid1 = seed_pending(env, "lrn-0000aaaa")
    rid2 = seed_pending(env, "lrn-0000bbbb")
    merge_data = {
        "cluster_id": "merge-0000cccc",
        "records": [rid1, rid2],
        "suggested_survivor": rid1,
        "rationale": "same lesson",
        "model": "claude-sonnet-5",
        "analyzed_at": "2026-08-06T00:00:00Z",
    }
    script = "\n".join([
        _write_script(worker.stage_dir() / f"{rid1}.yaml", _dump(_valid_trace(env))),
        _write_script(worker.stage_dir() / f"{rid2}.yaml", _dump(_valid_trace(env))),
        _write_script(worker.stage_dir() / "merge-0000cccc.yaml", _dump(merge_data)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result = worker.run(env.home)

    landed = env.proposals / "merge-0000cccc.yaml"
    assert landed.is_file()
    data = read_proposal(landed)
    assert data["record_shas"] == {rid1: _stamp_sha(env, rid1), rid2: _stamp_sha(env, rid2)}
    assert "merge-0000cccc" in result.merge_proposed


def test_cp10_a_repair_that_deletes_its_staged_file_does_not_kill_the_run(env, claude_cli_shim_worker, monkeypatch):
    """CP10 -- r1 gate NOTE 1, section 5's lead (c). Broken: MA44 (read
    the post-repair text unguarded -- the exception escapes a
    Popen-detached process: a stack dump, no commit, a dead run)."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid)))
    staged_path = worker.stage_dir() / f"{rid}.yaml"
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", f"rm -f {staged_path}")

    result = worker.run(env.home)

    assert isinstance(result, worker.RunResult)
    assert (env.bucket / "pending" / f"{rid}.md").exists()
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "disappeared during repair" in log_text


# ===================================================================== #
# SW -- the switches
# ===================================================================== #


def test_sw1_self_learn_stage_0_reverts_the_namespace_end_to_end(env, claude_cli_shim_worker, monkeypatch):
    """SW1 -- a FULL run under the switch, not a file assertion. Broken:
    MA45 (the switch gates only the settings file, leaving S3 reading
    the stage -- zero proposals land, SILENTLY, the worst possible
    behaviour for the control that exists to rescue a bad night)."""
    monkeypatch.setenv("SELF_LEARN_STAGE", "0")
    rid = seed_pending(env)

    settings = worker.write_settings_file(env.home)
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    assert allow == worker.write_permission_rules(env.home)
    assert worker.staged_paths() == []

    legacy_path = env.proposals / f"{rid}.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {legacy_path.parent} && cat > {legacy_path} <<'YAML'\n{_proposal_yaml(env)}YAML",
    )
    result = worker.run(env.home)

    assert legacy_path.is_file()
    assert rid in result.proposed
    assert read_proposal(legacy_path).get("record_sha")
    assert result.not_installed == []
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: stage disabled (SELF_LEARN_STAGE=0)" in log_text

    # Rule-F still fires on a foreign stamped file exactly as U-repair
    # shipped it.
    rid2 = seed_pending(env, "lrn-0000bbbb")
    dest2 = env.proposals / f"{rid2}.yaml"
    stamped2 = dict(_valid_trace(env))
    stamped2["record_sha"] = _stamp_sha(env, rid2)
    stamped2_text = _dump(stamped2)
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, _write_script(dest2, stamped2_text))
    result2 = worker.run(env.home)
    assert rid2 in result2.foreign_left
    assert dest2.read_text(encoding="utf-8") == stamped2_text

    # S3 must read `_written_since`, not the stage, while the switch is
    # off: drive a genuine repair round under SELF_LEARN_STAGE=0 and
    # confirm it actually engages. A version of S3 that still reads the
    # (empty, under the switch) stage sees no candidates at all -- S4's
    # dry-check never runs, the repair round never fires, and a real
    # defect sitting in the ledger is silently deleted instead of
    # repaired. This is the leg the happy-path fixture above cannot
    # catch: S7 independently recomputes the right set for `_harvest`
    # regardless of what S3 saw, so only a repair-round assertion pins
    # S3's own read.
    rid3 = seed_pending(env, "lrn-0000cccc")
    legacy_defect = env.proposals / f"{rid3}.yaml"
    bad = _t4_missing_target(env, rid3)
    fixed = _t4_target_fixed(env, rid3)
    _next_run_scripts(
        claude_cli_shim_worker,
        monkeypatch,
        _write_script(legacy_defect, _dump(bad)),
        _write_script(legacy_defect, _dump(fixed)),
    )
    result3 = worker.run(env.home)

    assert result3.repair_attempted
    assert result3.repair_eligible == 1
    assert result3.repair_cleared == 1
    assert rid3 in result3.proposed


def test_sw2_self_learn_enforce_scope_0_reverts_enforcement_and_only_that(env, claude_cli_shim_worker, monkeypatch):
    """SW2 -- Broken: MA46 (make SELF_LEARN_STAGE=0 drop defaultMode too
    -- reverting a security-relevant change as an undocumented side
    effect of reverting an unrelated one; section 3.7's deliberate
    asymmetry)."""
    monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", "0")
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    result = worker.run(env.home)

    settings = json.loads((worker.cache_dir() / "worker.settings.json").read_text())
    assert "defaultMode" not in settings["permissions"]
    assert settings["permissions"]["allow"] == worker.stage_permission_rules(env.home)
    assert rid in result.proposed  # the stage is still used, install still works

    # the two switches are independent: SELF_LEARN_STAGE=0 ALONE leaves
    # defaultMode PRESENT.
    monkeypatch.delenv("SELF_LEARN_ENFORCE_SCOPE", raising=False)
    monkeypatch.setenv("SELF_LEARN_STAGE", "0")
    settings2 = worker.write_settings_file(env.home)
    data2 = json.loads(settings2.read_text())
    assert data2["permissions"]["defaultMode"] == "default"


# ===================================================================== #
# OB -- the observable surface
# ===================================================================== #


def test_ob1_the_new_lines_exist_with_their_counts(env, claude_cli_shim_worker, monkeypatch):
    """OB1 -- Broken: MA29 (emit the stage line with no count)."""
    rid_ok1 = seed_pending(env, "lrn-0000aaaa")
    rid_ok2 = seed_pending(env, "lrn-0000bbbb")
    rid_decline_fresh = seed_pending(env, "lrn-0000cccc")
    rid_decline_draft = seed_pending(env, "lrn-0000dddd")
    rid_changed = seed_pending(env, "lrn-0000eeee")

    dest_fresh = env.proposals / f"{rid_decline_fresh}.yaml"
    dest_fresh.parent.mkdir(parents=True, exist_ok=True)
    stamped_fresh = dict(_valid_trace(env))
    stamped_fresh["record_sha"] = _STALE_SHA
    dest_fresh.write_text(_dump(stamped_fresh), encoding="utf-8")

    dest_draft = env.proposals / f"{rid_decline_draft}.yaml"
    dest_draft.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    commit_all(env.home, "seed declines")

    dest_changed = env.proposals / f"{rid_changed}.yaml"
    changed_data = dict(_valid_trace(env))
    changed_data["record_sha"] = _stamp_sha(env, rid_changed)

    concurrent_fresh = dict(_valid_trace(env))
    concurrent_fresh["rationale"] = "attended session"
    concurrent_fresh["record_sha"] = _stamp_sha(env, rid_decline_fresh)

    script = "\n".join([
        shim_writes(env, rid_ok1),
        shim_writes(env, rid_ok2),
        shim_writes(env, rid_decline_fresh),
        shim_writes(env, rid_decline_draft),
        _write_script(dest_fresh, _dump(concurrent_fresh)),
        _write_script(dest_changed, _dump(changed_data)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    worker.run(env.home)

    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: stage — 4 file(s) written by the model" in log_text
    assert "run: 2 ledger proposal(s) changed during the window — not this run's writes" in log_text
    assert (
        f"run: staged proposal {rid_decline_fresh}.yaml not installed — "
        "destination changed during the window"
    ) in log_text
    assert (
        f"run: staged proposal {rid_decline_draft}.yaml not installed — "
        "destination is an unstamped draft this run did not write"
    ) in log_text


def test_ob2_the_new_fields_are_populated(env, claude_cli_shim_worker, monkeypatch):
    """OB2 -- Broken: MA30 (never assign foreign_seen, leaving it 0)."""
    rid_ok = seed_pending(env, "lrn-0000aaaa")
    rid_decline = seed_pending(env, "lrn-0000bbbb")
    dest_decline = env.proposals / f"{rid_decline}.yaml"
    dest_decline.parent.mkdir(parents=True, exist_ok=True)
    stamped = dict(_valid_trace(env))
    stamped["record_sha"] = _STALE_SHA
    dest_decline.write_text(_dump(stamped), encoding="utf-8")
    commit_all(env.home, "seed a fresh destination")
    concurrent = dict(_valid_trace(env))
    concurrent["rationale"] = "attended session"
    concurrent["record_sha"] = _stamp_sha(env, rid_decline)

    script = "\n".join([
        shim_writes(env, rid_ok),
        shim_writes(env, rid_decline),
        _write_script(dest_decline, _dump(concurrent)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result = worker.run(env.home)

    assert result.staged_written == 2
    assert result.not_installed == [f"{rid_decline}.yaml"]
    assert result.foreign_seen == 1


def test_ob3_existing_fields_keep_their_meaning_touched_keeps_its_type(env, claude_cli_shim_worker, monkeypatch):
    """OB3 -- Broken: MA31 (count declines in invalid_deleted -- the one
    thing this field must never be able to say falsely), MA47 (discard
    staged files through _git_rm_or_unlink, which appends to touched)."""
    rid_ok = seed_pending(env, "lrn-0000aaaa")
    rid_invalid = seed_pending(env, "lrn-0000bbbb")
    rid_decline = seed_pending(env, "lrn-0000cccc")
    dest_decline = env.proposals / f"{rid_decline}.yaml"
    dest_decline.parent.mkdir(parents=True, exist_ok=True)
    stamped = dict(_valid_trace(env))
    stamped["record_sha"] = _STALE_SHA
    dest_decline.write_text(_dump(stamped), encoding="utf-8")
    commit_all(env.home, "seed a fresh destination")
    bad_data = dict(_valid_trace(env))
    bad_data["destination"] = "not-a-real-destination"
    concurrent = dict(_valid_trace(env))
    concurrent["rationale"] = "attended session"
    concurrent["record_sha"] = _stamp_sha(env, rid_decline)

    script = "\n".join([
        shim_writes(env, rid_ok),
        _write_script(worker.stage_dir() / f"{rid_invalid}.yaml", _dump(bad_data)),
        shim_writes(env, rid_decline),
        _write_script(dest_decline, _dump(concurrent)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result = worker.run(env.home)

    assert f"{rid_decline}.yaml" not in result.invalid_deleted
    assert f"{rid_decline}.yaml" in result.not_installed
    assert result.invalid_deleted == [f"{rid_invalid}.yaml"]
    for path in result.touched:
        assert path.is_relative_to(env.home)
        assert not path.is_relative_to(worker.stage_dir())


def test_ob4_workers_internals_stay_out_of_operator_surfaces(env, claude_cli_shim_worker, monkeypatch, capsys):
    """OB4 -- Broken: MA32 (add the counts to _cmd_worker's summary --
    the harmless-looking edit that annexes FW-82's scope in one line)."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    rc = cli.main(["worker", "run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert re.match(
        r"worker run: ok — \d+ proposal\(s\), \d+ merge, \d+ eligible, "
        r"\d+ recurrence suspect\(s\)\n?$",
        out,
    )
    for forbidden in ("not_installed", "staged_written", "foreign_seen"):
        assert forbidden not in out

    status = worker.fast_status(env.home)
    assert set(status.keys()) == {
        "buckets", "total_pending", "unanalyzed_total", "oldest_days",
        "worker_last_run", "staleness_alarm", "escalate",
    }

    ui_dir = Path(__file__).resolve().parent.parent.parent / "ui" / "src"
    assert ui_dir.is_dir(), ui_dir
    for path in ui_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("not_installed", "staged_written", "foreign_seen"):
            assert forbidden not in text, (path, forbidden)


# ===================================================================== #
# HY -- hygiene
#
# HY3 ("pyright is clean") is instrument-only in the spec's own words --
# satisfied by the pyright run recorded in the build report, not a
# function here (see this file's module docstring).
# ===================================================================== #


def test_hy1_no_test_in_the_suite_invokes_a_real_claude(env):
    """HY1 -- Broken: U-repair's M36/M52, which must still redden the
    shipped (bucket-1, unmodified) `test_repair.py::test_f6_no_test_
    invokes_a_real_claude`. Re-verified SUITE-WIDE here, plus the shim's
    multi-invocation-observability."""
    tests_dir = Path(__file__).parent
    pattern = re.compile(r'\[\s*"claude"\s*\]')
    hits: list[tuple[str, int, str]] = []
    for path in sorted(tests_dir.glob("*.py")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                hits.append((path.name, i, line))
    assert hits, "no claude-argv literal found anywhere -- HY1 has nothing to pin"
    for fname, lineno, line in hits:
        assert "worker._invoke_claude(" in line, (fname, lineno, line)

    from test_worker import claude_cli_shim_worker as _claude_shim_fixture

    shim_src = inspect.getsource(_claude_shim_fixture)
    assert "claude-invocation-count" in shim_src
    assert "claude-calls" in shim_src


def test_hy2_lock_invariant_exemption_list_is_honest():
    """HY2 -- Broken: MA33 (add the entries by wildcard, or add one
    covering _validate_written -- the dangerous direction: it would
    exempt the function that legitimately mutates the ledger)."""
    from test_lock_invariant import NOT_REPO_TRUTH

    assert "worker.stage_reset" in NOT_REPO_TRUTH
    assert "cache" in NOT_REPO_TRUTH["worker.stage_reset"].lower()
    assert "worker._stage_discard" in NOT_REPO_TRUTH
    assert "cache" in NOT_REPO_TRUTH["worker._stage_discard"].lower()
    assert "worker._validate_written" not in NOT_REPO_TRUTH
    assert "worker._install_staged" not in NOT_REPO_TRUTH


def test_hy4_the_install_is_visible_to_the_lock_invariant_analyser():
    """HY4 -- Broken: MA48 (install with shutil.copy2, replacing both
    primitives -- the whole install becomes invisible to the invariant
    and the suite still passes: a green suite proving nothing)."""
    import ast

    from test_lock_invariant import _primitive

    src = inspect.getsource(worker._install_staged)
    tree = ast.parse(src)

    replace_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "replace"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "os"
    ]
    assert len(replace_calls) == 1
    assert _primitive(replace_calls[0]) == "os.replace"

    write_text_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "write_text"
    ]
    assert write_text_calls
    for call in write_text_calls:
        assert _primitive(call) == "Path.write_text"

    src_worker_module = Path(worker.__file__).read_text(encoding="utf-8")
    assert "shutil.copy" not in src_worker_module
