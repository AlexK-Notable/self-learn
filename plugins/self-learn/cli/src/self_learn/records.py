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
    "GENERALITIES",
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

#: 11 §3: capture-time grounding classes. The strongest known predictor of
#: behavioral value (six dead fixture candidates were all general practice).
GENERALITIES = frozenset({"environment-specific", "general-practice", "uncertain"})

#: Scalar types allowed in env-hint values (versions, model names).
_ENV_SCALARS = (str, int, float)

#: Statuses in which the record is still a draft: substance edits allowed.
DRAFT_STATUSES = frozenset({"pending", "deferred"})

#: Required / optional body section headings by record type (02 §1).
REQUIRED_SECTIONS = {"behavior": ("Trigger", "Instruction"), "knowledge": ("Fact",)}
#: U-verbs §4.10: the closed set of things a `history` entry may
#: record as DISPLACED — `reopen` displaces a resolution; a future
#: verb correcting a wrong routing destination displaces a routing
#: block the same way. A future third displacement is a decision,
#: not a silent widening.
HISTORY_EVENTS = frozenset({"resolution", "routing"})
#: "Episode brief" (02 §1 amendment, 10 §3 U18): a miner-only, optional
#: body section for BOTH types — no ``required`` weight, duplicate-guarded
#: by ``_validate_body`` once registered here like any other optional
#: section. Producer-side convention (miner writes it only for
#: ``source: session``), not a validator or render gate (02 §1).
OPTIONAL_SECTIONS = {
    "behavior": ("Episode brief",),
    "knowledge": ("Context", "Episode brief"),
}

_HEADING_RE = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
_DELIM = "---"


class RecordError(Exception):
    """Base class for record schema errors."""


class ValidationError(RecordError):
    """The record's frontmatter or body violates 02 §1."""


class MutationError(RecordError):
    """An edit violates 02 §2's mutation rules."""


