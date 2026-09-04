"""U-readref — the reference-shelf read instrument (spec §7, T1-T13).

Covers: the closed telemetry kind (T1), the hook script's shell-level
behavior via real subprocess invocation (T2), report.py aggregation over
hand-authored tracked events (T3), ids-only content discipline (T4),
zero-read visibility (T5), instrument-state distinguishability (T6),
install/selfcheck wiring (T7), path normalization through a symlink (T8),
the emit->aggregate round trip (T9), the hook's inner timeout (T10),
stdout silence (T11), flush_state visibility (T12), and zero enumerable
targets (T13).

Fixture path style follows test_notify_script.py / test_selftest_hooks.py:
the REAL hook script is exercised via subprocess with a PATH-shimmed FAKE
`self-learn` (a same-interpreter python shim -- avoids the ~100ms `uv run`
wrapper while still driving the REAL `self_learn.cli.main` dispatch, not a
recording stub), plus the real system `jq`/`timeout`/`bash`/`cat`.
"""

from __future__ import annotations

import ast
import json
import os
import stat
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from self_learn import cli, refread, report, telemetry
from self_learn.hosts import load_hosts
from self_learn.ledger_ops import bucket_dir_for_scope, ensure_project_meta
from self_learn.selfcheck import _check_hooks, claude_runtime_dir
from support import init_repo, make_env, make_knowledge

#: tests/ -> cli/ -> self-learn/ -> plugins/ (same convention as
#: test_notify_script.py's PLUGINS_ROOT).
PLUGINS_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = PLUGINS_ROOT.parent
HOOK_SCRIPT = PLUGINS_ROOT / "self-learn" / "hooks" / "self-learn-refread.sh"
INSTALL_SH = REPO_ROOT / "install.sh"
README_MD = PLUGINS_ROOT / "self-learn" / "README.md"

TODAY = date(2026, 8, 23)


# --------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    e.claude = claude
    return e


def _instrument(claude_dir: Path) -> None:
    """Wires `instrument_state` to `ok`: an executable script at the
    expected path, registered in a parseable settings.json."""
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script = hooks_dir / "self-learn-refread.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    settings = claude_dir / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {
                            "matcher": "Read",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "$HOME/.claude/hooks/self-learn-refread.sh",
                                    "timeout": 5,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def seed_reference_routed(
    env,
    *,
    scope,
    record_id,
    reference_file=None,
    status="routed",
    superseded_by=None,
    project_path=None,
):
    """A resolved reference-routed record. ``scope`` is ``"skill:<name>"``,
    ``"project"``, or ``"user"`` — the same bucket-dir resolution
    `bucket_dir_for_scope` uses in production, never a hand-rolled path."""
    if scope == "project":
        proj = project_path if project_path is not None else env.host
        bucket_dir = bucket_dir_for_scope(env.ledger, "project", project_path=proj)
        ensure_project_meta(bucket_dir, proj)
    elif scope == "user":
        bucket_dir = env.ledger / "user"
        bucket_dir.mkdir(parents=True, exist_ok=True)
    else:
        bucket_dir = bucket_dir_for_scope(env.ledger, scope)
    record = make_knowledge(scope=scope, record_id=record_id)
    routing = {"routed_at": "2026-07-15T00:00:00Z", "destination": "reference", "by": "human"}
    if reference_file is not None:
        routing["reference_file"] = reference_file
    record.set_routing(routing)
    record.set_status(status)
    if superseded_by is not None:
        record.set_superseded_by(superseded_by)
    resolved = bucket_dir / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record.write(resolved / f"{record.id}.md")
    return record, bucket_dir


def write_tracked_event(
    home: Path,
    *,
    ts: str,
    ref_target: str,
    scope: str,
    bucket: str,
    subagent: bool,
    session: str,
    actor: str = "testhost",
) -> None:
    """Hand-authors one `reference-read` line directly into the TRACKED
    plane (`<home>/telemetry/*.jsonl`), bypassing spool/flush — T3's
    events are hand-authored against keys the test itself wrote (T9 is
    the real emit->aggregate join)."""
    tdir = home / "telemetry"
    tdir.mkdir(parents=True, exist_ok=True)
    path = tdir / f"{ts[:7]}.{actor}.jsonl"
    event = {
        "ts": ts,
        "kind": "reference-read",
        "actor": actor,
        "schema_version": telemetry.SCHEMA_VERSION,
        "nonce": os.urandom(4).hex(),
        "ref_target": ref_target,
        "scope": scope,
        "bucket": bucket,
        "subagent": subagent,
        "session": session,
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def write_raw_line(home: Path, line: str, *, actor: str = "testhost", month: str = "2026-08") -> None:
    tdir = home / "telemetry"
    tdir.mkdir(parents=True, exist_ok=True)
    path = tdir / f"{month}.{actor}.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def days_ago_ts(n: int, *, today: date = TODAY) -> str:
    d = today - timedelta(days=n)
    return f"{d.isoformat()}T00:00:00Z"


def _write_self_learn_shim(bin_dir: Path) -> Path:
    """A fast, same-interpreter `self-learn` PATH shim: `sys.executable`
    is the venv this test itself runs under (uv run --project cli
    pytest), so `self_learn` and its deps are already importable there
    -- this drives the REAL `cli.main` dispatch without the ~100ms `uv
    run` wrapper cost."""
    shim = bin_dir / "self-learn"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "from self_learn.cli import main\n"
        "sys.exit(main(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return shim


def _minimal_bin_dir(tmp_path, name, *, jq=True, self_learn=True, timeout=True) -> Path:
    """A PATH directory built from scratch with only the named binaries
    symlinked in (plus `bash`/`cat`, which the hook script always needs to
    even start, and `sleep`, which a slow-CLI test double needs so its
    delay is real rather than an instant "command not found") -- gives
    exact per-test control over which of the three guarded binaries
    (§4.2-3) is absent."""
    import shutil

    bindir = tmp_path / f"bin-{name}"
    bindir.mkdir()
    for tool in ("bash", "cat", "sleep"):
        real = shutil.which(tool)
        assert real, f"{tool} not found on the host PATH"
        (bindir / tool).symlink_to(real)
    if jq:
        real = shutil.which("jq")
        assert real, "jq not found on the host PATH"
        (bindir / "jq").symlink_to(real)
    if timeout:
        real = shutil.which("timeout")
        assert real, "timeout not found on the host PATH"
        (bindir / "timeout").symlink_to(real)
    if self_learn:
        _write_self_learn_shim(bindir)
    return bindir


#: MAJOR 3 (code gate r1): T9.2's no-re-split guard, structural rather
#: than a spelling blocklist -- the original three-literal blocklist
#: (".partition(\":\")", "ref_target.split(", "key.split(\"/\"") was
#: evaded by writing the exact same defect as `key.split(":", 1)`, which
#: matches none of the three strings. Every method in the split family
#: is forbidden, however it is spelled.
_STRING_SPLIT_METHODS = {"split", "rsplit", "partition", "rpartition"}


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _split_family_calls(func_node: ast.AST) -> list[str]:
    """Every `.split`/`.rsplit`/`.partition`/`.rpartition` METHOD CALL
    anywhere inside `func_node`'s body -- structural, not a spelling
    blocklist. Catches `key.partition(":")` AND `key.split(":", 1)`
    (and any other spelling) alike, because it does not look at spelling
    at all: it looks at which METHOD is called."""
    hits: list[str] = []
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _STRING_SPLIT_METHODS
        ):
            hits.append(node.func.attr)
    return hits


