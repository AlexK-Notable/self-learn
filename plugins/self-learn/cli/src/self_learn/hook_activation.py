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
   idempotent if the same target already does. Re-verified immediately
   after a fresh placement (fold r1, D-b) — a placement that does not
   read back as ``"matches"`` is undone and raises, rather than being
   trusted blind.
2. **registered** — parses ``settings.json`` with the same rules
   :func:`selfcheck._registered_hook_commands` already applies; an
   unparseable file is a hard refusal that leaves it byte-identical
   — never silently treated as empty; inserts the exact snippet bytes
   :func:`hook_compiler.settings_snippet` renders into the right event
   array, idempotent by (matcher, command) both matching — a command
   already registered under a DIFFERENT matcher is a refusal naming
   both (fold r1, D-a / Astra 6), never silently accepted or
   overwritten; keeps a timestamped backup, pruned to the last five,
   built from the SAME bytes this call already read once at the top —
   never a re-read at write time (fold r1, D-b / Astra 3's late-read
   lost-update risk).
3. **activation-checked** — replays the hook's own preview examples,
   read from the record's OWN persisted ``routing.hook.examples``
   first (fold r1, D-e — written at route time by
   ``verbs._prepare_hook_route``/``_prepare_one_motion_hook``),
   falling back to a still-present ``proposals/<id>.yaml`` sibling for
   the narrow case where one happens to exist; against the placed
   SYMLINK path, so a dangling or wrong-target link fails here rather
   than silently later. When NEITHER source carries examples (a
   record routed before this amendment persisted them, its proposal
   long swept) the receipt says so plainly rather than ever claiming a
   clean replay it never ran. The step then requires
   :func:`selfcheck._check_hooks`'s own byte-identity detection to
   report the registration live regardless. FW-154's rule applies
   exactly here: Claude Code's own reload of ``settings.json`` is
   never observed, and the receipt says so in those words.

Before step 1 ever places anything, the script at the ledger path is
byte-compared against the record's own approved bytes
(``routing.hook.script``) — the same check
:func:`selfcheck._check_hooks` performs, run here BEFORE the symlink
exists rather than only after (fold r1, D-c): a hand-edited or
recompiled-but-unrouted script must never get linked into a live
runtime directory, and the refusal names this specifically so it is
never confused with unrelated ``settings.json`` drift.

``register=False`` performs step 1 only and returns a receipt saying
activation is delegated but switched off — the overseer's own path
when ``overseer.hook_activation`` reads ``false`` (``config.py``); the
human path never passes it. The byte check above still runs on this
path too — a delegated placement is still a placement.

Every raw filesystem mutation this call makes is undone if the call
itself later raises (fold r1, D-b / Astra 5): a failed activation
never leaves a half-state or a mutation with no receipt to show for
it. ``deactivate`` is surgical, never a whole-file restore (fold r1,
D-a / Opus B1, Astra 1+2): it removes exactly this record's own
registration — the hook dict whose command AND matcher are this
record's own, inside the ``PreToolUse`` event — leaving every other
registration (this record's siblings, another record's, or a human's
own hand-edit) untouched, byte-for-byte, in content. The settings.json
backup a registration writes is kept purely as a human/rollback
artefact; nothing in this module ever reads it back.

