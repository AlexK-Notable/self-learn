"""Shared test helpers: sandbox git repos, record/proposal factories.

Tests create throwaway git repos under pytest tmpdirs and run git freely
inside them — never against the worktree repo itself.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from self_learn.records import Record

# ------------------------------------------------------------------ git


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")


def commit_all(repo: Path, message: str = "seed") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


_GIT_SHIM = '''#!/usr/bin/env python3
"""A REAL git that fails one subcommand while a flag file exists."""
import os, subprocess, sys

args = sys.argv[1:]
i, sub = 0, None
while i < len(args):
    a = args[i]
    if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
        i += 2
        continue
    if a.startswith("-"):
        i += 1
        continue
    sub = a
    break
if sub == {sub!r} and os.path.exists({flag!r}):
    sys.stderr.write("fatal: simulated git " + {sub!r} + " failure\\n")
    sys.exit(1)
sys.exit(subprocess.run([{real!r}, *args]).returncode)
'''


def failing_git_shim(tmp_path: Path, monkeypatch, *, sub: str = "commit") -> Path:
    """Put a REAL git shim on PATH that passes everything through to the
    real git except ``sub``, which fails while the returned FLAG file
    exists (audit 2026-07-16 round 7 BLOCKER 2's probe shape, made a
    fixture).

    A held lock is no longer a way to make a commit fail — the round-7
    invariant takes the lock BEFORE the first mutation, so a lock timeout
    is now a clean refusal that wrote nothing (which is the point). The
    ONLY way left to reach the half-written state is a git that fails at
    the commit itself, which is exactly what this produces — a real
    process failing a real exec, no mocks, and no monkeypatching of the
    code under test.

    Flag-gated rather than always-on so the surrounding test harness
    (:func:`commit_all` and friends) can still use git normally: create
    the flag immediately before the call under test, remove it after."""
    real = shutil.which("git")
    assert real, "no git on PATH"
    d = tmp_path / f"git-shim-{sub}"
    d.mkdir(parents=True, exist_ok=True)
    flag = tmp_path / f"fail-git-{sub}"
    shim = d / "git"
    shim.write_text(_GIT_SHIM.format(sub=sub, flag=str(flag), real=real))
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    return flag


#: The producer commit telemetry makes for itself (doc 13 H-5; audit
#: 2026-07-16 MAJOR 3). It rides on TOP of a verb's own commit, so "the
#: verb's commit" is no longer a synonym for HEAD.
TELEMETRY_SUBJECT = "self-learn: telemetry flush"


def last_verb_sha(repo: Path) -> str:
    """The newest commit that is NOT a telemetry-flush commit — i.e. the
    verb's own commit. Assertions keep their full strength: the verb
    commit must still be the newest thing besides the flush, with its
    exact pinned subject and its exact file list."""
    for line in git(repo, "log", "--format=%H %s").stdout.splitlines():
        sha, _, subject = line.partition(" ")
        if not subject.startswith(TELEMETRY_SUBJECT):
            return sha
    raise AssertionError(f"no non-telemetry commit in {repo}")


def verb_subject(repo: Path) -> str:
    return git(
        repo, "log", "-1", "--format=%s", last_verb_sha(repo)
    ).stdout.strip()


def verb_files(repo: Path) -> list[str]:
    return git(
        repo,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        last_verb_sha(repo),
    ).stdout.split()


# ------------------------------------------------- ledger home + host repo


class SandboxEnv:
    """The doc-13 fixture surface: an independent LEDGER home plus one
    sandbox HOST repo (skills root + registered project host in one)."""

    def __init__(self, ledger: Path, host: Path, skills: tuple[str, ...]):
        self.ledger = ledger
        self.host = host
        first = skills[0] if skills else "s"
        self.skill_dir = host / "plugins" / f"{first}-plugin" / "skills" / first
        self.skill_md = self.skill_dir / "SKILL.md"


SKILL_MD_SEED = "# {name} skill\n\nAuthored prose stays put.\n"
CLAUDE_MD_SEED = "# host project\n\nAuthored context stays put.\n"


def make_env(tmp_path: Path, skills: tuple[str, ...] = ("s",)) -> SandboxEnv:
    """Build the NEW (doc 13 §3) sandbox pair:

    - HOST repo at ``tmp_path/host-repo``: ``plugins/<n>-plugin/skills/<n>/
      SKILL.md`` per skill + a root ``CLAUDE.md``, git init + seed commit.
    - LEDGER home at ``tmp_path/ledger-home``: git repo with the layout
      dirs (``skills/ projects/ user/ telemetry/``) and a ``hosts.yaml``
      registering the host repo as BOTH skills root and project host.
    """
    host = tmp_path / "host-repo"
    init_repo(host)
    for name in skills:
        skill_dir = host / "plugins" / f"{name}-plugin" / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            SKILL_MD_SEED.format(name=name), encoding="utf-8"
        )
    (host / "CLAUDE.md").write_text(CLAUDE_MD_SEED, encoding="utf-8")
    commit_all(host, "host seed")

    ledger = tmp_path / "ledger-home"
    init_repo(ledger)
    for sub in ("skills", "projects", "user", "telemetry"):
        (ledger / sub).mkdir()
    (ledger / "hosts.yaml").write_text(
        f"skills_root: {host}\nprojects:\n  - path: {host}\n", encoding="utf-8"
    )
    commit_all(ledger, "ledger seed")
    return SandboxEnv(ledger, host, skills)


def make_home(tmp_path: Path, skills: tuple[str, ...] = ("s",)) -> Path:
    """A sandbox ledger home on the doc-13 layout (see :func:`make_env`);
    returns the LEDGER path — the paired host repo sits at
    ``tmp_path/host-repo``."""
    return make_env(tmp_path, skills).ledger


# --------------------------------------------------------------- records


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def days_ago(n: int) -> str:
    return iso(datetime.now(timezone.utc) - timedelta(days=n))


def make_behavior(
    scope: str = "skill:s",
    record_id: str | None = None,
    created_at: str | None = None,
    trigger: str = "About to edit .storage while HA is running.",
    instruction: str = "Stop the container first.",
) -> Record:
    return Record.create(
        type="behavior",
        scope=scope,
        source="teach",
        kind="anti-pattern",
        trigger=trigger,
        instruction=instruction,
        record_id=record_id,
        created_at=created_at,
    )


def make_knowledge(
    scope: str = "project",
    record_id: str | None = None,
    created_at: str | None = None,
    fact: str = "The router reserves 192.0.2.232 for the Beacon.",
) -> Record:
    return Record.create(
        type="knowledge",
        scope=scope,
        source="teach",
        fact=fact,
        record_id=record_id,
        created_at=created_at,
    )


# -------------------------------------------------------------- proposals
#
# S-26 (U-composer): the decision trace is now MANDATORY on every
# proposal `validate_proposal` accepts. The ~90 pre-existing call sites
# across this suite construct a proposal via `proposal_dict()` to test
# something ELSE entirely (glob validation, hook compilation, commit
# drift, retirement, verb wiring…) — none of them are about the trace's
# OWN content. Rather than hand-write a bespoke trace at each site,
# `proposal_dict()` now auto-attaches a Table-1-DERIVATION-CONSISTENT
# default trace keyed off the final `destination` (and `variant`/
# `rules_paths` where relevant), computed AFTER `overrides` are merged —
# unless the caller supplies `gates` itself, in which case nothing here
# is touched. `scope` is a separate keyword (default "skill:s", matching
# `make_behavior()`'s own default) because Table-1's derivation is
# scope-sensitive (R-SCOPE, and SKILL's t3-ownership match) in a way a
# destination string alone cannot resolve — callers pairing a proposal
# with a record at a DIFFERENT scope must pass the same `scope=` here.
#
# RECORD-sourced evidence quotes use `_RECORD_QUOTE` — a structural
# frontmatter fragment (`status: pending`) every fixture record carries
# regardless of its trigger/instruction/fact text, so containment
# (checked against the REAL paired record's `to_text()`) never depends
# on what that record's authored content happens to say. TARGET-sourced
# quotes are never containment-checked (u-schema §3.7 item 1 / R3), so
# they are free-form here.
#
# The roster-sha these traces carry is a well-shaped DUMMY
# (`sha256:000000000000`) — this is safe here because `write_proposal`/
# `validate_proposal` alone never checks a roster-sha's VALUE against a
# real composed roster (X3 checks only its SHAPE); the honesty check
# U-composer added (§3.6) lives in `worker._validate_written` and
# `analyst.analyze`, exercised only by an actual worker/analyst run —
# `test_worker.py`'s own `PROPOSAL_YAML_TEMPLATE` computes a REAL roster
# sha for exactly that reason, this one does not need to.

_RECORD_QUOTE = "status: pending"
_DUMMY_SHA = "sha256:000000000000"


def _base_gate_answers() -> dict:
    """The shared g0/t1(no)/t2(no)/t3(no)/t3a(null)/tn(no) skeleton every
    non-HOOK, non-SKILL, non-NEW_SKILL default trace starts from."""
    return {
        "g0": {
            "reject": {"answer": "no"},
            "defer": {"answer": "no"},
            "canon": {"answer": "no"},
        },
        "t1": {
            "attempted": False,
            "field_shaped": {"answer": "no", "evidence": _RECORD_QUOTE},
            "separable": {"answer": None},
            "cost_bearing": {"answer": None},
        },
        "t2": {"answer": "no", "evidence": _RECORD_QUOTE, "match_path": None},
        "t3": {
            "answer": "no",
            "owner": None,
            "scan_terms": ["probe", "terms"],
            "roster_sha": _DUMMY_SHA,
        },
        "t3a": None,
        "tn": {"answer": "no", "terms": [], "members": [], "proposed_name": None},
    }


def _e1_default() -> dict:
    return {"sightings": 1, "post_demand_recurrence": False}


def _routable_at(rendered: str, scope: str) -> bool:
    """Mirrors `ledger_ops._routable` (u-table §3.4) — R-SCOPE's two
    no-surface corners, kept local so this fixture module never reaches
    into that private function."""
    if rendered == "DEMAND":
        return scope != "user"
    if rendered == "PATHED":
        return not (isinstance(scope, str) and scope.startswith("skill:"))
    return True


def _skill_trace(scope: str) -> dict:
    owner = scope.partition(":")[2] if scope.startswith("skill:") else "s"
    gates = _base_gate_answers()
    gates["t3"] = {
        "answer": "yes",
        "owner": owner,
        "scan_terms": None,
        "roster_sha": _DUMMY_SHA,
    }
    gates["t3a"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None},
        "fs": {"verdict": "SILENT", "evidence": _RECORD_QUOTE},
    }
    gates["t4"] = None  # t3-route taken (owner matches scope) -> t4 null
    gates["e1"] = _e1_default()
    gates["outcome"] = "SKILL"
    return {"gates": gates, "flags": [], "recommendation": "route"}


def _always_trace() -> dict:
    gates = _base_gate_answers()
    gates["t4"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None},
        "conduct_mode": {"answer": "yes", "evidence": _RECORD_QUOTE},
        "fs": {"verdict": "INDETERMINATE", "evidence": None},
    }
    gates["e1"] = _e1_default()
    gates["outcome"] = "ALWAYS"
    return {"gates": gates, "flags": [], "recommendation": "route"}


def _sample_path_for_glob(pattern: str) -> str:
    """A literal path that matches `pattern` under this project's glob
    translator (`_glob_match`) — crude but sufficient for the shapes this
    suite's fixtures actually use (`src/**/*.ts`, `lib/*.ts`,
    `a/**`, …): drop `**` segments (they match zero levels), replace
    every `*` with a literal `x`.

    A TRAILING `/**` is a special case: `_compile_glob_pattern` treats a
    final `**` as `.*` preceded by a forced `/` separator (the segment
    before it never "supplies" that separator itself, unlike a `**` in
    the middle) — so `"a/**"` compiles to `a/.*`, which a bare `"a"`
    sample does NOT match (X1 measured this: `gates.t2.match_path 'a'
    matches none of rules_paths ['a/**']`). Append a synthetic trailing
    segment whenever the pattern ends in `**` so the sample lands past
    that forced separator."""
    segments = pattern.split("/")
    trailing_double_star = len(segments) > 1 and segments[-1] == "**"
    parts = [seg for seg in segments if seg != "**"]
    parts = [seg.replace("*", "x") for seg in parts]
    if trailing_double_star:
        parts.append("x")
    return "/".join(parts) or "x"


def _pathed_trace(scope: str, rules_paths: list) -> dict:
    gates = _base_gate_answers()
    match_path = _sample_path_for_glob(rules_paths[0])
    gates["t2"] = {"answer": "yes", "evidence": _RECORD_QUOTE, "match_path": match_path}
    gates["t4"] = None  # t2.answer == "yes" -> t4 null
    gates["e1"] = _e1_default()
    gates["outcome"] = "PATHED"
    routable = _routable_at("PATHED", scope)
    return {
        "gates": gates,
        "flags": [] if routable else ["no-cheap-surface"],
        "recommendation": "route" if routable else "defer",
    }


def _demand_trace(scope: str) -> dict:
    gates = _base_gate_answers()
    gates["t4"] = {
        "depth_behind_rule": {
            "answer": "yes",
            "evidence": "the target already documents this at length",
            "target": "the candidate target",
        },
        "conduct_mode": {"answer": "no", "evidence": None},
        "fs": {"verdict": "INDETERMINATE", "evidence": None},
    }
    gates["e1"] = _e1_default()
    gates["outcome"] = "DEMAND"
    routable = _routable_at("DEMAND", scope)
    return {
        "gates": gates,
        "flags": [] if routable else ["no-cheap-surface"],
        "recommendation": "route" if routable else "defer",
    }


def _hook_trace(scope: str, alternates: list) -> dict:
    """R-HOOK requires `alternates` to contain the LOAD CLASS's own
    destination (§3.1 note 1: load_class is computed even when a `g0`
    leg or `H` already decided the outcome) — and a caller's `alternates`
    override varies by test (`skill-md`, `claude-md`, `reference`, …), so
    the underlying load class must be picked to MATCH whichever
    destination the caller actually asked for, not a fixed one."""
    gates = _base_gate_answers()
    gates["t1"] = {
        "attempted": True,
        "field_shaped": {"answer": "yes", "evidence": _RECORD_QUOTE},
        "separable": {"answer": "yes", "evidence": _RECORD_QUOTE},
        "cost_bearing": {"answer": "yes", "evidence": _RECORD_QUOTE},
    }
    owner = scope.partition(":")[2] if scope.startswith("skill:") else None
    if "skill-md" in alternates and owner is not None:
        # L2b (SKILL): t3-route taken + a promoting fs verdict.
        gates["t3"] = {
            "answer": "yes",
            "owner": owner,
            "scan_terms": None,
            "roster_sha": _DUMMY_SHA,
        }
        gates["t3a"] = {
            "depth_behind_rule": {"answer": "no", "evidence": None},
            "fs": {"verdict": "SILENT", "evidence": _RECORD_QUOTE},
        }
        gates["t4"] = None  # t3-route taken -> t4 null
    elif "reference" in alternates:
        # L4 (DEMAND): t4.depth_behind_rule yes (TARGET-sourced, free).
        gates["t4"] = {
            "depth_behind_rule": {
                "answer": "yes",
                "evidence": "the target already documents this at length",
                "target": "the candidate target",
            },
            "conduct_mode": {"answer": "no", "evidence": None},
            "fs": {"verdict": "INDETERMINATE", "evidence": None},
        }
    elif "new-skill" in alternates:
        # L3 (NEW_SKILL): tn.answer yes -> t4 null (unusual HOOK alternate,
        # supported for completeness — no fixture uses it today).
        gates["tn"] = {
            "answer": "yes",
            "terms": ["probe", "terms"],
            "members": ["lrn-aaaaaaaa", "lrn-bbbbbbbb"],
            "proposed_name": "probe-skill",
        }
        gates["t4"] = None
    else:
        # L5 (ALWAYS) — the default, matching `proposal_dict`'s own
        # default `alternates: ["claude-md"]`.
        gates["t4"] = {
            "depth_behind_rule": {"answer": "no", "evidence": None},
            "conduct_mode": {"answer": "yes", "evidence": _RECORD_QUOTE},
            "fs": {"verdict": "INDETERMINATE", "evidence": None},
        }
    gates["e1"] = _e1_default()
    gates["outcome"] = "HOOK"
    return {"gates": gates, "flags": [], "recommendation": "route"}


def _new_skill_trace(name: str) -> dict:
    gates = _base_gate_answers()
    gates["tn"] = {
        "answer": "yes",
        "terms": ["probe", "terms"],
        "members": ["lrn-aaaaaaaa", "lrn-bbbbbbbb"],
        "proposed_name": name,
    }
    gates["t4"] = None  # tn.answer == "yes" -> t4 null
    gates["e1"] = _e1_default()
    gates["outcome"] = "NEW_SKILL"
    return {
        "gates": gates,
        "flags": [],
        "recommendation": "route",
        "new_skill": name,
    }


def default_trace_for(base: dict, scope: str) -> dict:
    """Pick the Table-1-consistent default trace for `base`'s (already
    override-merged) `destination`/`variant`/`rules_paths` at `scope`."""
    destination = base.get("destination")
    variant = base.get("variant")
    rules_paths = base.get("rules_paths")
    if destination == "skill-md":
        return _skill_trace(scope)
    if destination == "claude-md" and variant == "rules" and rules_paths:
        return _pathed_trace(scope, rules_paths)
    if destination == "claude-md":
        return _always_trace()
    if destination == "reference":
        return _demand_trace(scope)
    if destination == "hook":
        return _hook_trace(scope, base.get("alternates") or [])
    if destination == "new-skill":
        return _new_skill_trace(base.get("new_skill") or "probe-skill")
    return _always_trace()


def proposal_dict(*, scope: str = "skill:s", auto_trace: bool = True, **overrides) -> dict:
    """`auto_trace=False` opts a caller OUT of the default-trace
    attachment below — for `test_decision_trace.py`/`test_decision_table.py`
    only, which test the trace's OWN shape (including its absence under
    `TRACE_REQUIRED=False`) and shadow this function locally with that
    flag pinned off; every other caller wants the default."""
    base = {
        "destination": "skill-md",
        "alternates": ["claude-md"],
        "rationale": "deterministic guard beats advisory text",
        "already_canon": False,
        "already_canon_reason": "",
        "record_sha": "sha256:000000000000",
        "model": "claude-opus-4-8",
        "analyzed_at": "2026-07-13T00:00:00Z",
    }
    base.update(overrides)
    if auto_trace and "gates" not in overrides:
        base.update(default_trace_for(base, scope))
    return base


def hook_proposal_fields() -> dict:
    """The M3 hook-destination extension (02 §1): a ``destination: hook``
    proposal must carry the structured compile input + replay examples."""
    return {
        "hook": {
            "tools": ["Edit", "Write"],
            "path_regex": r"\.storage/",
            "deny_message": "stop the HA container first",
        },
        "examples": {
            "allow": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/config.yaml"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
            ],
            "deny": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/a"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/b"}},
            ],
        },
    }


def merge_proposal_text(cluster_id: str, records: list[str], survivor: str) -> str:
    shas = "\n".join(f"  {r}: sha256:000000000000" for r in records)
    ids = ", ".join(records)
    return (
        f"cluster_id: {cluster_id}\n"
        f"records: [{ids}]\n"
        f"suggested_survivor: {survivor}\n"
        f"rationale: same lesson twice\n"
        f"record_shas:\n{shas}\n"
        f"model: claude-sonnet-5\n"
        f"analyzed_at: 2026-07-13T02:10:00Z\n"
    )
