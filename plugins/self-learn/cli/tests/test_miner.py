"""Doc 12 (transcript miner): digest determinism + M-5 exclusions, cursor
walk, use-scaled caps, gate/dedup/reconciliation, scan-gated landing,
journal contract, watchdog, and the CLI/status surface.

The reader model is shimmed at `_invoke_reader` (unit/e2e) or via a PATH
`claude` shim (artifact-contract test) — the same honesty rule as the
worker suite: shims emit what the model actually would, never
pre-satisfied spec-forbidden fields.
"""

import fcntl
import json
import os
import time
from pathlib import Path

import pytest

from self_learn import cli, intents, miner, telemetry
from self_learn.ledger_ops import create_record
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_home


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


@pytest.fixture()
def home(tmp_path, monkeypatch):
    # doc-13: `home` is the LEDGER; make_home also builds the paired HOST
    # (tmp_path/host-repo) whose registered skill dir supplies skill:s.
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


@pytest.fixture()
def transcripts(tmp_path, monkeypatch):
    root = tmp_path / "transcripts"
    (root / "-home-u-proj").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    # Most tests exercise steady-state mining: mark the forward-only
    # initialization as already done (its own behavior is tested in
    # test_first_run_initializes_forward_only).
    miner._save_cursors({"__initialized__": "test-fixture"})
    return root


# ------------------------------------------------------- line builders


def u(text):
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
    )


def u_str(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def a(text):
    return json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    )


def tool(name, command, tid):
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": tid, "name": name, "input": {"command": command}}
                ]
            },
        }
    )


def result(tid, text, is_error=False):
    return json.dumps(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "is_error": is_error,
                        "content": [{"type": "text", "text": text}],
                    }
                ],
            },
        }
    )


def write_transcript(root, name, lines, project="-home-u-proj"):
    path = root / project / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def slice_of(path, start=0):
    lines = path.read_text(encoding="utf-8").splitlines()
    return miner.SessionSlice(
        path=path,
        session_id=path.stem,
        project=path.parent.name,
        start_line=start,
        lines=lines[start:],
    )


# ------------------------------------------------------------- digest


def test_digest_keeps_speech_drops_tool_bodies(transcripts):
    body = "\n".join(f"noise line {i}" for i in range(50))
    p = write_transcript(
        transcripts,
        "sess1",
        [
            u("please fix the flaky test"),
            tool("Bash", "uv run pytest -q", "t1"),
            result("t1", body),
            a("The root cause was a stale fixture."),
        ],
    )
    digest, halt = miner.digest_transcript(slice_of(p))
    assert not halt
    assert "please fix the flaky test" in digest
    assert "The root cause was a stale fixture." in digest
    assert "noise line 25" not in digest  # body dropped to edges
    assert "noise line 0" in digest and "noise line 49" in digest
    assert "uv run pytest" in digest  # command shape survives
    assert "[user L1]" in digest and "L4]" in digest  # line refs for origins


def test_digest_error_and_retry_cluster(transcripts):
    lines = []
    for i in range(3):
        lines.append(tool("Bash", "make build --fast", f"t{i}"))
        lines.append(result(f"t{i}", "boom", is_error=(i < 2)))
    lines.append(u("ugh, again"))
    p = write_transcript(transcripts, "sess2", lines)
    digest, _halt = miner.digest_transcript(slice_of(p))
    assert "ERROR" in digest
    assert "[retry-cluster Bash:make build ×3, 2 error(s)]" in digest


def test_digest_excludes_own_machinery(transcripts):
    p = write_transcript(
        transcripts,
        "worker-sess",
        [u("You are the self-learn routing analyst worker. Records below."), a("ok")],
    )
    assert miner.digest_transcript(slice_of(p)) == (None, True)
    p2 = write_transcript(
        transcripts,
        "miner-sess",
        [u("You are the self-learn transcript miner. Digests below."), a("ok")],
    )
    assert miner.digest_transcript(slice_of(p2)) == (None, True)


