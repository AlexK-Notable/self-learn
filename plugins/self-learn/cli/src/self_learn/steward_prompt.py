"""steward_prompt.py — the steward's packet (U9; plan-steward §4.1; U10
not yet built, so this unit's `assemble` is dead code today, same as
`worker.render_brief` was dead code until this unit — the packet the
runner hands to a Fable session, one per model call.

**Order is the design.** Seven blocks, evidence before advice, so the
steward's own view forms before it reads anyone's advice (astra-round3
"two reading views"): ``containment``, ``method``, ``user_model``,
``conditions``, ``open_cases``, ``briefs``, ``output_contract``, in that
order and no other.

This module never writes the ledger, takes no lock, never reads a
transcript, and never reads ``hosts.yaml`` or ``settings.json`` itself —
every fact it renders comes through :func:`conditions.feed` (already
fail-closed to ``"unavailable"``) or through an existing read-only
function (:func:`worker.render_brief`, :func:`cases.show`,
:func:`cases.list_cases`, :func:`user_model.show`).

**Proposal shape — this unit's own convention, not an applied spec.**
`ledger_ops.validate_proposal` (grepped: no ``id``/``record_id`` field
anywhere in the schema) confirms a raw proposal dict carries no record
id; the id lives only in the proposal FILE's name
(``proposals/<record-id>.yaml``, observed: `worker.py`'s
``_check_proposal_file``, ``path.stem``). U10, which reads those files,
does not exist yet, so this unit adopts the simplest convention a future
caller can meet: each dict in ``proposals`` MAY carry an ``"id"`` key
(set by whoever read the file) in addition to the fields
``read_proposal``/``validate_proposal`` already produce. A proposal
without one still renders — its card, through :func:`worker.render_brief`
unchanged — just with an "(unknown id)" header and no prior-case lookup.
**Ordering is the caller's job.** ``assemble`` renders ``proposals`` in
the exact order the caller passes them — it never sorts or reorders.
U10 is the one that must hand them over oldest first; this module only
preserves whatever order it is given.

**"Later observations", evidence-only view, and the blind default
(plan §4.1 item 5; this unit's own reading).** `cases.show`'s BLIND
default (kept, as the brief directs) renders sections 1/2/4 only —
section 6, "Later observations", is excluded by `cases._BLIND_SECTIONS`
by design. Rendering "every Later observations entry newer than
`steward.last_run_at`" (plan §4.1) therefore needs one additional,
narrow full-view read (`cases.show(..., evidence_only=False)`) per open
case, from which ONLY the "Later observations" section text is taken —
sections 3/5 (Decision, Application) from that full read are never
rendered anywhere. When `run.last_run_at` is `None` (no prior run),
every "Later observations" line is treated as newer than never — all of
them render. This makes an observation's free text (`cases.observe`'s
`text` argument) the ONE section-6 channel that reaches the steward at
all — U10/O-3 should know that text is constrained only by a secret
scan and a heading refusal (`cases._scan_or_refuse` /
`cases._refuse_headings`), never by anything narrower this module
adds."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

from . import batch
from . import cases
from . import conditions
from . import ledger_ops
from . import records
from . import verbs
from . import statements
from . import user_model
from . import worker
from .conditions import Item

__all__ = [
    "RunContext",
    "Block",
    "Packet",
    "OUTPUT_CONTRACT",
    "RUNNER_ONLY_PARKED_REASONS",
    "STAGE_EXAMPLES",
    "assemble",
    "withheld",
]

Block = tuple[str, str]

#: The seven block names, in the order §4.1 mandates.
_BLOCK_ORDER = (
    "containment",
    "method",
    "user_model",
    "conditions",
    "open_cases",
    "briefs",
    "output_contract",
)

#: Container reading order for the user-model block (plan §4.1 item 3):
#: own words -> seen readings -> declared conditions -> provisional
#: readings -> observed regularities. NOT the interface draft §3.1
#: table's alphabetical A-E listing (that table enumerates the
#: document's storage containers, not a reading order) -- no
#: disagreement to flag, the two describe different things.
_USER_MODEL_CONTAINER_ORDER = ("A", "B", "E", "C", "D")

_OBS_LINE_RE = re.compile(r"^-\s+obs-[0-9a-f]{8}\s+(\S+)")


@dataclass(frozen=True)
class RunContext:
    run_id: str
    stage_dir: Path
    packet_index: int
    packet_count: int
    last_run_at: str | None
    verbs_the_runner_executes: tuple[str, ...]


@dataclass(frozen=True)
class Packet:
    blocks: tuple[Block, ...]
    text: str
    withheld: tuple[str, ...]


#: The six stage files a steward session may write. The KEYS are the
#: runner's whitelist (`steward._validate_declared_stage` refuses any other
#: file); the values are one line each on what the file is for. The
#: FORMATS are not written here by hand: `_render_output_contract` builds
#: them from the constants the checkers themselves read (`cases.KINDS`,
#: `batch.PERMITTED_KEYS`, ...), so the brief cannot drift from the code.
#:
#: Rewritten 2026-09-20. The first version was written before the code
#: that reads these files existed, and described the finished six-section
#: case DOCUMENT `cases.record` renders, not the YAML file the steward has
#: to write. On the first real run (2026-09-19) each session spent about
#: 30 of its ~110 tool calls reading this package's source to find the
#: real formats -- "Now finding the runner code that parses the stage
#: files, so the format I write validates."
OUTPUT_CONTRACT: dict[str, str] = {
    "cases/*.yaml": "one file per decision: what you decided about which lessons, and why",
    "sheets/*.yaml": "one file per case, same file name: the actions the runner applies for that case",
    "revisions.yaml": "optional: reword a lesson's sentence (never its claim) before its case's sheet applies",
    "statements.yaml": "optional: something the user said, pointed at where they said it",
    "model-updates.yaml": "optional: a provisional reading of the user, or a lapse of an existing entry",
    "parked.yaml": "optional: a further question for the overseer",
}

#: `parked_reason` values a RUNNER writes and a model never chooses
#: (02-schema §3a; `steward._validate_declared_stage` refuses them in a
#: staged case). Lives here so the brief and the checker share one set.
RUNNER_ONLY_PARKED_REASONS = frozenset(
    {"attempts-exhausted", "ledger-refused", "plain-host-committed-file"}
)

#: S-71 §4.6: the output contract's one sentence on what becomes of a line
#: the ledger refuses.
_REFUSED_LINE_SENTENCE = (
    "A lesson whose line the ledger refuses is either sent back to you on a later night "
    "(once) or parked for the overseer; a refusal is never retried unchanged unless it "
    "was git trouble or a target file with uncommitted edits."
)

#: S-71 §4.6: the block a lesson sent back comes with, and the instruction
#: that closes it, exactly.
SENT_BACK_TITLE = "LESSONS SENT BACK TO YOU"
SENT_BACK_INSTRUCTION = (
    "Your earlier decision for these lessons could not be applied as written. Decide "
    "again: you may write a different line, choose a different destination or verb, or "
    "park the case with the reason that names its question. Do not write the same line "
    "again."
)

#: Sheet verbs the brief does not list: a pre-rename alias (S-67) only
#: adds a second spelling to get wrong. The set lives in `batch`, which
#: owns the alias -- `tests/test_rename_retire.py` confines the old word
#: to an allowlist of modules, and this one is rightly not on it.
_UNLISTED_SHEET_VERBS = batch.SHEET_VERB_ALIASES

#: Worked examples: two decided cases and one parked case, each with its
#: sheet, plus a revision, a statement and a user-model update.
#: `parked.yaml` has none on purpose: it is never how a lesson of the
#: packet is parked, and an example would invite exactly that.
#: Every one is fed through the REAL
#: checker in `tests/test_steward_output_contract.py` -- the stage
#: validator, `cases.record`, `statements.add`, `user_model.add_entry` --
#: so an example that stops being valid fails the suite instead of
#: misleading the model. Every id, path and sentence is invented.
STAGE_EXAMPLES: dict[str, str] = {
    "cases/shell-quoting.yaml": """\
