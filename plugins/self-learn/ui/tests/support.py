"""Shared test helpers for the U2 ledger/model suite.

Mirrors the CLI package's own ``tests/support.py`` fixture shape (doc 13
sandbox: an independent ledger home + one paired host repo) — deliberately
NOT imported cross-package (ui tests never reach into the cli package's
tests/ dir); this is a small, self-contained port of just what U2 needs.

10 §0 rules 7/8: every helper here builds THROWAWAY repos under pytest
tmpdirs and returns an explicit env mapping tests thread through
``self_learn_ui.ledger``'s ``env=`` parameter — nothing here ever touches
the real ``~/.self-learn``, ``~/.claude``, or the real XDG dirs.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from self_learn.ledger_ops import (
    LedgerOpsError,
    create_record,
    find_record_path,
    remove_proposal_siblings,
    write_proposal,
)
from self_learn.records import Record

from self_learn_ui.runner import FakeRunner, RunResult

# ------------------------------------------------------------------ git


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")


def commit_all(repo: Path, message: str = "seed") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


# ------------------------------------------------- ledger home + host repo

SKILL_MD_SEED = "# {name} skill\n\nAuthored prose stays put.\n"
CLAUDE_MD_SEED = "# host project\n\nAuthored context stays put.\n"


@dataclass
class SandboxEnv:
    ledger: Path
    host: Path
    skill_dir: Path
    skill_md: Path
    env: dict[str, str]


def make_env(tmp_path: Path, *, skills: tuple[str, ...] = ("s",)) -> SandboxEnv:
    """Build a ledger home + paired host repo (registered as BOTH skills
    root and project host), and an explicit env mapping
    (``XDG_CACHE_HOME``/``XDG_RUNTIME_DIR``/``SELF_LEARN_HOME`` redirected
    under *tmp_path*) ready to pass as ``env=`` to any ``ledger.py`` call
    — never mutates ``os.environ``."""
    host = tmp_path / "host-repo"
    init_repo(host)
    first = skills[0] if skills else "s"
    skill_dir = host / "plugins" / f"{first}-plugin" / "skills" / first
    for name in skills:
        d = host / "plugins" / f"{name}-plugin" / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(SKILL_MD_SEED.format(name=name), encoding="utf-8")
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

    cache_home = tmp_path / "cache"
    runtime_dir = tmp_path / "runtime"
    cache_home.mkdir()
    runtime_dir.mkdir()

    env = dict(os.environ)
    env["XDG_CACHE_HOME"] = str(cache_home)
    env["XDG_RUNTIME_DIR"] = str(runtime_dir)
    env["SELF_LEARN_HOME"] = str(ledger)

    return SandboxEnv(
        ledger=ledger,
        host=host,
        skill_dir=skill_dir,
        skill_md=skill_dir / "SKILL.md",
        env=env,
    )


def bare_ledger(tmp_path: Path) -> Path:
    """A ledger home with the layout dirs but NO hosts.yaml — the
    'nothing registered' state (matches a foreign/unregistered bucket)."""
    home = tmp_path / "bare-ledger"
    init_repo(home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()
    return home


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
    source: str = "teach",
) -> Record:
    return Record.create(
        type="behavior",
        scope=scope,
        source=source,
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
    source: str = "teach",
) -> Record:
    return Record.create(
        type="knowledge",
        scope=scope,
        source=source,
        fact=fact,
        record_id=record_id,
        created_at=created_at,
    )


def seed_record(ledger: Path, record: Record, *, project_path: Path | None = None) -> Path:
    return create_record(ledger, record, project_path=project_path)


def resolve_record_directly(
    ledger: Path,
    bucket_dir: Path,
    record: Record,
    *,
    destination: str | None = None,
    status: str = "routed",
    by: str = "human",
) -> None:
    """Move a pending record's file straight to resolved/, bypassing the
    real verb (no git commit needed) — enough to exercise the
    resolved-elsewhere READ path (09 §11 P1-9c), which only cares that
    the record's status is no longer pending/deferred, AND the U9
    bulk-loop-resume idempotency check (10 §5 playbook: "re-running the
    bulk row is idempotent — already-resolved ids vanish from the
    group"). The default destination derives from the record's scope
    (skill-md for skill:*, else claude-md — the CLI's own scope rules)
    so fixtures never mint routing states the route verb could not have
    produced (review 2026-07-18 flag).

    ``by`` (FW-64, defaulted "human" for byte-identical behaviour on
    every pre-existing caller): the hardcoded "human" literal this
    fixture used to bake in unconditionally is exactly why the UI's
    `routing.by` defect survived as long as it did — no test could even
    ASSERT a different value without editing this helper. A test that
    cares about `by` now passes it explicitly."""
    if destination is None:
        destination = "skill-md" if record.scope.startswith("skill:") else "claude-md"
    record.set_status(status)
    if status == "routed":
        record.set_routing(
            {"routed_at": "2026-07-01T00:00:00Z", "destination": destination, "by": by}
        )
    dest_path = bucket_dir / "resolved" / f"{record.id}.md"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    record.write(dest_path)
    pending_path = bucket_dir / "pending" / f"{record.id}.md"
    pending_path.unlink(missing_ok=True)


# -------------------------------------------------------------- proposals
#
# S-26 (U-composer's decision-trace flip, ledger_ops.TRACE_REQUIRED):
# `write_proposal` now REFUSES a proposal missing `gates`/`flags`/
# `recommendation`, and (once `gates` is present) re-derives
# `gates.outcome`/`recommendation` from the record's REAL scope
# (U-table's Table-1/Render-1) and refuses a mismatch. Every fixture
# proposal in this suite must therefore carry a Table-1-consistent
# trace for whatever destination/variant/scope it requests — this is a
# small, self-contained PORT of the CLI package's own
# `tests/support.py` trace-derivation helpers (`_base_gate_answers`
# through `default_trace_for`), not an import: this file's own
# docstring already rules out reaching into the CLI package's tests/
# dir, and that discipline stays even though this block's LOGIC must
# now track the CLI twin's. If the CLI twin's mapping changes, this one
# needs the same edit made twice.
#
# The roster-sha these traces carry is a well-shaped DUMMY
# (`sha256:000000000000`) — safe here because `write_proposal`/
# `validate_proposal` alone never check a roster-sha's VALUE against a
# real composed roster (X3 checks only its SHAPE); the honesty check
# U-composer added lives in `worker._validate_written`/`analyst.analyze`,
# neither of which any UI fixture exercises.

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
    suite's fixtures actually use. A TRAILING `/**` is a special case
    (`_compile_glob_pattern` treats a final `**` as `.*` preceded by a
    FORCED `/` separator) — append a synthetic trailing segment so the
    sample lands past that forced separator."""
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
    destination — and a caller's `alternates` override varies by test
    (`skill-md`, `claude-md`, `reference`, …), so the underlying load
    class must be picked to MATCH whichever destination the caller
    actually asked for, not a fixed one."""
    gates = _base_gate_answers()
    gates["t1"] = {
        "attempted": True,
        "field_shaped": {"answer": "yes", "evidence": _RECORD_QUOTE},
        "separable": {"answer": "yes", "evidence": _RECORD_QUOTE},
        "cost_bearing": {"answer": "yes", "evidence": _RECORD_QUOTE},
    }
    owner = scope.partition(":")[2] if scope.startswith("skill:") else None
    if "skill-md" in alternates and owner is not None:
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
        gates["t4"] = None
    elif "reference" in alternates:
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
        gates["tn"] = {
            "answer": "yes",
            "terms": ["probe", "terms"],
            "members": ["lrn-aaaaaaaa", "lrn-bbbbbbbb"],
            "proposed_name": "probe-skill",
        }
        gates["t4"] = None
    else:
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
    """``auto_trace=False`` opts a caller OUT of the default-trace
    attachment below, for a fixture that deliberately needs a trace-less
    proposal (S-26's own refusal behaviour) — every other caller wants
    the default. ``scope`` picks the Table-1-consistent trace to attach
    and MUST match the real scope of the record this proposal is written
    beside, or `write_proposal`'s own derivation check refuses the
    mismatch (measured while wiring this in: U-demand-user's merged-in
    fixtures that never needed to say `scope=` before this flip)."""
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


def seed_proposal(ledger: Path, record_id: str, **overrides) -> Path:
    return write_proposal(ledger, record_id, proposal_dict(**overrides))


def seed_raw_proposal(ledger: Path, record_id: str, data: dict) -> Path:
    """Write a proposal sibling WITHOUT going through `write_proposal`'s
    validation — for the rare fixture that deliberately needs a
    Table-1-INCONSISTENT proposal (e.g. `TestDestinationCorrection`'s
    stale `destination: skill-md` at project scope, which the real CLI
    pipeline can no longer produce post-S-26/U-table, but which the UI
    must still render defensively for legacy/malformed data already on
    disk). Never use this to route around a fixture that is merely
    missing `scope=` — that is `proposal_dict`'s own job; this is only
    for a proposal `write_proposal` would refuse on purpose."""
    from ruamel.yaml import YAML

    record_path = find_record_path(ledger, record_id)
    path = record_path.parent.parent / "proposals" / f"{record_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    import io

    buf = io.StringIO()
    yaml.dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


# ------------------------------------------------------ U-C3 regression
#
# The live-trial defect (09 §4/11 §2.4 Y-8): the real `route` CLI deletes
# the record's proposal sibling as part of resolving it
# (self_learn.ledger_ops.resolve_record -> remove_proposal_siblings, 08
# §1) — a PLAIN FakeRunner never reproduces this (it only records argv),
# which is exactly why the original Y-8 offer test passed against a UI
# handler that read `contradicts` AFTER runner.run() while production
# never rendered the offer at all (mock theater). This runner calls the
# REAL removal function — the same one the live CLI subprocess runs —
# so any route test built on it fails the instant a handler goes back to
# a post-dispatch read.


class RouteSideEffectRunner(FakeRunner):
    """FakeRunner + the one real side effect that broke Y-8 in
    production: a ``route`` call deletes the record's proposal
    sibling(s) via the actual :func:`remove_proposal_siblings`, exactly
    as the real CLI subprocess does at resolution. Every other verb
    behaves like a plain FakeRunner (argv recorded, queued/default
    result returned, no file touched)."""

    def __init__(self, ledger_home: Path, *, default: RunResult | None = None) -> None:
        super().__init__(default=default)
        self._home = ledger_home

    async def run(self, argv: list[str]) -> RunResult:
        result = await super().run(argv)
        if len(argv) >= 2 and argv[0] == "route":
            record_id = argv[1]
            try:
                path = find_record_path(self._home, record_id)
            except LedgerOpsError:
                path = None
            if path is not None:
                remove_proposal_siblings(self._home, path.parent.parent, record_id)
        return result


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


# ---------------------------------------------------- Y-15 client context
#
# The non-blocking pane start (09 §4.2 Y-15) drains the first turn as a
# background task on the APP's event loop. A bare TestClient runs every
# request on a throwaway per-request loop, which would destroy that task
# mid-flight — so route tests that touch panes enter the client's
# lifespan context (ONE persistent portal/loop per test) via the autouse
# stack conftest.py arms, and join turns deterministically through that
# same portal.

CLIENT_STACK = None  # armed per-test by conftest._client_contexts


def enter_client(client):
    """Enter *client*'s lifespan/portal context for the current test —
    required for any client whose requests spawn pane drains (Y-15)."""
    if CLIENT_STACK is None:
        raise RuntimeError("enter_client() used outside a test")
    return CLIENT_STACK.enter_context(client)


def join_pane_turn(client, manager) -> None:
    """Deterministic join on the background first turn
    (:meth:`PaneManager.wait_for_turn`) on the client's own loop."""
    assert client.portal is not None, "join_pane_turn needs an entered client"
    client.portal.call(manager.wait_for_turn)
