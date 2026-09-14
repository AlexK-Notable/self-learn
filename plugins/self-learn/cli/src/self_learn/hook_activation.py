"""S-66 / ``13-hosting-and-separation.md`` §7.4 — the owned hook-
activation path.

A routed hook record carries an APPROVED guard script
(``routing.hook.script``) and its host-side path
(``routing.hook.script_path``), but two manual steps used to stand
between that record and a live guard: symlink the script into the
user's Claude runtime directory, and add the printed snippet to
``settings.json`` by hand. This module is the one mechanism BOTH
callers now share to perform those steps in code — the human's
``self-learn hook activate``/``hook deactivate`` (``verbs.py``, always
all three steps, never gated) and the overseer's own runner (O-2b,
gated by ``config.hook_activation_enabled``) — this module knows
neither caller; it only knows ``claude_dir``, resolved the same way
``selfcheck.claude_runtime_dir`` already does
(``SELF_LEARN_CLAUDE_DIR`` first), so a test run never touches the
real ``~/.claude``.

Three receipted steps, each independently observable:

1. **placed** — a symlink ``<claude_dir>/hooks/<script_name>`` →
   the host's approved script, created atomically; refuses if a
   *different* target (or a plain file) already occupies the name;
   idempotent if the same target already does.
2. **registered** — parses ``settings.json`` with the same rules
   :func:`selfcheck._registered_hook_commands` already applies; an
   unparseable file is a hard refusal that leaves it byte-identical
   — never silently treated as empty; inserts the exact snippet bytes
   :func:`hook_compiler.settings_snippet` renders into the right event
   array, idempotent by presence-of-command (not dict/array equality
   — the same rule the doctor's own detection uses); keeps a
   timestamped backup, pruned to the last five.
3. **activation-checked** — replays the hook's own preview examples,
   when they are still readable (from its ``proposals/<id>.yaml``
   sibling — the same file :func:`verbs._prepare_hook_route` reads its
   ``examples`` from), against the placed SYMLINK path, so a dangling
   or wrong-target link fails here rather than silently later. NOTE:
   ``route()`` sweeps that proposal sibling on every successful route
   (``ledger_ops.remove_proposal_siblings``, confirmed by
   ``tests/test_route_hook.py``), and one-motion routing never writes
   one at all, so for a record routed through either real production
   path there is nothing left to replay — the receipt says "0
   examples replayed" rather than claiming a clean replay it never
   ran; see :func:`_examples_for`. The step then requires
   :func:`selfcheck._check_hooks`'s own byte-identity detection to
   report the registration live regardless. FW-154's rule applies
   exactly here: Claude Code's own reload of ``settings.json`` is
   never observed, and the receipt says so in those words.

``register=False`` performs step 1 only and returns a receipt saying
activation is delegated but switched off — the overseer's own path
when ``overseer.hook_activation`` reads ``false`` (``config.py``); the
human path never passes it.

No ledger write happens here. The verb's own ``hook-activated`` /
``hook-deactivated`` history entry and commit are written separately,
inside :func:`verbs._ledger_write`, by the caller — this module's own
writes land entirely outside every repo (the user's Claude runtime
directory), which is exactly the disposition
``tests/test_lock_invariant.py``'s one ``NOT_REPO_TRUTH`` entry for
this module records: :func:`_write_claude_runtime` is the ONLY
function in this module whose body performs a raw filesystem mutation
— every other function here only decides WHAT should happen."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .hook_compiler import replay_examples, settings_snippet
from .ledger_ops import read_proposal, require_status
from .primitives import fsops
from .records import Record

__all__ = [
    "ActivationResult",
    "HookActivationError",
    "StepReceipt",
    "activate",
    "deactivate",
]

#: The last N settings.json backups kept per activation (13 §7.4).
_BACKUP_KEEP = 5


class HookActivationError(Exception):
    """A step in the activation/deactivation path refused before (or
    instead of) writing anything further."""


@dataclass(frozen=True)
class StepReceipt:
    """One step's own receipt line (13 §7.4: "each step produces its
    own receipt line")."""

    step: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.step}: {self.detail}"


