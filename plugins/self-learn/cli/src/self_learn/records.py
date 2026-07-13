"""Learning-record schema: parse / write / validate / mutate (02 §1–§2).

A record is one file: YAML frontmatter (machine fields) + markdown body
(the lesson). Round-trip fidelity is a hard requirement — the 02 §1 example
contains YAML comments and must parse and re-emit byte-identically — so the
frontmatter is handled by ruamel.yaml in round-trip mode (PyYAML drops
comments and cannot meet that bar; recorded structural decision).

Mutation rules (02 §2) are enforced in code paths, not by convention:

- While ``status`` is ``pending`` (or ``deferred`` — still a draft awaiting
  triage), the body and the substance fields edit freely.
- Once the record leaves the draft states (``routed`` / ``rejected`` /
  ``superseded``), the substance — body, ``type``, ``source``,
  ``created_at`` — is FROZEN; setters raise :class:`MutationError`.
- ``evidence`` is APPEND-ONLY always: :meth:`Record.append_evidence` works
  in every status (merge collapses add provenance post-routing); rewriting
  or removing entries raises. The ``evidence`` property returns copies.
- Lifecycle fields stay mutable in every status: ``status``, ``routing``,
  ``sightings``, ``scope``/``kind`` (the filing is never frozen),
  ``deferred_until``/``deferred_count``, ``superseded_by`` (corrective
  supersession targets already-routed records by design).
- ``resolution_note`` is write-ONCE: a second write raises.
- ``superseded_by`` accepts only ``None``, a ``lrn-xxxxxxxx`` id, or the
  literal ``"canon"`` (graduation).

One lesson per record: a duplicated required section heading (two Triggers,
two Facts) is a validation error — a two-lesson capture becomes two records.
"""

from __future__ import annotations

import copy
import io
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

__all__ = [
    "MutationError",
    "Record",
    "RecordError",
    "ValidationError",
    "generate_id",
    "parse_record",
]

RECORD_ID_RE = re.compile(r"^lrn-[0-9a-f]{8}$")

TYPES = frozenset({"behavior", "knowledge"})
KINDS = frozenset({"anti-pattern", "surface-rule", "reasoning-pattern"})
SOURCES = frozenset({"teach", "auto-memory", "backlog", "session"})
STATUSES = frozenset({"pending", "routed", "rejected", "deferred", "superseded"})

#: Statuses in which the record is still a draft: substance edits allowed.
DRAFT_STATUSES = frozenset({"pending", "deferred"})

#: Required / optional body section headings by record type (02 §1).
REQUIRED_SECTIONS = {"behavior": ("Trigger", "Instruction"), "knowledge": ("Fact",)}
OPTIONAL_SECTIONS = {"behavior": (), "knowledge": ("Context",)}

_HEADING_RE = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
_DELIM = "---"


class RecordError(Exception):
    """Base class for record schema errors."""


class ValidationError(RecordError):
    """The record's frontmatter or body violates 02 §1."""


class MutationError(RecordError):
    """An edit violates 02 §2's mutation rules."""


def generate_id() -> str:
    """``lrn-`` + 8 random lowercase hex chars (collision-resistant across
    offline machines — 02 §2 pins random over sequential)."""
    return "lrn-" + secrets.token_hex(4)