kind: resolution
trigger: nightly
outcome: route
records: [lrn-0a1b2c3d]
scope: user
question: >-
  Should the lesson about quoting shell variables become standing guidance?
evidence:
  - ref: "ledger@4f2a9c1:user/shell/lrn-0a1b2c3d.yaml#L3-5"
    quote: "unquoted variables split on spaces"
  - ref: "transcript:example-session#L212"
    quote: "quote it, this bit me twice already"
decision:
  verb: route
  because: >-
    The lesson is specific, it recurred, and no existing guidance covers it.
  confidence: settled
  what_would_change:
    - "guidance that already says this turns up in an always-loaded file"
dependencies:
  statements: []
  user_model: []
  conditions: []
  capabilities: []
""",
    "sheets/shell-quoting.yaml": """\
version: 1
case: $CASE_ID
items:
  - id: lrn-0a1b2c3d
    verb: route
    note: recurred twice; nothing existing covers it; the proposal's destination stands
""",
    "cases/two-duplicates.yaml": """\
kind: resolution
trigger: nightly
outcome: reject
records: [lrn-1b2c3d4e, lrn-2c3d4e5f]
scope: user
question: >-
  Two lessons say the same one-off thing about a single afternoon; keep either?
evidence:
  - ref: "ledger@4f2a9c1:user/misc/lrn-1b2c3d4e.yaml#L3-4"
    quote: "the build was slow that day"
  - ref: "ledger@4f2a9c1:user/misc/lrn-2c3d4e5f.yaml#L3-4"
    quote: "builds were slow this afternoon"
