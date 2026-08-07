"""models.py — PURE screen-state derivation (09 §3/§7, 10 §1 "Screen-state
derivation" pin): ``(list --json, status --json, report --json, mine
status --json, merge-yaml set, sentinel mtime) → screen model``.

Nothing in this module does I/O. Every function takes already-loaded data
(CLI JSON as plain dicts wrapped in :class:`CliRead`, parsed proposal/merge
YAML as plain dicts, a parsed :class:`self_learn.records.Record`, the
card-sections registry as a plain list) and returns frozen dataclasses.
:mod:`self_learn_ui.ledger` is the ONLY module that touches a filesystem or
spawns a subprocess; it constructs the inputs these functions consume.

Three screen models, one per surface (09 §2):

- :func:`build_front_model` → :class:`FrontModel` (09 §2.1: bucket walk +
  status strip + Y-4 "is it holding?" + Y-6 follow-ups + Y-5 miner block).
- :func:`build_bucket_model` → :class:`BucketModel` (09 §2.2: grouped
  pending records, cluster rows, bulk collapse, Y-9/Y-11).
- :func:`build_detail_model` → :class:`DetailModel` (09 §2.3: card
  sections rendered generically off the registry, finding/change/why
  regions, Y-7/Y-8/Y-9/Y-11).

Y-10 (accessibility): every badge/status distinction carries a non-empty
text label — never hue alone. :class:`Badge` is the shared carrier; every
``*_label`` field is likewise always a non-empty string.

Y-9 (human-language-first): the leading text of any row/card is the
proposal's leading card section (registry order) or the record title —
NEVER a raw id, enum value, or scope slug. :func:`leading_text` is the one
place this is decided.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from self_learn import sentinel as sl_sentinel
from self_learn import worker as sl_worker
from self_learn.records import Record

__all__ = [
    "HOOK_VERBATIM_CAPTION",
    "NO_ANALYSIS_MESSAGE",
    "PARAMETER_FREE_DESTINATIONS",
    "PREVIEW_HONESTY_CAPTION",
    "REFERENCE_NO_CAP_LINE",
    "RULES_SCOPES",
    "ArchiveRow",
    "Badge",
    "BudgetRow",
    "BucketModel",
    "BucketRow",
    "BulkCollapseRow",
    "CanarySummary",
    "CardSection",
    "ChangeRegion",
    "ClusterRow",
    "CliRead",
    "DestinationGroup",
    "DetailModel",
    "FindingRegion",
    "FollowupRow",
    "FrontModel",
    "HoldingRow",
    "MinerBlock",
    "MinerRun",
    "NearMissRow",
    "RecordRow",
    "ResolvedDetailModel",
    "ResolvedRoutingFacts",
    "StatusStrip",
    "WhyRegion",
    "build_archive_rows",
    "build_bucket_model",
    "build_card_sections",
    "build_detail_model",
    "build_front_model",
    "build_resolved_detail_model",
    "correct_destination",
    "destination_label",
    "destination_path",
    "destination_cycle_for",
    "destinations_for_scope",
    "parse_variant_qualifier",
    "proposed_destination",
    "rules_dest",
    "rules_firing_note",
    "host_add_command",
    "leading_text",
]

#: 09 §2.3 action bar `o` pin: destinations a cycling key can supply
#: without extra structure. ``new-skill:<name>`` and ``hook`` need
#: structure a cycling key cannot supply (reachable via Iterate/CLI).
PARAMETER_FREE_DESTINATIONS: tuple[str, ...] = ("skill-md", "claude-md", "reference")

#: 09 §2.3 as amended 2026-07-18 (feedback round 2 item 3): the CLI's
#: own scope rules (the route verb's ``_resolve_target``), projected
#: onto the parameter-free set — skill-md needs ``skill:<name>`` scope;
#: reference needs skill or project (S-23 (2): user scope has no
#: references dir — it is a pathed-rules-only cheap surface, not a
#: reference shelf); claude-md is valid for every scope. Keyed by
#: :class:`~self_learn_ui.ledger.RecordLocation` scope tags; unknown
#: scopes fall back to the everywhere-valid singleton so the surface
#: can never offer an impossible destination.
_SCOPE_DESTINATIONS: dict[str, tuple[str, ...]] = {
    "skill": PARAMETER_FREE_DESTINATIONS,
    "project": ("claude-md", "reference"),
    "user": ("claude-md",),
}

#: U-demand-user §3.3(c): scopes the CLI's own
#: ``_resolve_rules_target`` guard (``verbs.py``'s
#: ``if scope not in ("user", "project")``) admits for a rules route —
#: mirrored here as a NAMED agreement (A12) so the UI never offers what
#: the verb refuses. Skill scope is the P-A13 rules deferral.
RULES_SCOPES: frozenset[str] = frozenset({"user", "project"})

#: Y-9 wording for the corrected-default note: why the analyst's
#: suggestion cannot land here, in human words (no scope slugs).
#: U-demand-user §8A.2(3): ``reference``'s wording is keyed on the
#: SITUATION (a correction only ever fires for ``reference`` at user
#: scope — it is scope-valid everywhere else, so `correct_destination`
#: never reaches this reason at project/skill scope). S-23 (2) promotes
#: pathed rules to the cheap tier there, so the honest reason is that
#: user scope has no cheap reference surface at all — not "pick
#: claude-md instead", which reads as a routine scope correction and
#: would be an ambush on Approve (§8A.2's own tradeoff).
_DEST_CORRECTION_REASONS: dict[str, str] = {
    "skill-md": "which only exists for a skill's own lessons",
    "reference": (
        "which has no cheap surface at user scope — S-23's cheap tier "
        "here is pathed rules, not a reference file"
    ),
}


#: A1 (labels-only claude-md spec, carved from the claude-md-
#: parameterization spec's F-1): ``claude-md`` alone resolves to three
#: different files by scope (verbs.py's route verb, claude-md branch,
#: ``verbs.py:575-603``) — ``_GROUP_LABELS["claude-md"]`` is scope-blind
#: and was rendering "Project instructions" over user/skill buckets
#: too. Keyed by SCOPE (the bare ``user``/``project``/``skill`` tags
#: ``_SCOPE_DESTINATIONS`` already uses), never by destination-enum
#: value — this is a scope specialization of the one polymorphic
#: destination, NOT a second enum->label map (P-A11): ``_GROUP_LABELS``
#: remains the only dict keyed by destination-enum values.
_CLAUDE_MD_SCOPE_LABELS: dict[str, str] = {
    "user": "User instructions",
    "project": "Project instructions",
    "skill": "Skills repo instructions",
}

#: P-A12: the resolved claude-md target path shown alongside the label
#: above, at the surfaces where a human commits to a file. Also
#: scope-keyed (same P-A11 reasoning as ``_CLAUDE_MD_SCOPE_LABELS`` —
#: not a second enum->label map). ``user``'s value is string-equal to
#: the CLI's ``DEFAULT_USER_CLAUDE_MD`` (``verbs.py:158``); ``project``/
#: ``skill`` are the schematic tokens verbs.py's own router resolves at
#: apply time (``verbs.py:587``/``:600``) — A1 threads no concrete host
#: path into the UI model.
_CLAUDE_MD_SCOPE_PATHS: dict[str, str] = {
    "user": "~/.claude/CLAUDE.md",
    "project": "<repo>/CLAUDE.md",
    "skill": "<skills root>/CLAUDE.md",
}

#: A2 §11 (widening A1, not forking it — same P-A11 reasoning as
#: ``_CLAUDE_MD_SCOPE_LABELS`` above): the ``rules`` variant's label,
#: keyed by scope. ``local`` has only one valid scope (project), so it
#: gets a single constant rather than a one-entry dict (§11's table:
#: local is project-only). Neither dict's keys are destination-enum
#: values — see :class:`TestNoSecondLabelMap` in the A1 test suite,
#: which this widening must keep passing.
_RULES_SCOPE_LABELS: dict[str, str] = {
    "user": "User rule",
    "project": "Project rule",
}

_LOCAL_LABEL = "Personal project notes"

#: A2 §11: the path templates paired with the labels above. ``{topic}``
#: is substituted by :func:`destination_path` when a topic is given.
_RULES_SCOPE_PATHS: dict[str, str] = {
    "user": "~/.claude/rules/{topic}.md",
    "project": "<repo>/.claude/rules/{topic}.md",
}

_LOCAL_PATH = "<repo>/CLAUDE.local.md"


def destination_label(
    value: str | None,
    scope: str | None = None,
    variant: str | None = None,
    rules_topic: str | None = None,
) -> str:
    """F5-9 (feedback round 5, U19 §1.5): Detail's action bar + Why
    region gloss every destination enum through this — the SAME
    ``_GROUP_LABELS`` map Bucket group headers already use (single
    source: no second label map may exist; a builder adding one breaks
    this rule). A live dict lookup, not a cached copy, so a corpus
    change to ``_GROUP_LABELS`` is reflected immediately, everywhere.
    ``None`` or an unrecognized value passes through unchanged (never a
    placeholder) — forms/argv keep the raw enum regardless; only the
    template's DISPLAY text goes through this.

    A1 widens this with an optional *scope*: ``claude-md`` alone
    resolves to three different files by scope (module docstring above
    ``_CLAUDE_MD_SCOPE_LABELS``), so a recognized scope substitutes the
    honest per-scope label. ``scope=None`` (the default) or any
    unrecognized scope — and every non-``claude-md`` value at ANY
    scope — falls through to today's gloss unchanged, so an
    un-updated caller degrades gracefully rather than crashing.

    A2 §11 ADDITIVELY widens this again with an optional *variant* (and
    *rules_topic*, only meaningful when ``variant == "rules"``) —
    ``variant=None`` (the default) reproduces A1's behavior exactly, so
    every existing caller is unaffected (P-A6-style no-migration for the
    label surface).

    U-demand-user §3.3(e): ADDITIVELY widens this a third time — when
    *variant* is left ``None`` (the caller has no separately-decoded
    variant, e.g. an action bar's ``dest`` field, which is the ONE
    string a qualified rules dest ever arrives as), decode *value*
    itself via :func:`parse_variant_qualifier`. A decode that yields a
    real variant treats *value* as ``claude-md`` for the branches below
    (so ``claude-md:rules:py-conventions`` glosses exactly like an
    already-decoded ``("claude-md", variant="rules",
    rules_topic="py-conventions")`` call would); a decode that yields
    nothing (an unqualified value, or a caller that already supplied its
    own *variant*) leaves *value*/*variant* untouched, so this widening
    is P-A6 no-migration for every existing caller — the ``value ==
    "claude-md"`` checks below still see a caller-supplied ``variant``
    exactly as before."""
    if value is None:
        return ""
    label_base = value
    if variant is None:
        decoded_variant, decoded_topic = parse_variant_qualifier(value)
        if decoded_variant is not None:
            variant, rules_topic = decoded_variant, decoded_topic
            label_base = "claude-md"
    if label_base == "claude-md" and variant == "rules" and scope in _RULES_SCOPE_LABELS:
        base = _RULES_SCOPE_LABELS[scope]
        return f"{base} — {rules_topic}" if rules_topic else base
    if label_base == "claude-md" and variant == "local" and scope == "project":
        return _LOCAL_LABEL
    if label_base == "claude-md" and scope in _CLAUDE_MD_SCOPE_LABELS:
        return _CLAUDE_MD_SCOPE_LABELS[scope]
    return _GROUP_LABELS.get(value, value)


def destination_path(
    scope: str | None, variant: str | None = None, rules_topic: str | None = None
) -> str:
    """P-A12: the §2 resolved claude-md path for *scope* — a plain
    static scope-keyed lookup (``_CLAUDE_MD_SCOPE_PATHS`` above),
    exposed alongside :func:`destination_label` so templates render the
    two together. ``None`` or an unrecognized scope returns ``""``
    (never a placeholder) — callers only invoke this once they already
    know the record's destination is ``claude-md``.

    A2 §11: *variant*/*rules_topic* additively widen this the same way
    they widen :func:`destination_label` — ``variant=None`` (the
    default) is byte-identical to A1's behavior."""
    if scope is None:
        return ""
    if variant == "rules" and scope in _RULES_SCOPE_PATHS:
        return _RULES_SCOPE_PATHS[scope].format(topic=rules_topic or "<topic>")
    if variant == "local" and scope == "project":
        return _LOCAL_PATH
    return _CLAUDE_MD_SCOPE_PATHS.get(scope, "")