@dataclass(frozen=True)
class ActivationResult:
    """What :func:`activate`/:func:`deactivate` did. ``backup_path`` is
    the settings.json backup path this call's own history entry note
    should carry (02 §2 amendment: "carrying the settings-file backup
    path", for BOTH ``hook-activated`` and ``hook-deactivated``) — for
    :func:`activate` the backup it just WROTE (``None`` when no
    settings change happened, e.g. idempotent or ``register=False``);
    for :func:`deactivate` the backup it just RESTORED FROM (``None``
    when it instead did a surgical removal, or found nothing to
    remove)."""

    steps: tuple[StepReceipt, ...]
    backup_path: Path | None = None

    @property
    def receipts(self) -> tuple[str, ...]:
        return tuple(str(s) for s in self.steps)


# --------------------------------------------------------- pure helpers


def _classify_symlink(link: Path, target: Path) -> str:
    """Non-mutating: ``"absent"`` (nothing at the name), ``"matches"``
    (already the right target — idempotent), or ``"conflict"`` (a
    plain file/dir, or a symlink to a DIFFERENT target, occupies the
    name)."""
    if not link.is_symlink():
        return "conflict" if link.exists() else "absent"
    try:
        raw = os.readlink(link)
    except OSError:
        return "conflict"
    current = Path(raw)
    if not current.is_absolute():
        current = link.parent / current
    try:
        matches = current.resolve() == target.resolve()
    except OSError:
        matches = False
    return "matches" if matches else "conflict"


def _read_settings(settings_path: Path) -> tuple[dict, str | None]:
    """Parse ``settings.json``. Returns ``({}, None)`` when the file is
    absent (nothing registered yet — a real, legitimate empty state);
    ``({}, problem)`` when the file EXISTS but does not parse or is
    not a JSON object — a hard refusal the caller must never treat as
    "empty" (13 §7.4)."""
    if not settings_path.is_file():
        return {}, None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, f"unparseable {settings_path}: {exc}"
    if not isinstance(data, dict):
        return {}, f"{settings_path} top level must be a JSON object"
    return data, None


def _command_for(name: str) -> str:
    """The exact command string ``settings_snippet`` embeds for hook
    ``name`` — the presence test both merge and removal key on."""
    return f"$HOME/.claude/hooks/{name}"


def _merge_snippet(data: dict, snippet: str, command: str) -> tuple[dict, bool]:
    """Insert ``snippet``'s event entry into ``data["hooks"][event]``
    unless ``command`` is already registered ANYWHERE in that event's
    array — idempotent by presence, the same rule
    :func:`selfcheck._registered_hook_commands` already applies when
    checking liveness (M3-1/M3-14: identical bytes twice would still
    read as two registrations under dict/array equality, which is not
    the question that matters). Returns ``(data, False)`` unchanged
    when already present."""
    fragment = json.loads("{" + snippet + "}")
    ((event, new_entries),) = fragment.items()
    new_entry = new_entries[0]
    hooks_cfg = dict(data.get("hooks") or {})
    event_list = list(hooks_cfg.get(event) or [])
    already = any(
        isinstance(item, dict)
        and any(
            isinstance(h, dict) and h.get("command") == command
            for h in (item.get("hooks") or [])
        )
        for item in event_list
    )
    if already:
        return data, False
    event_list = event_list + [new_entry]
    hooks_cfg[event] = event_list
    merged = dict(data)
    merged["hooks"] = hooks_cfg
    return merged, True


def _remove_command(data: dict, command: str) -> tuple[dict, bool]:
    """The deactivate-side twin of :func:`_merge_snippet`, used only
    when no recorded backup exists to restore from: drop every array
    entry that registers ``command``, in every event, leaving every
    other registration (this record's OR anyone else's) untouched."""
    hooks_cfg = data.get("hooks")
    if not isinstance(hooks_cfg, dict):
        return data, False
    new_hooks_cfg: dict = {}
    changed = False
    for event, entries in hooks_cfg.items():
        if not isinstance(entries, list):
            new_hooks_cfg[event] = entries
            continue
        kept = []
        for item in entries:
            hooks_list = item.get("hooks") if isinstance(item, dict) else None
            has_cmd = isinstance(hooks_list, list) and any(
                isinstance(h, dict) and h.get("command") == command
                for h in hooks_list
            )
            if has_cmd:
                changed = True
                continue
            kept.append(item)
        if kept:
            new_hooks_cfg[event] = kept
    if not changed:
        return data, False
    merged = dict(data)
    merged["hooks"] = new_hooks_cfg
    return merged, True


