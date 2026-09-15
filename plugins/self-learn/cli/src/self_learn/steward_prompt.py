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
from dataclasses import dataclass
from pathlib import Path

from . import cases
from . import conditions
from . import user_model
from . import worker
from .conditions import Item

__all__ = [
    "RunContext",
    "Block",
    "Packet",
    "OUTPUT_CONTRACT",
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


#: §4.1 item 7: file names and schemas for the runner's stage files. ONE
#: source (U10 imports this constant rather than re-stating it) — this
#: unit's own synthesis of plan §4.1 item 7 / §5.1 steps 7-10 and
#: interface §1-§2, since U10 (the actual writer/reader) is not built
#: yet; see this unit's report for what is read vs. inferred here.
OUTPUT_CONTRACT: dict[str, str] = {
    "cases/*.yaml": (
        "one decision case per file (02-schema.md §3a.1/§3a.2): the six "
        "sections in order (Identity and scope, Evidence, Decision, "
        "Dependencies, Application, Later observations); frontmatter "
        "carries case, opened_at, actor, run_id, records, kind, trigger, "
        "outcome, supersedes, superseded_by, parked_for, parked_reason, "
        "presented, decided_sha256. Sections 1-4 are frozen at write time "
        "(decided_sha256 covers them, re-verified on every read); only "
        "sections 5 and 6 are append-only afterward. Written by "
        "cases.record."
    ),
    "sheets/*.yaml": (
        "one sheet per case (plan §4.1 item 7): top-level `case:` names "
        "the case id this sheet belongs to. The runner applies it "
        "through `batch --dry-run --json` first, then `batch` (commit "
        "B) -- the same shape as a human-authored batch sheet."
    ),
    "parked.yaml": (
        "entries the runner turns into cases.record(kind=parked, "
        "parked_for=overseer, parked_reason=<one of the closed set, "
        "interface §1.3/§1.7>) calls -- parking never installs standing "
        "belief."
    ),
    "revisions.yaml": (
        "entries the runner turns into verbs.revise calls, one per "
        "pending record whose SENTENCE (never its claim) is being "
        "reshaped; each runs inside its case's sheet application "
        "(commit B)."
    ),
    "model-updates.yaml": (
        "entries the runner turns into user_model.add_entry / "
        "user_model.lapse_entry calls -- PROVISIONAL system readings "
        "only (a system-reading entry is always created "
        "provisional: true); a lapse names the changed condition."
    ),
    "statements.yaml": (
        "entries the runner turns into statements.add calls -- "
        "transcript-ref only: a `transcript:<session>#L<n>` or "
        "`conversation:<obs-id>` pointer, never inline quoted prose the "
        "steward invented."
    ),
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


def _render_method() -> str:
    path = worker.package_skill_refs() / "steward-method.md"
    return path.read_bytes().decode("utf-8")


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


def _render_output_contract() -> str:
    lines = ["output contract -- stage files the runner reads after you write:"]
    for name, schema in OUTPUT_CONTRACT.items():
        lines.append(f"\n{name}\n  {schema}")
    return "\n".join(lines)


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


def assemble(
    home: Path | str,
    cache_dir: Path | str,
    run: RunContext,
    proposals: list[dict],
) -> Packet:
    """Interface §4.1: the seven blocks, in order, evidence before advice.
    Never mutates the ledger, never reads a transcript, and never reads
    `hosts.yaml` or `settings.json` itself -- only through
    :func:`conditions.feed`."""
    home = Path(home)
    cache_dir = Path(cache_dir)
    items = conditions.feed(home, cache_dir)
    blocks = _ordered_blocks(home, run, proposals, items)
    text = "\n\n".join(f"=== {name} ===\n{body}" for name, body in blocks)
    return Packet(blocks=blocks, text=text, withheld=withheld())