def parse_variant_qualifier(dest: str | None) -> tuple[str | None, str | None]:
    """Decode a colon-qualified ``claude-md`` dest STRING (the pane
    proposal's own form — ``proposals.py``'s ``_DEST_RE`` grammar:
    ``claude-md:rules:<topic>`` / ``claude-md:local``) into the
    ``(variant, rules_topic)`` pair :func:`destination_label` /
    :func:`destination_path` take. This is the pane's ONLY variant
    signal — unlike the analyst's proposal.yaml, a ``VerbProposal``
    carries no separate ``variant``/``rules_topic`` fields (§4.1's
    string-qualified grammar IS its schema). ``(None, None)`` for
    ``None``, any unqualified dest, or any non-``claude-md`` dest
    (P-A6: no-migration — an un-widened caller's gloss is unaffected)."""
    if dest is None:
        return None, None
    base, sep, rest = dest.partition(":")
    if base != "claude-md" or not sep:
        return None, None
    if rest == "local":
        return "local", None
    if rest.startswith("rules:"):
        return "rules", rest.partition(":")[2] or None
    return None, None


def rules_firing_note(
    variant: str | None,
    scope: str | None,
    rules_paths: list[str] | tuple[str, ...] | None = None,
    *,
    adopted: bool = True,
) -> str:
    """A2 §11: the plain-words firing condition beside a variant label —
    P-A1's honest statement at the point of decision. A pathed rule
    names its glob; an unpathed one says it loads every session; an
    UNADOPTED user-scope rule (§10, P-A2b′) never implies cross-machine
    reach it does not have. ``""`` for anything this note does not
    apply to (plain claude-md, or a non-claude-md destination) — never a
    placeholder.

    U-demand-user §3.3(e) item 3 / A10: the pathed leg gains S-23's rider
    at USER scope only (project scope is byte-identical to before this
    unit) — a user-level glob resolves relative to the session's own
    working directory, never a repo, so it fires wherever a matching
    relative path exists, in ANY project. Stated plainly, and worded to
    invite no repo-targeting (no "this repo", no path-prefix suggestion,
    nothing implying the glob can be aimed)."""
    if variant == "local":
        return "loads every session in this project (you only)"
    if variant != "rules":
        return ""
    if rules_paths:
        globs = ", ".join(f"`{p}`" for p in rules_paths)
        if scope == "user":
            return (
                f"loads when you touch {globs} — matches relative to "
                "wherever the session is running, in any project"
            )
        return f"loads when you touch {globs}"
    if scope == "user" and not adopted:
        return "loads every session (this machine)"
    return "loads every session"


def destinations_for_scope(scope: str) -> tuple[str, ...]:
    """The `o`-cycle set for one record's scope (09 §2.3 as amended
    2026-07-18): only destinations the route verb can actually accept
    for that scope — prevention, so the confirm can never hand the CLI
    a structurally impossible ``--dest``."""
    return _SCOPE_DESTINATIONS.get(scope, ("claude-md",))


def rules_dest(scope: str | None, rules_topic: str | None) -> str | None:
    """U-demand-user §3.3(c): the ONE composition site for
    ``claude-md:rules:<topic>`` in this module (builder decision 2 — a
    second f-string of this shape anywhere in this unit's diff is a
    defect). ``None`` when *scope* is outside :data:`RULES_SCOPES` or
    *rules_topic* is falsy — the pathed tier is a per-record
    PARAMETERIZATION of ``claude-md``, never a scope-constant enum
    member (§3.3(b)), so it can only ever be composed here, from an
    actual topic, never minted by a keystroke."""
    if scope not in RULES_SCOPES or not rules_topic:
        return None
    return f"claude-md:rules:{rules_topic}"


def destination_cycle_for(scope: str, rules_topic: str | None) -> tuple[str, ...]:
    """U-demand-user §3.3(c): the per-record `o`-cycle —
    :func:`destinations_for_scope` with the pathed rules dest APPENDED
    (never prepended: ``cycle[0]`` is both the cycle's fallback and
    :func:`correct_destination`'s correction target, and this unit
    changes neither) when the record's own proposal names a topic.
    ``rules_topic=None`` reproduces :func:`destinations_for_scope`
    exactly (A7's own no-regression leg)."""
    base = destinations_for_scope(scope)
    extra = rules_dest(scope, rules_topic)
    if extra is None:
        return base
    return base + (extra,)


def correct_destination(
    scope: str, suggested: str | None
) -> tuple[str | None, str | None]:
    """09 §2.3 as amended 2026-07-18 (feedback round 2 item 3): the
    ``(default destination, plain-words note)`` the action bar presents.
    A scope-valid suggestion passes through untouched (note ``None``);
    a parameter-free suggestion the scope makes impossible (the live
    bug: skill-md proposed on a project record) becomes the scope's
    first valid destination plus a Y-9 note saying so — the value shown
    IS the value the arm/confirm executes. ``hook``/``new-skill`` (and
    no-analysis) stay ``(None, None)``: the route verb reads the
    proposal's own destination and remains the enforcer of their
    structural validity.

    U-demand-user §3.3(d): gains exactly ONE new leg, before the
    ``PARAMETER_FREE_DESTINATIONS`` guard below — a *suggested* that is
    ALREADY a qualified rules dest (``claude-md:rules:<topic>``) passes
    through unchanged, with no note, IFF the scope is in
    :data:`RULES_SCOPES` and the decoded topic is non-empty. This is the
    ECHO re-validator's leg (:func:`~self_learn_ui.routes._scope_
    corrected_dest` calls this on every unarmed re-render) — it never
    upgrades a bare enum to a qualified one (that would silently
    override a human's own demotion to plain ``claude-md`` — the
    FW-68/FW-69 defect class in the other direction); it only lets an
    ALREADY-qualified value survive the round trip. A scope outside
    ``RULES_SCOPES`` falls through to the unrecognized-value path below
    exactly as it did before this leg existed."""
    cycle = destinations_for_scope(scope)
    if suggested is not None and scope in RULES_SCOPES:
        suggested_variant, suggested_topic = parse_variant_qualifier(suggested)
        if suggested_variant == "rules" and suggested_topic:
            return suggested, None
    if suggested is None or suggested not in PARAMETER_FREE_DESTINATIONS:
        return None, None
    if suggested in cycle:
        return suggested, None
    corrected = cycle[0]
    reason = _DEST_CORRECTION_REASONS.get(suggested, "which this lesson's home cannot hold")
    note = f"the analyst suggested {suggested}, {reason} — corrected to {corrected}"
    return corrected, note


