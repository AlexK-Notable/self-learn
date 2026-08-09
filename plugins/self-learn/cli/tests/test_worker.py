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
from support import commit_all, git, make_behavior, make_env, make_home, proposal_dict

SKILL_MD = "# s skill\n\nAuthored prose stays put.\n"

# S-26: every proposal now needs the mandatory decision trace. This is a
# fixed, self-consistent SKILL-outcome trace for scope skill:s (the ONLY
# scope this file's shim-written proposals ever target — `seed_pending`
# always uses `make_behavior()`'s defaults). `{roster_sha}` is filled in
# by `_proposal_yaml` from the REAL `worker.skill_roster(env.home)` for
# the calling test's own env — a literal sha would drift the instant the
# roster's rendering format or this file's `make_env` skill seed changes.
PROPOSAL_YAML_TEMPLATE = """destination: skill-md
alternates: [reference]
rationale: "shim-written proposal"
already_canon: false
model: claude-sonnet-5
analyzed_at: "2026-07-15T00:00:00Z"
card:
  headline: "A test headline."
  impact: "Next time Claude does X it will Y."
  discuss: "Nothing contentious."
gates:
  g0:
    reject: {{answer: "no"}}
    defer: {{answer: "no"}}
    canon: {{answer: "no"}}
  t1:
    attempted: false
    field_shaped:
      answer: "no"
      evidence: "About to edit .storage while HA is running."
    separable: {{answer: null}}
    cost_bearing: {{answer: null}}
  t2:
    answer: "no"
    evidence: "About to edit .storage while HA is running."
    match_path: null
  t3:
    answer: "yes"
    owner: "s"
    scan_terms: null
    roster_sha: "{roster_sha}"
  t3a:
    depth_behind_rule: {{answer: "no", evidence: null}}
    fs: {{verdict: "SILENT", evidence: "About to edit .storage while HA is running."}}
  tn: {{answer: "no", terms: [], members: [], proposed_name: null}}
  t4: null
  e1: {{sightings: 1, post_demand_recurrence: false}}
  outcome: SKILL
flags: []
recommendation: route
"""