No ledger write happens here. The verb's own ``hook-activated`` /
``hook-deactivated`` history entry and commit are written separately,
inside :func:`verbs._ledger_write`, by the caller — but the caller
(fold r1, D-b) now invokes THIS module's own writes from INSIDE that
same lock span, so ``tests/test_lock_invariant.py``'s walker finds
:func:`_write_claude_runtime` — the ONLY function in this module whose
body performs a raw filesystem mutation, every other function here
only decides WHAT should happen — lock-reachable on its own, with no
``NOT_REPO_TRUTH`` exemption needed (the pre-fold entry for it was
removed once the walker confirmed it: see the fold r1 report)."""

from __future__ import annotations

import hashlib
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
    """What :func:`activate`/:func:`deactivate` did.

    ``backup_note`` (02 §2 amendment: each history entry's ``note``
    "carrying the settings-file backup path") is the exact text the
    caller's ``hook-activated``/``hook-deactivated`` history entry
    should record — computed HERE, not inferred by the caller from
    ``backup_path is None``, because that single boolean collapses
    three genuinely different truths: nothing changed (idempotent),
    something changed but there was no prior file to back up (a fresh
    ``settings.json``), and something changed with a real backup
    written. ``backup_path`` stays the literal path for the one case
    a backup file actually landed on disk (fold r1, D-g: never a path
    naming a file that was never written); ``None`` in every other
    case, INCLUDING every :func:`deactivate` call — D-a's surgical
    removal never restores from a backup, so deactivation never has
    one to name.

    ``hook_registered_entry``/``hook_script_path``/``hook_script_sha256``
    (fold r1, D-f / Astra 9) are the exact ``PreToolUse`` entry
    :func:`activate` wrote (or found already registered), the ledger-
    side script path, and its sha256 — set only when ``register=True``
    reached the registration step; ``None`` for a delegated
    (``register=False``) activation and always for :func:`deactivate`."""

    steps: tuple[StepReceipt, ...]
    backup_path: Path | None = None
    backup_note: str = "no settings.json change (already registered)"
    hook_registered_entry: str | None = None
    hook_script_path: str | None = None
    hook_script_sha256: str | None = None

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


def _read_settings(settings_path: Path) -> tuple[bytes | None, dict, str | None]:
    """Parse ``settings.json``, returning its RAW bytes too (fold r1,
    D-b / Astra 3): those bytes are the ONLY legitimate backup source
    for this call — :func:`_write_claude_runtime` never re-reads the
    file for its own backup, so a concurrent editor's write landing
    between this read and the eventual write can never silently win
    over what THIS call is backing up. ``(None, {}, None)`` when the
    file is absent (nothing registered yet — a real, legitimate empty
    state); ``(bytes, {}, problem)`` when the file EXISTS but does not
    parse or is not a JSON object — a hard refusal the caller must
    never treat as "empty" (13 §7.4)."""
    if not settings_path.is_file():
        return None, {}, None
    raw = settings_path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return raw, {}, f"unparseable {settings_path}: {exc}"
    if not isinstance(data, dict):
        return raw, {}, f"{settings_path} top level must be a JSON object"
    return raw, data, None


def _snippet_fragment(snippet: str) -> tuple[str, dict]:
    """Parse a :func:`hook_compiler.settings_snippet` fragment into its
    ``(event, entry)`` pair — shared by :func:`_merge_snippet` (what to
    insert), :func:`_remove_command`'s caller (what to remove), and
    :func:`activate`'s own receipt (the exact bytes the D-f/Astra 9
    fix shows)."""
    fragment = json.loads("{" + snippet + "}")
    ((event, new_entries),) = fragment.items()
    return event, new_entries[0]


def _command_for(name: str, claude_dir: Path) -> str:
    """The exact command string a registration for hook ``name`` under
    ``claude_dir`` keys on — the same rule
    :func:`hook_compiler.command_root` applies when rendering the
    snippet itself (fold r1, D-d), so merge/removal always compares
    against exactly what got written."""
    from .hook_compiler import command_root

    return f"{command_root(claude_dir)}/hooks/{name}"


def _merge_snippet(data: dict, snippet: str, command: str) -> tuple[dict, bool]:
    """Insert ``snippet``'s event entry into ``data["hooks"][event]``
    unless (matcher, command) is ALREADY registered together, ANYWHERE
    in that event's array (fold r1, D-a / Astra 6): idempotent only
    when both match; the same ``command`` found under a DIFFERENT
    matcher is a refusal naming both matchers, never silently accepted
    (it would leave the guard registered for the wrong tool set) and
    never silently rewritten (that would touch a registration this
    call does not own). Returns ``(data, False)`` unchanged when
    already present under the SAME matcher."""
    event, new_entry = _snippet_fragment(snippet)
    matcher = new_entry.get("matcher")
    hooks_cfg = dict(data.get("hooks") or {})
    event_list = list(hooks_cfg.get(event) or [])
    same_matcher_hit = False
    other_matcher: str | None = None
    for item in event_list:
        if not isinstance(item, dict):
            continue
        item_matcher = item.get("matcher")
        for h in item.get("hooks") or []:
            if isinstance(h, dict) and h.get("command") == command:
                if item_matcher == matcher:
                    same_matcher_hit = True
                elif other_matcher is None:
                    other_matcher = item_matcher
    if same_matcher_hit:
        return data, False
    if other_matcher is not None:
        raise HookActivationError(
            f"{command} is already registered under matcher "
            f"{other_matcher!r}, expected {matcher!r} — deactivate first"
        )
    event_list = event_list + [new_entry]
    hooks_cfg[event] = event_list
    merged = dict(data)
    merged["hooks"] = hooks_cfg
    return merged, True


def _remove_command(data: dict, event: str, matcher: str, command: str) -> tuple[dict, bool]:
    """The deactivate-side twin of :func:`_merge_snippet` (fold r1,
    D-a / Opus B1, Astra 1+2 — deactivate is surgical, never a
    whole-file restore): removes exactly the hook dict whose
    ``command`` equals ``command``, inside the ``event`` item whose
    ``matcher`` equals ``matcher`` — this record's own registration,
    and only it. If that item's ``hooks`` list still has other
    commands afterwards, the item stays with the survivors; it is
    dropped only when its list empties, and the ``event`` key itself
    is dropped only when ITS list empties (so a deactivation that
    undoes the only entry ever added restores the file to exactly
    what it looked like before — no stray empty containers). Every
    other item, every other event, and every other key on ``data`` is
    untouched byte-for-byte in content."""
    hooks_cfg = data.get("hooks")
    if not isinstance(hooks_cfg, dict):
        return data, False
    event_list = hooks_cfg.get(event)
    if not isinstance(event_list, list):
        return data, False
    new_event_list = []
    changed = False
    for item in event_list:
        if not (isinstance(item, dict) and item.get("matcher") == matcher):
            new_event_list.append(item)
            continue
        hooks_list = item.get("hooks")
        if not isinstance(hooks_list, list):
            new_event_list.append(item)
            continue
        survivors = [
            h for h in hooks_list
            if not (isinstance(h, dict) and h.get("command") == command)
        ]
        if len(survivors) == len(hooks_list):
            new_event_list.append(item)  # this item never had our command
            continue
        changed = True
        if survivors:
            new_item = dict(item)
            new_item["hooks"] = survivors
            new_event_list.append(new_item)
        # else: the item's hooks list emptied -- drop the whole item.
    if not changed:
        return data, False
    new_hooks_cfg = dict(hooks_cfg)
    if new_event_list:
        new_hooks_cfg[event] = new_event_list
    else:
        del new_hooks_cfg[event]
    merged = dict(data)
    if new_hooks_cfg:
        merged["hooks"] = new_hooks_cfg
    else:
        del merged["hooks"]
    return merged, True


def _examples_for(record: Record, bucket_dir: Path) -> dict:
    """The hook's own allow/deny preview examples, for replay (fold
    r1, D-e / Astra 8). The record's OWN persisted
    ``routing.hook.examples`` (written at route time by
    ``verbs._prepare_hook_route``/``_prepare_one_motion_hook``) is read
    FIRST; ``proposals/<id>.yaml`` is a fallback for the narrow case
    where that sibling still happens to exist (a re-authored proposal,
    or a hand-seeded test fixture) — NOT the normal case:
    ``resolve_record`` sweeps every destination's proposal sibling as
    part of a successful ``route()`` (confirmed in
    ``tests/test_route_hook.py::test_two_phase_route_lands_a_working_guard``,
    which asserts the file is gone immediately after ``verbs.route()``
    returns), and one-motion routing never writes one at all. ``{}``
    when NEITHER source carries examples — for a record routed before
    this amendment persisted them, this is the honest "nothing to
    replay" state; :func:`activate` reports it explicitly rather than
    ever claiming a clean replay it never ran."""
    meta = (record.routing or {}).get("hook") or {}
    examples = meta.get("examples")
    if isinstance(examples, dict):
        return examples
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
    backup_bytes: bytes | None = None,
    unlink_settings: bool = False,
    prune_backups: tuple[Path, ...] = (),
) -> None:
    """THE single function that performs every raw filesystem mutation
    under the user's Claude runtime directory. Every other function in
    this module only computes WHAT should happen; this is the only
    place any of it actually lands on disk. Fold r1, D-b: the caller
    (``verbs.hook_activate``/``hook_deactivate``) now invokes this
    module's calls from INSIDE the same ``with _ledger_write(home)``
    span the ledger's own history-entry write uses, so ``tests/
    test_lock_invariant.py``'s walker finds this function
    lock-reachable directly — no ``NOT_REPO_TRUTH`` exemption needed
    (these writes still are never ledger TRUTH in content — the
    ledger's own receipt is the separate history-entry write below —
    but "not ledger truth" and "not lock-reachable" are different
    questions; only the second one is what that exemption list is for).

    ``backup_bytes`` (fold r1, D-b / Astra 3) is the CALLER's already-
    read bytes to preserve as the backup — this function never reads
    ``settings_path`` itself to decide what the backup should contain,
    closing the late-read lost-update window a re-read would open.
    ``unlink_settings`` (fold r1, D-b / Astra 5) is the undo primitive
    for "this call created settings.json and must now un-create it" —
    the caller's OWN failed-activation rollback, never used on any
    success path."""
    if link is not None:
        link.parent.mkdir(parents=True, exist_ok=True)
        if unlink:
            link.unlink()
        else:
            assert link_target is not None
            tmp = link.parent / f".{link.name}.tmp-{os.getpid()}-{time.time_ns()}"
            os.symlink(link_target, tmp)
            os.replace(tmp, link)
    if settings_path is not None:
        if unlink_settings:
            settings_path.unlink(missing_ok=True)
        elif settings_bytes is not None:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            if backup_path is not None and backup_bytes is not None:
                fsops.atomic_write(backup_path, backup_bytes)
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
    module docstring for the three steps, their ordering, and the
    undo-on-failure guarantee."""
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
    settings_path = claude_dir / "settings.json"
    steps: list[StepReceipt] = []

    # Fold r1, D-c (Astra 4 / Opus B3 / N10): the byte check runs
    # BEFORE placing anything, regardless of `register` — a delegated
    # (register=False) activation still places a symlink, and this is
    # the check that protects placement itself. Distinguishable from
    # unrelated settings.json drift by its own wording.
    try:
        current_script = script_abs.read_text(encoding="utf-8")
    except OSError as exc:
        raise HookActivationError(f"cannot read {script_abs}: {exc}") from exc
    if current_script != meta.get("script"):
        raise HookActivationError(
            f"hook script {script_abs} no longer matches its approved "
            "bytes (drifted since routing) — never hand-edit a "
            "generated guard; run `self-learn recompile` before "
            "activating (13 §7.4 byte check)"
        )

    placed_by_this_call = False
    wrote_settings = False
    start_bytes: bytes | None = None
    try:
        classification = _classify_symlink(link, script_abs)
        if classification == "conflict":
            raise HookActivationError(
                f"{link} already exists and does not point at {script_abs} — "
                "refusing to overwrite (a different hook or a hand-edit owns it)"
            )
        if classification == "absent":
            _write_claude_runtime(link=link, link_target=script_abs, unlink=False)
            placed_by_this_call = True
            verify = _classify_symlink(link, script_abs)
            if verify != "matches":
                raise HookActivationError(
                    f"placed symlink {link} did not verify as pointing at "
                    f"{script_abs} immediately after placement"
                )
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

        # M3-12-style replay against the SYMLINK path, BEFORE
        # registering — a dangling or wrong-target link (or a broken
        # guard) must never be written into settings.json (13 §7.4's
        # own stated purpose: "so a dangling or wrong-target link
        # fails here, not silently later").
        bucket_dir = path.parent.parent
        examples = _examples_for(record, bucket_dir)
        n_examples = len(examples.get("allow", []) or []) + len(examples.get("deny", []) or [])
        mismatches = replay_examples(link, examples)
        if mismatches:
            raise HookActivationError(
                "guard replay failed against the placed symlink — aborting "
                "before registering (13 §7.4):\n  " + "\n  ".join(mismatches)
            )

        # Fold r1, D-b: read settings.json ONCE here — this read's
        # bytes are the ONLY backup source below (Astra 3's late-read
        # lost-update risk); nothing re-reads the file to decide what
        # the backup should contain.
        start_bytes, data, problem = _read_settings(settings_path)
        if problem is not None:
            raise HookActivationError(f"{problem} — settings.json left untouched")

        command = _command_for(name, claude_dir)
        snippet = settings_snippet(list(tools), name, claude_dir=claude_dir)
        _entry_event, entry = _snippet_fragment(snippet)
        entry_json = json.dumps(entry, sort_keys=True)
        script_sha256 = hashlib.sha256(current_script.encode("utf-8")).hexdigest()
        merged, changed = _merge_snippet(data, snippet, command)
        backup_path: Path | None = None
        backup_note = "no settings.json change (already registered)"
        if changed:
            new_bytes = (json.dumps(merged, indent=2) + "\n").encode("utf-8")
            if start_bytes is not None:
                existing = sorted(claude_dir.glob("settings.json.self-learn-bak.*"))
                backup_path = claude_dir / f"settings.json.self-learn-bak.{time.time_ns()}"
                all_after = existing + [backup_path]
                prune = tuple(all_after[: max(0, len(all_after) - _BACKUP_KEEP)])
                _write_claude_runtime(
                    settings_path=settings_path,
                    settings_bytes=new_bytes,
                    backup_path=backup_path,
                    backup_bytes=start_bytes,
                    prune_backups=prune,
                )
                backup_note = str(backup_path)
            else:
                _write_claude_runtime(settings_path=settings_path, settings_bytes=new_bytes)
                backup_note = "settings.json created — no prior file to back up"
            wrote_settings = True
            steps.append(
                StepReceipt(
                    "registered",
                    f"inserted the PreToolUse entry for {name}: {entry_json} "
                    f"(script {script_abs}, sha256 {script_sha256})",
                )
            )
        else:
            steps.append(
                StepReceipt(
                    "registered",
                    f"{command} already registered (idempotent): {entry_json} "
                    f"(script {script_abs}, sha256 {script_sha256})",
                )
            )

        verdict, message = selfcheck._check_hooks(home, claude_dir)  # noqa: SLF001
        if verdict is not selfcheck.Verdict.PASS:
            raise HookActivationError(
                f"registration did not verify as live: {message}"
            )
        if n_examples:
            replay_note = f"{n_examples} example(s) replayed clean against the symlink"
        else:
            # Fold r1, D-e: honest either way -- a record with no
            # persisted examples (its own meta AND any proposal
            # sibling both empty) never reads as "replay clean".
            replay_note = (
                "no examples recorded on this record — replay skipped; "
                "doctor verdict governs"
            )
        steps.append(
            StepReceipt(
                "activation-checked",
                f"{replay_note}; the doctor confirms the approved bytes at "
                "the host path and that the symlink resolves — it does not "
                "read the bytes through the symlink itself; Claude Code's "
                "own reload of settings.json was NOT observed (FW-154)",
            )
        )
        return ActivationResult(
            steps=tuple(steps),
            backup_path=backup_path,
            backup_note=backup_note,
            hook_registered_entry=entry_json,
            hook_script_path=str(script_abs),
            hook_script_sha256=script_sha256,
        )
    except BaseException:
        # Fold r1, D-b / Astra 5: undo ONLY what THIS call did, so a
        # failed activation never leaves a half-state or a mutation
        # with no receipt to show for it.
        if wrote_settings:
            if start_bytes is not None:
                _write_claude_runtime(settings_path=settings_path, settings_bytes=start_bytes)
            else:
                _write_claude_runtime(settings_path=settings_path, unlink_settings=True)
        if placed_by_this_call:
            _write_claude_runtime(link=link, unlink=True)
        raise


