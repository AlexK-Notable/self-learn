"""premises.py -- what a placed lesson rests on, and the read-only checks
that re-observe it (premise-check design, unit U1; decision row
S-NEXT-u1-premises, assigned at landing).

A placed lesson can stay loaded long after the fact it rests on stopped
being true (the case that prompted this: a lesson saying "nothing binds
service X to the bus" stayed loaded for weeks after a drop-in bound it).
This module gives a lesson a short list of **premises** -- plain claims,
each optionally paired with a **probe** from a closed catalog of read-only
checks -- and the code that runs those probes. Nothing here calls a model,
writes the ledger, or takes a lock. The daily sweep, the steward input and
the sheet verb that writes the field are later units (U2, U3, U4); this
module is the schema, the catalog, the runner and the comparison they
share.

**The field.** ``premises`` on a record (frontmatter), a list of at most
:data:`MAX_PREMISES` mappings, at most :data:`MAX_PROBED` of them with a
probe::

    premises:
      - id: p1
        claim: the unit is not bound to the session bus
        probe: {kind: systemd-show, scope: user, unit: x.service, property: BindsTo}
        holds_if: absent          # judged against the observed value
        match: dbus-broker.service
        on_change: re-decide      # re-decide | refresh
        source: case-0000000a#what_would_change[1]
        baseline: {value_sha: <32 hex>, shown: "", observed_at: <iso>, state: holds}
        decided_at: 2026-10-30
      - id: p2
        claim: the daemon can outlive a bus restart without reconnecting
        probe: null               # behavioural: written down, never probed

It is a metadata field (the ``env``/``follow_up`` class): mutable in every
status, carried over by ``replace`` (``cases.REWRITE_FIELDS``), and
validated by :meth:`records.Record.validate` through
:func:`validate_premises`. A record that breaks it does not load, like
any other field.

**The probe catalog is closed** (:data:`PROBE_KINDS`). Every probe obeys,
by construction of this module rather than by convention:

- It never acts on the system. Only three programs are ever run --
  ``systemctl`` (``show`` only), ``pacman`` (``-Q`` only) and ``git``
  (``cat-file blob HEAD:<path>`` only) -- from argv lists built here from
  validated fields, and :func:`_check_argv` refuses any argv outside those
  three exact shapes before the command runner is called, whatever runner
  is injected. No sudo, no pkexec, no ``busctl``/D-Bus method call, no
  network (``GIT_NO_LAZY_FETCH``), no shell, no running the tool a lesson
  is about. ``systemctl`` carries ``--no-ask-password`` so it can never
  start a polkit conversation.
- stdin is ``/dev/null`` and every command has a :data:`PROBE_TIMEOUT`
  (5 s) bound, enforced through :func:`procs.run_bounded` (the whole
  process group dies on expiry): a probe that blocks is ``unavailable``,
  never a hang (lrn-373f59d9). Children get a scrubbed environment
  (:func:`_child_env`): ``LC_ALL=C``, ``PATH``, ``HOME``,
  ``XDG_RUNTIME_DIR`` and the git safety switches -- no session bus
  address, no display, no agent sockets.
- Paths that look like credentials are refused when the premise is
  validated and again, on the resolved path, when the probe runs
  (:func:`credential_path_problem`; lrn-19abaf40). File reads never follow
  a FIFO or device (``O_NONBLOCK`` + a regular-file check) and stop at
  :data:`READ_LIMIT`; a larger file is ``unavailable``, never a partial
  answer.
- File text is never stored or returned: a file probe yields a token
  (``present``/``absent``/``missing``) or a hash of a line range, and an
  :class:`Observation` carries only a value hash plus a short display
  string that passed the secret scan.
- A probe that cannot read its target yields ``unavailable``, which
  :func:`verdict` never reads as unchanged or as moved (the
  ``conditions.py`` fail-closed rule; lrn-6d21607e). A target that is
  readably ABSENT (no such file, no such key, package not installed) is
  a real observation with its own value, so its disappearance is a
  change, never a silent "unchanged".

**Placement premises (unit U8).** ``reach``, ``writable`` and ``intact``
(:data:`PLACEMENT_PREMISE_IDS`) are implicit on every routed lesson and
derived by code from the lesson's placement; nobody writes them. They are
reserved here: a written premise may not use those names as an id or as a
probe kind. U8 builds their observations with :func:`observation_from_value`
(or :func:`unavailable_observation` for "unmeasurable"), so they share the
same value hash, the same fail-closed state and the same :func:`verdict`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from . import scan
from .primitives import chrono, procs

__all__ = [
    "ABSENT",
    "ALLOWED_PROGRAMS",
    "BASELINE_STATES",
    "MISSING",
    "MISSING_KEY",
    "NOT_FOUND",
    "NOT_INSTALLED",
    "OUT_OF_RANGE",
    "PRESENT",
    "CLAIM_CONTRADICTED",
    "CLAIM_HOLDS",
    "CLAIM_UNJUDGED",
    "CommandResult",
    "CommandRunner",
    "HOLDS_IF_VALUES",
    "MAX_PREMISES",
    "MAX_PROBED",
    "ON_CHANGE_VALUES",
    "OBS_OK",
    "OBS_UNAVAILABLE",
    "Observation",
    "PLACEMENT_PREMISE_IDS",
    "PROBE_KINDS",
    "PROBE_TIMEOUT",
    "PremiseCheck",
    "PremiseError",
    "ProbeEnv",
    "ProbeRefused",
    "READ_LIMIT",
    "VERDICTS",
    "VERDICT_HOLDS",
    "VERDICT_MOVED",
    "VERDICT_NO_BASELINE",
    "VERDICT_NO_PROBE",
    "VERDICT_UNAVAILABLE",
    "check_record",
    "credential_path_problem",
    "default_runner",
    "make_baseline",
    "normalize_premises",
    "normalize_value",
    "observation_from_value",
    "observe",
    "run_probe",
    "unavailable_observation",
    "validate_premises",
    "validate_probe",
    "value_sha",
    "vercmp",
    "verdict",
]

# ------------------------------------------------------------- vocabulary

#: The closed probe catalog (design D3). Adding a kind is a decision, not
#: a widening: each kind is one read-only executor below.
PROBE_KINDS = frozenset(
    {
        "path", "file-match", "json-key", "yaml-key", "toml-key",
        "systemd-show", "package", "which", "git-file", "ledger",
    }
)
#: How an observed value is judged against the premise's ``match``.
#: ``present``/``absent``: ``match`` occurs / does not occur in the value;
#: ``equals``/``not-equals``: whole-value comparison; ``version-range``
#: (``package`` probes only): ``match`` is a comma-separated list of
#: ``<op><version>`` clauses, all of which must hold (pacman's vercmp).
HOLDS_IF_VALUES = frozenset({"present", "absent", "equals", "not-equals", "version-range"})
#: ``re-decide``: a stable change puts the lesson in front of the steward.
#: ``refresh``: code re-records the baseline with no model call (D7.4).
ON_CHANGE_VALUES = frozenset({"re-decide", "refresh"})
#: ``holds``/``contradicts-claim``: the baseline value was judged against
#: the claim (``holds_if`` given); ``recorded``: no ``holds_if``, so only
#: a change from this value can be noticed (D10's disagreement-at-write).
BASELINE_STATES = frozenset({"holds", "contradicts-claim", "recorded"})
#: U8's implicit placement premises: derived by code, never written.
PLACEMENT_PREMISE_IDS = ("reach", "writable", "intact")

MAX_PREMISES = 4
MAX_PROBED = 3
#: Per-probe wall-clock bound in seconds. A caller may ask for less
#: (:attr:`ProbeEnv.timeout`), never more.
PROBE_TIMEOUT = 5.0
#: The most a file probe reads, and the most command output kept.
READ_LIMIT = 256 * 1024
#: Display strings longer than this are not stored (the hash still is).
SHOWN_LIMIT = 120
#: Value hashes are sha256 truncated to 32 hex characters (128 bits): the
#: secret scan's hex rule fires on runs of 48+ hex characters
#: (``scan._HEX_RUN``), so a full digest in a record would make every
#: whole-record scan (``replace``'s ``secret-record`` check) refuse it.
VALUE_SHA_CHARS = 32

OBS_OK = "ok"
OBS_UNAVAILABLE = "unavailable"
CLAIM_HOLDS = "holds"
CLAIM_CONTRADICTED = "contradicted"
CLAIM_UNJUDGED = "unjudged"

VERDICT_HOLDS = "holds"
VERDICT_MOVED = "moved"
VERDICT_UNAVAILABLE = "unavailable"
VERDICT_NO_PROBE = "no-probe"
VERDICT_NO_BASELINE = "no-baseline"
VERDICTS = frozenset(
    {VERDICT_HOLDS, VERDICT_MOVED, VERDICT_UNAVAILABLE, VERDICT_NO_PROBE, VERDICT_NO_BASELINE}
)

#: Tokens a probe yields for an observed absence or a match result. They
#: are never quoted, so no JSON-serialized key value can collide with
#: them (a found string value is always quoted by the canonical form).
MISSING = "missing"
PRESENT = "present"
ABSENT = "absent"
NOT_INSTALLED = "not-installed"
NOT_FOUND = "not-found"
MISSING_KEY = "<missing-key>"
OUT_OF_RANGE = "out-of-range"

_PREMISE_KEYS = (
    "id", "claim", "probe", "holds_if", "match", "on_change", "source",
    "baseline", "decided_at",
)
_BASELINE_KEYS = frozenset({"value_sha", "shown", "observed_at", "state"})
_PREMISE_ID_RE = re.compile(r"^p[1-9][0-9]?$")
_VALUE_SHA_RE = re.compile(r"^[0-9a-f]{%d}$" % VALUE_SHA_CHARS)
_RECORD_ID_RE = re.compile(r"^lrn-[0-9a-f]{8}$")
_STMT_ID_RE = re.compile(r"^stmt-[0-9a-f]{8}$")
_UNIT_RE = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9:_.@\\-]{0,200}\."
    r"(service|socket|target|timer|mount|automount|path|slice|scope|swap|device)$"
)
_PROPERTY_RE = re.compile(r"^[A-Z][A-Za-z0-9]{0,63}$")
_PACKAGE_RE = re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]{0,127}$")
_COMMAND_NAME_RE = re.compile(r"^[A-Za-z0-9_+][A-Za-z0-9._+-]{0,63}$")
_LINES_RE = re.compile(r"^([1-9][0-9]{0,6})(?:-([1-9][0-9]{0,6}))?$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)?$")
_VERSION_CLAUSE_RE = re.compile(r"^(>=|<=|==|!=|>|<)\s*([A-Za-z0-9:._+~-]{1,64})$")

_CLAIM_LIMIT = 300
_TEXT_LIMIT = 200
_PATH_LIMIT = 512
_KEY_PART_LIMIT = 128
_KEY_DEPTH_LIMIT = 16
_MAX_LINE_SPAN = 1000
_MAX_VERSION_CLAUSES = 4
#: Canonical-form budget for a parsed key value: a YAML alias bomb is
#: cheap to load (aliases share one object) but explodes when written
#: out, so the serializer counts nodes and gives up.
_CANON_NODE_BUDGET = 10_000
_CANON_DEPTH_LIMIT = 64


def _member(value: object, allowed: frozenset[str]) -> bool:
    """``value in allowed`` that cannot raise: a list or mapping where a
    word belongs (a hand-edited record) is simply not a member."""
    return isinstance(value, str) and value in allowed


class PremiseError(ValueError):
    """A premise or probe breaks this module's schema. ``records`` turns it
    into a :class:`records.ValidationError` at load and write time."""


class ProbeRefused(PremiseError):
    """An argv outside the three allowed command shapes reached the command
    gate. Raised before any runner is called; :func:`observe` reports it
    as ``unavailable`` and nothing runs."""


# --------------------------------------------------------- text and paths


def _text_problem(value: object, what: str, *, limit: int = _TEXT_LIMIT) -> str | None:
    """One line of printable text, scan-clean, at most *limit* characters."""
    if not isinstance(value, str) or not value.strip():
        return f"{what} must be non-empty text"
    if len(value) > limit:
        return f"{what} is longer than {limit} characters"
    if not value.isprintable():
        return f"{what} must be one line of printable text (no newline, tab or control character)"
    if scan.scan(value):
        return f"{what} looks like it holds a secret (the secret scan matched it)"
    return None


#: Directory or file names that hold credentials or keys, compared
#: case-insensitively against EVERY component of a path.
_CREDENTIAL_COMPONENTS = frozenset(
    {
        ".ssh", ".gnupg", ".password-store", ".aws", ".azure", ".kube", ".pki",
        ".docker", "keyrings", "secrets", ".secrets", "gh", "bws", "bitwarden cli",
        "rclone", "sops", "age", ".env", ".netrc", ".pgpass", ".git-credentials",
        ".npmrc", ".pypirc", ".htpasswd", ".credentials.json", "credentials",
        "credentials.json", "hosts.yml", "hosts.yaml", "auth.json", "shadow",
        "gshadow", "sudoers", "authorized_keys", "known_hosts", "keys.txt",
    }
)
#: A component starting with one of these (``id_rsa``, ``id_ed25519``,
#: ``.env.local``) is refused.
_CREDENTIAL_PREFIXES = ("id_", ".env.")
#: A component ending with one of these (``token.env``, ``server.key``).
_CREDENTIAL_SUFFIXES = (
    ".env", ".pem", ".key", ".p12", ".pfx", ".kdbx", ".age", ".gpg", ".asc",
    ".keystore", ".jks", ".ovpn",
)
#: A component containing one of these words anywhere.
_CREDENTIAL_WORDS = (
    "token", "secret", "credential", "password", "passwd", "apikey", "api_key",
    "api-key", "private", "bitwarden", "keepass", "1password",
)
#: Absolute trees no probe reads: process and device views (an
#: ``environ`` file, a tty that blocks), runtime sockets and agent
#: directories, root's home.
_DENIED_ROOTS = ("/proc", "/sys", "/dev", "/run", "/root", "/var/run")


def credential_path_problem(path: str, *, reads_content: bool = True) -> str | None:
    """Why *path* may not be probed, or ``None``. Lexical, case-insensitive,
    deliberately broad: a false refusal costs one premise its probe; a
    false pass could put a credential's existence or bytes in front of a
    model. ``~/`` counts as a home prefix, so ``~/.ssh/config`` is refused
    exactly like its absolute spelling. With *reads_content* (every kind
    that reads a file's bytes), a path inside a ``.git`` directory is also
    refused: a repository's ``config`` can carry a token in a remote URL.
    """
    if not isinstance(path, str) or not path:
        return "the path is empty"
    if path.startswith("/"):
        for root in _DENIED_ROOTS:
            if path == root or path.startswith(root + "/"):
                return f"paths under {root} are never probed"
    for part in PurePosixPath(path).parts:
        low = part.lower()
        if low in ("/", "~"):
            continue
        if low in _CREDENTIAL_COMPONENTS:
            return f"{part!r} names a credential or key location"
        if low.startswith(_CREDENTIAL_PREFIXES) or low.endswith(_CREDENTIAL_SUFFIXES):
            return f"{part!r} looks like a credential or key file"
        for word in _CREDENTIAL_WORDS:
            if word in low:
                return f"{part!r} contains {word!r}, which marks a credential"
        if reads_content and low == ".git":
            return "a file inside a .git directory may hold a credential (a remote URL)"
    return None


def _path_problem(value: object, what: str, *, reads_content: bool) -> str | None:
    """An absolute or ``~/`` path: printable, no ``.``/``..``/empty
    segments, no ``~user`` form, not a credential location."""
    if not isinstance(value, str) or not value:
        return f"{what} must be a non-empty path"
    if len(value) > _PATH_LIMIT:
        return f"{what} is longer than {_PATH_LIMIT} characters"
    if not value.isprintable():
        return f"{what} must be printable, with no newline or control character"
    if value.startswith("/"):
        rest = value[1:]
    elif value.startswith("~/"):
        rest = value[2:]
    else:
        return f"{what} must be absolute or start with ~/ (got {value!r})"
    segments = rest.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        return f"{what} may not hold empty, '.' or '..' segments (got {value!r})"
    problem = credential_path_problem(value, reads_content=reads_content)
    if problem is not None:
        return f"{what} is refused: {problem}"
    if scan.scan(value):
        return f"{what} looks like it holds a secret (the secret scan matched it)"
    return None


def _repo_relative_problem(value: object, what: str) -> str | None:
    """A path inside a repository, as git names it: relative, no
    ``.``/``..``/empty segments, not a credential location."""
    if not isinstance(value, str) or not value:
        return f"{what} must be a non-empty repository path"
    if len(value) > _PATH_LIMIT:
        return f"{what} is longer than {_PATH_LIMIT} characters"
    if not value.isprintable():
        return f"{what} must be printable, with no newline or control character"
    if value.startswith("/") or value.startswith("~"):
        return f"{what} must be relative to the repository (got {value!r})"
    if any(seg in ("", ".", "..") for seg in value.split("/")):
        return f"{what} may not hold empty, '.' or '..' segments (got {value!r})"
    if value.startswith("-"):
        return f"{what} may not start with '-'"
    problem = credential_path_problem(value, reads_content=True)
    if problem is not None:
        return f"{what} is refused: {problem}"
    if scan.scan(value):
        return f"{what} looks like it holds a secret (the secret scan matched it)"
    return None


def _expand(path: str, home: Path) -> str:
    """``~/x`` against *home*; an absolute path as it is."""
    if path.startswith("~/"):
        return str(home) + "/" + path[2:]
    return path


# ------------------------------------------------------- probe validation


def _key_path(value: object) -> list[str | int] | None:
    """The key path as a list, or ``None`` when malformed. A string is
    split on ``.`` (a key that itself holds a dot needs the list form)."""
    if isinstance(value, str):
        parts: list[Any] = value.split(".")
    elif isinstance(value, list):
        parts = list(value)
    else:
        return None
    if not 1 <= len(parts) <= _KEY_DEPTH_LIMIT:
        return None
    out: list[str | int] = []
    for part in parts:
        if isinstance(part, bool):
            return None
        if isinstance(part, int):
            if part < 0:
                return None
            out.append(int(part))
        elif isinstance(part, str):
            if _text_problem(part, "key", limit=_KEY_PART_LIMIT) is not None:
                return None
            out.append(str(part))
        else:
            return None
    return out


def _line_span(value: object) -> tuple[int, int] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return (int(value), int(value)) if value >= 1 else None
    if not isinstance(value, str):
        return None
    m = _LINES_RE.match(value)
    if m is None:
        return None
    first = int(m.group(1))
    last = int(m.group(2)) if m.group(2) else first
    if last < first or last - first >= _MAX_LINE_SPAN:
        return None
    return (first, last)


def _matcher_problem(probe: Mapping, kind: str) -> str | None:
    """A file-reading probe names exactly one of ``contains`` (a literal
    anywhere in the file), ``line`` (a line equal to it, ignoring the
    whitespace around it) or ``lines`` (``A`` or ``A-B``: the hash of that
    line range). No regular expressions: Python's ``re`` cannot be bounded
    in time, and a pattern written by a model over a 256 KiB file could
    hang the sweep."""
    given = [k for k in ("contains", "line", "lines") if k in probe]
    if len(given) != 1:
        return f"a {kind} probe names exactly one of contains, line or lines"
    key = given[0]
    if key == "lines":
        if _line_span(probe["lines"]) is None:
            return (
                f"{kind} probe lines must be 'A' or 'A-B' with 1 <= A <= B "
                f"and at most {_MAX_LINE_SPAN} lines"
            )
        return None
    return _text_problem(probe[key], f"{kind} probe {key}")


_PROBE_FIELDS: dict[str, frozenset[str]] = {
    "path": frozenset({"kind", "path"}),
    "file-match": frozenset({"kind", "path", "contains", "line", "lines"}),
    "json-key": frozenset({"kind", "path", "key"}),
    "yaml-key": frozenset({"kind", "path", "key"}),
    "toml-key": frozenset({"kind", "path", "key"}),
    "systemd-show": frozenset({"kind", "scope", "unit", "property"}),
    "package": frozenset({"kind", "name"}),
    "which": frozenset({"kind", "name"}),
    "git-file": frozenset({"kind", "repo", "path", "contains", "line", "lines"}),
    "ledger": frozenset({"kind", "target", "field"}),
}


def _probe_problem(probe: object, *, record_id: str | None = None) -> str | None:
    if not isinstance(probe, Mapping):
        return f"probe must be a mapping or null, got {type(probe).__name__}"
    kind = probe.get("kind")
    if kind in PLACEMENT_PREMISE_IDS:
        return (
            f"probe kind {kind!r} is a placement premise: code derives it for every "
            "routed lesson, and it is never written"
        )
    if not isinstance(kind, str) or kind not in PROBE_KINDS:
        return f"probe kind must be one of {sorted(PROBE_KINDS)}, got {kind!r}"
    unknown = sorted(str(k) for k in probe if k not in _PROBE_FIELDS[kind])
    if unknown:
        return f"{kind} probe does not take {unknown} (allowed: {sorted(_PROBE_FIELDS[kind])})"
    if kind == "path":
        return _path_problem(probe.get("path"), "path probe path", reads_content=False)
    if kind == "file-match":
        return _path_problem(
            probe.get("path"), "file-match probe path", reads_content=True
        ) or _matcher_problem(probe, kind)
    if kind in ("json-key", "yaml-key", "toml-key"):
        problem = _path_problem(probe.get("path"), f"{kind} probe path", reads_content=True)
        if problem is not None:
            return problem
        if _key_path(probe.get("key")) is None:
            return (
                f"{kind} probe key must be a dotted string or a list of 1-"
                f"{_KEY_DEPTH_LIMIT} names and indexes"
            )
        return None
    if kind == "systemd-show":
        if probe.get("scope") not in ("user", "system"):
            return f"systemd-show probe scope must be user or system, got {probe.get('scope')!r}"
        unit = probe.get("unit")
        if not isinstance(unit, str) or not _UNIT_RE.match(unit):
            return f"systemd-show probe unit is not a unit name: {unit!r}"
        prop = probe.get("property")
        if not isinstance(prop, str) or not _PROPERTY_RE.match(prop):
            return f"systemd-show probe property is not a property name: {prop!r}"
        return None
    if kind == "package":
        name = probe.get("name")
        if not isinstance(name, str) or not _PACKAGE_RE.match(name):
            return f"package probe name is not a package name: {name!r}"
        return None
    if kind == "which":
        name = probe.get("name")
        if not isinstance(name, str) or not _COMMAND_NAME_RE.match(name):
            return f"which probe name must be a bare command name, got {name!r}"
        return None
    if kind == "git-file":
        return (
            _path_problem(probe.get("repo"), "git-file probe repo", reads_content=True)
            or _repo_relative_problem(probe.get("path"), "git-file probe path")
            or _matcher_problem(probe, kind)
        )
    # kind == "ledger"
    target = probe.get("target")
    if isinstance(target, str) and _RECORD_ID_RE.match(target):
        if record_id is not None and target == record_id:
            return "a ledger probe may not name its own lesson"
        fld = probe.get("field", "status")
        if fld not in ("status", "follow_up"):
            return f"ledger probe field must be status or follow_up, got {fld!r}"
        return None
    if isinstance(target, str) and _STMT_ID_RE.match(target):
        if "field" in probe:
            return "a ledger probe on a statement takes no field"
        return None
    return f"ledger probe target must be a lesson id or a statement id, got {target!r}"


def validate_probe(probe: object, *, record_id: str | None = None) -> None:
    """Raise :class:`PremiseError` unless *probe* is one well-formed probe
    of the catalog. The steward's probe tool (U5) checks a probe it is
    writing with this same function."""
    problem = _probe_problem(probe, record_id=record_id)
    if problem is not None:
        raise PremiseError(problem)


def _version_clauses(match: str) -> list[tuple[str, str]] | None:
    clauses = [c.strip() for c in match.split(",")]
    if not 1 <= len(clauses) <= _MAX_VERSION_CLAUSES:
        return None
    out: list[tuple[str, str]] = []
    for clause in clauses:
        m = _VERSION_CLAUSE_RE.match(clause)
        if m is None:
            return None
        out.append((m.group(1), m.group(2)))
    return out


def _baseline_problem(baseline: object) -> str | None:
    if not isinstance(baseline, Mapping):
        return "baseline must be a mapping"
    unknown = sorted(str(k) for k in baseline if k not in _BASELINE_KEYS)
    if unknown:
        return f"baseline does not take {unknown}"
    sha = baseline.get("value_sha")
    if not isinstance(sha, str) or not _VALUE_SHA_RE.match(sha):
        return f"baseline value_sha must be {VALUE_SHA_CHARS} lowercase hex characters"
    shown = baseline.get("shown", "")
    if not isinstance(shown, str):
        return "baseline shown must be text"
    if shown:
        problem = _text_problem(shown, "baseline shown", limit=SHOWN_LIMIT)
        if problem is not None:
            return problem
    observed_at = baseline.get("observed_at")
    if not isinstance(observed_at, (str, datetime)) or (
        isinstance(observed_at, str)
        and (not observed_at.strip() or len(observed_at) > 64 or not observed_at.isprintable())
    ):
        return "baseline needs observed_at, a timestamp"
    if not _member(baseline.get("state"), BASELINE_STATES):
        return f"baseline state must be one of {sorted(BASELINE_STATES)}"
    return None


def _premise_problem(premise: object, *, record_id: str | None) -> str | None:
    if not isinstance(premise, Mapping):
        return f"each premise must be a mapping, got {type(premise).__name__}"
    unknown = sorted(str(k) for k in premise if k not in _PREMISE_KEYS)
    if unknown:
        return f"a premise does not take {unknown} (allowed: {list(_PREMISE_KEYS)})"
    pid = premise.get("id")
    if pid in PLACEMENT_PREMISE_IDS:
        return (
            f"premise id {pid!r} is a placement premise: code derives it for every "
            "routed lesson, and it is never written"
        )
    if not isinstance(pid, str) or not _PREMISE_ID_RE.match(pid):
        return f"premise id must be p1..p99, got {pid!r}"
    problem = _text_problem(premise.get("claim"), f"premise {pid} claim", limit=_CLAIM_LIMIT)
    if problem is not None:
        return problem
    probe = premise.get("probe")
    if probe is not None:
        problem = _probe_problem(probe, record_id=record_id)
        if problem is not None:
            return f"premise {pid}: {problem}"
    holds_if = premise.get("holds_if")
    match = premise.get("match")
    if holds_if is not None or match is not None:
        if probe is None:
            return f"premise {pid}: holds_if and match need a probe"
        if not _member(holds_if, HOLDS_IF_VALUES):
            return f"premise {pid}: holds_if must be one of {sorted(HOLDS_IF_VALUES)}"
        problem = _text_problem(match, f"premise {pid} match")
        if problem is not None:
            return problem
        if holds_if == "version-range":
            if probe.get("kind") != "package":
                return f"premise {pid}: holds_if version-range needs a package probe"
            if _version_clauses(str(match)) is None:
                return (
                    f"premise {pid}: version-range match must be up to "
                    f"{_MAX_VERSION_CLAUSES} comma-separated '<op><version>' clauses "
                    "(op: >= > <= < == !=)"
                )
    on_change = premise.get("on_change")
    if on_change is not None:
        if probe is None:
            return f"premise {pid}: on_change needs a probe"
        if not _member(on_change, ON_CHANGE_VALUES):
            return f"premise {pid}: on_change must be one of {sorted(ON_CHANGE_VALUES)}"
    source = premise.get("source")
    if source is not None:
        problem = _text_problem(source, f"premise {pid} source")
        if problem is not None:
            return problem
    baseline = premise.get("baseline")
    if baseline is not None:
        if probe is None:
            return f"premise {pid}: a premise with no probe has no baseline"
        problem = _baseline_problem(baseline)
        if problem is not None:
            return f"premise {pid}: {problem}"
    decided_at = premise.get("decided_at")
    if decided_at is not None and not (
        isinstance(decided_at, (date, datetime))
        or (isinstance(decided_at, str) and _DATE_RE.match(decided_at))
    ):
        return f"premise {pid}: decided_at must be a date"
    return None


def validate_premises(value: object, *, record_id: str | None = None) -> None:
    """Raise :class:`PremiseError` unless *value* is a well-formed
    ``premises`` list. An empty list is valid: it says "this lesson rests
    on nothing checkable", so the backfill (U6) does not offer it again.
    *record_id*, when given, refuses a ledger probe on the lesson itself."""
    if not isinstance(value, list):
        raise PremiseError(f"premises must be a list, got {type(value).__name__}")
    if len(value) > MAX_PREMISES:
        raise PremiseError(
            f"a lesson has at most {MAX_PREMISES} premises (got {len(value)}); "
            "one that needs more is about too many things"
        )
    seen: set[str] = set()
    probed = 0
    for premise in value:
        problem = _premise_problem(premise, record_id=record_id)
        if problem is not None:
            raise PremiseError(problem)
        pid = premise["id"]
        if pid in seen:
            raise PremiseError(f"duplicate premise id {pid!r}")
        seen.add(pid)
        if premise.get("probe") is not None:
            probed += 1
    if probed > MAX_PROBED:
        raise PremiseError(
            f"at most {MAX_PROBED} premises of a lesson carry a probe (got {probed})"
        )


def _plain(value: Any) -> Any:
    """A plain-Python deep copy of a loaded YAML value: mappings, lists,
    str/int/float/bool/None, and dates as ISO text."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, datetime):
        moment = value if value.tzinfo is None else value.astimezone(timezone.utc)
        return moment.strftime(chrono.ISO_FORMAT)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return value


def normalize_premises(value: object, *, record_id: str | None = None) -> list[dict]:
    """Validate *value* and return it as plain dicts in the field's
    canonical key order (``id, claim, probe, holds_if, match, on_change,
    source, baseline, decided_at``), dates as ISO text. What
    :meth:`records.Record.set_premises` stores."""
    validate_premises(value, record_id=record_id)
    out: list[dict] = []
    for premise in value:  # type: ignore[union-attr]  # validated a list above
        plain = _plain(premise)
        out.append({k: plain[k] for k in _PREMISE_KEYS if k in plain})
    return out


# ------------------------------------------------------------------ vercmp


def _rpmvercmp(a: str, b: str) -> int:
    """pacman's ``rpmvercmp`` (lib/libalpm/version.c), ASCII classes as in
    the C locale: alternating numeric and alphabetic segments, numeric
    beats alphabetic, a longer separator run wins, and a trailing
    alphabetic segment loses to nothing (``1.5b`` < ``1.5``)."""
    if a == b:
        return 0
    one = ptr1 = 0
    two = ptr2 = 0
    la, lb = len(a), len(b)
    while one < la and two < lb:
        while one < la and not _isalnum(a[one]):
            one += 1
        while two < lb and not _isalnum(b[two]):
            two += 1
        if not (one < la and two < lb):
            break
        if (one - ptr1) != (two - ptr2):
            return -1 if (one - ptr1) < (two - ptr2) else 1
        ptr1, ptr2 = one, two
        if _isdigit(a[ptr1]):
            while ptr1 < la and _isdigit(a[ptr1]):
                ptr1 += 1
            while ptr2 < lb and _isdigit(b[ptr2]):
                ptr2 += 1
            isnum = True
        else:
            while ptr1 < la and _isalpha(a[ptr1]):
                ptr1 += 1
            while ptr2 < lb and _isalpha(b[ptr2]):
                ptr2 += 1
            isnum = False
        if one == ptr1:
            return -1  # unreachable in practice; the C code's arbitrary answer
        if two == ptr2:
            return 1 if isnum else -1
        seg1, seg2 = a[one:ptr1], b[two:ptr2]
        if isnum:
            seg1 = seg1.lstrip("0")
            seg2 = seg2.lstrip("0")
            if len(seg1) != len(seg2):
                return 1 if len(seg1) > len(seg2) else -1
        if seg1 != seg2:
            return -1 if seg1 < seg2 else 1
        one, two = ptr1, ptr2
    if one >= la and two >= lb:
        return 0
    rest1 = a[one] if one < la else ""
    rest2 = b[two] if two < lb else ""
    if (not rest1 and not _isalpha(rest2)) or _isalpha(rest1):
        return -1
    return 1


def _isdigit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _isalpha(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _isalnum(ch: str) -> bool:
    return _isdigit(ch) or _isalpha(ch)


def _parse_evr(evr: str) -> tuple[str, str, str | None]:
    """``epoch:version-release`` as pacman's ``parseEVR`` splits it: the
    epoch is the leading digits before a ``:`` (else ``0``), the release
    follows the LAST ``-`` after the epoch."""
    s = 0
    while s < len(evr) and _isdigit(evr[s]):
        s += 1
    # `se = strrchr(s, '-')`: the last '-' at or after the epoch terminator.
    dash = evr.rfind("-", s)
    if s < len(evr) and evr[s] == ":":
        epoch = evr[:s] or "0"
        start = s + 1
    else:
        epoch = "0"
        start = 0
    if dash == -1:
        return epoch, evr[start:], None
    return epoch, evr[start:dash], evr[dash + 1:]


def vercmp(a: str, b: str) -> int:
    """``alpm_pkg_vercmp``: -1, 0 or 1. Releases are compared only when
    both versions carry one (``1.5`` equals ``1.5-1``)."""
    if a == b:
        return 0
    e1, v1, r1 = _parse_evr(a)
    e2, v2, r2 = _parse_evr(b)
    ret = _rpmvercmp(e1, e2)
    if ret == 0:
        ret = _rpmvercmp(v1, v2)
        if ret == 0 and r1 is not None and r2 is not None:
            ret = _rpmvercmp(r1, r2)
    return ret


def _version_holds(value: str, match: str) -> bool:
    clauses = _version_clauses(match)
    if clauses is None or not value or value in (NOT_INSTALLED, MISSING):
        return False
    for op, wanted in clauses:
        c = vercmp(value, wanted)
        ok = {
            ">=": c >= 0, ">": c > 0, "<=": c <= 0, "<": c < 0, "==": c == 0, "!=": c != 0,
        }[op]
        if not ok:
            return False
    return True


# ------------------------------------------------------------------ runner


@dataclass(frozen=True)
class CommandResult:
    """What a command runner returns: the exit status and raw output."""

    returncode: int
    stdout: bytes
    stderr: bytes


#: ``runner(argv, env, timeout) -> CommandResult``. May raise
#: :class:`subprocess.TimeoutExpired` or :class:`OSError`; either makes
#: the probe ``unavailable``. Tests inject one; the default runs the
#: command through :func:`procs.run_bounded`.
CommandRunner = Callable[[list[str], dict[str, str], float], CommandResult]


def default_runner(argv: list[str], env: dict[str, str], timeout: float) -> CommandResult:
    """Run *argv* with stdin ``/dev/null`` (``run_bounded`` passes
    ``DEVNULL`` when there is no input), cwd ``/``, the given environment,
    and the process group killed at *timeout*."""
    proc = procs.run_bounded(argv, timeout=timeout, cwd="/", env=env, binary=True)
    return CommandResult(proc.returncode, proc.stdout or b"", proc.stderr or b"")


def _process_path() -> str:
    return os.environ.get("PATH") or os.defpath


def _process_home() -> Path:
    return Path(os.path.expanduser("~"))


@dataclass(frozen=True)
class ProbeEnv:
    """Everything a probe reads from outside its own fields.

    ``home``: what ``~/`` means. ``path_env``: the ``PATH`` the three
    programs and ``which`` are resolved on. ``runner``: the command runner.
    ``ledger_home``: the ledger ``ledger`` probes read (``None``: those
    probes are unavailable). ``runtime_dir``: ``XDG_RUNTIME_DIR`` for
    ``systemctl --user``. ``timeout``: per-probe bound in seconds, capped
    at :data:`PROBE_TIMEOUT`. ``now``: the clock observations are stamped
    with."""

    home: Path = field(default_factory=_process_home)
    path_env: str = field(default_factory=_process_path)
    runner: CommandRunner = default_runner
    ledger_home: Path | None = None
    runtime_dir: str | None = field(default_factory=lambda: os.environ.get("XDG_RUNTIME_DIR"))
    timeout: float = PROBE_TIMEOUT
    now: Callable[[], str] = chrono.now_iso

    def bounded_timeout(self) -> float:
        try:
            wanted = float(self.timeout)
        except (TypeError, ValueError):
            return PROBE_TIMEOUT
        if wanted != wanted or wanted <= 0:  # NaN or non-positive
            return PROBE_TIMEOUT
        return min(wanted, PROBE_TIMEOUT)


def _child_env(env: ProbeEnv) -> dict[str, str]:
    """The whole environment a probe command gets. Nothing is inherited:
    no ``DBUS_SESSION_BUS_ADDRESS``, ``DISPLAY``, ``WAYLAND_DISPLAY``,
    ``SSH_AUTH_SOCK``, ``SUDO_*`` or token variables reach the child."""
    out = {
        "PATH": env.path_env,
        "HOME": str(env.home),
        "LC_ALL": "C",
        "LANG": "C",
        "NO_COLOR": "1",
        "SYSTEMD_COLORS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if env.runtime_dir and env.runtime_dir.startswith("/") and env.runtime_dir.isprintable():
        out["XDG_RUNTIME_DIR"] = env.runtime_dir
    return out


#: The only programs a probe ever runs, by bare name on ``PATH``.
ALLOWED_PROGRAMS = frozenset({"systemctl", "pacman", "git"})


def _systemctl_argv(scope: str, unit: str, prop: str) -> list[str]:
    return [
        "systemctl", "--user" if scope == "user" else "--system", "show",
        "--no-pager", "--no-ask-password", "--property", prop, "--value", "--", unit,
    ]


def _pacman_argv(name: str) -> list[str]:
    return ["pacman", "-Q", "--", name]


def _git_argv(repo: str, path: str) -> list[str]:
    return [
        "git", "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false",
        "-C", repo, "cat-file", "blob", f"HEAD:{path}",
    ]


def _check_argv(argv: Sequence[str]) -> None:
    """Refuse every argv that is not exactly one of the three catalog
    shapes. This is the gate; argv builders above are only conveniences.
    Raises :class:`ProbeRefused`, so nothing outside the catalog -- a
    ``systemctl start``, a ``sudo``, a ``busctl call``, a ``git fetch`` --
    can reach any runner, injected or not."""
    args = list(argv)
    if not args or not all(isinstance(a, str) for a in args):
        raise ProbeRefused("a probe command must be a non-empty list of strings")
    if any("\0" in a or "\n" in a for a in args):
        raise ProbeRefused("a probe command may not hold NUL or newline characters")
    program = args[0]
    if program not in ALLOWED_PROGRAMS:
        raise ProbeRefused(
            f"{program!r} is not a probe program (allowed: {sorted(ALLOWED_PROGRAMS)})"
        )
    if program == "systemctl":
        ok = (
            len(args) == 10
            and args[1] in ("--user", "--system")
            and args[2] == "show"
            and args[3:6] == ["--no-pager", "--no-ask-password", "--property"]
            and bool(_PROPERTY_RE.match(args[6]))
            and args[7:9] == ["--value", "--"]
            and bool(_UNIT_RE.match(args[9]))
        )
    elif program == "pacman":
        ok = (
            len(args) == 4
            and args[1:3] == ["-Q", "--"]
            and bool(_PACKAGE_RE.match(args[3]))
        )
    else:  # git
        ok = (
            len(args) == 10
            and args[1:5] == ["--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false"]
            and args[5] == "-C"
            and args[6].startswith("/")
            and args[7:9] == ["cat-file", "blob"]
            and args[9].startswith("HEAD:")
            and _repo_relative_problem(args[9][len("HEAD:"):], "path") is None
        )
    if not ok:
        raise ProbeRefused(f"{program} argv is not the catalog's read-only shape: {args!r}")


def _run_command(argv: list[str], env: ProbeEnv) -> CommandResult | str:
    """Gate, then run. Returns the result, or an ``unavailable`` reason
    (timeout, missing program, output over :data:`READ_LIMIT`). A refused
    argv raises :class:`ProbeRefused` before the runner is touched."""
    _check_argv(argv)
    try:
        result = env.runner(list(argv), _child_env(env), env.bounded_timeout())
    except subprocess.TimeoutExpired:
        return "timed out"
    except FileNotFoundError:
        return f"{argv[0]} is not installed"
    except OSError as exc:
        return f"{argv[0]} could not run ({type(exc).__name__})"
    if len(result.stdout) > READ_LIMIT:
        return "output too large"
    return result


# ---------------------------------------------------------- normalization


def normalize_value(text: str) -> str:
    """The canonical text a value is hashed from: CRLF as LF, trailing
    whitespace off each line, blank lines off both ends. A value that
    differs only in those ways is the same observation."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def value_sha(value: str) -> str:
    """The stored hash of a normalized value (see :data:`VALUE_SHA_CHARS`)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:VALUE_SHA_CHARS]


def _shown(value: str) -> str:
    """The value itself when it is short, one printable line and
    scan-clean; otherwise the empty string (the hash still records it)."""
    if not value or len(value) > SHOWN_LIMIT or not value.isprintable():
        return ""
    if scan.scan(value):
        return ""
    return value


class _Budget(Exception):
    pass


def _canonical(value: Any) -> str:
    """Sorted-key compact JSON with a node and depth budget; dates as ISO
    text. Raises :class:`_Budget` past the budget."""
    count = [0]

    def walk(node: Any, depth: int) -> Any:
        count[0] += 1
        if count[0] > _CANON_NODE_BUDGET or depth > _CANON_DEPTH_LIMIT:
            raise _Budget()
        if isinstance(node, Mapping):
            return {str(k): walk(v, depth + 1) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [walk(v, depth + 1) for v in node]
        if isinstance(node, bool) or node is None:
            return node
        if isinstance(node, (datetime, date)):
            return _plain(node)
        if isinstance(node, str):
            return str(node)
        if isinstance(node, int):
            return int(node)
        if isinstance(node, float):
            return float(node)
        return str(node)

    return json.dumps(walk(value, 0), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ----------------------------------------------------------- the executors


@dataclass(frozen=True)
class _Unavailable:
    reason: str


def _read_file(path: str, env: ProbeEnv) -> bytes | _Unavailable | None:
    """The bytes of a regular file, ``None`` when it does not exist, or
    ``_Unavailable``. The resolved path is checked against the credential
    rules again (a symlink can point anywhere); FIFOs, devices and
    directories are refused without blocking; a file over
    :data:`READ_LIMIT` is unavailable rather than half-read."""
    expanded = _expand(path, env.home)
    try:
        real = os.path.realpath(expanded, strict=True)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        return _Unavailable(f"cannot resolve the path ({type(exc).__name__})")
    problem = credential_path_problem(real, reads_content=True)
    if problem is not None:
        return _Unavailable(f"the path resolves to a refused location: {problem}")
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(real, flags)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        return _Unavailable(f"cannot open the file ({type(exc).__name__})")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return _Unavailable("not a regular file")
        if st.st_size > READ_LIMIT:
            return _Unavailable("file larger than the read limit")
        chunks: list[bytes] = []
        total = 0
        while total <= READ_LIMIT:
            chunk = os.read(fd, min(65536, READ_LIMIT + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > READ_LIMIT:
            return _Unavailable("file larger than the read limit")
        return b"".join(chunks)
    except OSError as exc:
        return _Unavailable(f"cannot read the file ({type(exc).__name__})")
    finally:
        os.close(fd)


def _match_bytes(data: bytes, probe: Mapping) -> str:
    """``present``/``absent`` for ``contains``/``line``; for ``lines``, a
    hash of that line range (or ``out-of-range``). Never the text."""
    if "contains" in probe:
        return PRESENT if str(probe["contains"]).encode("utf-8") in data else ABSENT
    lines = [ln[:-1] if ln.endswith(b"\r") else ln for ln in data.split(b"\n")]
    if "line" in probe:
        wanted = str(probe["line"]).strip().encode("utf-8")
        return PRESENT if any(ln.strip() == wanted for ln in lines) else ABSENT
    span = _line_span(probe["lines"])
    assert span is not None  # validated
    first, last = span
    if data.endswith(b"\n"):
        lines = lines[:-1]
    if last > len(lines):
        return OUT_OF_RANGE
    digest = hashlib.sha256(b"\n".join(lines[first - 1:last])).hexdigest()
    return "sha256:" + digest[:VALUE_SHA_CHARS]


def _probe_path(probe: Mapping, env: ProbeEnv) -> str | _Unavailable:
    expanded = _expand(str(probe["path"]), env.home)
    try:
        st = os.lstat(expanded)
    except (FileNotFoundError, NotADirectoryError):
        return MISSING
    except OSError as exc:
        return _Unavailable(f"cannot stat the path ({type(exc).__name__})")
    if stat.S_ISLNK(st.st_mode):
        try:
            return "symlink:" + os.readlink(expanded)
        except OSError as exc:
            return _Unavailable(f"cannot read the link ({type(exc).__name__})")
    if stat.S_ISREG(st.st_mode):
        return "file"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    return "other"


def _probe_file_match(probe: Mapping, env: ProbeEnv) -> str | _Unavailable:
    data = _read_file(str(probe["path"]), env)
    if data is None:
        return MISSING
    if isinstance(data, _Unavailable):
        return data
    return _match_bytes(data, probe)


def _walk_key(doc: Any, key: list[str | int]) -> tuple[bool, Any]:
    node = doc
    for part in key:
        if isinstance(node, Mapping):
            name = str(part)
            if name not in node:
                return False, None
            node = node[name]
        elif isinstance(node, list) and not isinstance(node, str):
            try:
                index = int(part)
            except (TypeError, ValueError):
                return False, None
            if not 0 <= index < len(node):
                return False, None
            node = node[index]
        else:
            return False, None
    return True, node


def _probe_key(probe: Mapping, env: ProbeEnv) -> str | _Unavailable:
    data = _read_file(str(probe["path"]), env)
    if data is None:
        return MISSING
    if isinstance(data, _Unavailable):
        return data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _Unavailable("the file is not UTF-8 text")
    kind = probe["kind"]
    try:
        if kind == "json-key":
            doc = json.loads(text)
        elif kind == "toml-key":
            doc = tomllib.loads(text)
        else:
            from ruamel.yaml import YAML  # the safe loader: no tags, no objects

            doc = YAML(typ="safe", pure=True).load(text)
    except RecursionError:
        return _Unavailable("the file nests too deeply to parse")
    except Exception as exc:  # noqa: BLE001 -- any parse failure is the same answer
        return _Unavailable(f"the file does not parse ({type(exc).__name__})")
    key = _key_path(probe["key"])
    assert key is not None  # validated
    found, node = _walk_key(doc, key)
    if not found:
        return MISSING_KEY
    try:
        return _canonical(node)
    except (_Budget, RecursionError):
        return _Unavailable("the value is too large to compare")


def _probe_systemd(probe: Mapping, env: ProbeEnv) -> str | _Unavailable:
    argv = _systemctl_argv(str(probe["scope"]), str(probe["unit"]), str(probe["property"]))
    result = _run_command(argv, env)
    if isinstance(result, str):
        return _Unavailable(result)
    if result.returncode != 0:
        return _Unavailable(f"systemctl exited {result.returncode}")
    return result.stdout.decode("utf-8", errors="replace")


def _probe_package(probe: Mapping, env: ProbeEnv) -> str | _Unavailable:
    name = str(probe["name"])
    result = _run_command(_pacman_argv(name), env)
    if isinstance(result, str):
        return _Unavailable(result)
    out = result.stdout.decode("utf-8", errors="replace").strip()
    err = result.stderr.decode("utf-8", errors="replace")
    if result.returncode == 1 and "was not found" in err:
        return NOT_INSTALLED
    if result.returncode != 0:
        return _Unavailable(f"pacman exited {result.returncode}")
    fields = out.split()
    if len(fields) != 2 or fields[0] != name:
        return _Unavailable("pacman printed something other than '<name> <version>'")
    return fields[1]


def _probe_which(probe: Mapping, env: ProbeEnv) -> str | _Unavailable:
    found = shutil.which(str(probe["name"]), path=env.path_env)
    return found if found else NOT_FOUND


def _probe_git_file(probe: Mapping, env: ProbeEnv) -> str | _Unavailable:
    repo = _expand(str(probe["repo"]), env.home)
    try:
        real_repo = os.path.realpath(repo, strict=True)
    except OSError:
        return _Unavailable("the repository path does not resolve")
    problem = credential_path_problem(real_repo, reads_content=True)
    if problem is not None:
        return _Unavailable(f"the repository resolves to a refused location: {problem}")
    result = _run_command(_git_argv(real_repo, str(probe["path"])), env)
    if isinstance(result, str):
        return _Unavailable(result)
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        if "does not exist in 'HEAD'" in err or "but not in 'HEAD'" in err:
            return MISSING
        return _Unavailable(f"git exited {result.returncode}")
    return _match_bytes(result.stdout, probe)


def _probe_ledger(probe: Mapping, env: ProbeEnv) -> str | _Unavailable:
    if env.ledger_home is None:
        return _Unavailable("no ledger to read")
    target = str(probe["target"])
    if _STMT_ID_RE.match(target):
        from . import statements

        try:
            rows = statements.list_statements(env.ledger_home)
        except (OSError, ValueError) as exc:
            return _Unavailable(f"cannot read the statements ({type(exc).__name__})")
        if not any(isinstance(r, Mapping) and r.get("id") == target for r in rows):
            return NOT_FOUND
        amended = sorted(
            str(r.get("id")) for r in rows if isinstance(r, Mapping) and r.get("amends") == target
        )
        return "amended-by:" + ",".join(amended) if amended else "current"
    from . import ledger_ops
    from .records import Record, RecordError

    try:
        path = ledger_ops.find_record_path(env.ledger_home, target)
    except ledger_ops.RecordNotFound:
        return NOT_FOUND
    except (ledger_ops.LedgerOpsError, OSError) as exc:
        return _Unavailable(f"cannot find the lesson ({type(exc).__name__})")
    try:
        record = Record.from_path(path)
    except (RecordError, OSError, UnicodeDecodeError) as exc:
        return _Unavailable(f"cannot read the lesson ({type(exc).__name__})")
    if probe.get("field", "status") == "follow_up":
        if record.follow_up is not None:
            return "open"
        done = record.follow_up_done
        if done is not None:
            return f"done:{_plain(done.get('done_at'))}"
        return "none"
    if record.status == "superseded":
        return f"superseded:{record.superseded_by}"
    return str(record.status)


_EXECUTORS: dict[str, Callable[[Mapping, ProbeEnv], str | _Unavailable]] = {
    "path": _probe_path,
    "file-match": _probe_file_match,
    "json-key": _probe_key,
    "yaml-key": _probe_key,
    "toml-key": _probe_key,
    "systemd-show": _probe_systemd,
    "package": _probe_package,
    "which": _probe_which,
    "git-file": _probe_git_file,
    "ledger": _probe_ledger,
}


# ------------------------------------------------------------ observations


@dataclass(frozen=True)
class Observation:
    """One probe run, as it may be kept: a value hash and a short display
    string, never the value's text. ``state`` is :data:`OBS_OK` or
    :data:`OBS_UNAVAILABLE`; ``claim`` is the premise's ``holds_if``
    judged against the value (:data:`CLAIM_UNJUDGED` with no
    ``holds_if``, or when unavailable); ``reason`` says why a probe was
    unavailable."""

    state: str
    value_sha: str | None
    shown: str
    claim: str
    reason: str
    observed_at: str

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "value_sha": self.value_sha,
            "shown": self.shown,
            "claim": self.claim,
            "reason": self.reason,
            "observed_at": self.observed_at,
        }


def unavailable_observation(reason: str, *, observed_at: str | None = None) -> Observation:
    """An observation that could not be made (U8's ``unmeasurable`` too)."""
    return Observation(
        state=OBS_UNAVAILABLE, value_sha=None, shown="", claim=CLAIM_UNJUDGED,
        reason=reason or "unavailable", observed_at=observed_at or chrono.now_iso(),
    )


def _judge(premise: Mapping | None, value: str) -> str:
    if premise is None:
        return CLAIM_UNJUDGED
    holds_if = premise.get("holds_if")
    match = premise.get("match")
    if holds_if is None or not isinstance(match, str):
        return CLAIM_UNJUDGED
    if holds_if == "present":
        ok = match in value
    elif holds_if == "absent":
        ok = match not in value
    elif holds_if == "equals":
        ok = value == match
    elif holds_if == "not-equals":
        ok = value != match
    elif holds_if == "version-range":
        ok = _version_holds(value, match)
    else:
        return CLAIM_UNJUDGED
    return CLAIM_HOLDS if ok else CLAIM_CONTRADICTED


def observation_from_value(
    value: str, *, premise: Mapping | None = None, observed_at: str | None = None
) -> Observation:
    """An :data:`OBS_OK` observation of *value* (normalized here). The
    value itself is dropped once hashed; only a scan-clean short display
    string survives. U8 builds its placement observations with this."""
    norm = normalize_value(value)
    return Observation(
        state=OBS_OK, value_sha=value_sha(norm), shown=_shown(norm),
        claim=_judge(premise, norm), reason="", observed_at=observed_at or chrono.now_iso(),
    )


def run_probe(probe: Mapping, env: ProbeEnv, *, premise: Mapping | None = None) -> Observation:
    """Validate *probe* (raising :class:`PremiseError` when it is not a
    catalog probe), run it, and return the observation. Every failure to
    observe -- timeout, missing program, unreadable file, a refused argv --
    is an ``unavailable`` observation, never an exception."""
    validate_probe(probe)
    at = env.now()
    try:
        raw = _EXECUTORS[str(probe["kind"])](probe, env)
    except ProbeRefused as exc:
        return unavailable_observation(f"refused: {exc}", observed_at=at)
    except Exception as exc:  # noqa: BLE001 -- a probe never takes a sweep down
        return unavailable_observation(f"probe failed ({type(exc).__name__})", observed_at=at)
    if isinstance(raw, _Unavailable):
        return unavailable_observation(raw.reason, observed_at=at)
    return observation_from_value(raw, premise=premise, observed_at=at)


def observe(premise: Mapping, env: ProbeEnv) -> Observation | None:
    """The observation for one premise, or ``None`` for a premise with no
    probe. Total: never raises; a malformed probe is ``unavailable``."""
    probe = premise.get("probe") if isinstance(premise, Mapping) else None
    if probe is None:
        return None
    try:
        return run_probe(probe, env, premise=premise)
    except PremiseError as exc:
        return unavailable_observation(f"invalid probe: {exc}", observed_at=env.now())


def verdict(premise: Mapping, observation: Observation | None) -> str:
    """Compare one observation with the premise's baseline, edge-only:

    - no probe -> ``no-probe``;
    - the probe could not observe -> ``unavailable`` -- NEVER ``holds``
      and never ``moved`` (fail-closed: a broken probe is neither a
      confirmation nor a trigger);
    - no baseline recorded yet -> ``no-baseline``;
    - the value hash differs from the baseline's -> ``moved``;
    - otherwise ``holds``.

    Whether the claim itself holds against the value is the
    observation's ``claim`` and the baseline's ``state``; the trigger is
    the change (design D7.1). Stability across sweeps (D7.2) is the
    sweep's job (U2), not this single comparison's."""
    if premise.get("probe") is None:
        return VERDICT_NO_PROBE
    if observation is None or observation.state != OBS_OK or not observation.value_sha:
        return VERDICT_UNAVAILABLE
    baseline = premise.get("baseline")
    if not isinstance(baseline, Mapping) or not baseline.get("value_sha"):
        return VERDICT_NO_BASELINE
    if observation.value_sha != baseline.get("value_sha"):
        return VERDICT_MOVED
    return VERDICT_HOLDS


def make_baseline(observation: Observation) -> dict:
    """The ``baseline`` mapping to record from an observation. An
    unavailable observation has nothing to record and is refused: a
    baseline is a value seen, never a guess."""
    if observation.state != OBS_OK or not observation.value_sha:
        raise PremiseError(
            f"cannot record a baseline from an unavailable observation ({observation.reason})"
        )
    state = {
        CLAIM_HOLDS: "holds",
        CLAIM_CONTRADICTED: "contradicts-claim",
    }.get(observation.claim, "recorded")
    return {
        "value_sha": observation.value_sha,
        "shown": observation.shown,
        "observed_at": observation.observed_at,
        "state": state,
    }


@dataclass(frozen=True)
class PremiseCheck:
    """One premise of one lesson, checked now: what ``premises check``
    (U2) prints and the sweep (U2) compares across days."""

    record_id: str
    premise_id: str
    claim: str
    verdict: str
    observation: Observation | None
    baseline: dict | None
    on_change: str

    def as_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "premise_id": self.premise_id,
            "claim": self.claim,
            "verdict": self.verdict,
            "observation": self.observation.as_dict() if self.observation else None,
            "baseline": self.baseline,
            "on_change": self.on_change,
        }


def check_record(record: Any, env: ProbeEnv) -> list[PremiseCheck]:
    """Run every probe of one record's premises (its ``premises``
    property) and judge each against its baseline. Read-only; never
    raises for a probe's sake."""
    out: list[PremiseCheck] = []
    for premise in record.premises or []:
        observation = observe(premise, env)
        baseline = premise.get("baseline")
        out.append(
            PremiseCheck(
                record_id=str(record.id),
                premise_id=str(premise.get("id")),
                claim=str(premise.get("claim")),
                verdict=verdict(premise, observation),
                observation=observation,
                baseline=dict(baseline) if isinstance(baseline, Mapping) else None,
                on_change=str(premise.get("on_change") or "re-decide"),
            )
        )
    return out