def test_digest_selflearn_tag_halts_rest_of_session(transcripts):
    """Audit 2026-07-15 B2: the old span rule collapsed on the first user
    reply — a review session's card content (verbatim lesson text) was
    mined back as fake sightings. The tag now halts the WHOLE remainder,
    including the user's own review replies, forever."""
    p = write_transcript(
        transcripts,
        "sess3",
        [
            u("normal work before"),
            u("<command-name>/self-learn:review</command-name> run it"),
            a("Card 1 of 3: the lesson about storage edits…"),
            u("route it"),  # the realistic next turn — a review reply
            a("Card 2 of 3: another lesson's full trigger text…"),
        ],
    )
    digest, halt = miner.digest_transcript(slice_of(p))
    assert halt is True
    assert "normal work before" in digest
    assert "Card 1 of 3" not in digest
    assert "route it" not in digest
    assert "Card 2 of 3" not in digest


def test_digest_plain_string_content(transcripts):
    p = write_transcript(transcripts, "sess4", [u_str("string-content user turn")])
    digest, _halt = miner.digest_transcript(slice_of(p))
    assert "string-content user turn" in digest


# ------------------------------------------------------------- walk


def test_walk_cursor_advance_and_append(transcripts):
    p = write_transcript(transcripts, "sess5", [u("one"), u("two")])
    slices = miner.walk()
    assert len(slices) == 1 and slices[0].start_line == 0
    miner._advance_cursors([(s, False) for s in slices])
    assert miner.walk() == []
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(u("three") + "\n")
    slices = miner.walk()
    assert len(slices) == 1
    assert slices[0].start_line == 2 and len(slices[0].lines) == 1


def test_walk_since_rereads_from_zero(transcripts):
    p = write_transcript(transcripts, "sess6", [u("old content")])
    miner._advance_cursors([(s, False) for s in miner.walk()])
    assert miner.walk() == []
    slices = miner.walk(since="2020-01-01")
    assert len(slices) == 1 and slices[0].start_line == 0
    assert miner.walk(since="2999-01-01") == []
    assert p.is_file()


# ------------------------------------------------------------- caps


def test_cap_scales_with_use(monkeypatch):
    assert miner.cap_for(1) == 2
    assert miner.cap_for(4) == 8
    assert miner.cap_for(50) == 15  # ceiling
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "5")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "40")
    assert miner.cap_for(4) == 20
    assert miner.cap_for(100) == 40


# ------------------------------------------------- run: guards + journal


