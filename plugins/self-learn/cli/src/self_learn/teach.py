"""``self-learn teach`` — capture one lesson into the ledger (T5), or
route it in one motion (``--route``, T8).

Flag surface (01 §3.2 + 08 §1 pins):

  self-learn teach [LESSON]
    scope      ``--skill <name>`` | ``--project`` | ``--user``
               (mutually exclusive; default: project — 01 §2)
    typing     ``--type behavior|knowledge`` — inferred when omitted, and
               the inference is echoed for confirmation;
               ``--kind anti-pattern|surface-rule|reasoning-pattern``
               (behavior only; defaults to ``surface-rule``, echoed —
               02 §1 requires a kind on every behavior record and the
               T5 DoD invocation carries none)
    behavior   ``--trigger <text>`` (always required — the firing
               condition is the record's real key) ·
               ``--instruction <text>``
    knowledge  ``--fact <text>`` · ``--context <text>``
    evidence   ``--quote <text>`` + ``--session <id>``
               (``--evidence-session`` is an alias for ``--session`` —
               01 §3.2 names the long form)
    links      ``--supersedes <lrn-id>`` — capture half only: records the
               link on the NEW record; the old record is untouched until
               the replacement routes (T7/T8; 08 §1 gate-check F5)
    scan       ``--redact`` — the default policy on a secret-scan hit is
               REFUSE (print span + rule, write nothing, exit 3);
               ``--redact`` replaces each span with ``[redacted:<rule>]``
               and sets frontmatter ``redacted: true``; NO bypass flag
               in v1 (08 §1 Secret-scan pin)
    routing    ``--route`` — skip the pending bucket: compose → scan →
               write DIRECTLY to the bucket's ``resolved/`` as
               ``status: routed`` (02 §2 lifecycle note: never transiting
               ``pending/``) → compile → print the applied diff → pinned
               commit → push. NO confirmation prompt anywhere: invocation
               is the approval (08 §1 `teach --route` pin).
               ``--dest <target>`` makes the path deterministic and
               zero-model (in-session callers pass structured fields +
               ``--dest``); a bare ``--route`` with no ``--dest`` runs the
               one-shot ``claude -p`` analyst against the routing doctrine
               file — flags documented in :mod:`self_learn.analyst`.
               ``--note <text>`` → ``resolution_note`` + commit body;
               ``--no-push`` commits exactly as pinned, skips only the
               push. All three require/imply ``--route``.

Composition: structured fields win; the positional LESSON fills a missing
Instruction (behavior) or Fact (knowledge). Type inference heuristic
(deliberately simple, documented): a lesson opening with imperative /
trigger-ish language (never / always / don't / stop / avoid / when /
before / after / if …) → behavior; a declarative sentence → knowledge.

Scan-then-write (02 §2): the composed body and every evidence quote are
scanned BEFORE anything touches disk.

Exit codes: 0 created (or routed) · 2 usage/validation (nothing written;
includes a missing routing-doctrine file, pre-spawn) · 3 secret scan
refusal (nothing written) · 4 analyst failure — the record was safely
captured to ``pending/`` as a normal teach (never lost). A route that
commits but fails to push still exits 0: the commit is kept, the push
failure is loud, and ``self-learn push`` retries it.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone

from . import analyst, verbs
from .chezmoi import ChezmoiAbort, ChezmoiError
from .compilers import CompileError
from .ledger import resolve_home
from .ledger_ops import LedgerOpsError, create_record, record_title
from .records import KINDS, RECORD_ID_RE, Record, RecordError
from .scan import format_refusal, redact, scan

__all__ = ["add_teach_parser", "infer_type", "run_teach"]

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SCAN = 3
EXIT_ANALYST = 4  # analysis/route failed — record captured to pending/

DEFAULT_BEHAVIOR_KIND = "surface-rule"

#: The inference heuristic: an opening imperative / trigger-ish word reads
#: as a rule about *doing* (behavior); anything else reads as a stated fact
#: (knowledge). Kept simple on purpose — the echo line plus triage
#: re-classification make a wrong guess cheap (01 §2: mis-scoping/mis-filing
#: is cheap; the filing is never frozen).
_TRIGGERISH_RE = re.compile(
    r"^(?:never|always|don'?t|do\s+not|stop|avoid|use|prefer|check|verify"
    r"|ensure|run|ask|remember\s+to|when(?:ever)?|before|after|if|on)\b",
    re.IGNORECASE,
)


def infer_type(lesson: str) -> str:
    """behavior for imperative/trigger-ish openings, else knowledge."""
    return "behavior" if _TRIGGERISH_RE.match(lesson.strip()) else "knowledge"


def add_teach_parser(sub) -> argparse.ArgumentParser:
    p = sub.add_parser(
        "teach",
        help="capture one lesson into the ledger",
        description=(
            "Capture one lesson as a pending record. Structured fields win; "
            "the positional LESSON fills a missing Instruction/Fact."
        ),
    )
    p.add_argument("lesson", nargs="?", default=None, metavar="LESSON")
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--skill", metavar="NAME", help="skill scope (skill:<name> bucket)")
    scope.add_argument("--project", action="store_true", help="project scope (default)")
    scope.add_argument("--user", action="store_true", help="user scope")
    p.add_argument(
        "--type",
        choices=("behavior", "knowledge"),
        help="record type; inferred (and echoed) when omitted",
    )
    p.add_argument(
        "--kind",
        choices=tuple(sorted(KINDS)),
        help=f"behavior only; defaults to {DEFAULT_BEHAVIOR_KIND}",
    )
    p.add_argument("--trigger", metavar="TEXT", help="behavior: the firing condition")
    p.add_argument("--instruction", metavar="TEXT", help="behavior: what to do (and why)")
    p.add_argument("--fact", metavar="TEXT", help="knowledge: the fact")
    p.add_argument("--context", metavar="TEXT", help="knowledge: optional context")
    p.add_argument("--quote", metavar="TEXT", help="evidence quote (needs --session)")
    p.add_argument(
        "--session",
        "--evidence-session",
        dest="session",
        metavar="ID",
        help="evidence session id (--evidence-session is an alias)",
    )
    p.add_argument(
        "--supersedes",
        metavar="LRN_ID",
        help="record the corrective-supersession link on the new record",
    )
    p.add_argument(
        "--redact",
        action="store_true",
        help="on a secret-scan hit, redact spans instead of refusing",
    )
    p.add_argument(
        "--route",
        action="store_true",
        help="skip the bucket: analyze + apply + commit now (invocation = approval)",
    )
    p.add_argument(
        "--dest",
        metavar="TARGET",
        help="with --route: deterministic destination (skill-md | claude-md | "
        "reference[:<file>]); omitted → one-shot analyst",
    )
    p.add_argument(
        "--note",
        metavar="TEXT",
        help="with --route: resolution note (record frontmatter + commit body)",
    )
    p.add_argument(
        "--no-push",
        action="store_true",
        dest="no_push",
        help="with --route: commit exactly as pinned, skip only the push",
    )
    return p


def _fail(msg: str) -> int:
    print(f"self-learn teach: {msg}", file=sys.stderr)
    return EXIT_USAGE


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_teach(args: argparse.Namespace) -> int:
    # ---- --route flag-family validation (before anything composes)
    for flag, given in (
        ("--dest", args.dest is not None),
        ("--note", args.note is not None),
        ("--no-push", args.no_push),
    ):
        if given and not args.route:
            return _fail(f"{flag} needs --route")
    if args.route and args.dest is not None:
        try:
            destination, _ = verbs._parse_dest(args.dest)
        except verbs.VerbError as exc:
            return _fail(str(exc))
        if destination in verbs.M3_DESTINATIONS:
            return _fail(f"destination {destination!r} is not built until M3")

    lesson = _clean(args.lesson)
    trigger = _clean(args.trigger)
    instruction = _clean(args.instruction)
    fact = _clean(args.fact)
    context = _clean(args.context)
    quote = _clean(args.quote)
    session = _clean(args.session)

    behavior_flags = [
        name
        for name, value in (("--trigger", trigger), ("--instruction", instruction), ("--kind", args.kind))
        if value
    ]
    knowledge_flags = [
        name for name, value in (("--fact", fact), ("--context", context)) if value
    ]
    if behavior_flags and knowledge_flags:
        return _fail(
            f"conflicting structured flags: {'/'.join(behavior_flags)} are behavior "
            f"fields, {'/'.join(knowledge_flags)} are knowledge fields — one lesson, "
            "one type (02 §1)"
        )

    # ---- resolve type (explicit > structured-flag family > text heuristic)
    if args.type:
        rtype = args.type
        inferred = False
    elif behavior_flags:
        rtype, inferred = "behavior", True
    elif knowledge_flags:
        rtype, inferred = "knowledge", True
    elif lesson:
        rtype, inferred = infer_type(lesson), True
    else:
        return _fail("nothing to capture: pass a lesson text or structured fields")

    if rtype == "knowledge" and behavior_flags:
        return _fail(
            f"{'/'.join(behavior_flags)} appl{'ies' if len(behavior_flags) == 1 else 'y'} "
            "to behavior records only, but the type is knowledge"
        )
    if rtype == "behavior" and knowledge_flags:
        return _fail(
            f"{'/'.join(knowledge_flags)} appl{'ies' if len(knowledge_flags) == 1 else 'y'} "
            "to knowledge records only, but the type is behavior"
        )

    if inferred:
        print(f"type: {rtype} (inferred — pass --type to override)")

    # ---- remaining flag validation (before anything composes)
    if args.supersedes is not None and not RECORD_ID_RE.match(args.supersedes):
        return _fail(
            f"--supersedes must be a record id (lrn-<8 lowercase hex>), got {args.supersedes!r}"
        )
    if quote and not session:
        return _fail("--quote needs --session <id>: an evidence quote without its session pointer is unattributable (02 §1)")

    if args.skill is not None:
        skill = args.skill.strip()
        if not skill:
            return _fail("--skill needs a skill name")
        scope = f"skill:{skill}"
    elif args.user:
        scope = "user"
    else:
        scope = "project"  # default (01 §2)

    # ---- compose (structured fields win; positional fills the gap)
    try:
        if rtype == "behavior":
            if not trigger:
                return _fail(
                    "behavior records need --trigger (the firing condition — "
                    "02 §1's real key); pass it, or --type knowledge if this is a fact"
                )
            body_instruction = instruction or lesson
            if not body_instruction:
                return _fail(
                    "behavior records need an instruction: pass --instruction "
                    "or the positional lesson text"
                )
            kind = args.kind or DEFAULT_BEHAVIOR_KIND
            if args.kind is None:
                print(f"kind: {kind} (defaulted — pass --kind to override)")
            record = Record.create(
                type="behavior",
                scope=scope,
                source="teach",
                kind=kind,
                trigger=trigger,
                instruction=body_instruction,
            )
        else:
            body_fact = fact or lesson
            if not body_fact:
                return _fail(
                    "knowledge records need a fact: pass --fact or the positional lesson text"
                )
            record = Record.create(
                type="knowledge",
                scope=scope,
                source="teach",
                fact=body_fact,
                context=context,
            )
        if args.supersedes is not None:
            record.set_supersedes(args.supersedes)
    except RecordError as exc:
        return _fail(str(exc))

    # ---- scan-then-write (02 §2: full body + evidence quotes, before disk)
    body_hits = scan(record.body)
    quote_hits = scan(quote) if quote else []
    hits = body_hits + quote_hits
    if hits and not args.redact:
        print(format_refusal(hits), file=sys.stderr)
        return EXIT_SCAN
    if hits:
        if body_hits:
            record.set_body(redact(record.body)[0])
        if quote_hits:
            quote = redact(quote)[0]
        record.set_redacted(True)
        n = len(hits)
        print(f"secret scan: {n} span{'s' if n != 1 else ''} redacted")

    if session:
        entry: dict = {"session": session, "ts": _now_iso()}
        if quote:
            entry["quote"] = quote
        record.append_evidence(entry)

    if args.route:
        return _route_now(args, record)

    try:
        path = create_record(resolve_home(), record)
    except LedgerOpsError as exc:
        return _fail(str(exc))

    if args.supersedes is not None:
        print(
            f"supersedes {args.supersedes} (link recorded at capture; "
            "the old record resolves when this one routes)"
        )
    kind_part = f" ({record.kind})" if record.kind else ""
    print(f"created {record.id} → {path}")
    print(f"  {record.type}{kind_part} · {record.scope} · {record_title(record)}")
    return EXIT_OK


# --------------------------------------------------------------- --route (T8)


def _capture_to_pending(home, record_text: str, reason: str, hint: str) -> int:
    """Fallback on any post-composition routing failure: the composed
    record (pristine, pre-routing-mutation snapshot) is captured to
    ``pending/`` as a NORMAL teach — the lesson is never lost."""
    record = Record.from_text(record_text)
    try:
        path = create_record(home, record)
    except LedgerOpsError as exc:  # capture itself failed — nothing written
        print(f"self-learn teach: {reason}", file=sys.stderr)
        return _fail(f"and the pending capture also failed: {exc}")
    print(
        f"self-learn teach: {reason} — record captured to pending; {hint}",
        file=sys.stderr,
    )
    print(f"created {record.id} → {path} (pending)")
    return EXIT_ANALYST


def _route_now(args: argparse.Namespace, record: Record) -> int:
    """The one-motion path: destination (``--dest``, or the one-shot
    analyst), then :func:`verbs.route_direct` — straight to ``resolved/``,
    compile, diff print, pinned commit, push. Invocation = approval: no
    confirmation prompt anywhere (08 §1 `teach --route` pin)."""
    home = resolve_home()
    dest = args.dest

    if dest is None:
        # Bare --route: the one-shot analyst (flags in self_learn.analyst).
        doctrine = analyst.doctrine_path(home)
        if not doctrine.is_file():
            return _fail(f"routing doctrine not installed — T10 ({doctrine})")
        try:
            proposal = analyst.analyze(home, record)
        except analyst.AnalystError as exc:
            return _capture_to_pending(
                home,
                record.to_text(),
                f"analysis failed ({exc})",
                "run review or route --dest",
            )
        dest = proposal["destination"]
        rationale = proposal.get("rationale") or ""
        print(f"analyst: destination {dest} — {rationale}")

    snapshot = record.to_text()  # pristine copy for the never-lost fallback
    try:
        result = verbs.route_direct(
            home, record, dest=dest, note=args.note, no_push=args.no_push
        )
    except verbs.SecretRefusal as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_SCAN
    except (
        verbs.VerbError,
        LedgerOpsError,
        CompileError,
        ChezmoiAbort,
        ChezmoiError,
    ) as exc:
        return _capture_to_pending(
            home,
            snapshot,
            f"route failed ({exc})",
            "fix the cause, then `self-learn route <id>`",
        )

    # The applied diff — printed, never prompted on (invocation = approval).
    if result.diff:
        print(result.diff, end="" if result.diff.endswith("\n") else "\n")

    if args.supersedes is not None:
        print(f"supersedes {args.supersedes}: completed in the same commit")
    if result.push is None:
        push_note = "not pushed — --no-push"
    elif result.push.ok:
        push_note = "pushed"
    else:
        push_note = "PUSH FAILED — commit kept; run `self-learn push`"
    destination = (record.routing or {}).get("destination", dest)
    kind_part = f" ({record.kind})" if record.kind else ""
    print(
        f"routed {record.id} → {destination} @ {result.commit_sha[:7]} ({push_note})"
    )
    print(f"  {record.type}{kind_part} · {record.scope} · {record_title(record)}")
    return EXIT_OK