def _proposal_rules_topic(proposal: dict | None) -> str | None:
    """The ONE site that derives a record's own analyst-proposed rules
    topic from its (already-loaded) proposal dict — used by both
    :func:`proposed_destination`'s passthrough leg and the bucket-row
    cycle in :func:`build_bucket_model`, so the two can never drift
    apart. ``None`` unless the proposal names ``destination: claude-md``,
    ``variant: rules``, and a non-empty ``rules_topic`` — mirrors
    :func:`~self_learn_ui.routes._record_rules_topic`'s ledger-sourced
    gate exactly, just from an already-loaded dict rather than a fresh
    read."""
    proposal = proposal or {}
    if proposal.get("destination") != "claude-md" or proposal.get("variant") != "rules":
        return None
    topic = proposal.get("rules_topic")
    return topic if isinstance(topic, str) and topic else None


def _defer_note(scope: str, item_destination: str | None) -> str:
    """§8A.2(3), blind code-gate FOLD (round 1): the note must not lie
    about why nothing arms. The first cut delegated straight to
    :func:`correct_destination`, whose note always ends "— corrected to
    <X>" — but a `defer` recommendation corrects NOTHING (the bar arms
    NOTHING, not `<X>`), so that tail was a false claim every time this
    leg fired. This composes its own note instead: when the analyst's
    destination is scope-invalid, it reuses the SAME single-source
    reason text :func:`correct_destination` keys on
    (:data:`_DEST_CORRECTION_REASONS`) — informative context, never a
    correction claim; a generic, honest sentence otherwise (a
    scope-valid destination, or hook/new-skill/no-analysis, where
    nothing is wrong with the destination itself — only the
    recommendation blocks it)."""
    cycle = destinations_for_scope(scope)
    if (
        item_destination is not None
        and item_destination in PARAMETER_FREE_DESTINATIONS
        and item_destination not in cycle
    ):
        reason = _DEST_CORRECTION_REASONS.get(
            item_destination, "which this lesson's home cannot hold"
        )
        return (
            f"the analyst suggested {item_destination}, {reason} "
            "— deferred, no destination armed"
        )
    return "the analyst recommends deferring this lesson — no destination armed"


def proposed_destination(
    scope: str, item_destination: str | None, proposal: dict | None
) -> tuple[str | None, str | None]:
    """U-demand-user §3.3(d)/§8A.2: the armed default for a NEW page
    build (:func:`build_bucket_model`/:func:`build_detail_model`) — the
    load-bearing counterpart to :func:`correct_destination`'s echo-
    revalidator role (§3.3(d)'s own distinction: an INITIAL arm should
    produce the qualified dest for a rules proposal; a later re-render
    must never silently UPGRADE a human's own choice, which is why this
    is a separate function rather than one with a ``variant=`` kwarg).

    Two additive legs, checked in this order:

    (1) **H5 (§8A.2), load-bearing.** When the proposal's own
    ``recommendation`` is ``"defer"``, nothing arms — ``(None, note)``,
    where *note* is composed by :func:`_defer_note` (blind code-gate
    FOLD, round 1: this used to reuse :func:`correct_destination`'s own
    note, whose trailing "— corrected to <X>" clause LIED here — nothing
    is ever corrected on this leg, the bar arms nothing at all).
    ``_defer_note`` states the S-23 tier-fact reason when the analyst's
    destination is scope-invalid (``reference`` at user scope), and a
    generic honest sentence otherwise (e.g. ``claude-md`` at project
    scope, which was already scope-valid). This is checked FIRST — a
    defer recommendation means "no cheap surface fits this lesson
    here", which must win over any other leg. The `o` cycle can still
    reach a destination from an empty arm (an explicit human override,
    `dest_touched=True` → `by: human` — FW-64's own distinction, not the
    silent default H5 kills).

    (2) When *item_destination* is ``claude-md`` and the proposal names
    ``variant: rules`` with a topic :func:`rules_dest` accepts for
    *scope*, returns that qualified dest with NO note — the analyst's
    own choice needs no correction note (mirrors
    :func:`~self_learn_ui.routes._pending_dest_override`'s same
    distinction). A bare ``claude-md`` proposal, or one whose topic
    :func:`rules_dest` refuses (wrong scope), delegates unchanged.

    Otherwise delegates to :func:`correct_destination` unchanged — the
    byte-identical pre-existing behaviour for every non-rules,
    non-defer proposal."""
    proposal = proposal or {}
    if proposal.get("recommendation") == "defer":
        return None, _defer_note(scope, item_destination)
    if item_destination == "claude-md":
        dest = rules_dest(scope, _proposal_rules_topic(proposal))
        if dest is not None:
            return dest, None
    return correct_destination(scope, item_destination)

#: 02 §4's preview-honesty caption (standing, non-hook proposals/diffs).
PREVIEW_HONESTY_CAPTION = (
    "compilers regenerate from the record at apply time — this preview is "
    "advisory"
)

#: 09 §11 Y-7 — the M3 verbatim-apply caption for hook-destination proposals.
HOOK_VERBATIM_CAPTION = (
    "what you see IS the bytes the verb applies; a record_sha mismatch "
    "aborts at the verb, never silently regenerates"
)

#: 09 §11 Y-20 / 08 §1 F1 — the template-static line for `reference`: no
#: CLI datum, no probe (reference is the cap-free overflow sink entries
#: graduate INTO, so it has no fill to report against).
REFERENCE_NO_CAP_LINE = (
    "reference files have no cap — this is the overflow surface entries "
    "graduate into."
)

NO_ANALYSIS_MESSAGE = "no analysis yet — `i` to analyze now"

#: 09 §2.2 group labels — plain words, deliberately NOT "unanalyzed"
#: (W-6: that word names the Front page's eligibility *count*, a
#: different measure; distinct labels keep the two from being conflated).
_GROUP_LABELS: dict[str, str] = {
    "skill-md": "Skill doc",
    "claude-md": "Project instructions",
    "reference": "Reference file",
    "new-skill": "New skill",
    "hook": "Guard hook",
    "malformed": "Proposal needs repair",
    "no-analysis": "No analysis yet",
}
_GROUP_ORDER: tuple[str, ...] = (
    "skill-md",
    "claude-md",
    "reference",
    "new-skill",
    "hook",
    "malformed",
    "no-analysis",
)

_MINER_STATUS_LABELS: dict[str, str] = {
    "ok": "completed",
    "idle": "idle — nothing new to scan",
    "failed": "failed",
    "landed-uncommitted": "landed, not yet committed",
    "initialized": "initialized (first run)",
    "held-gate": "held at the pending gate",
}

#: 09 §11 Y-24 — the drill row's badge text per `disposition` (Y-10: a
#: badge is never hue alone). Rendered verbatim from the CLI's own fold
#: (miner.py's `disposition`) — this is display text ONLY, never a
#: re-derivation of which class an outcome falls into.
_NEARMISS_BADGE_LABELS: dict[str, str] = {
    "cap-refused": "cap refused",
    "rubric-dropped": "below the bar",
    "already-canon": "already canon",
    "rejected": "rejected",
    "scan-blocked": "scan blocked",
    "other": "not landed",
}


# --------------------------------------------------------------- CliRead


@dataclass(frozen=True)
class CliRead:
    """One CLI ``--json`` invocation's outcome. ``error`` is set (and
    ``data`` is ``None``) on ANY failure — spawn error, non-zero exit,
    unparseable JSON — so a CLI invocation failure surfaces as an explicit
    model state, never a silent empty list (task pin)."""

    data: Any | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# -------------------------------------------------------------- helpers


def _parse_dt(value: str | None) -> datetime | None:
    """Lenient ISO-8601 (or bare ``YYYY-MM-DD``) → aware UTC datetime."""
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _bare_scope(scope: object) -> str:
    """Reduce a RECORD's scope to a BUCKET's scope vocabulary.

    They are not the same alphabet, and the mismatch is a live trap: a
    bucket's scope is bare (``skill`` / ``project`` / ``user``), while a
    record's own ``scope`` field qualifies skills as ``skill:<name>``.
    Comparing the two directly looks obviously correct and silently drops
    every record in every skill bucket.

    Only the segment before the first colon is meaningful here, because
    the bucket NAME already carries the skill's identity — pairing this
    with the name is what makes ``(scope, name)`` a real bucket key."""
    return str(scope or "").split(":", 1)[0]


def _is_deferred(deferred_until: str | None, now: datetime) -> bool:
    """Deferred membership per 02 §2: ``deferred_until`` is in the FUTURE
    relative to ``now`` (a past date means deferral has lapsed — the
    record resurfaces, and ``deferred_until`` may still be populated)."""
    dt = _parse_dt(deferred_until)
    return dt is not None and dt > now


def host_add_command(scope: str, project_path: str | None) -> str | None:
    """09 §11 Y-11's exact copyable command. Only derivable for project
    buckets whose recorded ``meta.yaml`` path is known — a skill bucket's
    host path cannot be inferred from ledger data alone until *some*
    skills root is registered (there is no candidate path to suggest)."""
    if scope == "project" and project_path:
        return f"self-learn host add {project_path}"
    return None


