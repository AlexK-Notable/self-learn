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

__all__ = ["CONFIG_BASENAME", "config_path", "one_motion_enabled"]

CONFIG_BASENAME = "config.yaml"

#: The section gating S-10's one-motion path for the M3 destinations.
ONE_MOTION_SECTION = "one_motion_route"


def config_path(home: Path | str) -> Path:
    return Path(home) / CONFIG_BASENAME


def _warn(message: str) -> None:
    print(f"self-learn: config.yaml ignored — {message}", file=sys.stderr)


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
