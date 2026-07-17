"""T13/T14/T15: worker kick/coalesce/run, digest, validation + sweep,
events.jsonl, notification template, escalation, fast status, and the
11 §2.2 recurrence-suspect rider.

The `claude` binary is a PATH shim that records argv and writes proposal
files per a test-provided script; `claude-skills-sync` is a sandbox stub.
All cache state is XDG-redirected; the ledger is a sandbox git repo.
"""

import json
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from self_learn import cli, telemetry, worker
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_env, proposal_dict

SKILL_MD = "# s skill\n\nAuthored prose stays put.\n"

PROPOSAL_YAML = """destination: skill-md
alternates: [reference]
rationale: "shim-written proposal"
already_canon: false
model: claude-sonnet-5
analyzed_at: "2026-07-15T00:00:00Z"
card:
  headline: "A test headline."
  impact: "Next time Claude does X it will Y."
  discuss: "Nothing contentious."
"""


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


class Env:
    """doc-13 pair: `home` is the LEDGER (SELF_LEARN_HOME); the worker
    reads/writes the ledger's skill bucket, and reads canon from the HOST
    skill dir via the registry."""

    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir  # HOST skill dir (canon source)
        self.skill_md = sandbox.skill_md
        # make_env already seeded SKILL.md with identical content; keep the
        # HOST clean (no dangling uncommitted change).
        self.bucket = self.home / "skills" / "s"  # LEDGER skill bucket
        self.bare = tmp_path / "remote.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.bare)],
            check=True,
        )
        git(self.home, "remote", "add", "origin", str(self.bare))
        git(self.home, "push", "-q", "-u", "origin", "main")
        self.proposals = self.bucket / "proposals"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


@pytest.fixture()
def claude_shim(tmp_path, monkeypatch, env):
    """PATH shim: records argv NUL-separated; runs $CLAUDE_SHIM_SCRIPT
    (a bash snippet, e.g. writing proposal files); exits $CLAUDE_SHIM_EXIT."""
    shims = tmp_path / "shims"
    shims.mkdir(exist_ok=True)
    log = tmp_path / "claude-argv.log"
    prompt_log = tmp_path / "claude-prompt.log"
    shim = shims / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'printf \'%s\\0\' "$@" > "{log}"\n'
        # the prompt rides STDIN (audit 2026-07-15: argv caps at 128 KiB)
        f'cat > "{prompt_log}" || true\n'
        'if [ -n "${CLAUDE_SHIM_SCRIPT-}" ]; then bash -c "$CLAUDE_SHIM_SCRIPT"; fi\n'
        'exit "${CLAUDE_SHIM_EXIT-0}"\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")
    return {"log": log, "prompt": prompt_log, "dir": shims}


@pytest.fixture()
def notify_shim(claude_shim, tmp_path):
    """PATH shim for `self-learn-notify` (10 U8): lives in the SAME
    shims dir `claude_shim` already put on PATH, so both binaries
    resolve together. Logs argv NUL-separated; `NOTIFY_SHIM_SCRIPT` (a
    bash snippet, e.g. `sleep N`) lets a test simulate the helper
    blocking on `notify-send --wait` without touching the real desktop —
    the worker must return long before it exits."""
    log = tmp_path / "notify-argv.log"
    shim = claude_shim["dir"] / "self-learn-notify"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'printf \'%s\\0\' "$@" > "{log}"\n'
        'if [ -n "${NOTIFY_SHIM_SCRIPT-}" ]; then bash -c "$NOTIFY_SHIM_SCRIPT"; fi\n'
        'exit 0\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return {"log": log, "dir": claude_shim["dir"]}


