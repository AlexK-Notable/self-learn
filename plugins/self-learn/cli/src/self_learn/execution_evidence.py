"""Trusted execution references for recoverable delegated batch runs.

This module deliberately imports neither :mod:`batch` nor :mod:`steward`.
It owns only the small, shared identity carried by ledger mutation commits
and the compound-intent proof that must be written in the same commit as a
collapse.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import gitops, intents
from .primitives import fsops


class ExecutionEvidenceError(ValueError):
    """A trusted execution reference or its committed manifest is invalid."""


_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CASE_ID_RE = re.compile(r"^case-[0-9a-f]{8}$")
_RECORD_ID_RE = re.compile(r"^lrn-[0-9a-f]{8}$")
_SHORT_SHA_RE = re.compile(r"^[0-9a-f]{8}$")
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_VERB_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_ACTORS = frozenset({"human", "steward", "overseer"})


@dataclass(frozen=True)
class TrailerIdentity:
    actor: str
    case_id: str
    sheet_sha: str
    item: int


@dataclass(frozen=True)
class ExecutionRef:
    """One original sheet item's immutable, runner-owned identity."""

    run_id: str
    case_id: str
    sheet_sha: str
    sheet_digest: str
    item: int
    record_id: str
    verb: str
    actor: str

    def __post_init__(self) -> None:
        checks = (
            (_RUN_ID_RE.fullmatch(self.run_id), "run id"),
            (_CASE_ID_RE.fullmatch(self.case_id), "case id"),
            (_SHORT_SHA_RE.fullmatch(self.sheet_sha), "short sheet sha"),
            (_FULL_SHA_RE.fullmatch(self.sheet_digest), "full sheet digest"),
            (isinstance(self.item, int) and self.item > 0, "item ordinal"),
            (_RECORD_ID_RE.fullmatch(self.record_id), "record id"),
            (_VERB_RE.fullmatch(self.verb), "verb"),
            (self.actor in _ACTORS, "actor"),
        )
        failed = [name for ok, name in checks if not ok]
        if failed:
            raise ExecutionEvidenceError(
                "invalid execution reference field(s): " + ", ".join(failed)
            )

    def trailer_identity(self) -> TrailerIdentity:
        return TrailerIdentity(self.actor, self.case_id, self.sheet_sha, self.item)

    def to_proof(self) -> dict[str, Any]:
        return {
            "case": self.case_id,
            "sheet_sha": self.sheet_sha,
            "sheet_digest": self.sheet_digest,
            "item": self.item,
            "record": self.record_id,
            "verb": self.verb,
        }


def manifest_path(home: Path | str, run_id: str) -> Path:
    """Return the sole permitted manifest path for *run_id*.

    The runner supplies only an identifier, never an arbitrary destination.
    """
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        raise ExecutionEvidenceError(f"invalid run id for manifest path: {run_id!r}")
    home = Path(home).resolve()
    root = (home / "cases" / "runs").resolve()
    path = (root / f"{run_id}.json").resolve()
    if path.parent != root:
        raise ExecutionEvidenceError("run manifest must live directly under cases/runs")
    return path


def render_trailers(ref: ExecutionRef) -> str:
    """Render the exact final trailer block for a mutation commit."""
    return (
        f"By: {ref.actor}\n"
        f"Case: {ref.case_id}\n"
        f"Sheet: {ref.sheet_sha}\n"
        f"Item: {ref.item}"
    )


def append_trailers(body: str | None, ref: ExecutionRef) -> str:
    """Append the canonical execution block as its own final paragraph."""
    trailers = render_trailers(ref)
    if body is None or not body.strip():
        return trailers
    return f"{body.rstrip()}\n\n{trailers}"


_FINAL_TRAILERS_RE = re.compile(
    r"(?:^|\n\n)By: (?P<actor>[^\n]+)\n"
    r"Case: (?P<case>[^\n]+)\n"
    r"Sheet: (?P<sheet>[0-9a-f]{8})\n"
    r"Item: (?P<item>[1-9][0-9]*)\Z"
)


