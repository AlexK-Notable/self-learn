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
from typing import Any

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import analyst, gitops, telemetry, verbs
from .primitives import chrono
from .compilers import CompileError
from .gitops import EXIT_GIT_FAILED as _EXIT_GIT_FAILED
from .gitops import EXIT_HALF_WRITTEN as _EXIT_HALF_WRITTEN
from .ledger import EXIT_NO_HOME as _EXIT_NO_HOME
from .ledger import home_state, home_state_message, resolve_home
from .ledger_ops import LedgerOpsError, create_record, record_title
from .records import GENERALITIES, KINDS, RECORD_ID_RE, Record, RecordError
from .scan import format_refusal, redact, scan

__all__ = ["add_teach_parser", "infer_type", "run_teach"]

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SCAN = 3
EXIT_ANALYST = 4  # analysis/route failed — record captured to pending/
# 5, 6 and 7 are the SHARED codes, imported (not re-pinned) from the
# modules that own the concepts — see their docstrings. teach used to
# return its own EXIT_USAGE(2) for a bad home while all eight other
# surfaces returned 5 (audit 2026-07-16 MINOR G); importing is what keeps
# that unified. Round 7 BLOCKER 2: sharing the INTEGER was never enough —
# teach documented 6 as "the record IS written", the verbs documented the
# same 6 as "nothing was written", and both were right about themselves.
# One code, one state fact, every surface: 6 = nothing written · 7 = the
# write landed, its commit did not.
EXIT_NO_HOME = _EXIT_NO_HOME              # bad ledger home — nothing written
EXIT_GIT_FAILED = _EXIT_GIT_FAILED        # git failed BEFORE any write
EXIT_HALF_WRITTEN = _EXIT_HALF_WRITTEN    # record WRITTEN but not committed

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
    # 11 §3 capture-time grounding — optional-but-offered; cheap while the
    # wound is fresh, unreconstructable later. Bare-CLI teach never prompts.
    p.add_argument(
        "--verified",
        action="store_true",
        help="the lesson was verified at capture (repro'd, tested)",
    )
    p.add_argument(
        "--verified-how",
        dest="verified_how",
        metavar="TEXT",
        help="with --verified: how it was verified",
    )
    p.add_argument(
        "--incident-cost",
        dest="incident_cost",
        metavar="TEXT",
        help="what the incident cost, in human terms ('an evening')",
    )
    p.add_argument(
        "--generality",
        choices=tuple(sorted(GENERALITIES)),
        help="environment quirk or general practice? (the strongest known "
        "predictor of behavioral value)",
    )
    p.add_argument(
        "--env",
        action="append",
        metavar="COMPONENT=VERSION",
        help="version present at capture (repeatable; user entries win "
        "over ambient hints)",
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
    p.add_argument(
        "--hook-input",
        dest="hook_input",
        metavar="YAML",
        help="with --route --dest hook (config-gated, S-10 amendment): the "
        "compile input file — {rationale, hook: {tools, path_regex, "
        "deny_message}, examples: {allow, deny}}; the CLI generates the "
        "script, validates, scans, replays, and prints the applied bytes",
    )
    return p


def _home_gate(home) -> int | None:
    """teach's WRITE-surface home gate — the same answer every other
    surface gives (:data:`EXIT_NO_HOME`), refused before anything is
    written. ledger_ops.require_writable_home also refuses, but as a
    LedgerOpsError that teach mapped onto its own EXIT_USAGE(2) — a code
    that means "you typed the command wrong", not "your ledger is
    missing" (audit 2026-07-16 MINOR G)."""
    state = home_state(home)
    if state in ("missing", "not-a-repo"):
        print(f"self-learn teach: {home_state_message(state, home)}", file=sys.stderr)
        return EXIT_NO_HOME
    return None


def _fail(msg: str) -> int:
    print(f"self-learn teach: {msg}", file=sys.stderr)
    return EXIT_USAGE


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _now_iso() -> str:
    return chrono.now_iso()


def _project_path() -> Path:
    """Project scope binds to THIS session's project (doc 13 §3: producers
    know the path — teach uses cwd): the git toplevel of cwd, else cwd."""
    return gitops.toplevel(Path.cwd()) or Path.cwd()


def _capture_txn(
    home: Path,
    record: Record,
    project_path: Path | None,
    *,
    no_push: bool = False,
) -> tuple[Path, bool]:
    """Write the record and commit it as ONE locked transaction, then push
    outside the lock. Returns (path, committed).

    H-5 (doc 13 §5): producers commit their own writes — every capture gets
    an attributable ledger commit (pinned subject) + best-effort push;
    pending captures no longer ride anonymous autosync commits. Under H-5
    there is no watcher and every other producer stages only its own paths,
    so a capture that fails to commit is committed by nobody, ever. That
    makes it a FAILURE, not a warning (audit 2026-07-16 BLOCKER B — probed:
    `teach` blocked 120 s behind a hanging push, printed "created lrn-…",
    then **exited 0** on an uncommitted record, while claiming "nothing was
    written").

    **The lock opens before ``create_record``** (audit 2026-07-16 round 7 —
    the invariant: no ledger mutation may precede its lock). It used to
    open at the commit, which made teach's exit 6 mean "the record IS
    written but uncommitted" while the SAME code on the resolution verbs
    meant "nothing was written" — one integer, two opposite states, each
    documented as the truth in a different command file. With the lock
    first, teach's codes say what every other surface's say: a lock
    timeout is a clean refusal that wrote nothing (:data:`EXIT_GIT_FAILED`,
    re-run it), and only a COMMIT failure is half-written
    (:data:`EXIT_HALF_WRITTEN`, repair printed).

    Creating a record is the benign half of the invariant (a new file is
    untracked, and an autostash cannot see it) — but ``meta.yaml`` is
    tracked once the bucket has been committed once, and defence in depth
    against a data-loss class is worth a lock held for the milliseconds of
    a local write.

    The push sits OUTSIDE the lock (a push touches no index — see the
    ``gitops`` module docstring for the re-scope). ``no_push`` honors
    ``teach --no-push`` on the capture path: the flag used to bind only
    ``--route``, so a plain ``teach --no-push`` pushed here regardless."""
    message = f"self-learn: capture {record.id} ({record.scope})"
    with gitops.commit_lock(home):  # BEFORE the first mutation
        path = create_record(home, record, project_path=project_path)
        touched = [path]
        meta = path.parent.parent / "meta.yaml"
        if meta.is_file():
            touched.append(meta)
        try:
            gitops.stage(home, touched)
            gitops.commit(home, message, paths=touched)
        except gitops.GitOpsError as exc:
            print(
                f"self-learn: CAPTURE NOT COMMITTED ({exc})\n"
                f"  The record IS written: {path}\n"
                "  Nothing else will ever commit it (doc 13 H-5: no watcher "
                "on the ledger; every other producer stages only its own "
                "paths), so a re-clone would destroy it.\n"
                f"  Repair: self-learn reconcile   (or, by hand: "
                f"git -C {home} add -- {path} && git -C {home} commit "
                f"-m {message!r})",
                file=sys.stderr,
            )
            return path, False
    if not no_push:
        try:
            gitops.push_if_remote(home)
        except gitops.GitOpsError as exc:
            # The commit is safe; only publication failed. Loud, not fatal —
            # `self-learn push` republishes it (unlike an uncommitted record,
            # a local commit is not one clone away from gone).
            print(
                f"self-learn: capture committed but NOT pushed ({exc}) — run "
                "`self-learn push` to publish it",
                file=sys.stderr,
            )
    return path, True


def run_teach(args: argparse.Namespace) -> int:
    # ---- --route flag-family validation (before anything composes)
    for flag, given in (
        ("--dest", args.dest is not None),
        ("--note", args.note is not None),
        ("--no-push", args.no_push),
        ("--hook-input", args.hook_input is not None),
    ):
        if given and not args.route:
            return _fail(f"{flag} needs --route")
    if args.route and args.dest is not None:
        try:
            destination, _ = verbs._parse_dest(args.dest)
        except verbs.VerbError as exc:
            return _fail(str(exc))
        # S-10 amendment 2026-07-16: the refusal is the DEFAULT, opted out
        # of only by the committed <home>/config.yaml (fail-closed parse).
        # The message is unchanged from the hard-coded era.
        if not verbs.one_motion_allowed(resolve_home(), destination):
            return _fail(
                f"destination {destination!r} cannot be routed in one "
                "motion — capture without --route, then `self-learn route "
                "<id> --dest "
                + ("hook` (with an approved hook proposal)" if destination == "hook"
                   else "new-skill:<name>`")
            )
        if args.hook_input is not None and destination != "hook":
            return _fail("--hook-input needs --route --dest hook")
    elif args.hook_input is not None:
        return _fail("--hook-input needs --route --dest hook")

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

    # ---- 11 §3 capture-time grounding (optional-but-offered)
    if args.verified_how and not args.verified:
        return _fail("--verified-how needs --verified")
    try:
        if args.verified:
            record.set_verified(True, how=_clean(args.verified_how))
        if args.incident_cost is not None:
            record.set_incident_cost(_clean(args.incident_cost))
        if args.generality is not None:
            record.set_generality(args.generality)
        if args.env:
            env: dict = {}
            for item in args.env:
                key, sep, value = item.partition("=")
                if not sep or not key.strip() or not value.strip():
                    return _fail(f"--env needs COMPONENT=VERSION, got {item!r}")
                env[key.strip()] = value.strip()
            record.set_env(env)
    except RecordError as exc:
        return _fail(str(exc))

    # Free-text metadata is published in the record file: scan ALL of it
    # like the body — verified_how/incident_cost, every --env key and
    # value, and the --session id (audit 2026-07-15: --env values escaped
    # the scan; with --route the secret would have been committed and
    # pushed). No redact path here — a hit refuses outright (short
    # user-typed phrases; retype them clean).
    meta_texts = [args.verified_how, args.incident_cost, session]
    for item in args.env or ():
        meta_texts.append(item)
    meta_hits = [h for text in meta_texts if text for h in scan(text)]
    if meta_hits:
        print(format_refusal(meta_hits), file=sys.stderr)
        return EXIT_SCAN

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

    project_path = _project_path() if scope == "project" else None

    if args.route:
        return _route_now(args, record, project_path)

    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    try:
        # H-5: producers commit their writes. no_push is always False here
        # today (validation makes --no-push imply --route), passed for
        # correctness if that pin ever widens.
        path, committed = _capture_txn(
            home, record, project_path, no_push=args.no_push
        )
    except LedgerOpsError as exc:
        return _fail(str(exc))
    except gitops.GitOpsError as exc:
        # The lock is taken BEFORE the write (round 7), so this is the one
        # git failure teach can honestly call clean: nothing was written.
        print(
            f"self-learn teach: {exc}\n"
            "  Nothing was written — re-run this command once the other "
            "producer finishes.",
            file=sys.stderr,
        )
        return EXIT_GIT_FAILED

    # Code-emitted capture event (11 §4.3) — the accepted-offer half of the
    # denominator; the declined half is `telemetry note offer-declined`.
    telemetry.spool_quiet(
        "capture", source="teach", scope=record.scope, record=record.id
    )

    if args.supersedes is not None:
        print(
            f"supersedes {args.supersedes} (link recorded at capture; "
            "the old record resolves when this one routes)"
        )
    kind_part = f" ({record.kind})" if record.kind else ""
    print(f"created {record.id} → {path}")
    print(f"  {record.type}{kind_part} · {record.scope} · {record_title(record)}")
    # An uncommitted capture is a FAILURE, not a footnote (BLOCKER B): with
    # no watcher (H-5) nothing else will ever commit it. _capture_txn has
    # already printed what is wrong and how to repair it. The code is
    # HALF_WRITTEN, not GIT_FAILED (round 7 BLOCKER 2): the record is on
    # disk, which is the opposite of 6's promise.
    return EXIT_OK if committed else EXIT_HALF_WRITTEN


# --------------------------------------------------------------- --route (T8)


def _capture_to_pending(
    home,
    record_text: str,
    reason: str,
    hint: str,
    project_path: Path | None,
    *,
    no_push: bool = False,
) -> int:
    """Fallback on any post-composition routing failure: the composed
    record (pristine, pre-routing-mutation snapshot) is captured to
    ``pending/`` as a NORMAL teach — the lesson is never lost.

    ``no_push`` carries the route's ``--no-push`` onto the fallback
    (BLOCKER 3): this is the live teach path that KICKS a worker (the CLI
    kicks on exit 4), so it is exactly where an unbound flag leaked."""
    record = Record.from_text(record_text)
    try:
        # H-5: still a producer write
        path, committed = _capture_txn(home, record, project_path, no_push=no_push)
    except (LedgerOpsError, gitops.GitOpsError) as exc:
        # capture itself failed — nothing written (the lock is taken before
        # the write, round 7)
        print(f"self-learn teach: {reason}", file=sys.stderr)
        return _fail(f"and the pending capture also failed: {exc}")
    print(
        f"self-learn teach: {reason} — record captured to pending; {hint}",
        file=sys.stderr,
    )
    # Still a capture (audit 2026-07-15): an uncounted fallback would push
    # report's "ceiling" below the true rate, breaking the label's meaning.
    telemetry.spool_quiet(
        "capture", source="teach", scope=record.scope, record=record.id
    )
    print(f"created {record.id} → {path} (pending)")
    # EXIT_ANALYST(4) promises "safely captured to pending/, nothing lost".
    # If the commit failed that promise is FALSE, and the stronger, truer
    # code wins (BLOCKER B; round 7: and the true code for "written but not
    # committed" is HALF_WRITTEN, not GIT_FAILED).
    return EXIT_ANALYST if committed else EXIT_HALF_WRITTEN


def _route_now(
    args: argparse.Namespace, record: Record, project_path: Path | None
) -> int:
    """The one-motion path: destination (``--dest``, or the one-shot
    analyst), then :func:`verbs.route_direct` — straight to ``resolved/``,
    compile, diff print, pinned commit, push. Invocation = approval: no
    confirmation prompt anywhere (08 §1 `teach --route` pin)."""
    home = resolve_home()
    if (code := _home_gate(home)) is not None:
        return code
    dest = args.dest
    # FW-64: captured BEFORE the bare-`--route` branch below overwrites
    # `dest` with the analyst's own proposal — `by` must record who chose
    # the destination, and that is decided entirely by whether the human
    # typed --dest, not by whatever `dest` holds by the time route_direct
    # is called. An explicit --dest is always the human's flag, whether
    # typed at the terminal or (T8/CLI-only path) supplied programmatically.
    by = "human" if args.dest is not None else "analyst"

    hook_input = None
    if args.hook_input is not None:
        # S-10 one-motion hook: the compile-input file. Fail-closed load —
        # any parse problem is a usage refusal before anything composes.
        try:
            loaded = YAML(typ="safe").load(
                Path(args.hook_input).read_text(encoding="utf-8")
            )
        except (OSError, YAMLError, UnicodeDecodeError) as exc:
            return _fail(f"--hook-input unreadable: {exc}")
        if not isinstance(loaded, dict):
            return _fail("--hook-input must be a YAML mapping (doctrine §5.1)")
        hook_input = loaded

    if dest is None:
        # Bare --route: the one-shot analyst (flags in self_learn.analyst).
        doctrine = analyst.doctrine_path()
        if not doctrine.is_file():
            return _fail(f"routing doctrine not installed — T10 ({doctrine})")
        # U-corrob (`DEN3`, 2026-08-28): a caller-owned accumulator, the
        # same shape `FW-107` uses on the worker leg -- `analyze` extends
        # it with this invocation's charter-sourced denials whether it
        # returns or raises, so the line below fires on BOTH branches of
        # this `try` (the only surface where an analyst denial has ever
        # been silently invisible before this unit: 16 of 22 analyst tool
        # calls in the corpus errored with no denial line anywhere).
        charter_denials: list[dict[str, Any]] = []
        try:
            proposal = analyst.analyze(
                home, record, project_path=project_path, charter_denials=charter_denials,
            )
        except analyst.AnalystError as exc:
            if charter_denials:
                tools = sorted({tool for d in charter_denials if (tool := d.get("tool"))})
                print(
                    f"analyst: {len(charter_denials)} charter denial(s) this run "
                    f"({', '.join(tools)})"
                )
            return _capture_to_pending(
                home,
                record.to_text(),
                f"analysis failed ({exc})",
                "run review or route --dest",
                project_path,
                no_push=args.no_push,
            )
        if charter_denials:
            tools = sorted({tool for d in charter_denials if (tool := d.get("tool"))})
            print(
                f"analyst: {len(charter_denials)} charter denial(s) this run "
                f"({', '.join(tools)})"
            )
        dest = proposal["destination"]
        rationale = proposal.get("rationale") or ""
        print(f"analyst: destination {dest} — {rationale}")
        if dest == "hook" and hook_input is None:
            # config-enabled one-motion: the analyst's proposal IS the
            # compile input (it carries the §5.1 hook block + examples,
            # or route_direct's validation refuses and the capture falls
            # back to pending — never lost).
            hook_input = proposal

    snapshot = record.to_text()  # pristine copy for the never-lost fallback
    try:
        result = verbs.route_direct(
            home,
            record,
            dest=dest,
            by=by,
            note=args.note,
            no_push=args.no_push,
            project_path=project_path,
            hook_input=hook_input,
        )
    except verbs.SecretRefusal as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_SCAN
    except (
        verbs.VerbError,
        LedgerOpsError,
        CompileError,
    ) as exc:
        return _capture_to_pending(
            home,
            snapshot,
            f"route failed ({exc})",
            "fix the cause, then `self-learn route <id>`",
            project_path,
            no_push=args.no_push,
        )

    telemetry.spool_quiet(
        "capture", source="teach", scope=record.scope, record=record.id
    )

    # The applied diff — printed, never prompted on (invocation = approval).
    if result.diff:
        print(result.diff, end="" if result.diff.endswith("\n") else "\n")

    if args.supersedes is not None:
        print(f"supersedes {args.supersedes}: completed in the same commit")
    # BOTH push phases, via the shared renderer (audit 2026-07-16 MAJOR 4:
    # this path read result.push only, so a failed HOST push printed
    # "(pushed)" and returned 0 — the canon commit unpublished and
    # unmentioned). Deferred import: cli imports this module.
    from .cli import push_note

    destination = (record.routing or {}).get("destination", dest)
    kind_part = f" ({record.kind})" if record.kind else ""
    print(
        f"routed {record.id} → {destination} @ {result.commit_sha[:7]} "
        f"({push_note(result)})"
    )
    if (budget_note := result.budget_note()) is not None:
        print(budget_note, file=sys.stderr)
    print(f"  {record.type}{kind_part} · {record.scope} · {record_title(record)}")
    # M3-11 (one-motion hook/new-skill, config-enabled): the required
    # manual steps — the guard stays inert until settings.json is edited.
    for note_line in result.post_notes:
        print(note_line)

    # EXIT 0 even when a push failed — the DOCUMENTED pin (08 §1; this
    # module's docstring: "A route that commits but fails to push still
    # exits 0: the commit is kept, the push failure is loud, and
    # `self-learn push` retries it").
    #
    # Audit 2026-07-16 BLOCKER 2: a fix batch folded gitops' push exits
    # into teach's return (`return push.exit_code`). But teach's 3 and 4
    # are ALREADY TAKEN and mean something else entirely —
    # EXIT_SCAN(3) = "secret scan refused → re-run with --redact" and
    # EXIT_ANALYST(4) = "record safely captured to pending/, nothing lost"
    # (commands/teach.md §5 tells the agent exactly that). gitops'
    # EXIT_PUSH_FAILED is 3 and EXIT_REBASE_CONFLICT is 4, so a routed,
    # compiled, committed record that merely failed to PUSH reported
    # itself as an unwritten scan refusal or a pending-bucket fallback —
    # both catastrophically wrong for a record that DID route.
    #
    # M4's exit-code folding is right for the `route` VERB, where
    # push-failure=3 is the established meaning; it must not extend here.
    # The failure is surfaced by push_note()'s "PUSH FAILED — commit kept;
    # run `self-learn push`" line above, per phase, ledger and host.
    if any(p is not None and not p.ok for p in (result.push, result.host_push)):
        print(
            "self-learn teach: the record is routed, compiled and committed; "
            "only the PUSH failed — nothing is lost. Run `self-learn push` to "
            "publish it.",
            file=sys.stderr,
        )
    return EXIT_OK