def _latest_hook_activation_backup(record: Record) -> str | None:
    """The settings.json backup path recorded on the record's most
    recent ``hook-activated`` history entry that actually carries one
    (02 §2 amendment), skipping past any entry whose ``note`` is not a
    ``settings.json.self-learn-bak.*`` path — a ``register=False``
    activation's own fallback note (see :func:`activate`'s
    ``"delegated"`` step) is not a backup path, and a naive "most
    recent entry, whatever its note says" read would stop there and
    report no backup even when an EARLIER activation on the same
    record really did register (and back up) settings.json. ``None``
    when no ``hook-activated`` entry carries a real backup path."""
    for entry in reversed(record.history):
        if entry.get("event") != "hook-activated":
            continue
        note = entry.get("note")
        if isinstance(note, str) and note and Path(note).name.startswith(
            "settings.json.self-learn-bak."
        ):
            return note
    return None


def _examples_for(record: Record, bucket_dir: Path) -> dict:
    """The proposal-carried allow/deny examples for ``record``, when
    they still exist. ``proposals/<id>.yaml`` is NOT durable past
    routing: ``resolve_record`` sweeps every destination's proposal
    sibling as part of a successful ``route()`` (confirmed in
    ``tests/test_route_hook.py::test_two_phase_route_lands_a_working_guard``,
    which asserts the file is gone immediately after ``verbs.route()``
    returns), and one-motion routing never writes a proposal file at
    all. So for a record routed through either real production path,
    this returns ``{}`` — examples survive here only for a record
    whose proposal was re-authored after routing, or a hand-seeded
    test fixture that plants one deliberately. ``{}`` is not treated
    as a refusal — :func:`replay_examples` on zero examples is a
    no-op, and :func:`activate` reports the count explicitly so a
    zero-example run never reads as "replay clean" (see the
    ``activation-checked`` receipt)."""
    proposal_path = bucket_dir / "proposals" / f"{record.id}.yaml"
    if not proposal_path.is_file():
        return {}
    data = read_proposal(proposal_path)
    examples = data.get("examples")
    return examples if isinstance(examples, dict) else {}


# ---------------------------------------------------- the one raw writer


def _write_claude_runtime(
    *,
    link: Path | None = None,
    link_target: Path | None = None,
    unlink: bool = False,
    settings_path: Path | None = None,
    settings_bytes: bytes | None = None,
    backup_path: Path | None = None,
    prune_backups: tuple[Path, ...] = (),
) -> None:
    """THE single function that performs every raw filesystem mutation
    under the user's Claude runtime directory. Every other function in
    this module only computes WHAT should happen; this is the only
    place any of it actually lands on disk — ``tests/
    test_lock_invariant.py``'s ``NOT_REPO_TRUTH`` carries exactly one
    entry, for this function, because these writes are never ledger
    truth (the verb's own history-entry receipt is written separately,
    under :func:`verbs._ledger_write`)."""
    if link is not None:
        link.parent.mkdir(parents=True, exist_ok=True)
        if unlink:
            link.unlink()
        else:
            assert link_target is not None
            tmp = link.parent / f".{link.name}.tmp-{os.getpid()}-{time.time_ns()}"
            os.symlink(link_target, tmp)
            os.replace(tmp, link)
    if settings_path is not None and settings_bytes is not None:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path is not None and settings_path.is_file():
            fsops.atomic_write(backup_path, settings_path.read_bytes())
        fsops.atomic_write(settings_path, settings_bytes)
    for stale in prune_backups:
        stale.unlink(missing_ok=True)


# --------------------------------------------------------------- verbs