def parse_trailers(body: str) -> TrailerIdentity | None:
    """Parse only a single canonical trailer block at the end of *body*."""
    match = _FINAL_TRAILERS_RE.search(body.rstrip("\n"))
    if match is None:
        return None
    try:
        identity = TrailerIdentity(
            actor=match.group("actor"),
            case_id=match.group("case"),
            sheet_sha=match.group("sheet"),
            item=int(match.group("item")),
        )
        # Reuse the strict validators, with harmless placeholders for fields
        # that are deliberately absent from a commit trailer.
        ExecutionRef(
            run_id="parse",
            case_id=identity.case_id,
            sheet_sha=identity.sheet_sha,
            sheet_digest="0" * 64,
            item=identity.item,
            record_id="lrn-00000000",
            verb="parse",
            actor=identity.actor,
        )
    except ExecutionEvidenceError:
        return None
    return identity


def _prepared_item(manifest: dict[str, Any], ref: ExecutionRef) -> dict[str, Any]:
    if manifest.get("version") != 1 or manifest.get("run_id") != ref.run_id:
        raise ExecutionEvidenceError("run manifest identity does not match execution reference")
    cases = manifest.get("cases")
    recipe = cases.get(ref.case_id) if isinstance(cases, dict) else None
    if not isinstance(recipe, dict):
        raise ExecutionEvidenceError(f"manifest has no prepared case {ref.case_id}")
    if recipe.get("sheet_sha") != ref.sheet_sha:
        raise ExecutionEvidenceError("manifest short sheet sha does not match execution reference")
    if recipe.get("sheet_digest") != ref.sheet_digest:
        raise ExecutionEvidenceError("manifest full sheet digest does not match execution reference")
    items = recipe.get("items")
    if not isinstance(items, list):
        raise ExecutionEvidenceError("manifest prepared case has no item list")
    matches = [
        item for item in items
        if isinstance(item, dict) and item.get("n") == ref.item
    ]
    if len(matches) != 1:
        raise ExecutionEvidenceError(
            f"manifest must contain exactly one original item {ref.item}"
        )
    expected = {"n": ref.item, "id": ref.record_id, "verb": ref.verb}
    if any(matches[0].get(key) != value for key, value in expected.items()):
        raise ExecutionEvidenceError("manifest item does not match execution reference")
    return matches[0]


def validate_manifest_ref(manifest: dict[str, Any], ref: ExecutionRef) -> None:
    """Require *manifest* to contain the exact prepared item for *ref*."""
    _prepared_item(manifest, ref)


