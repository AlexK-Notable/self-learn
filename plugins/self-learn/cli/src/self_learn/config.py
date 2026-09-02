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

import io
import sys
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

__all__ = [
    "CONFIG_BASENAME",
    "PROVIDER_KEYS",
    "ConfigWriteError",
    "config_path",
    "dump_editable",
    "effective_default_mode",
    "invocation_backend",
    "load_editable",
    "one_motion_enabled",
    "present",
    "provider_setting",
    "provider_unknown_keys",
    "set_leaf",
    "settings_leaf",
    "settings_unknown_keys",
    "unset_leaf",
]

CONFIG_BASENAME = "config.yaml"

#: The section gating S-10's one-motion path for the M3 destinations.
ONE_MOTION_SECTION = "one_motion_route"

#: U-hostmode §4.2: the section carrying the default mode for newly
#: registered hosts.
HOSTS_SECTION = "hosts"

#: U-bedrock `Key-1` -- the closed, whitelisted provider config key set.
#: Every value here is a NON-SECRET (`K-a`): a region name, a profile
#: NAME, and model ids are all safe to commit. There is deliberately no
#: key for an access key, a secret key, a session token, a bearer token,
#: or any credential file's contents.
PROVIDER_KEYS = (
    "name",
    "bedrock.region",
    "bedrock.profile",
    "bedrock.models.worker",
    "bedrock.models.miner",
    "bedrock.models.analyst",
    "bedrock.models.small_fast",
)

_PROVIDER_SECTION = "provider"


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


def provider_setting(home: Path | str, key: str) -> tuple[str, str] | None:
    """U-bedrock `Key-1`/`K-b` -- one reader over the `provider:` section,
    walking the dotted path of a `PROVIDER_KEYS` member. `key` outside
    `PROVIDER_KEYS` is a PROGRAMMING error and raises `ValueError` (never
    operator input). Follows :func:`invocation_backend`'s discipline case
    for case; the returned first element is `key` itself, verbatim, so a
    caller can build its own `"config:provider.{key}"` source string.
    Does NOT validate the value against `PROVIDERS` or any model-id shape
    -- those judgements belong to `provider.py` and the doctor."""
    if key not in PROVIDER_KEYS:
        raise ValueError(f"provider_setting: {key!r} is not in PROVIDER_KEYS")
    path = config_path(home)
    if not path.is_file():
        return None
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        _warn(f"unparseable ({exc}); provider.{key} ignored")
        return None
    if data is None:
        return None
    if not isinstance(data, dict):
        _warn(
            f"top level must be a mapping, got {type(data).__name__}; "
            f"provider.{key} ignored"
        )
        return None
    section = data.get(_PROVIDER_SECTION)
    if section is None:
        return None

    segments = key.split(".")
    node: object = section
    path_so_far = _PROVIDER_SECTION
    for segment in segments[:-1]:
        if not isinstance(node, dict):
            _warn(f"{path_so_far} must be a mapping, got {node!r}; provider.{key} ignored")
            return None
        path_so_far = f"{path_so_far}.{segment}"
        if segment not in node:
            return None
        node = node[segment]

    if not isinstance(node, dict):
        _warn(f"{path_so_far} must be a mapping, got {node!r}; provider.{key} ignored")
        return None
    leaf = segments[-1]
    if leaf not in node:
        return None
    value = node[leaf]
    if not isinstance(value, str):
        _warn(f"provider.{key} must be a string, got {value!r}; ignored")
        return None
    return (key, value)


def _collect_leaf_paths(node: object, prefix: str, out: set) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if not isinstance(k, str):
                continue
            child_prefix = f"{prefix}.{k}" if prefix else k
            _collect_leaf_paths(v, child_prefix, out)
    elif prefix:
        out.add(prefix)


def provider_unknown_keys(home: Path | str) -> list[str]:
    """U-bedrock `K-c` -- the sorted dotted paths present under
    `provider:` that are NOT in `PROVIDER_KEYS`, ignoring nothing. Never
    warns by itself (`K-c`); the doctor renders one WARN row from this
    list."""
    path = config_path(home)
    if not path.is_file():
        return []
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError):
        return []
    if data is None or not isinstance(data, dict):
        return []
    section = data.get(_PROVIDER_SECTION)
    if section is None or not isinstance(section, dict):
        return []
    found: set = set()
    _collect_leaf_paths(section, "", found)
    return sorted(p for p in found if p not in PROVIDER_KEYS)