decision:
  verb: reject
  because: >-
    Both describe one afternoon, not a practice; neither would change what a later session does.
  confidence: settled
dependencies:
  statements: []
  user_model: []
  conditions: []
  capabilities: []
""",
    "sheets/two-duplicates.yaml": """\
version: 1
case: $CASE_ID
items:
  - id: lrn-1b2c3d4e
    verb: reject
    note: a one-off observation, not a practice
  - id: lrn-2c3d4e5f
    verb: reject
    note: the same one-off observation as lrn-1b2c3d4e
""",
    "cases/whose-call.yaml": """\
kind: parked
trigger: nightly
outcome: parked
parked_for: overseer
parked_reason: authority-unclear
records: [lrn-3d4e5f6a]
scope: "project:/srv/example-repo"
question: >-
  May a lesson learned in one project change guidance that every project loads?
evidence:
  - ref: "ledger@4f2a9c1:projects/example-repo/lrn-3d4e5f6a.yaml#L3-6"
    quote: "always run the formatter before committing"
decision:
  verb: defer
  because: >-
    The lesson is sound for this project. Widening it to every project is a call about the
    user's other work that nothing in the evidence lets me make. Tentative answer, held
    loosely: keep it here and look again once a second project shows the same need.
  confidence: provisional
  what_would_change:
    - "the user says the formatter rule is meant for every project"
dependencies:
  statements: []
  user_model: []
  conditions: []
  capabilities: []
""",
    "sheets/whose-call.yaml": """\
version: 1
case: $CASE_ID
items:
  - id: lrn-3d4e5f6a
    verb: defer
    note: tentative only; parked for the overseer, so this is recorded and not applied
""",
    "revisions.yaml": """\
entries:
  - case: shell-quoting
    id: lrn-0a1b2c3d
    section: Instruction
    text: Quote every shell variable expansion unless word splitting is wanted.
    because: the original sentence named one variable; the lesson is general
""",
    "statements.yaml": """\
entries:
  - verbatim: "quote it, this bit me twice already"
    source:
      message_ref: "transcript:example-session#L212"
    answers:
      kind: instruction
    scope:
      level: user
""",
    "model-updates.yaml": """\
entries:
  - action: add
    container: C
    source: system-reading
    title: Prefers a general rule over a list of cases
    because: asked twice for the general form of a lesson that named one case
    ref: "transcript:example-session#L212"
    statements: [stmt-0a1b2c3d]
  - action: lapse
    id: um-0a1b
    changed_condition: the project this reading came from was archived