def build_card_sections(
    card: dict[str, str] | None, registry: list[dict]
) -> tuple["CardSection", ...]:
    """The card-sections.yaml contract, rendered generically (09 §2.3 /
    the registry file's own docstring): iterate ascending ``order``, emit
    label + text for each key PRESENT in ``card``, skip absent keys,
    render unknown keys last (raw key as label). No section name is ever
    hardcoded here."""
    if not card:
        return ()
    known = {r["key"]: r for r in registry}
    sections: list[CardSection] = []
    for r in sorted(registry, key=lambda r: r["order"]):
        text = card.get(r["key"])
        if text:
            sections.append(
                CardSection(key=r["key"], label=r["label"], order=r["order"], text=text)
            )
    unknown_keys = sorted(k for k in card if k not in known and card.get(k))
    for key in unknown_keys:
        sections.append(CardSection(key=key, label=key, order=10**9, text=card[key]))
    return tuple(sections)


def leading_text(
    proposal: dict | None, registry: list[dict], title: str
) -> str:
    """09 §11 Y-9: the proposal's leading card section (registry order)
    when a proposal exists, else the record title — NEVER a raw id."""
    if proposal:
        cards = build_card_sections(proposal.get("card"), registry)
        if cards:
            return cards[0].text
    return title or "(untitled)"


# ---------------------------------------------------------------- Badge


@dataclass(frozen=True)
class Badge:
    """Y-10: hue is never the sole carrier — every badge carries text."""

    text: str
    kind: str


# ---------------------------------------------------------- Front model


@dataclass(frozen=True)
class BucketRow:
    name: str
    scope: str
    pending: int
    oldest_days: int | None
    unanalyzed: int
    #: Feedback round 1 item 8: how many of this bucket's records are
    #: currently snoozed (deferred_until in the future). Counted from the
    #: SAME list read Front already makes — never a second CLI call.
    deferred: int


@dataclass(frozen=True)
class StatusStrip:
    worker_last_run: str | None
    worker_stale: bool
    worker_stale_label: str
    total_pending: int
    open_followups: int
    sentinel_live: bool
    sentinel_label: str
    #: 09 §5 unreadable-record row: total records that could not be read,
    #: sourced from `status --json`'s top-level `total_unreadable` — never
    #: a server-side ledger derivation. 0 renders no count line on Front.
    total_unreadable: int = 0


@dataclass(frozen=True)
class HoldingRow:
    """09 §11 Y-4 — a routed record with unconfirmed recurrence suspects."""

    id: str
    bucket: str
    routed_days_ago: int | None
    sighted_count: int
    newest_nonce: str
    text: str
    #: Human-readable "why this was flagged", already joined for display.
    #: Empty string when no sighting carried a basis (pre-existing
    #: telemetry, or a producer that omits it) — the row still renders,
    #: it just says less.
    basis_text: str = ""


@dataclass(frozen=True)
class FollowupRow:
    """09 §11 Y-6 — passthrough of ``report --json .open_followups``."""

    id: str
    bucket: str
    action: str | None
    unblocks_on: str | None
    note: str | None
    routed_at: str | None


@dataclass(frozen=True)
class MinerRun:
    ts: str | None
    status: str
    status_label: str
    trigger: str | None
    sessions_scanned: int | None
    landed: int | None
    folded: int | None
    recurrences: int | None
    fires: int | None


@dataclass(frozen=True)
class NearMissRow:
    """09 §11 Y-24 — one drill row, from the LATEST ok/landed-uncommitted
    run only (spec F4: older runs' near-misses are never re-surfaced).
    ``index`` is this outcome's position in that run's own ``outcomes``
    list — the exact coordinate ``POST /mine/near-miss/promote`` sends;
    the server re-reads the snippet from a fresh ``mine status --json``
    at that (run_id, index), never trusting anything from this row."""

    index: int
    badge: Badge
    reason: str
    promotable: bool
    #: The dimmed single-line draft (promotable rows only) — formats the
    #: CLI-supplied snippet fields, never derives new meaning from them.
    draft_line: str | None
    #: `already-canon` rows only — links the matched record id.
    record_id: str | None


@dataclass(frozen=True)
class CanarySummary:
    """09 §11 Y-24 / FW-34 §4 — ``mine status --json``'s top-level
    ``canaries`` block, rendered verbatim; ``None`` (absent) when no
    canary has ever been planted (the one-liner's "· canaries K/N
    caught" suffix)."""

    planted: int
    caught: int


@dataclass(frozen=True)
class MinerBlock:
    """09 §11 Y-5 / Y-24 — ``mine status --json`` rendered verbatim;
    force-run + (Y-24) Promote are its only actions."""

    ok: bool
    error: str | None
    last_run: str | None
    stale: bool
    stale_label: str
    runs: tuple[MinerRun, ...]
    #: Y-24 one-liner: "miner: N sessions read, K landed, M near-misses"
    #: — N/K/M all drawn from the SAME latest ok/landed-uncommitted run
    #: (``None`` fields when no such run exists yet).
    latest_run_id: str | None
    latest_sessions_scanned: int | None
    latest_landed: int | None
    near_miss_count: int
    #: The drill's rows — latest run only (F4).
    near_miss_rows: tuple[NearMissRow, ...]
    #: ``None`` when no canary has ever been planted.
    canaries: CanarySummary | None


@dataclass(frozen=True)
class FrontModel:
    ok: bool
    errors: tuple[str, ...]
    buckets: tuple[BucketRow, ...]
    status: StatusStrip
    holding: tuple[HoldingRow, ...]
    followups: tuple[FollowupRow, ...]
    miner: MinerBlock


def _worker_stale(
    worker_last_run: str | None, now: datetime, total_unanalyzed: int
) -> bool:
    """Reuses the worker's OWN escalation threshold
    (:data:`self_learn.worker.STALE_AFTER_SECS`) — never a second
    definition. Gated on unanalyzed supply existing at all, mirroring
    :func:`self_learn.worker.fast_status`'s own gate: no supply, no alarm."""
    if total_unanalyzed < 1:
        return False
    if worker_last_run is None:
        return True  # missing = infinitely old (fast_status's own rule)
    dt = _parse_dt(worker_last_run)
    if dt is None:
        return True
    return (now - dt).total_seconds() > sl_worker.STALE_AFTER_SECS


def _sentinel_live(mtime: float | None, now: datetime) -> bool:
    """mtime-younger-than-TTL = live; TTL imported from
    :mod:`self_learn.sentinel`, never re-pinned here."""
    if mtime is None:
        return False
    return (now.timestamp() - mtime) < sl_sentinel.SENTINEL_TTL_SECONDS


#: Plain-English readings of the `basis` a recurrence-suspect carries.
#: The strength ordering is the point, not the wording: `fire-violated`
#: is the model itself reporting that it broke this routed rule, while
#: the other three are text-similarity heuristics that can fire on a
#: lesson nobody actually violated. A human choosing revise / escalate /
#: tolerate / retire is weighing exactly that difference.
#:
#: Deliberately NOT a closed set — an unrecognised basis renders verbatim
#: (see :func:`_basis_text`). Producers add bases without consulting this
#: layer, and a suspect that silently loses its reason is the defect this
#: mapping exists to fix.
_BASIS_LABELS = {
    "fire-violated": "the model reported violating this rule",
    "miner-match": "a transcript matched this rule's text",
    "origin-match": "a new lesson names the same origin",
    "title-token-overlap": "a new lesson's title overlaps this one",
}


def _basis_text(bases: list[str]) -> str:
    """Join the distinct bases behind a holding row into one clause.

    Empty in, empty out — a row whose sightings carry no basis (older
    telemetry, or a producer that omits it) simply says less, rather than
    rendering an empty parenthetical or the word "None"."""
    if not bases:
        return ""
    return "; ".join(_BASIS_LABELS.get(b, b) for b in bases)


def _build_holding_rows(report_data: dict | None) -> tuple[HoldingRow, ...]:
    if not report_data:
        return ()
    suspects = report_data.get("recurrence_suspects") or []
    routed_live = {r["id"]: r for r in (report_data.get("routed_live") or [])}
    grouped: dict[str, list[dict]] = {}
    for s in suspects:
        rid = s.get("id")
        if not isinstance(rid, str):
            continue
        grouped.setdefault(rid, []).append(s)
    rows: list[HoldingRow] = []
    for record_id, events in grouped.items():
        events_sorted = sorted(events, key=lambda e: e.get("seen_at") or "")
        newest = events_sorted[-1]
        # WHY each sighting was raised, which is most of the evidence
        # behind revise / escalate / tolerate / retire. `fire-violated`
        # means the model reported breaking this rule; the others are
        # text-similarity heuristics and are much weaker. Distinct values
        # in first-seen order — a record can carry both, and "it matched
        # some text AND the model admitted violating it" is a different
        # situation from either alone. An unrecognised value renders
        # verbatim rather than being dropped: producers add bases without
        # asking this layer.
        seen_bases: list[str] = []
        for event in events_sorted:
            basis = event.get("basis")
            if isinstance(basis, str) and basis and basis not in seen_bases:
                seen_bases.append(basis)
        live = routed_live.get(record_id)
        bucket = live["bucket"] if live else ""
        routed_days_ago = live.get("routed_days_ago") if live else None
        count = len(events)
        when = (
            f"Routed {routed_days_ago}d ago."
            if routed_days_ago is not None
            else "Routing date unknown."
        )
        plural = "time" if count == 1 else "times"
        text = f"{when} Sighted {count} {plural} since."
        rows.append(
            HoldingRow(
                id=record_id,
                bucket=bucket,
                routed_days_ago=routed_days_ago,
                sighted_count=count,
                newest_nonce=str(newest.get("nonce", "")),
                text=text,
                basis_text=_basis_text(seen_bases),
            )
        )
    return tuple(sorted(rows, key=lambda r: r.id))