def _wait_for_file(path: Path, timeout: float = 5.0) -> None:
    """Poll for a file a DETACHED child writes asynchronously — the
    worker returns before the spawned helper necessarily has."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)


def _path_without_real_notify_helper(*leading_dirs: Path) -> str:
    """Build a PATH with `leading_dirs` first, then the inherited PATH
    with any directory that would resolve a REAL `self-learn-notify`
    filtered out — so a "helper absent" test stays true even on a
    machine (like this repo's own dev host) where self-learn-notify is
    actually deployed to `~/bin` (repo CLAUDE.md deploy surface)."""
    parts = [str(d) for d in leading_dirs]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and not (Path(entry) / "self-learn-notify").exists():
            parts.append(entry)
    return os.pathsep.join(parts)


def seed_pending(env, rid="lrn-0000aaaa", created_at=None):
    record = make_behavior(record_id=rid, created_at=created_at)
    create_record(env.home, record)
    commit_all(env.home, f"pending {rid}")
    return rid


def shim_writes(env, rid) -> str:
    path = env.proposals / f"{rid}.yaml"
    return (
        f"mkdir -p {env.proposals} && cat > {path} <<'YAML'\n{PROPOSAL_YAML}YAML"
    )


# ------------------------------------------------------------------- kick


def test_kick_spawns_one_window_and_second_is_absorbed(env, monkeypatch):
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK")
    spawned = []

    def fake_spawn(home, *, no_push=False):  # no_push: BLOCKER 3 signature
        spawned.append(home)
        return os.getpid()  # a live pid

    monkeypatch.setattr(worker, "_spawn_window", fake_spawn)
    assert worker.kick(env.home) == "spawned"
    assert worker.kick(env.home) == "absorbed-window"
    assert len(spawned) == 1
    assert (worker.cache_dir() / "worker.dirty").is_file()


def test_dead_pid_window_reopens(env, monkeypatch):
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK")
    worker.cache_dir().mkdir(parents=True, exist_ok=True)
    (worker.cache_dir() / "worker.window").write_text("999999999")
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: os.getpid()
    )
    assert worker.kick(env.home) == "spawned"


def test_autokick_disabled_is_noop(env):
    assert worker.kick(env.home) == "disabled"
    assert not (worker.cache_dir() / "worker.dirty").exists()


def test_teach_kicks_import_kicks(env, monkeypatch, capsys):
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK")
    kicked = []
    monkeypatch.setattr(
        worker,
        "kick",
        # no_push: the kick signature carries the invoking verb's
        # --no-push to the spawned worker (BLOCKER 3).
        lambda home, *, no_push=False: kicked.append((home, no_push)) or "spawned",
    )
    rc = cli.main(
        ["teach", "--skill", "s", "--type", "knowledge", "--fact", "A fact."]
    )
    assert rc == 0
    assert len(kicked) == 1
    # A plain teach never asked for --no-push, so the spawned worker is
    # free to publish (BLOCKER 3: no_push is opt-in, not the default).
    assert kicked[0][1] is False


def test_teach_route_success_does_not_kick(env, monkeypatch):
    seeded = seed_pending(env)  # ensures repo has ledger dirs
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK")
    kicked = []
    monkeypatch.setattr(
        worker,
        "kick",
        # no_push: the kick signature carries the invoking verb's
        # --no-push to the spawned worker (BLOCKER 3).
        lambda home, *, no_push=False: kicked.append((home, no_push)) or "spawned",
    )
    rc = cli.main(
        [
            "teach", "--skill", "s", "--type", "knowledge",
            "--fact", "Routed directly.", "--route", "--dest", "reference",
            "--no-push",
        ]
    )
    assert rc == 0
    assert kicked == []


# -------------------------------------------------------------------- run


def test_run_happy_path(env, claude_shim, monkeypatch):
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    result = worker.run(env.home)
    assert result.status == "ok"
    assert result.proposed == [rid]
    # proposal stamped by the CLI (model never emits record_sha)
    text = (env.proposals / f"{rid}.yaml").read_text(encoding="utf-8")
    assert "record_sha: sha256:" in text
    # last-run touched; events line appended with pinned schema
    assert (worker.cache_dir() / "worker.last-run").is_file()
    events = (
        (worker.cache_dir() / "events.jsonl").read_text(encoding="utf-8").splitlines()
    )
    line = json.loads(events[-1])
    assert line["event"] == "proposals"
    assert line["record_ids"] == [rid]
    assert line["aggregate"]["pending"] == 1
    assert line["aggregate"]["buckets"] == [{"bucket": "s", "pending": 1}]


def test_run_argv_pins(env, claude_shim, monkeypatch):
    """E-18 property (flag syntax adjusted at T13 per the pin's own
    instruction): read-only allowedTools, Bash/Edit explicitly
    disallowed, Write granted ONLY via the settings file's ledger
    proposals-scoped rules (doc 13: three)."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    worker.run(env.home)
    argv = claude_shim["log"].read_text(encoding="utf-8").split("\0")[:-1]
    allowed = argv[argv.index("--allowedTools") + 1]
    assert allowed == "Read,Grep,Glob"
    assert "Write" not in allowed and "Bash" not in allowed
    disallowed = argv[argv.index("--disallowedTools") + 1]
    assert "Bash" in disallowed and "Edit" in disallowed
    settings_path = argv[argv.index("--settings") + 1]
    rules = json.loads(Path(settings_path).read_text(encoding="utf-8"))[
        "permissions"
    ]["allow"]
    # live-verified rule family: Edit(...) governs Write; Write(...) rules
    # match nothing on the live CLI (T13-start check, 2026-07-15).
    # doc 13: three ledger-scoped proposals dirs, no host path reachable.
    assert rules == [
        f"Edit(/{env.home}/skills/**/proposals/**)",
        f"Edit(/{env.home}/projects/**/proposals/**)",
        f"Edit(/{env.home}/user/proposals/**)",
    ]
    for rule in rules:  # // prefix = filesystem-absolute in rule syntax
        assert rule.startswith("Edit(//")
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"
    # The prompt is NOT in argv (audit 2026-07-15: 128 KiB argv cap; a
    # full batch exceeds it) — it rides stdin.
    assert "-p" in argv
    assert not any("About to edit" in a for a in argv)
    prompt = claude_shim["prompt"].read_text(encoding="utf-8")
    assert "About to edit .storage while HA is running." in prompt  # record body
    assert "Authored prose stays put." in prompt  # target-canon excerpt


def test_run_idle_when_nothing_eligible(env, claude_shim):
    result = worker.run(env.home)
    assert result.status == "idle"
    assert (worker.cache_dir() / "worker.last-run").is_file()
    assert not claude_shim["log"].exists()  # claude never invoked


def test_run_invalid_output_deleted_and_run_fails(env, claude_shim, monkeypatch):
    rid = seed_pending(env)
    bad = env.proposals / f"{rid}.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {env.proposals} && printf 'destination: bogus\\n' > {bad}",
    )
    result = worker.run(env.home)
    assert result.status == "failed"
    assert not bad.exists()  # deleted (unattended policy)
    assert result.invalid_deleted == [f"{rid}.yaml"]
    assert not (worker.cache_dir() / "worker.last-run").exists()