""",
}

def withheld() -> tuple[str, ...]:
    """§4.1's withheld list, verbatim in substance -- never installed as
    prose in the packet; this exists so the run record can print what
    was left out."""
    return (
        "the rejected-classes digest (worker._digest -- the CLI-built "
        "negative-exemplar list `compose_batch_prompt` used to "
        "interpolate before U7) as a 'never' list",
        "the doctrine's §7 'propose only' paragraph (routing-doctrine.md "
        "§7, 'Your boundaries') and §8 paragraph (routing-doctrine.md "
        "§8, 'The decision-support contract (write for the steward "
        "first, the human on presentation)') -- both describe a "
        "different reader",
        "the August reviewer-preference numbers P1-P9 as facts (they "
        "enter only as provisional user-model entries the user has not "
        "yet seen -- there is no review_by field and no expiry, "
        "02-schema.md §3a.4)",
        "other pending records outside the batch, except their ids and "
        "headlines when a brief's 'you may already have this' section "
        "or the canon index names them",
        "transcript text beyond the lines a brief cites",
    )


def _render_containment(run: RunContext) -> str:
    lines = [
        f"run: {run.run_id}",
        f"stage directory (the only place you may write): {run.stage_dir}",
        f"packet {run.packet_index} of {run.packet_count}",
        f"last steward run: {run.last_run_at or 'never'}",
        "verbs the runner will execute from your stage files: "
        + (", ".join(run.verbs_the_runner_executes) or "(none declared)"),
        "you cannot run a verb yourself -- you write stage files; the "
        "runner applies them (§6.1, verb authority, not prompt text)",
    ]
    return "\n".join(lines)


#: Rulings the steward's first real run (2026-09-21) went to the repository
#: to find -- five greps of the spec tree for "always-loaded" before it
#: decided a user-scope route. Each headline is QUOTED, not paraphrased,
#: and `tests/test_steward_prompt.py` checks the quote against the spec.
STANDING_RULINGS = (
    ("S-23", "The cheap tier is PATHED, not DEMAND — at every scope."),
    ("SA-1", "Q1 HELD for the trial — no new escalation to always-loaded lines or to guards."),
)


def _render_standing_rulings() -> str:
    lines = [
        "STANDING RULINGS YOU WOULD OTHERWISE GO LOOKING FOR",
        "Whether a user-scope lesson may land on an always-loaded line (the managed section",
        "of the user's CLAUDE.md) is settled by two decisions in the design authority,",
        "docs/specs/self-learn/03-decisions.md, and by the routing doctrine's gate",
        "(routing-doctrine.md sections 2-3), which the analyst ran to produce each proposal's",
        "destination and decision trace. You need not open any of them; their headlines:",
    ]
    for number, headline in STANDING_RULINGS:
        note = " (user ruling 2026-09-11)" if number == "SA-1" else ""
        lines.append(f'  {number}{note}: "{headline}"')
    lines += [
        "When the proposal's trace and these rulings leave you unsure whether an always-loaded",
        "destination is yours to apply, park the case as `always-loaded-user-scope` (section 12).",
        "`report.context_budget` in the conditions block shows that file's growth against its",
        "threshold.",
    ]
    return "\n".join(lines)


def _render_method() -> str:
    path = worker.package_skill_refs() / "steward-method.md"
    return path.read_bytes().decode("utf-8").rstrip("\n") + "\n\n" + _render_standing_rulings()


def _render_user_model_entry(container: str, entry: dict) -> str:
    lines = [
        f"[{container}] {entry.get('id')} — {entry.get('title')} "
        f"(r{entry.get('r')})",
        f"  held_since: {entry.get('held_since')}",
        f"  because: {entry.get('because')}",
    ]
    conds = entry.get("conditions") or []
    if conds:
        lines.append(f"  conditions: [{', '.join(conds)}]")
    lines.append(f"  status: {entry.get('status')}")
    if entry.get("status") == "LAPSED":
        lines.append(f"  lapsed_at: {entry.get('lapsed_at')}")
        lines.append(f"  changed_condition: {entry.get('changed_condition')}")
    if entry.get("provisional") is True:
        lines.append(
            f"  the user has not yet seen this; cite by "
            f"{entry.get('id')}@r{entry.get('r')}"
        )
    return "\n".join(lines)


def _render_user_model(home: Path) -> str:
    try:
        containers = user_model.show(home)["containers"]
    except Exception as exc:  # noqa: BLE001 -- never blocks assembly
        return f"(user model unavailable: {exc})"
    current: list[str] = []
    lapsed: list[str] = []
    for letter in _USER_MODEL_CONTAINER_ORDER:
        for entry in containers.get(letter, []):
            rendered = _render_user_model_entry(letter, entry)
            if entry.get("status") == "LAPSED":
                lapsed.append(rendered)
            else:
                current.append(rendered)
    ordered = current + lapsed
    if not ordered:
        return "(no user-model entries)"
    return "\n\n".join(ordered)


def _escape_cell(value: object) -> str:
    """N3: a declared-condition title or a settings value can legitimately
    contain a ``|`` or a newline; unescaped, either breaks the Markdown
    table row the steward reads (a `|` opens a new column, a newline
    opens a new row). Backslash is escaped first so escaping this
    function's OWN output a second time would not double up."""
    text = str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n").replace(
        "\r", ""
    )


def _render_conditions(items: list[Item]) -> str:
    lines = ["| key | value | observed_at | source |", "|---|---|---|---|"]
    for item in items:
        cells = (item.key, item.value, item.observed_at, item.source)
        lines.append("| " + " | ".join(_escape_cell(c) for c in cells) + " |")
    return "\n".join(lines)