def run_hook(payload: str, *, env_vars: dict, bin_dir: Path, timeout_s: float = 30):
    return subprocess.run(
        [str(HOOK_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        env={**env_vars, "PATH": str(bin_dir)},
        timeout=timeout_s,
    )


def _base_payload(file_path: str, *, session: str = "sess-0001", subagent: bool = False) -> dict:
    body = {
        "cwd": "/tmp/hookprobe",
        "duration_ms": 12,
        "effort": None,
        "hook_event_name": "PostToolUse",
        "permission_mode": "bypassPermissions",
        "prompt_id": "prompt-0001",
        "session_id": session,
        "tool_input": {"file_path": file_path},
        "tool_name": "Read",
        "tool_response": {
            "type": "text",
            "file": {
                "filePath": file_path,
                "content": "# reference target\n\nordinary body text\n",
                "numLines": 3,
                "startLine": 1,
                "totalLines": 3,
            },
        },
        "tool_use_id": "toolu_0001",
        "transcript_path": "/tmp/hookprobe/transcript.jsonl",
    }
    if subagent:
        body["agent_id"] = "agent-0001"
        body["agent_type"] = "general-purpose"
    return body


# ------------------------------------------------------------------- T1


class TestT1KindSchema:
    def test_t1_1_kind_registered(self):
        assert "reference-read" in telemetry.EVENT_KINDS

    def test_t1_2_schema_version_bumped(self):
        assert telemetry.SCHEMA_VERSION == 3

    def test_t1_3_not_a_note_kind(self):
        assert "reference-read" not in telemetry.NOTE_KINDS

    def test_t1_4_telemetry_note_refuses(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home"))
        rc = cli.main(["telemetry", "note", "reference-read"])
        assert rc != 0
        assert list(telemetry.spool_dir().glob("*.jsonl")) == []

    def test_t1_5_typo_kind_still_raises(self):
        with pytest.raises(telemetry.TelemetryError):
            telemetry.spool_event("reference-reads")

    def test_t1_6_dict_payload_value_raises(self):
        with pytest.raises(telemetry.TelemetryError):
            telemetry.spool_event("reference-read", ref_target={"a": 1})


# ------------------------------------------------------------------- T2


class TestT2EmissionFixture:
    def test_t2_1_reference_read_emits_exactly_one_event(self, env, tmp_path):
        skill_refs = (env.host / "plugins" / "s-plugin" / "skills" / "s" / "references")
        skill_refs.mkdir(parents=True)
        target = skill_refs / "LEARNINGS.md"
        target.write_text("# shelf\n", encoding="utf-8")
        payload = _base_payload(str(target))
        # positive control (spec's own T2.1 requirement): the payload
        # itself must actually name the reference path, or a fixture that
        # silently stopped matching would read as "correctly emitted
        # nothing" (the lrn-ea833a5b shape).
        assert str(target) in json.dumps(payload)

        bin_dir = _minimal_bin_dir(tmp_path, "t21")
        result = run_hook(
            json.dumps(payload),
            env_vars={
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": os.environ["XDG_CACHE_HOME"],
                "HOME": str(tmp_path),
            },
            bin_dir=bin_dir,
        )
        assert result.returncode == 0
        assert result.stdout == ""

        lines = [
            json.loads(line)
            for path in telemetry.spool_dir().glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(lines) == 1
        event = lines[0]
        assert event["ref_target"] == "skill:s/references/LEARNINGS.md"
        assert event["scope"] == "skill"
        assert event["bucket"] == "s"

    def test_t2_2_ordinary_source_file_emits_nothing(self, env, tmp_path):
        ordinary = tmp_path / "src" / "main.py"
        ordinary.parent.mkdir(parents=True)
        ordinary.write_text("print('hi')\n", encoding="utf-8")
        bin_dir = _minimal_bin_dir(tmp_path, "t22")
        result = run_hook(
            json.dumps(_base_payload(str(ordinary))),
            env_vars={
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": os.environ["XDG_CACHE_HOME"],
                "HOME": str(tmp_path),
            },
            bin_dir=bin_dir,
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert list(telemetry.spool_dir().glob("*.jsonl")) == []

    def test_t2_3_agent_id_present_means_subagent_true(self, env, tmp_path):
        skill_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        skill_refs.mkdir(parents=True)
        target = skill_refs / "LEARNINGS.md"
        bin_dir = _minimal_bin_dir(tmp_path, "t23")
        run_hook(
            json.dumps(_base_payload(str(target), subagent=True)),
            env_vars={
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": os.environ["XDG_CACHE_HOME"],
                "HOME": str(tmp_path),
            },
            bin_dir=bin_dir,
        )
        lines = [
            json.loads(line)
            for path in telemetry.spool_dir().glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(lines) == 1
        assert lines[0]["subagent"] is True

    def test_t2_4_no_agent_id_means_subagent_false(self, env, tmp_path):
        skill_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        skill_refs.mkdir(parents=True)
        target = skill_refs / "LEARNINGS.md"
        bin_dir = _minimal_bin_dir(tmp_path, "t24")
        run_hook(
            json.dumps(_base_payload(str(target), subagent=False)),
            env_vars={
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": os.environ["XDG_CACHE_HOME"],
                "HOME": str(tmp_path),
            },
            bin_dir=bin_dir,
        )
        lines = [
            json.loads(line)
            for path in telemetry.spool_dir().glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(lines) == 1
        assert lines[0]["subagent"] is False

    def test_t2_5a_jq_absent_self_learn_present(self, env, tmp_path):
        bin_dir = _minimal_bin_dir(tmp_path, "t25a", jq=False)
        result = run_hook(
            json.dumps(_base_payload(str(tmp_path / "x" / "references" / "y.md"))),
            env_vars={"SELF_LEARN_HOME": str(env.ledger), "HOME": str(tmp_path)},
            bin_dir=bin_dir,
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert list(telemetry.spool_dir().glob("*.jsonl")) == []

    def test_t2_5b_self_learn_absent_jq_present(self, env, tmp_path):
        bin_dir = _minimal_bin_dir(tmp_path, "t25b", self_learn=False)
        result = run_hook(
            json.dumps(_base_payload(str(tmp_path / "x" / "references" / "y.md"))),
            env_vars={"SELF_LEARN_HOME": str(env.ledger), "HOME": str(tmp_path)},
            bin_dir=bin_dir,
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert list(telemetry.spool_dir().glob("*.jsonl")) == []

    def test_t2_5c_timeout_absent_jq_and_self_learn_present(self, env, tmp_path):
        bin_dir = _minimal_bin_dir(tmp_path, "t25c", timeout=False)
        result = run_hook(
            json.dumps(_base_payload(str(tmp_path / "x" / "references" / "y.md"))),
            env_vars={"SELF_LEARN_HOME": str(env.ledger), "HOME": str(tmp_path)},
            bin_dir=bin_dir,
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert list(telemetry.spool_dir().glob("*.jsonl")) == []

    def test_t2_6_no_registered_host_emits_nothing(self, tmp_path):
        # a bare ledger with NO hosts.yaml at all
        home = tmp_path / "bare-home"
        for sub in ("skills", "projects", "user", "telemetry"):
            (home / sub).mkdir(parents=True)
        init_repo(home)
        target = tmp_path / "somewhere" / "references" / "y.md"
        target.parent.mkdir(parents=True)
        bin_dir = _minimal_bin_dir(tmp_path, "t26")
        result = run_hook(
            json.dumps(_base_payload(str(target))),
            env_vars={
                "SELF_LEARN_HOME": str(home),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-t26"),
                "HOME": str(tmp_path),
            },
            bin_dir=bin_dir,
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert list(telemetry.spool_dir().glob("*.jsonl")) == []

    def test_t2_7_no_absolute_path_in_emitted_line(self, env, tmp_path):
        skill_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        skill_refs.mkdir(parents=True)
        target = skill_refs / "LEARNINGS.md"
        bin_dir = _minimal_bin_dir(tmp_path, "t27")
        run_hook(
            json.dumps(_base_payload(str(target))),
            env_vars={
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": os.environ["XDG_CACHE_HOME"],
                "HOME": str(tmp_path),
            },
            bin_dir=bin_dir,
        )
        raw = "".join(
            path.read_text(encoding="utf-8") for path in telemetry.spool_dir().glob("*.jsonl")
        )
        assert str(target) not in raw
        assert str(tmp_path) not in raw


# ------------------------------------------------------------------- T3


class TestT3Aggregation:
    def test_t3_1_sessions_vs_raw_events(self, env):
        _instrument(env.claude)
        record, _ = seed_reference_routed(env, scope="skill:s", record_id="lrn-1000aaaa")
        key = "skill:s/references/LEARNINGS.md"
        for i, sess in enumerate(("sess-a", "sess-a", "sess-b")):
            write_tracked_event(
                env.ledger,
                ts=days_ago_ts(1),
                ref_target=key,
                scope="skill",
                bucket="s",
                subagent=False,
                session=sess,
            )
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == key)
        assert row["reads_30d"] == 3
        assert row["read_sessions_30d"] == 2

    def test_t3_2_window_boundary(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-1000aaab")
        key = "skill:s/references/LEARNINGS.md"
        write_tracked_event(
            env.ledger, ts=days_ago_ts(30), ref_target=key, scope="skill",
            bucket="s", subagent=False, session="sess-a",
        )
        write_tracked_event(
            env.ledger, ts=days_ago_ts(31), ref_target=key, scope="skill",
            bucket="s", subagent=False, session="sess-b",
        )
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == key)
        assert row["reads_30d"] == 1
        assert row["reads_all_time"] == 2

    def test_t3_3_per_target_rows_and_total(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-1000aaac")
        key = "skill:s/references/LEARNINGS.md"
        write_tracked_event(
            env.ledger, ts=days_ago_ts(1), ref_target=key, scope="skill",
            bucket="s", subagent=False, session="sess-a",
        )
        # a second target reached only via events (T3.7-adjacent, no live record)
        write_tracked_event(
            env.ledger, ts=days_ago_ts(1), ref_target="project:deadbeef/references/LEARNINGS.md",
            scope="project", bucket="deadbeef", subagent=False, session="sess-c",
        )
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert len(rs["targets"]) == 2
        assert rs["reads_30d_total"] == 2

    def test_t3_4_subagent_reads(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-1000aaad")
        key = "skill:s/references/LEARNINGS.md"
        for subagent in (True, True, False, False):
            write_tracked_event(
                env.ledger, ts=days_ago_ts(1), ref_target=key, scope="skill",
                bucket="s", subagent=subagent, session="sess-a",
            )
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == key)
        assert row["subagent_reads_30d"] == 2

    def test_t3_5_cold_is_not_unread(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-1000aaae")
        key = "skill:s/references/LEARNINGS.md"
        write_tracked_event(
            env.ledger, ts=days_ago_ts(60), ref_target=key, scope="skill",
            bucket="s", subagent=False, session="sess-a",
        )
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == key)
        assert row["zero_read"] is False
        assert row["reads_30d"] == 0
        assert row["last_read"] is not None

    def test_t3_6_malformed_line_skipped_not_crashed(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-1000aaaf")
        write_raw_line(env.ledger, json.dumps({"ts": days_ago_ts(1), "kind": "reference-read"}))
        facts = report.gather(env.ledger, today=TODAY)  # must not raise
        assert "reference_shelf" in facts

    def test_t3_7_events_but_no_live_record(self, env):
        _instrument(env.claude)
        key = "skill:s/references/LEARNINGS.md"
        write_tracked_event(
            env.ledger, ts=days_ago_ts(1), ref_target=key, scope="skill",
            bucket="s", subagent=False, session="sess-a",
        )
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == key)
        assert row["records"] == 0

    def test_t3_8_observation_start_is_the_earliest(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-1000aaa0")
        key = "skill:s/references/LEARNINGS.md"
        write_tracked_event(
            env.ledger, ts=days_ago_ts(12), ref_target=key, scope="skill",
            bucket="s", subagent=False, session="sess-a",
        )
        write_tracked_event(
            env.ledger, ts=days_ago_ts(40), ref_target=key, scope="skill",
            bucket="s", subagent=False, session="sess-b",
        )
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert rs["observation_start"] == days_ago_ts(40)

    def test_t3_8_observation_start_null_with_no_events(self, env):
        _instrument(env.claude)
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert rs["observation_start"] is None


# ------------------------------------------------------------------- T4


class TestT4IdsOnlyScan:
    def _run(self, env, tmp_path, target, *, session="sess-canary"):
        canary = f"CANARY-{os.urandom(8).hex()}"
        secret_literal = "sk-live-abcdefghijklmnopqrstuvwxyz012345"
        payload = _base_payload(str(target), session=session)
        payload["tool_response"]["file"]["content"] = (
            f"{canary}\nBearer {secret_literal}\n"
        )
        raw = json.dumps(payload)
        # T4.0 positive control
        assert canary in raw
        bin_dir = _minimal_bin_dir(tmp_path, f"t4-{session}")
        run_hook(
            raw,
            env_vars={
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": os.environ["XDG_CACHE_HOME"],
                "HOME": str(tmp_path),
            },
            bin_dir=bin_dir,
        )
        lines = [
            json.loads(line)
            for path in telemetry.spool_dir().glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        raw_spooled = "".join(
            path.read_text(encoding="utf-8") for path in telemetry.spool_dir().glob("*.jsonl")
        )
        return canary, secret_literal, lines, raw_spooled

    def test_t4_skill_scope_no_content_leakage(self, env, tmp_path):
        skill_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        skill_refs.mkdir(parents=True)
        target = skill_refs / "LEARNINGS.md"
        canary, secret, lines, raw = self._run(env, tmp_path, target)

        assert len(lines) == 1
        event = lines[0]
        # T4.1
        assert canary not in raw
        # T4.2
        assert secret not in raw
        assert "/home/" not in raw
        assert str(target) not in raw
        # T4.3 — exact key set
        assert set(event.keys()) == {
            "ts", "kind", "actor", "schema_version", "nonce",
            "ref_target", "scope", "bucket", "subagent", "session",
        }
        # T4.4
        assert "agent_type" not in event
        # T4.5 — source-level: no EXECUTABLE line references tool_response
        # (comments MAY discuss the guarantee in prose; what must never
        # happen is the script actually reading/extracting the field).
        code_lines = [
            line
            for line in HOOK_SCRIPT.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("#")
        ]
        assert not any("tool_response" in line for line in code_lines)

    def test_t4_6_project_scope_digest_only(self, env, tmp_path):
        # T4.6.0: a REAL mangled project slug containing a "/home/"-shaped
        # segment (portable across hosts — the hazard class, not this
        # machine's literal $HOME).
        project_path = tmp_path / "home" / "testuser" / "proj"
        project_path.mkdir(parents=True)
        init_repo(project_path)
        (project_path / "CLAUDE.md").write_text("# proj\n", encoding="utf-8")

        # register it as an ADDITIONAL project host (append to hosts.yaml)
        hosts = load_hosts(env.ledger)
        hosts_yaml = env.ledger / "hosts.yaml"
        hosts_yaml.write_text(
            f"skills_root: {hosts.skills_root}\n"
            f"projects:\n  - path: {env.host}\n  - path: {project_path}\n",
            encoding="utf-8",
        )

        resolved_str = str(project_path.resolve())
        import hashlib

        digest = hashlib.sha256(resolved_str.encode("utf-8")).hexdigest()[:8]
        readable = resolved_str.replace("/", "-")
        slug = f"{readable}-{digest}"

        bucket_dir = bucket_dir_for_scope(env.ledger, "project", project_path=project_path)
        ensure_project_meta(bucket_dir, project_path)
        # positive control: the ledger's own bucket dir name IS the
        # mangled, home-containing slug (a pre-existing fact this unit
        # must not leak into telemetry).
        assert bucket_dir.name == slug
        assert "-home-" in slug

        refs_dir = project_path / "references"
        refs_dir.mkdir(parents=True)
        target = refs_dir / "LEARNINGS.md"

        canary, secret, lines, raw = self._run(env, tmp_path, target, session="sess-t46")

        assert readable not in raw
        assert "-home-" not in raw
        assert str(project_path) not in raw
        assert resolved_str.replace("/", "-") not in raw

        assert len(lines) == 1
        event = lines[0]
        assert event["bucket"] == digest
        assert event["ref_target"] == f"project:{digest}/references/LEARNINGS.md"
        import re

        assert re.fullmatch(r"[0-9a-f]{8}", event["bucket"])

        # T4.6.4 — the round trip at project scope
        seed_reference_routed(
            env, scope="project", record_id="lrn-2000aaaa", project_path=project_path
        )
        _instrument(env.claude)
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == event["ref_target"])
        assert row["ref_target"] == event["ref_target"]


# ------------------------------------------------------------------- T5


class TestT5ZeroReadVisibility:
    def test_t5_1_zero_read_row_present_and_named(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-3000aaaa")
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == "skill:s/references/LEARNINGS.md")
        assert row["reads_all_time"] == 0
        assert row["zero_read"] is True
        assert rs["targets_zero_read"] == 1
        assert rs["records_on_zero_read_targets"] == 1

    def test_t5_2_render_text_names_target_and_record_count(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-3000aaab")
        facts = report.gather(env.ledger, today=TODAY)
        text = report.render_text(facts)
        assert "skill:s/references/LEARNINGS.md" in text
        assert "1 record" in text

    def test_t5_3_zero_read_row_ordered_first(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-3000aaac", reference_file="A.md")
        seed_reference_routed(env, scope="skill:s", record_id="lrn-3000aaad", reference_file="B.md")
        write_tracked_event(
            env.ledger, ts=days_ago_ts(1),
            ref_target="skill:s/references/A.md", scope="skill", bucket="s",
            subagent=False, session="sess-a",
        )
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert rs["targets"][0]["zero_read"] is True
        assert rs["targets"][0]["ref_target"] == "skill:s/references/B.md"

    def test_t5_4_records_count_on_zero_read_target(self, env):
        _instrument(env.claude)
        for i in range(14):
            seed_reference_routed(env, scope="skill:s", record_id=f"lrn-30{i:06d}")
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert rs["records_on_zero_read_targets"] == 14

    def test_t5_5_project_scope_render_names_slug_beside_digest(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="project", record_id="lrn-3000aaae")
        facts = report.gather(env.ledger, today=TODAY)
        rs = facts["reference_shelf"]
        row = next(r for r in rs["targets"] if r["scope"] == "project")
        assert row["bucket_readable"] is not None
        text = report.render_text(facts)
        assert row["bucket"] in text
        assert row["bucket_readable"] in text

    def test_t5_6_event_only_project_row_recovers_slug_from_bucket_dir(
        self, env, tmp_path
    ):
        """NIT 4 (code gate r1): Amendment B binds EVERY project-scope
        row, not only ones reached through a live record — the slug is
        RECOVERABLE from the ledger's own bucket dir name (it ends in
        `-<digest>`), not reversed from the digest."""
        import hashlib

        _instrument(env.claude)
        project_path = tmp_path / "some-other-project"
        project_path.mkdir()
        init_repo(project_path)
        bucket_dir = bucket_dir_for_scope(
            env.ledger, "project", project_path=project_path
        )
        ensure_project_meta(bucket_dir, project_path)

        digest = hashlib.sha256(
            str(project_path.resolve()).encode("utf-8")
        ).hexdigest()[:8]
        key = f"project:{digest}/references/LEARNINGS.md"
        write_tracked_event(
            env.ledger, ts=days_ago_ts(1), ref_target=key, scope="project",
            bucket=digest, subagent=False, session="sess-t56",
        )

        facts = report.gather(env.ledger, today=TODAY)
        rs = facts["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == key)
        assert row["records"] == 0  # reached only via the event, no live record
        assert row["bucket_readable"] == bucket_dir.name

        text = report.render_text(facts)
        assert bucket_dir.name in text

    def test_t5_7_genuinely_unresolvable_project_slug_renders_absent_marker(
        self, env
    ):
        """NIT 4 (code gate r1): when the digest matches no bucket dir on
        disk (the bucket has since been pruned/rebound), that is a real,
        distinct case — rendered as an explicit ABSENT marker, never a
        silent omission of the parenthetical."""
        _instrument(env.claude)
        key = "project:deadbeef/references/LEARNINGS.md"
        write_tracked_event(
            env.ledger, ts=days_ago_ts(1), ref_target=key, scope="project",
            bucket="deadbeef", subagent=False, session="sess-t57",
        )
        facts = report.gather(env.ledger, today=TODAY)
        rs = facts["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == key)
        assert row["bucket_readable"] is None

        text = report.render_text(facts)
        assert "slug: ABSENT" in text


# ------------------------------------------------------------------- T6


class TestT6InstrumentState:
    def test_t6_1_script_missing(self, env):
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert rs["instrumented"] is False
        assert rs["instrument_state"] == "script-missing"

    def test_t6_2_not_registered(self, env):
        (env.claude / "hooks").mkdir(parents=True, exist_ok=True)
        script = env.claude / "hooks" / "self-learn-refread.sh"
        script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert rs["instrument_state"] == "not-registered"

    def test_t6_3_settings_unparseable(self, env):
        (env.claude / "hooks").mkdir(parents=True, exist_ok=True)
        script = env.claude / "hooks" / "self-learn-refread.sh"
        script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        (env.claude / "settings.json").write_text("{not valid json", encoding="utf-8")
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]  # must not raise
        assert rs["instrument_state"] == "settings-unparseable"

    def test_t6_4_uninstrumented_fields_are_null(self, env):
        seed_reference_routed(env, scope="skill:s", record_id="lrn-4000aaaa")
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        row = rs["targets"][0]
        for field in (
            "reads_all_time", "reads_30d", "read_sessions_30d",
            "subagent_reads_30d", "last_read", "zero_read",
        ):
            assert row[field] is None
        assert rs["reads_30d_total"] is None
        assert rs["targets_zero_read"] is None
        assert rs["records_on_zero_read_targets"] is None

    def test_t6_5_render_text_says_absent_not_zero(self, env):
        seed_reference_routed(env, scope="skill:s", record_id="lrn-4000aaab")
        facts = report.gather(env.ledger, today=TODAY)
        text = report.render_text(facts)
        assert "ABSENT" in text
        import re

        assert not re.search(r"\breads?[:\s].{0,12}\b0\b", text)

    def test_t6_6_instrumented_and_zero_read_coexist(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-4000aaac")
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert rs["instrumented"] is True
        assert rs["targets"][0]["zero_read"] is True

    def test_t6_7_all_four_states_reachable(self, env, tmp_path):
        observed = set()

        def _setup_script_missing(c):
            pass

        def _setup_not_registered(c):
            (c / "hooks").mkdir(parents=True, exist_ok=True)
            script = c / "hooks" / "self-learn-refread.sh"
            script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)

        def _setup_settings_unparseable(c):
            _setup_not_registered(c)
            (c / "settings.json").write_text("{broken", encoding="utf-8")

        scenarios = {
            "script-missing": _setup_script_missing,
            "not-registered": _setup_not_registered,
            "settings-unparseable": _setup_settings_unparseable,
            "ok": _instrument,
        }
        for scenario, setup in scenarios.items():
            cdir = tmp_path / f"claude-{scenario}"
            cdir.mkdir()
            setup(cdir)
            observed.add(_instrument_state_for(env.ledger, cdir))

        assert observed == {"ok", "script-missing", "not-registered", "settings-unparseable"}


def _instrument_state_for(home: Path, claude_dir: Path) -> str:
    """Drive `report._instrument_state` against an explicit claude_dir by
    way of `SELF_LEARN_CLAUDE_DIR` (the only knob `claude_runtime_dir`
    reads) — a plain monkeypatch-free helper since this runs outside a
    per-test `monkeypatch` fixture's scope."""
    old = os.environ.get("SELF_LEARN_CLAUDE_DIR")
    os.environ["SELF_LEARN_CLAUDE_DIR"] = str(claude_dir)
    try:
        return report._instrument_state(home)
    finally:
        if old is None:
            os.environ.pop("SELF_LEARN_CLAUDE_DIR", None)
        else:
            os.environ["SELF_LEARN_CLAUDE_DIR"] = old


# ------------------------------------------------------------------- T7


class TestT7InstallAndSelfcheck:
    def test_t7_1_install_sh_links_the_hook(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "hooks/self-learn-refread.sh" in text
        assert "self-learn-refread.sh" in text

    def test_t7_2_script_executable_and_bash_n_clean(self):
        assert os.access(HOOK_SCRIPT, os.X_OK)
        result = subprocess.run(
            ["bash", "-n", str(HOOK_SCRIPT)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    def test_t7_3_dangling_symlink_flagged_by_selftest_hooks(self, env):
        # a settings.json registration naming self-learn-refread.sh with
        # NO corresponding ~/.claude/hooks symlink.
        (env.claude / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PostToolUse": [
                            {
                                "matcher": "Read",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "$HOME/.claude/hooks/self-learn-refread.sh",
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        ok, reason = _check_hooks(env.ledger, claude_runtime_dir())
        assert not ok
        assert "self-learn-refread.sh" in reason
        assert "missing" in reason or "dangling" in reason

    def test_t7_4_readme_carries_registration_snippet_with_timeout(self):
        text = README_MD.read_text(encoding="utf-8")
        assert "self-learn-refread.sh" in text
        assert '"timeout": 5' in text
        assert "PostToolUse" in text


# ------------------------------------------------------------------- T8


class TestT8PathNormalization:
    def test_t8_0_positive_control_symlink_differs_and_both_exist(self, env, tmp_path):
        real_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        real_refs.mkdir(parents=True)
        (real_refs / "LEARNINGS.md").write_text("x", encoding="utf-8")

        alt_claude = tmp_path / "alt-claude-skills"
        alt_claude.mkdir()
        symlinked_skill = alt_claude / "s"
        symlinked_skill.symlink_to(env.host / "plugins" / "s-plugin" / "skills" / "s")
        symlinked_path = symlinked_skill / "references" / "LEARNINGS.md"
        real_path = real_refs / "LEARNINGS.md"

        assert str(symlinked_path) != str(real_path)
        assert symlinked_path.exists()
        assert real_path.exists()
        assert symlinked_path.resolve() == real_path.resolve()

    def test_t8_1_symlinked_path_resolves_to_the_real_key(self, env, tmp_path):
        real_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        real_refs.mkdir(parents=True)
        (real_refs / "LEARNINGS.md").write_text("x", encoding="utf-8")

        alt_claude = tmp_path / "alt-claude-skills"
        alt_claude.mkdir()
        symlinked_skill = alt_claude / "s"
        symlinked_skill.symlink_to(env.host / "plugins" / "s-plugin" / "skills" / "s")
        symlinked_path = symlinked_skill / "references" / "LEARNINGS.md"

        target = refread.resolve_ref_target(env.ledger, symlinked_path)
        assert target is not None
        assert target.key == "skill:s/references/LEARNINGS.md"

    def test_t8_2_real_path_yields_the_same_key(self, env):
        real_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        real_refs.mkdir(parents=True)
        real_path = real_refs / "LEARNINGS.md"
        real_path.write_text("x", encoding="utf-8")
        target = refread.resolve_ref_target(env.ledger, real_path)
        assert target is not None
        assert target.key == "skill:s/references/LEARNINGS.md"

    def test_t8_3_dotdot_and_trailing_slash_normalize_the_same(self, env):
        real_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        real_refs.mkdir(parents=True)
        (real_refs / "LEARNINGS.md").write_text("x", encoding="utf-8")

        via_dotdot = real_refs / ".." / "references" / "LEARNINGS.md"
        via_trailing = str(real_refs) + "/./LEARNINGS.md"

        t1 = refread.resolve_ref_target(env.ledger, via_dotdot)
        t2 = refread.resolve_ref_target(env.ledger, via_trailing)
        assert t1 is not None and t2 is not None
        assert t1.key == t2.key == "skill:s/references/LEARNINGS.md"

    def test_t8_4_candidate_side_symlinked_skills_root(self, tmp_path):
        """MAJOR 2 (code gate r1): T8.0-T8.3 all vary the READ path;
        none varies the CANDIDATE path (refread.py's own
        `(skill_dir / "references").resolve()`). A skills_root reached
        through a symlink exercises exactly that half of §4.1.1's
        normalization requirement -- the mutation this test is required
        to kill drops `.resolve()` from the CANDIDATE side specifically,
        which T8.0-T8.3 cannot see (their read path is already resolved
        or is the real path outright)."""
        real_root = tmp_path / "real-skills-root"
        real_refs_dir = real_root / "plugins" / "s-plugin" / "skills" / "s" / "references"
        real_refs_dir.mkdir(parents=True)
        target = real_refs_dir / "LEARNINGS.md"
        target.write_text("x", encoding="utf-8")

        sym_root = tmp_path / "sym-skills-root"
        sym_root.symlink_to(real_root)

        home = tmp_path / "ledger-t84"
        for sub in ("skills", "projects", "user", "telemetry"):
            (home / sub).mkdir(parents=True)
        init_repo(home)
        (home / "hosts.yaml").write_text(
            f"skills_root: {sym_root}\nprojects: []\n", encoding="utf-8"
        )

        # positive control: the CANDIDATE path (built by globbing the
        # symlinked skills_root, before `.resolve()`) is a DIFFERENT
        # STRING from the real references dir, and both exist / name the
        # same file -- the fixture actually carries the hazard.
        unresolved_candidate = (
            sym_root / "plugins" / "s-plugin" / "skills" / "s" / "references"
        )
        assert str(unresolved_candidate) != str(real_refs_dir)
        assert unresolved_candidate.resolve() == real_refs_dir.resolve()
        assert target.exists()

        target_result = refread.resolve_ref_target(home, target)
        assert target_result is not None
        assert target_result.key == "skill:s/references/LEARNINGS.md"


# ------------------------------------------------------------------- T9


class TestT9RoundTrip:
    def test_t9_1_emit_and_aggregate_agree(self, env):
        from self_learn.selfcheck import _reference_target_for

        _instrument(env.claude)
        record, bucket_dir = seed_reference_routed(env, scope="skill:s", record_id="lrn-5000aaaa")
        from self_learn.ledger import Bucket

        bucket = Bucket(path=bucket_dir, scope="skill", name="s")
        abs_target = _reference_target_for(env.ledger, bucket, record)
        assert abs_target is not None
        abs_target.parent.mkdir(parents=True, exist_ok=True)
        abs_target.write_text("# shelf\n", encoding="utf-8")

        emitted = refread.emit_reference_read(
            env.ledger, abs_path=str(abs_target), session="sess-t9", subagent=False
        )
        assert emitted is not None
        # `emit_reference_read` spools (cache-only); `report.gather` reads
        # only the TRACKED plane (§6.7) — flush first, same as the real
        # `report` verb does before gathering.
        telemetry.flush(env.ledger, push=False)

        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        row = next(r for r in rs["targets"] if r["ref_target"] == emitted.key)
        assert row["records"] >= 1
        assert row["reads_all_time"] == 1

    def test_t9_2_no_re_split_at_source_level(self):
        """MAJOR 3 (code gate r1): structural, not a spelling blocklist
        -- AST-scans report.py's `_reference_shelf` (the aggregate side)
        and cli.py's `_cmd_telemetry_read_observed` (the emit side) for
        ANY call to str's split family, whatever it is spelled. Both
        functions need zero such calls today (§4.1.2's components come
        off `RefTarget`/the event's own fields), so this is a real,
        zero-false-positive guard against §10.1's re-split defect
        reappearing under a different method name."""
        report_src = Path(report.__file__).read_text(encoding="utf-8")
        cli_src = Path(cli.__file__).read_text(encoding="utf-8")

        shelf_fn = _find_function(ast.parse(report_src), "_reference_shelf")
        assert shelf_fn is not None, "report.py::_reference_shelf not found"
        shelf_hits = _split_family_calls(shelf_fn)
        assert shelf_hits == [], (
            f"report.py::_reference_shelf calls string {shelf_hits} — a "
            "structural re-split of the key/digest, forbidden by §10.1 "
            "even when every other test is green"
        )

        emit_fn = _find_function(ast.parse(cli_src), "_cmd_telemetry_read_observed")
        assert emit_fn is not None, "cli.py::_cmd_telemetry_read_observed not found"
        emit_hits = _split_family_calls(emit_fn)
        assert emit_hits == [], (
            f"cli.py::_cmd_telemetry_read_observed calls string {emit_hits} "
            "— the emit side must read scope/bucket off RefTarget, never "
            "re-split a key string"
        )

        # `refread` imported, used — the aggregate side reads components
        # off RefTarget/the event, never re-derives the mapping itself.
        assert "from .refread import resolve_ref_target" in report_src


# ------------------------------------------------------------------ T10


class TestT10InnerTimeout:
    def test_t10_1_hook_returns_rc0_within_inner_budget(self, env, tmp_path):
        bin_dir = _minimal_bin_dir(tmp_path, "t10")
        slow = bin_dir / "self-learn"
        slow.write_text("#!/usr/bin/env bash\nsleep 999\n", encoding="utf-8")
        slow.chmod(slow.stat().st_mode | stat.S_IEXEC)

        skill_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        skill_refs.mkdir(parents=True)
        target = skill_refs / "LEARNINGS.md"

        import time

        start = time.monotonic()
        result = run_hook(
            json.dumps(_base_payload(str(target))),
            env_vars={"SELF_LEARN_HOME": str(env.ledger), "HOME": str(tmp_path)},
            bin_dir=bin_dir,
            timeout_s=20,
        )
        elapsed = time.monotonic() - start
        assert result.returncode == 0
        # Bounded from BELOW too: a slow CLI that sleeps 999s must
        # actually run into the hook's own `timeout 4` (~4s), not exit
        # near-instantly (the bug this exact assertion caught during
        # development: an incomplete PATH made the slow shim's `sleep`
        # itself unresolvable, so it exited immediately with "command not
        # found" and the timeout path was never really exercised).
        assert 3.5 <= elapsed < 10.0  # comfortably inside the harness's 5s bound + slack

    def test_t10_2_stdout_empty_on_timeout(self, env, tmp_path):
        bin_dir = _minimal_bin_dir(tmp_path, "t10b")
        slow = bin_dir / "self-learn"
        slow.write_text("#!/usr/bin/env bash\nsleep 999\n", encoding="utf-8")
        slow.chmod(slow.stat().st_mode | stat.S_IEXEC)
        skill_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        skill_refs.mkdir(parents=True)
        target = skill_refs / "LEARNINGS.md"
        result = run_hook(
            json.dumps(_base_payload(str(target))),
            env_vars={"SELF_LEARN_HOME": str(env.ledger), "HOME": str(tmp_path)},
            bin_dir=bin_dir,
            timeout_s=20,
        )
        assert result.stdout == ""

    def test_t10_3_source_level_wrapped_in_timeout(self):
        text = HOOK_SCRIPT.read_text(encoding="utf-8")
        assert "timeout 4 self-learn telemetry read-observed" in text


# ------------------------------------------------------------------ T11


class TestT11StdoutSilence:
    def _stimuli(self, env, tmp_path):
        skill_refs = env.host / "plugins" / "s-plugin" / "skills" / "s" / "references"
        skill_refs.mkdir(parents=True)
        target = skill_refs / "LEARNINGS.md"
        ordinary = tmp_path / "src.py"
        ordinary.write_text("x", encoding="utf-8")
        return target, ordinary

    def test_t11_1_stdout_empty_across_six_stimuli(self, env, tmp_path):
        target, ordinary = self._stimuli(env, tmp_path)
        base_env = {"SELF_LEARN_HOME": str(env.ledger), "HOME": str(tmp_path)}

        # 1. successful reference read
        r1 = run_hook(json.dumps(_base_payload(str(target))), env_vars=base_env, bin_dir=_minimal_bin_dir(tmp_path, "s1"))
        # 2. prefilter miss
        r2 = run_hook(json.dumps(_base_payload(str(ordinary))), env_vars=base_env, bin_dir=_minimal_bin_dir(tmp_path, "s2"))
        # 3. jq missing
        r3 = run_hook(json.dumps(_base_payload(str(target))), env_vars=base_env, bin_dir=_minimal_bin_dir(tmp_path, "s3", jq=False))
        # 4. self-learn missing
        r4 = run_hook(json.dumps(_base_payload(str(target))), env_vars=base_env, bin_dir=_minimal_bin_dir(tmp_path, "s4", self_learn=False))
        # 5. CLI non-zero exit
        bin5 = _minimal_bin_dir(tmp_path, "s5")
        bad = bin5 / "self-learn"
        bad.write_text("#!/usr/bin/env bash\necho should-not-appear\nexit 1\n", encoding="utf-8")
        bad.chmod(bad.stat().st_mode | stat.S_IEXEC)
        r5 = run_hook(json.dumps(_base_payload(str(target))), env_vars=base_env, bin_dir=bin5)
        # 6. CLI timeout
        bin6 = _minimal_bin_dir(tmp_path, "s6")
        slow = bin6 / "self-learn"
        slow.write_text("#!/usr/bin/env bash\nsleep 999\n", encoding="utf-8")
        slow.chmod(slow.stat().st_mode | stat.S_IEXEC)
        r6 = run_hook(json.dumps(_base_payload(str(target))), env_vars=base_env, bin_dir=bin6, timeout_s=20)

        for r in (r1, r2, r3, r4, r5, r6):
            assert r.returncode == 0
            assert r.stdout == ""

    def test_t11_2_stderr_may_carry_diagnostics_stdout_still_empty(self, env, tmp_path):
        target, _ = self._stimuli(env, tmp_path)
        result = run_hook(
            json.dumps(_base_payload(str(target))),
            env_vars={"SELF_LEARN_HOME": str(env.ledger), "HOME": str(tmp_path)},
            bin_dir=_minimal_bin_dir(tmp_path, "s7"),
        )
        assert result.stdout == ""


# ------------------------------------------------------------------ T12


class TestT12FlushState:
    def test_t12_1_refused(self, env, monkeypatch):
        def fake_flush(home, *, push=True):
            raise telemetry.ScanRefusal("simulated scan hit")

        monkeypatch.setattr(cli.telemetry, "flush", fake_flush)
        state = cli._flush_spool_best_effort(env.ledger)
        assert state == "refused"

    def test_t12_2_not_attempted_by_default(self, env):
        facts = report.gather(env.ledger, today=TODAY)
        assert facts["reference_shelf"]["flush_state"] == "not-attempted"

    def test_t12_3_ok_on_clean_flush(self, env, monkeypatch, capsys):
        # MAJOR 1 (code gate r1): T12.3's OWN stated criterion is
        # `flush_state == "ok"` AND spooled events counted, not merely
        # `rc == 0` — drives the real `_cmd_report` -> `_flush_spool_
        # best_effort` -> `gather(home, flush_state=...)` three-step path
        # end to end. Kills severing the `cli.py` pass-through (step 2):
        # a build that drops `flush_state=flush_state` from that call
        # still exits 0 and still emits valid JSON, so `rc == 0` alone
        # cannot tell the two apart.
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        _instrument(env.claude)
        seed_reference_routed(env, scope="skill:s", record_id="lrn-7000aaaa")
        key = "skill:s/references/LEARNINGS.md"
        # a real event sitting in the SPOOL (unflushed) — `report` is a
        # flushing verb (§6.7), so this run must move it into the
        # tracked plane and count it, not just report `rc == 0`.
        telemetry.spool_event(
            "reference-read",
            ref_target=key,
            scope="skill",
            bucket="s",
            subagent=False,
            session="sess-t123",
        )

        rc = cli.main(["report", "--json"])
        assert rc == 0
        facts = json.loads(capsys.readouterr().out)
        rs = facts["reference_shelf"]
        assert rs["flush_state"] == "ok"
        row = next(r for r in rs["targets"] if r["ref_target"] == key)
        assert row["reads_all_time"] == 1

    def test_t12_4_failed_osrror_branch(self, env, monkeypatch):
        def fake_flush(home, *, push=True):
            raise OSError("simulated disk failure")

        monkeypatch.setattr(cli.telemetry, "flush", fake_flush)
        state = cli._flush_spool_best_effort(env.ledger)
        assert state == "failed"

    def test_t12_5_all_five_states_reachable(self, env, monkeypatch, capsys):
        """M-M fold r2 NIT n-1: a fifth state ("deferred") was added by
        fold r1 MAJOR M-1; this enumeration must name all five, not the
        four that predate it."""
        observed = set()

        def refused(home, *, push=True):
            raise telemetry.ScanRefusal("x")

        def failed(home, *, push=True):
            raise OSError("x")

        def ok(home, *, push=True):
            return telemetry.FlushReport(events=0, files=[])

        def deferred(home, *, push=True):
            return telemetry.FlushReport(deferred_reason="x", deferred_events=1)

        for fn in (refused, failed, ok, deferred):
            monkeypatch.setattr(cli.telemetry, "flush", fn)
            observed.add(cli._flush_spool_best_effort(env.ledger))
        observed.add(report.gather(env.ledger, today=TODAY)["reference_shelf"]["flush_state"])

        assert observed == {"ok", "refused", "failed", "not-attempted", "deferred"}

    def test_t12_6_deferred_when_flush_could_not_start(self, env, monkeypatch):
        """M-M fold r1 MAJOR M-1: a flush that never got to append (its
        `commit_lock` busy, or the repo itself unavailable) must not read
        as "ok" — `FlushReport.deferred_reason` is how `telemetry.flush`
        says so, and `_flush_spool_best_effort` must pass a non-"ok"
        state through, not swallow it the way it did before the fold
        (when a deferral and an empty spool were indistinguishable)."""

        def fake_flush(home, *, push=True):
            return telemetry.FlushReport(
                deferred_reason="commit lock <path> still held after 0.3s",
                deferred_events=2,
            )

        monkeypatch.setattr(cli.telemetry, "flush", fake_flush)
        state = cli._flush_spool_best_effort(env.ledger)
        assert state == "deferred"

    def test_t12_7_deferred_makes_counts_a_lower_bound(self, env):
        """The one caller that consumes `_flush_spool_best_effort`'s
        outcome (`_cmd_report` -> `report.gather(flush_state=...)`) must
        see its `counts_are_lower_bound` flip True on "deferred" exactly
        like it already does on "refused"/"failed" — this is the whole
        point of `_flush_spool_best_effort` no longer returning "ok" for
        a deferral (fold r1 MAJOR M-1)."""
        facts = report.gather(env.ledger, today=TODAY, flush_state="deferred")
        assert (
            facts["context_budget"]["conditional"]["reference"][
                "counts_are_lower_bound"
            ]
            is True
        )


# ------------------------------------------------------------------ T13


class TestT13ZeroEnumerableTargets:
    def test_t13_1_user_scope_only_is_none_enumerable(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="user", record_id="lrn-6000aaaa")
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert rs["targets_total"] == 0
        assert rs["enumeration_state"] == "none-enumerable"
        assert rs["targets_zero_read"] is None
        assert rs["records_on_zero_read_targets"] is None

    def test_t13_2_unresolvable_records_named(self, env):
        _instrument(env.claude)
        record, _ = seed_reference_routed(env, scope="user", record_id="lrn-6000aaab")
        rs = report.gather(env.ledger, today=TODAY)["reference_shelf"]
        assert rs["unresolvable_records"] == 1
        assert record.id in rs["unresolvable_record_ids"]

    def test_t13_3_text_states_condition_prints_no_zero_counts(self, env):
        _instrument(env.claude)
        seed_reference_routed(env, scope="user", record_id="lrn-6000aaac")
        facts = report.gather(env.ledger, today=TODAY)
        text = report.render_text(facts)
        assert "ABSENT" in text
        assert "targets_zero_read: 0" not in text
        assert "records_on_zero_read_targets: 0" not in text