def _build_followup_rows(report_data: dict | None) -> tuple[FollowupRow, ...]:
    if not report_data:
        return ()
    return tuple(
        FollowupRow(
            id=f["id"],
            bucket=f["bucket"],
            action=f.get("action"),
            unblocks_on=f.get("unblocks_on"),
            note=f.get("note"),
            routed_at=f.get("routed_at"),
        )
        for f in (report_data.get("open_followups") or [])
    )


def _build_miner_runs(runs: list[dict]) -> tuple[MinerRun, ...]:
    out = []
    for e in runs:
        status = e.get("status") or "unknown"
        out.append(
            MinerRun(
                ts=e.get("ts"),
                status=status,
                status_label=_MINER_STATUS_LABELS.get(status, status),
                trigger=e.get("trigger"),
                sessions_scanned=e.get("sessions_scanned"),
                landed=e.get("landed"),
                folded=e.get("folded"),
                recurrences=e.get("recurrences"),
                fires=e.get("fires"),
            )
        )
    return tuple(out)


def _latest_ok_run(runs: list[dict]) -> dict | None:
    """09 §11 Y-24 (F4): the latest ok/landed-uncommitted run — the SAME
    run the one-liner's N/K/M counts describe. Older runs' near-misses
    are never re-surfaced as rows (no accumulating multi-run list)."""
    for entry in reversed(runs):
        if entry.get("status") in ("ok", "landed-uncommitted"):
            return entry
    return None


def _nearmiss_draft_line(snippet: Any) -> str | None:
    """09 §11 Y-24 — the promotable row's dimmed single-line draft:
    formats the CLI-supplied snippet's own fields (trigger/instruction
    or fact/context), never derives new meaning from them. ``None`` for
    a non-dict snippet (absent, ``{scan_refused_rule}``, ``{overlength}``
    — none of which are ever passed here; the caller gates on
    ``promotable`` first)."""
    if not isinstance(snippet, dict):
        return None
    if "trigger" in snippet or "instruction" in snippet:
        parts = [snippet.get("trigger"), snippet.get("instruction")]
    elif "fact" in snippet or "context" in snippet:
        parts = [snippet.get("fact"), snippet.get("context")]
    else:
        return None
    text = " — ".join(p for p in parts if p)
    return text or None


def _build_near_miss_rows(latest: dict | None) -> tuple[NearMissRow, ...]:
    """09 §11 Y-24: rows from the latest run's ``outcomes`` ONLY — an
    entry with no ``disposition`` (``landed``/``resurfaced``) is not a
    near-miss and contributes no row. ``index`` mirrors the outcome's
    position in the CLI's own list, exactly what the promote endpoint
    expects back."""
    if not latest:
        return ()
    rows: list[NearMissRow] = []
    for idx, o in enumerate(latest.get("outcomes") or []):
        disposition = o.get("disposition")
        if not isinstance(disposition, str):
            continue
        promotable = bool(o.get("promotable"))
        rows.append(
            NearMissRow(
                index=idx,
                badge=Badge(
                    _NEARMISS_BADGE_LABELS.get(disposition, disposition), disposition
                ),
                reason=o.get("reason") or "",
                promotable=promotable,
                draft_line=_nearmiss_draft_line(o.get("snippet")) if promotable else None,
                record_id=o.get("record") if disposition == "already-canon" else None,
            )
        )
    return tuple(rows)


def _build_canary_summary(data: dict) -> CanarySummary | None:
    canaries = data.get("canaries")
    if not isinstance(canaries, dict) or not canaries.get("planted"):
        return None
    return CanarySummary(
        planted=int(canaries.get("planted") or 0), caught=int(canaries.get("caught") or 0)
    )


def _build_miner_block(mine_read: CliRead) -> MinerBlock:
    if not mine_read.ok or mine_read.data is None:
        return MinerBlock(
            ok=False,
            error=mine_read.error,
            last_run=None,
            stale=True,
            stale_label="miner status unavailable",
            runs=(),
            latest_run_id=None,
            latest_sessions_scanned=None,
            latest_landed=None,
            near_miss_count=0,
            near_miss_rows=(),
            canaries=None,
        )
    data = mine_read.data
    stale = bool(data.get("stale"))
    label = "miner overdue (>36h)" if stale else "miner current"
    runs = data.get("runs") or []
    latest = _latest_ok_run(runs)
    return MinerBlock(
        ok=True,
        error=None,
        last_run=data.get("last_run"),
        stale=stale,
        stale_label=label,
        runs=_build_miner_runs(runs),
        latest_run_id=latest.get("run_id") if latest else None,
        latest_sessions_scanned=latest.get("sessions_scanned") if latest else None,
        latest_landed=latest.get("landed") if latest else None,
        near_miss_count=int((latest or {}).get("near_miss_count") or 0),
        near_miss_rows=_build_near_miss_rows(latest),
        canaries=_build_canary_summary(data),
    )


def build_front_model(
    list_read: CliRead,
    status_read: CliRead,
    report_read: CliRead,
    mine_read: CliRead,
    *,
    sentinel_mtime: float | None,
    now: datetime | None = None,
) -> FrontModel:
    """09 §2.1: the bucket walk + status strip + Y-4/Y-5/Y-6 sections.
    ``list_read`` is accepted (and its error surfaced) even though this
    model does not otherwise consume list rows directly — Bucket pages
    own record-level rendering; Front only needs its error state."""
    now = now if now is not None else datetime.now(timezone.utc)
    errors = tuple(
        r.error
        for r in (list_read, status_read, report_read, mine_read)
        if r.error
    )

    status_data = status_read.data if status_read.ok and status_read.data else {}
    buckets_raw = status_data.get("buckets") or []
    # Keyed by (scope, bucket) — a bucket is not identified by name alone,
    # and two same-named buckets in different scopes used to show each
    # other's combined deferred count (review 2026-07-17 round-1, MINOR-2).
    #
    # That was deferred at the time with the reason "`list --json` items
    # carry no scope field ... fixing it properly is an 08 §1 substrate
    # edit (+scope on list items), not a UI-side derivation." **The
    # substrate edit has since landed** — `ledger_ops.list_items` emits
    # `"scope": record.scope` — so the blocker is gone and this IS a
    # UI-side derivation now. The stale deferral was keeping a known bug
    # open on a premise that had stopped being true.
    #
    # The two vocabularies still differ, which is the trap: a bucket's
    # scope is bare (`skill`), a record's own scope qualifies skills
    # (`skill:<name>`). `_bare_scope` reduces the record form to the
    # bucket form so the two can be compared at all — a plain equality
    # test would drop every skill bucket's count to zero.
    # An item with no usable `scope` (a malformed record — `Record.scope`
    # is a plain frontmatter lookup and can come back None — or an older
    # CLI) must not silently vanish from the count. When its bucket NAME
    # is unambiguous it is attributed there, which is both correct and
    # what the name-only keying did for every non-colliding bucket. Only a
    # genuinely ambiguous name (same name in two scopes AND no scope on
    # the item) is undecidable, and that is the one case it is dropped —
    # rather than guessing, or inflating both.
    scopes_by_name: dict[str, set[str]] = {}
    for b in buckets_raw:
        scopes_by_name.setdefault(b["bucket"], set()).add(b["scope"])

    deferred_by_bucket: dict[tuple[str, str], int] = {}
    if list_read.ok:
        for item in list_read.data or []:
            if not _is_deferred(item.get("deferred_until"), now):
                continue
            name = item.get("bucket") or ""
            scope = _bare_scope(item.get("scope"))
            if not scope:
                candidates = scopes_by_name.get(name) or set()
                if len(candidates) != 1:
                    continue  # undecidable: ambiguous name, no scope
                scope = next(iter(candidates))
            key = (scope, name)
            deferred_by_bucket[key] = deferred_by_bucket.get(key, 0) + 1
    buckets = tuple(
        sorted(
            (
                BucketRow(
                    name=b["bucket"],
                    scope=b["scope"],
                    pending=b["pending"],
                    oldest_days=b.get("oldest_days"),
                    unanalyzed=b["unanalyzed"],
                    deferred=deferred_by_bucket.get((b["scope"], b["bucket"]), 0),
                )
                for b in buckets_raw
            ),
            key=lambda b: (b.oldest_days is None, -(b.oldest_days or 0)),
        )
    )

    total_pending = status_data.get("total_pending", 0)
    open_followups = status_data.get("open_followups", 0)
    worker_last_run = status_data.get("worker_last_run")
    total_unanalyzed = sum(b.unanalyzed for b in buckets)
    stale = _worker_stale(worker_last_run, now, total_unanalyzed)
    if total_unanalyzed < 1:
        worker_label = "worker current — nothing unanalyzed"
    elif stale:
        worker_label = "worker overdue"
    else:
        worker_label = "worker current"

    sentinel_live = _sentinel_live(sentinel_mtime, now)
    sentinel_label = (
        "autosync paused — a canon apply is in flight"
        if sentinel_live
        else "autosync live"
    )

    status_strip = StatusStrip(
        worker_last_run=worker_last_run,
        worker_stale=stale,
        worker_stale_label=worker_label,
        total_pending=total_pending,
        open_followups=open_followups,
        sentinel_live=sentinel_live,
        sentinel_label=sentinel_label,
        total_unreadable=status_data.get("total_unreadable", 0),
    )

    report_data = report_read.data if report_read.ok else None

    return FrontModel(
        ok=not errors,
        errors=errors,
        buckets=buckets,
        status=status_strip,
        holding=_build_holding_rows(report_data),
        followups=_build_followup_rows(report_data),
        miner=_build_miner_block(mine_read),
    )