def read_manifest(
    home: Path | str,
    run_id: str,
    *,
    at: str = "HEAD",
) -> dict[str, Any]:
    """Read a run manifest from a pinned committed Git object."""
    home = Path(home)
    path = manifest_path(home, run_id)
    relpath = path.relative_to(home.resolve())
    proc = gitops._git(home, "show", f"{at}:{relpath}")  # noqa: SLF001
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ExecutionEvidenceError(
            f"committed run manifest {run_id!r} is invalid JSON at {at}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ExecutionEvidenceError("committed run manifest must be a JSON object")
    return data


def find_mutation_commit(
    home: Path | str,
    ref: ExecutionRef,
    *,
    after: str | None = None,
    at: str = "HEAD",
) -> str | None:
    """Find the sole reachable commit with *ref*'s subject and trailers.

    The subject must be one the referenced verb can write for the referenced
    record, and the final trailer identity must match exactly. Content/effect
    validation against the original item remains the caller's verb-specific
    job. More than one exact match is ambiguity and therefore a refusal, never
    a guess.
    """
    home = Path(home)
    revision = f"{after}..{at}" if after is not None else at
    proc = gitops._git(  # noqa: SLF001
        home, "log", "--format=%H%x1f%s%x1f%B%x1e", revision
    )
    want = ref.trailer_identity()
    matches: list[str] = []
    for entry in proc.stdout.split("\x1e"):
        entry = entry.strip("\n")
        if not entry or "\x1f" not in entry:
            continue
        sha, subject, body = entry.split("\x1f", 2)
        if parse_trailers(body) == want and _subject_matches(ref, subject):
            matches.append(sha.strip())
    if len(matches) > 1:
        raise ExecutionEvidenceError(
            "more than one mutation commit matches the execution reference"
        )
    return matches[0] if matches else None


def _subject_matches(ref: ExecutionRef, subject: str) -> bool:
    """Whether *subject* is one the referenced verb can actually write."""
    rid = ref.record_id
    exact = {
        "followup-done": f"self-learn: follow-up done on {rid}",
        "confirm-recurrence": f"self-learn: recurrence confirmed on {rid}",
        "confirm-held": f"self-learn: confirmed holding {rid}",
        "dismiss-suspect": f"self-learn: suspect dismissed on {rid}",
    }
    if ref.verb in exact:
        return subject == exact[ref.verb]
    if ref.verb == "link-contradicts":
        return subject.startswith(f"self-learn: link {rid} contradicts ")
    prefixes = [f"self-learn: {ref.verb} {rid}"]
    # The compatibility alias delegates to retire when `covered_by` is
    # supplied, and therefore deliberately uses retire's subject.
    if ref.verb == "graduate":
        prefixes.append(f"self-learn: retire {rid}")
    return any(subject == prefix or subject.startswith(prefix + " ") for prefix in prefixes)


def _proof_state(manifest: dict[str, Any], ref: ExecutionRef) -> str:
    """Classify *ref*'s compound proof without accepting near matches."""
    validate_manifest_ref(manifest, ref)
    effects = manifest.get("ledger_effects")
    if not isinstance(effects, list):
        raise ExecutionEvidenceError("run manifest ledger_effects must be a list")
    keyed = [
        item
        for item in effects
        if isinstance(item, dict)
        and item.get("case") == ref.case_id
        and item.get("sheet_digest") == ref.sheet_digest
        and item.get("item") == ref.item
    ]
    if not keyed:
        return "absent"
    if keyed != [ref.to_proof()]:
        raise ExecutionEvidenceError("conflicting ledger effect proof")
    return "exact"


def find_compound_proof_commit(
    home: Path | str,
    ref: ExecutionRef,
    *,
    after: str,
    at: str = "HEAD",
) -> str | None:
    """Find the commit that first introduced *ref*'s compound proof.

    This is the tagless roll-forward seam: an intent recovery commit may
    carry only its pinned subject, so the proof's first appearance in the
    committed manifest identifies the candidate mutation commit. The caller
    still verifies its verb-specific ledger effects.
    """
    home = Path(home)
    if _proof_state(read_manifest(home, ref.run_id, at=after), ref) != "absent":
        raise ExecutionEvidenceError(
            "compound proof already exists at the prepared boundary"
        )
    relpath = manifest_path(home, ref.run_id).relative_to(home.resolve())
    commits = gitops._git(  # noqa: SLF001 — committed manifest history query
        home,
        "rev-list",
        "--reverse",
        f"{after}..{at}",
        "--",
        str(relpath),
    ).stdout.splitlines()
    introduced: str | None = None
    for sha in commits:
        state = _proof_state(read_manifest(home, ref.run_id, at=sha), ref)
        if state == "exact" and introduced is None:
            introduced = sha
        elif state == "absent" and introduced is not None:
            raise ExecutionEvidenceError(
                "compound proof was removed by an intervening manifest change"
            )
    return introduced


def write_compound_proof(intent: intents.Intent, ref: ExecutionRef) -> Path:
    """Attach *ref*'s ledger-effect proof to an existing compound intent.

    The path is registered before mutation and returned so the caller can
    include it in the compound mutation commit. This function never commits.
    """
    path = manifest_path(intent.home, ref.run_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionEvidenceError(f"cannot read committed run manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ExecutionEvidenceError("run manifest must be a JSON object")
    _prepared_item(data, ref)
    proof = ref.to_proof()
    effects = data.get("ledger_effects")
    if not isinstance(effects, list):
        raise ExecutionEvidenceError("run manifest ledger_effects must be a list")
    same_key = [
        item for item in effects
        if isinstance(item, dict)
        and item.get("case") == ref.case_id
        and item.get("sheet_digest") == ref.sheet_digest
        and item.get("item") == ref.item
    ]
    if same_key:
        if same_key != [proof]:
            raise ExecutionEvidenceError("conflicting ledger effect proof")
        raise ExecutionEvidenceError(
            "ledger effect proof already exists; refuse duplicate compound mutation"
        )
    intents.add_step(intent, path)
    data["ledger_effects"] = [*effects, proof]
    fsops.atomic_write(
        path,
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        fsync=True,
    )
    return path
