"""The overseer builds, changes and retires the skills self-learn owns
(SK3, S-107; skill-writing plan §2 steps 4, 7 and 10,
decisions D4 and D10; ``03-decisions.md`` S-107 parts 4-6).

This module is the overseer runner's half of skill writing. The writer
itself (template check, name check, secret scan, deploy, registry row,
link) is :mod:`self_learn.skill_writer`; the runner calls it in-process with
``by="overseer"``. What lives here:

**Phase B's inputs** (:func:`stage_phase_b`), in the workspace:

- ``owned-skills/<name>/`` for every live skill self-learn owns: ``files/``
  (its ``SKILL.md`` without the runner's stamp and the managed section, and
  its ``references/*.md`` -- exactly what phase B edits and hands back),
  ``row.yaml`` (its registry row, less the 64-hex hash, which the whole-stage
  secret scan would match), ``lessons.yaml`` (the lessons routed into it)
  and ``changed-since-last-write.diff`` (what changed in its authored text
  since self-learn last wrote it, read from the skills root's history);
- ``vetoes.yaml``: the vetoed names, the live skills whose name is vetoed,
  and the user's open retirement requests (read from the registry by
  :mod:`self_learn.skill_requests`);
- ``skill-proposals.yaml``: the steward's parked ``skill-proposal`` cases
  (their files are in ``parked/``);
- ``skill-writing.yaml``: whether this run deploys what phase B writes.

A staged file the secret scan matches is replaced by a one-line stub, as
``run._stage_lessons`` does, and that skill cannot be rewritten this run
(phase B never saw its whole text, so a rewrite could carry the stub over
the real file).

**Phase B's output.** ``skills/<name>/`` is one skill to build or rewrite.
It belongs to the case/sheet pair whose case carries ``decision.skill``
naming it (:func:`step_for_case`). A case whose ``decision.skill`` names an
owned skill and that wrote no folder routes lessons into that skill: no
skill step, ordinary routing. So is a case that names a skill self-learn
does not own, writes no folder and routes nothing into ``new-skill:<name>``
(a declined proposal, a route into a linked skill). A case with ``outcome: retire`` and
``decision.skill`` retires the skill once its sheet has moved every lesson
out. Each step is checked here with ``skill_writer.check`` before anything
reaches the ledger; a refused check drops the pair. A folder no case names
is dropped and named (:func:`unclaimed_folders`).

**Writing on or off** (:func:`writing_state`). ``overseer.skill_writing``
is ``on`` (the default) or ``off``, read from ``config.yaml`` only;
``auto``, the old default, reads as ``on``, and any other value (a YAML
boolean included) reads as ``off``. ``on`` deploys from the first run;
``off`` keeps every build or rewrite as a checked draft in the ledger
(``overseer/skills/<week>/drafts/<name>/``), makes no retirement, and
applies none of those pairs (S-107 part 6 as amended by
S-NEXT-ft-skills-on: the one-week drafts-only trial is gone).

**Applying** (:func:`apply_write`, :func:`apply_retire`). The runner writes
a skill BEFORE it records the pair's case and applies its sheet (a refused
write drops the pair: nothing of it reaches the ledger), and retires a
skill AFTER the sheet has moved its lessons out. Both are idempotent, so a
resumed run finishes what an interrupted one started.

Nothing here takes a lock or writes the ledger itself: the writer takes its
own locks, the stage is the runner's (``run._write_stage``), and the drafts
are written by the runner inside its own locked commits.
"""

from __future__ import annotations

import copy
import difflib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, cast

from ruamel.yaml import YAML

from .. import config, scan, settings, skill_registry, skill_writer
from ..hosts import HostsError, load_hosts
from ..skill_registry import STATUS_LIVE, SkillRegistryError

__all__ = [
    "DIFF_FILE",
    "FILES_DIR",
    "LESSONS_FILE",
    "LEDGER_DIR",
    "MODE_OFF",
    "MODE_ON",
    "OWNED_DIR",
    "PROPOSALS_FILE",
    "ROW_FILE",
    "SKILL_PROPOSAL_REASON",
    "STAGE_SKILLS_DIR",
    "VETOES_FILE",
    "WRITING_FILE",
    "SkillPairError",
    "SkillStep",
    "StagedSkills",
    "StepOutcome",
    "WritingState",
    "apply_rename",
    "apply_retire",
    "apply_write",
    "claimed_name",
    "decision_lessons",
    "draft_entry",
    "draft_files",
    "drafts_dir",
    "preview_for_step",
    "renamed_from",
    "report_lines",
    "short_hashes",
    "stage_phase_b",
    "stale_draft_files",
    "step_for_case",
    "unclaimed_folders",
    "writing_mode",
    "writing_state",
]

MODE_ON, MODE_OFF = settings.SKILL_WRITING_MODES

# ------------------------------------------------------------- the workspace

#: Phase B's output: ``skills/<name>/`` per skill to build or rewrite.
STAGE_SKILLS_DIR = "skills"
#: Phase B's input: ``owned-skills/<name>/`` per live skill self-learn owns.
OWNED_DIR = "owned-skills"
FILES_DIR = "files"
ROW_FILE = "row.yaml"
LESSONS_FILE = "lessons.yaml"
DIFF_FILE = "changed-since-last-write.diff"
VETOES_FILE = "vetoes.yaml"
PROPOSALS_FILE = "skill-proposals.yaml"
WRITING_FILE = "skill-writing.yaml"

#: The steward's parked reason for a skill it proposes (SK6 adds it to
#: ``cases.PARKED_REASONS``; until then no such case can exist).
SKILL_PROPOSAL_REASON = "skill-proposal"

# ---------------------------------------------------------------- the ledger