# --------------------------------------------------------- Bucket model


@dataclass(frozen=True)
class RecordRow:
    id: str
    leading_text: str
    age_days: int
    sightings: int
    destination: str | None
    #: What the row's action bar arms as ``--dest`` (09 §2.3 as amended
    #: 2026-07-18): :func:`proposed_destination` of ``destination`` and
    #: this row's own proposal (U-demand-user §3.3(d)) — never a value
    #: the record's scope makes impossible. ``destination`` above stays
    #: the analyst's raw suggestion (grouping/display).
    destination_default: str | None
    destination_note: str | None
    deferred: bool
    already_canon: bool
    badges: tuple[Badge, ...]
    #: U-demand-user §3.3(f)/§3.5: this row's OWN `o`-cycle
    #: (:func:`destination_cycle_for`, per-record — REPLACES
    #: ``BucketModel.destination_cycle``, dropped §3.5A after this
    #: field gave it zero readers). Without a per-row cycle, a row whose
    #: armed dest is the qualified rules token would render against the
    #: scope-level singleton and the bar would lie that no other
    #: destination fits — a NEW funnel this unit's own fix would create,
    #: which S-22 forbids (§3.5).
    destination_cycle: tuple[str, ...]


@dataclass(frozen=True)
class BulkCollapseRow:
    """09 §2.2 carried P1-1: a homogeneous already-canon group renders as
    ONE collapsible decision row arming a loop of per-record ``graduate``
    verbs — never rejection."""

    count: int
    ids: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class DestinationGroup:
    key: str
    label: str
    rows: tuple[RecordRow, ...]
    bulk_collapse: BulkCollapseRow | None


@dataclass(frozen=True)
class ClusterRow:
    cluster_id: str
    member_ids: tuple[str, ...]
    member_count: int
    suggested_survivor: str
    rationale: str


@dataclass(frozen=True)
class ArchiveRow:
    """B1 (U-grad-ui spec §4) / M4's target: one row of the Bucket page's
    collapsed "Routed here" archive section — INDEX-SET (§2.2), already
    scope-confirmed and raw-read-hydrated by the caller (routes.py's
    ``_gather_archive_entries``).

    Y-9: ``leading_text`` is the record's OWN title (raw read, never a
    second title definition — :func:`build_archive_rows`'s docstring),
    NEVER the raw id (M4's exact regression: "return `record.id` instead
    of the record's leading text"). ``id`` is carried as its own field so
    the template can render it in a dedicated ``.record-row-id`` span —
    §4's load-bearing pin: if the id lived only in the anchor's ``href``,
    M18 (stripping the anchor) would blind criteria 2/3's id-scoped
    exclusion assertions too, not just criterion 1."""

    id: str
    leading_text: str
    fact_text: str


def _archive_fact_text(entry: dict, scope: str) -> str:
    """The archive row's plain-words routing fact line (§4: "routed N
    days ago → destination; recurrences if any") — never a raw enum, per
    Y-9. ``destination`` is glossed through the SAME single-source
    resolver every other destination display in this module uses."""
    routed_days_ago = entry.get("routed_days_ago")
    when = (
        f"routed {routed_days_ago}d ago"
        if routed_days_ago is not None
        else "routed — date unknown"
    )
    destination = entry.get("destination")
    dest_part = f" → {destination_label(destination, scope)}" if destination else ""
    recurrences = entry.get("recurrences") or 0
    recur_part = ""
    if recurrences:
        plural = "time" if recurrences == 1 else "times"
        recur_part = f" · sighted {recurrences} {plural} since"
    return f"{when}{dest_part}{recur_part}"


def build_archive_rows(entries: list[dict], scope: str) -> tuple[ArchiveRow, ...]:
    """B1 (§4): format the Bucket page's routed-record archive section.
    ``entries`` is caller-hydrated (``routes._gather_archive_entries``) —
    each dict already carries ``id``, ``title`` (a raw
    ``ledger.record_title()`` read — the same raw-read path Detail
    already uses, never a second title definition, §5), ``routed_days_ago``,
    ``destination`` (from the record's own ``routing`` block — the CLI's
    ``routed_live`` carries no destination field), and ``recurrences``.
    This function does no I/O and does not re-derive the SET — it only
    formats what the caller already assembled (09 §3's screen-state-
    derivation pin). Order is preserved from the caller (which preserves
    `report --json`'s own ``routed_live`` order — never re-sorted here)."""
    rows = []
    for e in entries:
        title = e.get("title") or ""
        rows.append(
            ArchiveRow(
                id=e["id"],
                leading_text=title or "(untitled)",
                fact_text=_archive_fact_text(e, scope),
            )
        )
    return tuple(rows)


@dataclass(frozen=True)
class BucketModel:
    bucket: str
    scope: str
    host_registered: bool
    host_add_command: str | None
    groups: tuple[DestinationGroup, ...]
    clusters: tuple[ClusterRow, ...]
    #: 09 §5 unreadable-record row: this bucket's own count of records that
    #: could not be read, sourced from `status --json`'s per-bucket
    #: `unreadable` field — never a server-side ledger derivation. 0
    #: renders no count line on the Bucket page.
    unreadable: int = 0
    #: B1 (U-grad-ui §4): the routed-record archive section's rows —
    #: INDEX-SET (§2.2), empty by default so every existing caller of
    #: :func:`build_bucket_model` (this module's own tests included)
    #: degrades to "no archive section" rather than breaking.
    archive: tuple[ArchiveRow, ...] = ()
    #: Code-gate finding 6 / user ruling 2026-08-02: set (to `report
    #: --json`'s own error string) ONLY when the underlying CLI read
    #: itself failed — never for "read succeeded, zero routed records".
    #: `None` (the overwhelmingly common case, and every pre-existing
    #: caller's default) renders the ordinary empty-or-populated archive;
    #: a non-`None` value renders a distinct "Routed here (unavailable)"
    #: header instead of silently omitting the section — the bug this
    #: unit exists to fix, one layer up, is exactly a thing the user
    #: needed being invisible with no indication it existed.
    archive_error: str | None = None


def _group_key_for(item: dict) -> str:
    if not item.get("has_proposal"):
        return "no-analysis"
    dest = item.get("destination")
    if dest in _GROUP_LABELS and dest not in ("no-analysis", "malformed"):
        return dest
    return "malformed"


def _record_badges(item: dict, deferred: bool, stale: bool) -> tuple[Badge, ...]:
    badges: list[Badge] = []
    if item.get("source") == "session":
        badges.append(Badge("mined", "mined"))
    if deferred:
        badges.append(Badge("deferred", "deferred"))
    if item.get("already_canon"):
        badges.append(Badge("already canon", "already-canon"))
    if stale:
        badges.append(Badge("stale — record edited since analysis", "stale"))
    return tuple(badges)


def build_bucket_model(
    bucket_name: str,
    scope: str,
    items: list[dict],
    proposals: dict[str, dict | None],
    clusters_raw: list[dict],
    registry: list[dict],
    *,
    host_registered: bool,
    host_add_command: str | None,
    unreadable: int = 0,
    archive_entries: list[dict] | None = None,
    archive_error: str | None = None,
    now: datetime | None = None,
) -> BucketModel:
    """09 §2.2: group precedence (P2-9), the Y-9 human-language-first row
    rule, deferred-dimmed-at-bottom ordering, cluster rows, and bulk
    collapse for a homogeneous already-canon group. ``unreadable`` is this
    bucket's `status --json` unreadable count (09 §5), passed through for
    the skip-and-count line. ``archive_entries`` (B1, U-grad-ui §4) is the
    caller-hydrated routed-record archive section — ``None``/``[]``
    renders no archive section, same "absent renders nothing" posture as
    every other optional region in this module. ``archive_error``
    (code-gate finding 6) is the DISTINCT "the read itself failed" state
    — never conflated with "read succeeded, nothing routed": passing it
    renders "Routed here (unavailable)" instead of omitting the section."""
    now = now if now is not None else datetime.now(timezone.utc)
    clustered_ids = {rid for c in clusters_raw for rid in (c.get("records") or [])}

    groups_map: dict[str, list[RecordRow]] = {k: [] for k in _GROUP_ORDER}
    for item in items:
        rid = item["id"]
        if rid in clustered_ids:
            continue
        proposal = proposals.get(rid)
        group_key = _group_key_for(item)
        deferred = _is_deferred(item.get("deferred_until"), now)
        stale = bool(item.get("has_proposal")) and not item.get("proposal_fresh", False)
        dest_default, dest_note = proposed_destination(scope, item.get("destination"), proposal)
        row = RecordRow(
            id=rid,
            leading_text=leading_text(proposal, registry, item.get("title", "")),
            age_days=item.get("age_days", 0),
            sightings=item.get("sightings", 1),
            destination=item.get("destination"),
            destination_default=dest_default,
            destination_note=dest_note,
            deferred=deferred,
            already_canon=bool(item.get("already_canon")),
            badges=_record_badges(item, deferred, stale),
            destination_cycle=destination_cycle_for(scope, _proposal_rules_topic(proposal)),
        )
        groups_map[group_key].append(row)

    groups: list[DestinationGroup] = []
    for key in _GROUP_ORDER:
        rows = groups_map[key]
        if not rows:
            continue
        # Deferred pushed to the bottom, dimmed — stable sort preserves
        # the existing oldest-first order within each half.
        rows = sorted(rows, key=lambda r: r.deferred)
        bulk: BulkCollapseRow | None = None
        if key not in ("no-analysis", "malformed") and all(
            r.already_canon for r in rows
        ):
            bulk = BulkCollapseRow(
                count=len(rows),
                ids=tuple(r.id for r in rows),
                text=f"{len(rows)} already-canon records — acknowledge all as canon",
            )
            rows = ()
        groups.append(
            DestinationGroup(
                # O-2 e (A1): route the group heading through the SAME
                # widened resolver the per-record sites use — a bucket
                # page is one scope (``scope`` above), so this resolves
                # to exactly one (scope, destination) pair; only
                # ``claude-md`` specializes, every other key is
                # byte-identical to the old direct ``_GROUP_LABELS[key]``
                # index at every scope.
                key=key, label=destination_label(key, scope), rows=tuple(rows), bulk_collapse=bulk
            )
        )

    clusters = tuple(
        ClusterRow(
            cluster_id=c["cluster_id"],
            member_ids=tuple(c.get("records") or ()),
            member_count=len(c.get("records") or ()),
            suggested_survivor=c.get("suggested_survivor", ""),
            rationale=c.get("rationale", ""),
        )
        for c in clusters_raw
    )

    return BucketModel(
        bucket=bucket_name,
        scope=scope,
        host_registered=host_registered,
        host_add_command=host_add_command,
        groups=tuple(groups),
        clusters=clusters,
        unreadable=unreadable,
        archive=build_archive_rows(archive_entries or [], scope),
        archive_error=archive_error,
    )