def validate_body(type: str, body: str) -> None:
    """Body-shape validator for ``type`` (02 §1: ``behavior`` needs
    ``Trigger``+``Instruction``, ``knowledge`` needs ``Fact``) -- the ONE
    validator. :meth:`Record.set_body`, :meth:`Record.set_type`, and
    :meth:`Record.validate` all reach it through Record's own private
    body-shape staticmethod, which delegates here; this
    module-level function is the public surface for any caller outside
    this module that needs to check a body's shape against a type without
    constructing or mutating a :class:`Record` (gate r2 m-4: before this,
    the one caller with that need reached Record's own private
    body-shape staticmethod directly -- the only cross-module access to a
    private member in either src tree). Counts headings; never inspects content
    (a present-but-empty required section is NOT a violation -- gate r2
    B-1/M-3: that is a body-quality question, orthogonal to this shape
    check, and measured to have zero live instances -- see
    ``misc/u-verbs-p2-r2-build/scan_empty_sections.py``)."""
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
        # gate r2 B-1 (advisor re-check): the universal choke point --
        # MEASURED, not assumed, to be safe for every existing caller
        # (full CLI + UI suites green, identical pass/fail counts to
        # baseline, including UI's own direct `record.write(...)` fixture
        # call sites, which bypass `reclassify`'s pre-lock validation
        # entirely). A future caller that mutates type/kind without
        # `_reclassify_apply`'s discipline is now caught HERE, not left
        # to become a new instance of B-1's defect class.
        self.validate()
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

    # -- 11 §3 adjudication-plane fields (all optional; metadata class,
    # -- same as superseded_by: verb-written, mutable in every status).

    @property
    def verified(self) -> bool | None:
        return self._fm.get("verified")

    @property
    def verified_how(self) -> str | None:
        return self._fm.get("verified_how")

    @property
    def incident_cost(self) -> str | None:
        return self._fm.get("incident_cost")

    @property
    def generality(self) -> str | None:
        return self._fm.get("generality")

    @property
    def env(self) -> dict | None:
        value = self._fm.get("env")
        return copy.deepcopy(dict(value)) if value is not None else None

    @property
    def follow_up(self) -> dict | None:
        """The OPEN follow-up on the routing block (11 §2.1), if any."""
        routing = self._fm.get("routing")
        if routing is None:
            return None
        value = routing.get("follow_up")
        return copy.deepcopy(dict(value)) if value is not None else None

    @property
    def follow_up_done(self) -> dict | None:
        value = self._fm.get("follow_up_done")
        return copy.deepcopy(dict(value)) if value is not None else None

    @property
    def recurrences(self) -> tuple:
        """Read-only view of the append-only recurrence list (11 §2.2)."""
        return tuple(copy.deepcopy(dict(r)) for r in self._fm.get("recurrences") or [])

    @property
    def dismissed_suspects(self) -> tuple:
        """Read-only view of the append-only suspect-dismissal list
        (11 §2.2, U-dismiss §4): a recurrence-suspect telemetry claim the
        human judged to be a matcher false-positive, never a recurrence."""
        return tuple(
            copy.deepcopy(dict(d)) for d in self._fm.get("dismissed_suspects") or []
        )

    @property
    def history(self) -> tuple:
        """Read-only view of the append-only ``history`` list (U-verbs
        §4.10): values a verb DISPLACED — the old ``resolution_note``
        (``reopen``) or an old ``routing`` block a later correcting verb
        displaces. Same
        metadata class as ``recurrences``: optional, verb-written,
        mutable in every status, never part of the substance freeze."""
        return tuple(copy.deepcopy(dict(h)) for h in self._fm.get("history") or [])

    @property
    def notes(self) -> tuple:
        """Read-only view of the append-only ``notes`` list (U-verbs
        §4.10): commentary a human ADDED via ``self-learn note --append``.
        Distinct from ``history`` — ``notes`` records what was ADDED,
        ``history`` records what was DISPLACED; merging the two would make
        both unreadable."""
        return tuple(copy.deepcopy(dict(n)) for n in self._fm.get("notes") or [])

    @property
    def last_confirmed(self):
        return self._fm.get("last_confirmed")

    @property
    def contradicts(self) -> tuple:
        links = self._fm.get("links")
        if not links:
            return ()
        return tuple(links.get("contradicts") or ())

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
    def redacted(self) -> bool:
        """True iff the secret scan redacted spans in this record (08 §1
        Secret-scan pin: ``--redact`` sets frontmatter ``redacted: true``)."""
        return self._fm.get("redacted") is True

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
            if routing.get("follow_up") is not None:
                _validate_follow_up(routing["follow_up"])
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

    def clear_resolution_note(self) -> None:
        """The ONLY writer permitted to set ``resolution_note`` back to
        ``None`` — ``reopen``'s displacement (U-verbs §4.10/02 §2
        amendment). Refuses UNLESS the current note already appears in a
        ``history`` entry with ``event: "resolution"`` — so the
        write-once field can be DISPLACED but never DESTROYED. A record
        with no ``resolution_note`` set is a no-op (idempotent: `reopen`
        calls this after appending the history entry, never before)."""
        note = self._fm.get("resolution_note")
        if note is None:
            return
        history = self._fm.get("history") or []
        if not any(
            h.get("event") == "resolution" and h.get("note") == note
            for h in history
        ):
            raise MutationError(
                f"resolution_note cannot be cleared on {self.id}: it is not "
                "yet displaced into a `history` entry (event: resolution) — "
                "call append_history first (02 §2)"
            )
        self._fm["resolution_note"] = None

    def set_redacted(self, value: bool = True) -> None:
        """Mark that the secret scan replaced spans (``--redact``). Absent
        when never redacted — writers set it only on an actual redaction."""
        if not isinstance(value, bool):
            raise ValidationError(f"redacted must be a bool, got {value!r}")
        if value:
            self._fm["redacted"] = True
        else:
            self._fm.pop("redacted", None)

    # ---------------------------------------- 11 §3 metadata-class setters

    def set_verified(self, value: bool | None, how: str | None = None) -> None:
        """Capture-time grounding grade (11 §3). ``None`` clears both
        fields; ``how`` without a verified value is meaningless."""
        if value is None:
            if how is not None:
                raise ValidationError("verified_how needs a verified value")
            self._fm.pop("verified", None)
            self._fm.pop("verified_how", None)
            return
        if not isinstance(value, bool):
            raise ValidationError(f"verified must be a bool, got {value!r}")
        self._fm["verified"] = value
        if how is not None:
            if not isinstance(how, str) or not how.strip():
                raise ValidationError("verified_how must be non-empty text")
            self._fm["verified_how"] = how

    def set_incident_cost(self, value: str | None) -> None:
        if value is None:
            self._fm.pop("incident_cost", None)
            return
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("incident_cost must be non-empty text")
        self._fm["incident_cost"] = value

    def set_generality(self, value: str | None) -> None:
        if value is None:
            self._fm.pop("generality", None)
            return
        if value not in GENERALITIES:
            raise ValidationError(
                f"generality must be one of {sorted(GENERALITIES)}, got {value!r}"
            )
        self._fm["generality"] = value

    def set_env(self, value: dict | None) -> None:
        """Versions PRESENT at capture — an ambient hint (11 §3): code
        cannot know what a lesson is 'about'; user-supplied entries win."""
        if value is None:
            self._fm.pop("env", None)
            return
        _validate_env(value)
        self._fm["env"] = dict(value)

    def set_last_confirmed(self, value) -> None:
        """Written by ``confirm-held`` (11 §2.2): a human observed the rule
        working. Age-since-confirmation is the staleness metric."""
        if value is None:
            self._fm.pop("last_confirmed", None)
            return
        self._fm["last_confirmed"] = value

    def set_follow_up(
        self,
        action: str,
        *,
        unblocks_on: str | None = None,
        note: str | None = None,
    ) -> None:
        """Attach the known-partial follow-up to the routing block
        (11 §2.1). The record must be routed — a follow-up is a planned
        upgrade to landed coverage, not a pre-routing wish."""
        routing = self._fm.get("routing")
        if routing is None:
            raise MutationError(
                f"record {self.id} has no routing block — follow-ups ride "
                "routing (11 §2.1); route first"
            )
        if self.status != "routed":
            raise MutationError(
                f"record {self.id} is {self.status!r} — follow-ups attach to "
                "LIVE routed coverage only (11 §2.1); a superseded lesson's "
                "upgrade plan belongs on its successor"
            )
        fu = {"action": action}
        if unblocks_on is not None:
            fu["unblocks_on"] = unblocks_on
        if note is not None:
            fu["note"] = note
        _validate_follow_up(fu)
        routing["follow_up"] = fu

    def complete_follow_up(
        self, *, done_at: str | None = None, done_note: str | None = None
    ) -> None:
        """``followup done`` (11 §2.5): clear ``routing.follow_up``, moving
        it to a dated top-level ``follow_up_done`` block."""
        routing = self._fm.get("routing")
        open_fu = routing.get("follow_up") if routing is not None else None
        if open_fu is None:
            raise MutationError(f"record {self.id} has no open follow-up")
        done = dict(open_fu)
        done["done_at"] = done_at if done_at is not None else _now_iso()[:10]
        if done_note is not None:
            if not isinstance(done_note, str) or not done_note.strip():
                raise ValidationError("done_note must be non-empty text")
            done["done_note"] = done_note
        del routing["follow_up"]
        self._fm["follow_up_done"] = done

    def append_recurrence(self, entry: dict) -> None:
        """Append one confirmed recurrence (11 §2.2) — append-only, dated,
        carrying the minimal facts; ``ref`` is a courtesy pointer."""
        _validate_recurrence(entry)
        if self._fm.get("recurrences") is None:
            self._fm["recurrences"] = []
        self._fm["recurrences"].append(dict(entry))

    def append_dismissed_suspect(self, entry: dict) -> None:
        """Append one dismissed recurrence suspect (11 §2.2, U-dismiss §4)
        — append-only, dated, carrying the minimal facts copied OUT of the
        telemetry event; unlike :meth:`append_recurrence`, ``ref`` is
        REQUIRED here (§4.3 asymmetry): without the nonce a dismissal
        clears nothing and means nothing."""
        _validate_dismissal(entry)
        if self._fm.get("dismissed_suspects") is None:
            self._fm["dismissed_suspects"] = []
        self._fm["dismissed_suspects"].append(dict(entry))

    def append_history(self, event: str, payload: dict) -> None:
        """Append one DISPLACED-value entry (U-verbs §4.10) — append-only,
        never rewritten, never removed. ``event`` is the closed set
        :data:`HISTORY_EVENTS`: ``reopen`` displaces the old resolution
        (``event="resolution"``, payload carrying ``status``/``note``);
        a later verb correcting a wrong routing destination displaces
        the old routing block (``event="routing"``,
        payload carrying ``routing``). A future third displacement is a
        decision, not a silent widening."""
        if event not in HISTORY_EVENTS:
            raise ValidationError(
                f"history event must be one of {sorted(HISTORY_EVENTS)}, got {event!r}"
            )
        if not isinstance(payload, dict):
            raise ValidationError("history payload must be a mapping")
        entry: dict = {"at": _now_iso(), "event": event}
        entry.update(payload)
        if self._fm.get("history") is None:
            self._fm["history"] = []
        self._fm["history"].append(entry)

    def append_note(self, text: str, *, by: str = "human", key: str | None = None) -> None:
        """Append one commentary entry to ``notes`` (U-verbs §4.10) — ANY
        status, and NEVER touches ``resolution_note``: ``notes`` records
        what a human ADDED, ``history`` records what a verb DISPLACED.
        ``key`` is the optional sheet-line idempotency token
        ``self-learn batch`` stamps on a ``note`` item's entry — never
        generated here; a human call at a terminal omits it and every
        call appends (two identical observations on two days are two
        facts)."""
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("note text must be non-empty")
        entry: dict = {"at": _now_iso(), "by": by, "text": text}
        if key is not None:
            entry["key"] = key
        if self._fm.get("notes") is None:
            self._fm["notes"] = []
        self._fm["notes"].append(entry)

    def note_has_key(self, key: str) -> bool:
        """True iff a ``notes[]`` entry already carries this idempotency
        key — the read ``self-learn batch`` classifies a ``note`` item's
        already-applied state on (§3.3b row 10). The one verb whose
        effect is not derivable from record state, so it is the one verb
        that carries a key."""
        return any(n.get("key") == key for n in self._fm.get("notes") or [])

    def append_contradicts(self, target: str) -> None:
        """Append one contradiction edge (11 §2.4): a record id or a canon
        anchor string."""
        if not isinstance(target, str) or not target.strip():
            raise ValidationError("contradicts target must be non-empty text")
        links = self._fm.get("links")
        if links is None:
            links = CommentedMap()
            self._fm["links"] = links
        if links.get("contradicts") is None:
            links["contradicts"] = []
        if target in links["contradicts"]:
            raise ValidationError(f"{self.id} already contradicts {target!r}")
        links["contradicts"].append(target)

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
            if routing.get("follow_up") is not None:
                _validate_follow_up(routing["follow_up"])
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
        redacted = fm.get("redacted")
        if redacted is not None and not isinstance(redacted, bool):
            raise ValidationError(f"redacted must be a bool, got {redacted!r}")
        count = fm.get("deferred_count")
        if count is not None and (
            not isinstance(count, int) or isinstance(count, bool) or count < 0
        ):
            raise ValidationError(f"deferred_count must be a non-negative int, got {count!r}")

        # ---- 11 §3 adjudication-plane fields (all optional)
        verified = fm.get("verified")
        if verified is not None and not isinstance(verified, bool):
            raise ValidationError(f"verified must be a bool, got {verified!r}")
        how = fm.get("verified_how")
        if how is not None:
            if not isinstance(how, str) or not how.strip():
                raise ValidationError("verified_how must be non-empty text")
            if verified is None:
                raise ValidationError("verified_how needs a verified value")
        cost = fm.get("incident_cost")
        if cost is not None and (not isinstance(cost, str) or not cost.strip()):
            raise ValidationError("incident_cost must be non-empty text")
        generality = fm.get("generality")
        if generality is not None and generality not in GENERALITIES:
            raise ValidationError(
                f"generality must be one of {sorted(GENERALITIES)}, got {generality!r}"
            )
        env = fm.get("env")
        if env is not None:
            _validate_env(env)
        done = fm.get("follow_up_done")
        if done is not None:
            _validate_follow_up(done)
            if done.get("done_at") is None:
                raise ValidationError("follow_up_done needs done_at (11 §2.5)")
        recurrences = fm.get("recurrences")
        if recurrences is not None:
            if not isinstance(recurrences, list):
                raise ValidationError("recurrences must be a list")
            for entry in recurrences:
                _validate_recurrence(entry)
        dismissed_suspects = fm.get("dismissed_suspects")
        if dismissed_suspects is not None:
            if not isinstance(dismissed_suspects, list):
                raise ValidationError("dismissed_suspects must be a list")
            for entry in dismissed_suspects:
                _validate_dismissal(entry)
        links = fm.get("links")
        if links is not None:
            _validate_links(links)
        history = fm.get("history")
        if history is not None:
            if not isinstance(history, list):
                raise ValidationError("history must be a list")
            for entry in history:
                _validate_history_entry(entry)
        notes = fm.get("notes")
        if notes is not None:
            if not isinstance(notes, list):
                raise ValidationError("notes must be a list")
            for entry in notes:
                _validate_note_entry(entry)

        self._validate_body(fm["type"], self._body)

    @staticmethod
    def _validate_body(type: str, body: str) -> None:
        validate_body(type, body)