#: ``overseer/skills/`` under the ledger home: ``<week>/drafts/<name>/``
#: (``02-schema.md`` §3, S-107). A ``writing-trial.yaml`` an older run left
#: here is history: nothing reads it (S-NEXT-ft-skills-on).
LEDGER_DIR = "overseer/skills"

#: What a step does, in the report's words.
_LABEL_BUILD = "build"
_LABEL_CHANGE = "change"
_LABEL_RETIRE = "retire"
_LABEL_RENAME = "rename"
_DONE_TAGS = {
    _LABEL_BUILD: "[new skill]",
    _LABEL_CHANGE: "[skill changed]",
    _LABEL_RETIRE: "[skill retired]",
    _LABEL_RENAME: "[skill renamed]",
}
_WOULD = {
    _LABEL_BUILD: "would build",
    _LABEL_CHANGE: "would change",
    _LABEL_RETIRE: "would retire",
    _LABEL_RENAME: "would rename",
}


#: A git or authored-content hash in a message. The writer names full
#: sha256 values (a stale ``--expect``), and the run's secret scan reads any
#: run of 48 or more hex digits as a likely secret, which would redact the
#: whole line; the report needs the reason, not the full hash.
_LONG_HEX_RE = re.compile(r"[0-9a-f]{40,}")


def short_hashes(text: str) -> str:
    """*text* with every long hex run cut to its first 12 digits."""
    return _LONG_HEX_RE.sub(lambda m: m.group(0)[:12] + "…", text)


class SkillPairError(Exception):
    """A pair's skill step cannot be made: the pair is dropped and the
    message is its "Refused / could not do" line."""


def _yaml_text(data: Any) -> str:
    stream = io.StringIO()
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.width = 4096
    yaml.dump(data, stream)
    return stream.getvalue()


# ------------------------------------------------------------ writing on/off


def writing_mode(home: Path | str) -> tuple[str, str | None]:
    """``overseer.skill_writing`` as the runner obeys it, and a sentence
    when the value in ``config.yaml`` is not one it knows.

    Read from ``config.yaml`` only: no environment variable and no override
    channel (S-107 part 6). A missing key is the default, ``on``, and so is
    ``auto``, the old default (S-NEXT-ft-skills-on: it meant "write" after
    one week, so reading it as ``off`` would turn writing off for the person
    who never touched the switch). A ``config.yaml`` that cannot be read
    reads as ``off``. Any other value -- a typo, ``null``, a YAML boolean
    such as ``false`` -- reads as ``off``, never as the default, so a
    mistyped rollback fails closed. (``settings.resolve_setting`` would read
    a boolean as the default; that is why the runner does not use it here.)"""
    found = config.settings_leaf(home, "overseer", "skill_writing")
    if found is None:
        broken = settings.skill_writing_config_unreadable(home)
        if broken is not None:
            # Fix round 1 (gate r1 NIT): `settings_leaf` answers None for a
            # config.yaml it cannot read as it does for a missing key; a
            # broken file must not read as the default.
            return MODE_OFF, (
                f"config.yaml {broken}, so overseer.skill_writing cannot be read; it reads as "
                "off, so every skill this run builds or changes is kept as a draft"
            )
        return MODE_ON, None
    raw = found[1]
    if raw == settings.SKILL_WRITING_LEGACY_ON:
        return MODE_ON, None
    if isinstance(raw, str) and raw in settings.SKILL_WRITING_MODES:
        return raw, None
    return MODE_OFF, (
        f"overseer.skill_writing is {raw!r} in config.yaml, which is not on or off; "
        "it reads as off, so every skill this run builds or changes is kept as a draft"
    )


def drafts_dir(home: Path | str, week: str, name: str) -> Path:
    """``overseer/skills/<week>/drafts/<name>/``."""
    return Path(home) / LEDGER_DIR / week / "drafts" / name


@dataclass(frozen=True)
class WritingState:
    """What ``overseer.skill_writing`` means for one run."""

    #: ``on`` or ``off``, as the runner reads it.
    mode: str
    #: Whether this run deploys what phase B builds, changes or retires.
    deploy: bool
    #: The sentence for a value the runner does not know.
    note: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "deploy": self.deploy,
            **({"note": self.note} if self.note else {}),
        }

    def stage_text(self) -> str:
        if self.deploy:
            says = (
                "This run deploys what you write: a skill you build or change is written to the "
                "skills root and linked, and a skill you retire is removed."
            )
        else:
            says = (
                "This run deploys nothing. Every skill you build or change is checked by the same "
                "rules as a real write and kept as a draft in the ledger; a retirement is not made; "
                "the pairs that would move lessons for them are not applied. The report says what "
                "would have been built, changed or retired. Write each skill exactly as you would if "
                "it were deployed."
            )
        return _yaml_text({"mode": self.mode, "deploy": self.deploy, "says": says})


def writing_state(home: Path | str) -> WritingState:
    """``on`` deploys; ``off`` does not."""
    mode, note = writing_mode(home)
    return WritingState(mode=mode, deploy=mode == MODE_ON, note=note)


# ---------------------------------------------------------------- staging


@dataclass
class StagedSkills:
    """What :func:`stage_phase_b` showed phase B, for the checks after it."""

    #: Each live skill's authored sha256 as staged: the ``expect_sha`` of a
    #: rewrite (D4's compare-and-swap). Absent for a skill with no files.
    expect: dict[str, str] = field(default_factory=dict)
    #: Live skills a staged file of which was replaced by a stub.
    withheld: set[str] = field(default_factory=set)
    #: Live skills with no ``SKILL.md`` in the skills root.
    missing: set[str] = field(default_factory=set)
    #: Lines for "Refused / could not do" (nothing here refuses the run).
    notes: list[str] = field(default_factory=list)