# --------------------------------------------------------- Detail model


@dataclass(frozen=True)
class CardSection:
    key: str
    label: str
    order: int
    text: str


@dataclass(frozen=True)
class FindingRegion:
    title: str
    record_type: str
    body: str
    evidence: tuple[dict, ...]
    source: str
    sightings: int
    created_at: str | None
    provenance_text: str
    #: 09 §2.3 Y-21 / 10 §3 U18: the '## Episode brief' section split OUT
    #: of ``body`` above (never inline in the decision content). None when
    #: the record carries no brief (no-backfill posture: absent renders
    #: nothing, not a placeholder).
    episode_brief: str | None = None


@dataclass(frozen=True)
class ChangeRegion:
    """09 §2.3 region 2 / Y-7. ``kind`` selects what U3 renders:
    ``none`` (no proposal — ``message`` carries the CTA), ``diff``
    (Pygments DiffLexer), ``proposal-yaml`` (Pygments YAML lexer, the
    proposal's raw sibling text), ``hook`` (the FULL stored script + its
    replay examples, M3 verbatim-apply caption), ``new-skill`` (scaffold
    preview)."""

    kind: str
    content: str | None
    caption: str
    message: str | None = None
    replay_examples: dict | None = None
    scaffold_name: str | None = None


@dataclass(frozen=True)
class BudgetRow:
    """09 §11 Y-20 — one scope-valid candidate destination's loaded-surface
    budget line for the Why region (the surface's SINGLE budget display;
    the armed action bar carries none, F2). ``skill-md``/``claude-md`` are
    CLI-datum rows built from `surface_fill`; a capped destination the CLI
    omitted (any VerbError — F5) never becomes a row at all — the register
    lists only what it can state a fact about. ``reference`` is always
    present for a scope where it is a valid candidate — its text is the
    fixed no-cap line, never a CLI datum (F1: it is the cap-free overflow
    sink)."""

    destination: str
    text: str
    over_cap: bool


@dataclass(frozen=True)
class WhyRegion:
    rationale: str | None
    destination: str | None
    alternates: tuple[str, ...]
    already_canon: bool
    already_canon_reason: str | None
    freshness: str
    freshness_label: str
    #: 09 §11 Y-20 — every scope-valid candidate's budget, in cycle order
    #: (:func:`destinations_for_scope`); a capped destination with no
    #: `surface_fill` key is simply absent from this tuple (F5).
    budgets: tuple[BudgetRow, ...]
    #: A2 §11: the analyst proposal's own variant fields, additive and
    #: `None`/`()` for every pre-A2 proposal (P-A6) — threaded through so
    #: `detail.html` can gloss the SUGGESTED destination the same
    #: variant-aware way a resolved record's own label would (§13 item 5,
    #: §15 item 9).
    variant: str | None = None
    rules_topic: str | None = None
    rules_paths: tuple[str, ...] = ()
    #: U-demand-user §8A.2(1)/H5: the analyst proposal's own decision-
    #: trace fields (U-schema, S-26) — additive and `None`/`()` for
    #: every proposal that never set them (P-A6, same posture as
    #: variant/rules_topic/rules_paths above): no live proposal carries
    #: them today, and none will until U-composer's flip. `flags` are
    #: DISPLAY-ONLY here (§8A.3) — they render and change no behaviour;
    #: only `recommendation == "defer"` is behavioural (§8A.2(2)).
    recommendation: str | None = None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetailModel:
    id: str
    bucket: str
    scope: str
    status: str
    cards: tuple[CardSection, ...]
    finding: FindingRegion
    change: ChangeRegion
    why: WhyRegion
    contradicts: tuple[str, ...]
    destination_cycle: tuple[str, ...]
    #: 09 §2.3 as amended 2026-07-18: what the unarmed bar's hidden dest
    #: field carries (and so what Approve arms/executes) + the Y-9 note
    #: shown when the analyst's suggestion was scope-corrected.
    destination_default: str | None
    destination_note: str | None
    badges: tuple[Badge, ...]
    host_registered: bool
    host_add_command: str | None


#: Local heading matcher — mirrors records.py's private ``_HEADING_RE``
#: (not exported; the model builder owns section EXTRACTION the same way
#: compilers.py's ``_body_sections`` does for the CLI package, 02 §1).
_HEADING_RE = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)