# ===================================================================== #
# U-settings Phase 1 -- the settings registry's TWO generic primitives.
# `provider_setting`/`provider_unknown_keys` above are scoped to the one
# `provider:` section and its `PROVIDER_KEYS` whitelist; `settings.py`
# needs the SAME fail-closed discipline over an arbitrary section (one
# per settings-registry domain: `worker:`, `miner:`, `analyst:`, `sdk:`,
# `serve:`, `ledger:`) -- generalizing the pattern rather than growing a
# second one, per doctrine (settings-surface-spec's reframe). Neither
# function below changes anything above; both are strictly additive.
# ===================================================================== #


def settings_leaf(home: Path | str, section: str, key: str) -> tuple[str, object] | None:
    """The settings-registry's one generic config.yaml reader. Walks the
    dotted `key` under top-level `section`, returning `(key, raw_value)`
    for the leaf when present -- `raw_value` is whatever native YAML
    scalar the operator wrote (`str`/`int`/`float`/`bool`), UNVALIDATED
    against any expected type; that judgement belongs to the registry's
    own parser (mirrors `provider_setting`'s division of labor, `K-b`).

    Same fail-closed discipline as every reader above, generalized over
    `section`: missing file -> `None` silent; empty file -> `None`
    silent; unparseable file, non-mapping top level, `section` absent,
    or a non-mapping node encountered while walking `key`'s dotted path
    -> `_warn` (except `section` absent, which is silent -- an operator
    who has not written that section yet is not misusing config.yaml)
    + `None`; `key` (or a segment of it) absent -> `None` silent."""
    path = config_path(home)
    if not path.is_file():
        return None
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        _warn(f"unparseable ({exc}); {section}.{key} ignored")
        return None
    if data is None:
        return None
    if not isinstance(data, dict):
        _warn(
            f"top level must be a mapping, got {type(data).__name__}; "
            f"{section}.{key} ignored"
        )
        return None
    node: object = data.get(section)
    if node is None:
        return None

    segments = key.split(".")
    path_so_far = section
    for segment in segments[:-1]:
        if not isinstance(node, dict):
            _warn(f"{path_so_far} must be a mapping, got {node!r}; {section}.{key} ignored")
            return None
        path_so_far = f"{path_so_far}.{segment}"
        if segment not in node:
            return None
        node = node[segment]

    if not isinstance(node, dict):
        _warn(f"{path_so_far} must be a mapping, got {node!r}; {section}.{key} ignored")
        return None
    leaf = segments[-1]
    if leaf not in node:
        return None
    return (key, node[leaf])


def settings_unknown_keys(home: Path | str, section: str, known_keys: frozenset) -> list[str]:
    """The settings-registry's per-section unknown-key sweep -- same
    shape as :func:`provider_unknown_keys` (`K-c`): the sorted dotted
    paths present under top-level `section` that are NOT in
    `known_keys`. Never warns by itself; the doctor renders one WARN row
    per section from this list."""
    path = config_path(home)
    if not path.is_file():
        return []
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError):
        return []
    if data is None or not isinstance(data, dict):
        return []
    node = data.get(section)
    if node is None or not isinstance(node, dict):
        return []
    found: set = set()
    _collect_leaf_paths(node, "", found)
    return sorted(p for p in found if p not in known_keys)


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


def effective_default_mode(home: Path | str) -> str:
    """U-hostmode MODE3: the default ``mode`` for a NEWLY registered host
    (``host add`` with no explicit ``--mode``), from ``<home>/config.yaml``
    ``hosts.default_mode``. Same fail-closed discipline as
    :func:`one_motion_enabled` — S-10's precedent carried over verbatim:
    only the literal YAML string ``"plain"`` enables plain mode. Every
    other shape — missing file, unparseable, non-mapping top level,
    non-mapping section, a missing key, or any value that is not exactly
    ``"plain"`` or ``"git"`` — reads as ``"git"``; a PRESENT but wrong
    value warns on stderr (a typo must never silently become a policy
    decision)."""
    path = config_path(home)
    if not path.is_file():
        return "git"
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        _warn(f"unparseable ({exc}); hosts default to git mode")
        return "git"
    if data is None:
        return "git"
    if not isinstance(data, dict):
        _warn(
            f"top level must be a mapping, got {type(data).__name__}; "
            "hosts default to git mode"
        )
        return "git"
    section = data.get(HOSTS_SECTION)
    if section is None:
        return "git"
    if not isinstance(section, dict):
        _warn(
            f"{HOSTS_SECTION} must be a mapping, got {section!r}; hosts "
            "default to git mode"
        )
        return "git"
    value = section.get("default_mode")
    if value is None:
        return "git"
    if value == "plain":
        return "plain"
    if value == "git":
        return "git"
    _warn(
        f"{HOSTS_SECTION}.default_mode must be the literal string "
        f"'plain' or 'git', got {value!r}; defaulting to git"
    )
    return "git"


