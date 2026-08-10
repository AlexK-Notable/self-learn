"""Operator policy config (S-10 amendment 2026-07-16): ``<home>/config.yaml``.

One file, one concern: policy knobs the OPERATOR sets by hand and commits
in the ledger repo. It is deliberately NOT hosts.yaml — that file is the
H-3 compile-target registry with a verb-managed write discipline ("never
a hand edit the compilers trust blindly"), and its failure mode is
canon-written-to-the-wrong-place. This file's failure mode is the safe
direction by construction: **every parse is fail-closed** — a missing
file, a malformed file, a wrong shape, or any value that is not the YAML
boolean ``true`` all read as "not enabled", and the pre-M3 review-gated
default stands. That asymmetry is why a hand-edited policy file is
acceptable here where it is not for hosts.yaml.

Why a committed file and not an env var (the user's 2026-07-16 ruling,
recorded at S-10): a setting that changes what executable code the CLI
may auto-commit belongs in version control — visible in the ledger's own
git history, synced to every machine, revocable by a commit — not in
ambient shell state that differs invisibly per terminal.

Current keys::

    # ~/.self-learn/config.yaml  (commit it: git -C ~/.self-learn add
    # config.yaml && git commit -m "policy: enable one-motion hook routes")
    one_motion_route:
      hook: true        # allow one-motion hook routes: `teach --route
                        #   --dest hook --hook-input …` AND a bare
                        #   `teach --route` whose analyst proposes
                        #   destination: hook (doctrine §7 — the model
                        #   authors the compile input; the CLI still
                        #   generates the script, validates, scans,
                        #   replays, and prints the applied bytes)
      new-skill: true   # allow `teach --route --dest new-skill:<name>`

ONLY the YAML 1.2 boolean ``true`` enables. Everything else refuses —
``false``, ``null``, ``"true"`` (a string), and ``yes`` in ANY spelling:
the safe loader is YAML 1.2 core schema, where bare ``yes`` is the
STRING ``"yes"``, not a boolean (verified: both ``hook: yes`` and
``hook: 'yes'`` refuse with the same WARN). Malformed values WARN on
stderr (fail-closed must not also be silent, or a typo reads as a
policy decision).
"""

from __future__ import annotations

import sys
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

__all__ = ["CONFIG_BASENAME", "config_path", "invocation_backend", "one_motion_enabled"]

CONFIG_BASENAME = "config.yaml"

#: The section gating S-10's one-motion path for the M3 destinations.
ONE_MOTION_SECTION = "one_motion_route"


def config_path(home: Path | str) -> Path:
    return Path(home) / CONFIG_BASENAME


def _warn(message: str) -> None:
    print(f"self-learn: config.yaml ignored — {message}", file=sys.stderr)


#: U-seam §3.7.1 — the two config-file rungs of the backend precedence
#: chain, keyed by surface (finer) then by the flat general key.
_INVOCATION_SECTION = "invocation"


def invocation_backend(home: Path | str, surface: str) -> tuple[str, str] | None:
    """U-seam §3.7.3 — the registry's rung-3/rung-4 config reader.
    Returns ``(key, value)`` for the FIRST present key among
    ``invocation.backend_<surface>`` (rung 3) and ``invocation.backend``
    (rung 4) -- ``key`` names the exact key that matched, so a caller
    building an operator-facing warning names the file the operator
    actually wrote, never a per-surface key that was never present
    (gate MAJOR-1: the registry used to hardcode ``backend_<surface>``
    regardless of which rung answered). ``value`` may be ``""`` (`R-a`:
    an empty string is a valid match -- "no answer", not an unknown
    value -- the caller decides whether to fall through). ``None`` only
    when neither key is present, or upstream discipline already fired.
    Follows :func:`one_motion_enabled`'s discipline case for case:
    missing file -> ``None`` silent; empty file (YAML loads to ``None``)
    -> ``None`` silent; unparseable -> ``_warn`` + ``None``; non-mapping
    top level -> ``_warn`` + ``None``; ``invocation`` section absent ->
    ``None`` silent; ``invocation`` section present but not a mapping ->
    ``_warn`` + ``None``; value present but not a ``str`` -> ``_warn`` +
    ``None``. Does NOT validate the value against the known backend
    names — that judgement, and its warning, belong to the registry
    (`R-c`), so there is one place where "unknown means cli" is
    decided."""
    path = config_path(home)
    if not path.is_file():
        return None
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        _warn(f"unparseable ({exc}); invocation backend selection ignored")
        return None
    if data is None:
        return None
    if not isinstance(data, dict):
        _warn(
            f"top level must be a mapping, got {type(data).__name__}; "
            "invocation backend selection ignored"
        )
        return None
    section = data.get(_INVOCATION_SECTION)
    if section is None:
        return None
    if not isinstance(section, dict):
        _warn(
            f"{_INVOCATION_SECTION} must be a mapping, got {section!r}; "
            "invocation backend selection ignored"
        )
        return None
    for key in (f"backend_{surface}", "backend"):
        if key not in section:
            continue
        value = section[key]
        if not isinstance(value, str):
            _warn(
                f"{_INVOCATION_SECTION}.{key} must be a string, got {value!r}; "
                "invocation backend selection ignored"
            )
            return None
        return (key, value)
    return None


def one_motion_enabled(home: Path | str, destination: str) -> bool:
    """True iff ``config.yaml`` explicitly enables one-motion routing for
    ``destination`` with the YAML boolean ``true``. FAIL-CLOSED on every
    other input; malformed shapes warn on stderr so a typo never passes
    silently as a policy decision."""
    path = config_path(home)
    if not path.is_file():
        return False  # no config = the default posture; silent
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        _warn(f"unparseable ({exc}); one-motion routes stay review-gated")
        return False
    if data is None:
        return False
    if not isinstance(data, dict):
        _warn(
            f"top level must be a mapping, got {type(data).__name__}; "
            "one-motion routes stay review-gated"
        )
        return False
    section = data.get(ONE_MOTION_SECTION)
    if section is None:
        return False
    if not isinstance(section, dict):
        _warn(
            f"{ONE_MOTION_SECTION} must be a mapping of destination → "
            f"boolean, got {section!r}; one-motion routes stay review-gated"
        )
        return False
    value = section.get(destination)
    if value is None or value is False:
        return False
    if value is True:
        return True
    _warn(
        f"{ONE_MOTION_SECTION}.{destination} must be the YAML boolean "
        f"true, got {value!r}; staying review-gated"
    )
    return False