def activate(
    home: Path | str,
    record_id: str,
    *,
    claude_dir: Path,
    register: bool = True,
) -> ActivationResult:
    """Place the symlink; when ``register`` (the human path always
    passes the default, ``True``), also register + verify. See the
    module docstring for the three steps and their ordering."""
    home = Path(home)
    path, record = require_status(
        home, record_id, frozenset({"routed"}), verb="hook activate"
    )
    routing = record.routing or {}
    if routing.get("destination") != "hook":
        raise HookActivationError(
            f"record {record_id} is routed to {routing.get('destination')!r}, "
            "not hook — hook activate needs a hook-routed record"
        )
    meta = routing.get("hook") or {}
    tools = meta.get("tools")
    if not meta.get("script_path") or not tools:
        raise HookActivationError(
            f"record {record_id}'s hook routing is incomplete (no "
            "script_path/tools) — re-route before activating"
        )

    # Deferred: verbs.py imports THIS module at its own top level (to
    # call activate/deactivate), so an equally top-level import back
    # from here would be a real circular import — the same "same
    # module family" deferred-import precedent verbs.py itself already
    # uses for `.ledger_ops._generate_hook_script`. `selfcheck` is
    # deferred for the identical reason one hop further out:
    # `selfcheck.py` imports names FROM `verbs` at its own top level.
    from . import selfcheck, verbs

    warnings: list[str] = []
    location = verbs._hook_script_location(home, record, warnings)  # noqa: SLF001
    if location is None:
        raise HookActivationError(
            f"cannot locate {record_id}'s hook script — "
            + ("; ".join(warnings) if warnings else "no routing.hook.script_path")
        )
    _host_repo, script_abs, _rel, _mode = location
    if not script_abs.is_file():
        raise HookActivationError(
            f"hook script {script_abs} is missing — run `self-learn recompile`"
        )

    name = script_abs.name
    link = claude_dir / "hooks" / name
    steps: list[StepReceipt] = []

    classification = _classify_symlink(link, script_abs)
    if classification == "conflict":
        raise HookActivationError(
            f"{link} already exists and does not point at {script_abs} — "
            "refusing to overwrite (a different hook or a hand-edit owns it)"
        )
    if classification == "absent":
        _write_claude_runtime(link=link, link_target=script_abs, unlink=False)
        steps.append(StepReceipt("placed", f"symlinked {link} -> {script_abs}"))
    else:
        steps.append(
            StepReceipt("placed", f"{link} already points at {script_abs} (idempotent)")
        )

    if not register:
        steps.append(
            StepReceipt(
                "delegated",
                "activation is delegated but switched off "
                "(overseer.hook_activation is false) — placed only",
            )
        )
        return ActivationResult(steps=tuple(steps))

    # M3-12-style replay against the SYMLINK path, BEFORE registering —
    # a dangling or wrong-target link (or a broken guard) must never be
    # written into settings.json (13 §7.4's own stated purpose: "so a
    # dangling or wrong-target link fails here, not silently later").
    bucket_dir = path.parent.parent
    examples = _examples_for(record, bucket_dir)
    n_examples = len(examples.get("allow", []) or []) + len(examples.get("deny", []) or [])
    mismatches = replay_examples(link, examples)
    if mismatches:
        raise HookActivationError(
            "guard replay failed against the placed symlink — aborting "
            "before registering (13 §7.4):\n  " + "\n  ".join(mismatches)
        )

    settings_path = claude_dir / "settings.json"
    data, problem = _read_settings(settings_path)
    if problem is not None:
        raise HookActivationError(f"{problem} — settings.json left untouched")
    command = _command_for(name)
    snippet = settings_snippet(list(tools), name)
    merged, changed = _merge_snippet(data, snippet, command)
    backup_path: Path | None = None
    if changed:
        existing = sorted(claude_dir.glob("settings.json.self-learn-bak.*"))
        backup_path = claude_dir / f"settings.json.self-learn-bak.{time.time_ns()}"
        all_after = existing + [backup_path]
        prune = tuple(all_after[: max(0, len(all_after) - _BACKUP_KEEP)])
        new_bytes = (json.dumps(merged, indent=2) + "\n").encode("utf-8")
        _write_claude_runtime(
            settings_path=settings_path,
            settings_bytes=new_bytes,
            backup_path=backup_path,
            prune_backups=prune,
        )
        steps.append(
            StepReceipt("registered", f"inserted the PreToolUse entry for {name}")
        )
    else:
        steps.append(
            StepReceipt("registered", f"{command} already registered (idempotent)")
        )

    verdict, message = selfcheck._check_hooks(home, claude_dir)  # noqa: SLF001
    if verdict is not selfcheck.Verdict.PASS:
        raise HookActivationError(
            f"registration did not verify as live: {message}"
        )
    if n_examples:
        replay_note = f"{n_examples} example(s) replayed clean against the symlink"
    else:
        replay_note = (
            "0 examples replayed — proposal sibling swept at route time; "
            "behavioral replay ran at route, the doctor's byte-identity "
            "check below is the live verification"
        )
    steps.append(
        StepReceipt(
            "activation-checked",
            f"{replay_note}; registration verified live by the doctor's own "
            "hook check; Claude Code's own reload of settings.json was NOT "
            "observed (FW-154)",
        )
    )
    return ActivationResult(steps=tuple(steps), backup_path=backup_path)