def _proposal_yaml(env) -> str:
    """The canned shim proposal text, its roster sha filled in from the
    REAL roster this test's own env composes (see the template's own
    docstring above)."""
    from self_learn.worker import skill_roster

    return PROPOSAL_YAML_TEMPLATE.format(roster_sha=skill_roster(env.home).sha)


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
    """PATH shim, MULTI-INVOCATION-OBSERVABLE (U-repair F5, §9-X7 — the
    pre-U-repair shim truncated with `>`, so a two-invocation run left
    only the SECOND call observable; a repair-round test built against
    it would silently exercise round 2 alone).

    Five capabilities (F5), all keyed off a per-invocation counter
    (``{tmp_path}/claude-invocation-count``, incremented once per call):

    1. **per-invocation argv capture** — appended (never truncated) to
       the legacy ``log`` path (the ~30 existing single-invocation tests
       keep reading it unchanged: for exactly one call, append-to-empty
       is byte-identical to truncate) AND to a per-call
       ``claude-calls/argv.<n>`` file, read via ``claude_shim["argv"](n)``.
    2. **per-invocation stdin capture** — same shape, legacy ``prompt``
       path (appended) plus ``claude-calls/prompt.<n>``, read via
       ``claude_shim["call_prompt"](n)``.
    3. **a per-invocation counter** — ``claude_shim["count"]()``.
    4. **per-invocation script** — ``CLAUDE_SHIM_SCRIPT_<n>``, falling
       back to the unnumbered ``CLAUDE_SHIM_SCRIPT`` when the numbered
       form is unset, so every existing single-invocation test (which
       only ever sets the unnumbered var) keeps working unchanged.
    5. **per-invocation exit code and sleep** — ``CLAUDE_SHIM_EXIT_<n>``
       (falling back to unnumbered ``CLAUDE_SHIM_EXIT``, default ``0``)
       and ``CLAUDE_SHIM_SLEEP_<n>`` (no unnumbered fallback — round 1
       never needs to sleep just because round 2 does)."""
    shims = tmp_path / "shims"
    shims.mkdir(exist_ok=True)
    counter = tmp_path / "claude-invocation-count"
    log = tmp_path / "claude-argv.log"
    prompt_log = tmp_path / "claude-prompt.log"
    calls_dir = tmp_path / "claude-calls"
    calls_dir.mkdir(exist_ok=True)
    shim = shims / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'CTR="{counter}"\n'
        'N=$(( $(cat "$CTR" 2>/dev/null || echo 0) + 1 ))\n'
        'echo "$N" > "$CTR"\n'
        f'printf \'%s\\0\' "$@" >> "{log}"\n'
        f'printf \'%s\\0\' "$@" >> "{calls_dir}/argv.$N"\n'
        # the prompt rides STDIN (audit 2026-07-15: argv caps at 128 KiB)
        f'cat > "{calls_dir}/prompt.$N" || true\n'
        f'cat "{calls_dir}/prompt.$N" >> "{prompt_log}" || true\n'
        'SCRIPT_VAR="CLAUDE_SHIM_SCRIPT_$N"\n'
        'SCRIPT="${!SCRIPT_VAR-}"\n'
        'if [ -z "$SCRIPT" ]; then SCRIPT="${CLAUDE_SHIM_SCRIPT-}"; fi\n'
        'if [ -n "$SCRIPT" ]; then bash -c "$SCRIPT"; fi\n'
        'SLEEP_VAR="CLAUDE_SHIM_SLEEP_$N"\n'
        'SLEEP="${!SLEEP_VAR-}"\n'
        'if [ -n "$SLEEP" ]; then sleep "$SLEEP"; fi\n'
        'EXIT_VAR="CLAUDE_SHIM_EXIT_$N"\n'
        'EXIT="${!EXIT_VAR-}"\n'
        'if [ -z "$EXIT" ]; then EXIT="${CLAUDE_SHIM_EXIT-0}"; fi\n'
        'exit "$EXIT"\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")

    def argv_for(n: int) -> list[str]:
        p = calls_dir / f"argv.{n}"
        return p.read_text(encoding="utf-8").split("\0")[:-1] if p.exists() else []

    def prompt_for(n: int) -> str:
        p = calls_dir / f"prompt.{n}"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def count() -> int:
        try:
            return int(counter.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return 0

    return {
        "log": log,
        "prompt": prompt_log,
        "dir": shims,
        "argv": argv_for,
        "call_prompt": prompt_for,
        "count": count,
    }


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
        f"mkdir -p {env.proposals} && cat > {path} <<'YAML'\n{_proposal_yaml(env)}YAML"
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
    # U-repair F1: --strict-mcp-config is on the argv, carries no value
    # of its own (build_argv appends it LAST, nothing after it), and no
    # --mcp-config accompanies it (the analyst needs no MCP server;
    # §3.11).
    assert "--strict-mcp-config" in argv
    assert argv[-1] == "--strict-mcp-config"
    assert "--mcp-config" not in argv


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
    orphan.write_text(_proposal_yaml(env), encoding="utf-8")
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
    bad = _proposal_yaml(env).replace(
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


# -------------------------------------- FW-31/FW-32 riders (Y-22/Y-23)


def test_prompt_template_carries_pointers_not_lint_rules():
    """Placement-invariant MUST (analyst-riders-spec §1/§8): the M2
    template may point at the doctrine's lint/contradiction subsections
    but must NEVER carry the rules themselves — else M1 inline and the
    pane silently stop linting with no test failing (the exact silent
    three-producer-break failure mode the spec calls out)."""
    tpl = worker._PROMPT_TEMPLATE
    assert "§9" in tpl  # pointer to the lint subsection
    assert "§10" in tpl  # pointer to the contradiction subsection
    for rule_text in (
        "trigger_recognizable",
        "why_present",
        "reasoning-pattern",
        "sharpening",
    ):
        assert rule_text not in tpl


def test_prompt_template_narrows_contradicts_to_destination_section():
    """Y-23: the M2-only contradicts line no longer invites a canon-wide
    scan — narrowed to the destination section already shown in the
    candidate-target excerpt (analyst-riders-spec §2)."""
    tpl = worker._PROMPT_TEMPLATE
    assert "existing canon" not in tpl
    assert "destination section" in tpl
    assert "contradicts" in tpl


def test_routing_doctrine_carries_the_lint_rules_and_kind_aware_clause():
    """The rules-in-doctrine placement is what makes lint three-producer
    (M1 inline + M2 + the pane all load this one file) — proven against
    the REAL shipped routing-doctrine.md, not a stub."""
    text = (worker.package_skill_refs() / "routing-doctrine.md").read_text(
        encoding="utf-8"
    )
    assert "trigger_recognizable" in text
    assert "why_present" in text
    # kind-aware non-punitive posture (pinned MUST)
    assert "reasoning-pattern" in text
    assert "reject-worthy" in text


def test_routing_doctrine_carries_the_bounded_contradiction_subsection():
    """Analyst-riders-spec §2/§7: the doctrine addition that first makes
    front-half contradiction detection three-producer."""
    text = (worker.package_skill_refs() / "routing-doctrine.md").read_text(
        encoding="utf-8"
    )
    assert "destination section" in text
    assert "G-5-gated" in text
    assert "canon-wide" in text


def test_canon_excerpt_unresolvable_skill_target_never_raises(tmp_path):
    """Degradation leg (analyst-riders-spec §4, Y-20 F5 posture): an
    unresolvable target reads as a sentinel string, never an exception —
    the analyst then has no section to check and (per doctrine) omits
    both `contradicts` and the `conflict` card, never guesses a target.
    `compose_batch_prompt` must still assemble around the sentinel without
    crashing the run."""
    from self_learn.ledger import discover_buckets

    from self_learn.ledger_ops import queue as _queue

    home = make_home(tmp_path)
    # Create while the host is still registered (creation itself is
    # validity-gated, H-3) — THEN break registration to simulate the
    # excerpt-time resolution failure the degradation leg covers.
    create_record(home, make_behavior(record_id="lrn-0000aaaa"))
    (home / "hosts.yaml").write_text("projects: []\n", encoding="utf-8")
    (bucket,) = [b for b in discover_buckets(home) if b.name == "s"]
    (entry,) = _queue(bucket)

    excerpt = worker._canon_excerpt(home, entry)
    assert "unresolvable" in excerpt

    prompt, _roster = worker.compose_batch_prompt(home, [entry])
    assert "unresolvable" in prompt


def test_canon_excerpt_finds_the_compiler_written_markers_in_a_fat_target(env):
    """U-marker (u-marker-excerpt-case-spec.md §3 criterion A): a fat
    project-scope target's compiled section must reach the excerpt. The
    section here is written by the REAL compiler (`compile_managed_text`)
    — the marker text is never typed in this test, only the imported
    compiler constants are used to assert on it (spec §2's import rule:
    `worker._canon_excerpt` must search for the markers the compiler
    actually writes, not a hand-typed legacy spelling)."""
    from self_learn.compilers import (
        BEGIN_MARKER,
        END_MARKER,
        compile_managed_text,
        entry_line,
    )
    from self_learn.ledger import discover_buckets
    from self_learn.ledger_ops import queue as _queue

    routed_record = make_behavior(record_id="lrn-0000c0de")
    routed_record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "claude-md", "by": "human"}
    )
    routed_record.set_status("routed")

    leading = "\n".join(f"authored line {i}" for i in range(250))
    trailing = "\n".join(f"trailing line {i}" for i in range(30))
    compiled = compile_managed_text(leading, [routed_record])
    full_text = compiled.text + trailing + "\n"
    (env.host / "CLAUDE.md").write_text(full_text, encoding="utf-8")

    lines = full_text.splitlines()
    begin_idx = next(i for i, ln in enumerate(lines) if BEGIN_MARKER in ln)
    end_idx = next(i for i, ln in enumerate(lines) if END_MARKER in ln)
    # A0 — fixture guard: without this, A would pass pre-fix whenever the
    # section happened to land inside the head-of-file truncation window.
    assert len(lines) >= 200
    assert begin_idx > 60

    pending = make_behavior(scope="project", record_id="lrn-0000feed")
    create_record(env.home, pending, project_path=env.host)
    (bucket,) = [b for b in discover_buckets(env.home) if b.scope == "project"]
    (entry,) = _queue(bucket)

    excerpt = worker._canon_excerpt(env.home, entry)
    excerpt_lines = excerpt.splitlines()

    assert BEGIN_MARKER in excerpt  # A1
    assert END_MARKER in excerpt  # A1
    assert entry_line(routed_record) in excerpt_lines  # A2 — payload, not frame
    lo, hi = max(0, begin_idx - 20), min(len(lines), end_idx + 21)
    assert excerpt_lines == lines[lo:hi]  # A3 — exact list equality
    # Measured shape (spec §3A): 43 lines, first "authored line 231",
    # last "trailing line 19".
    assert excerpt_lines == lines[231:274]