def _later_observations(home: Path, case_id: str, since: str | None) -> list[str]:
    try:
        full = cases.show(home, case_id, evidence_only=False)
    except cases.CaseError:
        return []
    text = full.sections.get("Later observations", "")
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "(none)":
            continue
        m = _OBS_LINE_RE.match(line)
        ts = m.group(1) if m else None
        # S1: a line whose timestamp does not match `_OBS_LINE_RE` (ts is
        # None) renders unconditionally -- fail-OPEN by design. An
        # unparseable line is more likely an observation-line format drift
        # than something safe to withhold from the steward, so this
        # module errs toward showing it rather than silently dropping it.
        if since is None or ts is None or ts > since:
            out.append(line)
    return out


def _render_open_cases(home: Path, run: RunContext) -> str:
    all_rows = cases.list_cases(home, parked_for="overseer", only_ok=False)
    ok_rows = [r for r in all_rows if r.get("frozen_ok", True)]
    excluded = len(all_rows) - len(ok_rows)
    open_rows = [r for r in ok_rows if not r.get("superseded_by")]

    blocks: list[str] = []
    for row in open_rows:
        case_id = row["case"]
        try:
            view = cases.show(home, case_id)  # blind default -- kept
        except cases.CaseError as exc:
            blocks.append(f"case {case_id}: unavailable ({exc})")
            continue
        text = view.to_text()
        later = _later_observations(home, case_id, run.last_run_at)
        if later:
            text += "\n  Later observations (since last run):\n" + "\n".join(
                f"    {ln}" for ln in later
            )
        blocks.append(text)
    if excluded:
        blocks.append(f"{excluded} cases excluded: freeze hash mismatch")
    if not blocks:
        return "(no open parked cases)"
    return "\n\n".join(blocks)


def _existing_cases_for_record(
    home: Path, record_id: str | None
) -> tuple[list[dict], int]:
    """S6: mirrors `_render_open_cases`'s own `frozen_ok` filter (the U2
    TAMPERED convention "the rule every index consumer follows") instead
    of relying on `list_cases(only_ok=True)` to drop tampered rows
    invisibly. Returns the intact rows plus how many were excluded, so
    the caller can render the same one-line exclusion count the
    open_cases block renders."""
    if not record_id:
        return [], 0
    all_rows = cases.list_cases(home, record_id=record_id, only_ok=False)
    ok_rows = [r for r in all_rows if r.get("frozen_ok", True)]
    return ok_rows, len(all_rows) - len(ok_rows)


def _render_briefs(home: Path, proposals: list[dict]) -> str:
    if not proposals:
        return "(no records in this packet)"
    blocks: list[str] = []
    for proposal in proposals:
        record_id = proposal.get("id")
        prior_rows, excluded = _existing_cases_for_record(home, record_id)
        for prior_row in prior_rows:
            try:
                prior_view = cases.show(home, prior_row["case"])  # blind default
            except cases.CaseError:
                continue
            blocks.append(f"### prior case for {record_id}\n{prior_view.to_text()}")
        if excluded:
            blocks.append(f"{excluded} prior cases excluded: freeze hash mismatch")
        header = f"### brief: {record_id or '(unknown id)'}"
        rows = worker.render_brief(proposal)
        body = "\n".join(f"[{key}] {text}" for key, text in rows)
        blocks.append(f"{header}\n{body}" if body else header)
    return "\n\n".join(blocks)


def _words(values) -> str:
    return " | ".join(sorted(values))


def _sheet_verb_lines() -> list[str]:
    """One line per sheet verb, from `batch.PERMITTED_KEYS` /
    `batch.REQUIRED_KEYS` -- the same two tables `batch.load_sheet`
    checks an item against. `by` is left out: the runner writes it."""
    lines = []
    for verb in sorted(batch.PERMITTED_KEYS):
        if verb in _UNLISTED_SHEET_VERBS:
            continue
        required = sorted(batch.REQUIRED_KEYS.get(verb, frozenset()))
        optional = sorted(batch.PERMITTED_KEYS[verb] - set(required) - {"by"})
        parts = []
        if required:
            parts.append("required: " + ", ".join(required))
        if optional:
            parts.append("optional: " + ", ".join(optional))
        lines.append(f"    {verb:<19} {'; '.join(parts) if parts else '(no keys)'}")
    return lines