Writer = Callable[[Path, Path, str], None]


def _stub(rule: str, where: str) -> str:
    return (
        f"withheld: the secret scan matched {rule}; the text is in {where}. "
        "This skill cannot be rewritten this run.\n"
    )


def _row_for_stage(row: dict) -> dict:
    """The registry row without its 64-hex hash (the whole-stage secret
    scan would match it), with ``case`` and ``by`` kept."""
    out = copy.deepcopy(row)
    last = out.get("last_write")
    if isinstance(last, dict):
        last.pop("authored_sha256", None)
    return out


def stage_phase_b(
    home: Path | str, stage: Path, parked_rows: list[dict], state: WritingState, write: Writer,
) -> StagedSkills:
    """Write phase B's skill inputs into *stage* with *write* (the runner's
    ``_write_stage``). Never raises for the ledger's content: a registry or a
    skills root that cannot be read is said in a note, and the files say
    what could not be shown."""
    home = Path(home)
    staged = StagedSkills()
    write(stage, stage / WRITING_FILE, state.stage_text())
    try:
        registry = skill_registry.load(home)
    except SkillRegistryError as exc:
        why = short_hashes(str(exc))
        if scan.scan(why):
            why = "its text matched the secret scan"
        staged.notes.append(
            f"owned-skills.yaml could not be read ({why}); no skill self-learn owns was shown "
            "to phase B, and none can be built, changed or retired this run"
        )
        write(stage, stage / VETOES_FILE, _yaml_text({"unreadable": why}))
        _stage_proposals(stage, parked_rows, write)
        return staged
    for name in registry.live():
        try:
            _stage_owned(home, stage, registry, name, staged, write)
        except Exception as exc:  # noqa: BLE001 -- one skill's trouble never costs the run
            staged.missing.add(name)
            why = short_hashes(f"{type(exc).__name__}: {exc}")
            if scan.scan(why):
                why = f"{type(exc).__name__} (its message matched the secret scan)"
            staged.notes.append(
                f"owned skill {name}: could not be shown to phase B ({why}); "
                "it cannot be changed this run"
            )
            write(stage, stage / OWNED_DIR / name / ROW_FILE, _yaml_text({
                "name": name, "shown": False, "why": why,
            }))
    _stage_vetoes(home, stage, registry, staged, write)
    _stage_proposals(stage, parked_rows, write)
    return staged


def _stage_owned(
    home: Path, stage: Path, registry: skill_registry.Registry, name: str,
    staged: StagedSkills, write: Writer,
) -> None:
    folder = stage / OWNED_DIR / name
    row = registry.row(name) or {}
    lessons = skill_writer.routed_lessons(home, name)
    write(stage, folder / LESSONS_FILE, _yaml_text({"lessons": lessons}))
    deployed = skill_writer.deployed_files(home, name)
    if deployed is None:
        staged.missing.add(name)
        write(stage, folder / ROW_FILE, _yaml_text({
            "name": name, "row": _row_for_stage(row), "deployed": False,
            "says": (
                "This skill's SKILL.md is not in the skills root. It cannot be changed until a "
                "person restores it; the selftest names it."
            ),
        }))
        return
    withheld: list[str] = []
    for rel, text in sorted(skill_writer.draft_view(deployed).items()):
        hits = scan.scan(text)
        if hits:
            withheld.append(rel)
            text = _stub(hits[0].rule, "the skills root")
        write(stage, folder / FILES_DIR / rel, text)
    current = skill_writer.deployed_authored_sha256(home, name)
    recorded = (row.get("last_write") or {}).get("authored_sha256")
    diff = _changed_since_last_write(home, name, row, deployed, current, recorded)
    hits = scan.scan(diff)
    if hits:
        withheld.append(DIFF_FILE)
        diff = _stub(hits[0].rule, "the skills root's history")
    write(stage, folder / DIFF_FILE, diff)
    if current is not None:
        staged.expect[name] = current
    if withheld:
        staged.withheld.add(name)
    write(stage, folder / ROW_FILE, _yaml_text({
        "name": name,
        "row": _row_for_stage(row),
        "deployed": True,
        "changed_since_last_write": current != recorded,
        **({"withheld": withheld} if withheld else {}),
    }))


def _skills_root(home: Path) -> Path | None:
    try:
        return load_hosts(home).skills_root
    except HostsError:
        return None


def _files_at_last_write(home: Path, name: str, row: dict) -> dict[str, str] | None:
    """The skill's files as self-learn's last write (or its last rename)
    committed them to the skills root (one definition:
    ``skill_writer.files_at_last_write``)."""
    return skill_writer.files_at_last_write(home, name, row)


def _diff_lines(old: str, new: str, rel: str) -> list[str]:
    lines = []
    for line in difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"last-write/{rel}", tofile=f"now/{rel}",
    ):
        lines.append(line if line.endswith("\n") else line + "\n")
    return lines


def _changed_since_last_write(
    home: Path, name: str, row: dict, deployed: dict[str, str],
    current: str | None, recorded: str | None,
) -> str:
    """D4's view for phase B: what a person (or another agent) changed in
    the skill's authored text since self-learn last wrote it."""
    case = (row.get("last_write") or {}).get("case")
    if current is not None and current == recorded:
        return (
            f"# Unchanged: {name}'s text is as self-learn last wrote it (case {case}).\n"
        )
    old = _files_at_last_write(home, name, row)
    if old is None:
        return (
            f"# Changed: {name}'s text is not as self-learn last wrote it (case {case}), and that "
            "version could not be found in the skills root's history, so no diff can be shown. "
            f"{FILES_DIR}/ holds the text as it is now. Keep what a person wrote unless your case "
            "says why not.\n"
        )
    before = skill_writer.draft_view(old)
    after = skill_writer.draft_view(deployed)
    lines = [
        f"# Changed since self-learn last wrote {name} (case {case}): lines starting with + are "
        "new since then, lines starting with - were taken out. Keep what a person wrote unless "
        "your case says why not.\n"
    ]
    for rel in sorted(set(before) | set(after)):
        if before.get(rel, "") != after.get(rel, ""):
            lines += _diff_lines(before.get(rel, ""), after.get(rel, ""), rel)
    return "".join(lines)