def test_canon_excerpt_case_variant_of_compiler_marker_does_not_match(env):
    """U-marker (u-marker-excerpt-case-spec.md §3 criterion B): a
    case-variant of the compiler's own marker must NOT match. Both
    needles are derived from the imported constants (case-swapped) — no
    marker spelling is typed in this build at all.

    This fixture is red pre-fix BECAUSE an uppercased begin marker
    contains the legacy needle (spec §1) as a substring, and likewise
    the uppercased end marker contains its counterpart, so
    unfixed code wrongly finds a window around line 150 instead of
    falling through to the head-of-file truncation. Do not case-fold
    this fixture away — it is the positive control that catches a
    case-folded "defensive" fix (`BEGIN_MARKER.lower() in ln.lower()`),
    which would match this fixture exactly the way the legacy needle
    did.

    FW-52 (2026-08-02): uppercasing BOTH markers means a build that
    case-folds only ONE needle (begin or end) survives this test too —
    it finds the folded one, misses the untouched one, and lands on the
    exact same truncation this test asserts. Closed by the two
    single-needle variants immediately below, added ALONGSIDE this one
    — this stays the only fixture red against the ORIGINAL (pre-U-marker)
    legacy-needle bug, so it remains the required positive control and
    must not be removed."""
    from self_learn.compilers import BEGIN_MARKER, END_MARKER
    from self_learn.ledger import discover_buckets
    from self_learn.ledger_ops import queue as _queue

    lines = [f"line {i}" for i in range(300)]
    lines[150] = BEGIN_MARKER.upper()
    lines[160] = END_MARKER.upper()
    (env.host / "CLAUDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    pending = make_behavior(scope="project", record_id="lrn-0000face")
    create_record(env.home, pending, project_path=env.host)
    (bucket,) = [b for b in discover_buckets(env.home) if b.scope == "project"]
    (entry,) = _queue(bucket)

    excerpt = worker._canon_excerpt(env.home, entry)
    # B1 — exact list equality against the head-of-file truncation.
    assert excerpt.splitlines() == [f"line {i}" for i in range(60)] + [
        "… (truncated)"
    ]


def test_canon_excerpt_begin_only_case_variant_does_not_match(env):
    """FW-52: the shipped criterion B above uppercases BOTH markers, so it
    cannot tell a fully case-sensitive extractor (correct) from one that
    case-folds only the BEGIN needle (`BEGIN_MARKER.lower() in
    ln.lower()` on begin, plain `END_MARKER in ln` on end) — that
    half-blind build finds begin via the fold, finds end normally (it is
    untouched, genuinely lowercase), and produces a real window instead
    of falling through `begin is None or end is None` to the truncation
    both fixtures assert. This fixture isolates the BEGIN needle: only
    line 150 is uppercased, line 160 keeps the real, untyped
    `END_MARKER`. Shipped (fully case-sensitive) code still finds `end`
    but not `begin`, so `begin is None` alone is enough to trip the same
    truncation branch — added ALONGSIDE the both-uppercased fixture, not
    instead of it (see that test's docstring: it is the only fixture red
    against the pre-U-marker legacy-needle bug, since an
    all-uppercase-vs-all-uppercase substring match is exactly what the
    legacy `"SELF-LEARN:BEGIN"`/`"SELF-LEARN:END"` needles would have hit
    on both lines here; a single uppercased needle plus one real,
    lowercase needle does NOT reproduce that failure, so this fixture is
    NOT red pre-fix — it targets only the half-case-fold class, a defect
    that postdates the original fix and that the shipped both-uppercased
    fixture cannot see)."""
    from self_learn.compilers import BEGIN_MARKER, END_MARKER
    from self_learn.ledger import discover_buckets
    from self_learn.ledger_ops import queue as _queue

    lines = [f"line {i}" for i in range(300)]
    lines[150] = BEGIN_MARKER.upper()
    lines[160] = END_MARKER  # real marker, untouched — the control leg
    (env.host / "CLAUDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    pending = make_behavior(scope="project", record_id="lrn-0000beef")
    create_record(env.home, pending, project_path=env.host)
    (bucket,) = [b for b in discover_buckets(env.home) if b.scope == "project"]
    (entry,) = _queue(bucket)

    excerpt = worker._canon_excerpt(env.home, entry)
    assert excerpt.splitlines() == [f"line {i}" for i in range(60)] + [
        "… (truncated)"
    ]


def test_canon_excerpt_end_only_case_variant_does_not_match(env):
    """FW-52, the END-needle twin of the test above: line 150 keeps the
    real, untyped `BEGIN_MARKER`; only line 160 (the END needle) is
    uppercased. A build that case-folds only the END check (plain
    `BEGIN_MARKER in ln` on begin, `END_MARKER.lower() in ln.lower()` on
    end) finds begin normally and end via the fold, and — like the
    begin-only variant above — produces a real window where shipped
    (fully case-sensitive) code correctly finds `end is None` and falls
    through to the same head-of-file truncation. Added alongside, never
    replacing, the both-uppercased fixture; not red pre-fix for the same
    reason as the begin-only variant (one real, lowercase needle here
    breaks the legacy all-uppercase substring match the original bug
    needed)."""
    from self_learn.compilers import BEGIN_MARKER, END_MARKER
    from self_learn.ledger import discover_buckets
    from self_learn.ledger_ops import queue as _queue

    lines = [f"line {i}" for i in range(300)]
    lines[150] = BEGIN_MARKER  # real marker, untouched — the control leg
    lines[160] = END_MARKER.upper()
    (env.host / "CLAUDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    pending = make_behavior(scope="project", record_id="lrn-0000e0e0")
    create_record(env.home, pending, project_path=env.host)
    (bucket,) = [b for b in discover_buckets(env.home) if b.scope == "project"]
    (entry,) = _queue(bucket)

    excerpt = worker._canon_excerpt(env.home, entry)
    assert excerpt.splitlines() == [f"line {i}" for i in range(60)] + [
        "… (truncated)"
    ]


def test_worker_prompt_assembly_carries_the_real_doctrine_lint_schema(
    env, claude_shim, monkeypatch
):
    """One-schema fixture (spec §8): the M2 worker's ACTUAL assembled
    prompt — built from the real shipped routing-doctrine.md via
    `compose_batch_prompt`, not a mock — carries the same `lint:` field names
    the doctrine teaches every producer (M1 inline included: it loads the
    identical file per `commands/review.md` step 2). No fork between
    what the doctrine teaches and what a producer's prompt actually
    carries."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    worker.run(env.home)
    prompt = claude_shim["prompt"].read_text(encoding="utf-8")
    assert "trigger_recognizable" in prompt
    assert "why_present" in prompt
    assert "§9" in prompt
    assert "§10" in prompt