def _render_output_contract() -> str:
    """The brief's last block: the exact shape of every file the steward
    writes. Closed sets and key tables are read from the checkers' own
    constants; the examples are `STAGE_EXAMPLES`, which the suite feeds
    through those same checkers."""
    model_parked_reasons = cases.PARKED_REASONS - RUNNER_ONLY_PARKED_REASONS
    lesson_sections = sorted({name for names in records.REQUIRED_SECTIONS.values() for name in names})
    out = [
        "output contract -- the files you write, and the exact shape of each.",
        "",
        "Everything below is generated from the constants the runner's own checkers read,",
        "and every example has been run through those checkers. You do not need to read",
        "this product's source code to find a format; if something here is unclear, write",
        "the closest valid thing and say so in the case's `because`.",
        "",
        "The runner checks every file before anything touches the ledger. If a file fails,",
        "you get ONE repair turn with the error text. Files that are YAML input are what is",
        "described here -- not the finished case document the runner later renders from them.",
        "",
        "FILES (inside the stage directory; any other file is refused):",
    ]
    out += [f"  {name:<20} {purpose}" for name, purpose in OUTPUT_CONTRACT.items()]
    out += [
        "",
        "RULES THE CHECKER ENFORCES ACROSS FILES",
        "  - At least one case. Every case has a sheet with the SAME file name, and the reverse.",
        "  - Every lesson in this packet appears in the `records:` of EXACTLY ONE case --",
        "    not zero, not two. Lessons that share one decision may share one case.",
        "  - Every lesson in a case has its own item in that case's sheet. A lesson the case",
        "    covers and the sheet forgets is refused.",
        "  - File names are yours to choose (`<lesson id>.yaml` is fine).",
        "",
        "cases/<name>.yaml -- a YAML mapping with exactly these keys:",
        f"  kind           {_words(cases.KINDS)}",
        f"  trigger        {_words(cases.TRIGGERS)}   (a scheduled run like this one: nightly)",
        f"  outcome        {_words(cases.OUTCOMES)}",
        "                 The one word that names what this case decides. Nothing checks it",
        "                 against the sheet's verbs; where a verb has no word of its own, use",
        "                 the nearest (rescope -> rehome, supersede -> replaced).",
        "  records        non-empty list of lesson ids (lrn- plus 8 hex digits)",
        "  scope          non-empty text: `user`, or `project:<path>`",
        "  question       one sentence: what is being decided",
        "  evidence       non-empty list of {ref, quote}; both required; quote is verbatim",
        "  decision       mapping: `because` (required), `confidence` (required:",
        f"                 {_words(cases.CONFIDENCE_VALUES)}), `verb`, `what_would_change` (list of",
        "                 strings), and for a retire `covered_by`",
        "  dependencies   mapping of four lists of strings: statements, user_model, conditions,",
        "                 capabilities (use [] for none)",
        "  supersedes     optional: the id of a case this one replaces (case- plus 8 hex digits)",
        "  parked_for, parked_reason   only when kind is parked (method section 12):",
        f"                 parked_for is always `overseer`; parked_reason is one of {_words(model_parked_reasons)}",
        f"                 ({_words(RUNNER_ONLY_PARKED_REASONS)} are written by the runner; never write them)",
        "  Do NOT write: case, opened_at, actor, run_id, superseded_by, decided_sha256, presented.",
        "  The runner fills those in. No line of any text field may start with `## `, and every",
        "  text field is secret-scanned; a hit refuses the case.",
        "",
        "  evidence `ref` forms:",
        "    ledger@<commit>:<path>#L<a>-<b>        a lesson's own record or proposal",
        "    transcript:<session-id>#L<n>            a transcript line",
        "    conversation:<obs-id>                   a line typed into the overseer conversation",
        "    file@<commit>:<path>#L<a>-<b>           a tracked canon or reference file",
        "    file:<path>@<mtime-iso>                 an untracked file",
        "    stmt-<8 hex> | um-<4 hex>@r<n> | cond:<key>@<observed_at> | telemetry:<event-id> | case-<8 hex>",
        "",
        "sheets/<name>.yaml -- a YAML mapping with exactly three keys:",
        "  version: 1",
        "  case: $CASE_ID        write this literally; the runner substitutes the real id",
        "  items:                non-empty list; each item has `id` (a lesson id), `verb`, and",
        "                        only the keys its verb allows. Never write `by`: the runner",
        "                        writes `by: steward` on every item that takes it.",
        "  verbs and their keys:",
    ]
    out += _sheet_verb_lines()
    out += [
        "  `defer`'s `until` is a date, YYYY-MM-DD, today (UTC) or later; left out, it is 30 days.",
        "  WHERE A ROUTE LANDS. Leave `route`'s `dest` out to take the lesson's proposal exactly",
        "  as written: its destination AND its variant -- `local` (the host's git-ignored",
        "  CLAUDE.local.md) or `rules` (a path-scoped file under .claude/rules/, with the",
        "  proposal's `rules_topic` and `rules_paths`). Writing `dest` REPLACES the proposal's",
        "  whole destination, variant included: a bare `dest: claude-md` is the host's plain",
        "  CLAUDE.md, which on a project host is usually a committed file. Write `dest` only to",
        "  choose somewhere other than the proposal; to keep a variant while writing it, spell",
        "  the variant: `claude-md:local`, or `claude-md:rules:<topic>` (the proposal's",
        "  `rules_paths` carry over only when it names the same topic). `dest` is one of",
        f"  {_words(ledger_ops.PROPOSAL_DESTINATIONS)}, or `reference:<file name>`,",
        "  `claude-md:local`, `claude-md:rules:<topic>`. `follow_up` (with `unblocks_on`,",
        "  a gate label, and `follow_up_note`) records that this routing is a known-partial form",
        "  and names the planned stronger one; `allow_empty_glob` routes a path-scoped rule whose",
        "  glob matches nothing on this machine; `collapse` folds a merge cluster into this",
        "  lesson as its survivor.",
        f"  `retire`'s `covered_by` is `<kind>:<name>`, kind one of {_words(records.COVERAGE_KINDS)}:",
        "  `claude-md:<path of the file>`, `skill-md:<skill name>`, `reference:<file name>`,",
        "  `output-style:<style name>` -- the surface whose text already covers the lesson",
        "  (method section 9). `supersede` marks the item's `id` (the OLD lesson) replaced by",
        "  `new_id`, which must already exist as a record; the successor is routed by its own",
        "  item. `rehome` and `rescope` both move a pending or deferred lesson to another",
        "  registered scope (`to`: `user`, `skill:<name>`, or a project path). `reopen` returns a",
        "  rejected or superseded lesson to pending.",
        "  WHAT EACH VERB NEEDS THE LESSON'S STATUS TO BE (the verbs' own checks; a mismatch is",
        "  a refusal naming the real status, and the lesson comes back to you as below):",
        f"    route, reject, defer, rehome, rescope, revise:  {_words(ledger_ops.LIVE_STATUSES)}",
        f"    retire, supersede (the old and the new lesson):  {_words(ledger_ops.RESOLVABLE_STATUSES)}",
        f"    undefer:  {_words(ledger_ops.DEFERRED_ONLY)}      reopen:  {_words(verbs.REOPEN_ADMITTED_STATUSES)}",
        f"  These are never sheet verbs and are refused: {', '.join(sorted(batch.REFUSED_VERBS_LITERAL))}, and",
        "  anything starting `host `. A route to `dest: hook` is not applied: the runner parks",
        "  that case for the overseer.",
        *textwrap.wrap(
            _REFUSED_LINE_SENTENCE, width=90, initial_indent="  ", subsequent_indent="  "
        ),
        "",
        "revisions.yaml -- `entries:` list. Each entry: `case` (the FILE NAME of the case whose",
        "  sheet it belongs to, without .yaml), `id`, `section`, `text`, `because` -- all required.",
        f"  `section` is a heading the lesson already has ({', '.join(lesson_sections)}). The runner turns",
        "  each entry into a `revise` item placed just before that lesson's `route` item.",
        "",
        "statements.yaml -- `entries:` list. Each entry: `verbatim` (required; the user's exact",
        "  words), `source: {message_ref: ...}` (required; `transcript:<session-id>#L<n>` or",
        f"  `conversation:obs-<8 hex>`), and optionally `answers: {{kind: {_words(statements.ANSWER_KINDS)}}}`,",
        f"  `scope: {{level: {_words(statements.SCOPE_LEVELS)}, host: <path, required for project>}}`, `uncertainty`,",
        "  `amends` (stmt- plus 8 hex digits). Never a sentence you composed.",
        "",
        "model-updates.yaml -- `entries:` list. Each entry has `action: add` or `action: lapse`.",
        "  add:   `container` (you may add to C only), `source: system-reading` (the only source",
        "         you may add), `title`, `because`, `ref`, `statements` (at least one stmt- id) --",
        "         all required; optional `conditions`, `basis` (lists of strings), `held_since`.",
        "         The stmt- id must already exist: a statement you add in this same packet has",
        "         no id until the runner applies it, so it cannot be cited here yet.",
        "         `title` and `because` are one line each and may not use the words ratified,",
        "         ruled, stated or contradicted.",
        "  lapse: `id` (um- plus 4 hex digits) and EXACTLY ONE of `changed_condition`, `contrary`,",
        "         `consolidated_into`.",
        "",
        "PARKING A LESSON (method section 12) -- when you cannot decide it alone:",
        "  Write its case like any other, with `kind: parked`, `outcome: parked`,",
        "  `parked_for: overseer`, and the `parked_reason` that actually stopped you. `question`",
        "  is the question for the overseer; `decision.because` says what stopped you and what",
        "  fact or value is missing; `decision.confidence` is `provisional`.",
        "  Its sheet is your TENTATIVE ANSWER: the items you would have written had you decided.",
        "  The runner records them as parked and applies none of them, so the lesson stays",
        "  pending until the overseer decides. A sheet cannot be empty, so give a tentative",
        "  answer even when you hold it loosely, and say how loosely in `because`.",
        "  A parked case still counts toward the every-lesson-in-one-case rule.",
        "",
        "parked.yaml -- a FURTHER question for the overseer, never the way to park a lesson of",
        "  this packet. `entries:` list. Each entry is a case mapping with the keys above, minus",
        "  kind, outcome and parked_for (the runner sets them), plus a `parked_reason` you may",
        "  choose. An entry here does NOT count toward the every-lesson-in-one-case rule.",
        "",
        "EXAMPLES (all ids and text invented)",
    ]
    for name, body in STAGE_EXAMPLES.items():
        out.append(f"\n--- {name}")
        out.append(body.rstrip("\n"))
    return "\n".join(out)