def _stage_vetoes(
    home: Path, stage: Path, registry: skill_registry.Registry, staged: StagedSkills,
    write: Writer,
) -> None:
    """``vetoes.yaml``: the vetoed names, the live skills under a vetoed
    name (``renames_owed``) and the live skills the user asked to retire
    (``retire_requests``), all read from the registry alone
    (:mod:`self_learn.skill_requests`, S-NEXT-skills-chain)."""
    from .. import skill_requests

    data: dict[str, Any] = {
        "vetoed": [dict(entry) for entry in registry.vetoed],
        "renames_owed": [],
        "retire_requests": [],
    }
    try:
        data["renames_owed"] = skill_requests.pending_renames(home)
    except Exception as exc:  # noqa: BLE001 -- a note, never a refused run
        staged.notes.append(f"vetoes.yaml: the vetoed live skills could not be listed ({exc})")
    try:
        data["retire_requests"] = skill_requests.pending_retire_requests(home)
    except Exception as exc:  # noqa: BLE001
        staged.notes.append(
            f"vetoes.yaml: the user's retirement requests could not be read ({exc}); "
            "they reach a later run"
        )
    write(stage, stage / VETOES_FILE, _yaml_text(data))


def _stage_proposals(stage: Path, parked_rows: list[dict], write: Writer) -> None:
    proposals = [
        {
            "case": row.get("case"),
            "records": list(row.get("records") or []),
            "file": f"parked/{row.get('case')}.md",
        }
        for row in parked_rows
        if row.get("parked_reason") == SKILL_PROPOSAL_REASON
    ]
    write(stage, stage / PROPOSALS_FILE, _yaml_text({"proposals": proposals}))


# ------------------------------------------------------- phase B's output