def deactivate(
    home: Path | str,
    record_id: str,
    *,
    claude_dir: Path,
) -> ActivationResult:
    """Reverse :func:`activate`: remove the symlink (only if it points
    at the expected target) and surgically remove only this hook's own
    registration from ``settings.json`` — every other registration
    (this record's siblings, another record's, or a human's own hand-
    edit) is left byte-for-byte untouched (fold r1, D-a / Opus B1,
    Astra 1+2). Never restores a whole-file backup: the settings.json
    backup a registration wrote is kept purely as a human/rollback
    artefact, never read back by this function."""
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
    settings_path = claude_dir / "settings.json"
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

    tools = list(meta.get("tools") or [])
    command = _command_for(name, claude_dir)
    snippet = settings_snippet(tools, name, claude_dir=claude_dir)
    event, entry = _snippet_fragment(snippet)
    matcher = entry.get("matcher")
    # `settings_snippet` always sets a string "matcher" key -- narrows
    # the type for pyright, not a runtime-load-bearing check.
    assert isinstance(matcher, str)
    start_bytes, data, problem = _read_settings(settings_path)
    if problem is not None:
        steps.append(
            StepReceipt("unregistered", f"{problem} — settings.json left untouched")
        )
        backup_note = f"{problem} — settings.json left untouched"
    else:
        merged, changed = _remove_command(data, event, matcher, command)
        if changed:
            new_bytes = (json.dumps(merged, indent=2) + "\n").encode("utf-8")
            _write_claude_runtime(settings_path=settings_path, settings_bytes=new_bytes)
            steps.append(
                StepReceipt(
                    "unregistered",
                    f"removed the PreToolUse entry for {name} (surgical — "
                    "every other registration untouched)",
                )
            )
            backup_note = "no settings.json backup used (surgical removal)"
        else:
            steps.append(StepReceipt("unregistered", f"{command} already absent (idempotent)"))
            backup_note = "no settings.json change (already absent)"

    return ActivationResult(steps=tuple(steps), backup_path=None, backup_note=backup_note)