def test_run_partial_success(env, claude_shim, monkeypatch):
    ra = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    rb = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    good = shim_writes(env, ra)
    bad = f"printf 'destination: bogus\\n' > {env.proposals}/{rb}.yaml"
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", f"{good}\n{bad}")
    result = worker.run(env.home)
    assert result.status == "ok"  # partial success succeeds (pinned)
    assert result.proposed == [ra]
    assert result.invalid_deleted == [f"{rb}.yaml"]
    assert (worker.cache_dir() / "worker.last-run").is_file()


def test_fresh_proposals_skipped_stale_reanalyzed(env, claude_shim, monkeypatch):
    """Content identity, never mtime: a fresh valid proposal keeps the
    record out of the batch; editing the record body re-analyzes."""
    rid = seed_pending(env)
    write_proposal(env.home, rid, proposal_dict())
    from self_learn.ledger_ops import stamp_proposal

    stamp_proposal(env.home, rid)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    result = worker.run(env.home)
    assert result.status == "idle"  # nothing eligible — fresh proposal

    # mtime churn alone must NOT re-analyze (git checkouts rewrite mtimes)
    rpath = env.bucket / "pending" / f"{rid}.md"
    os.utime(rpath, (time.time(), time.time()))
    assert worker.run(env.home).status == "idle"

    # a real body edit re-analyzes
    record = Record.from_path(rpath)
    record.set_body(record.body.replace("Stop the container", "Halt the container"))
    record.write(rpath)
    result = worker.run(env.home)
    assert result.status == "ok"
    assert result.proposed == [rid]