def deactivate(
    home: Path | str,
    record_id: str,
    *,
    claude_dir: Path,
) -> ActivationResult:
    """Reverse :func:`activate`: remove the symlink (only if it points
    at the expected target) and restore ``settings.json`` from the
    recorded backup when one exists (only THIS activation's own prior
    state, never a later, unrelated edit — the backup is read from the
    record's own ``hook-activated`` history note); with no recorded
    backup (e.g. a ``register=False`` activation never registered
    anything), surgically removes only this hook's own entry."""
    home = Path(home)
    path, record = require_status(
        home, record_id, frozenset({"routed"}), verb="hook deactivate"
    )
    routing = record.routing or {}
    if routing.get("destination") != "hook":
        raise HookActivationError(
            f"record {record_id} is routed to {routing.get('destination')!r}, "
            "not hook — hook deactivate needs a hook-routed record"
        )
    meta = routing.get("hook") or {}
    if not meta.get("script_path"):
        raise HookActivationError(
            f"record {record_id} carries no routing.hook.script_path"
        )

    from . import verbs  # deferred: see activate()

    warnings: list[str] = []
    location = verbs._hook_script_location(home, record, warnings)  # noqa: SLF001
    if location is None:
        raise HookActivationError(
            f"cannot locate {record_id}'s hook script — "
            + ("; ".join(warnings) if warnings else "no routing.hook.script_path")
        )
    _host_repo, script_abs, _rel, _mode = location
    name = script_abs.name
    link = claude_dir / "hooks" / name
    steps: list[StepReceipt] = []

    classification = _classify_symlink(link, script_abs)
    if classification == "matches":
        _write_claude_runtime(link=link, unlink=True)
        steps.append(StepReceipt("unplaced", f"removed {link}"))
    elif classification == "absent":
        steps.append(StepReceipt("unplaced", f"{link} already absent (idempotent)"))
    else:
        steps.append(
            StepReceipt(
                "unplaced",
                f"{link} does not point at {script_abs} — left in place "
                "(not this record's symlink)",
            )
        )

    command = _command_for(name)
    settings_path = claude_dir / "settings.json"
    backup_note = _latest_hook_activation_backup(record)
    restored_from: Path | None = None
    if backup_note is not None and Path(backup_note).is_file():
        restore_bytes = Path(backup_note).read_bytes()
        _write_claude_runtime(settings_path=settings_path, settings_bytes=restore_bytes)
        steps.append(
            StepReceipt("unregistered", f"restored settings.json from {backup_note}")
        )
        restored_from = Path(backup_note)
    else:
        data, problem = _read_settings(settings_path)
        if problem is not None:
            steps.append(
                StepReceipt("unregistered", f"{problem} — settings.json left untouched")
            )
        else:
            merged, changed = _remove_command(data, command)
            if changed:
                new_bytes = (json.dumps(merged, indent=2) + "\n").encode("utf-8")
                _write_claude_runtime(settings_path=settings_path, settings_bytes=new_bytes)
                steps.append(
                    StepReceipt(
                        "unregistered",
                        f"removed the PreToolUse entry for {name} (no recorded backup)",
                    )
                )
            else:
                steps.append(
                    StepReceipt("unregistered", f"{command} already absent (idempotent)")
                )

    return ActivationResult(steps=tuple(steps), backup_path=restored_from)
