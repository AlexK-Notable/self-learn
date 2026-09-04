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

U-verbs §3.3a: the eight-integer contract above describes ONE mutation;
``self-learn batch`` performs many, so it gains exactly ONE new integer,
``EXIT_BATCH_PARTIAL = 8`` — "batch completed; N items applied, M
refused; the ledger DID change; read the ``--json`` envelope for which."
`0` only when every item applied; `8` on an applied+refused mix; `1`
ONLY when nothing landed (its ratified meaning is never forked); `3`/
`4`/`7` propagate, worst wins; `5`/`6`/`64` as today. Rendered on three
surfaces (measured, `S-54`): here, ``commands/review.md:230-264`` (whose
"Only 3, 4 and 7 mean 'the ledger changed'" becomes "Only 3, 4, 7 and
8"), and ``skills/self-learn/SKILL.md:96-101``. `commands/teach.md` and
`11-telemetry-and-lifecycle.md` take neither row — a different contract,
a different owner.
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
from . import batch, config, gitops, miner, provider, refread, selfcheck, sentinel, serve, settings, telemetry, verbs, worker
from .compilers import CompileError, ReferenceResult
from .import_backlog import import_backlog
from .import_common import ImporterError
from .import_memory import import_memory, prune_memory
from .gitops import EXIT_GIT_FAILED
from .ledger import (
    EXIT_NO_HOME,
    InitError,
    discover_buckets,
    home_state,
    home_state_message,
    init_home,
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
from .verbs import DISMISS_REASONS

EXIT_OK = 0
# 64 = sysexits EX_USAGE — deliberately NOT 2, which P2-8 pins as the
# proposal-validate scan-hit code (audit 2026-07-14: machine consumers must
# never see usage errors aliased onto scan hits). argparse's own flag-error
# exit stays 2 but cannot occur on a well-formed programmatic invocation.
EXIT_USAGE = 64

#: U-verbs §3.3a: the ONE integer the batch executor adds to the
#: eight-integer contract above — "batch completed; N applied, M
#: refused; the ledger DID change; read the --json envelope". The next
#: free integer (0-7 and 64 are taken; 2 is proposal-validate's own
#: scan-hit code, pinned un-aliasable at :71 below).
EXIT_BATCH_PARTIAL = 8

#: Re-exported (defined in :mod:`self_learn.ledger` / :mod:`self_learn.
#: gitops`, beside the concepts they name) so every surface — including
#: `teach`, which used to pin its own — returns the SAME integer.
#: EXIT_NO_HOME 5: the home is missing / not a git repo (BLOCKER 11).
#: EXIT_GIT_FAILED 6: a GitOpsError reached dispatch (BLOCKER B).

_MEMORY_DIR_TAIL = (
    "or set SELF_LEARN_MEMORY_DIR. There is no default: the only "
    "derivable candidate would guess Claude Code's projects-dir slug, "
    "and prune-memory deletes at this path."
)
_IMPORT_MEMORY_DIR_REQUIRED = (
    f"self-learn import: no memory directory — pass `--memory DIR` {_MEMORY_DIR_TAIL}"
)
_PRUNE_MEMORY_DIR_REQUIRED = (
    f"self-learn prune-memory: no memory directory — pass `DIR` {_MEMORY_DIR_TAIL}"
)


def default_memory_dir() -> Path | None:
    """`import --memory` / `prune-memory` dir: env only, no default.

    There is deliberately NO built-in default: the only derivable
    candidate would be a guess at Claude Code's undocumented, many-to-one
    ~/.claude/projects slug scheme, and `prune-memory` DELETES at this
    path. Refusing is the safe answer; see the spec's §4.1.
    """
    env = os.environ.get("SELF_LEARN_MEMORY_DIR")
    return Path(env).expanduser() if env else None


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
    list_p.add_argument(
        "--surface-fill",
        action="store_true",
        dest="surface_fill",
        help="add per-record surface_fill (09 §11 Y-20, U-cap §6.3): "
        "current fill of each scope-valid PROBED destination "
        "(skill-md/claude-md), plus a reference read-rate verdict. "
        "Default OFF; the unflagged --json output is byte-unchanged. "
        "Costly (a routed-record scan per distinct target) — pass --id "
        "to scope it to one record (delta F9).",
    )
    list_p.add_argument(
        "--id",
        metavar="ID",
        dest="record_id",
        help="scope the listing to one record id — with --surface-fill, "
        "computes fill for ONLY this record's targets, not every pending "
        "record's (delta F9; the UI Detail call site)",
    )

    show_p = sub.add_parser(
        "show", help="read-only record detail (U-verbs §4.3) — mutates nothing"
    )
    show_p.add_argument("id", metavar="ID")
    show_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="read-only (U-verbs §4.3) — still ticks the miner watchdog "
        "like every other command; SELF_LEARN_MINER_AUTOKICK=0 "
        "suppresses it, same as `list`",
    )

    add_teach_parser(sub)

    sub.add_parser(
        "init",
        help="bootstrap $SELF_LEARN_HOME as a git repo with the ledger "
        "layout (doc 13 §3; C1 §2.2)",
    )

    def _verb(
        name: str, help_text: str, *, json_flag: bool = False
    ) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--note", metavar="TEXT", help="resolution note → commit body")
        p.add_argument(
            "--no-push",
            action="store_true",
            dest="no_push",
            help="commit exactly as pinned, skip only the push",
        )
        if json_flag:
            # Resolution-evidence unit (§2.1/§3.1): a machine envelope on
            # stdout, populated ONLY on a successful (exit 0) run — never
            # a second outcome channel. Scoped to route/reject/defer/
            # graduate (the resolution verbs the UI's evidence surface
            # drives) — never rehome/supersede/confirm-recurrence/
            # confirm-held, which stay text-only.
            p.add_argument(
                "--json",
                action="store_true",
                dest="as_json",
                help="emit a machine-readable outcome envelope on stdout "
                "and nothing else — success/failure is still the exit "
                "status, never this JSON (07 §4 contract 2)",
            )
        return p

    route = _verb("route", "route a pending record into canon", json_flag=True)
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
    route.add_argument(
        "--allow-empty-glob",
        action="store_true",
        dest="allow_empty_glob",
        help="A2 §5.1 / U-glob: route a rules_paths glob (either scope) that "
        "matches nothing, or that the reachability probe could not decide "
        "within its budget; the bypass and its reason are recorded in the "
        "routing block",
    )
    route.add_argument(
        "--by",
        choices=sorted(verbs.ROUTING_BY_VALUES),
        help="FW-64: names the actor that chose the destination, for a "
        "caller (the review UI's own subprocess call) that knows better "
        "than the --dest-given heuristic — an unmodified approve-as-"
        "proposed still carries an explicit --dest, so without this the "
        "record would read 'human' for an analyst- or agent-chosen "
        "route. Programmatic callers only; omit at a terminal and the "
        "usual rule applies (an explicit --dest you typed IS your own "
        "choice).",
    )
    route.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="U-verbs §4.3: run every preflight, compute the bytes the "
        "compiler would write, and throw them away — writes nothing, "
        "commits nothing, takes no lock, holds no sentinel",
    )

    reject = _verb("reject", "reject a pending record", json_flag=True)
    reject.add_argument("id", metavar="ID")

    defer = _verb(
        "defer", "defer a pending record (default +30 d)", json_flag=True
    )
    defer.add_argument("id", metavar="ID")
    defer.add_argument("--until", metavar="YYYY-MM-DD", help="explicit defer date")

    graduate = _verb(
        "graduate", "mark a lesson graduated into authored canon", json_flag=True
    )
    graduate.add_argument("id", metavar="ID")

    rehome = _verb(
        "rehome", "move a pending record to any registered scope"
    )
    rehome.add_argument("id", metavar="ID")
    rehome.add_argument(
        "--to",
        required=True,
        metavar="TARGET",
        help="U-verbs §3.2: 'user' | 'skill:<name>' | 'project:<path-or-"
        "slug>' | a bare project path/slug (byte-compatible with every "
        "existing call) — the target must already be registered; "
        "self-learn host add <path> [--skills-root] registers one",
    )

    rescope = _verb(
        "rescope",
        "move a pending record between the user bucket, a skill bucket, "
        "or any registered project",
    )
    rescope.add_argument("id", metavar="ID")
    rescope.add_argument(
        "--to",
        required=True,
        metavar="TARGET",
        help="U-verbs §3.2: 'user' | 'skill:<name>' | 'project:<path-or-"
        "slug>' | a bare project path/slug — the target must already be "
        "registered; self-learn host add <path> [--skills-root] "
        "registers one",
    )

    undefer = _verb(
        "undefer", "bring a deferred record back to the queue now (U-verbs §4.2)"
    )
    undefer.add_argument("id", metavar="ID")

    reopen = _verb(
        "reopen", "return a rejected record to the draft plane (U-verbs §4.2)"
    )
    reopen.add_argument("id", metavar="ID")

    reroute = _verb(
        "reroute",
        "correct a wrong routing destination on a routed record "
        "(U-verbs §4.5, Phase 2)",
        json_flag=True,
    )
    reroute.add_argument("id", metavar="ID")
    reroute.add_argument(
        "--dest",
        required=True,
        metavar="TARGET",
        help="the new destination: skill-md | claude-md[:local|:rules:"
        "<topic>] | reference[:<file>] — never hook or new-skill "
        "(rerouting INTO either is a fresh `route`, not a correction)",
    )
    reroute.add_argument(
        "--by",
        choices=sorted(verbs.ROUTING_BY_VALUES),
        help="FW-64: names the actor that chose the NEW destination "
        "(defaults to 'human' — a terminal reroute IS a human decision)",
    )

    reclassify = _verb(
        "reclassify", "re-file a record's kind/type (U-verbs §4.7, Phase 2)"
    )
    reclassify.add_argument("id", metavar="ID")
    reclassify.add_argument(
        "--kind",
        choices=sorted(verbs.records_mod.KINDS),
        default=None,
        help="every status (02 §2: the filing is never frozen) — "
        "behavior records only",
    )
    reclassify.add_argument(
        "--type",
        choices=sorted(verbs.records_mod.TYPES),
        default=None,
        help="pending/deferred only (02 §2 freezes type at routing); "
        "re-validates the required body sections and refuses rather "
        "than rewriting the body to fit",
    )

    note_p = sub.add_parser(
        "note", help="append a commentary entry to a record (U-verbs §4.2)"
    )
    note_p.add_argument("id", metavar="ID")
    note_p.add_argument(
        "--append",
        required=True,
        metavar="TEXT",
        help="the commentary text to append to notes[] — any status, "
        "never touches resolution_note",
    )
    note_p.add_argument(
        "--key",
        metavar="KEY",
        help="idempotency token (self-learn batch's own sheet-line hash) "
        "— when a notes[] entry already carries this key, nothing is "
        "appended (rc 0, no commit); a human at a terminal omits this",
    )
    note_p.add_argument(
        "--no-push",
        action="store_true",
        dest="no_push",
        help="commit exactly as pinned, skip only the push",
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

    ds = _verb(
        "dismiss-suspect",
        "dismiss a recurrence suspect as a matcher false-positive (11 §2.2)",
    )
    ds.add_argument("id", metavar="ID")
    ds.add_argument(
        "--event",
        required=True,
        metavar="NONCE",
        help="the recurrence-suspect telemetry event's nonce (see report --json)",
    )
    ds.add_argument(
        "--why",
        required=True,
        choices=DISMISS_REASONS,
        help="why the suspect is false — the analyst's x-axis",
    )


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
    fadd = followup_sub.add_parser(
        "add",
        help="open a follow-up on a routed record (U-verbs §4.7, Phase 2)",
    )
    fadd.add_argument("id", metavar="ID")
    fadd.add_argument(
        "--action", required=True, metavar="TEXT",
        help="the planned upgrade (11 §2.1)",
    )
    fadd.add_argument(
        "--unblocks-on", dest="unblocks_on", metavar="GATE",
        help="human-readable gate label (e.g. M3)",
    )
    fadd.add_argument("--note", metavar="TEXT", help="why the strong form matters")
    fadd.add_argument(
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
    tread = telemetry_sub.add_parser(
        "read-observed",
        help="U-readref §4: code-emitted reference-read observation "
        "(hook-invoked; not a model-facing verb)",
    )
    tread.add_argument(
        "--path", required=True, metavar="ABS", help="tool_input.file_path, absolute"
    )
    tread.add_argument(
        "--session", default="", metavar="ID", help="the reading session's uuid"
    )
    tread.add_argument(
        "--subagent",
        action="store_true",
        help="present iff the PostToolUse payload carried an agent_id key",
    )

    sub.add_parser(
        "report", help="facts layer v1 (11 §5): lifecycle + telemetry counts"
    ).add_argument("--json", action="store_true", dest="as_json")

    worker_p = sub.add_parser(
        "worker", help="background pre-analysis worker: kick | run (08 §7.1)"
    )
    worker_sub = worker_p.add_subparsers(dest="worker_command", metavar="<verb>")
    wkick = worker_sub.add_parser(
        "kick", help="mark dirty + open a coalescing window (absorbed if open)"
    )
    wkick.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="U-verbs §3.7/§4.8: one outcome object on stdout — the "
        "library's own outcome string, never a re-derived label; the "
        "exit status is unchanged (07 §4 contract 2)",
    )
    wrun = worker_sub.add_parser("run", help="one worker run (normally spawned)")
    wrun.add_argument(
        "--coalesce",
        action="store_true",
        help="sleep SELF_LEARN_COALESCE_SECS first (the kick-spawned form)",
    )
    wrun.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="U-verbs §3.7/§4.8: one outcome object on stdout; exit "
        "status unchanged",
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
    mrun.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="U-verbs §3.7/§4.8: one outcome object on stdout — the "
        "library's own status string, never a re-derived label; exit "
        "status unchanged (07 §4 contract 2)",
    )
    mstatus = mine_sub.add_parser(
        "status", help="last runs, outcomes, and staleness — from the journal"
    )
    mstatus.add_argument("--json", dest="as_json", action="store_true")

    canary_p = sub.add_parser(
        "canary", help="recall check: plant a lesson, scored on later mining runs (FW-34 §3)"
    )
    canary_sub = canary_p.add_subparsers(dest="canary_command", metavar="<verb>")
    cplant = canary_sub.add_parser(
        "plant", help="drop a genuine lesson into the wild as a catchable canary"
    )
    cplant.add_argument("--lesson", required=True, metavar="TEXT")
    cplant.add_argument(
        "--expect", metavar="TEXT", help="optional trigger phrase the miner should catch"
    )

    batch_p = sub.add_parser(
        "batch",
        help="apply a decision sheet in one locked run (U-verbs §3.3/§4.4) "
        "— the review skill's apply path; never hand-write a batch script",
    )
    batch_p.add_argument("sheet", metavar="SHEET.yaml")
    batch_p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="report every item's preflight (all refusals, not the "
        "first) and any sheet-level prerequisite; writes nothing",
    )
    batch_p.add_argument("--json", action="store_true", dest="as_json")
    batch_p.add_argument(
        "--no-push",
        action="store_true",
        dest="no_push",
        help="hold the sentinel, run every item, skip only the final push",
    )

    sub.add_parser("push", help="publish pending local commits (pinned retry)")

    serve_p = sub.add_parser(
        "serve",
        help="run the long-lived host process (U-engine Phase 2: scheduler + heartbeat)",
    )
    serve_p.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        metavar="N",
        help="run exactly N scheduler ticks then exit 0 (default: run forever; smoke-testing hook)",
    )

    doctor_p = sub.add_parser(
        "doctor",
        help="read-only diagnostics: invocation (provider/backend config), "
        "settings (the U-settings registry); bare `doctor` defaults to "
        "`doctor invocation`",
    )
    doctor_sub = doctor_p.add_subparsers(dest="doctor_command", metavar="[<verb>]")
    doctor_sub.add_parser(
        "invocation",
        help="provider/backend switches, model ids, and Bedrock env assembly "
        "(U-bedrock) — the default when no <verb> is given",
    )
    doctor_sub.add_parser(
        "settings",
        help="the U-settings registry: every operator-facing setting, its "
        "resolved value, and its source (env/config.yaml/default)",
    )
    # Bare `doctor` (no <verb>) behaves exactly as `doctor invocation` —
    # there is only one verb today, and forcing operators to spell it out
    # was a papercut nobody chose on purpose (U-papercuts P-2). This sets
    # the namespace default BEFORE parsing; an explicit `doctor invocation`
    # still sets the same value via the subparser action itself, and an
    # unknown verb (`doctor bogus`) is still rejected by argparse's own
    # choice validation before this default is ever consulted. `doctor
    # settings` (U-settings Phase 1) is a SECOND real verb now, added
    # alongside `invocation` without touching its output — `_cmd_doctor`'s
    # dispatch below branches on `doctor_command` explicitly.
    doctor_p.set_defaults(doctor_command="invocation")

    config_p = sub.add_parser(
        "config",
        help="the U-settings registry's write path (Phase 2): "
        "get | set | unset — `doctor settings` stays the read-only "
        "diagnostic view of the same registry",
    )
    config_sub = config_p.add_subparsers(dest="config_command", metavar="<verb>")
    cget = config_sub.add_parser(
        "get",
        help="print every registry entry as `name = value (source)`, or "
        "just one with NAME",
    )
    cget.add_argument("name", nargs="?", metavar="NAME", default=None)
    cget.add_argument("--json", action="store_true", dest="as_json")
    cset = config_sub.add_parser(
        "set",
        help="write NAME=VALUE to config.yaml (validated through the "
        "registry's own parser), commit it, and print the resolved "
        "value + source afterward",
    )
    cset.add_argument("name", metavar="NAME")
    cset.add_argument(
        "value",
        metavar="VALUE",
        help="a VALUE starting with '-' that isn't a bare negative "
        "number (e.g. -5, -5.5) needs `--` before it: "
        "`config set NAME -- -abc`",
    )
    cset.add_argument("--note", metavar="TEXT", default=None)
    cset.add_argument("--json", action="store_true", dest="as_json")
    cunset = config_sub.add_parser(
        "unset", help="remove NAME's config.yaml key and commit"
    )
    cunset.add_argument("name", metavar="NAME")
    cunset.add_argument("--note", metavar="TEXT", default=None)

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
    hadd.add_argument(
        "--mode",
        choices=hosts_mod.HOST_MODES,
        default=None,
        help="U-hostmode: 'git' (default) commits and pushes canon there "
        "like every host always has; 'plain' writes canon UNCOMMITTED — "
        "self-learn makes no commit, no push, and no off-machine backup "
        "of the host's own file, ever, for that host (incompatible with "
        "--init: a plain host is never a git repo self-learn manages). "
        "Omit to use hosts.default_mode (config.yaml), or 'git' when that "
        "is also unset.",
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
    hrm.add_argument(
        "--gate-only",
        action="store_true",
        dest="gate_only",
        help="U-verbs §3.6: proceed even while >=1 routed record still "
        "compiles into this host — today's behaviour, made explicit and "
        "loud (a post-note names the count and the `recompile` "
        "WARN-and-skip consequence). Without this flag, host remove "
        "REFUSES on any such record.",
    )
    host_sub.add_parser("list", help="show the registered hosts")

    bucket_p = sub.add_parser(
        "bucket", help="ledger bucket lifecycle (U-verbs §4.6, Phase 2)"
    )
    bucket_sub = bucket_p.add_subparsers(dest="bucket_command", metavar="<verb>")
    bprune = bucket_sub.add_parser(
        "prune",
        help="remove every record-less, proposal-less bucket directory "
        "(never the user/ bucket)",
    )
    bprune.add_argument("--dry-run", action="store_true", dest="dry_run")
    bprune.add_argument(
        "--no-push", action="store_true", dest="no_push",
        help="commit exactly as pinned, skip only the push",
    )
    hcd = host_sub.add_parser(
        "commit-drift",
        help="F5-5 guided commit-first: commit a dirty compile target's "
        "OWN pending changes (never a plain-host compile-record mismatch — "
        "that refuses naming `recompile --adopt`), then the caller "
        "retries its route",
    )
    hcd.add_argument("id", metavar="ID")
    hcd.add_argument(
        "--dest",
        metavar="TARGET",
        help="the same --dest the failed route used (omit to read the "
        "record's proposal, same rule as route)",
    )
    hcd.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="report {repo, files} and write nothing — same preconditions "
        "and refusals as the real run",
    )
    hcd.add_argument("--json", action="store_true", dest="as_json")

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
    recompile_p.add_argument(
        "--adopt",
        metavar="TARGET",
        default=None,
        help="re-record TARGET's on-disk managed region as authoritative, "
        "clearing an edited/unknown-provenance refusal — content is never "
        "changed (no --force is offered)",
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
        help="import auto-memory topic files (DIR, or $SELF_LEARN_MEMORY_DIR; no default)",
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


def _cmd_init() -> int:
    """``self-learn init`` (C1 §2.2). Deliberately NOT home-gated: gating
    on `home_state` would refuse the exact home this verb exists to
    create. P-C1.10: the resolved path is echoed BEFORE anything is
    created — a wrong/unset ``$SELF_LEARN_HOME`` must be visible
    immediately, not discovered after a second ledger silently appeared
    at a mistyped path."""
    home = resolve_home()
    print(f"self-learn init: {home}")
    try:
        result = init_home(home)
    except InitError as exc:
        print(f"self-learn init: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if result.already_complete:
        print(f"self-learn init: {result.path} already complete — nothing to do")
    elif result.created_repo:
        print(
            f"self-learn init: created git repo + layout "
            f"({', '.join(result.added_dirs)}) at {result.path}"
        )
    else:
        parts = []
        if result.added_dirs:
            parts.append(f"added {', '.join(result.added_dirs)}")
        if result.made_head:
            parts.append("created HEAD (empty commit)")
        print(f"self-learn init: topped up {result.path} — {'; '.join(parts)}")
    return EXIT_OK


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
        if getattr(args, "as_json", False):
            # U-verbs §3.7/§4.8: one outcome object, nothing else on
            # stdout. The library's own `status` string rides through
            # UNCHANGED as `outcome` — never a re-derived label (PROD1).
            # Exit codes are byte-unchanged (PROD3): `ok` is derived
            # from the same two statuses the return below already maps
            # to non-zero, never from the integer itself (PROD2).
            print(
                json.dumps(
                    {
                        "command": "mine run",
                        "outcome": result.status,
                        "ok": result.status not in ("failed", "landed-uncommitted"),
                        "landed": len(result.landed),
                        "folded": len(result.folded),
                        "recurrences": len(result.recurrences),
                        "fires": result.fires,
                        "run_id": result.run_id,
                    }
                )
            )
        else:
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
            payload = {
                "last_run": miner.last_run_iso(),
                "stale": miner.stale(),
                "runs": entries,
            }
            # FW-34 §4: absent/empty when no canary has ever been planted
            # — the one-liner appends "· canaries K/N caught" only when
            # planted > 0.
            canaries = miner.read_canaries_summary()
            if canaries is not None:
                payload["canaries"] = canaries
            print(json.dumps(payload))
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
                    f"fires={e.get('fires', 0)} cap={e.get('cap', '?')} "
                    f"near-misses={e.get('near_miss_count', 0)}"
                )
            if e.get("status") == "landed-uncommitted":
                line += "  ⚠ uncommitted — `self-learn reconcile` commits them"
            elif e.get("status") == "held-gate":
                line += f"  pending={e.get('pending')} ≥ gate={e.get('gate')}"
            elif e.get("status") == "failed":
                line += f"  reason: {e.get('reason', '?')}"
            # FW-53: a run degrades (skip, count, still land) rather than
            # wedging on one undecodable ledger file — surfaced here so a
            # skip is never silent even in the human-readable one-liner.
            corrupt = e.get("corrupt_records") or []
            if corrupt:
                line += f"  ⚠ {len(corrupt)} ledger file(s) not UTF-8, skipped"
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


def _cmd_canary(args: argparse.Namespace) -> int:
    if args.canary_command == "plant":
        try:
            canary_id = miner.plant_canary(args.lesson, args.expect)
        except miner.CanaryError as exc:
            print(f"self-learn canary: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"canary planted: {canary_id}")
        return EXIT_OK
    print("usage: self-learn canary plant --lesson TEXT [--expect TEXT]", file=sys.stderr)
    return EXIT_USAGE


def _cmd_worker(args: argparse.Namespace) -> int:
    home = resolve_home()
    if args.worker_command == "kick":
        outcome = worker.kick(home)
        if getattr(args, "as_json", False):
            # U-verbs §3.7/§4.8: one outcome object, nothing else on
            # stdout — `outcome` is the library's own string UNCHANGED
            # (PROD1), never re-derived; exit stays byte-unchanged (PROD3).
            print(
                json.dumps(
                    {"command": "worker kick", "outcome": outcome, "ok": True}
                )
            )
        else:
            print(f"worker kick: {outcome}")
        return EXIT_OK
    if args.worker_command == "run":
        result = worker.run(
            home, coalesce=args.coalesce, no_push=worker.no_push_requested()
        )
        ok = result.status in ("ok", "idle")
        if getattr(args, "as_json", False):
            print(
                json.dumps(
                    {
                        "command": "worker run",
                        "outcome": result.status,
                        "ok": ok,
                        "proposed": len(result.proposed),
                        "merge_proposed": len(result.merge_proposed),
                        "eligible": result.eligible,
                        "suspects": result.suspects,
                    }
                )
            )
        else:
            n = len(result.proposed)
            print(
                f"worker run: {result.status} — {n} proposal(s), "
                f"{len(result.merge_proposed)} merge, {result.eligible} eligible,"
                f" {result.suspects} recurrence suspect(s)"
            )
        return EXIT_OK if ok else 1
    print("usage: self-learn worker kick | worker run [--coalesce]", file=sys.stderr)
    return EXIT_USAGE


def _cmd_serve(args: argparse.Namespace) -> int:
    """U-engine Phase 2 (spec Sec 5) -- runs `serve.run_forever` in the
    foreground until SIGINT/SIGTERM, or for exactly `--max-ticks` ticks
    (a bounded smoke-testing hook -- also what lets `test_lock_invariant.
    py`'s held-lock harness drive this surface without hanging: HP3
    means a bounded `serve` tick never blocks on the ledger's commit
    lock in the first place). Never home-gated: the daemon is meant to
    be always-on, even against a pristine/uninitialized home."""
    home = resolve_home()
    return serve.run_forever(home, max_ticks=args.max_ticks)


def _cmd_doctor_settings(home: Path) -> int:
    """U-settings Phase 1 -- `doctor settings`'s thin printer, mirroring
    `_cmd_doctor`'s own discipline for `invocation`: every verdict comes
    from :func:`settings.preflight`, the single source of truth; this
    function computes nothing itself. This surface never FAILs (§4:
    introspection only, nothing here gates) -- an unknown config.yaml
    key only ever produces a WARN row, and this verb has no FAIL tier
    at all, so the exit code is unconditionally EXIT_OK regardless of
    verdict, matching `doctor invocation`'s "WARN still exits 0" half
    of its posture without needing the FAIL half."""
    for row in settings.preflight(home):
        print(f"doctor: {row.verdict} {row.name} — {row.detail}")
    return EXIT_OK


def _cmd_doctor(args: argparse.Namespace) -> int:
    """`Doc-0` -- a THIN PRINTER. Computes no verdict of its own and
    calls no probe directly: every verdict comes from
    :func:`provider.preflight` (`invocation`) or :func:`settings.
    preflight` (`settings`, U-settings Phase 1), the single source of
    truth for each verb. Never home-gated (`_home_gate` guards WRITE
    surfaces against a missing/uninitialized ledger; this command never
    writes and must work on a pristine home with no `config.yaml` at all
    — `Doc-c`)."""
    home = resolve_home()
    if args.doctor_command == "settings":
        return _cmd_doctor_settings(home)
    if args.doctor_command != "invocation":
        print("usage: self-learn doctor invocation", file=sys.stderr)
        return EXIT_USAGE
    rows = provider.preflight(home)
    failed = False
    for row in rows:
        if row.verdict == "FAIL":
            failed = True
        print(f"doctor: {row.verdict} {row.name} — {row.detail}")
    print("doctor: ---")
    for field, value in provider._handoff_fields(home, rows):
        print(f"doctor: handoff: {field} = {value}")
    return 1 if failed else EXIT_OK


def _print_setting_row(row: dict, *, prefix: str = "") -> None:
    """The one non-JSON renderer for a `settings.setting_row` dict --
    shared by `config get` and `config set` so the printed shape never
    drifts between the two verbs. Mirrors `doctor settings`'s own
    `name = value (source)` line; the WARN, when present, goes to
    stderr like every other WARN this CLI prints, verbatim (never
    paraphrased — the settings page reuses this same `warn` string)."""
    print(f"{prefix}{row['name']} = {row['value']!r} ({row['source']})")
    if row["warn"]:
        print(f"self-learn: settings — {row['warn']}", file=sys.stderr)


def _cmd_config_get(args: argparse.Namespace, home: Path) -> int:
    if args.name is not None:
        try:
            target = settings.by_name(args.name)
        except KeyError:
            print(f"self-learn config get: unknown setting {args.name!r}", file=sys.stderr)
            return EXIT_USAGE
        rows = [settings.setting_row(home, target)]
    else:
        rows = [settings.setting_row(home, s) for s in settings.REGISTRY]
    if args.as_json:
        print(json.dumps(rows))
        return EXIT_OK
    for row in rows:
        _print_setting_row(row)
    return EXIT_OK


def _cmd_config_set(args: argparse.Namespace, home: Path) -> int:
    setting = settings.config_set(home, args.name, args.value, note=args.note)
    row = settings.setting_row(home, setting)
    if args.as_json:
        print(json.dumps(row))
        return EXIT_OK
    _print_setting_row(row, prefix="config set: ")
    return EXIT_OK


def _cmd_config_unset(args: argparse.Namespace, home: Path) -> int:
    setting, removed = settings.config_unset(home, args.name, note=args.note)
    if removed:
        print(f"config unset: {setting.name}")
    else:
        print(f"config unset: {setting.name} — already unset, nothing to remove")
    return EXIT_OK


def _cmd_config_inner(args: argparse.Namespace, home: Path) -> int:
    if args.config_command == "get":
        return _cmd_config_get(args, home)
    if args.config_command == "set":
        return _cmd_config_set(args, home)
    if args.config_command == "unset":
        return _cmd_config_unset(args, home)
    print("usage: self-learn config get [NAME] | set NAME VALUE | unset NAME", file=sys.stderr)
    return EXIT_USAGE


def _cmd_config(args: argparse.Namespace) -> int:
    """The `config` surface (U-settings Phase 2). `get` is read-only,
    ungated, exactly like `doctor` (`Doc-c`'s reasoning: it must work on
    a pristine home with no config.yaml at all). `set`/`unset` are
    ledger-mutating and home-gated like `host add`/`rebind`/`remove`
    (`_cmd_host`'s own precedent) — same two documented git failure
    codes (`EXIT_HALF_WRITTEN`/`EXIT_GIT_FAILED`), and the settings-
    registry refusal family (`UnknownSettingError` -> `EXIT_USAGE`,
    `InvalidSettingValueError` -> 1) alongside `verbs.VerbError`
    (`DirtyTargetError`'s own home, raised via a lazy import inside
    `settings.py` to avoid a module cycle — see its docstring) for the
    dirty-config-yaml refusal. `config.ConfigWriteError`/`settings.
    NoConfigRungError` (MAJOR-1/MINOR-4, code-gate review r1
    2026-09-01) join this chain for the same reason `UnknownSettingError`/
    `InvalidSettingValueError` are here: a malformed `config.yaml`
    (a scalar section, an unparseable file, a non-mapping top level, a
    mid-walk scalar) used to propagate past every branch below all the
    way to a raw Python traceback (absolute paths and all) — the UI's
    settings row then painted that traceback verbatim into its error
    strip (`routes.py`'s `settings_set`, measured with `RealRunner`).
    Both new branches print ONLY the exception's own composed message
    and exit 1, never a stack trace."""
    home = resolve_home()
    if args.config_command in ("set", "unset") and (code := _home_gate(home)) is not None:
        return code
    try:
        return _cmd_config_inner(args, home)
    except settings.UnknownSettingError as exc:
        print(f"self-learn config {args.config_command}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except settings.NoConfigRungError as exc:
        print(f"self-learn config {args.config_command}: {exc}", file=sys.stderr)
        return 1
    except settings.InvalidSettingValueError as exc:
        print(f"self-learn config {args.config_command}: {exc}", file=sys.stderr)
        return 1
    except config.ConfigWriteError as exc:
        print(f"self-learn config {args.config_command}: {exc}", file=sys.stderr)
        return 1
    except verbs.VerbError as exc:  # DirtyTargetError, SecretRefusal, exit_code=1
        print(f"self-learn config {args.config_command}: {exc}", file=sys.stderr)
        return exc.exit_code
    except gitops.HalfWrittenError as exc:
        return _report_half_written(f"config {args.config_command}", exc)
    except gitops.GitOpsError as exc:  # lock timeout / wedged git: nothing written
        print(f"self-learn config {args.config_command}: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED


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
            # 09 §5 unreadable-record row (FW-18): per-bucket `unreadable`
            # rides each buckets[] entry (from status_infos); the top-level
            # total is the Front consumer's datum. The `--fast` path OMITS
            # this field entirely (absence = unknown, never zero) — its
            # frontmatter-only scan cannot detect the schema/section class.
            "total_unreadable": sum(i["unreadable"] for i in infos),
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


def _add_surface_fill(
    home: Path,
    items: list[dict],
    *,
    user_claude_md: Path | str | None = None,
) -> None:
    """09 §11 Y-20 / 08 §1: mutate each item in place, adding its
    ``surface_fill`` object. One cache dict spans every item passed in, so
    records sharing a target (one skill's SKILL.md, the one user-scope
    CLAUDE.md) pay for the compile exactly once per invocation (08 §1 e).

    ``user_claude_md`` is an internal passthrough to
    :func:`verbs.surface_fill` (blind-review F5) — there is no CLI flag
    for it; ``_cmd_list`` never passes anything but the default, so real
    invocations keep reading the real user-scope canon file for a
    user-scope record, exactly like every other verb call site. It exists
    so an in-process caller (a test) can override the target WITHOUT
    going through a subprocess — the real hazard this closes is a
    CLI-path test calling this function directly on a user-scope pending
    record and silently reading ``~/.claude/CLAUDE.md``."""
    cache: dict = {}
    for item in items:
        try:
            path = find_record_path(home, item["id"])
        except LedgerOpsError:
            continue  # can't happen off list_items's own output; defensive
        bucket_dir = path.parent.parent
        item["surface_fill"] = verbs.surface_fill(
            home, bucket_dir, item["scope"], user_claude_md=user_claude_md, cache=cache
        )


def _cmd_list(
    as_json: bool,
    include_deferred: bool,
    surface_fill: bool = False,
    record_id: str | None = None,
) -> int:
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    _warn_unparseable(home)
    items = list_items(home, include_deferred=include_deferred)
    if record_id is not None:
        items = [i for i in items if i["id"] == record_id]

    if as_json:
        if surface_fill:
            _add_surface_fill(home, items)
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


# ------------------------------------------------ resolution-evidence (§2.1)
#
# The `--json` envelope for route/reject/defer/graduate. Built ENTIRELY
# from typed `VerbResult` attributes — never by re-parsing `commit_message`
# (that class of mistake is what `_routed_destination` / the `" until "`
# split below still do, for the UNRELATED plain-text summary line only;
# this envelope path never calls them). `outcome_state` is derived HERE,
# CLI-side (§3.3): `compile_result` is a Python object that exists only in
# this process, so the surface renders the value and evaluates no
# predicate of its own.


def _push_state(push: gitops.PushResult | None) -> str:
    """One of the three states §2.1's `pushed`/`host_pushed` rows require
    the envelope to tell apart — never a formatted sentence (§3.1: the
    envelope carries machine structure, the surface does the wording)."""
    if push is None:
        return "not_requested"  # --no-push
    if push.skipped:
        return "no_remote"
    return "pushed" if push.ok else "failed"


def _created_flag(compile_result: object) -> bool | None:
    """`SectionResult.bootstrapped` / `ReferenceResult.created` /
    `NewSkillApplyResult.scaffolded` — whichever the result type carries.
    `None` for a result type with none of the three (hook, user-scope):
    those are not a "created vs appended" shape at all.

    `bootstrapped=True` means the managed-section MARKERS were absent and
    got appended — NOT that the file itself was created (compilers.py:118
    docstring). A `claude-md` route DOES create a missing target file
    first (verbs.py ~1663); `skill-md` never does (preflight refuses a
    missing target). This function reports the per-type boolean
    verbatim and nothing more — the surface must render it as "added a
    section" wording, never "created this file", or it claims a file
    creation this field was never able to prove."""
    if compile_result is None:
        return None
    for attr in ("bootstrapped", "created", "scaffolded"):
        if hasattr(compile_result, attr):
            return bool(getattr(compile_result, attr))
    return None


def _reports_no_change(compile_result: object) -> bool:
    """The §3.3 state-2 (`no_op`) per-type read — no field is shared
    across every compile-result type, so each is read on its own terms:
    ``SectionResult``/``HookApplyResult``/``NewSkillApplyResult`` share
    ``.changed`` (duck-typed, read generically below); ``ReferenceResult``
    has ``.applied`` instead."""
    if isinstance(compile_result, ReferenceResult):
        return not compile_result.applied
    changed = getattr(compile_result, "changed", None)
    if changed is not None:
        return not changed
    return False  # unrecognized result type: never silently claim no_op


def _outcome_state(result: verbs.VerbResult) -> str:
    """§3.3's four states plus `unknown`, derived CLI-side.

    Verb-aware, and deliberately NOT one predicate applied uniformly:
    the literal ``compile_result is None and host_commit_sha is None``
    drift key only means "a host write was attempted and failed" for
    `route`, where a real success always sets `compile_result` (so
    `None` proves `_host_phase` caught one of `_HOST_PHASE_ERRORS`).

    `reject`/`defer` never attempt a host write at all — the ledger
    resolution IS the whole verb, so "landed" is the only honest label
    (never `no_op`: §3.3 state 2's own text is "nothing changed **plus
    the existing file**", which is false copy for a reject that just
    moved the record to `resolved/`).

    `graduate`'s retirement host phase discards its compile object even
    on a genuine success (`_, host_sha = _host_phase(...)`,
    verbs.py:1570 in `_retirement_host_phase`) — so `compile_result` is
    ALWAYS `None` on a `VerbResult` from `graduate`, success or not.
    Worse, `_retirement_preflight` (verbs.py:1514) returns an empty
    `_Retirement()` — no host phase even attempted — whenever the
    graduated record was never routed at all, which is graduate's own
    documented second door: "a pending already-canon one (the
    bulk-acknowledge door)" (verbs.py ~2907). Applying route's literal
    predicate here would report EVERY bulk-acknowledge as "drift",
    telling the user to `recompile` canon that never existed. A genuine
    retirement failure still surfaces via `warnings` regardless (§3.7
    renders it on the success leg unconditionally) — this function only
    controls the summary label, never the repair text."""
    if result.action in ("reject", "defer"):
        return "landed"
    if result.action == "graduate":
        return "landed" if result.host_commit_sha is not None else "no_op"
    # route: the full 4-state predicate.
    if result.host_commit_sha is not None:
        return "landed"
    if result.compile_result is None:
        return "drift"
    if _reports_no_change(result.compile_result):
        return "no_op"
    # U-hostmode PLAIN3: every PLAIN host's successful, changed write
    # never sets host_commit_sha (no host commit exists in plain mode by
    # construction), so without this the shipped predicate fell through
    # to "unknown" for every plain route. `result.mode` is `None` for a
    # spec-less verb (reject/defer/graduate), which correctly never
    # reaches this branch.
    if result.variant == "local" or result.mode == "plain":
        return "wrote_uncommitted"
    return "unknown"


def _canon_path(result: verbs.VerbResult) -> str | None:
    """`target` is the canon path (§0's ruling: never `staged`) — but a
    `reference` route's `TargetSpec.target` is `None` by construction
    (verbs.py's reference branch of `_resolve_target`: the references
    file is discovered per-record at COMPILE time, not known ahead of
    it, so nothing is threaded into `TargetSpec.target`). That left
    `canon_path` reading `None` even on a landed reference-route
    success — code-gate finding 1 (BLOCKER): the render surface then
    interpolated it unguarded, printing literal "in `None`". Fall back
    to `ReferenceResult.path`, the one compile-result type that carries
    its own path outside `target`; still `None` for graduate/defer
    (nothing to fall back to) and for a genuine drift (no compile
    result reached at all)."""
    if result.target is not None:
        return str(result.target)
    if isinstance(result.compile_result, ReferenceResult):
        return str(result.compile_result.path)
    return None


def _verb_envelope(result: verbs.VerbResult) -> dict:
    """The §2.1 envelope, verb-shape-agnostic — every field is present
    for every verb; verb-specific ones (`canon_path`, `destination`,
    `variant`, `deferred_until`) are `None` where they do not apply. The
    surface picks what to render per §3.2's per-verb content table."""
    return {
        "action": result.action,
        "record_id": result.record_id,
        # target — NEVER staged (the ledger's own resolved/ path). See
        # §2.1: a toast sourcing "paths written" from `staged` would show
        # a ledger record path on every verb, including defer. Falls
        # back to ReferenceResult.path for the one destination whose
        # TargetSpec.target is never set (see _canon_path).
        "canon_path": _canon_path(result),
        "host_commit_sha": result.host_commit_sha,
        # reject's "moved to resolved/" content — the LEDGER paths.
        "ledger_paths": [str(p) for p in result.staged],
        "commit_message": result.commit_message,
        "destination": result.destination,
        "variant": result.variant,
        "deferred_until": result.deferred_until,
        "warnings": list(result.warnings),
        "created": _created_flag(result.compile_result),
        "outcome_state": _outcome_state(result),
        "budget": result.budget_note(),
        "pushed": _push_state(result.push),
        # `None` when no host commit ever happened — "pushed" is moot,
        # never rendered as "you chose not to" for a verb that had
        # nothing to push in the first place.
        "host_pushed": (
            _push_state(result.host_push)
            if result.host_commit_sha is not None
            else None
        ),
    }


def _finish_verb(result: verbs.VerbResult, target: str, *, as_json: bool = False) -> int:
    """One-line success summary: id, action, target, short sha, push state
    (ledger AND host). Exit 0, or the distinct push-failure code — a HOST
    push failure counts exactly like a ledger one (MAJOR 4).

    A hook route carries the ENTIRE generated script as ``diff`` (08 §8.1
    approval flow — never a summary) and the required manual steps as
    ``post_notes`` (M3-11): both print here, script first — UNLESS
    ``as_json``, where §4 pins stdout as "the envelope and NOTHING else":
    `diff` and `post_notes` are both stdout-bound prose (a hook's entire
    generated script; multi-line manual-step text) that would otherwise
    turn stdout into "JSON-then-prose". Exit status and stderr (warnings,
    the budget note, the push-failure code) are UNCHANGED either way —
    `--json` never moves the outcome, only how it is printed."""
    if as_json:
        print(json.dumps(_verb_envelope(result)))
    else:
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
    if (note := result.budget_note()) is not None:
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
        if args.command == "route" and getattr(args, "dry_run", False):
            # U-verbs §4.3 (DRY3): no sentinel, no lock — a preview only.
            dr = verbs.route_dry_run(
                home,
                args.id,
                dest=args.dest,
                allow_empty_glob=args.allow_empty_glob,
            )
            if args.as_json:
                print(json.dumps(dr.to_json()))
            else:
                if dr.would_refuse:
                    for reason in dr.would_refuse:
                        print(f"self-learn route --dry-run: {reason}", file=sys.stderr)
                else:
                    print(
                        f"route --dry-run {args.id} → {dr.destination} "
                        f"@ {dr.target or '(no single target)'} "
                        f"(+{dr.added_lines}/-{dr.removed_lines}"
                        f"{', already present' if dr.already_present else ''})"
                    )
                    if dr.unified_diff:
                        print(dr.unified_diff)
            return EXIT_OK if dr.ok else 1
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
                by=args.by,
                note=args.note,
                no_push=args.no_push,
                follow_up=follow_up,
                collapse=args.collapse,
                allow_empty_glob=args.allow_empty_glob,
            )
            return _finish_verb(
                result, _routed_destination(result), as_json=args.as_json
            )
        if args.command == "reject":
            result = verbs.reject(home, args.id, note=args.note, no_push=args.no_push)
            return _finish_verb(result, "rejected", as_json=args.as_json)
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
            return _finish_verb(
                result, f"deferred until {until_str}", as_json=args.as_json
            )
        if args.command == "graduate":
            result = verbs.graduate(
                home, args.id, note=args.note, no_push=args.no_push
            )
            return _finish_verb(result, "canon", as_json=args.as_json)
        if args.command == "rehome":
            result = verbs.rehome(
                home, args.id, to=args.to, note=args.note, no_push=args.no_push
            )
            # pinned subject: "self-learn: rehome lrn-… → projects/<slug>"
            return _finish_verb(result, _routed_destination(result))
        if args.command == "rescope":
            result = verbs.rescope(
                home, args.id, to=args.to, note=args.note, no_push=args.no_push
            )
            # U-verbs §3.2: `rescope --to` now accepts the same UNION
            # grammar `rehome` does, so `args.to` is no longer always a
            # bare scope literal `_rescope_dest_label` could parse
            # directly — `_routed_destination` reads the RESOLVED
            # dest-label back off the verb's own commit message instead,
            # the same generic "text after →" parse `rehome` already
            # uses (both verbs build that label through the same
            # `_move_dest_label` helper now, so the two can never
            # diverge).
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
        if args.command == "dismiss-suspect":
            result = verbs.dismiss_suspect(
                home,
                args.id,
                event_ref=args.event,
                why=args.why,
                note=args.note,
                no_push=args.no_push,
            )
            return _finish_verb(result, "suspect dismissed")
        if args.command == "undefer":
            result = verbs.undefer(home, args.id, note=args.note, no_push=args.no_push)
            return _finish_verb(result, "pending")
        if args.command == "reopen":
            result = verbs.reopen(home, args.id, note=args.note, no_push=args.no_push)
            return _finish_verb(result, "pending")
        if args.command == "note":
            result = verbs.note(
                home, args.id, append=args.append, key=args.key, no_push=args.no_push
            )
            return _finish_verb(result, "noted")
        if args.command == "reroute":
            result = verbs.reroute(
                home, args.id, dest=args.dest, by=args.by, note=args.note,
                no_push=args.no_push,
            )
            return _finish_verb(
                result, _routed_destination(result), as_json=args.as_json
            )
        if args.command == "reclassify":
            result = verbs.reclassify(
                home, args.id, kind=args.kind, type=args.type, note=args.note,
                no_push=args.no_push,
            )
            return _finish_verb(result, "reclassified")
    except verbs.VerbError as exc:  # incl. SecretRefusal
        print(f"self-learn {args.command}: {exc}", file=sys.stderr)
        return exc.exit_code
    except LedgerOpsError as exc:  # unknown/malformed id, proposal trouble
        print(f"self-learn {args.command}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except CompileError as exc:
        # broken markers: refused, nothing lost
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
        # U-hostmode MODE1/§4.2: an explicit --mode wins; omitted falls
        # back to hosts.default_mode (config.yaml), or "git" when that is
        # also unset — never a silent per-call default divorced from the
        # registry-wide setting a human may have opted into.
        mode = args.mode if args.mode is not None else hosts_mod.effective_default_mode(home)
        try:
            result = hosts_mod.host_add(home, args.path, kind, init=args.init, mode=mode)
        except hosts_mod.HostsError as exc:
            print(f"self-learn host add: {exc}", file=sys.stderr)
            return EXIT_USAGE
        registry = result.hosts
        mode_suffix = f" (mode={mode})" if mode != "git" else ""
        print(f"host add: {kind} {Path(args.path).expanduser().resolve()}{mode_suffix}")
        if result.marker_restored:
            # N-3 (code gate r3 fold): the print moved here from inside
            # hosts.py's host_add (M-4, code gate r2 fold) — the
            # library layer now returns the SIGNAL, this CLI layer owns
            # the terminal.
            marker_path = (
                Path(args.path).expanduser().resolve() / hosts_mod.MARKER_FILENAME
            )
            print(f"host add: marker restored at {marker_path}")
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
        if mode == "plain":
            # PLAIN7: name what plain mode does NOT do, plus §4.11's
            # residual (a plain host is only ever unpublished until a
            # human's own later `git init` + push change that).
            print(
                "  consent (plain mode): self-learn makes NO commit, NO "
                "push, and keeps NO off-machine backup of this host's own "
                "file — every write lands uncommitted; committing and "
                "publishing it is entirely yours to do, or not"
            )
            print(
                "  note: a claude-md:local file written here is NOT "
                "gitignore-protected (nothing is tracked) — if you later "
                "git init and push this host yourself, anything already "
                "written here publishes with it"
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
        gate_only = getattr(args, "gate_only", False)
        # N-3-style split (host_add's own precedent): the LIBRARY layer
        # returns the fact (records_targeting), this CLI layer owns the
        # terminal note — computed BEFORE the call so a --gate-only run
        # can name the exact count it is bypassing (HOST2).
        bypassed = (
            hosts_mod.records_targeting(home, args.path) if gate_only else []
        )
        try:
            registry = hosts_mod.host_remove(home, args.path, gate_only=gate_only)
        except hosts_mod.HostRemoveRefused as exc:
            print(f"self-learn host remove: {exc}", file=sys.stderr)
            return 1
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
        if bypassed:
            print(
                f"  --gate-only: {len(bypassed)} routed record(s) still "
                "compiled into this host — that canon is now UNMANAGED; "
                "`recompile` will WARN and skip it"
            )
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
    if args.host_command == "commit-drift":
        try:
            result = verbs.commit_drift(
                home, args.id, dest=args.dest, dry_run=args.dry_run
            )
        except (verbs.VerbError, LedgerOpsError, RecordError) as exc:
            # gate 64: the commit-drift refusals (clean / drift / bad id /
            # a resolution VerbError) are usage-shaped, like every other
            # host-family refusal — never route's own exit-1 mapping
            # (_cmd_verb), because this surface is dispatched through
            # _cmd_host, not _cmd_verb.
            print(f"self-learn host commit-drift: {exc}", file=sys.stderr)
            return EXIT_USAGE
        if args.as_json:
            print(json.dumps({"repo": str(result.repo), "files": result.files}))
        elif result.dry_run:
            print(f"commit-drift (dry-run): {result.repo} ({len(result.files)} file(s))")
            for f in result.files:
                print(f"  {f}")
        else:
            print(
                f"commit-drift: {result.repo} ({len(result.files)} file(s)) "
                f"@ {(result.commit_sha or '')[:7]}"
            )
        return EXIT_OK
    print(
        "usage: self-learn host add <path> [--skills-root] | "
        "host rebind <slug-or-old-path> <new-path> | host remove <path> | "
        "host commit-drift <id> [--dest TARGET] [--dry-run] [--json] | "
        "host list",
        file=sys.stderr,
    )
    return EXIT_USAGE


def _cmd_bucket(args: argparse.Namespace) -> int:
    """The ``bucket`` surface (U-verbs S-54 / §4.6, Phase 2, HOST4) —
    same home-gate/GitOpsError discipline as ``_cmd_host`` (round 7
    BLOCKER 1's own reasoning applies here too: a missing home makes
    ``commit_lock_path`` raise)."""
    if args.bucket_command != "prune":
        print("usage: self-learn bucket prune [--dry-run] [--no-push]", file=sys.stderr)
        return EXIT_USAGE
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    try:
        result = verbs.bucket_prune(home, dry_run=args.dry_run, no_push=args.no_push)
    except gitops.HalfWrittenError as exc:
        return _report_half_written("bucket prune", exc)
    except gitops.GitOpsError as exc:
        print(f"self-learn bucket prune: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED
    if args.dry_run:
        if not result.pruned:
            print("bucket prune (dry-run): nothing to prune")
        else:
            print(f"bucket prune (dry-run): {len(result.pruned)} empty bucket(s)")
            for b in result.pruned:
                print(f"  {b}")
        return EXIT_OK
    if not result.pruned:
        print("bucket prune: nothing to prune")
        return EXIT_OK
    print(f"bucket prune: {len(result.pruned)} empty bucket(s) removed")
    for b in result.pruned:
        print(f"  {b}")
    if result.push is not None and not result.push.ok:
        return result.push.exit_code
    return EXIT_OK


def _host_line(home, path, kind: str) -> str:
    """One registry line, with any gate problem spelled out inline.

    U-hostmode MODE11/UN4: the mode suffix appears ONLY for a non-git
    host — a registry with no plain entries renders byte-identical to
    50fa815's (git stays the silent, unannotated default everywhere else
    in this line's shape)."""
    if path is None:
        return "(none registered)"
    problem = hosts_mod.host_path_problem(home, path, kind)
    mode = hosts_mod.host_mode(home, path)
    mode_suffix = f"  [mode={mode}]" if mode != "git" else ""
    if problem is None:
        return f"{path}{mode_suffix}"
    return f"{path}{mode_suffix}  ⚠ BROKEN — {problem}"


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
        result = verbs.recompile(
            home,
            no_push=args.no_push,
            adopt=Path(args.adopt) if args.adopt else None,
        )
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
            # a plain host commits nothing (no host commit exists there —
            # PLAIN3); user scope is one plain host among the rest.
            state = "recompiled (plain host, no commit)"
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
    memory_dir: Path | None = None
    if args.backlog is None:
        memory_dir = Path(args.memory).expanduser() if args.memory else default_memory_dir()
        if memory_dir is None:
            print(_IMPORT_MEMORY_DIR_REQUIRED, file=sys.stderr)
            return EXIT_USAGE
    try:
        if memory_dir is not None:            # NOT `args.backlog is not None`
            report = import_memory(home, memory_dir)
        else:
            report = import_backlog(home, args.backlog)
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
    if memory_dir is None:
        print(_PRUNE_MEMORY_DIR_REQUIRED, file=sys.stderr)
        return EXIT_USAGE
    report = prune_memory(home, memory_dir, dry_run=args.dry_run)
    print(report.summary())
    return EXIT_OK


def _cmd_followup(args: argparse.Namespace) -> int:
    if args.followup_command not in ("done", "add"):
        print(
            "usage: self-learn followup done <id> [--note TEXT] | "
            "followup add <id> --action TEXT [--unblocks-on GATE] "
            "[--note TEXT]",
            file=sys.stderr,
        )
        return EXIT_USAGE
    home = resolve_home()
    if (code := _home_gate(home)) is not None:  # see _cmd_verb
        return code
    surface = f"followup {args.followup_command}"
    try:
        if args.followup_command == "add":
            result = verbs.followup_add(
                home, args.id, action=args.action, unblocks_on=args.unblocks_on,
                note=args.note, no_push=args.no_push,
            )
        else:
            result = verbs.followup_done(
                home, args.id, note=args.note, no_push=args.no_push
            )
    except verbs.VerbError as exc:
        print(f"self-learn {surface}: {exc}", file=sys.stderr)
        return exc.exit_code
    except LedgerOpsError as exc:
        print(f"self-learn {surface}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except gitops.GitOpsError as exc:  # BLOCKER B: never a traceback
        print(f"self-learn {surface}: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED
    label = "follow-up added" if args.followup_command == "add" else "follow-up done"
    return _finish_verb(result, label)


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
        # Fold r1 MAJOR M-1: `summary()` now says "deferred" honestly on
        # stdout when the lock could not be taken (was "spool empty"
        # before the fold) — the CLI's exit namespace has no existing
        # non-error, non-OK code for "deferred" (EXIT_BATCH_PARTIAL is
        # `batch`'s own multi-item semantics; every other non-OK code
        # names an actual failure), so this stays EXIT_OK: a deferred
        # flush is not an error, it retries on its own next time, and the
        # text is now honest either way.
        return EXIT_OK
    if args.telemetry_command == "read-observed":
        return _cmd_telemetry_read_observed(args)
    print(
        "usage: self-learn telemetry note <kind> [--reason WHY] | "
        "telemetry flush | telemetry read-observed --path ABS [--session ID] [--subagent]",
        file=sys.stderr,
    )
    return EXIT_USAGE


def _cmd_telemetry_read_observed(args: argparse.Namespace) -> int:
    """U-readref §4.1/§4.2-6: the hook-invoked, code-emitted verb behind
    the PostToolUse Read hook's rare (references-shaped-path) leg. Emits
    one `reference-read` event iff `--path` resolves to a REGISTERED
    references target (§4.1.2's `refread.resolve_ref_target`) — an
    unresolvable path emits nothing and is not an error (T2.6).

    Silent on stdout on EVERY path (§4.2-7) — this verb sits on the
    critical path of every reference-shaped Read via the hook, and an
    instrument that spoke into the session would perturb the very
    behaviour it measures. Failure-tolerant by construction: nothing here
    may raise past this function — `spool_quiet` (never `spool_event`,
    §5.2) already absorbs a spool failure, and `resolve_ref_target` itself
    never raises (read-only resolution, absorbs its own OS/parse errors)."""
    try:
        refread.emit_reference_read(
            resolve_home(),
            abs_path=args.path,
            session=args.session or "",
            subagent=bool(args.subagent),
        )
    except Exception as exc:  # never surfaces on stdout either way (§4.2-7)
        print(f"self-learn telemetry read-observed: {exc}", file=sys.stderr)
    return EXIT_OK


def _cmd_report(as_json: bool) -> int:
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    # report is a flushing verb (11 §4.2) — its numbers include the spool.
    # U-readref §6.7/§10.2: the flush outcome is PASSED IN, never inferred
    # from the spool at gather time — a concurrent session's spool write
    # would misreport a healthy run as `refused`.
    flush_state = _mutating_epilogue(home)
    facts = report_mod.gather(home, flush_state=flush_state)
    print(report_mod.render_json(facts) if as_json else report_mod.render_text(facts))
    return EXIT_OK


def _flush_spool_best_effort(home=None, *, no_push: bool = False) -> str:
    """11 §4.2: teach/import/resolution verbs flush the spool after their
    own work. Best-effort — a flush problem is loud but never changes the
    verb's outcome; a scan hit leaves the spool intact.

    ``no_push`` carries the calling verb's ``--no-push`` through: the
    flush commits (H-5 — telemetry is a producer, audit 2026-07-16
    MAJOR 3) but must not PUSH, or it would publish the very commit the
    verb was told to keep local.

    Returns the outcome — ``"ok"`` | ``"refused"`` | ``"failed"`` |
    ``"deferred"`` (U-readref §6.7/§10.2; ``"deferred"`` added M-M fold r1
    MAJOR M-1) — the four cases this function now distinguishes
    internally. `_cmd_report` is the one caller that consumes it (passed to
    `report.gather` as `flush_state`, which gates
    ``counts_are_lower_bound`` on anything other than ``"ok"``); every
    other caller may still ignore it, unchanged."""
    try:
        flush_report = telemetry.flush(
            home if home is not None else resolve_home(), push=not no_push
        )
    except telemetry.ScanRefusal as exc:
        print(f"self-learn: telemetry flush refused: {exc}", file=sys.stderr)
        return "refused"
    except OSError as exc:
        print(f"self-learn: telemetry flush failed: {exc}", file=sys.stderr)
        return "failed"
    else:
        if flush_report.deferred_reason is not None:
            # Fold r1 MAJOR M-1: a deferred flush is NOT "ok" — the
            # spool still holds events `read_events` never sees, so the
            # one caller that consumes this outcome (`_cmd_report`, via
            # `report.gather`'s `flush_state`) must see something other
            # than "ok" or its `counts_are_lower_bound` reads False while
            # counts silently under-report.
            print(flush_report.summary(), file=sys.stderr)
            return "deferred"
        if flush_report.events:
            print(flush_report.summary(), file=sys.stderr)
        return "ok"


def _mutating_epilogue(home=None, *, no_push: bool = False) -> str:
    """U-verbs §3.3c: THE one place 11 §4.2's flush rule is written.
    Carries :func:`_flush_spool_best_effort`'s EXACT signature and
    return so every substitution is a one-line, in-place edit — every
    dispatch that may commit ends HERE, so a new surface cannot miss the
    rule by forgetting to copy a line. `_flush_spool_best_effort` itself
    has exactly one caller after the fold: this function (`BAT11` leg
    (a)). The seven normative call SITES (§3.3c's table): `_cmd_report`,
    `_main`'s teach/`VERB_COMMANDS`/followup/link/import branches, and
    `batch.run` (after its item loop, inside the sentinel hold, before
    the push, always with `no_push=True` — the batch owns the single
    push, so the flush's own commit rides it rather than publishing
    itself)."""
    return _flush_spool_best_effort(home, no_push=no_push)


def _cmd_show(args: argparse.Namespace) -> int:
    """Read-only record detail (U-verbs §4.3, ``SHOW2``/``SHOW3``) — its
    own `_cmd_*`, deliberately OUTSIDE ``VERB_COMMANDS``: that set's
    dispatch flushes the telemetry spool (`_main`), and the flush
    COMMITS (`_flush_spool_best_effort`'s own docstring) — a read-only
    verb wired through it would move the ledger's ``HEAD`` whenever a
    spool happened to be non-empty. Like every command except
    `mine`/`init`/`serve`, it still ticks the miner watchdog
    (`_main`'s own tick, unconditional here) —
    ``SELF_LEARN_MINER_AUTOKICK=0`` suppresses it, same as `list`."""
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    try:
        data = verbs.show(home, args.id)
    except LedgerOpsError as exc:
        print(f"self-learn show: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.as_json:
        print(json.dumps(data))
        return EXIT_OK
    print(f"{data['id']}  {data['status']}  {data['scope']}  {data['bucket']}")
    if data["kind"]:
        print(f"  kind: {data['kind']}  type: {data['type']}")
    else:
        print(f"  type: {data['type']}")
    print(f"  created: {data['created_at']}  sightings: {data['sightings']}")
    if data["deferred_until"]:
        print(
            f"  deferred until {data['deferred_until']} "
            f"(count {data['deferred_count']})"
        )
    if data["superseded_by"]:
        print(f"  superseded by: {data['superseded_by']}")
    if data["resolution_note"]:
        print(f"  resolution note: {data['resolution_note']}")
    routing = data["routing"]
    if routing is not None:
        print(
            f"  routed → {routing['destination']} "
            f"({routing['by']}, {routing['routed_at']})"
        )
        canon = data["canon"]
        if canon["target"]:
            present = "present" if canon["present"] else "NOT present"
            print(f"  canon: {canon['target']} — {present}")
        if routing.get("follow_up"):
            print(f"  open follow-up: {routing['follow_up'].get('action')}")
    prop = data["proposal"]
    if prop["present"]:
        fresh = "fresh" if prop["fresh"] else "stale"
        print(f"  proposal: {prop['destination']} ({fresh})")
    if data["last_confirmed"]:
        print(f"  last confirmed: {data['last_confirmed']}")
    for note_entry in data["notes"]:
        print(f"  note ({note_entry.get('at')}): {note_entry.get('text')}")
    if data["lifecycle"]:
        print("  lifecycle:")
        for row in data["lifecycle"]:
            print(f"    {row['sha']}  {row['date']}  {row['subject']}")
    return EXIT_OK


def _cmd_batch(args: argparse.Namespace) -> int:
    """``self-learn batch`` (U-verbs §3.3/§4.4) — apply a decision sheet
    in one locked run. Deliberately OUTSIDE ``VERB_COMMANDS``: the flush
    and the push are both ``batch.run``'s own responsibility
    (``_mutating_epilogue``'s docstring names ``batch.run`` as call site
    #7) — wiring `batch` through `VERB_COMMANDS` would flush and push a
    SECOND time on top of the one `batch.run` already does internally.
    ``--dry-run`` takes neither the sentinel nor the lock (BAT9) — a
    preview only, same shape as `route --dry-run` (DRY3)."""
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    try:
        items = batch.load_sheet(args.sheet)
    except batch.BatchError as exc:
        print(f"self-learn batch: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.dry_run:
        dr = batch.dry_run(home, items)
        if args.as_json:
            print(json.dumps(dr.to_json()))
        else:
            for it in dr.items:
                line = f"  [{it.n}] {it.id} {it.verb}: {it.state}"
                if it.detail:
                    line += f" — {it.detail}"
                print(line)
            if dr.hook_items:
                print(
                    "self-learn batch --dry-run: hook route(s) present "
                    f"({', '.join(dr.hook_items)}) — refused inside a "
                    "batch, route by hand",
                    file=sys.stderr,
                )
        return EXIT_OK if dr.ok else 1

    sentinel.heartbeat()  # mutating invocation class (08 §1)
    result = batch.run(home, items, no_push=args.no_push)
    if args.as_json:
        print(json.dumps(result.to_json()))
    else:
        for it in result.items:
            line = f"  [{it.n}] {it.id} {it.verb}: {it.state}"
            if it.detail:
                line += f" — {it.detail}"
            print(line)
        summary = result.summary
        print(
            f"self-learn batch: {summary['applied']} applied, "
            f"{summary['already_applied']} already-applied, "
            f"{summary['refused']} refused (of {summary['total']})",
            file=sys.stderr,
        )
        if result.stopped_at is not None:
            print(
                f"self-learn batch: stopped at item {result.stopped_at} "
                "— ledger-level failure, unsafe to keep writing",
                file=sys.stderr,
            )
    return result.process_code


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
        "rescope",
        "supersede",
        "confirm-recurrence",
        "confirm-held",
        "dismiss-suspect",
        # U-verbs Phase 1: undefer/reopen/note dispatch through the same
        # `_cmd_verb` ladder and therefore ride the SAME flush call site
        # (§3.3c) — no eighth caller added.
        "undefer",
        "reopen",
        "note",
        # U-verbs Phase 2: reroute/reclassify dispatch through the SAME
        # `_cmd_verb` ladder too — no new caller of the epilogue.
        "reroute",
        "reclassify",
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


#: NIT-2 (code-gate review r1 2026-09-01): a `config set` VALUE token
#: beginning with `-` that argparse reads as an attempted FLAG (not a
#: value) is swallowed by argparse's own optional-argument matching
#: before `_cmd_config` ever runs, and the user sees a generic "the
#: following arguments are required: value" instead of anything
#: explaining what happened. argparse's own `--` separator already
#: handles this correctly (`config set NAME --json -- -abc` works
#: today, unmodified) -- `_swallowed_config_set_value` is a narrow
#: PRE-CHECK, run before the real parser even sees argv, that
#: recognizes exactly this one swallowed-value shape and prints a clear
#: pointer at `--` instead of argparse's confusing message. It never
#: fires when `--` is already present (that already parses correctly)
#: or when VALUE is one of the many shapes argparse's OWN internal
#: "looks like a negative number" heuristic already lets through
#: unassisted (`-5`, `-5.5`, `-5e10`, and less obviously `-1abc`,
#: `-5.5.5`, `-1_000` -- measured on this interpreter: a hand-written
#: `^-\d+$`-style regex guess was WRONG about several of these, so
#: :func:`_looks_option_like` asks argparse's own matcher directly
#: rather than re-deriving its rule) -- see `test_config_cli.py`'s
#: NIT-2 cases for the exact shapes covered.
_PROBE_PARSER = argparse.ArgumentParser(add_help=False)


def _looks_option_like(token: str) -> bool:
    """True iff argparse's OWN optional-argument matcher would treat
    `token` as an attempted flag rather than an ordinary positional
    value -- delegates to `ArgumentParser._parse_optional` (a private
    method, but the exact logic the real `config set` subparser applies
    when it decides whether a token is "still might be an option"). A
    throwaway parser with zero registered options classifies identically
    to `cset` for this purpose: the special case that lets a
    negative-looking token through does not depend on what options are
    registered, only on argparse's own internal heuristic for "looks
    like a negative number." Falls back to "not option-like" (never
    flags anything) if this private method is ever removed in some
    future Python -- degrades to argparse's own native error message,
    never a crash."""
    parse_optional = getattr(_PROBE_PARSER, "_parse_optional", None)
    if parse_optional is None:
        return False
    try:
        return parse_optional(token) is not None
    except Exception:
        return False


def _swallowed_config_set_value(argv: list[str]) -> str | None:
    """Return the VALUE token `config set NAME VALUE` would lose to
    argparse's optional-argument matching, or `None` when nothing would
    be swallowed. Only ever looks at a `config set ...` argv shape --
    `config get`/`config unset` take no free-form VALUE positional and
    are not this Nit's concern."""
    if len(argv) < 2 or argv[0] != "config" or argv[1] != "set":
        return None
    rest = argv[2:]
    pre_separator_positionals: list[str] = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--":
            break  # everything after this is already correctly escaped
        if tok == "--json":
            i += 1
            continue
        if tok == "--note":
            i += 2  # the flag and its own value -- neither is VALUE
            continue
        if tok.startswith("--note="):
            i += 1
            continue
        pre_separator_positionals.append(tok)
        i += 1
    if len(pre_separator_positionals) != 2:
        # 0/1: too few tokens to have reached VALUE yet. >2: a shape
        # argparse will refuse on its own terms either way -- not this
        # check's job.
        return None
    value_tok = pre_separator_positionals[1]
    if not _looks_option_like(value_tok):
        return None
    return value_tok


def _main(argv: list[str] | None = None) -> int:
    resolved_argv = argv if argv is not None else sys.argv[1:]
    swallowed = _swallowed_config_set_value(resolved_argv)
    if swallowed is not None:
        print(
            f"self-learn config set: {swallowed!r} looks like a flag, not "
            "a value -- put `--` before it, e.g. "
            f"`self-learn config set NAME -- {swallowed}`",
            file=sys.stderr,
        )
        return 2  # matches what argparse itself would have exited with here
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
    # MINOR 3 (code gate): `init` is the one verb whose premise is that
    # the home may not exist or may be unusable — ticking the miner
    # watchdog first spawned a detached run against a home `init` was
    # about to refuse.
    if args.command not in ("mine", "init", "serve"):
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

    if args.command == "init":
        return _cmd_init()

    if args.command == "status":
        if args.fast:
            return _cmd_status_fast()
        return _cmd_status(as_json=args.as_json)

    if args.command == "list":
        return _cmd_list(
            as_json=args.as_json,
            include_deferred=args.include_deferred,
            surface_fill=args.surface_fill,
            record_id=args.record_id,
        )

    if args.command == "show":
        # U-verbs §4.3 (SHOW3): read-only — deliberately NOT in
        # VERB_COMMANDS, so no flush runs here (the flush COMMITS).
        return _cmd_show(args)

    if args.command in ("teach", "import", "prune-memory", "proposal", "report"):
        sentinel.heartbeat()  # 08 §1: every mutating invocation touches a
        # live sentinel; heartbeat never resurrects a stale one.
        # (`telemetry note` is cache-only and model-emittable — it must
        # not extend a review hold's liveness; `telemetry flush` heartbeats
        # in its own branch.)

    if args.command == "teach":
        code = run_teach(args)
        # teach is a flushing verb (11 §4.2); --no-push rides along
        _mutating_epilogue(no_push=getattr(args, "no_push", False))
        # Kick when a PENDING record landed (08 §7.1 trigger pin):
        # plain teach success, or a --route that fell back to pending (4).
        if (code == EXIT_OK and not args.route) or code == 4:
            _kick_after_capture(no_push=getattr(args, "no_push", False))
        return code

    if args.command == "route" and getattr(args, "dry_run", False):
        # U-verbs §4.3 (DRY3, code gate B1): a preview only — deliberately
        # NOT dispatched through VERB_COMMANDS, same reasoning as `show`
        # (SHOW3) just above: VERB_COMMANDS's flush COMMITS (and, without
        # --no-push, PUSHES) whenever the telemetry spool is non-empty, and
        # a read-only preview must never move the ledger's HEAD. `_cmd_verb`
        # itself already special-cases this branch first, before any lock
        # or sentinel — routing it here just keeps it off the epilogue.
        return _cmd_verb(args)

    if args.command in VERB_COMMANDS:
        code = _cmd_verb(args)
        # every resolution verb flushes (11 §4.2); --no-push rides along
        _mutating_epilogue(no_push=getattr(args, "no_push", False))
        return code

    if args.command == "followup":
        code = _cmd_followup(args)
        _mutating_epilogue(no_push=getattr(args, "no_push", False))
        return code

    if args.command == "link":
        code = _cmd_link(args)
        _mutating_epilogue(no_push=getattr(args, "no_push", False))
        return code

    if args.command == "telemetry":
        return _cmd_telemetry(args)

    if args.command == "report":
        return _cmd_report(as_json=args.as_json)

    if args.command == "push":
        return _cmd_push()

    if args.command == "batch":
        return _cmd_batch(args)

    if args.command == "doctor":
        return _cmd_doctor(args)

    if args.command == "config":
        return _cmd_config(args)

    if args.command == "reconcile":
        return _cmd_reconcile(args)

    if args.command == "host":
        return _cmd_host(args)

    if args.command == "bucket":
        return _cmd_bucket(args)

    if args.command == "recompile":
        sentinel.heartbeat()  # mutating invocation class (08 §1)
        return _cmd_recompile(args)

    if args.command == "sentinel":
        return _cmd_sentinel(args.action)

    if args.command == "import":
        code = _cmd_import(args)
        # import is a flushing verb (11 §4.2); --no-push rides along
        _mutating_epilogue(no_push=getattr(args, "no_push", False))
        if code == EXIT_OK:
            _kick_after_capture(no_push=getattr(args, "no_push", False))
        return code

    if args.command == "worker":
        return _cmd_worker(args)

    if args.command == "serve":
        return _cmd_serve(args)

    if args.command == "mine":
        return _cmd_mine(args)

    if args.command == "canary":
        return _cmd_canary(args)

    if args.command == "prune-memory":
        return _cmd_prune_memory(args)

    if args.command == "proposal":
        return _cmd_proposal(args)

    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


def entrypoint() -> None:  # console-script target
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