@dataclass(frozen=True)
class SkillStep:
    """One skill step a pair carries: ``write`` (build or rewrite, with the
    folder phase B wrote), ``retire``, or ``rename`` (S-NEXT-skills-chain,
    SK-C2: *renamed_from* is the name the skill has, *name* the new one).
    Kept in the run record, so a resumed run makes the same step."""

    action: str
    name: str
    updating: bool = False
    files: dict[str, str] = field(default_factory=dict)
    expect_sha: str | None = None
    deploy: bool = True
    renamed_from: str | None = None

    @property
    def label(self) -> str:
        if self.action == "retire":
            return _LABEL_RETIRE
        if self.action == "rename":
            return _LABEL_RENAME
        return _LABEL_CHANGE if self.updating else _LABEL_BUILD

    @property
    def sheetless_ok(self) -> bool:
        """A pair that only changes, renames or retires a skill may have an
        empty sheet (a skill whose lessons were all folded into its text has
        none to move; a rename moves its lessons itself); a new skill is
        built with the lessons it takes in."""
        return self.action in ("retire", "rename") or self.updating

    def to_json(self) -> dict[str, Any]:
        return {
            "action": self.action, "name": self.name, "updating": self.updating,
            "files": dict(self.files), "expect_sha": self.expect_sha, "deploy": self.deploy,
            **({"renamed_from": self.renamed_from} if self.renamed_from else {}),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "SkillStep":
        renamed_from = data.get("renamed_from")
        return cls(
            action=str(data["action"]), name=str(data["name"]),
            updating=bool(data.get("updating")), files=dict(data.get("files") or {}),
            expect_sha=data.get("expect_sha"), deploy=bool(data.get("deploy", True)),
            renamed_from=str(renamed_from) if renamed_from else None,
        )


def decision_lessons(case_data: dict) -> list[str]:
    """The lessons a staged case's ``decision.skill`` names."""
    decision = case_data.get("decision")
    skill = decision.get("skill") if isinstance(decision, dict) else None
    lessons = skill.get("lessons") if isinstance(skill, dict) else None
    return [str(rid) for rid in lessons] if isinstance(lessons, list) else []


def renamed_from(case_data: dict) -> str | None:
    """The skill a staged case renames (``decision.skill.renamed_from``),
    or ``None``."""
    decision = case_data.get("decision")
    skill = decision.get("skill") if isinstance(decision, dict) else None
    old = skill.get("renamed_from") if isinstance(skill, dict) else None
    return old if isinstance(old, str) and old else None


def claimed_name(case_data: dict) -> str | None:
    """The skill a staged case names in ``decision.skill``, or ``None``."""
    decision = case_data.get("decision")
    skill = decision.get("skill") if isinstance(decision, dict) else None
    name = skill.get("name") if isinstance(skill, dict) else None
    return name if isinstance(name, str) and name else None


def _refusal(name: str, kind: str | None, problems: tuple[str, ...] | list[str]) -> str:
    return short_hashes(
        f"the skill write for {name} would be refused"
        + (f" [{kind}]" if kind else "")
        + ": " + "; ".join(problems)
    )


def _refuse_a_retire_that_leaves_lessons(
    home: Path, name: str, sheet_ids: Collection[str],
) -> None:
    """Fix round 2 (gate r2 MINOR): a case with ``outcome: retire`` naming
    an owned skill in ``decision.skill`` retires the skill, which ``skill
    retire`` refuses while a lesson routes into it. A sheet that names
    none of some lesson routed there now cannot move it out, so the pair is
    dropped here, saying so, rather than reported as "would retire" (writing
    not in effect) or retired in name only after its lines apply. A case
    that retires lessons out of a skill it keeps does not name the skill."""
    try:
        routed = skill_writer.routed_lessons(home, name)
    except Exception as exc:  # noqa: BLE001 -- this pair, not the run
        raise SkillPairError(
            f"the lessons routed into {name} could not be read ({type(exc).__name__}), "
            "so its retirement cannot be checked"
        ) from exc
    left = [rid for rid in routed if rid not in sheet_ids]
    if left:
        raise SkillPairError(
            f"a case with outcome: retire that names {name} in decision.skill retires that "
            f"skill, but its sheet has no line for {', '.join(left)}, which "
            + ("routes" if len(left) == 1 else "route")
            + f" into it, so {name} cannot be retired; a case that retires lessons out of a "
            "skill it keeps does not name the skill in decision.skill"
        )


def step_for_case(
    home: Path | str, stage: Path, case_data: dict, *, staged: StagedSkills, deploy: bool,
    sheet_dests: Collection[str] = (), sheet_ids: Collection[str] = (),
) -> SkillStep | None:
    """The skill step a staged case carries, checked; ``None`` when it
    carries none. Raises :class:`SkillPairError` (the pair is dropped) when
    the step cannot be made: a new skill without its folder, a retirement of
    a skill self-learn does not own, a folder the template check, the name
    check, the secret scan or the compare-and-swap refuses.

    *sheet_dests* is the ``dest`` of every line of the pair's sheet. A case
    may name in ``decision.skill`` a skill self-learn does not own without
    building it: it declines a steward's skill proposal (the successor of a
    ``skill-proposal`` parked case carries the proposal's
    ``decision.skill``), or it routes lessons into a linked skill a person
    owns (D17). Such a case, with no ``skills/<name>/`` folder, carries no
    skill step and is an ordinary pair (fix round 1, gate r1 MAJOR: before,
    it was dropped whole, and a declined proposal's parked case stayed open
    week after week). Only a case whose sheet routes a lesson into
    ``new-skill:<name>`` is building that skill, so only then is the missing
    folder a refusal.

    *sheet_ids* is the lesson ``id`` of every line of the pair's sheet (fix
    round 2, gate r2 MINOR). A case with ``outcome: retire`` naming a skill
    self-learn does not own is an ordinary pair when its sheet has a line,
    and is refused when it has none; one naming an owned skill retires it,
    and is refused when its sheet has no line for some lesson routed into
    the skill (:func:`_refuse_a_retire_that_leaves_lessons`)."""
    name = claimed_name(case_data)
    if name is None:
        return None
    home = Path(home)
    folder = stage / STAGE_SKILLS_DIR / name
    try:
        registry = skill_registry.load(home)
    except SkillRegistryError as exc:
        raise SkillPairError(f"owned-skills.yaml could not be read ({exc})") from exc
    owned = registry.is_owned(name)
    outcome = case_data.get("outcome")
    old = renamed_from(case_data)
    if old is not None:
        return _rename_step(home, folder, registry, old, name, outcome, staged=staged, deploy=deploy)
    if outcome == "retire":
        if folder.exists():
            raise SkillPairError(
                f"a case that retires {name} writes no {STAGE_SKILLS_DIR}/{name}/ folder"
            )
        if not owned:
            if sheet_ids:
                # Fix round 2 (gate r2 MINOR): a case that retires lessons
                # and names a skill self-learn does not own (a declined
                # proposal's successor keeps the proposal's decision.skill)
                # is an ordinary pair, as for any other outcome. With no
                # line, it can only mean retiring the skill: refused.
                return None
            raise SkillPairError(f"{name} is not a skill self-learn owns, so it cannot be retired")
        _refuse_a_retire_that_leaves_lessons(home, name, sheet_ids)
        return SkillStep(action="retire", name=name, updating=True, deploy=deploy)
    if not folder.is_dir():
        if owned:
            return None  # lessons routed into an owned skill: ordinary routing
        if f"new-skill:{name}" in sheet_dests:
            raise SkillPairError(
                f"decision.skill names {name}, which is not a skill self-learn owns, and its "
                f"sheet routes lessons into new-skill:{name}, but no {STAGE_SKILLS_DIR}/{name}/ "
                "folder was written to build it from"
            )
        # A skill this case names but does not build (a declined proposal,
        # a route into a linked skill): no skill step, ordinary routing.
        return None
    if not owned and outcome != "route":
        raise SkillPairError(
            f"a new skill ({name}) is built by a case with outcome: route whose sheet moves "
            f"lessons into it, not outcome: {outcome}"
        )
    if owned and name in staged.withheld:
        raise SkillPairError(
            f"{name} cannot be rewritten this run: part of its text matched the secret scan, so "
            "it was not shown to you in full; a person must remove that text first"
        )
    if owned and name in staged.missing:
        raise SkillPairError(
            f"{name} cannot be rewritten this run: its files could not be read from the skills root"
        )
    try:
        files = skill_writer.read_draft_dir(folder)
    except (ValueError, OSError) as exc:
        raise SkillPairError(f"{STAGE_SKILLS_DIR}/{name}/ cannot be read as a skill: {exc}") from exc
    expect = staged.expect.get(name) if owned else None
    try:
        # A file that is not UTF-8 comes back as bytes; the template check names it.
        checked = skill_writer.check(
            home, name, cast(Mapping[str, str], files), expect_sha=expect, updating=owned,
        )
    except Exception as exc:  # noqa: BLE001 -- a git or hosts read failed: this pair, not the run
        raise SkillPairError(
            f"the skill write for {name} could not be checked ({type(exc).__name__}: {exc})"
        ) from exc
    if not checked.ok:
        raise SkillPairError(_refusal(name, checked.kind, checked.problems))
    text_files = {key: value for key, value in files.items() if isinstance(value, str)}
    return SkillStep(
        action="write", name=name, updating=owned, files=text_files, expect_sha=expect,
        deploy=deploy,
    )


def _rename_step(
    home: Path, folder: Path, registry: skill_registry.Registry, old: str, new: str,
    outcome: object, *, staged: StagedSkills, deploy: bool,
) -> SkillStep:
    """S-NEXT-skills-chain (SK-C2): a case whose ``decision.skill`` names
    ``renamed_from`` renames that skill self-learn owns to ``name``. The
    rename is checked by the writer's own rules (``skill_writer.rename_check``:
    the new name as a write would check it, a vetoed name included, and the
    bucket rule) before any pair reaches the ledger."""
    if outcome == "retire":
        raise SkillPairError(
            f"a case that renames {old} to {new} does not retire it (outcome: retire)"
        )
    if folder.exists():
        raise SkillPairError(
            f"a case that renames {old} to {new} writes no {STAGE_SKILLS_DIR}/{new}/ folder; "
            "change the skill's text in a later run, under its new name"
        )
    if not registry.is_owned(old):
        raise SkillPairError(f"{old} is not a live skill self-learn owns, so it cannot be renamed")
    if old in staged.missing:
        raise SkillPairError(
            f"{old} cannot be renamed this run: its files could not be read from the skills root"
        )
    expect = staged.expect.get(old)
    try:
        checked = skill_writer.rename_check(home, old, new, expect_sha=expect)
    except Exception as exc:  # noqa: BLE001 -- a git or hosts read failed: this pair, not the run
        raise SkillPairError(
            f"the rename of {old} to {new} could not be checked ({type(exc).__name__}: {exc})"
        ) from exc
    if not checked.ok:
        raise SkillPairError(short_hashes(
            f"the rename of {old} to {new} would be refused"
            + (f" [{checked.kind}]" if checked.kind else "")
            + ": " + "; ".join(checked.problems)
        ))
    return SkillStep(
        action="rename", name=new, updating=True, expect_sha=expect, deploy=deploy,
        renamed_from=old,
    )


def unclaimed_folders(
    stage: Path, claimed: set[str], named_by_dropped: Collection[str] = (),
) -> list[str]:
    """One line per entry under ``skills/`` that no kept staged case named
    in ``decision.skill``: it is not written. *named_by_dropped* are the
    names a case dropped before its skill step was looked at names (fix
    round 1, gate r1 NIT: such a folder was said to be named by no case)."""
    root = stage / STAGE_SKILLS_DIR
    if not root.is_dir():
        return []
    lines = []
    for entry in sorted(root.iterdir()):
        if entry.name in claimed:
            continue
        if entry.name in named_by_dropped:
            lines.append(
                f"{STAGE_SKILLS_DIR}/{entry.name}{'/' if entry.is_dir() else ''}: not written — "
                "the case that names it in decision.skill was dropped (its own line says why)"
            )
            continue
        lines.append(
            f"{STAGE_SKILLS_DIR}/{entry.name}{'/' if entry.is_dir() else ''}: not written — no "
            "case names it in decision.skill (a skill is written with the case/sheet pair that "
            "builds or changes it)"
        )
    return lines


#: The words of SK2's refusal of an agent's route into a skill self-learn
#: does not own (`verbs.owned_skill_refusal`: "new-skill:<name> is not a
#: skill self-learn owns ..."). In a build pair's preview, a line into the
#: skill being built meets that refusal only because the skill is written
#: later in the same pair. The build tests in
#: `tests/test_overseer_skill_build.py` fail if these words drift.
_NOT_OWNED_YET = "is not a skill self-learn owns"


def _is_placed(home: Path, record_id: str) -> bool:
    """Whether the lesson is routed now; ``False`` when it cannot be read
    (``route --dry-run`` then names why)."""
    from ..ledger_ops import find_record_path
    from ..records import Record

    try:
        return Record.from_path(find_record_path(home, record_id)).status == "routed"
    except Exception:  # noqa: BLE001 -- unreadable: left to route --dry-run's own refusal
        return False


def _preview_once_written(
    home: Path, item: Any, line: Any, name: str, reconsidered: Collection[str] = (),
) -> Any:
    """A ``would-refuse`` preview item whose only refusal said the skill
    being built is not owned yet, judged as it will be once the skill is
    written. A ``route`` line of a pending or deferred lesson is previewed
    again by ``route --dry-run``'s own checks (the lesson's status, its
    scope, the destination), which the batch runs after the ownership check
    and so never reached; its refusal there is believed.

    A ``route`` line of a placed (routed) lesson that the pair's own ``kind:
    reconsider`` case covers (*reconsidered*, ``steward._reconsidered_by``)
    is that lesson's reroute at apply time (``batch._dispatch_reroute``,
    S-72), not a route: ``route --dry-run``'s status check refuses every
    routed lesson, so it is not asked (fix round 2, gate r2 MAJOR: before,
    every reroute into the skill being built was believed refused, and a
    skill made of placed lessons could never be built). The reroute's own
    checks need the skill to exist, so the line goes on to apply, where
    they run for real, as does any other verb."""
    from dataclasses import replace

    from .. import batch, verbs

    once = f"previewed before {name} is written; checked when it applies"
    if item.verb != "route":
        return replace(item, state="would-apply", kind=None, detail=once)
    if item.id in reconsidered and _is_placed(home, item.id):
        return replace(
            item, state="would-apply", kind=None,
            detail=f"reconsider: reroute; {once}",
        )
    try:
        dr = verbs.route_dry_run(
            home, item.id, dest=line.fields.get("dest"),
            note=line.fields.get("note"),
            hook_input=line.fields.get("hook"),
            rules_paths=line.fields.get("rules_paths"),
            allow_empty_glob=bool(line.fields.get("allow_empty_glob", False)),
        )
    except Exception as exc:  # noqa: BLE001 -- believed as a refusal, never the run's
        return replace(item, detail=f"{item.id}: {type(exc).__name__}: {exc}")
    if dr.would_refuse:
        return replace(
            item, detail="; ".join(dr.would_refuse),
            kind=batch._preview_kind(dr.refusal_errors),  # noqa: SLF001 -- the batch's own classification
        )
    return replace(item, state="would-apply", kind=None, detail=once)


def preview_for_step(
    home: Path | str, preview: Any, sheet: Any, step: SkillStep | None,
    *, reconsidered: Collection[str] = (),
) -> Any:
    """The preview a build pair's sheet is judged by.

    A line that routes a lesson into the skill this pair builds (``dest:
    new-skill:<name>``) is previewed before the skill exists, so the
    refusal "not a skill self-learn owns" says nothing about the line after
    the write: that one refusal is set aside and the line is judged as it
    will be once the skill is written (:func:`_preview_once_written`). Any
    other refusal is believed, as S-101 believes every preview refusal (fix
    round 1, gate r1: before, every refused line into the skill became
    would-apply, whatever the reason). *reconsidered* is the record ids the
    pair's ``kind: reconsider`` case covers: a placed one among them moves
    in by reroute (fix round 2).

    Raises :class:`SkillPairError` when no line would move a lesson into the
    new skill: the skill would be written first and then stand live and
    owned with no lesson in it."""
    if step is None or step.action != "write" or step.updating:
        return preview
    from dataclasses import replace

    home = Path(home)
    target = f"new-skill:{step.name}"
    lines = {line.n: line for line in sheet}
    items = []
    for item in preview.items:
        line = lines.get(item.n)
        if (
            item.state == "would-refuse" and line is not None
            and line.fields.get("dest") == target
            and f"{target} {_NOT_OWNED_YET}" in (item.detail or "")
        ):
            item = _preview_once_written(home, item, line, step.name, reconsidered)
        items.append(item)
    from .. import batch

    # A refusal of a retried kind (git or lock trouble) may clear by apply
    # time, as `run._preview_refusals` lets it.
    if not any(
        (item.state != "would-refuse" or item.kind in batch.RETRIED_REFUSAL_KINDS)
        and (lines.get(item.n) is not None and lines[item.n].fields.get("dest") == target)
        for item in items
    ):
        raise SkillPairError(
            f"no line of the sheet would move a lesson into {target}, so {step.name} is not "
            "built: a new skill is built with the lessons it takes in"
        )
    return replace(preview, items=items)


def draft_entry(step: SkillStep, case_name: str, lessons: list[str]) -> dict[str, Any]:
    """A skill step kept, not made (writing not in effect), for the run
    record and the report. A build or a change carries its files, which
    the runner commits as a draft; a rename names the skill it renames."""
    return {
        "name": step.name,
        "action": step.label,
        "case_name": case_name,
        "lessons": sorted(dict.fromkeys(lessons)),
        **({"files": dict(step.files)} if step.action == "write" else {}),
        **({"renamed_from": step.renamed_from} if step.renamed_from else {}),
    }


def draft_files(home: Path | str, week: str, drafts: list[dict]) -> list[tuple[Path, str]]:
    """``(ledger path, text)`` for every file of every draft that carries
    files: ``overseer/skills/<week>/drafts/<name>/<file>``."""
    out: list[tuple[Path, str]] = []
    for draft in drafts:
        files = draft.get("files")
        if not isinstance(files, dict):
            continue
        folder = drafts_dir(home, week, str(draft["name"]))
        for rel, text in sorted(files.items()):
            out.append((folder / rel, str(text)))
    return out


def stale_draft_files(home: Path | str, week: str, drafts: list[dict]) -> list[Path]:
    """Files left in a draft's folder by an earlier run of the same week
    that this run's draft of that skill no longer has."""
    stale: list[Path] = []
    for draft in drafts:
        files = draft.get("files")
        if not isinstance(files, dict):
            continue
        folder = drafts_dir(home, week, str(draft["name"]))
        if not folder.is_dir():
            continue
        keep = {folder / rel for rel in files}
        stale += sorted(p for p in folder.rglob("*") if p.is_file() and p not in keep)
    return stale


# ---------------------------------------------------------------- applying


@dataclass(frozen=True)
class StepOutcome:
    """What one skill step did. ``state`` is ``applied`` or ``refused``;
    ``line`` is its report line ("Decided in the user's stead" when
    applied, "Refused / could not do" when refused); ``warning`` is a
    "Refused / could not do" line for an applied step that left something
    for a person (a link it could not make)."""

    state: str
    line: str
    warning: str | None = None
    #: The writer's refusal kind on a refused step (fix round 2, gate r2
    #: NIT): a ``git`` refusal is tried again by the run's resume.
    kind: str | None = None


def _already_written(home: Path, case_id: str, step: SkillStep) -> bool:
    """A resumed run: this case's write already landed (its registry row
    names the case and the deployed files are what that write left)."""
    try:
        row = skill_registry.load(home).row(step.name)
    except SkillRegistryError:
        return False
    if row is None or row.get("status") != STATUS_LIVE:
        return False
    last = row.get("last_write") or {}
    if last.get("case") != case_id:
        return False
    return skill_writer.deployed_authored_sha256(home, step.name) == last.get("authored_sha256")


def _done_line(step: SkillStep, case_id: str) -> str:
    what = {
        _LABEL_BUILD: "written to the skills root and linked",
        _LABEL_CHANGE: "its text rewritten",
        _LABEL_RETIRE: "removed from the skills root, with its link",
        _LABEL_RENAME: (
            f"renamed from {step.renamed_from}; its folder, marketplace entry, link, lessons "
            "and ledger bucket moved with it"
        ),
    }[step.label]
    return f"{_DONE_TAGS[step.label]} {step.name}: {what} ({case_id})"


def apply_write(home: Path | str, case_id: str, step: SkillStep, *, case_name: str) -> StepOutcome:
    """Write the skill before its pair is recorded (``by: overseer``,
    ``no_push``: the run's own push publishes both repositories)."""
    home = Path(home)
    if _already_written(home, case_id, step):
        return StepOutcome("applied", _done_line(step, case_id))
    result = skill_writer.write(
        home, step.name, step.files, case=case_id, by="overseer",
        expect_sha=step.expect_sha, updating=step.updating, no_push=True,
    )
    if result.ok:
        return StepOutcome("applied", _done_line(step, case_id))
    if result.authored_sha256 is not None and (result.ledger_sha or result.host_sha):
        # The files and the row landed; only the link could not be made.
        return StepOutcome(
            "applied", _done_line(step, case_id),
            warning=short_hashes(f"{step.name}: " + "; ".join(result.problems)),
        )
    if result.kind == skill_writer.KIND_GIT:
        # Fix round 2 (gate r2 NIT): git trouble says nothing about the
        # skill and often clears, as for a sheet line of that kind (Q19).
        tail = "; the pair waits, and the run's resume writes the skill again"
    else:
        tail = "; the pair was dropped, so no lesson moved"
    return StepOutcome(
        "refused",
        f"{STAGE_SKILLS_DIR}/{step.name}/ ({case_name}): "
        + _refusal(step.name, result.kind, result.problems).replace("would be", "was")
        + tail,
        kind=result.kind,
    )


def apply_rename(home: Path | str, case_id: str, step: SkillStep, *, case_name: str) -> StepOutcome:
    """Rename the skill before its pair is recorded (``by: overseer``,
    ``no_push``). Idempotent: a resumed run finishes an interrupted rename,
    and a finished one changes nothing."""
    assert step.renamed_from is not None
    result = skill_writer.rename(
        Path(home), step.renamed_from, step.name, case=case_id, by="overseer",
        expect_sha=step.expect_sha, no_push=True,
    )
    if result.ok:
        warning = (
            short_hashes(f"{step.name}: " + "; ".join(result.warnings)) if result.warnings else None
        )
        return StepOutcome("applied", _done_line(step, case_id), warning=warning)
    if result.kind == skill_writer.KIND_GIT:
        tail = "; the pair waits, and the run's resume renames the skill again"
    else:
        tail = "; the pair was dropped"
    return StepOutcome(
        "refused",
        short_hashes(
            f"{step.renamed_from} → {step.name} ({case_name}): the rename was refused"
            + (f" [{result.kind}]" if result.kind else "")
            + ": " + "; ".join(result.problems)
        ) + tail,
        kind=result.kind,
    )


def apply_retire(home: Path | str, case_id: str, step: SkillStep, *, case_name: str) -> StepOutcome:
    """Retire the skill after its pair's sheet moved every lesson out."""
    result = skill_writer.retire(
        Path(home), step.name, case=case_id, by="overseer", no_push=True,
    )
    if result.ok:
        return StepOutcome("applied", _done_line(step, case_id))
    return StepOutcome(
        "refused",
        f"{step.name} ({case_name}): not retired"
        + (f" [{result.kind}]" if result.kind else "")
        + ": " + short_hashes("; ".join(result.problems)),
    )


# ----------------------------------------------------------------- report


def report_lines(manifest: dict[str, Any]) -> list[str]:
    """The run's skill lines for "Decided in the user's stead": every skill
    built, changed or retired (from the run record's steps, so a resumed
    run reports what an earlier attempt did), every draft with its "would
    ..." line, and, when writing was off, one line saying so. A run record
    written before S-NEXT-ft-skills-on may carry ``trial_ready`` and
    ``trial_why``; they are ignored."""
    info = manifest.get("skills")
    if not isinstance(info, dict):
        return []
    lines: list[str] = []
    recipes = manifest.get("cases") or {}
    for case_id in manifest.get("case_order") or []:
        raw = (recipes.get(case_id) or {}).get("skill")
        if not isinstance(raw, dict) or raw.get("state") != "applied":
            continue
        lines.append(_done_line(SkillStep.from_json(raw), case_id))
    drafts = [d for d in info.get("drafts") or [] if isinstance(d, dict)]
    week = info.get("week") or manifest.get("week")
    for draft in drafts:
        name = draft.get("name")
        label = draft.get("action")
        where = (
            f"; kept as a draft at {LEDGER_DIR}/{week}/drafts/{name}/"
            if isinstance(draft.get("files"), dict) else ""
        )
        lessons = draft.get("lessons") or []
        moving = (
            f"; it would move {', '.join(lessons)}"
            if lessons and label not in (_LABEL_RETIRE, _LABEL_RENAME) else ""
        )
        old = draft.get("renamed_from")
        what = f"would rename {old} to it" if label == _LABEL_RENAME and old else (
            f"{_WOULD.get(str(label), 'would change')} it"
        )
        lines.append(
            f"[skill drafted] {name}: {what} ({draft.get('case_name')}){where}{moving}"
        )
    state = info.get("state") or {}
    if not state.get("deploy", True):
        lines.append(
            "skill writing is off (overseer.skill_writing): every skill phase B built or "
            "changed was kept as a checked draft; nothing was deployed or retired"
        )
    return lines
