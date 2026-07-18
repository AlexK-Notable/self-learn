"""self-learn CLI — argparse skeleton (T1) + real `status`/`list` (T3) +
`teach` (T5) + resolution verbs / `push` / `sentinel` (T7 functions, wired
at T8) + `import`/`prune-memory` (T9 modules, wired at T11) +
`proposal validate` and the real `--selftest` (T11; the validate verb is
08 §7.1's pull-forward from T13 — all its logic already existed).

`status` and `list` compute over the shared queue/eligibility functions in
ledger_ops (08 §1 `--json`-stubs pin incl. the G-3 hardening; §7.1 step 2 /
P2-4). `teach` lives in :mod:`self_learn.teach`; the verbs are thin
wrappers over :mod:`self_learn.verbs`; validate + selftest live in
:mod:`self_learn.selfcheck`.

Verb exit codes (T7's mapping, surfaced here): 0 success · a verb refusal
carries its exception's ``exit_code`` (``VerbError`` 1;
``SecretRefusal`` 1 — P2-7 refusal; all five destinations compile as of
M3 — the old ``DestinationNotBuilt`` 2 is gone) · unknown /
malformed record id (``LedgerOpsError``) and every other usage error 64
(EX_USAGE — audit 2026-07-14: never 2, which P2-8 pins for scan hits) · a
push failure after a kept commit exits with the push result's code
(``EXIT_PUSH_FAILED`` 3, ``EXIT_REBASE_CONFLICT`` 4 — gitops). `proposal
validate` has its own pinned trio (P2-8): 0 valid+stamped · 1
schema-invalid · 2 scan hit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from . import report as report_mod
from . import hosts as hosts_mod
from . import reconcile as reconcile_mod
from . import gitops, miner, selfcheck, sentinel, telemetry, verbs, worker
from .chezmoi import ChezmoiAbort, ChezmoiError
from .compilers import CompileError
from .import_backlog import import_backlog
from .import_common import ImporterError
from .import_memory import import_memory, prune_memory
from .gitops import EXIT_GIT_FAILED
from .ledger import (
    EXIT_NO_HOME,
    discover_buckets,
    home_state,
    home_state_message,
    resolve_home,
)
from .ledger_ops import (
    LedgerOpsError,
    find_record_path,
    list_items,
    open_followups,
    status_infos,
    unparseable_pending,
)
from .records import Record, RecordError
from .teach import add_teach_parser, run_teach
from .telemetry import DECLINE_REASONS

EXIT_OK = 0
# 64 = sysexits EX_USAGE — deliberately NOT 2, which P2-8 pins as the
# proposal-validate scan-hit code (audit 2026-07-14: machine consumers must
# never see usage errors aliased onto scan hits). argparse's own flag-error
# exit stays 2 but cannot occur on a well-formed programmatic invocation.
EXIT_USAGE = 64

#: Re-exported (defined in :mod:`self_learn.ledger` / :mod:`self_learn.
#: gitops`, beside the concepts they name) so every surface — including
#: `teach`, which used to pin its own — returns the SAME integer.
#: EXIT_NO_HOME 5: the home is missing / not a git repo (BLOCKER 11).
#: EXIT_GIT_FAILED 6: a GitOpsError reached dispatch (BLOCKER B).

#: The auto-memory location for THIS repo (08 §3 T9/T11; MEMORY.md + topic
#: files). Env-overridable; tests always override — the real dir is never
#: resolved under pytest.
DEFAULT_MEMORY_DIR = "~/.claude/projects/-home-komi-repos-claude-skills/memory"


def default_memory_dir() -> Path:
    """`import --memory` / `prune-memory` dir default: env override first."""
    env = os.environ.get("SELF_LEARN_MEMORY_DIR")
    return Path(env if env else DEFAULT_MEMORY_DIR).expanduser()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="self-learn",
        description="Git-backed lesson ledger: capture, triage, route (M1).",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run installation self-checks (loud PASS/FAIL, non-zero on FAIL)",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    status = sub.add_parser("status", help="show bucket/pending overview")
    status.add_argument("--json", action="store_true", dest="as_json")
    status.add_argument(
        "--fast",
        action="store_true",
        help="pending/-only frontmatter scan, no git (SessionStart budget; "
        "implies --json; excludes follow-up counts — 08 §7.1)",
    )

    list_p = sub.add_parser("list", help="list queued records")
    list_p.add_argument("--json", action="store_true", dest="as_json")
    list_p.add_argument(
        "--include-deferred",
        action="store_true",
        dest="include_deferred",
        help="superset: also show records whose deferred_until is in the future",
    )

    add_teach_parser(sub)

    def _verb(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--note", metavar="TEXT", help="resolution note → commit body")
        p.add_argument(
            "--no-push",
            action="store_true",
            dest="no_push",
            help="commit exactly as pinned, skip only the push",
        )
        return p

    route = _verb("route", "route a pending record into canon")
    route.add_argument("id", metavar="ID")
    route.add_argument(
        "--dest",
        metavar="TARGET",
        help="override the proposal: skill-md | claude-md | "
        "reference[:<file>] | new-skill:<name> | hook (needs a hook "
        "proposal)",
    )
    route.add_argument(
        "--collapse",
        metavar="CLUSTER_ID",
        help="collapse a merge cluster into this survivor (one commit; "
        "losers superseded — 08 §7.1 Merge-proposals pin)",
    )
    route.add_argument(
        "--follow-up",
        dest="follow_up",
        metavar="ACTION",
        help="known-partial coverage (11 §2.1): the planned upgrade, on the routing block",
    )
    route.add_argument(
        "--unblocks-on",
        dest="unblocks_on",
        metavar="GATE",
        help="with --follow-up: human-readable gate label (e.g. M3)",
    )
    route.add_argument(
        "--follow-up-note",
        dest="follow_up_note",
        metavar="TEXT",
        help="with --follow-up: why the strong form matters",
    )

    reject = _verb("reject", "reject a pending record")
    reject.add_argument("id", metavar="ID")

    defer = _verb("defer", "defer a pending record (default +30 d)")
    defer.add_argument("id", metavar="ID")
    defer.add_argument("--until", metavar="YYYY-MM-DD", help="explicit defer date")

    graduate = _verb("graduate", "mark a lesson graduated into authored canon")
    graduate.add_argument("id", metavar="ID")

    rehome = _verb(
        "rehome", "move a pending record to another registered project bucket"
    )
    rehome.add_argument("id", metavar="ID")
    rehome.add_argument(
        "--to",
        required=True,
        metavar="PATH_OR_SLUG",
        help="the registered project to move it to — its path or its "
        "bucket slug (project→project only; the target must already be "
        "in hosts.yaml — self-learn host add <path> registers it)",
    )

    supersede = _verb("supersede", "mark OLD superseded by NEW (metadata only)")
    supersede.add_argument("old_id", metavar="OLD_ID")
    supersede.add_argument("new_id", metavar="NEW_ID")

    cr = _verb(
        "confirm-recurrence",
        "confirm a recurrence suspect onto a routed record (11 §2.2)",
    )
    cr.add_argument("id", metavar="ID")
    cr.add_argument(
        "--event",
        required=True,
        metavar="NONCE",
        help="the recurrence-suspect telemetry event's nonce (see report)",
    )
    cr.add_argument(
        "--tolerate",
        action="store_true",
        help="the rule stays despite the recurrence (needs --note: the why)",
    )

    ch = _verb("confirm-held", "record that a routed rule was seen working")
    ch.add_argument("id", metavar="ID")

    link = sub.add_parser("link", help="record graph edges (11 §2.4)")
    link_sub = link.add_subparsers(dest="link_command", metavar="<edge>")
    lc = link_sub.add_parser(
        "contradicts", help="mark ID as contradicting TARGET (id or canon anchor)"
    )
    lc.add_argument("id", metavar="ID")
    lc.add_argument("target", metavar="TARGET")
    lc.add_argument("--note", metavar="TEXT", help="why → commit body")
    lc.add_argument(
        "--no-push", action="store_true", dest="no_push",
        help="commit exactly as pinned, skip only the push",
    )

    followup = sub.add_parser(
        "followup", help="follow-up lifecycle on routed records (11 §2.1)"
    )
    followup_sub = followup.add_subparsers(dest="followup_command", metavar="<verb>")
    fdone = followup_sub.add_parser(
        "done", help="clear an open follow-up into a dated follow_up_done block"
    )
    fdone.add_argument("id", metavar="ID")
    fdone.add_argument("--note", metavar="TEXT", help="done note → record + commit body")
    fdone.add_argument(
        "--no-push",
        action="store_true",
        dest="no_push",
        help="commit exactly as pinned, skip only the push",
    )

    telemetry_p = sub.add_parser(
        "telemetry", help="observation plane (11 §4): note (spool) | flush"
    )
    telemetry_sub = telemetry_p.add_subparsers(
        dest="telemetry_command", metavar="<verb>"
    )
    tnote = telemetry_sub.add_parser(
        "note",
        help="spool one offer-ledger event (cache-only — no repo write, no commit)",
    )
    tnote.add_argument(
        "kind", metavar="KIND", help="offer-made | offer-declined (model-emitted kinds)"
    )
    tnote.add_argument(
        "--reason",
        metavar="WHY",
        help=f"offer-declined only; closed enum: {' | '.join(DECLINE_REASONS)}",
    )
    telemetry_sub.add_parser(
        "flush", help="spool → tracked telemetry files (scan-at-flush; no commit)"
    )

    sub.add_parser(
        "report", help="facts layer v1 (11 §5): lifecycle + telemetry counts"
    ).add_argument("--json", action="store_true", dest="as_json")

    worker_p = sub.add_parser(
        "worker", help="background pre-analysis worker: kick | run (08 §7.1)"
    )
    worker_sub = worker_p.add_subparsers(dest="worker_command", metavar="<verb>")
    worker_sub.add_parser(
        "kick", help="mark dirty + open a coalescing window (absorbed if open)"
    )
    wrun = worker_sub.add_parser("run", help="one worker run (normally spawned)")
    wrun.add_argument(
        "--coalesce",
        action="store_true",
        help="sleep SELF_LEARN_COALESCE_SECS first (the kick-spawned form)",
    )

    mine_p = sub.add_parser(
        "mine", help="transcript miner: run | status (doc 12)"
    )
    mine_sub = mine_p.add_subparsers(dest="mine_command", metavar="<verb>")
    mrun = mine_sub.add_parser(
        "run", help="one mining pass over unread transcripts (timer/manual/kick)"
    )
    mrun.add_argument(
        "--trigger",
        choices=("timer", "manual", "kick"),
        default="manual",
        help="journal attribution for this run (default: manual)",
    )
    mrun.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="deliberate backfill: re-read transcripts modified on/after "
        "this date from line 0 (origin dedup makes replays safe)",
    )
    mstatus = mine_sub.add_parser(
        "status", help="last runs, outcomes, and staleness — from the journal"
    )
    mstatus.add_argument("--json", dest="as_json", action="store_true")

    sub.add_parser("push", help="publish pending local commits (pinned retry)")

    rec = sub.add_parser(
        "reconcile",
        help="commit ledger records/proposals a producer left uncommitted",
    )
    rec.add_argument(
        "--no-push", action="store_true", help="commit only; do not publish"
    )

    host_p = sub.add_parser(
        "host",
        help="compile-host registry (doc 13 §3): add | rebind | remove | list",
    )
    host_sub = host_p.add_subparsers(dest="host_command", metavar="<verb>")
    hadd = host_sub.add_parser(
        "add", help="register a repo canon may compile into (H-3)"
    )
    hadd.add_argument("path", metavar="PATH")
    hadd.add_argument(
        "--skills-root",
        action="store_true",
        dest="skills_root",
        help="register as THE skills root (plugins/*/skills/* live there) "
        "instead of a project host",
    )
    hadd.add_argument(
        "--init",
        action="store_true",
        dest="init",
        help="git init + an empty root commit at PATH first, when it is "
        "not already a repo root (09 §11 Y-17: existing directories "
        "only; no-op when PATH is already a root, zero-commit included; "
        "nested inside a parent work tree is intended)",
    )
    hrebind = host_sub.add_parser(
        "rebind",
        help="re-point a project bucket + its hosts.yaml entry at a MOVED "
        "repo (one ledger commit)",
    )
    hrebind.add_argument("ref", metavar="SLUG-OR-OLD-PATH")
    hrebind.add_argument("new_path", metavar="NEW-PATH")
    hrm = host_sub.add_parser(
        "remove", help="deregister a host (records and buckets are untouched)"
    )
    hrm.add_argument("path", metavar="PATH")
    host_sub.add_parser("list", help="show the registered hosts")

    recompile_p = sub.add_parser(
        "recompile",
        help="recompute every managed canon target from the ledger — the "
        "doc-13 drift repair (idempotent)",
    )
    recompile_p.add_argument(
        "--no-push",
        action="store_true",
        dest="no_push",
        help="commit host changes exactly as pinned, skip only the pushes",
    )

    sentinel_p = sub.add_parser(
        "sentinel", help="autosync-pause sentinel: hold | heartbeat | release"
    )
    sentinel_p.add_argument("action", choices=("hold", "heartbeat", "release"))

    imp = sub.add_parser(
        "import", help="one-shot importers: --backlog <skill> | --memory [<dir>]"
    )
    src = imp.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--backlog",
        metavar="SKILL",
        help="mine the skill's references/GOTCHAS.journal.md (journal ONLY)",
    )
    src.add_argument(
        "--memory",
        nargs="?",
        const="",
        metavar="DIR",
        help=f"import auto-memory topic files (default: {DEFAULT_MEMORY_DIR})",
    )

    prune = sub.add_parser(
        "prune-memory",
        help="S-13 sweep: remove memory files whose records reached a terminal status",
    )
    prune.add_argument("--dry-run", action="store_true", dest="dry_run")
    prune.add_argument("dir", nargs="?", default=None, metavar="DIR")

    proposal = sub.add_parser("proposal", help="proposal-sibling operations")
    proposal_sub = proposal.add_subparsers(dest="proposal_command", metavar="<verb>")
    validate = proposal_sub.add_parser(
        "validate",
        help="scan + schema-validate + stamp one record's proposal (0/1/2)",
    )
    validate.add_argument("id", metavar="ID")

    return parser


def _home_gate(home) -> int | None:
    """The read-surface home gate (audit 2026-07-16 BLOCKER 11): a
    missing / not-a-repo home is LOUD and non-zero — never a confident
    "0 pending, exit 0" for a ledger nobody can see. An initialized home
    with no records is a legitimate quiet zero (None → carry on); an
    uninitialized repo warns but still answers (it exists, and the first
    capture bootstraps its dirs).

    Returns an exit code to return immediately, or None to continue."""
    state = home_state(home)
    if state == "ok":
        return None
    print(f"self-learn: {home_state_message(state, home)}", file=sys.stderr)
    return None if state == "uninitialized" else EXIT_NO_HOME


def _warn_unparseable(home) -> None:
    """Unparseable pending files are excluded from the queue — never
    silently: name each one on stderr."""
    for bucket in discover_buckets(home):
        for path in unparseable_pending(bucket):
            print(
                f"self-learn: warning: skipping unparseable record {path}",
                file=sys.stderr,
            )


def _cmd_status_fast() -> int:
    """08 §7.1 SessionStart pin: guaranteed-cheap, pending/-only. The bash
    hook consumes this — queue semantics live HERE, never in bash. Doc 12
    R1 layer 3: the miner's staleness keys ride the same payload (two
    stats, still cheap).

    The hook jq-parses stdout, so stdout stays VALID JSON in every state
    (audit 2026-07-16 BLOCKER 11) — the home's state rides the payload as
    ``home_state`` and the hook prints the warning. A bad home also exits
    non-zero and says so on stderr, for humans and for any caller that
    checks."""
    home = resolve_home()
    state = home_state(home)
    if state != "ok":
        # Valid-JSON stdout FIRST (the hook's contract), then the loud line.
        print(
            json.dumps(
                {
                    "home_state": state,
                    "home": str(home),
                    "total_pending": 0,
                    "unanalyzed_total": 0,
                    "oldest_days": 0,
                    "staleness_alarm": False,
                    "escalate": False,
                    "miner_last_run": None,
                    "miner_stale": False,
                }
            )
        )
        print(f"self-learn: {home_state_message(state, home)}", file=sys.stderr)
        return EXIT_OK if state == "uninitialized" else EXIT_NO_HOME
    data = worker.fast_status(home)
    data["home_state"] = state
    data["miner_last_run"] = miner.last_run_iso()
    data["miner_stale"] = miner.stale()
    print(json.dumps(data))
    return EXIT_OK


def _cmd_mine(args: argparse.Namespace) -> int:
    home = resolve_home()
    if args.mine_command == "run":
        if args.since is not None:
            try:
                datetime.fromisoformat(args.since)
            except ValueError:
                print(
                    f"self-learn mine: --since needs YYYY-MM-DD, got {args.since!r}",
                    file=sys.stderr,
                )
                return EXIT_USAGE
        # The process boundary is read HERE, at the child's dispatch
        # surface, and travels as a parameter from here on (BLOCKER D).
        result = miner.run(
            home,
            trigger=args.trigger,
            since=args.since,
            no_push=worker.no_push_requested(),
        )
        print(
            f"mine run: {result.status} — {len(result.landed)} landed, "
            f"{len(result.folded)} folded, {len(result.recurrences)} "
            f"recurrence(s), {result.fires} fire(s)"
        )
        if result.status == "landed-uncommitted":
            # BLOCKER B (c): records written, commit failed, cursors gone.
            # Round 7 MAJOR 4: no longer data loss — name the recovery.
            print(
                "self-learn mine: candidates were written but NOT committed "
                "— run `self-learn reconcile` to commit them now; the next "
                "mine run reconciles them automatically. See `self-learn "
                "mine status` and the miner log.",
                file=sys.stderr,
            )
            return gitops.EXIT_HALF_WRITTEN
        return EXIT_OK if result.status != "failed" else 1
    if args.mine_command == "status":
        entries = miner.read_journal()
        if args.as_json:
            print(
                json.dumps(
                    {
                        "last_run": miner.last_run_iso(),
                        "stale": miner.stale(),
                        "runs": entries,
                    }
                )
            )
            return EXIT_OK
        last = miner.last_run_iso() or "never (on this machine)"
        print(f"miner last run: {last}" + ("  ⚠ STALE (>36h)" if miner.stale() else ""))
        if not entries:
            print("no journaled runs yet")
            return EXIT_OK
        for e in entries[-10:]:
            line = (
                f"{e.get('ts', '?')}  {e.get('status', '?'):9s} "
                f"trigger={e.get('trigger', '?')}"
            )
            # MINOR (audit 2026-07-16 round 7): the counts expanded for
            # "ok" ONLY, so a `landed-uncommitted` row rendered bare —
            # hiding the landed count on the one status where "how many
            # records are at risk?" is the question being asked. Both
            # statuses journal the same keys; both render them.
            if e.get("status") in ("ok", "landed-uncommitted"):
                line += (
                    f"  scanned={e.get('sessions_scanned', 0)} "
                    f"landed={e.get('landed', 0)} folded={e.get('folded', 0)} "
                    f"recurrences={e.get('recurrences', 0)} "
                    f"fires={e.get('fires', 0)} cap={e.get('cap', '?')}"
                )
            if e.get("status") == "landed-uncommitted":
                line += "  ⚠ uncommitted — `self-learn reconcile` commits them"
            elif e.get("status") == "held-gate":
                line += f"  pending={e.get('pending')} ≥ gate={e.get('gate')}"
            elif e.get("status") == "failed":
                line += f"  reason: {e.get('reason', '?')}"
            print(line)
            for o in e.get("outcomes", []) or []:
                extra = {
                    k: v
                    for k, v in o.items()
                    if k not in ("origin", "outcome") and v
                }
                suffix = f"  {extra}" if extra else ""
                print(f"    {o.get('outcome', '?'):22s} {o.get('origin', '?')}{suffix}")
        return EXIT_OK
    print("usage: self-learn mine run [--trigger …] [--since …] | mine status", file=sys.stderr)
    return EXIT_USAGE


def _cmd_worker(args: argparse.Namespace) -> int:
    home = resolve_home()
    if args.worker_command == "kick":
        outcome = worker.kick(home)
        print(f"worker kick: {outcome}")
        return EXIT_OK
    if args.worker_command == "run":
        result = worker.run(
            home, coalesce=args.coalesce, no_push=worker.no_push_requested()
        )
        n = len(result.proposed)
        print(
            f"worker run: {result.status} — {n} proposal(s), "
            f"{len(result.merge_proposed)} merge, {result.eligible} eligible,"
            f" {result.suspects} recurrence suspect(s)"
        )
        return EXIT_OK if result.status in ("ok", "idle") else 1
    print("usage: self-learn worker kick | worker run [--coalesce]", file=sys.stderr)
    return EXIT_USAGE


def _kick_after_capture(*, no_push: bool = False) -> None:
    """teach (without --route) and import end by calling worker kick
    (08 §7.1 trigger pin). Never fails the capture.

    ``no_push`` binds the SPAWNED worker to the invoking verb's
    ``--no-push`` (audit 2026-07-16 BLOCKER 3): the kicked worker is
    detached and commits + pushes at run end, and ``git push`` publishes the
    whole branch — so without this, ``teach --no-push`` wrote the record
    unpublished and the worker it kicked published it seconds later. See
    :func:`worker.no_push_requested` for the "not now, not never"
    semantics."""
    try:
        outcome = worker.kick(resolve_home(), no_push=no_push)
    except OSError as exc:
        print(f"self-learn: worker kick failed: {exc}", file=sys.stderr)
        return
    if outcome == "spawned":
        print("worker: analysis window opened", file=sys.stderr)


def _cmd_status(as_json: bool) -> int:
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    _warn_unparseable(home)
    infos = status_infos(home)
    total_pending = sum(i["pending"] for i in infos)
    # 11 §2.1: one line on the FULL status paths only — the future
    # `--json --fast` path stays a pending/-only scan (08 §7.1).
    followups = len(open_followups(home))

    if as_json:
        payload = {
            "buckets": infos,
            "total_pending": total_pending,
            "open_followups": followups,
            # 08 §7.1 amendment: iso8601 | null (null = never ran here)
            "worker_last_run": worker.last_run_iso(),
            # T19 (08 §8.1 O-3/O-7-revisit row): supply mix + the 04
            # success-metrics counters — FULL status only; the --fast
            # SessionStart path stays a pending/-only scan, no git.
            "supply_mix": report_mod.supply_mix(home),
            "metrics": report_mod.ledger_metrics(home),
        }
        print(json.dumps(payload))
        return EXIT_OK

    if not infos:
        print("self-learn: no buckets, 0 pending")
        return EXIT_OK

    plural = "s" if len(infos) != 1 else ""
    print(f"self-learn: {total_pending} pending across {len(infos)} bucket{plural}")
    for i in infos:
        age = "" if i["oldest_days"] is None else f", oldest {i['oldest_days']}d"
        print(
            f"  {i['bucket']} ({i['scope']}): {i['pending']} pending, "
            f"{i['unanalyzed']} unanalyzed{age}"
        )
    if followups:
        plural = "s" if followups != 1 else ""
        print(
            f"  {followups} open follow-up{plural} (`self-learn report` lists them)"
        )
    return EXIT_OK


def _proposal_cell(item: dict) -> str:
    if not item["has_proposal"]:
        return "-"
    return "fresh" if item["proposal_fresh"] else "stale"


def _cmd_list(as_json: bool, include_deferred: bool) -> int:
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    _warn_unparseable(home)
    items = list_items(home, include_deferred=include_deferred)

    if as_json:
        print(json.dumps(items))
        return EXIT_OK

    if not items:
        print("self-learn: 0 records")
        return EXIT_OK

    print(
        f"{'ID':<13} {'AGE':>4} {'STATUS':<9} {'TYPE':<9} "
        f"{'PROPOSAL':<8} {'SCOPE':<22} TITLE"
    )
    for i in items:
        print(
            f"{i['id']:<13} {str(i['age_days']) + 'd':>4} {i['status']:<9} "
            f"{i['type']:<9} {_proposal_cell(i):<8} {i['scope']:<22} {i['title']}"
        )
    return EXIT_OK


# ------------------------------------------------------- verb wiring (T8)


def push_note(result: verbs.VerbResult) -> str:
    """The push half of a verb's one-line summary — BOTH phases (audit
    2026-07-16 MAJOR 4): ``VerbResult.host_push`` was set by every
    canon-touching verb and read by nobody, so a failed HOST push printed
    "(pushed)" and exited 0 — the canon commit sat unpublished with no
    sign anything was wrong.

    A clean two-phase route still reads "(pushed)": one word, both repos.
    Anything else is spelled out per phase."""
    ledger = _phase_note(result.push)
    if result.host_push is None:
        return ledger
    host = _phase_note(result.host_push)
    if ledger == host == "pushed":
        return "pushed"  # ledger + host, both clean
    return f"ledger {ledger}; host {host}"


def _phase_note(push: gitops.PushResult | None) -> str:
    if push is None:
        return "not pushed — --no-push"
    if push.skipped:
        return "not pushed — no remote configured"
    if push.ok:
        return "pushed"
    return "PUSH FAILED — commit kept; run `self-learn push`"


def _finish_verb(result: verbs.VerbResult, target: str) -> int:
    """One-line success summary: id, action, target, short sha, push state
    (ledger AND host). Exit 0, or the distinct push-failure code — a HOST
    push failure counts exactly like a ledger one (MAJOR 4).

    A hook route carries the ENTIRE generated script as ``diff`` (08 §8.1
    approval flow — never a summary) and the required manual steps as
    ``post_notes`` (M3-11): both print here, script first."""
    if result.diff:
        print(result.diff)
    print(
        f"{result.action} {result.record_id} → {target} "
        f"@ {result.commit_sha[:7]} ({push_note(result)})"
    )
    for note_line in result.post_notes:
        print(note_line)
    for warning in result.warnings:
        print(warning, file=sys.stderr)
    if (note := result.over_cap_note()) is not None:
        print(note, file=sys.stderr)
    for push in (result.push, result.host_push):
        if push is not None and not push.ok:
            return push.exit_code
    return EXIT_OK


def _routed_destination(result: verbs.VerbResult) -> str:
    # The pinned commit subject is "self-learn: route lrn-… → <target>…";
    # the target after the arrow is authoritative (proposal or --dest).
    return result.commit_message.split("→", 1)[1].strip().split(" ")[0]


def _cmd_verb(args: argparse.Namespace) -> int:
    """Home-gated like every other surface (doc 13 B-11). Two reasons, one
    line: a bad home used to reach ``find_record_path`` and come back "no
    such record lrn-…" — blaming the ID for a home nobody could see; and
    since BLOCKER 4 the verbs take a commit lock on the ledger, which for a
    missing / not-a-repo home raises GitOpsError — an uncaught traceback
    (found 2026-07-16 by running the verbs against a missing home; the
    suite never did, so it stayed green through both)."""
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    try:
        if args.command == "route":
            follow_up = None
            if args.follow_up is not None:
                follow_up = {"action": args.follow_up}
                if args.unblocks_on is not None:
                    follow_up["unblocks_on"] = args.unblocks_on
                if args.follow_up_note is not None:
                    follow_up["note"] = args.follow_up_note
            elif args.unblocks_on is not None or args.follow_up_note is not None:
                print(
                    "self-learn route: --unblocks-on/--follow-up-note need "
                    "--follow-up",
                    file=sys.stderr,
                )
                return EXIT_USAGE
            result = verbs.route(
                home,
                args.id,
                dest=args.dest,
                note=args.note,
                no_push=args.no_push,
                follow_up=follow_up,
                collapse=args.collapse,
            )
            return _finish_verb(result, _routed_destination(result))
        if args.command == "reject":
            result = verbs.reject(home, args.id, note=args.note, no_push=args.no_push)
            return _finish_verb(result, "rejected")
        if args.command == "defer":
            until = None
            if args.until is not None:
                try:
                    until = date.fromisoformat(args.until)
                except ValueError:
                    print(
                        f"self-learn defer: --until must be YYYY-MM-DD, "
                        f"got {args.until!r}",
                        file=sys.stderr,
                    )
                    return EXIT_USAGE
            result = verbs.defer(
                home, args.id, until=until, note=args.note, no_push=args.no_push
            )
            # pinned subject: "self-learn: defer lrn-… until <date>"
            until_str = result.commit_message.rsplit(" until ", 1)[1]
            return _finish_verb(result, f"deferred until {until_str}")
        if args.command == "graduate":
            result = verbs.graduate(
                home, args.id, note=args.note, no_push=args.no_push
            )
            return _finish_verb(result, "canon")
        if args.command == "rehome":
            result = verbs.rehome(
                home, args.id, to=args.to, note=args.note, no_push=args.no_push
            )
            # pinned subject: "self-learn: rehome lrn-… → projects/<slug>"
            return _finish_verb(result, _routed_destination(result))
        if args.command == "supersede":
            result = verbs.supersede(
                home,
                args.old_id,
                args.new_id,
                note=args.note,
                no_push=args.no_push,
            )
            return _finish_verb(result, args.new_id)
        if args.command == "confirm-recurrence":
            result = verbs.confirm_recurrence(
                home,
                args.id,
                event_ref=args.event,
                tolerate=args.tolerate,
                note=args.note,
                no_push=args.no_push,
            )
            return _finish_verb(result, "recurrence confirmed")
        if args.command == "confirm-held":
            result = verbs.confirm_held(
                home, args.id, note=args.note, no_push=args.no_push
            )
            return _finish_verb(result, "confirmed holding")
    except verbs.VerbError as exc:  # incl. SecretRefusal
        print(f"self-learn {args.command}: {exc}", file=sys.stderr)
        return exc.exit_code
    except LedgerOpsError as exc:  # unknown/malformed id, proposal trouble
        print(f"self-learn {args.command}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (CompileError, ChezmoiAbort, ChezmoiError) as exc:
        # broken markers / user-scope chezmoi aborts: refused, nothing lost
        print(f"self-learn {args.command}: {exc}", file=sys.stderr)
        return 1
    except gitops.HalfWrittenError as exc:
        # The commit itself failed, AFTER resolve_record moved the record.
        # Probed 2026-07-16 (round 7 BLOCKER 2): this used to take the
        # branch below and exit 6 — whose documented meaning is "refused
        # BEFORE writing, safe to retry" — over a record that had ALREADY
        # moved pending→resolved; the documented retry then failed 64
        # "record not found". Same exception, same code, opposite state.
        return _report_half_written(args.command, exc)
    except gitops.GitOpsError as exc:
        # A lock timeout / wedged git / unwritable repo, raised BEFORE the
        # first mutation. Probed 2026-07-16 (BLOCKER B): a second process
        # merely HOLDING the commit lock made reject/push/recompile die
        # with an uncaught traceback. The "nothing was written" claim this
        # code carries is safe by construction — and only because the lock
        # is taken before the first mutation and every post-mutation git
        # failure is re-raised as HalfWrittenError above.
        print(f"self-learn {args.command}: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED
    raise AssertionError(f"unhandled verb {args.command!r}")  # pragma: no cover


def _cmd_host(args: argparse.Namespace) -> int:
    """The ``host`` surface. Audit 2026-07-16 round 7 BLOCKER 1: this was
    the ONE dispatch surface with no ``GitOpsError`` catch — probed, `host
    rebind` against a merely-held lock exited 1 with a traceback. It is
    home-gated for the same reason ``_cmd_verb`` is (a missing home makes
    ``commit_lock_path`` raise), and every git failure now lands on the
    same two documented codes as every other verb."""
    home = resolve_home()
    if args.host_command in ("add", "rebind", "remove") and (
        (code := _home_gate(home)) is not None
    ):
        return code
    try:
        return _cmd_host_inner(args, home)
    except gitops.HalfWrittenError as exc:
        return _report_half_written(f"host {args.host_command}", exc)
    except gitops.GitOpsError as exc:  # lock timeout / wedged git: nothing written
        print(f"self-learn host {args.host_command}: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED


def _report_half_written(surface: str, exc: gitops.HalfWrittenError) -> int:
    """The ONE renderer for :data:`EXIT_HALF_WRITTEN` (round 7 BLOCKER 2).

    A surface may not report this state without printing the repair — so
    printing it is not left to each surface's discretion, it is this
    function, and the exception type is what forces the call."""
    print(
        f"self-learn {surface}: WRITE NOT COMMITTED ({exc})\n"
        "  The ledger IS mutated — this is NOT a clean refusal and a blind "
        "retry is not safe.\n"
        f"  Repair: {exc.repair}",
        file=sys.stderr,
    )
    return gitops.EXIT_HALF_WRITTEN


def _cmd_host_inner(args: argparse.Namespace, home) -> int:
    if args.host_command == "add":
        kind = "skills-root" if args.skills_root else "project"
        try:
            registry = hosts_mod.host_add(home, args.path, kind, init=args.init)
        except hosts_mod.HostsError as exc:
            print(f"self-learn host add: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"host add: {kind} {Path(args.path).expanduser().resolve()}")
        print(
            f"  registry: skills_root={registry.skills_root or '(none)'} · "
            f"{len(registry.projects)} project host(s)"
        )
        # 09 §11 Y-2 companion (10 U0): registration is a consent moment —
        # name the consequence, don't leave it implicit.
        print(
            "  consent: registers this repo's canon surfaces as compile "
            "targets and analyst-readable"
        )
        return EXIT_OK
    if args.host_command == "rebind":
        try:
            bucket = hosts_mod.host_rebind(home, args.ref, args.new_path)
        except (hosts_mod.HostsError, LedgerOpsError) as exc:
            print(f"self-learn host rebind: {exc}", file=sys.stderr)
            return EXIT_USAGE
        target = Path(args.new_path).expanduser().resolve()
        print(f"host rebind: {args.ref} → {target}")
        print(f"  bucket: {bucket}")
        return EXIT_OK

    if args.host_command == "remove":
        try:
            registry = hosts_mod.host_remove(home, args.path)
        except hosts_mod.HostsError as exc:
            print(f"self-learn host remove: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"host remove: {Path(args.path).expanduser().resolve()}")
        print(
            f"  registry: skills_root={registry.skills_root or '(none)'} · "
            f"{len(registry.projects)} project host(s)"
        )
        print("  the bucket and its records are untouched — only the "
              "compile gate closed")
        return EXIT_OK

    if args.host_command == "list":
        try:
            registry = hosts_mod.load_hosts(home)
        except hosts_mod.HostsError as exc:
            print(f"self-learn host list: {exc}", file=sys.stderr)
            return 1
        # `list` stays lenient and SHOWS a broken entry marked broken —
        # exploding on a bad entry hides exactly the thing you ran `list`
        # to find (MAJOR 6). The canon-writing gates are what refuse.
        print(f"skills_root: {_host_line(home, registry.skills_root, 'skills-root')}")
        if registry.projects:
            print("projects:")
            for p in registry.projects:
                print(f"  - {_host_line(home, p, 'project')}")
        else:
            print("projects: (none registered)")
        return EXIT_OK
    print(
        "usage: self-learn host add <path> [--skills-root] | "
        "host rebind <slug-or-old-path> <new-path> | host remove <path> | "
        "host list",
        file=sys.stderr,
    )
    return EXIT_USAGE


def _host_line(home, path, kind: str) -> str:
    """One registry line, with any gate problem spelled out inline."""
    if path is None:
        return "(none registered)"
    problem = hosts_mod.host_path_problem(home, path, kind)
    return str(path) if problem is None else f"{path}  ⚠ BROKEN — {problem}"


def _cmd_recompile(args: argparse.Namespace) -> int:
    """Audit 2026-07-16 MAJOR 5: recompile had no home gate, so against a
    missing home it printed "no managed targets (no routed records)" and
    exited 0 — the ADVERTISED drift repair telling a user whose canon is
    actually adrift that all is well. It is the loudest possible place for
    B-11's silent all-clear: the drift warning names this command, so a
    confident zero here ends the trail."""
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    try:
        result = verbs.recompile(home, no_push=args.no_push)
    except gitops.GitOpsError as exc:  # BLOCKER B: never a traceback
        print(f"self-learn recompile: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED
    for warning in result.warnings:
        print(f"recompile: WARNING {warning}", file=sys.stderr)
    if not result.entries:
        print("recompile: no managed targets (no routed records)")
        return EXIT_OK
    for entry in result.entries:
        if entry.skipped:
            state = f"skipped ({entry.skipped})"
        elif entry.changed and entry.commit_sha:
            state = f"recompiled @ {entry.commit_sha[:7]}"
        elif entry.changed:
            # the chezmoi user flow commits its own repo — no host sha
            state = "recompiled (dotfiles repo committed)"
        else:
            state = "up to date"
        print(f"recompile: {entry.target} — {state}")
    return EXIT_OK


def _cmd_push() -> int:
    """Publish the ledger AND every registered host with unpushed commits
    (MAJOR 4: the host half had no retry path — this verb was ledger-only,
    so the command the failure message names could not fix it).

    Home-gated (audit 2026-07-16 MAJOR 5): on a missing / not-a-repo home
    this died with an uncaught GitOpsError traceback — a stack trace where
    every other push failure in this CLI is a plain sentence naming the
    fix."""
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    try:
        # Round 7 MAJOR 4: publishing a ledger whose records were never
        # committed is the moment the H-5 gap is most visible — `push` is
        # what a human runs when something went wrong, so it heals first.
        # Cheap and idempotent on a clean ledger (one `git status`).
        healed = reconcile_mod.reconcile(home, no_push=True)
        if healed.healed:
            print(
                f"push: reconciled {len(healed.committed)} orphaned record(s) "
                "first (a producer wrote them but could not commit them)"
            )
        report = verbs.push_pending(home)
    except gitops.HalfWrittenError as exc:
        return _report_half_written("push", exc)
    except gitops.GitOpsError as exc:  # BLOCKER B: never a traceback
        print(f"self-learn push: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED
    for repo, result in report.entries:
        state = "ok" + (" (after rebase-retry)" if result.retried else "")
        if not result.ok:
            state = "FAILED"
        print(f"push: {repo} — {state}")
    if report.ok:
        return EXIT_OK
    # gitops already printed the loud warning; exit with the distinct code.
    return report.exit_code


def _cmd_reconcile(args: argparse.Namespace) -> int:
    """``self-learn reconcile`` (round 7 MAJOR 4): commit what a producer
    wrote and could not commit. See :mod:`self_learn.reconcile` for why
    "reported honestly" was not the same as "recovered"."""
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    try:
        result = reconcile_mod.reconcile(home, no_push=args.no_push)
    except gitops.HalfWrittenError as exc:
        return _report_half_written("reconcile", exc)
    except gitops.GitOpsError as exc:
        print(f"self-learn reconcile: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED
    for line in result.blocked:
        print(
            f"reconcile: NOT touched — {line}\n"
            "  a staged rename/deletion is a half-committed resolution; "
            "reconcile never commits one half of a `git mv` (it would leave "
            "the record in pending/ AND resolved/). Use the repair command "
            "the verb printed.",
            file=sys.stderr,
        )
    if not result.committed:
        print("reconcile: nothing uncommitted — the ledger is whole")
        return EXIT_OK
    # ReconcileResult.sha is str | None by field default, but every path
    # that reaches here (committed non-empty) came through a successful
    # gitops.commit(), which always returns a str — sha is None here only
    # if that invariant is ever broken, and this must stay loud, not crash
    # a report of an otherwise-successful commit.
    sha_display = result.sha[:7] if result.sha is not None else "(sha unknown)"
    print(
        f"reconcile: committed {len(result.committed)} orphaned path(s) "
        f"@ {sha_display}"
    )
    for path in result.committed:
        print(f"  {path}")
    if result.push is not None and not result.push.ok:
        return result.push.exit_code
    return EXIT_OK


def _cmd_sentinel(action: str) -> int:
    path = sentinel.sentinel_path()
    if action == "hold":
        hold = sentinel.hold()
        if hold.owned:
            print(f"sentinel held: {path}")
        else:
            print(f"sentinel already held (live) — left in place: {path}")
        return EXIT_OK
    if action == "heartbeat":
        if sentinel.heartbeat():
            print(f"sentinel heartbeat: {path}")
        else:
            print("sentinel heartbeat: no live sentinel")
        return EXIT_OK
    # release: the CLI form releases across invocations (the slash review's
    # batch hold spans processes), so it deletes whatever sentinel exists —
    # in-process ownership scoping belongs to the verbs' self-holds.
    try:
        path.unlink()
        print(f"sentinel released: {path}")
    except FileNotFoundError:
        print("sentinel release: none held")
    return EXIT_OK


def _cmd_import(args: argparse.Namespace) -> int:
    home = resolve_home()
    try:
        if args.backlog is not None:
            report = import_backlog(home, args.backlog)
        else:
            memory_dir = (
                Path(args.memory).expanduser() if args.memory else default_memory_dir()
            )
            report = import_memory(home, memory_dir)
    except ImporterError as exc:  # missing journal / memory dir
        print(f"self-learn import: {exc}", file=sys.stderr)
        return 1
    except LedgerOpsError as exc:  # unknown skill bucket
        print(f"self-learn import: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except gitops.GitOpsError as exc:
        # The importers take the ledger lock BEFORE their first write
        # (round 7), so reaching here means the lock was never acquired:
        # nothing was written, and the import is idempotent by origin —
        # re-running it is exactly right.
        print(
            f"self-learn import: {exc}\n"
            "  Nothing was written — re-run once the other producer "
            "finishes (import is idempotent).",
            file=sys.stderr,
        )
        return EXIT_GIT_FAILED
    # Code-emitted capture events (11 §4.3 payload: source + bucket/scope).
    for rid in report.created:
        try:
            scope = Record.from_path(find_record_path(home, rid)).scope
        except (LedgerOpsError, RecordError):
            scope = None  # scope is a payload nicety, never worth failing on
        telemetry.spool_quiet(
            "capture", source=report.source, record=rid, scope=scope
        )
    print(report.summary())
    # BLOCKER B: records on disk that nobody committed are not a success.
    # Round 7 BLOCKER 2's sweep: and the code for that state is 7, not 6 —
    # the records ARE written, which is the exact opposite of what 6
    # promises. `commit_import` has already printed the repair.
    return EXIT_OK if report.committed else gitops.EXIT_HALF_WRITTEN


def _cmd_prune_memory(args: argparse.Namespace) -> int:
    home = resolve_home()
    memory_dir = Path(args.dir).expanduser() if args.dir else default_memory_dir()
    report = prune_memory(home, memory_dir, dry_run=args.dry_run)
    print(report.summary())
    return EXIT_OK


def _cmd_followup(args: argparse.Namespace) -> int:
    if args.followup_command != "done":
        print("usage: self-learn followup done <id> [--note TEXT]", file=sys.stderr)
        return EXIT_USAGE
    home = resolve_home()
    if (code := _home_gate(home)) is not None:  # see _cmd_verb
        return code
    try:
        result = verbs.followup_done(
            home, args.id, note=args.note, no_push=args.no_push
        )
    except verbs.VerbError as exc:
        print(f"self-learn followup done: {exc}", file=sys.stderr)
        return exc.exit_code
    except LedgerOpsError as exc:
        print(f"self-learn followup done: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except gitops.GitOpsError as exc:  # BLOCKER B: never a traceback
        print(f"self-learn followup done: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED
    return _finish_verb(result, "follow-up done")


def _cmd_telemetry(args: argparse.Namespace) -> int:
    if args.telemetry_command == "note":
        if args.kind not in telemetry.NOTE_KINDS:
            print(
                f"self-learn telemetry note: kind must be one of "
                f"{sorted(telemetry.NOTE_KINDS)} — every other kind is "
                "code-emitted inside CLI paths (11 §4.3)",
                file=sys.stderr,
            )
            return EXIT_USAGE
        try:
            path = telemetry.spool_event(args.kind, reason=args.reason)
        except telemetry.TelemetryError as exc:
            print(f"self-learn telemetry note: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"noted {args.kind} → {path} (spool; flushes with the next verb)")
        return EXIT_OK
    if args.telemetry_command == "flush":
        sentinel.heartbeat()  # tracked-plane write = mutating invocation
        try:
            flush_report = telemetry.flush(resolve_home())
        except telemetry.ScanRefusal as exc:
            print(f"self-learn telemetry flush: {exc}", file=sys.stderr)
            return exc.exit_code
        print(flush_report.summary())
        return EXIT_OK
    print(
        "usage: self-learn telemetry note <kind> [--reason WHY] | telemetry flush",
        file=sys.stderr,
    )
    return EXIT_USAGE


def _cmd_report(as_json: bool) -> int:
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    # report is a flushing verb (11 §4.2) — its numbers include the spool.
    _flush_spool_best_effort(home)
    facts = report_mod.gather(home)
    print(report_mod.render_json(facts) if as_json else report_mod.render_text(facts))
    return EXIT_OK


def _flush_spool_best_effort(home=None, *, no_push: bool = False) -> None:
    """11 §4.2: teach/import/resolution verbs flush the spool after their
    own work. Best-effort — a flush problem is loud but never changes the
    verb's outcome; a scan hit leaves the spool intact.

    ``no_push`` carries the calling verb's ``--no-push`` through: the
    flush commits (H-5 — telemetry is a producer, audit 2026-07-16
    MAJOR 3) but must not PUSH, or it would publish the very commit the
    verb was told to keep local."""
    try:
        flush_report = telemetry.flush(
            home if home is not None else resolve_home(), push=not no_push
        )
    except telemetry.ScanRefusal as exc:
        print(f"self-learn: telemetry flush refused: {exc}", file=sys.stderr)
    except OSError as exc:
        print(f"self-learn: telemetry flush failed: {exc}", file=sys.stderr)
    else:
        if flush_report.events:
            print(flush_report.summary(), file=sys.stderr)


def _cmd_proposal(args: argparse.Namespace) -> int:
    if args.proposal_command != "validate":
        print("usage: self-learn proposal validate <id>", file=sys.stderr)
        return EXIT_USAGE
    try:
        return selfcheck.proposal_validate(resolve_home(), args.id)
    except LedgerOpsError as exc:  # unknown/malformed record id: usage, not P2-8
        print(f"self-learn proposal validate: {exc}", file=sys.stderr)
        return EXIT_USAGE


VERB_COMMANDS = frozenset(
    {
        "route",
        "reject",
        "defer",
        "graduate",
        "rehome",
        "supersede",
        "confirm-recurrence",
        "confirm-held",
    }
)


def _cmd_link(args: argparse.Namespace) -> int:
    if args.link_command != "contradicts":
        print("usage: self-learn link contradicts <id> <target>", file=sys.stderr)
        return EXIT_USAGE
    if (code := _home_gate(resolve_home())) is not None:  # see _cmd_verb
        return code
    try:
        result = verbs.link_contradicts(
            resolve_home(),
            args.id,
            args.target,
            note=args.note,
            no_push=args.no_push,
        )
    except verbs.VerbError as exc:
        print(f"self-learn link contradicts: {exc}", file=sys.stderr)
        return exc.exit_code
    except LedgerOpsError as exc:
        print(f"self-learn link contradicts: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except gitops.GitOpsError as exc:  # BLOCKER B: never a traceback
        print(f"self-learn link contradicts: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED
    return _finish_verb(result, f"contradicts {args.target}")


def main(argv: list[str] | None = None) -> int:
    """Dispatch, with the last-resort ``GitOpsError`` net (audit
    2026-07-16 round 7 BLOCKER 1).

    Every surface catches its own — that is where the state fact is known,
    and only the surface can tell "nothing written" (6) from "half
    written" (7). This net exists because ``_cmd_host`` proved the
    per-surface rule is a thing a human can simply FORGET: it shipped with
    no catch at all and turned a merely-held lock into a stack trace. A
    net cannot know the state fact, so it makes the conservative claim —
    it never says "nothing was written" — and the structural test
    (tests/test_lock_invariant.py) is what keeps surfaces from relying on
    it."""
    try:
        return _main(argv)
    except gitops.HalfWrittenError as exc:  # pragma: no cover - net
        return _report_half_written("(unrouted)", exc)
    except gitops.GitOpsError as exc:  # pragma: no cover - net
        print(
            f"self-learn: git operation failed: {exc}\n"
            "  This surface did not say whether anything was written — run "
            "`self-learn reconcile` to commit any orphaned record, then "
            "`self-learn status`.",
            file=sys.stderr,
        )
        return EXIT_GIT_FAILED


def _main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args, _extra = parser.parse_known_args(argv)
    except SystemExit as exc:  # argparse error (e.g. bad choice, missing group)
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE

    if args.selftest:
        return selfcheck.run_selftest(resolve_home())

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    # Doc 12 R1 layer 2: every CLI invocation is a watchdog tick — spawn a
    # detached mining run when the last one is >24 h old. Never blocks,
    # never fails the command; `mine` itself is excluded (no self-trigger).
    if args.command != "mine":
        try:
            # no_push is passed EXPLICITLY (BLOCKER D): this tick runs
            # before dispatch for every command, so `reject --no-push` used
            # to spawn a miner that pushed the whole branch — the flag it
            # was told nothing about.
            outcome = miner.maybe_kick(
                resolve_home(), no_push=getattr(args, "no_push", False)
            )
            if outcome == "spawned":
                print("miner: catch-up run spawned (>24h)", file=sys.stderr)
        except Exception:  # noqa: BLE001 — watchdog must never break a verb
            pass

    if _extra:
        print(
            f"self-learn {args.command}: unrecognized arguments: {' '.join(_extra)}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.command == "status":
        if args.fast:
            return _cmd_status_fast()
        return _cmd_status(as_json=args.as_json)

    if args.command == "list":
        return _cmd_list(
            as_json=args.as_json, include_deferred=args.include_deferred
        )

    if args.command in ("teach", "import", "prune-memory", "proposal", "report"):
        sentinel.heartbeat()  # 08 §1: every mutating invocation touches a
        # live sentinel; heartbeat never resurrects a stale one.
        # (`telemetry note` is cache-only and model-emittable — it must
        # not extend a review hold's liveness; `telemetry flush` heartbeats
        # in its own branch.)

    if args.command == "teach":
        code = run_teach(args)
        # teach is a flushing verb (11 §4.2); --no-push rides along
        _flush_spool_best_effort(no_push=getattr(args, "no_push", False))
        # Kick when a PENDING record landed (08 §7.1 trigger pin):
        # plain teach success, or a --route that fell back to pending (4).
        if (code == EXIT_OK and not args.route) or code == 4:
            _kick_after_capture(no_push=getattr(args, "no_push", False))
        return code

    if args.command in VERB_COMMANDS:
        code = _cmd_verb(args)
        # every resolution verb flushes (11 §4.2); --no-push rides along
        _flush_spool_best_effort(no_push=getattr(args, "no_push", False))
        return code

    if args.command == "followup":
        code = _cmd_followup(args)
        _flush_spool_best_effort(no_push=getattr(args, "no_push", False))
        return code

    if args.command == "link":
        code = _cmd_link(args)
        _flush_spool_best_effort(no_push=getattr(args, "no_push", False))
        return code

    if args.command == "telemetry":
        return _cmd_telemetry(args)

    if args.command == "report":
        return _cmd_report(as_json=args.as_json)

    if args.command == "push":
        return _cmd_push()

    if args.command == "reconcile":
        return _cmd_reconcile(args)

    if args.command == "host":
        return _cmd_host(args)

    if args.command == "recompile":
        sentinel.heartbeat()  # mutating invocation class (08 §1)
        return _cmd_recompile(args)

    if args.command == "sentinel":
        return _cmd_sentinel(args.action)

    if args.command == "import":
        code = _cmd_import(args)
        # import is a flushing verb (11 §4.2); --no-push rides along
        _flush_spool_best_effort(no_push=getattr(args, "no_push", False))
        if code == EXIT_OK:
            _kick_after_capture(no_push=getattr(args, "no_push", False))
        return code

    if args.command == "worker":
        return _cmd_worker(args)

    if args.command == "mine":
        return _cmd_mine(args)

    if args.command == "prune-memory":
        return _cmd_prune_memory(args)

    if args.command == "proposal":
        return _cmd_proposal(args)

    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


def entrypoint() -> None:  # console-script target
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