def test_run_disabled(home, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER", "0")
    assert miner.run(home).status == "disabled"


def test_run_busy_under_live_lock(home, transcripts):
    lock = miner.miner_dir() / "miner.lock"
    with open(lock, "w", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        assert miner.run(home).status == "busy"


def test_run_idle_journals_and_touches(home, transcripts):
    result = miner.run(home)
    assert result.status == "idle"
    assert (miner.miner_dir() / "miner.last-run").is_file()
    entries = miner.read_journal()
    assert entries and entries[-1]["status"] == "idle"
    assert entries[-1]["trigger"] == "manual"


def test_run_ends_at_start_on_a_live_stop(home):
    """§7.2a.5(4)/§7.2a.8: "a run that sees a `stopped` outcome ends
    there... before enumeration and before any model session is spent."
    No `transcripts` fixture -- this must never reach transcript-walking
    at all. Same plant recipe as `test_intents.py`'s own
    `test_stop_when_prior_content_is_unresolvable_anywhere`: an
    unrelated commit moves HEAD past the intent's `old_sha`, so no
    source (worktree/HEAD/inline) can resolve it."""
    f = home / "a.txt"
    f.write_text("old", encoding="utf-8")
    commit_all(home, "seed")
    intent = intents.begin(home, "test-op", [f], "self-learn: test op")
    f.write_text("mutated", encoding="utf-8")
    git(home, "add", "-A")
    git(home, "commit", "-q", "-m", "an unrelated commit moves HEAD past old_sha")
    f.write_text("further mutated, still uncompleted", encoding="utf-8")

    result = miner.run(home)

    assert result.status == "stopped"
    assert result.stopped and intent.id in result.stopped[0]
    entries = miner.read_journal()
    assert entries and entries[-1]["status"] == "stopped"
    # Never enumerated, never mined for -- the intent is left exactly
    # where the STOP found it, for a human.
    assert intent.file_path.exists()


# ----------------------------------------------- run: e2e with shimmed reader


def shim_reader(monkeypatch, payload):
    """Replace the model pass: write `payload` as the output artifact."""

    def fake(home, prompt):
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps(payload), encoding="utf-8")
        return out

    monkeypatch.setattr(miner, "_invoke_reader", fake)


def candidate(**over):
    base = {
        "scope": "skill:s",
        "type": "behavior",
        "kind": "anti-pattern",
        "trigger": "About to cp -r a uv project into a sandbox",
        "instruction": "Delete the copied .venv first — the editable install points at the original tree",
        "quote": "rm -rf .venv fixed it",
        "session": "sess-e2e",
        "line": 42,
        "verified": True,
        "verified_how": "reproduced twice in-session",
        "incident_cost": "two invalidated runs",
        "generality": "general-practice",
        "confidence": "high",
        "why_durable": "will recur in any sandboxed uv experiment",
        "match": {"record": None, "status": None},
    }
    base.update(over)
    return base


def pending_ids(home):
    out = []
    for d in home.glob("skills/*/pending/lrn-*.md"):
        out.append(d.stem)
    for d in home.glob("projects/*/pending/lrn-*.md"):
        out.append(d.stem)
    for d in home.glob("user/pending/lrn-*.md"):
        out.append(d.stem)
    return out


@pytest.mark.parametrize("with_uuid", [False, True])
def test_rejected_old_sighting_does_not_count_again(home, transcripts, with_uuid):
    rows = [{"type": "user", "message": {"content": text}} for text in
            ("opening\u2028turn", "already observed", "new observation")]
    if with_uuid:
        for n, row in enumerate(rows):
            row["uuid"] = f"rejected-{n}"
    write_transcript(transcripts, "sess-rejected-old", [json.dumps(row, ensure_ascii=False) for row in rows])
    path = miner.miner_dir() / "rejected-sightings.json"
    path.write_text(json.dumps({"lrn-11111111": ["transcript:sess-rejected-old#L3"]}))
    assert json.loads(path.read_text())["lrn-11111111"] == ["transcript:sess-rejected-old#L3"]
    assert miner._rejected_counter_bump("lrn-11111111", "transcript:sess-rejected-old#L2") == 1
    assert miner._rejected_counter_bump("lrn-11111111", "transcript:sess-rejected-old#L2") == 1
    assert miner._rejected_counter_bump("lrn-11111111", "transcript:sess-rejected-old#L3") == 2
    assert miner._rejected_counter_bump("lrn-11111111", "transcript:sess-rejected-old#L3") == 2


# --------------------------------------------- episode briefs (12 §11 / U18)


def test_teach_sourced_record_never_carries_episode_brief(home):
    """The brief is written ONLY by the miner's _build_record — a
    teach/import-created record (this ledger's create_record path, never
    touching miner.py) has no section, by construction (12 §11)."""
    record = make_behavior()
    create_record(home, record)
    landed = Record.from_path(home / "skills/s/pending" / f"{record.id}.md")
    assert landed.source == "teach"
    assert "## Episode brief" not in landed.body


def test_reader_prompt_pins_episode_brief_instruction(home):
    """Live model output cannot be asserted in a unit test — pin the
    prompt TEXT instead (100-200 words, plain-words retell-never-quote
    register, optional-and-omittable framing)."""
    prompt, corrupt = miner._compose_prompt(home, ["(digest)"], Path("/tmp/out.json"))
    assert corrupt == []
    assert '"episode_brief"' in prompt
    assert "100-200 words" in prompt
    assert "RETELL, never quote" in prompt
    assert "optional" in prompt.lower()


def test_reader_prompt_pins_three_value_fire_outcome(home):
    """U6 (12 §Phase-2 contract; rubric lines 70–76): the prompt's fire shape
    names the three suspicion values and never the retired two. The
    acceptance check refuses the old values, so a prompt that reverted to
    them would have every fire silently dropped — pin the TEXT."""
    prompt, corrupt = miner._compose_prompt(home, ["(digest)"], Path("/tmp/out.json"))
    assert corrupt == []
    assert '"suspected-compliance"' in prompt
    assert '"suspected-violation"' in prompt
    assert '"cannot-tell"' in prompt
    assert '"outcome": "complied"' not in prompt
    assert '"complied" | "violated"' not in prompt


def _resolve(home, record, status):
    """Move a pending record to resolved/ with the given status."""
    record.set_status(status)
    resolved = home / "skills/s/resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    path = resolved / f"{record.id}.md"
    record.write(path)
    return path


# --------------------------------------------------- reader containment


# U-cleanup-B DELETE (§8.4a: "test_hosting.py, test_miner.py:746 and
# test_lock_invariant.py:148 cannot be migrated: their subject -- that a
# settings file is written to a particular place -- is deleted"):
# `test_reader_argv_and_settings` drove `miner.write_reader_settings` and
# `miner.build_reader_argv`, both deleted (§8.1/§8.3) -- the reader round
# has no argv and no on-disk settings file any more (`options_kwargs(spec)`
# feeds the sdk seam directly, `settings=None`). Every guarantee this test
# checked survives elsewhere against the real sdk transport:
#   - allow-rule scoped to .../spool/**, repo out of write reach ->
#     test_reader_contract.py::test_ct2_options_kwargs_matches_c_c_table_
#     and_key_set, test_ct4_write_to_spool_artifact_allowed_lands_on_disk,
#     test_ct5_write_outside_spool_denied_two_targets
#   - defaultMode "default" (the security hotfix) ->
#     test_reader_contract.py::test_ct2 (settings=None pins the same
#     default-mode contract at the containment layer)
#   - no filesystem tools reach the model (Bash/Edit/Read/Grep/Glob/
#     WebFetch denied) ->
#     test_reader_contract.py::test_ct6_read_grep_glob_denied_with_step1_
#     wording, test_ct5, test_ct8_hatch_permanently_closed_even_with_
#     enforce_scope_unset
#   - prompt never in argv, always on stdin (audit B1) ->
#     test_reader_contract.py::test_rc7_prompt_reaches_the_model_on_
#     stdin_never_argv
#   - no dead settings file survives under the cache dir ->
#     test_reader_contract.py::test_rc8_no_dead_settings_write_under_
#     the_cache_dir


# U-cleanup-B DELETE (code gate r1, NIT-6): `test_reader_survives_
# oversize_prompt` -- left `@pytest.mark.skip`ped by Phase A with no
# further disposition, per A's inherit list. Its subject (E2BIG-via-
# argv on a >128KiB prompt) is a `CliBackend` transport-mechanics
# concern that cannot recur under `SdkBackend` -- the prompt never
# touches argv/exec at all -- and its own skip reason already named
# the replacement: `test_reader_contract.py::test_rc7_prompt_reaches_
# the_model_on_stdin_never_argv` (200KiB, spies the real wire + the
# real child's argv log). This was also the suite's LAST surviving
# FUNCTIONAL inline bash `claude` shim -- one whose script actually
# answers on the model's behalf (writes an `OUTPUT_BASENAME` payload)
# rather than existing purely as a PATH-hygiene negative control.
# `test_reader_contract.py::_shadow_claude` still writes a decoy to a
# `shims/claude` path -- deliberately, per its own docstring: it
# exits 1 and answers nothing, a tripwire for "this leg should never
# reach here", not a functioning fake CLI. That one is not this NIT's
# subject and stays.


def test_artifact_contract_sweeps_strays(home, tmp_path, monkeypatch):
    spool = miner.spool_dir()
    # U-cleanup-A: sdk-backed replacement for the bash `claude` PATH shim
    # -- `fake_claude.py`'s `shim_script` scenario interprets these SAME
    # `echo CONTENT > path` lines via its `_ECHO_RE` idiom (bare,
    # unquoted paths -- no spaces in a pytest tmp_path, matching every
    # other write idiom this interpreter already supports).
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")
    monkeypatch.setenv(
        "SELF_LEARN_SDK_CLI_PATH",
        str(Path(__file__).parent / "fixtures" / "fake_claude.py"),
    )
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "shim_script")
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"echo stray > {spool}/litter.txt\n"
        f'echo \'{{"candidates": [], "fires": []}}\' > {spool}/{miner.OUTPUT_BASENAME}\n',
    )
    out = miner._invoke_reader(home, "PROMPT")
    assert out is not None and out.is_file()
    assert not (spool / "litter.txt").exists()