def _ordered_blocks(
    home: Path,
    run: RunContext,
    proposals: list[dict],
    items: list[Item],
) -> tuple[Block, ...]:
    """The seven blocks, §4.1's order. Factored out of :func:`assemble`
    so a test can monkeypatch this ONE function to prove the offset
    test actually catches a scrambled order (a swap here is a swap in
    `assemble`'s own real return value, not a copy the test built
    itself)."""
    return (
        ("containment", _render_containment(run)),
        ("method", _render_method()),
        ("user_model", _render_user_model(home)),
        ("conditions", _render_conditions(items)),
        ("open_cases", _render_open_cases(home, run)),
        ("briefs", _render_briefs(home, proposals)),
        ("output_contract", _render_output_contract()),
    )


def _render_sent_back(returned: dict[str, dict]) -> str:
    """S-71 §4.6: each lesson a ledger refusal sent back, with the case that
    decided it before and the ledger's words, then the one instruction."""
    lines = [SENT_BACK_TITLE, ""]
    for record_id in sorted(returned):
        entry = returned[record_id] or {}
        lines.append(f"- {record_id} (earlier case {entry.get('case') or 'unknown'}):")
        words = [str(line) for line in entry.get("lines") or [] if str(line).strip()]
        lines += [f"    the ledger said: {line}" for line in words] or [
            "    the ledger said: (no words recorded)"
        ]
    lines += ["", SENT_BACK_INSTRUCTION]
    return "\n".join(lines)