def test_deferred_records_skipped(env, claude_shim):
    rid = seed_pending(env)
    rpath = env.bucket / "pending" / f"{rid}.md"
    record = Record.from_path(rpath)
    record.set_status("deferred")
    record.set_deferred_until("2099-01-01")
    record.write(rpath)
    assert worker.run(env.home).status == "idle"


def test_orphan_proposal_swept(env, claude_shim, monkeypatch):
    rid = seed_pending(env)
    # a PRE-EXISTING orphan (its record resolved on another machine, say):
    # step-5's sweep owns it — step-4 validation only sees run-written files
    orphan = env.proposals / "lrn-99999999.yaml"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(PROPOSAL_YAML, encoding="utf-8")
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    result = worker.run(env.home)
    assert result.status == "ok"
    assert not orphan.exists()
    assert "lrn-99999999.yaml" in result.orphans_swept


def test_kick_mid_run_triggers_followon(env, claude_shim, monkeypatch):
    rid = seed_pending(env)
    # the shim re-marks dirty mid-run, as a landing kick would
    dirty = worker.cache_dir() / "worker.dirty"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT", f"{shim_writes(env, rid)}\ntouch {dirty}"
    )
    spawned = []
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: spawned.append(1) or 12345
    )
    result = worker.run(env.home)
    assert result.followon is True
    assert spawned == [1]