# ===================================================================== #
# U-settings Phase 2 -- the settings page's WRITE path. Every reader
# above (`settings_leaf` included) loads with `YAML(typ="safe")`: that
# stays the security boundary, strict, no arbitrary tag construction
# (this file's own module docstring). A WRITE needs the round-trip
# type instead, so the operator's own comments and key ordering survive
# an edit -- `hosts.py`'s `_yaml()`/`save_hosts` is the model this
# mirrors, generalized over an arbitrary section the way `settings_leaf`
# already generalizes the READ side over `provider_setting`'s one
# section.
# ===================================================================== #


class ConfigWriteError(Exception):
    """A `config.yaml` write could not proceed without either clobbering
    operator content it cannot safely merge past (a path segment that is
    already a scalar, not a mapping) or writing over a top level that
    is not a mapping at all. Never raised by a READER above -- those
    stay fail-closed-to-default; a WRITE must refuse loudly instead,
    the same asymmetry `hosts.HostsError` already draws for hosts.yaml."""


def _rt_yaml() -> YAML:
    y = YAML(typ="rt")
    y.default_flow_style = False
    return y


def load_editable(home: Path | str) -> CommentedMap:
    """Round-trip load of `config.yaml` for a WRITE. A missing file (or
    an empty one) loads as a fresh, empty mapping -- `config.yaml` is
    created on first write, same as `hosts.yaml` is not required to
    exist before `host add`'s first call. Raises :class:`ConfigWriteError`
    on a non-mapping top level (a malformed file a WRITE must not paper
    over silently, unlike the fail-closed-to-default readers above)."""
    path = config_path(home)
    if not path.is_file():
        return CommentedMap()
    try:
        data = _rt_yaml().load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        raise ConfigWriteError(f"{path} is unparseable ({exc}) -- refusing to write over it") from exc
    if data is None:
        return CommentedMap()
    if not isinstance(data, dict):
        raise ConfigWriteError(
            f"{path} must be a YAML mapping, got {type(data).__name__} -- refusing to write over it"
        )
    return data


def dump_editable(home: Path | str, data: CommentedMap) -> Path:
    """Serialize `data` back to `config.yaml`, round-trip (comments,
    key order, and every untouched key survive). Returns the path
    written -- the caller's `gitops.stage`/`commit` pathspec."""
    path = config_path(home)
    buf = io.StringIO()
    _rt_yaml().dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def _walk_leaf(
    data: CommentedMap, section: str, key: str, *, create: bool
) -> tuple[list[tuple[dict, str]], bool]:
    """The one walk-and-refuse behind `set_leaf`/`unset_leaf`/`present`
    (NIT-2, code-gate review r2 2026-09-02: three near-identical
    walkers, each with its own copy of the same "not a mapping" refusal
    under a slightly different wording, collapsed into one walker and
    one message).

    Descends `section`, then `key`'s dotted segments, through `data`.
    The instant an ALREADY-WALKED segment holds something other than a
    mapping, refuses loudly with :class:`ConfigWriteError` -- the leaf
    ITSELF is never type-checked here (overwriting, deleting, or
    reading a scalar leaf is fine; only a scalar mid-walk, blocking
    whatever comes after it, is the refusal).

    Returns `(chain, found)`: `chain[i]` is `(dict, key-within-that-
    dict)` for every segment walked, `section` first -- `chain[-1]` is
    always `(the leaf's own parent mapping, the leaf's own key)` when
    `found`, so `chain[-1][0][chain[-1][1]]` reads/writes/deletes the
    leaf directly, and a caller pruning empty maps back upward (`unset_
    leaf`) walks `chain[:-1]` in reverse.

    `create=True` (`set_leaf`'s mode): a missing OR `None`-valued
    segment (`section` included -- a bare `section:` key with no value
    parses as `None`) is (re)created as a fresh empty mapping as the
    walk passes through it, so the walk always reaches the leaf and
    `found` is always `True`. `create=False` (`unset_leaf`/`present`'s
    mode): a missing segment stops the walk early and `found` is
    `False` -- genuinely absent is not an error for either of those
    two, just "nothing (yet) to unset/read". Kept asymmetric on
    purpose: a `None`-valued MID-WALK segment under `create=False`
    still falls through to the mapping check below and refuses (same
    as this function has always done) -- only the creating mode treats
    `None` as "as good as absent"."""
    node: dict = data
    chain: list[tuple[dict, str]] = []
    segments = [section, *key.split(".")]
    path_so_far = ""
    for segment in segments[:-1]:
        path_so_far = segment if not path_so_far else f"{path_so_far}.{segment}"
        if segment not in node:
            if not create:
                return chain, False
            node[segment] = CommentedMap()
        elif create and node[segment] is None:
            node[segment] = CommentedMap()
        chain.append((node, segment))
        node = node[segment]
        if not isinstance(node, dict):
            raise ConfigWriteError(
                f"{path_so_far}: already a {type(node).__name__}, not a mapping -- "
                f"refusing to write {section}.{key} over it"
            )
    leaf = segments[-1]
    if not create and leaf not in node:
        return chain, False
    chain.append((node, leaf))
    return chain, True


