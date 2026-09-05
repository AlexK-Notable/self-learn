"""T8: `teach --route` (deterministic --dest path + one-shot analyst) and
the CLI verb wiring (route/reject/defer/graduate/supersede/push/sentinel).

All CLI-level via cli.main (the console entry's target). Sandbox git repos
with bare remotes under tmpdirs; the sentinel is XDG-redirected; the
analyst's `claude` is a PATH shim that records its argv.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest

from self_learn import analyst, cli, sentinel
from self_learn.analyst import ANALYST_ALLOWED_TOOLS, DEFAULT_ANALYST_MODEL
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.normalize import sha_anchor
from self_learn.records import Record
from support import (
    SKILL_MD_SEED,
    commit_all,
    git,
    hook_proposal_fields,
    last_verb_sha,
    make_behavior,
    make_env,
    proposal_dict,
    verb_files,
    verb_subject,
)

SKILL_MD = SKILL_MD_SEED.format(name="s")

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"

# doc 13 T-H3: the routing doctrine now ships with the CLI PACKAGE (one
# file, package-relative) — it is ALWAYS present, no longer installed into
# any home. Tests read the shipped text rather than seeding their own.
DOCTRINE_TEXT = analyst.doctrine_path().read_text(encoding="utf-8")

TEACH_ARGS = [
    "teach",
    "--skill",
    "s",
    "--type",
    "behavior",
    "--kind",
    "anti-pattern",
    "--trigger",
    "About to edit .storage while HA is running.",
    "--instruction",
    "Stop the container first.",
]


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel goes to a per-test XDG cache, never the real ~/.cache."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


class Env:
    """The doc-13 sandbox pair: an independent LEDGER home (skill `s`
    bucket, hosts.yaml registering the host) with a bare remote, plus the
    HOST repo (plugins/s-plugin/skills/s/SKILL.md) with its own bare remote
    so the two-phase canon push is clean. Records live in the ledger; canon
    compiles into the host."""

    def __init__(self, tmp_path):
        e = make_env(tmp_path)
        self.home = e.ledger
        self.host = e.host
        self.skill_dir = e.skill_dir  # host-side plugins/s-plugin/skills/s
        self.skill_md = e.skill_md  # host-side SKILL.md (seeded by make_env)
        self.bare = tmp_path / "remote.git"
        self.host_bare = tmp_path / "host-remote.git"
        for bare, repo in ((self.bare, self.home), (self.host_bare, self.host)):
            subprocess.run(
                ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
            )
            git(repo, "remote", "add", "origin", str(bare))
            git(repo, "push", "-q", "-u", "origin", "main")
        # the ledger's seed subject, for "commit stayed local" assertions
        self.seed_subject = self.local_subject()

    # -- ledger (home) side
    #
    # doc 13 H-5 (audit 2026-07-16 MAJOR 3): telemetry commits ITSELF now,
    # on top of the verb's commit — so "the verb's commit" is the newest
    # NON-flush commit, not HEAD. The assertions keep their strength: the
    # verb commit must still be the newest thing besides the flush, with
    # its exact pinned subject and its exact file list.
    def local_subject(self):
        return verb_subject(self.home)

    def local_body(self):
        return git(
            self.home, "log", "-1", "--format=%B", last_verb_sha(self.home)
        ).stdout

    def remote_subject(self):
        return verb_subject(self.bare)

    def remote_files(self):
        return git(self.bare, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()

    def committed_files(self):
        return verb_files(self.home)

    # -- host side (compiled canon)
    def host_subject(self):
        return git(self.host, "log", "-1", "--format=%s").stdout.strip()

    def host_committed_files(self):
        return git(
            self.host, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()

    # -- ledger bucket paths (skills/s/{pending,resolved})
    def pending_files(self):
        pending = self.home / "skills" / "s" / "pending"
        return sorted(pending.glob("lrn-*.md")) if pending.is_dir() else []

    def resolved_files(self):
        resolved = self.home / "skills" / "s" / "resolved"
        return sorted(resolved.glob("lrn-*.md")) if resolved.is_dir() else []

    def pending(self, rid):
        return self.home / "skills" / "s" / "pending" / f"{rid}.md"

    def resolved(self, rid):
        return self.home / "skills" / "s" / "resolved" / f"{rid}.md"


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


@pytest.fixture
def sdk_fake_analyst(tmp_path, monkeypatch):
    """U-cleanup-A migration: SDK-backed replacement for the bash PATH
    shim, keeping the EXACT interface every dependent test already reads
    (``["log"]``, ``["out"]``, ``["cwd"]``). Routes `analyst.analyze`'s
    invocation through `SdkBackend` against `tests/fixtures/fake_claude.py`
    with `FAKE_CLAUDE_FORCE_SCENARIO=analyst_result` -- the SAME
    scenario/knob pair `test_u_sdka.py::leg`'s sdk branch already uses for
    this surface (`FAKE_CLAUDE_OUT` is the wire-level counterpart of
    `CLAUDE_SHIM_OUT`: the shim used to `cat` it to stdout, the SDK
    scenario emits its text as the terminating `ResultMessage.result`,
    E-7 branch 1). A caller that writes `["out"]` BEFORE `analyst.analyze`
    runs needs no other change."""
    log = tmp_path / "claude-shim-argv.log"
    cwd_log = tmp_path / "claude-shim-cwd.log"
    out = tmp_path / "claude-shim-stdout.txt"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "analyst_result")
    monkeypatch.setenv("FAKE_CLAUDE_OUT", str(out))
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_CWD_LOG", str(cwd_log))
    prompt_log = tmp_path / "claude-shim-prompt.log"
    monkeypatch.setenv("FAKE_CLAUDE_PROMPT_LOG", str(prompt_log))
    return {"log": log, "out": out, "cwd": cwd_log, "prompt": prompt_log}


def seed_pending(env, rid="lrn-0000aaaa", **kwargs):
    record = make_behavior(record_id=rid, **kwargs)
    create_record(env.home, record)
    commit_all(env.home, "seed record")
    git(env.home, "push", "-q")
    return record


def sole(paths):
    (path,) = paths
    return path


# ------------------------------------------------- teach --route --dest


def test_teach_route_dest_end_to_end(env, capsys):
    rc = cli.main(TEACH_ARGS + ["--route", "--dest", "skill-md"])
    out = capsys.readouterr().out
    assert rc == 0

    # Record landed in resolved/ as status: routed — never in pending/.
    assert env.pending_files() == []
    resolved_path = sole(env.resolved_files())
    record = Record.from_path(resolved_path)
    assert record.status == "routed"
    assert record.routing["destination"] == "skill-md"
    assert record.routing["by"] == "human"

    # Compiled section carries the record's line — in the HOST's SKILL.md.
    assert record.id in env.skill_md.read_text(encoding="utf-8")

    # Two-phase (doc 13 §4): LEDGER commit moves the record to resolved/;
    # HOST commit applies the compiled SKILL.md. Each repo touched exactly
    # its own path, and both were pushed.
    assert env.local_subject() == f"self-learn: route {record.id} → skill-md"
    # U-hostmode REC9: the compile record rides this SAME ledger commit —
    # one extra `compiled/<slug>.yaml` path, never a second commit.
    committed = env.committed_files()
    assert f"skills/s/resolved/{record.id}.md" in committed
    compiled_paths = [p for p in committed if p.startswith("compiled/")]
    assert len(compiled_paths) == 1 and compiled_paths[0].endswith(".yaml")
    assert len(committed) == 2
    assert env.remote_subject() == f"self-learn: route {record.id} → skill-md"
    assert f"skills/s/resolved/{record.id}.md" in "\n".join(env.remote_files())

    assert env.host_subject() == (
        f"self-learn: apply {record.id} → "
        "plugins/s-plugin/skills/s/SKILL.md (skill-md)"
    )
    assert env.host_committed_files() == ["plugins/s-plugin/skills/s/SKILL.md"]

    # The applied diff was printed (no confirmation prompt anywhere).
    assert "diff --git" in out
    assert "SKILL.md" in out
    assert f"routed {record.id} → skill-md @" in out
    assert "(pushed)" in out


def test_teach_route_dest_note_rides_record_and_commit_body(env, capsys):
    rc = cli.main(
        TEACH_ARGS + ["--route", "--dest", "skill-md", "--note", "hard-won lesson"]
    )
    assert rc == 0
    record = Record.from_path(sole(env.resolved_files()))
    assert record.resolution_note == "hard-won lesson"
    assert "hard-won lesson" in env.local_body()


def test_teach_route_dest_supersedes_same_commit(env, capsys):
    old = seed_pending(env)
    rc = cli.main(
        TEACH_ARGS + ["--route", "--dest", "skill-md", "--supersedes", old.id]
    )
    assert rc == 0
    new_record = Record.from_path(
        sole([p for p in env.resolved_files() if p.stem != old.id])
    )

    # Old record superseded in the SAME commit, pinned suffix on the subject.
    old_after = Record.from_path(env.resolved(old.id))
    assert old_after.status == "superseded"
    assert old_after.superseded_by == new_record.id
    assert (
        env.local_subject()
        == f"self-learn: route {new_record.id} → skill-md (supersedes {old.id})"
    )
    committed = env.committed_files()
    assert f"resolved/{old.id}.md" in "\n".join(committed)
    assert f"resolved/{new_record.id}.md" in "\n".join(committed)
    # Superseded records never compile (the old line is absent from the HOST).
    assert old.id not in env.skill_md.read_text(encoding="utf-8")


def test_teach_route_no_push_then_push(env, capsys):
    rc = cli.main(TEACH_ARGS + ["--route", "--dest", "skill-md", "--no-push"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "not pushed — --no-push" in out
    assert env.remote_subject() == env.seed_subject  # commit stayed local

    assert cli.main(["push"]) == 0
    assert env.remote_subject().startswith("self-learn: route lrn-")


# --------------------------------------------- teach --route (analyst path)


def test_teach_route_analyst_routes_to_shim_destination(env, sdk_fake_analyst, capsys):
    sdk_fake_analyst["out"].write_text(
        "```yaml\n"
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        + _skill_gates_yaml(env)
        + "```\n",
        encoding="utf-8",
    )
    rc = cli.main(TEACH_ARGS + ["--route"])
    out = capsys.readouterr().out
    assert rc == 0

    # Routed to the fake analyst's destination, never via pending/.
    assert env.pending_files() == []
    record = Record.from_path(sole(env.resolved_files()))
    assert record.routing["destination"] == "skill-md"
    assert env.remote_subject() == f"self-learn: route {record.id} → skill-md"
    assert "analyst: destination skill-md" in out

    # The recorded invocation: doctrine as system prompt, pinned default
    # model, record content riding the prompt. U-cleanup-A migration
    # (§3.4's own measurement names THIS test the one genuine claude-argv
    # test in test_route_cli.py): `-p <prompt>` and `--allowedTools` are
    # CLI-transport-only — measured live, the sdk backend's real argv
    # carries neither (the prompt rides the wire via `ClaudeSDKClient.
    # query`, never argv; allowed-tool enforcement is the `can_use_tool`
    # charter, `CH1`-`CH13`, not a CLI flag) — `--append-system-prompt`
    # and `--model` DO still appear and are unchanged assertions.
    argv = sdk_fake_analyst["log"].read_text(encoding="utf-8").split("\0")[:-1]
    assert argv[argv.index("--append-system-prompt") + 1] == DOCTRINE_TEXT
    assert argv[argv.index("--model") + 1] == DEFAULT_ANALYST_MODEL
    prompt = sdk_fake_analyst["prompt"].read_text(encoding="utf-8")
    assert "About to edit .storage while HA is running." in prompt


def test_teach_route_bare_analyst_path_records_by_analyst(env, sdk_fake_analyst, capsys):
    """FW-64: the bare `teach --route` path's destination comes from
    `analyst.analyze()`, not the human at the terminal — `routing.by`
    must say "analyst", never the old hardcoded/defaulted "human" this
    exact call site used to write (teach.py:698 passed no `by=` at all,
    so `route_direct`'s `by: str = "human"` default silently applied).
    The paired `--dest` path (`test_teach_route_dest_end_to_end`) is
    unaffected — this test's twin is
    `test_route_observability.py::test_route_direct_emits_via_teach_route_dest`,
    which already pins `by == "human"` for that path."""
    sdk_fake_analyst["out"].write_text(
        "```yaml\n"
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        + _skill_gates_yaml(env)
        + "```\n",
        encoding="utf-8",
    )
    rc = cli.main(TEACH_ARGS + ["--route"])
    assert rc == 0
    record = Record.from_path(sole(env.resolved_files()))
    assert record.routing["by"] == "analyst"


@pytest.mark.parametrize(
    "sabotage",
    [
        {"stdout": "::: not yaml {{{\n"},  # unparseable
        {"stdout": "just a string\n"},  # parses, not a mapping
        {"stdout": "destination: bogus\nrationale: r\n"},  # bad enum
        {"stdout": "destination: skill-md\n", "exit": "1"},  # non-zero exit
    ],
)
def test_teach_route_analyst_failure_captures_to_pending(
    env, sdk_fake_analyst, capsys, monkeypatch, sabotage
):
    sdk_fake_analyst["out"].write_text(sabotage["stdout"], encoding="utf-8")
    if "exit" in sabotage:
        monkeypatch.setenv("CLAUDE_SHIM_EXIT", sabotage["exit"])
    rc = cli.main(TEACH_ARGS + ["--route"])
    captured = capsys.readouterr()
    assert rc == 4

    # Never lost: the record sits in pending/ as a NORMAL teach.
    assert env.resolved_files() == []
    record = Record.from_path(sole(env.pending_files()))
    assert record.status == "pending"
    assert record.routing is None
    assert "analysis failed" in captured.err
    assert "captured to pending" in captured.err


def test_teach_route_missing_doctrine_exits_2_pre_spawn(
    env, sdk_fake_analyst, capsys, monkeypatch, tmp_path
):
    """Node name is historical (`_exits_2`) — armor treats a rename as a
    delete plus an add (two doors instead of one), so the name is kept
    even though the code changed. A22 (fold r1, 2026-09-04) unified
    teach's usage-error exit with the CLI's own (`teach.EXIT_USAGE`
    2 -> 64); this is that exit family, so the expected code below moved
    from 2 to 64.

    doc 13 T-H3: the doctrine ships package-relative and is normally
    always present. Force the "not installed" branch by pointing the
    package-refs resolver at an empty dir — the shim must never spawn.
    """
    empty_refs = tmp_path / "empty-refs"
    empty_refs.mkdir()
    monkeypatch.setattr(
        "self_learn.worker.package_skill_refs", lambda: empty_refs
    )
    rc = cli.main(TEACH_ARGS + ["--route"])
    err = capsys.readouterr().err
    assert rc == 64
    assert "routing doctrine not installed — T10" in err
    assert not sdk_fake_analyst["log"].exists()  # pre-spawn
    assert env.pending_files() == [] and env.resolved_files() == []


def test_teach_route_bare_analyst_threads_project_path_at_project_scope(
    env, monkeypatch
):
    """Gate FOLD 6 — teach.py's OWN call site (`_route_now`, ~:683) must
    actually PASS `project_path=` to `analyst.analyze`, not merely have a
    callee that accepts it when supplied (FOLD 5's three tests all drive
    `analyst.analyze` directly — none of them exercise `_route_now`
    itself). Same callee-tested/caller-untested class FOLD 4 closed for
    `_prepare_one_motion_hook`'s `alternates` merge via a
    `validate_proposal` spy on the REAL call site
    (`test_production_call_site_actually_merges_reference_in`) — this
    mirrors that pattern for `analyst.analyze`. Absent/broken: deleting
    `project_path=project_path` from teach.py's call (the one line that
    makes FOLD 5's fix reach the common case) leaves `analyze()`'s new
    parameter perfectly valid and every other test green, since nothing
    else asserts what THIS call site passes it.

    Raises `AnalystError` from the patched `analyze` immediately after
    recording its arguments — cheaper than a full shim/proposal round
    trip, and `_route_now`'s AnalystError branch (`_capture_to_pending`)
    is already covered elsewhere
    (`test_teach_route_analyst_failure_captures_to_pending`); this test's
    OWN job is only the one kwarg."""
    from self_learn import gitops

    expected_project_path = gitops.toplevel(env.host)
    assert expected_project_path is not None  # env.host IS a git repo

    captured: dict = {}

    def fake_analyze(home, record, *, project_path=None, charter_denials=None):
        # U-corrob (`DEN3`, 2026-08-28): `_route_now` now always passes
        # `charter_denials=` alongside `project_path=` (`FW-107`'s shape,
        # extended to the analyst leg) -- accepted and ignored here, this
        # probe's own job is only the `project_path` kwarg (see docstring
        # above).
        captured["project_path"] = project_path
        raise analyst.AnalystError("FOLD 6 probe — captured, not routed")

    monkeypatch.setattr(analyst, "analyze", fake_analyze)
    monkeypatch.chdir(env.host)  # binds project scope to the registered host

    project_args = [
        "teach",
        "About to edit .storage while HA is running.",
        "--type",
        "behavior",
        "--trigger",
        "About to edit .storage while HA is running.",
        "--instruction",
        "Stop the container first.",
        "--route",
    ]
    rc = cli.main(project_args)
    assert rc == 4  # EXIT_ANALYST — the probe's AnalystError, captured to pending
    assert "project_path" in captured
    assert captured["project_path"] == expected_project_path


# ---------------------------- analyst.analyze() proposal fidelity + cwd --
# U-analyst (FW-41, docs/specs/self-learn/drafts/
# u-analyst-proposal-fidelity-spec.md): the enumerated-rebuild defect and
# the missing cwd=home pin. All six call analyst.analyze(env.home, record)
# directly, per the spec's §4 builder decision — the CLI path additionally
# needs the one_motion_route config opt-in before a hook proposal is
# observable at all, and that gate is out of this unit's scope.


def _yaml_dump(data: dict) -> str:
    """Serialize a dict to YAML text for a shim's canned stdout (mirrors
    test_one_motion_config.py's io.StringIO + ruamel pattern)."""
    import io

    from ruamel.yaml import YAML

    buf = io.StringIO()
    YAML(typ="safe").dump(data, buf)
    return buf.getvalue()


# S-26 (ledger_ops.TRACE_REQUIRED): every proposal the fake analyst shim
# emits now needs a decision trace, containment-checked against the REAL
# record it rides (`make_behavior()`'s default trigger, "About to edit
# .storage while HA is running.") and, for `gates.t3.roster_sha`,
# X3-honesty-checked against the REAL roster `env.home`'s skill "s"
# composes (`worker.skill_roster` -- same idiom as test_worker.py's own
# `_proposal_yaml`). These trace bodies are appended after a shim's own
# `destination`/`alternates`/... lines, exactly like `_yaml_dump` already
# is for the hook-fields case above.

_TRIGGER_QUOTE = "About to edit .storage while HA is running."


def _roster_sha(env) -> str:
    from self_learn.worker import skill_roster

    return skill_roster(env.home).sha


def _skill_gates_yaml(env) -> str:
    """A SKILL-outcome trace at scope skill:s -- `make_behavior()`'s
    default scope -- always routable (recommendation: route)."""
    return f"""gates:
  g0:
    reject: {{answer: "no"}}
    defer: {{answer: "no"}}
    canon: {{answer: "no"}}
  t1:
    attempted: false
    field_shaped:
      answer: "no"
      evidence: "{_TRIGGER_QUOTE}"
    separable: {{answer: null}}
    cost_bearing: {{answer: null}}
  t2:
    answer: "no"
    evidence: "{_TRIGGER_QUOTE}"
    match_path: null
  t3:
    answer: "yes"
    owner: "s"
    scan_terms: null
    roster_sha: "{_roster_sha(env)}"
  t3a:
    depth_behind_rule: {{answer: "no", evidence: null}}
    fs: {{verdict: "SILENT", evidence: "{_TRIGGER_QUOTE}"}}
  tn: {{answer: "no", terms: [], members: [], proposed_name: null}}
  t4: null
  e1: {{sightings: 1, post_demand_recurrence: false}}
  outcome: SKILL
flags: []
recommendation: route
"""


def _hook_gates_yaml(env) -> str:
    """A HOOK-outcome trace (T1's H row) whose load class is SKILL,
    matching the `alternates: [skill-md]` every hook fixture in this file
    already declares (R-HOOK needs the load class's own destination
    inside `alternates`)."""
    return f"""gates:
  g0:
    reject: {{answer: "no"}}
    defer: {{answer: "no"}}
    canon: {{answer: "no"}}
  t1:
    attempted: true
    field_shaped:
      answer: "yes"
      evidence: "{_TRIGGER_QUOTE}"
    separable:
      answer: "yes"
      evidence: "{_TRIGGER_QUOTE}"
    cost_bearing:
      answer: "yes"
      evidence: "{_TRIGGER_QUOTE}"
  t2:
    answer: "no"
    evidence: "{_TRIGGER_QUOTE}"
    match_path: null
  t3:
    answer: "yes"
    owner: "s"
    scan_terms: null
    roster_sha: "{_roster_sha(env)}"
  t3a:
    depth_behind_rule: {{answer: "no", evidence: null}}
    fs: {{verdict: "SILENT", evidence: "{_TRIGGER_QUOTE}"}}
  tn: {{answer: "no", terms: [], members: [], proposed_name: null}}
  t4: null
  e1: {{sightings: 1, post_demand_recurrence: false}}
  outcome: HOOK
flags: []
recommendation: route
"""


def _defer_gates_yaml(env) -> str:
    """A DEFER-outcome trace (G2's g0.defer leg) -- destination must be
    the load class's own render (DEMAND -> "reference" here, since every
    downstream gate is the "not reached" skeleton), never the outcome's."""
    return f"""gates:
  g0:
    reject: {{answer: "no"}}
    defer:
      answer: "yes"
      evidence: "{_TRIGGER_QUOTE}"
    canon: {{answer: "no"}}
  t1:
    attempted: false
    field_shaped:
      answer: "no"
      evidence: "{_TRIGGER_QUOTE}"
    separable: {{answer: null}}
    cost_bearing: {{answer: null}}
  t2:
    answer: "no"
    evidence: "{_TRIGGER_QUOTE}"
    match_path: null
  t3:
    answer: "no"
    owner: null
    scan_terms: ["probe", "terms"]
    roster_sha: "{_roster_sha(env)}"
  t3a: null
  tn: {{answer: "no", terms: [], members: [], proposed_name: null}}
  t4:
    depth_behind_rule: {{answer: "no", evidence: null}}
    conduct_mode: {{answer: "no", evidence: null}}
    fs: {{verdict: "INDETERMINATE", evidence: null}}
  e1: {{sightings: 1, post_demand_recurrence: false}}
  outcome: DEFER
flags: []
"""


def test_analyst_analyze_round_trips_unknown_fields(env, sdk_fake_analyst):
    """A1 — campaign §5 positive control. r2's incoming `recommendation:`
    key and a synthetic `probe_key`, both nowhere in analyst.py and
    nowhere in validate_proposal, must round-trip with their emitted
    values. A test that only round-trips fields the analyst already knows
    about would pass just as happily on the broken (M1b) code — that is
    the reason this assertion exists."""
    sdk_fake_analyst["out"].write_text(
        "destination: reference\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        + _defer_gates_yaml(env)
        + "recommendation: defer\n"
        "probe_key: probe-value\n",
        encoding="utf-8",
    )
    proposal = analyst.analyze(env.home, make_behavior())
    assert proposal["recommendation"] == "defer"
    assert proposal["probe_key"] == "probe-value"


def test_analyst_analyze_hook_round_trips(env, sdk_fake_analyst):
    """A2 (FW-41) — a doctrine-conformant hook proposal must return
    without raising, with the returned hook/examples equal to what the
    model emitted. Today the enumerated rebuild drops both keys before
    validate_proposal ever sees them, so this raises AnalystError."""
    hook_fields = hook_proposal_fields()
    body = (
        "destination: hook\n"
        "alternates: [skill-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        + _hook_gates_yaml(env)
    ) + _yaml_dump(hook_fields)
    sdk_fake_analyst["out"].write_text(body, encoding="utf-8")
    proposal = analyst.analyze(env.home, make_behavior())
    assert proposal["hook"] == hook_fields["hook"]
    assert proposal["examples"] == hook_fields["examples"]


def test_analyst_analyze_cli_owned_fields_win(env, sdk_fake_analyst):
    """A3 — model-emitted model/analyzed_at/record_sha (valid shape,
    deliberately wrong value — the control) must be overwritten by the
    CLI's own stamp, never carried through. Matching values could not
    tell a stamped field from a carried one."""
    sdk_fake_analyst["out"].write_text(
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        "model: pwned-model\n"
        "analyzed_at: 1999-01-01T00:00:00Z\n"
        "record_sha: sha256:deadbeefdead\n"
        + _skill_gates_yaml(env),
        encoding="utf-8",
    )
    record = make_behavior()
    proposal = analyst.analyze(env.home, record)
    assert proposal["model"] == DEFAULT_ANALYST_MODEL
    assert proposal["record_sha"] == sha_anchor(record.body)
    assert proposal["analyzed_at"] != "1999-01-01T00:00:00Z"


def _script_probe_body(env, destination: str) -> str:
    """A4 shim body: an otherwise-valid `destination` proposal that also
    carries a forbidden `script` and a `probe_key`."""
    lines = [
        f"destination: {destination}\n",
        "rationale: deterministic guard beats advisory text\n",
        'script: "#!/usr/bin/env bash\\necho pwned\\n"\n',
        "probe_key: probe-value\n",
    ]
    if destination == "hook":
        lines.append("alternates: [skill-md]\n")
        lines.append(_hook_gates_yaml(env))
        lines.append(_yaml_dump(hook_proposal_fields()))
    else:
        lines.append("alternates: [claude-md]\n")
        lines.append(_skill_gates_yaml(env))
    return "".join(lines)


@pytest.mark.parametrize("destination", ["hook", "skill-md"])
def test_analyst_analyze_strips_script_unconditionally(env, sdk_fake_analyst, destination):
    """A4 — `script` is the one key this codebase refuses from a model on
    every other path; it must never survive into the returned proposal,
    regardless of destination. The skill-md case is what makes the strip
    unconditional-and-pre-validation load-bearing: validate_proposal
    refuses a `script` key outright on any non-hook destination, so a
    strip that only fires for destination == "hook", or that runs after
    validate_proposal, turns THIS routable non-hook proposal into an
    AnalystError instead of a clean return — the hook case alone cannot
    see that failure mode. The probe_key assertion is the presence check
    that stops the absence assertion ("script" not in proposal) passing
    vacuously on a build that carries nothing at all."""
    sdk_fake_analyst["out"].write_text(
        _script_probe_body(env, destination), encoding="utf-8"
    )
    proposal = analyst.analyze(env.home, make_behavior())
    assert "script" not in proposal
    assert proposal["probe_key"] == "probe-value"


def test_analyst_analyze_runs_in_ledger_home(env, sdk_fake_analyst, monkeypatch, tmp_path):
    """A5 — the analyst subprocess's cwd is pinned to `home`, never
    inherited from the caller. The chdir to an unrelated directory is the
    control: without it, an unpinned build could pass whenever pytest's
    own cwd happened to match `home`."""
    sdk_fake_analyst["out"].write_text(
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        + _skill_gates_yaml(env),
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    analyst.analyze(env.home, make_behavior())
    recorded = sdk_fake_analyst["cwd"].read_text(encoding="utf-8").strip()
    assert recorded == str(Path(env.home).resolve())


@pytest.mark.parametrize("kind", ["missing", "file", "unenterable"])
def test_analyst_analyze_bad_home_refuses_pre_spawn(sdk_fake_analyst, tmp_path, kind):
    """A6 — a home that is not an ENTERABLE directory refuses pre-spawn,
    naming the offending path in the message. `is_dir()` alone does not
    close the class: an existing directory without the search bit still
    reaches `subprocess.run(cwd=...)`, which raises PermissionError —
    caught by nothing, escaping analyze()'s AnalystError-only contract.
    Neither "AnalystError was raised" (the unguarded build raises one too,
    mislabeled "claude CLI not found on PATH" once cwd=home is wired) nor
    "the shim never ran" (absent pre-spawn on both builds either way) can
    tell a guarded build from an unguarded one — only the message content
    can, hence the substring assertion below."""
    if kind == "unenterable" and os.geteuid() == 0:
        pytest.skip("root ignores the directory search bit")
    if kind == "missing":
        bad_home = tmp_path / "does-not-exist"
    elif kind == "file":
        bad_home = tmp_path / "a-file"
        bad_home.write_text("not a directory", encoding="utf-8")
        # EXECUTABLE on purpose. A 0644 file fails os.access(X_OK) for the
        # wrong reason, which lets a guard reduced to os.access(X_OK) alone
        # — is_dir() deleted — pass this case. Measured: with that guard an
        # executable regular file reaches subprocess.run(cwd=...) and raises
        # NotADirectoryError, which escapes analyze()'s AnalystError-only
        # contract and loses the captured lesson. 0o755 pins the is_dir()
        # half so only the real guard passes.
        bad_home.chmod(0o755)
    else:
        bad_home = tmp_path / "unenterable"
        bad_home.mkdir()
        bad_home.chmod(0o000)
    try:
        with pytest.raises(analyst.AnalystError) as exc_info:
            analyst.analyze(bad_home, make_behavior())
        assert str(bad_home) in str(exc_info.value)
    finally:
        if kind == "unenterable":
            bad_home.chmod(0o755)  # let tmp_path cleanup rmtree it


# ----------------------------------------------------------- verb wiring


def test_route_cli_with_proposal_sibling(env, capsys):
    record = seed_pending(env)
    write_proposal(env.home, record.id, proposal_dict())
    commit_all(env.home, "proposal")

    rc = cli.main(["route", record.id])
    out = capsys.readouterr().out
    assert rc == 0
    assert env.resolved(record.id).is_file()
    assert env.local_subject() == f"self-learn: route {record.id} → skill-md"
    assert env.remote_subject() == f"self-learn: route {record.id} → skill-md"
    assert record.id in env.skill_md.read_text(encoding="utf-8")
    sha7 = git(
        env.home, "rev-parse", "--short=7", last_verb_sha(env.home)
    ).stdout.strip()
    assert f"route {record.id} → skill-md @ {sha7} (pushed)" in out


def test_route_cli_no_proposal_no_dest_exits_1(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["route", record.id])
    assert rc == 1
    assert "no proposal" in capsys.readouterr().err


def test_route_cli_bare_new_skill_exits_1_naming_the_recipe(env, capsys):
    # supersedes the M1-era exit-2 "not built until M3" check: the
    # compiler exists (T18), but the name slot is the human's call.
    record = seed_pending(env)
    rc = cli.main(["route", record.id, "--dest", "new-skill"])
    assert rc == 1
    assert "new-skill:<name>" in capsys.readouterr().err
    assert env.pending(record.id).is_file()  # untouched


def test_reject_cli_note_in_commit_body(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["reject", record.id, "--note", "duplicate of canon"])
    out = capsys.readouterr().out
    assert rc == 0
    assert env.local_subject() == f"self-learn: reject {record.id}"
    assert "duplicate of canon" in env.local_body()
    assert Record.from_path(env.resolved(record.id)).status == "rejected"
    assert f"reject {record.id} → rejected @" in out


def test_defer_cli_until_date(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["defer", record.id, "--until", "2027-01-01"])
    out = capsys.readouterr().out
    assert rc == 0
    after = Record.from_path(env.pending(record.id))  # defer stays pending
    assert str(after.deferred_until) == "2027-01-01"
    assert env.local_subject() == f"self-learn: defer {record.id} until 2027-01-01"
    assert f"defer {record.id} → deferred until 2027-01-01 @" in out


def test_defer_cli_bad_date_is_usage_error(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["defer", record.id, "--until", "next tuesday"])
    assert rc == 64
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_graduate_cli(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["graduate", record.id])
    assert rc == 0
    after = Record.from_path(env.resolved(record.id))
    assert after.status == "superseded"
    assert after.superseded_by == "canon"
    assert env.local_subject() == f"self-learn: graduate {record.id}"


def test_supersede_cli(env, capsys):
    old = seed_pending(env, rid="lrn-0000aaaa")
    new = seed_pending(env, rid="lrn-0000bbbb")
    rc = cli.main(["supersede", old.id, new.id])
    assert rc == 0
    after = Record.from_path(env.resolved(old.id))
    assert after.superseded_by == new.id
    assert env.local_subject() == f"self-learn: supersede {old.id} → {new.id}"


def test_verb_no_push_then_bare_push(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["reject", record.id, "--no-push"])
    assert rc == 0
    assert "not pushed — --no-push" in capsys.readouterr().out
    assert env.remote_subject() == "seed record"

    rc = cli.main(["push"])
    assert rc == 0
    assert env.remote_subject() == f"self-learn: reject {record.id}"


def test_unknown_record_id_is_usage_error(env, capsys):
    rc = cli.main(["reject", "lrn-deadbeef"])
    assert rc == 64
    assert "not found" in capsys.readouterr().err


def test_malformed_record_id_is_usage_error(env, capsys):
    rc = cli.main(["route", "not-an-id"])
    assert rc == 64
    assert "not a record id" in capsys.readouterr().err


# --------------------------------------------------------------- sentinel


def test_sentinel_hold_heartbeat_release_cycle(env, capsys):
    path = sentinel.sentinel_path()

    assert cli.main(["sentinel", "hold"]) == 0
    assert path.is_file()
    assert "sentinel held" in capsys.readouterr().out

    # heartbeat re-touches a live sentinel's mtime.
    old = time.time() - 600
    os.utime(path, (old, old))
    assert cli.main(["sentinel", "heartbeat"]) == 0
    assert path.stat().st_mtime > old + 1
    assert "sentinel heartbeat" in capsys.readouterr().out

    assert cli.main(["sentinel", "release"]) == 0
    assert not path.exists()
    assert "sentinel released" in capsys.readouterr().out


def test_sentinel_heartbeat_without_hold_is_noop(env, capsys):
    assert cli.main(["sentinel", "heartbeat"]) == 0
    assert "no live sentinel" in capsys.readouterr().out
    assert not sentinel.sentinel_path().exists()


def test_sentinel_release_without_hold(env, capsys):
    assert cli.main(["sentinel", "release"]) == 0
    assert "none held" in capsys.readouterr().out


def test_verbs_self_hold_releases_only_own_sentinel(env, capsys):
    # A pre-existing LIVE hold (the slash review's batch hold) survives a verb.
    assert cli.main(["sentinel", "hold"]) == 0
    record = seed_pending(env)
    assert cli.main(["reject", record.id]) == 0
    assert sentinel.sentinel_path().is_file()  # not released by the verb
    assert cli.main(["sentinel", "release"]) == 0
    assert not sentinel.sentinel_path().exists()