# ----------------------------------------------------------- watchdog


def test_maybe_kick_disabled_fresh_spawned(home, monkeypatch):
    assert miner.maybe_kick(home) == "disabled"  # conftest sets AUTOKICK=0
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "1")
    spawned = []
    monkeypatch.setattr(
        miner, "_spawn_run", lambda h, **kw: spawned.append(h) or 4242
    )
    assert miner.maybe_kick(home) == "spawned"  # no last-run = infinitely old
    assert spawned == [home]
    (miner.miner_dir() / "miner.last-run").touch()
    assert miner.maybe_kick(home) == "fresh"
    monkeypatch.setenv("SELF_LEARN_MINER", "0")
    assert miner.maybe_kick(home) == "disabled"


def test_stale_predicate(home, monkeypatch):
    assert miner.stale() is True  # never ran = alarm (self-healing via kick)
    (miner.miner_dir() / "miner.last-run").touch()
    assert miner.stale() is False
    monkeypatch.setenv("SELF_LEARN_MINER", "0")
    assert miner.stale() is False  # deliberately disabled never alarms


# ------------------------------------------------------------ CLI surface


def test_status_fast_carries_miner_keys(home, capsys):
    assert cli.main(["status", "--fast"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["miner_last_run"] is None
    assert data["miner_stale"] is True


# ------------------------------------------------------- report (T-M5)


# ----------------------------------------- audit-fix regressions (round 1)


def test_torn_trailing_line_left_for_next_run(transcripts):
    p = transcripts / "-home-u-proj" / "sess-torn.jsonl"
    p.write_text(u("complete line") + "\n" + '{"type":"user","mes', encoding="utf-8")
    slices = miner.walk()
    assert len(slices) == 1 and len(slices[0].lines) == 1
    miner._advance_cursors([(slices[0], False)])
    # the torn tail completes later
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('sage":{"role":"user","content":"finished now"}}\n')
    slices = miner.walk()
    assert len(slices) == 1
    assert slices[0].start_line == 1  # the once-torn line is NOW read
    assert "finished now" in slices[0].lines[0]


def test_walk_skips_unchanged_files_without_reading(transcripts, monkeypatch):
    p = write_transcript(transcripts, "sess-skip", [u("one")])
    slices = miner.walk()
    miner._advance_cursors([(s, False) for s in slices])
    reads = []
    real = miner._complete_lines
    monkeypatch.setattr(
        miner, "_complete_lines", lambda path: reads.append(path) or real(path)
    )
    assert miner.walk() == []
    assert reads == []  # size unchanged → no I/O
    assert p.is_file()


# ---------------------------------------- cursor hold (U-cursorhold, FW-73)
#
# Rule-H (spec §3.1): a cap-dropped candidate holds its originating
# session's cursor UNLESS that slice is halted (M-5 wins) or unmatched
# (the reader never actually saw that session's text this run).


_A10_OVERLENGTH_WHY_DURABLE = (
    "This candidate exists to model the exact drained scenario measured "
    "in the run journal, where a single session produced far more "
    "distinct lessons than the per run landing cap could ever absorb in "
    "one pass, and the fourth of those dropped candidates carried a "
    "snippet so long that the near miss surface itself refused to keep "
    "any content at all, leaving only a bare overlength marker behind "
    "for a human reviewer to see, which is precisely why holding that "
    "candidate cursor is the only path back to it, since the near miss "
    "promote button had genuinely nothing else to offer this session."
)


# --------------------- steward build U6: fire is a suspicion, not a verdict


def test_live_fires_loop_skips_non_routed_record(home, transcripts, monkeypatch):
    """Code-gate F1 (steward build, U6: THE CROSSOVER this guard used to
    sit above is gone, but the routed guard itself is unchanged and still
    load-bearing) — a `suspected-violation` fire naming a `superseded`
    record must raise no `fire` event at all: `found[0].status !=
    "routed"` is checked BEFORE the fire is ever spooled, so a
    non-routed record leaves nothing behind, not even evidence."""
    superseded = make_behavior()
    _resolve(home, superseded, "superseded")
    write_transcript(transcripts, "sess-nonrouted", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "fires": [
                {"record": superseded.id, "session": "sess-nonrouted",
                 "line": 5, "outcome": "suspected-violation"}
            ],
        },
    )
    result = miner.run(home)
    assert result.fires == 0
    assert result.recurrences == []
    events = telemetry.read_events(home)
    assert [e for e in events if e.get("kind") == "fire"] == []
    assert [e for e in events if e.get("kind") == "recurrence-suspect"] == []


# =================================================== FW-34: near-miss visibility

SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6Q7r8"


def test_every_disposition_has_a_reason(home):
    """Blind-review fold 1 (table-completeness): every value
    `_NEARMISS_DISPOSITION` can produce must have a plain-words reason —
    an addition to the fold table with no matching `_NEARMISS_REASON`
    entry would KeyError at journal-write time on the very outcome it
    was meant to enrich (`_enrich_near_miss`'s `_NEARMISS_REASON[disposition]`
    lookup, not `.get`)."""
    dispositions = set(miner._NEARMISS_DISPOSITION.values())
    assert dispositions  # the table itself is non-empty — a vacuous pass is not a pass
    missing = dispositions - set(miner._NEARMISS_REASON)
    assert not missing, f"disposition(s) in the fold table with no reason: {missing}"


# ------------------------------------------------------- FW-34 §3: canaries


def test_canary_plant_writes_cache_entry(home):
    canary_id = miner.plant_canary(
        "always run go vet before committing Go changes", expect="go vet"
    )
    assert canary_id
    canaries = miner._load_canaries()
    assert len(canaries) == 1
    assert canaries[0]["id"] == canary_id
    assert canaries[0]["lesson"] == "always run go vet before committing Go changes"
    assert canaries[0]["expect"] == "go vet"
    assert canaries[0]["status"] == "open"


def test_canary_plant_refuses_dp2(home):
    """t-g: `plant --lesson` naming DP-2 is refused — the standing
    window-placement experiment is never planted artificially."""
    with pytest.raises(miner.CanaryError):
        miner.plant_canary("the DP-2 window placement rule should always apply")
    assert miner._load_canaries() == []
    # case-insensitive + inside --expect too
    with pytest.raises(miner.CanaryError):
        miner.plant_canary("a fine lesson", expect="matches dp-2 somehow")
    assert miner._load_canaries() == []


def test_canary_plant_cli_refuses_dp2(home, capsys):
    """The CLI surface: a usage exit, nothing written."""
    rc = cli.main(["canary", "plant", "--lesson", "always honor DP-2"])
    assert rc == cli.EXIT_USAGE
    assert "DP-2" in capsys.readouterr().err
    assert miner._load_canaries() == []


def test_canary_plant_writes_no_transcript(home, transcripts):
    """t-h: plant creates/mutates no `*.jsonl` under any transcripts
    dir — the honesty pin: canaries never forge transcript content."""
    before = sorted(transcripts.rglob("*.jsonl"))
    miner.plant_canary("always double check migrations before applying them")
    after = sorted(transcripts.rglob("*.jsonl"))
    assert before == after == []
    assert miner.canaries_path().is_file()


# ============================================== FW-53: ledger decode safety
#
# A record file that is not valid UTF-8 (a torn write, a bad merge, a
# hand edit) must never wedge a whole `mine run`. Confirmed pre-existing:
# `_compose_prompt` -> `_ledger_index` -> `Record.from_path` -> `read_text`
# ran BEFORE `_reconcile_and_land`, so `run()`'s outer handler turned the
# ENTIRE run into `status: failed` on one bad byte, before the reader was
# ever invoked. Decision: skip the corrupt file, count it, land everything
# else (the nightly producer degrades, it does not stop) — but the skip
# is REPORTED, never silent: `result.corrupt_records`, every journal entry
# from the point of detection onward, `miner.log`, and the human-readable
# `mine status` one-liner all carry it.


def _write_bad_bytes(path: Path, prefix: str = "") -> None:
    """`prefix` (valid UTF-8) + bytes that are not valid UTF-8 anywhere —
    guaranteed to raise `UnicodeDecodeError` on decode (mirrors
    selfcheck.py's own FW-66 helper of the same name/shape)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(prefix.encode("utf-8") + b"\xff\xfe garbage")


def test_ledger_index_skips_undecodable_record_and_reports_it(home):
    good = make_behavior(record_id="lrn-00009999")
    pending = home / "skills/s/pending"
    pending.mkdir(parents=True, exist_ok=True)
    good.write(pending / f"{good.id}.md")
    bad_path = pending / "lrn-0badbeef.md"
    _write_bad_bytes(bad_path, "---\ntype: behavior\nid: lrn-0badbeef\n---\n")

    corrupt: list[Path] = []
    index = miner._ledger_index(home, corrupt)

    assert good.id in index
    assert "lrn-0badbeef" not in index
    assert corrupt == [bad_path]


def test_canon_index_skips_undecodable_record_and_reports_it(home):
    routed = make_behavior(record_id="lrn-00009999")
    _resolve(home, routed, "routed")
    bad_path = home / "skills/s/resolved" / "lrn-0badbeef.md"
    _write_bad_bytes(
        bad_path, "---\ntype: behavior\nid: lrn-0badbeef\nstatus: routed\n---\n"
    )

    corrupt: list[Path] = []
    index = miner._canon_index(home, corrupt)

    assert routed.id in index
    assert "lrn-0badbeef" not in index
    assert corrupt == [bad_path]


def test_compose_prompt_surfaces_corrupt_records_without_crashing(home):
    _write_bad_bytes(
        home / "skills/s/pending" / "lrn-0badbeef.md",
        "---\ntype: behavior\nid: lrn-0badbeef\n---\n",
    )

    prompt, corrupt = miner._compose_prompt(home, ["(digest)"], Path("/tmp/out.json"))

    assert len(corrupt) == 1
    assert corrupt[0].name == "lrn-0badbeef.md"
    assert "(digest)" in prompt  # composition still completed


def test_find_record_returns_none_for_undecodable_file_never_raises(home):
    _write_bad_bytes(
        home / "skills/s/pending" / "lrn-0badbeef.md",
        "---\ntype: behavior\nid: lrn-0badbeef\n---\n",
    )

    assert miner._find_record(home, "lrn-0badbeef") is None


# ============================== M-W/D7 gate r1 fold: BLOCKER-2/MAJOR-3(d)


def test_mine_recovers_a_restorable_intent_and_logs_it(home):
    """Gate r1 BLOCKER-2 / MAJOR-3(d): a mine START must recover a
    RESTORABLE intent left by a previous run's crash, complete
    normally, and LOG the recovery — pins the fix at `_run_locked`'s own
    self-heal block. Before the fix, `if healed.healed:` was true here
    with `healed.committed` empty (nothing to reconcile, only an intent
    to recover), and `healed.sha[:7]` crashed the WHOLE mine run with an
    uncaught `TypeError` — this is the identical shape, minus the
    SIGKILL: a real intent planted directly, recovery running for real
    inside a real `miner.run(home)` call. No cursors are initialized, so
    this reaches `status == "initialized"` (the first-activation path)
    right after recovery, without ever touching the reader/SDK — the
    self-heal step runs BEFORE that check, so it is exercised either
    way."""
    f = home / "a.txt"
    f.write_text("old", encoding="utf-8")
    commit_all(home, "seed")
    intent = intents.begin(home, "test-op", [f], "self-learn: test op")
    f.write_text("mutated, crash before complete()", encoding="utf-8")  # never completed

    result = miner.run(home)

    assert result.status == "initialized"  # the mine run itself completes, no crash
    assert f.read_text(encoding="utf-8") == "old"
    assert not intent.file_path.exists()
    log_text = (miner.miner_dir() / "miner.log").read_text(encoding="utf-8")
    assert f"recovered {intent.id} (restored: its mutation was undone)" in log_text


@pytest.mark.parametrize("encode", [u, u_str])
def test_digest_omits_compact_provenance_note_keeps_user_control(tmp_path, encode):
    marker = "[compact-provenance note: written by a mod, not typed by the user]"
    # A note can quote a failing label containing a command tag: it is noise,
    # not an instruction to halt mining the rest of the session.
    note = marker + '\n\nUnverified: <command-name>/self-learn:review</command-name>'
    path = tmp_path / "compact-note.jsonl"
    path.write_text("\n".join([
        encode(note),
        encode("Please keep this ordinary user turn."),
        encode("I am quoting the marker: " + marker),
        encode(marker + " is the marker I saw"),
        json.dumps({"type": "user", "origin": {"kind": "human"},
                    "message": {"content": marker + "\nHuman-authored explanation."}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "text", "text": marker + "\nMixed-block explanation."},
            {"type": "text", "text": "Please keep my comment too."},
        ]}}),
    ]) + "\n")
    digest, halt = miner.digest_transcript(slice_of(path))
    assert digest is not None
    assert "[user L2] Please keep this ordinary user turn." in digest
    assert "[user L3] I am quoting the marker: " + marker in digest
    assert "[user L4] " + marker + " is the marker I saw" in digest
    assert "Human-authored explanation." in digest
    assert "Mixed-block explanation." in digest
    assert "Please keep my comment too." in digest
    assert not halt
    assert "Unverified:" not in digest
    assert "L1]" not in digest