def _validate_follow_up(fu: object) -> None:
    """Shape of a follow-up block (open or done): ``action`` required;
    ``unblocks_on``/``note`` optional human-readable strings (11 §2.1)."""
    if not isinstance(fu, dict):
        raise ValidationError(f"follow_up must be a mapping, got {fu!r}")
    action = fu.get("action")
    if not isinstance(action, str) or not action.strip():
        raise ValidationError("follow_up needs a non-empty action (11 §2.1)")
    for key in ("unblocks_on", "note", "done_note"):
        value = fu.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValidationError(f"follow_up {key} must be non-empty text")


def _validate_env(env: object) -> None:
    if not isinstance(env, dict) or not env:
        raise ValidationError("env must be a non-empty mapping of component → version")
    for key, value in env.items():
        if not isinstance(key, str) or not key.strip():
            raise ValidationError(f"env keys must be non-empty strings, got {key!r}")
        if not isinstance(value, _ENV_SCALARS) or isinstance(value, bool):
            raise ValidationError(
                f"env values must be version scalars, got {key}: {value!r}"
            )


def _validate_recurrence(entry: object) -> None:
    """One confirmed recurrence: ts + origin are the minimal facts copied
    out of the event; note/ref optional (ref = courtesy pointer, 11 §2.2)."""
    if not isinstance(entry, dict) or not entry:
        raise ValidationError(f"recurrence must be a non-empty mapping, got {entry!r}")
    for key in ("ts", "origin"):
        value = entry.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValidationError(f"recurrence needs {key} (11 §2.2), got {entry!r}")