def _split_episode_brief(body: str) -> tuple[str, str | None]:
    """09 §2.3 Y-21 / 10 §3 U18: split the optional '## Episode brief'
    section OUT of a record body, so the Finding region's decision
    content (Trigger/Instruction/Fact/Context) renders exactly as it did
    before the brief existed, and the brief renders separately, collapsed,
    below it. Returns ``(body_without_brief, brief_text_or_none)``; a
    record with no brief section returns ``(body, None)`` unchanged."""
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return body, None
    brief: str | None = None
    kept_spans: list[tuple[int, int]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        if m.group(1) == "Episode brief":
            brief = body[m.end() : end].strip()
        else:
            kept_spans.append((m.start(), end))
    if brief is None:
        return body, None
    if not kept_spans:
        return "", brief
    prefix = body[: kept_spans[0][0]]
    kept_text = "".join(body[start:end] for start, end in kept_spans)
    return (prefix + kept_text).rstrip("\n") + "\n", brief


def _build_finding(record: Record, title: str) -> FindingRegion:
    # F5-6 (feedback round 5, U19 §1.4 gate M4): the raw "created ...Z"
    # ISO stamp used to be baked into this pre-joined string, which no
    # Jinja filter could reach — it is dropped here and rendered from the
    # discrete `created_at` field below instead, as its own
    # `humanize_ts`-filtered element on the same line (detail.html).
    parts = [record.source, f"{record.sightings} sighting(s)"]
    body, episode_brief = _split_episode_brief(record.body)
    return FindingRegion(
        title=title or "(untitled)",
        record_type=record.type,
        body=body,
        evidence=tuple(dict(e) for e in record.evidence),
        source=record.source,
        sightings=record.sightings,
        created_at=str(record.created_at) if record.created_at else None,
        provenance_text=" · ".join(parts),
        episode_brief=episode_brief,
    )


def _build_change(
    proposal: dict | None, diff_text: str | None, proposal_raw_text: str | None
) -> ChangeRegion:
    if proposal is None:
        return ChangeRegion(
            kind="none", content=None, caption="", message=NO_ANALYSIS_MESSAGE
        )
    destination = proposal.get("destination")
    if destination == "hook":
        return ChangeRegion(
            kind="hook",
            content=proposal.get("script"),
            caption=HOOK_VERBATIM_CAPTION,
            replay_examples=proposal.get("examples"),
        )
    if destination == "new-skill":
        name = proposal.get("new_skill")
        content = (
            f"new skill scaffold: {name}"
            if name
            else "new skill scaffold (name chosen at route time)"
        )
        return ChangeRegion(
            kind="new-skill",
            content=content,
            caption=PREVIEW_HONESTY_CAPTION,
            scaffold_name=name,
        )
    if diff_text is not None:
        return ChangeRegion(kind="diff", content=diff_text, caption=PREVIEW_HONESTY_CAPTION)
    if proposal_raw_text is not None:
        return ChangeRegion(
            kind="proposal-yaml", content=proposal_raw_text, caption=PREVIEW_HONESTY_CAPTION
        )
    return ChangeRegion(kind="none", content=None, caption="", message=NO_ANALYSIS_MESSAGE)


#: Blind-review F1 fix: how close to a cap counts as "near" enough to earn
#: the nearness clause — fewer than 3 entries of headroom, or the word
#: axis at/past 80% of its budget. Below both, and not over cap, the bare
#: fill fact is the whole sentence (an empty/low surface saying "lands
#: near the cap" is not just uninformative, it inverts the feature's
#: point: the emptiest surface is the BEST route target).
_NEAR_ENTRIES_HEADROOM = 2
_NEAR_WORDS_RATIO = 0.8


def _budget_text(destination: str, fill: dict) -> str:
    """09 §11 Y-20 / §2.3: the plain-words fill sentence for a CAPPED
    destination — the CLI supplies the datum (``entries``/``entries_cap``/
    ``words``/``words_cap``/``over_cap``), this is the template. The
    nearness clause (word-cap or entries-cap phrasing) is gated on ACTUAL
    proximity (blind-review F1) — never appended unconditionally — using
    the SAME datum the CLI already computed, no fuzzy guess: over cap, or
    within :data:`_NEAR_ENTRIES_HEADROOM` entries of the cap, or the word
    axis at/past :data:`_NEAR_WORDS_RATIO` of its budget. Below every one
    of those, the sentence is the bare fill fact alone — honest and
    sufficient for a section nowhere near full. When a clause IS earned,
    the word-cap phrasing fires when ``words`` is proportionally the
    tighter (binding) constraint. At or over cap the sentence still
    states only the fill fact; the escalation itself is the EXISTING
    02 §4 over-cap WARNING (surfaced through the verb's own stderr at
    route time), not duplicated here (spec point 5)."""
    entries, entries_cap = fill["entries"], fill["entries_cap"]
    words, words_cap = fill["words"], fill["words_cap"]
    over_cap = bool(fill.get("over_cap"))
    base = (
        f"this {destination} section already holds {entries} of its "
        f"{entries_cap} entries"
    )

    entries_ratio = (entries / entries_cap) if entries_cap else 0.0
    words_ratio = (words / words_cap) if words_cap else 0.0
    entries_near = entries_cap > 0 and (entries_cap - entries) <= _NEAR_ENTRIES_HEADROOM
    words_near = words_cap > 0 and words_ratio >= _NEAR_WORDS_RATIO
    if not (over_cap or entries_near or words_near):
        return base

    words_bound = words_ratio > entries_ratio
    tail = (
        " — and is near its word budget"
        if words_bound
        else " — a route here lands near the cap"
    )
    return base + tail


def _budget_rows(item: dict, scope: str) -> tuple[BudgetRow, ...]:
    """09 §11 Y-20(2): every scope-valid candidate destination
    (:func:`destinations_for_scope` — the SAME scope predicate the `o`
    cycle uses, no second scope definition), not just the suggestion —
    the Why region is the single budget surface and the whole point is
    the human weighing an ALTERNATIVE with its cost visible too. A capped
    destination (`skill-md`/`claude-md`) with no `surface_fill` key is
    simply skipped (F5: any VerbError leg omits the key, never a zero,
    never a placeholder row). `reference` always gets the static no-cap
    line when it is a scope-valid candidate — no probe, no key to be
    absent (F1)."""
    fills = item.get("surface_fill") or {}
    rows: list[BudgetRow] = []
    for destination in destinations_for_scope(scope):
        if destination == "reference":
            rows.append(
                BudgetRow(destination="reference", text=REFERENCE_NO_CAP_LINE, over_cap=False)
            )
            continue
        fill = fills.get(destination)
        if fill is None:
            continue
        rows.append(
            BudgetRow(
                destination=destination,
                text=_budget_text(destination, fill),
                over_cap=bool(fill.get("over_cap")),
            )
        )
    return tuple(rows)


def _build_why(item: dict, proposal: dict | None, scope: str) -> WhyRegion:
    has_proposal = bool(item.get("has_proposal"))
    fresh = bool(item.get("proposal_fresh"))
    if not has_proposal:
        freshness, label = "none", "no analysis yet"
    elif fresh:
        freshness, label = "fresh", "fresh"
    else:
        freshness, label = (
            "stale",
            "stale — record edited since analysis (Iterate to regenerate)",
        )
    return WhyRegion(
        rationale=(proposal or {}).get("rationale"),
        destination=item.get("destination"),
        alternates=tuple((proposal or {}).get("alternates") or ()),
        already_canon=bool(item.get("already_canon")),
        already_canon_reason=(proposal or {}).get("already_canon_reason"),
        freshness=freshness,
        freshness_label=label,
        budgets=_budget_rows(item, scope),
        # A2 §11: read straight off the proposal (never `item`, which is
        # the ledger's routing-agnostic summary) — `None`/`()` for every
        # proposal that never set these (P-A6 no-migration).
        variant=(proposal or {}).get("variant"),
        rules_topic=(proposal or {}).get("rules_topic"),
        rules_paths=tuple((proposal or {}).get("rules_paths") or ()),
        # H5 (§8A.2(1)): same additive P-A6 posture as the three lines
        # above — read straight off the proposal, `None`/`()` for every
        # proposal that never set them.
        recommendation=(proposal or {}).get("recommendation"),
        flags=tuple((proposal or {}).get("flags") or ()),
    )


def build_detail_model(
    item: dict,
    record: Record,
    proposal: dict | None,
    diff_text: str | None,
    proposal_raw_text: str | None,
    registry: list[dict],
    *,
    bucket: str,
    scope: str,
    host_registered: bool,
    host_add_command: str | None,
    now: datetime | None = None,
) -> DetailModel:
    """09 §2.3: card-sections-first render + the three machine regions."""
    now = now if now is not None else datetime.now(timezone.utc)
    title = item.get("title", "")
    deferred = _is_deferred(item.get("deferred_until"), now)
    stale = bool(item.get("has_proposal")) and not item.get("proposal_fresh", False)

    badges = list(_record_badges(item, deferred, stale))
    if not host_registered:
        badges.append(Badge("unregistered project", "unregistered-host"))

    contradicts = tuple((proposal or {}).get("contradicts") or ())
    dest_default, dest_note = proposed_destination(scope, item.get("destination"), proposal)

    return DetailModel(
        id=record.id,
        bucket=bucket,
        scope=scope,
        status=record.status,
        cards=build_card_sections((proposal or {}).get("card"), registry),
        finding=_build_finding(record, title),
        change=_build_change(proposal, diff_text, proposal_raw_text),
        why=_build_why(item, proposal, scope),
        contradicts=contradicts,
        # U-demand-user §3.3(f): per-record now, not the scope-level
        # default — a rules proposal's own topic reaches the `o` cycle.
        destination_cycle=destination_cycle_for(scope, _proposal_rules_topic(proposal)),
        destination_default=dest_default,
        destination_note=dest_note,
        badges=tuple(badges),
        host_registered=host_registered,
        host_add_command=host_add_command,
    )


# ------------------------------------------------ resolved Detail model
#
# U-grad-ui §2.1/§5: VIEWABLE renders every status a resolved record can
# carry (routed/rejected/superseded). `detail_resolved.html`'s own model
# — deliberately NOT `DetailModel` reused, because `WhyRegion`/`ChangeRegion`
# are shaped around a PENDING record's proposal (has_proposal/destination
# suggestion/budgets), none of which exist once a record has resolved; a
# resolved record's routing facts live on the record itself
# (`record.routing`/`recurrences`/`last_confirmed`/`resolution_note`/
# `follow_up`), never on `item` (the ledger's pending-shaped summary,
# synthesized as a near-empty stand-in for a resolved record —
# `_gather_detail_bundle`'s docstring).


@dataclass(frozen=True)
class ResolvedRoutingFacts:
    """§5's routing facts, read straight off the record — never `item`.
    ``destination``/``destination_label_text`` are ``None``/``""`` for a
    `rejected`/`superseded`-with-no-routing record (routing is `None`
    once a record never routed, or after a corrective supersession that
    cleared it) — the template renders nothing for an absent fact,
    no-backfill, same posture as :class:`FindingRegion`'s
    ``episode_brief``."""

    destination: str | None
    destination_label_text: str
    routed_at: str | None
    routed_by: str | None
    last_confirmed: str | None
    resolution_note: str | None
    recurrences: tuple[dict, ...]
    follow_up: dict | None


@dataclass(frozen=True)
class ResolvedDetailModel:
    id: str
    bucket: str
    scope: str
    status: str
    finding: FindingRegion
    routing: ResolvedRoutingFacts
    host_registered: bool
    host_add_command: str | None


def build_resolved_detail_model(
    record: Record,
    *,
    title: str,
    bucket: str,
    scope: str,
    host_registered: bool,
    host_add_command: str | None,
) -> ResolvedDetailModel:
    """§2.1 VIEWABLE / §5: the resolved Detail page's model — the record's
    OWN Trigger/Fact section (``title``, criterion 13 — a raw
    ``ledger.record_title()`` read the caller already made, never
    re-derived here) plus its routing facts, read off ``record`` itself.
    No proposal, no change region, no destination cycle, no budgets — a
    resolved record structurally has none of them (§5's builder
    decision)."""
    routing = record.routing or {}
    destination = routing.get("destination")
    return ResolvedDetailModel(
        id=record.id,
        bucket=bucket,
        scope=scope,
        status=record.status,
        finding=_build_finding(record, title),
        routing=ResolvedRoutingFacts(
            destination=destination,
            destination_label_text=(
                destination_label(
                    destination, scope, routing.get("variant"), routing.get("rules_topic")
                )
                if destination
                else ""
            ),
            routed_at=routing.get("routed_at"),
            routed_by=routing.get("by"),
            last_confirmed=str(record.last_confirmed) if record.last_confirmed else None,
            resolution_note=record.resolution_note,
            recurrences=tuple(dict(r) for r in record.recurrences),
            follow_up=dict(record.follow_up) if record.follow_up else None,
        ),
        host_registered=host_registered,
        host_add_command=host_add_command,
    )