def assemble(
    home: Path | str,
    cache_dir: Path | str,
    run: RunContext,
    proposals: list[dict],
    *,
    conditions_items: list[Item] | None = None,
    returned: dict[str, dict] | None = None,
) -> Packet:
    """Interface §4.1: the seven blocks, in order, evidence before advice.
    Never mutates the ledger, never reads a transcript, and never reads
    `hosts.yaml` or `settings.json` itself -- only through
    :func:`conditions.feed`. A caller assembling several packets of ONE
    run passes the feed it built once as ``conditions_items`` (the feed
    is one snapshot "as of this run", plan §4.4); left out, the feed is
    built here.

    ``returned`` (S-71 §4.6) maps a lesson of this packet the ledger sent
    back to ``{"case": <the case that decided it>, "lines": [<the ledger's
    words>]}``; when it names any, a `sent_back` block titled
    :data:`SENT_BACK_TITLE` goes in just before the open-cases block."""
    home = Path(home)
    cache_dir = Path(cache_dir)
    items = conditions.feed(home, cache_dir) if conditions_items is None else list(conditions_items)
    blocks = _ordered_blocks(home, run, proposals, items)
    if returned:
        at = next(
            (index for index, (name, _body) in enumerate(blocks) if name == "open_cases"),
            len(blocks),
        )
        blocks = (*blocks[:at], ("sent_back", _render_sent_back(returned)), *blocks[at:])
    text = "\n\n".join(f"=== {name} ===\n{body}" for name, body in blocks)
    return Packet(blocks=blocks, text=text, withheld=withheld())