def _make_yaml() -> YAML:
    """Round-trip YAML configured for byte-identical re-emission of the
    02 §1 example: preserve quotes/comments, 2-space sequence-item indent,
    explicit ``null`` for None, no line wrapping."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)

    def _represent_none(representer, _data):
        return representer.represent_scalar("tag:yaml.org,2002:null", "null")

    yaml.representer.add_representer(type(None), _represent_none)
    return yaml


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_record_id(value: object) -> bool:
    return isinstance(value, str) and bool(RECORD_ID_RE.match(value))


class Record:
    """One learning record. Construct via :func:`parse_record` /
    :meth:`from_path` (existing files) or :meth:`create` (new captures).

    All state lives in the private frontmatter map + body string; mutation
    goes through the explicit setters, which enforce 02 §2.
    """

    def __init__(self, frontmatter: CommentedMap, body: str) -> None:
        self._fm = frontmatter
        self._body = body

    # ---------------------------------------------------------------- parse

    @classmethod
    def from_text(cls, text: str) -> "Record":
        lines = text.split("\n")
        if not lines or lines[0] != _DELIM:
            raise ValidationError("record must start with a '---' frontmatter line")
        try:
            close = lines[1:].index(_DELIM) + 1
        except ValueError:
            raise ValidationError("unterminated frontmatter: no closing '---'") from None
        fm_text = "\n".join(lines[1:close]) + "\n"
        body = "\n".join(lines[close + 1 :])
        fm = _make_yaml().load(fm_text)
        if not isinstance(fm, CommentedMap):
            raise ValidationError("frontmatter is not a YAML mapping")
        record = cls(fm, body)
        record.validate()
        return record

    @classmethod
    def from_path(cls, path: Path | str) -> "Record":
        return cls.from_text(Path(path).read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- create

    @classmethod
    def create(
        cls,
        *,
        type: str,
        scope: str,
        source: str,
        kind: str | None = None,
        trigger: str | None = None,
        instruction: str | None = None,
        fact: str | None = None,
        context: str | None = None,
        evidence: list[dict] | None = None,
        record_id: str | None = None,
        created_at: str | None = None,
    ) -> "Record":
        """Build a new pending record from structured fields."""
        if type == "behavior":
            if not trigger or not instruction:
                raise ValidationError("behavior records need trigger and instruction")
            sections = [("Trigger", trigger), ("Instruction", instruction)]
        elif type == "knowledge":
            if not fact:
                raise ValidationError("knowledge records need a fact")
            sections = [("Fact", fact)]
            if context:
                sections.append(("Context", context))
        else:
            raise ValidationError(f"type must be one of {sorted(TYPES)}, got {type!r}")

        fm = CommentedMap()
        fm["id"] = record_id if record_id is not None else generate_id()
        fm["type"] = type
        fm["scope"] = scope
        if kind is not None:
            fm["kind"] = kind
        fm["source"] = source
        fm["status"] = "pending"
        fm["created_at"] = created_at if created_at is not None else _now_iso()
        fm["sightings"] = 1
        fm["evidence"] = [dict(e) for e in (evidence or [])]
        fm["routing"] = None
        fm["supersedes"] = None
        fm["superseded_by"] = None
        fm["resolution_note"] = None

        body = "\n" + "\n\n".join(f"## {name}\n{text.strip()}" for name, text in sections) + "\n"
        record = cls(fm, body)
        record.validate()
        return record

    # ----------------------------------------------------------------- emit

    def to_text(self) -> str:
        buf = io.StringIO()
        _make_yaml().dump(self._fm, buf)
        return f"{_DELIM}\n{buf.getvalue()}{_DELIM}\n{self._body}"

    def write(self, path: Path | str) -> None:
        Path(path).write_text(self.to_text(), encoding="utf-8")

    # ------------------------------------------------------------ read view

    @property
    def id(self) -> str:
        return self._fm.get("id")

    @property
    def type(self) -> str:
        return self._fm.get("type")

    @property
    def scope(self) -> str:
        return self._fm.get("scope")

    @property
    def kind(self) -> str | None:
        return self._fm.get("kind")

    @property
    def source(self) -> str:
        return self._fm.get("source")

    @property
    def status(self) -> str:
        return self._fm.get("status")

    @property
    def created_at(self):
        return self._fm.get("created_at")

    @property
    def sightings(self) -> int:
        return self._fm.get("sightings", 1)

    @property
    def evidence(self) -> tuple:
        """Read-only view: copies, so callers cannot poke entries in place."""
        return tuple(copy.deepcopy(dict(e)) for e in self._fm.get("evidence") or [])

    @property
    def routing(self):
        value = self._fm.get("routing")
        return copy.deepcopy(dict(value)) if value is not None else None

    @property
    def supersedes(self) -> str | None:
        return self._fm.get("supersedes")

    @property
    def superseded_by(self) -> str | None:
        return self._fm.get("superseded_by")

    @property
    def resolution_note(self) -> str | None:
        return self._fm.get("resolution_note")

    @property
    def deferred_until(self):
        return self._fm.get("deferred_until")

    @property
    def deferred_count(self) -> int | None:
        return self._fm.get("deferred_count")

    @property
    def body(self) -> str:
        return self._body

    @property
    def substance_frozen(self) -> bool:
        """True once the record has left the draft states (02 §2:
        substance freezes at routing/resolution)."""
        return self.status not in DRAFT_STATUSES

    # ------------------------------------------------- substance mutation

    def _check_thawed(self, what: str) -> None:
        if self.substance_frozen:
            raise MutationError(
                f"{what} is frozen: record {self.id} is {self.status!r} — "
                "correct a routed lesson with a new record and supersedes:, "
                "never by editing (02 §2)"
            )

    def set_body(self, body: str) -> None:
        self._check_thawed("body")
        self._validate_body(self.type, body)
        self._body = body

    def set_type(self, type: str) -> None:
        self._check_thawed("type")
        if type not in TYPES:
            raise ValidationError(f"type must be one of {sorted(TYPES)}, got {type!r}")
        if type != "behavior" and self._fm.get("kind") is not None:
            raise ValidationError(
                "clear kind first (set_kind(None)): kind applies to behavior records only"
            )
        self._validate_body(type, self._body)  # body sections must match the new type
        self._fm["type"] = type

    def set_source(self, source: str) -> None:
        self._check_thawed("source")
        if source not in SOURCES:
            raise ValidationError(f"source must be one of {sorted(SOURCES)}, got {source!r}")
        self._fm["source"] = source

    def set_created_at(self, created_at: str) -> None:
        self._check_thawed("created_at")
        self._fm["created_at"] = created_at

    # -------------------------------------------------- lifecycle mutation

    def set_status(self, status: str) -> None:
        if status not in STATUSES:
            raise ValidationError(f"status must be one of {sorted(STATUSES)}, got {status!r}")
        self._fm["status"] = status

    def set_routing(self, routing: dict | None) -> None:
        if routing is not None:
            missing = {"routed_at", "destination", "by"} - set(routing)
            if missing:
                raise ValidationError(f"routing block missing {sorted(missing)}")
            routing = dict(routing)
        self._fm["routing"] = routing

    def set_sightings(self, sightings: int) -> None:
        if not isinstance(sightings, int) or isinstance(sightings, bool) or sightings < 1:
            raise ValidationError(f"sightings must be a positive int, got {sightings!r}")
        self._fm["sightings"] = sightings

    def set_scope(self, scope: str) -> None:
        _validate_scope(scope)
        self._fm["scope"] = scope

    def set_kind(self, kind: str | None) -> None:
        if kind is None:
            self._fm.pop("kind", None)
            return
        if self.type != "behavior":
            raise ValidationError("kind applies to behavior records only (02 §1)")
        if kind not in KINDS:
            raise ValidationError(f"kind must be one of {sorted(KINDS)}, got {kind!r}")
        self._fm["kind"] = kind

    def set_deferred_until(self, value) -> None:
        self._fm["deferred_until"] = value

    def set_deferred_count(self, count: int) -> None:
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValidationError(f"deferred_count must be a non-negative int, got {count!r}")
        self._fm["deferred_count"] = count

    def set_supersedes(self, record_id: str | None) -> None:
        # Set at capture on the *replacement* record (teach --supersedes);
        # substance-adjacent, so it thaws/freezes with the draft states.
        self._check_thawed("supersedes")
        if record_id is not None and not _is_record_id(record_id):
            raise ValidationError(f"supersedes must be null or a record id, got {record_id!r}")
        self._fm["supersedes"] = record_id

    def set_superseded_by(self, value: str | None) -> None:
        """Domain: None | lrn-xxxxxxxx | the literal "canon" (graduation).
        Mutable in every status — corrective supersession marks records
        that are already routed (02 §2)."""
        if value is not None and value != "canon" and not _is_record_id(value):
            raise ValidationError(
                f"superseded_by must be null, a record id, or 'canon', got {value!r}"
            )
        self._fm["superseded_by"] = value

    def set_resolution_note(self, note: str) -> None:
        """Write-once: the human's *why*, part of the resolution event."""
        if self._fm.get("resolution_note") is not None:
            raise MutationError(
                f"resolution_note is write-once and already set on {self.id} (02 §2)"
            )
        if not isinstance(note, str) or not note.strip():
            raise ValidationError("resolution_note must be non-empty text")
        self._fm["resolution_note"] = note

    # ------------------------------------------------- evidence (append-only)

    def append_evidence(self, entry: dict) -> None:
        """Append one provenance entry. Allowed in EVERY status — merge
        collapses add the losers' provenance after routing (02 §2)."""
        if not isinstance(entry, dict) or not entry:
            raise ValidationError(f"evidence entry must be a non-empty mapping, got {entry!r}")
        if self._fm.get("evidence") is None:
            self._fm["evidence"] = []
        self._fm["evidence"].append(dict(entry))

    def set_evidence(self, _entries) -> None:
        raise MutationError("evidence is append-only: use append_evidence (02 §2)")

    def remove_evidence(self, _index) -> None:
        raise MutationError("evidence is append-only: entries are never removed (02 §2)")

    def rewrite_evidence(self, _index, _entry) -> None:
        raise MutationError("evidence is append-only: entries are never rewritten (02 §2)")

    # ------------------------------------------------------------- validate

    def validate(self) -> None:
        fm = self._fm
        if not _is_record_id(fm.get("id")):
            raise ValidationError(f"id must match lrn-<8 lowercase hex>, got {fm.get('id')!r}")
        if fm.get("type") not in TYPES:
            raise ValidationError(f"type must be one of {sorted(TYPES)}, got {fm.get('type')!r}")
        _validate_scope(fm.get("scope"))
        kind = fm.get("kind")
        if fm["type"] == "behavior":
            if kind not in KINDS:
                raise ValidationError(
                    f"behavior records need kind in {sorted(KINDS)}, got {kind!r}"
                )
        elif kind is not None:
            raise ValidationError("kind applies to behavior records only (02 §1)")
        if fm.get("source") not in SOURCES:
            raise ValidationError(
                f"source must be one of {sorted(SOURCES)}, got {fm.get('source')!r}"
            )
        if fm.get("status") not in STATUSES:
            raise ValidationError(
                f"status must be one of {sorted(STATUSES)}, got {fm.get('status')!r}"
            )
        if fm.get("created_at") is None:
            raise ValidationError("created_at is required")
        sightings = fm.get("sightings")
        if sightings is not None and (
            not isinstance(sightings, int) or isinstance(sightings, bool) or sightings < 1
        ):
            raise ValidationError(f"sightings must be a positive int, got {sightings!r}")
        evidence = fm.get("evidence")
        if evidence is not None:
            if not isinstance(evidence, list) or any(
                not isinstance(e, dict) or not e for e in evidence
            ):
                raise ValidationError("evidence must be a list of non-empty mappings")
        routing = fm.get("routing")
        if routing is not None:
            if not isinstance(routing, dict):
                raise ValidationError("routing must be null or a mapping")
            missing = {"routed_at", "destination", "by"} - set(routing)
            if missing:
                raise ValidationError(f"routing block missing {sorted(missing)}")
        supersedes = fm.get("supersedes")
        if supersedes is not None and not _is_record_id(supersedes):
            raise ValidationError(f"supersedes must be null or a record id, got {supersedes!r}")
        superseded_by = fm.get("superseded_by")
        if (
            superseded_by is not None
            and superseded_by != "canon"
            and not _is_record_id(superseded_by)
        ):
            raise ValidationError(
                f"superseded_by must be null, a record id, or 'canon', got {superseded_by!r}"
            )
        note = fm.get("resolution_note")
        if note is not None and not isinstance(note, str):
            raise ValidationError("resolution_note must be null or text")
        count = fm.get("deferred_count")
        if count is not None and (
            not isinstance(count, int) or isinstance(count, bool) or count < 0
        ):
            raise ValidationError(f"deferred_count must be a non-negative int, got {count!r}")
        self._validate_body(fm["type"], self._body)

    @staticmethod
    def _validate_body(type: str, body: str) -> None:
        headings = _HEADING_RE.findall(body)
        required = REQUIRED_SECTIONS[type]
        optional = OPTIONAL_SECTIONS[type]
        for name in required:
            n = headings.count(name)
            if n == 0:
                raise ValidationError(
                    f"{type} record body must contain a '## {name}' section (02 §1)"
                )
            if n > 1:
                raise ValidationError(
                    f"duplicate '## {name}' section: two-lesson capture — "
                    "split into two records (02 §1: one lesson per record)"
                )
        for name in optional:
            if headings.count(name) > 1:
                raise ValidationError(f"duplicate optional '## {name}' section")


def _validate_scope(scope: object) -> None:
    if scope in ("project", "user"):
        return
    if isinstance(scope, str) and scope.startswith("skill:") and len(scope) > len("skill:"):
        return
    raise ValidationError(f"scope must be skill:<name>, project, or user, got {scope!r}")


def parse_record(text: str) -> Record:
    """Parse a record from its file text (frontmatter + body), validating it."""
    return Record.from_text(text)