def test_run_never_execs_a_sync_script_from_the_ledger_home(env, claude_shim):
    """MINOR 10 (audit 2026-07-16): the sync-first step is GONE. It looked
    for `<home>/bin/claude-skills-sync` — which the ledger home will never
    contain, since doc 13 H-5 gives the ledger no watcher — so it logged
    "skipped" on every run forever. This replaces the old
    test_sync_first_runs_sandbox_script, which pinned the removed
    behavior: an executable at that path must now be IGNORED, not run
    (the ledger home is data; the worker never execs out of it)."""
    marker = env.home / "sync-ran"
    script = env.home / "bin" / "claude-skills-sync"
    script.parent.mkdir(exist_ok=True)
    script.write_text(f"#!/usr/bin/env bash\ntouch {marker}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    worker.run(env.home)

    assert not marker.exists()
    assert not hasattr(worker, "_sync_first")
    assert "sync-first" not in (worker.cache_dir() / "worker.log").read_text(
        encoding="utf-8"
    )


# ------------------------------------------------------------------ digest


def test_digest_contains_rejected_with_notes(env, claude_shim, monkeypatch):
    rid = seed_pending(env, "lrn-0000dddd")
    assert cli.main(["reject", rid, "--note", "one-off task instruction", "--no-push"]) == 0
    digest = worker._digest(env.home)
    assert rid in digest
    assert "one-off task instruction" in digest


# ------------------------------------------------- T14: template + escalation


def test_notification_template_verbatim():
    assert worker.render_notification(2, ["s", "project"], 7, 2) == (
        "self-learn: 2 new proposals for s, project. "
        "7 pending across 2 scopes — /self-learn:review"
    )
    assert worker.render_notification(1, ["s"], 1, 1) == (
        "self-learn: 1 new proposal for s. 1 pending across 1 scope — "
        "/self-learn:review"
    )


def test_notify_uses_helper_with_pinned_argv_and_matching_ids(
    env, claude_shim, notify_shim, monkeypatch
):
    """10 U8: the proposals notification's transport swaps to a detached
    spawn of `self-learn-notify`, pinned argv (10 §1) — `--line` carries
    the byte-unchanged `render_notification` template, `--ids` carries
    the SAME ids `append_event` already logged, comma-joined."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    worker.run(env.home)

    _wait_for_file(notify_shim["log"])
    argv = notify_shim["log"].read_text(encoding="utf-8").split("\0")[:-1]
    assert argv == [
        "--line",
        worker.render_notification(1, ["s"], 1, 1),
        "--ids",
        rid,
    ]

    events = [
        json.loads(ln)
        for ln in (worker.cache_dir() / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    line = events[-1]
    assert line["event"] == "proposals"
    assert line["record_ids"] == [rid]
    # byte-for-byte: the helper's --ids is the events line's record_ids,
    # comma-joined — never a second computation.
    assert argv[3] == ",".join(line["record_ids"])


def test_notify_helper_absent_falls_back_to_direct_notify_send(
    env, claude_shim, monkeypatch, tmp_path
):
    """Graceful degradation (headless/partial-deploy safety, 09 §5):
    `self-learn-notify` missing from PATH → the old M2 direct
    notify-send path is taken, no crash, logged one line."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))

    notify_send_log = tmp_path / "notify-send.log"
    shim = claude_shim["dir"] / "notify-send"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'printf \'%s\\0\' "$@" > "{notify_send_log}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    # self-learn-notify deliberately NOT added to claude_shim["dir"];
    # strip any other PATH entry that would resolve a real one too.
    monkeypatch.setenv("PATH", _path_without_real_notify_helper(claude_shim["dir"]))

    result = worker.run(env.home)
    assert result.status == "ok"  # no crash

    argv = notify_send_log.read_text(encoding="utf-8").split("\0")[:-1]
    assert argv == ["self-learn", worker.render_notification(1, ["s"], 1, 1)]

    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "self-learn-notify not on PATH" in log_text


def test_notify_never_blocks_worker_on_detached_helper(
    env, claude_shim, notify_shim, monkeypatch
):
    """The helper is spawned DETACHED — the worker must never wait on
    its exit (self-learn-notify itself blocks on `notify-send --wait`
    until acted on or expired; that latency must never become the
    worker's)."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    monkeypatch.setenv("NOTIFY_SHIM_SCRIPT", "sleep 5")

    start = time.monotonic()
    result = worker.run(env.home)
    elapsed = time.monotonic() - start

    assert result.status == "ok"
    assert elapsed < 2.0, f"worker.run blocked on the notify helper ({elapsed:.2f}s)"
    # confirm the helper really was invoked (not silently skipped) —
    # give the still-sleeping detached child time to have written argv.
    _wait_for_file(notify_shim["log"])
    assert notify_shim["log"].exists()


def test_escalation_fires_and_debounces(env, claude_shim):
    for i in range(5):
        seed_pending(env, f"lrn-0000000{i}")
    result = worker.run(env.home)  # 5 pending → threshold
    assert result.escalated is True
    events = [
        json.loads(ln)
        for ln in (worker.cache_dir() / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(e["event"] == "escalation" and e["record_ids"] == [] for e in events)
    # debounced: a second run within 24 h does not escalate again
    assert worker.run(env.home).escalated is False


def test_no_escalation_under_thresholds(env, claude_shim, monkeypatch):
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    assert worker.run(env.home).escalated is False


# --------------------------------------------- 11 §2.2 recurrence suspects


def test_recurrence_suspect_spooled_once(env, claude_shim, monkeypatch):
    routed = seed_pending(env, "lrn-0000aaaa")
    write_proposal(env.home, routed, proposal_dict())
    commit_all(env.home, "p")
    assert cli.main(["route", routed, "--no-push"]) == 0
    # a new capture with the SAME trigger text → title-token-overlap
    rid2 = seed_pending(env, "lrn-0000bbbb")
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid2))
    result = worker.run(env.home)
    assert result.suspects == 1
    events = telemetry.read_events(env.home)
    suspects = [e for e in events if e["kind"] == "recurrence-suspect"]
    assert len(suspects) == 1
    assert suspects[0]["record"] == routed
    assert suspects[0]["origin"] == rid2
    assert suspects[0]["basis"] == "title-token-overlap"
    # a second run does not re-emit the same pair
    result2 = worker.run(env.home)
    assert result2.suspects == 0


# ---------------------------------------------------- T15: fast status


def test_fast_status_shape_and_semantics(env, claude_shim, monkeypatch):
    rid = seed_pending(env)
    # one analyzed (fresh proposal), one deferred-hidden
    write_proposal(env.home, rid, proposal_dict())
    from self_learn.ledger_ops import stamp_proposal

    stamp_proposal(env.home, rid)
    rid2 = seed_pending(env, "lrn-0000bbbb")
    rpath = env.bucket / "pending" / f"{rid2}.md"
    record = Record.from_path(rpath)
    record.set_status("deferred")
    record.set_deferred_until("2099-01-01")
    record.write(rpath)

    payload = worker.fast_status(env.home)
    assert payload["total_pending"] == 1  # deferred hidden
    assert payload["unanalyzed_total"] == 0  # fresh proposal
    assert payload["worker_last_run"] is None
    assert payload["staleness_alarm"] is False  # no un-analyzed supply
    assert payload["escalate"] is False


def test_staleness_predicate_truth_table(env, monkeypatch):
    """Pinned predicate: (≥1 un-analyzed) AND (last-run >3d old OR
    missing). Five cases."""
    cache = worker.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    last_run = cache / "worker.last-run"

    # 1: no pending at all → never alarms
    assert worker.fast_status(env.home)["staleness_alarm"] is False

    rid = seed_pending(env)  # un-analyzed supply exists from here on

    # 2: un-analyzed + last-run MISSING → alarms (missing = infinitely old)
    assert worker.fast_status(env.home)["staleness_alarm"] is True

    # 3: un-analyzed + fresh last-run → quiet
    last_run.touch()
    assert worker.fast_status(env.home)["staleness_alarm"] is False

    # 4: un-analyzed + last-run 4 days old → alarms
    old = time.time() - 4 * 24 * 3600
    os.utime(last_run, (old, old))
    assert worker.fast_status(env.home)["staleness_alarm"] is True

    # 5: analyzed supply only + old last-run → quiet (no un-analyzed)
    write_proposal(env.home, rid, proposal_dict())
    from self_learn.ledger_ops import stamp_proposal

    stamp_proposal(env.home, rid)
    assert worker.fast_status(env.home)["staleness_alarm"] is False


def test_status_fast_cli_and_worker_last_run(env, capsys):
    rid = seed_pending(env)
    rc = cli.main(["status", "--fast"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_pending"] == 1
    assert payload["unanalyzed_total"] == 1
    assert payload["worker_last_run"] is None


def test_fast_status_budget(env):
    """<500 ms warm on a 100-record fixture (pinned budget)."""
    for i in range(100):
        create_record(env.home, make_behavior(record_id=f"lrn-{i:08x}"))
    worker.fast_status(env.home)  # warm
    elapsed = float("inf")
    for _ in range(2):  # min-of-two: resist load spikes, keep the budget real
        start = time.monotonic()
        payload = worker.fast_status(env.home)
        elapsed = min(elapsed, time.monotonic() - start)
    assert payload["total_pending"] >= 100
    assert elapsed < 0.5, f"fast status took {elapsed:.3f}s"


# ------------------------------------------- audit 2026-07-15 regressions


MERGE_NO_SHAS = """cluster_id: merge-0000cccc
records: [lrn-0000aaaa, lrn-0000bbbb]
suggested_survivor: lrn-0000aaaa
rationale: same lesson twice
model: claude-sonnet-5
analyzed_at: "2026-07-15T00:00:00Z"
"""


def test_batch_cap_leftovers_keep_dirty_and_followon(env, claude_shim, monkeypatch):
    """Pinned: leftovers keep worker.dirty set for a follow-on window.
    16 eligible → batch 15, 1 leftover, dirty kept, follow-on opened."""
    for i in range(16):
        create_record(
            env.home,
            make_behavior(
                record_id=f"lrn-000000{i:02x}",
                created_at=f"2026-07-{1 + i:02d}T00:00:00Z",
            ),
        )
    commit_all(env.home, "sixteen pending")
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, "lrn-00000000"))
    spawned = []
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: spawned.append(1) or 4242
    )
    result = worker.run(env.home)
    assert result.eligible == 15  # cap
    assert result.leftovers == 1
    assert (worker.cache_dir() / "worker.dirty").is_file()
    assert result.followon is True
    assert spawned == [1]


def test_merge_output_without_shas_survives_and_is_stamped(env, claude_shim, monkeypatch):
    """M2-21: the model must NOT emit record_shas — the CLI stamps them
    before validation. (The old validate-first order deleted every
    spec-compliant merge proposal.)"""
    seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    merge_path = env.proposals / "merge-0000cccc.yaml"
    script = (
        f"{shim_writes(env, 'lrn-0000aaaa')}\n"
        f"cat > {merge_path} <<'YAML'\n{MERGE_NO_SHAS}YAML"
    )
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result = worker.run(env.home)
    assert result.status == "ok"
    assert result.merge_proposed == ["merge-0000cccc"]
    text = merge_path.read_text(encoding="utf-8")
    assert text.count("sha256:") == 2  # CLI-stamped, one per member
    # merges count as proposals in the event (deep-link target exists)
    events = [
        json.loads(ln)
        for ln in (worker.cache_dir() / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    proposals_events = [e for e in events if e["event"] == "proposals"]
    assert proposals_events and "merge-0000cccc" in proposals_events[-1]["record_ids"]


def test_unexpected_artifacts_deleted_never_published(env, claude_shim, monkeypatch):
    rid = seed_pending(env)
    sub = env.proposals / "sub"
    junk = env.proposals / "notes.txt"
    script = (
        f"{shim_writes(env, rid)}\n"
        f"mkdir -p {sub} && printf 'x: 1\\n' > {sub}/sneaky.yaml\n"
        f"printf 'scratch\\n' > {junk}"
    )
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result = worker.run(env.home)
    assert result.status == "ok"
    assert not (sub / "sneaky.yaml").exists()
    assert not junk.exists()
    assert "sneaky.yaml" in result.invalid_deleted
    assert "notes.txt" in result.invalid_deleted


def test_secret_bearing_proposal_deleted(env, claude_shim, monkeypatch):
    rid = seed_pending(env)
    bad = PROPOSAL_YAML.replace(
        'rationale: "shim-written proposal"',
        'rationale: "use password = hunter2secret9 for this"',
    )
    path = env.proposals / f"{rid}.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {env.proposals} && cat > {path} <<'YAML'\n{bad}YAML",
    )
    result = worker.run(env.home)
    assert result.status == "failed"
    assert not path.exists()  # never reaches autosync


def test_run_releases_owned_sentinel_and_respects_other_holder(env, claude_shim):
    from self_learn import sentinel as sentinel_mod

    worker.run(env.home)
    assert not sentinel_mod.sentinel_path().exists()  # owned → released
    # another flow's live hold survives the run untouched
    hold = sentinel_mod.hold()
    assert hold.owned
    worker.run(env.home)
    assert sentinel_mod.sentinel_path().exists()
    hold.release()


def test_open_window_absorbed_race(env, monkeypatch):
    import fcntl as fcntl_mod

    worker.cache_dir().mkdir(parents=True, exist_ok=True)
    lock_path = worker.cache_dir() / "worker.spawn.lock"
    with open(lock_path, "w", encoding="utf-8") as holder:
        fcntl_mod.flock(holder.fileno(), fcntl_mod.LOCK_EX)
        monkeypatch.setattr(
            worker,
            "_spawn_window",
            lambda home, *, no_push=False: pytest.fail("must not spawn"),
        )
        assert worker._open_window(env.home) == "absorbed-race"


def test_digest_ordered_by_author_date_newest_first(env, claude_shim, monkeypatch):
    older = seed_pending(env, "lrn-0000aaaa")
    newer = seed_pending(env, "lrn-0000bbbb")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-07-01T00:00:00Z")
    assert cli.main(["reject", older, "--note", "older reject", "--no-push"]) == 0
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-07-10T00:00:00Z")
    assert cli.main(["reject", newer, "--note", "newer reject", "--no-push"]) == 0
    digest = worker._digest(env.home)
    assert digest.index(newer) < digest.index(older)


def test_run_reasserts_sentinel_deleted_mid_pass(env, claude_shim, monkeypatch):
    """Audit 2026-07-15 (miner round, M2): a concurrent short holder (the
    miner's landing phase) that created the sentinel can release-delete it
    while this worker run — a mere joiner — is mid-model-pass. The run
    must re-assert the hold before validation, or autosync's rebase can
    eat valid proposals mid-validation."""
    from self_learn import sentinel

    rid = seed_pending(env)
    sentinel_path = sentinel.sentinel_path()
    # the shim simulates the racing holder: it deletes the sentinel file
    # during the model pass, after writing its proposal
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        shim_writes(env, rid) + f'\nrm -f "{sentinel_path}"',
    )
    result = worker.run(env.home)
    assert result.status == "ok" and result.proposed == [rid]
    # the re-assert happened: a sentinel existed during validation and the
    # run's own release removed it at the end (owned)
    assert not sentinel_path.exists()