def _validate_dismissal(entry: object) -> None:
    """One dismissed recurrence suspect (11 §2.2, U-dismiss §4.3): ``ref``
    + ``ts`` + ``why`` are the minimal facts. Unlike
    :func:`_validate_recurrence`, ``ref`` is REQUIRED — a dismissal is a
    fact about one specific machine claim, and without the nonce it
    clears nothing and means nothing. No enum check on ``why`` here
    (U-dismiss §5): that lives at the CLI (argparse ``choices=``) so a
    record written under an older, smaller enum never retroactively
    fails validation."""
    if not isinstance(entry, dict) or not entry:
        raise ValidationError(f"dismissal must be a non-empty mapping, got {entry!r}")
    for key in ("ref", "ts", "why"):
        value = entry.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValidationError(f"dismissal needs {key} (11 §2.2), got {entry!r}")


def _validate_history_entry(entry: object) -> None:
    """One ``history`` entry (U-verbs §4.10): ``at`` + ``event`` are the
    minimal facts; ``event`` must be in the closed set, checked here too
    (not only at append time) so a hand-edited or migrated ledger cannot
    carry a widened event a future reader has never heard of."""
    if not isinstance(entry, dict) or not entry:
        raise ValidationError(f"history entry must be a non-empty mapping, got {entry!r}")
    at = entry.get("at")
    if at is None or (isinstance(at, str) and not at.strip()):
        raise ValidationError(f"history entry needs at (U-verbs §4.10), got {entry!r}")
    event = entry.get("event")
    if event not in HISTORY_EVENTS:
        raise ValidationError(
            f"history entry event must be one of {sorted(HISTORY_EVENTS)}, got {event!r}"
        )