def set_leaf(home: Path | str, section: str, key: str, value: object) -> Path:
    """Write `value` at `section.key` (dotted `key` walks/creates nested
    maps, e.g. `sdk`/`max_turns.worker` -> `sdk: {max_turns: {worker:
    ...}}`) preserving every other key and comment. A path segment that
    already holds a non-mapping value (e.g. `sdk: 5` in the file, mid-
    walk toward `sdk.max_turns.worker`) REFUSES with
    :class:`ConfigWriteError` rather than clobbering it -- the write-path
    counterpart to `settings_leaf`'s own "must be a mapping" warn, made
    loud instead of fail-closed-silent because a write, unlike a read,
    has no safe default to fall back to."""
    data = load_editable(home)
    chain, _found = _walk_leaf(data, section, key, create=True)
    parent, leaf = chain[-1]
    parent[leaf] = value
    return dump_editable(home, data)


def unset_leaf(home: Path | str, section: str, key: str) -> bool:
    """Remove `section.key`, pruning now-empty nested maps upward --
    including `section` itself when it becomes empty. Returns `True` iff
    something was actually removed; a section/segment that is simply
    ABSENT is a silent no-op (`False`), never an error -- `unset` of an
    already-unset key stays idempotent, same posture as `host_add`'s
    already-registered leg.

    U-settings Phase 2 code-gate MINOR-2 (review r1 2026-09-01): a
    section/mid-walk segment that IS PRESENT but not a mapping (the
    same `worker: 5` / `sdk.max_turns: 5` shapes `set_leaf` refuses)
    now RAISES :class:`ConfigWriteError` here too, instead of the old
    silent `False` -- same file, same refusal, matching `set`'s own
    posture rather than reporting "nothing to remove" against a file
    `config set` would refuse outright."""
    data = load_editable(home)
    chain, found = _walk_leaf(data, section, key, create=False)
    if not found:
        return False
    parent, leaf = chain[-1]
    del parent[leaf]
    current: dict = parent
    for ancestor, at_key in reversed(chain[:-1]):
        if len(current) > 0:
            break
        del ancestor[at_key]
        current = ancestor
    dump_editable(home, data)
    return True


def present(home: Path | str, section: str, key: str) -> tuple[bool, object]:
    """A validated, NON-mutating "is `section.key` set" check -- both
    `config_set`'s idempotency check and `config_unset`'s existence
    pre-check need this BEFORE opening the ledger's commit lock. Uses
    the SAME round-trip WRITE-path load as `set_leaf`/`unset_leaf`
    (never the lenient `settings_leaf`, which warns-and-returns-`None`
    on a malformed file or a non-mapping mid-path -- exactly the
    silence code-gate MINOR-2 found: `config unset` reported "already
    unset" against a file `config set` refused outright).

    `config_set` used to keep its idempotency check on `settings_leaf`
    instead, on the theory that a malformed file there just means "not
    idempotent, proceed to the write" and `set_leaf` would raise this
    same family one step later, under the lock. Code-gate MINOR-1
    (review r2 2026-09-02) found the flaw in that theory: "proceed to
    the write" means proceeding all the way to `gitops.commit_lock`,
    and if another producer already held that lock, `set` sat out the
    full 150s `COMMIT_LOCK_TIMEOUT` before reporting a wedged-producer
    error that misdiagnosed a malformed file as lock contention.
    `config_set` now uses THIS function too, for the same reason
    `config_unset` already did: raising here happens before the lock is
    ever requested, so the real problem surfaces fast, held lock or not.

    Raises :class:`ConfigWriteError` on any of the same malformed shapes
    `set_leaf`/`unset_leaf` refuse (unparseable file, non-mapping top
    level, a scalar section, a scalar mid-walk segment) -- so a caller
    doing this check FIRST refuses IDENTICALLY to the write itself,
    before ever touching the lock. Returns `(True, raw_value)` when the
    leaf is set, `(False, None)` when the path is well-formed but the
    leaf genuinely is not."""
    data = load_editable(home)
    chain, found = _walk_leaf(data, section, key, create=False)
    if not found:
        return False, None
    parent, leaf = chain[-1]
    return True, parent[leaf]