def _validate_note_entry(entry: object) -> None:
    """One ``notes`` entry (U-verbs §4.10): ``at`` is the minimal fact;
    ``key``, when present, must be non-empty text (the batch idempotency
    token)."""
    if not isinstance(entry, dict) or not entry:
        raise ValidationError(f"note entry must be a non-empty mapping, got {entry!r}")
    at = entry.get("at")
    if at is None or (isinstance(at, str) and not at.strip()):
        raise ValidationError(f"note entry needs at (U-verbs §4.10), got {entry!r}")
    key = entry.get("key")
    if key is not None and (not isinstance(key, str) or not key.strip()):
        raise ValidationError("note entry key must be non-empty text")


def _validate_links(links: object) -> None:
    if not isinstance(links, dict):
        raise ValidationError("links must be a mapping")
    contradicts = links.get("contradicts")
    if contradicts is None:
        return
    if not isinstance(contradicts, list) or not contradicts:
        raise ValidationError("links.contradicts must be a non-empty list")
    for target in contradicts:
        if not isinstance(target, str) or not target.strip():
            raise ValidationError(
                f"contradicts targets must be non-empty strings, got {target!r}"
            )


def _validate_scope(scope: object) -> None:
    if scope in ("project", "user"):
        return
    if isinstance(scope, str) and scope.startswith("skill:") and len(scope) > len("skill:"):
        return
    raise ValidationError(f"scope must be skill:<name>, project, or user, got {scope!r}")


def parse_record(text: str) -> Record:
    """Parse a record from its file text (frontmatter + body), validating it."""
    return Record.from_text(text)
