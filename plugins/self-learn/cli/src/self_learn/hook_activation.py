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
``selfcheck.claude_runtime_dir`` already does (``SELF_LEARN_CLAUDE_DIR``
first), so a test run never touches the real ``~/.claude``. Every entry
point anchors ``claude_dir`` to an absolute path first (fold r2, item E
/ Astra 13's relative-override half — :func:`hook_compiler._absolute`'s
same no-symlink-resolution rule), so the placed symlink and the command
this module writes into ``settings.json`` always name the SAME
directory.

Three receipted steps, each independently observable:

1. **placed** — a symlink ``<claude_dir>/hooks/<script_name>`` →
   the host's approved script, created atomically; refuses if a
   *different* target (or a plain file) already occupies the name;
   idempotent if the same target already does. Re-verified immediately
   after a fresh placement — a placement that does not read back as
   ``"matches"`` is undone and raises, rather than being trusted blind.
2. **registered** — parses ``settings.json`` with the same rules
   :func:`selfcheck._registered_hook_commands` already applies; an
   unparseable file is a hard refusal that leaves it byte-identical
   — never silently treated as empty; inserts the exact snippet bytes
   :func:`hook_compiler.settings_snippet` renders into the right event
   array, idempotent by (matcher, command) both matching — a command
   already registered under a DIFFERENT matcher (or one with a missing
   or null matcher — fold r2, item D / Astra 6's second hole) is a
   refusal naming both, checked BEFORE the same-matcher idempotence
   check so a mixed-item settings file (this command registered under
   both the right matcher and a wrong one) is never silently accepted;
   keeps a timestamped backup, pruned to the last five, built from the
   SAME bytes this call already read once at the top — never a re-read
   at write time. An idempotent match's receipt shows the entry AS
   ACTUALLY REGISTERED (fold r2, item F / Astra 9's second half — a
   grouped item with a sibling command or an extra key like
   ``timeout`` reads back exactly, never the freshly rendered snippet
   this call would have proposed had nothing been there).
3. **activation-checked** / **doctor-checked** — replays the hook's own
   preview examples, read from the record's OWN persisted
   ``routing.hook.examples`` first (written at route time by
   ``verbs._prepare_hook_route``/``_prepare_one_motion_hook``), falling
   back to a still-present ``proposals/<id>.yaml`` sibling for the
   narrow case where one happens to exist; against the placed SYMLINK
   path, so a dangling or wrong-target link fails here rather than
   silently later. The step's OWN label distinguishes whether a replay
   actually ran (``activation-checked``, ``replay: "ran"``) from a
   record with NOTHING to replay (``doctor-checked``, ``replay:
   "skipped-no-examples"`` — fold r2, item G / Astra 8: the label
   itself, not only the detail text, must never read as though a
   replay happened when none did). Either way the step then requires
   :func:`selfcheck._check_hooks`'s own byte-identity detection to
   report the registration live regardless, and the receipt never
   claims more than that — Claude Code's own reload of ``settings.json``
   is never observed, and the receipt says so in those words (FW-154).

Before step 1 ever places anything, the script at the ledger path is
byte-compared against the record's own approved bytes
(``routing.hook.script``) — the same check
:func:`selfcheck._check_hooks` performs, run here BEFORE the symlink
exists rather than only after: a hand-edited or recompiled-but-unrouted
script must never get linked into a live runtime directory, and the
refusal names this specifically so it is never confused with unrelated
``settings.json`` drift.

``register=False`` performs step 1 only and returns a receipt saying
activation is delegated but switched off — the overseer's own path
when ``overseer.hook_activation`` reads ``false`` (``config.py``); the
human path never passes it. The byte check above still runs on this
path too — a delegated placement is still a placement.

**Fold r2 — prepare-first, independent cleanups, residual receipts.**
:func:`activate`/:func:`deactivate` each split into two phases: Phase 1
computes everything decidable WITHOUT touching disk — the byte check,
the symlink's current classification, the matcher/idempotence/conflict
rules above, the merged settings bytes, the backup path, the exact
command string — and can refuse outright with zero raw writes behind
it. Phase 2 performs the writes, in order — for ``activate``: the
backup file, the symlink placement (a check that requires the LIVE
symlink, the example replay, sits between placement and the settings
write — it must abort BEFORE registering, per this module's own stated
purpose above), the settings replace, the doctor verdict; for
``deactivate``: the settings replace, THEN the symlink removal (the
REVERSE of ``activate``'s order — a half-state where the registration
is gone but the guard symlink still sits inert is strictly safer than
one where the symlink is gone but ``settings.json`` still names it,
which would leave Claude Code invoking a dangling command). Each raw
write is recorded on a small mutable :class:`_Progress` object
EAGERLY, right before the write is attempted — never only after the
call returns without raising (a replace that lands and then fails its
own trailing directory fsync still counts as WRITTEN; "the call didn't
raise" is not the boundary this module trusts). Undoing an effect that
was marked but never actually landed is always safe: restoring
identical bytes, or removing a path that was never created
(``missing_ok=True`` throughout — see :func:`_undo`), is a harmless
no-op.

On any raise once Phase 2 has begun, :func:`_undo` attempts each
cleanup INDEPENDENTLY in its own ``try`` — a failure restoring
``settings.json`` must never skip removing the symlink or the backup
this call made, and vice versa. The ORIGINAL exception stays the
primary error regardless of what cleanup does or does not manage;
residual effects a cleanup itself could not undo are attached to it as
notes (``BaseException.add_note`` — Python ≥3.11, this project's
floor), never swallowed into a different exception type or message.

Backup PRUNING moves out of this module entirely (fold r1 kept it
inside the same call that registers; fold r2 removes it): an
activation that registers something new only ever WRITES one backup
here — deciding which older ones are now stale, and removing them, is
the VERB's job, run only after its ledger commit has landed, and a
pruning failure is its own receipt line, never an activation failure
(an activation that already committed successfully must never read as
having failed because disk cleanup afterward hit an ``OSError``).

**The runtime-to-ledger handoff is part of the failure model too**
(fold r2, item B). :func:`activate`/:func:`deactivate` return their
:class:`_Progress` on :class:`ActivationResult` (as ``progress``) even
on SUCCESS — not only so this module's OWN except block can undo a
mid-call failure, but so the VERB (``verbs.hook_activate``/
``hook_deactivate``) can call :func:`_undo` itself if something AFTER
this call returns (``Record.write``, the ledger commit) fails. Because
that later failure might strike AFTER the commit has actually landed —
an exception raised while a subprocess's own output is still being
read, say, after ``git commit`` already created the object and moved
``HEAD`` — the verb checks whether the ledger's ``HEAD`` actually
advanced before deciding: if it did, the runtime change is KEPT (an
activated hook a ledger record fails to describe is a worse outcome
than an over-cautious one that stays live) and the uncertain outcome
is reported rather than silently undone.

No ledger write happens here. The verb's own ``hook-activated`` /
``hook-deactivated`` history entry and commit are written separately,
inside :func:`verbs._ledger_write`, by the caller — but the caller now
invokes THIS module's own writes from INSIDE that same lock span, so
``tests/test_lock_invariant.py``'s walker finds :func:`_write_claude_runtime`
— the ONLY function in this module whose body performs a raw
filesystem mutation, every other function here only decides WHAT
should happen — lock-reachable on its own, with no ``NOT_REPO_TRUTH``
exemption needed.

**The concurrent-editor bound.** A human hand-editing ``settings.json``
in an editor at the same moment this module runs is NOT serialised by
the commit lock — that lock only ever holds off another self-learn
call. This module's own discipline is read-once-then-atomic-replace:
settings.json is read exactly once, at the top of Phase 1, and every
later decision (the merge, the backup bytes) is computed from that one
read. Stated plainly, the bound is NOT reassuring: a concurrent
editor's write landing between this read and this call's own replace
is silently LOST — self-learn's replace wins, unconditionally, and the
human's edit is recoverable from neither the live file nor this call's
own backup (which captured the bytes BEFORE the human's edit, not
after). The reverse also holds: this call's own registration can be
overwritten by a slower-finishing concurrent human edit landing after
it. Atomic replacement guarantees the file is never observed
half-written; it guarantees nothing about which of two racing writers'
content survives."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .hook_compiler import command_for, replay_examples, settings_snippet
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

#: Fold r2, item D (Astra 6's second hole): a sentinel distinguishing
#: "this command is not registered under ANY matcher in this event" from
#: "found, but its matcher key is itself missing or null" — both would
#: otherwise collapse onto plain ``None`` and be indistinguishable.
_NOT_FOUND = object()


class HookActivationError(Exception):
    """A step in the activation/deactivation path refused before (or
    instead of) writing anything further."""


def _absolute_claude_dir(claude_dir: Path | str) -> Path:
    """Anchor ``claude_dir`` to an absolute path once, at the top of
    :func:`activate`/:func:`deactivate` — see the module docstring's
    opening paragraph. Delegates to :func:`hook_compiler._absolute` so
    the placement path and the registered command (:func:`command_for`,
    same module) can never disagree about what "absolute" means."""
    from . import hook_compiler

    return hook_compiler._absolute(Path(claude_dir))  # noqa: SLF001


@dataclass(frozen=True)
class StepReceipt:
    """One step's own receipt line (13 §7.4: "each step produces its
    own receipt line")."""

    step: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.step}: {self.detail}"


@dataclass
class _Progress:
    """Fold r2, item A/B: which raw effects THIS :func:`activate`/
    :func:`deactivate` call has attempted — set EAGERLY by the call
    site, immediately before the write that would produce the effect,
    never only after that write returns without raising (see the
    module docstring). Carried on :class:`ActivationResult` so a LATER
    failure outside this module (the verb's own ledger write) can still
    call :func:`_undo` against exactly what this call did."""

    link: Path
    settings_path: Path
    link_target: Path | None = None
    link_placed: bool = False
    link_removed: bool = False
    start_bytes: bytes | None = None
    settings_written: bool = False
    backup_path: Path | None = None
    backup_written: bool = False


def _restore_landed(settings_path: Path, expected_bytes: bytes | None) -> bool:
    """Fold r3, N6: whether ``settings_path`` actually holds
    ``expected_bytes`` on disk (or, when ``expected_bytes`` is ``None``,
    is genuinely absent) — read back after the attempt, never inferred
    from whether the write call itself raised. The same boundary
    :class:`_Progress`'s own eager marking already draws for the
    FORWARD write ("a replace that lands and then fails its own
    trailing directory fsync still counts as WRITTEN") applies just as
    much to :func:`_undo`'s restore attempts: a call that raises AFTER
    genuinely landing the bytes must not be reported as a failed
    restore, and — the rarer direction — a call that returns cleanly
    but somehow left the wrong bytes on disk must not be reported as a
    success either way this function is ever called."""
    if expected_bytes is None:
        return not settings_path.exists()
    try:
        return settings_path.read_bytes() == expected_bytes
    except OSError:
        return False


def _undo(progress: _Progress) -> list[str]:
    """Fold r2, item A: each cleanup attempted INDEPENDENTLY in its own
    ``try`` — a failure undoing one effect must never skip the others.
    Every cleanup here tolerates the marked effect never having actually
    landed (``missing_ok=True`` throughout, and restoring ``start_bytes``
    over a file that already holds those exact bytes is a harmless
    no-op) — see the module docstring's "eager marking" paragraph.
    Returns the list of effects a cleanup itself could NOT undo (empty =
    fully undone); the caller's ORIGINAL exception stays primary
    regardless — this function never raises, and never decides what the
    caller's error should be.

    Fold r3, N7: a pre-commit ledger failure (the verb's own
    ``record.write``/``_commit_ledger`` raising) leaves the ledger
    record on disk DIRTY with a ``hook-activated``/``hook-deactivated``
    history entry, by design — this function only ever touches the
    Claude runtime directory (the symlink, ``settings.json``, the
    backup file) and never the ledger record itself; the next call's
    recover-or-refuse path (§7.2a.5) is what reconciles that dirty
    record, not this function."""
    residual: list[str] = []
    if progress.settings_written:
        write_exc: Exception | None = None
        try:
            if progress.start_bytes is not None:
                _write_claude_runtime(
                    settings_path=progress.settings_path, settings_bytes=progress.start_bytes
                )
            else:
                _write_claude_runtime(settings_path=progress.settings_path, unlink_settings=True)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            write_exc = exc
        # Fold r3, N6: decide by reading the bytes back, not by whether
        # the write call above raised.
        if not _restore_landed(progress.settings_path, progress.start_bytes):
            detail = (
                write_exc
                if write_exc is not None
                else "the file on disk does not match the expected restored bytes"
            )
            residual.append(
                f"settings.json restore failed: {detail} — the registration "
                "change made by this call may still be live"
            )
    if progress.link_placed:
        try:
            _write_claude_runtime(link=progress.link, unlink=True)
        except Exception as exc:  # noqa: BLE001
            residual.append(
                f"symlink {progress.link} removal failed: {exc} — the "
                "link this call placed may still be present"
            )
    elif progress.link_removed:
        try:
            assert progress.link_target is not None
            _write_claude_runtime(link=progress.link, link_target=progress.link_target, unlink=False)
        except Exception as exc:  # noqa: BLE001
            residual.append(
                f"symlink {progress.link} restore failed: {exc} — the "
                "link this call removed was not put back"
            )
    if progress.backup_written and progress.backup_path is not None:
        try:
            _write_claude_runtime(remove_backup=progress.backup_path)
        except Exception as exc:  # noqa: BLE001
            residual.append(
                f"backup {progress.backup_path} removal failed: {exc} — "
                "a stray backup file may remain"
            )
    return residual


@dataclass(frozen=True)
class ActivationResult:
    """What :func:`activate`/:func:`deactivate` did.

    ``backup_note`` (02 §2 amendment, fold r2: an ``activate`` entry's
    ``note`` carries the settings-file backup path or a truthful
    no-backup string; a ``deactivate`` entry's names the removed
    registration and the symlink path instead — see each function's own
    computation) is the exact text the caller's ``hook-activated``/
    ``hook-deactivated`` history entry should record — computed HERE,
    not inferred by the caller from ``backup_path is None``, because
    that single boolean collapses several genuinely different truths.
    ``backup_path`` stays the literal path for the one case a backup
    file actually landed on disk; ``None`` in every other case,
    INCLUDING every :func:`deactivate` call — D-a's surgical removal
    never restores from a backup, so deactivation never has one to name.

    ``hook_registered_entry``/``hook_script_path``/``hook_script_sha256``
    (fold r1, D-f / Astra 9; fold r2, item F fixes what
    ``hook_registered_entry`` shows on an idempotent match) are the
    exact ``PreToolUse`` entry :func:`activate` wrote (or found already
    registered — the ACTUAL registered item, siblings and all, not the
    freshly rendered snippet this call would have proposed), the
    ledger-side script path, and its sha256; ``None`` for a delegated
    (``register=False``) activation and always for :func:`deactivate`.

    ``replay``/``reload_caveat`` (fold r2, item G / Astra 8): the
    STRUCTURED form of step 3's own receipt — ``replay`` is
    ``"ran"``/``"skipped-no-examples"``/``None`` (delegated activation
    or ``deactivate``, where no replay step exists at all);
    ``reload_caveat`` is the FW-154 sentence, carried separately so a
    ``--json`` consumer can read it without parsing prose out of a
    receipt string.

    ``progress`` (fold r2, item B) is the mutable record of this call's
    own raw effects — see :func:`_undo`; the verb calls it directly if
    a LATER failure (outside this function) needs to reverse what THIS
    call did."""

    steps: tuple[StepReceipt, ...]
    backup_path: Path | None = None
    backup_note: str = "no settings.json change (already registered)"
    hook_registered_entry: str | None = None
    hook_script_path: str | None = None
    hook_script_sha256: str | None = None
    replay: Literal["ran", "skipped-no-examples"] | None = None
    reload_caveat: str | None = None
    progress: _Progress | None = field(default=None, compare=False)

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
    """Parse ``settings.json``, returning its RAW bytes too: those bytes
    are the ONLY legitimate backup source for this call —
    :func:`_write_claude_runtime` never re-reads the file for its own
    backup, so a concurrent editor's write landing between this read
    and the eventual replace is silently LOST — it is captured in
    neither the live file (self-learn's atomic replace overwrites it)
    nor this call's own backup (which holds the bytes from BEFORE that
    edit) — see the module docstring's concurrent-editor paragraph for
    the fully honest statement of that bound (fold r2, nit 6: the OLD
    text here claimed the opposite direction). ``(None, {}, None)``
    when the file is absent (nothing registered yet — a real,
    legitimate empty state); ``(bytes, {}, problem)`` when the file
    EXISTS but does not parse or is not a JSON object — a hard refusal
    the caller must never treat as "empty" (13 §7.4)."""
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
    ``claude_dir`` keys on — a thin pass-through to
    :func:`hook_compiler.command_for` (fold r2, item E: the shared
    quoting/absolutizing function :func:`hook_compiler.settings_snippet`
    itself now also calls), so merge/removal always compares against
    exactly what got written."""
    return command_for(name, claude_dir)


def _registered_matcher_for(data: dict, event: str, command: str):
    """Every matcher ``command`` is registered under, in ``event``'s
    array — fold r2, item D, mirrored on the removal side; fold r3,
    item S4: collect-ALL, matching :func:`_merge_snippet`'s write-side
    scan. The round-2 shape returned only the FIRST matching item's
    matcher and stopped, so whether :func:`deactivate` refused depended
    on array ORDER (gate round-3 SHOULD-FIX 4, probes M7/M8/M9): the
    reachable sequence — activate normally, hand-add a foreign-matcher
    entry for the SAME command, deactivate — silently removed the
    OWNED entry and left a dangling foreign registration pointing at
    the symlink this call had just deleted, its own receipt claiming
    "every other registration untouched". Returns the module-level
    :data:`_NOT_FOUND` sentinel when ``command`` is not registered
    anywhere in this event's array; otherwise a list of EVERY matcher
    found (duplicates included; a missing or null ``matcher`` key
    normalizes to ``None``, same as the write side) — the caller
    refuses whenever anything besides its own matcher appears in that
    list, regardless of which element came first."""
    hooks_cfg = data.get("hooks") or {}
    found: list = []
    for item in hooks_cfg.get(event) or []:
        if not isinstance(item, dict):
            continue
        for h in item.get("hooks") or []:
            if isinstance(h, dict) and h.get("command") == command:
                found.append(item.get("matcher"))
    if not found:
        return _NOT_FOUND
    return found


def _registered_item(data: dict, event: str, matcher, command: str) -> dict | None:
    """Fold r2, item F (Astra 9's second half): the ACTUAL item dict
    currently sitting in ``settings.json`` for ``(event, matcher,
    command)`` — siblings, a hand-added ``timeout`` key, whatever else
    is really there — never the freshly rendered snippet
    :func:`activate` would have PROPOSED had nothing already existed.
    ``None`` only when nothing matches (should not happen when this is
    called after confirming an idempotent hit, but never asserted —
    the caller falls back to the proposed entry rather than crash)."""
    hooks_cfg = data.get("hooks") or {}
    for item in hooks_cfg.get(event) or []:
        if not isinstance(item, dict) or item.get("matcher") != matcher:
            continue
        for h in item.get("hooks") or []:
            if isinstance(h, dict) and h.get("command") == command:
                return item
    return None


def _merge_snippet(data: dict, snippet: str, command: str) -> tuple[dict, bool]:
    """Insert ``snippet``'s event entry into ``data["hooks"][event]``
    unless (matcher, command) is ALREADY registered together, ANYWHERE
    in that event's array: idempotent only when both match; the same
    ``command`` found under a DIFFERENT matcher — including an item
    whose ``matcher`` key is itself missing or null (fold r2, item D /
    Astra 6's second hole) — is a refusal naming both, CHECKED BEFORE
    the same-matcher idempotence check (fold r2: Astra 6's first hole —
    a MIXED settings array carrying this command under both the right
    matcher and a wrong one, in either array order, must never read as
    "already registered" just because a same-matcher hit also exists).
    Never silently accepted (it would leave the guard registered for
    the wrong tool set) and never silently rewritten (that would touch
    a registration this call does not own). Returns ``(data, False)``
    unchanged when already present under the SAME matcher."""
    event, new_entry = _snippet_fragment(snippet)
    matcher = new_entry.get("matcher")
    hooks_cfg = dict(data.get("hooks") or {})
    event_list = list(hooks_cfg.get(event) or [])
    same_matcher_hit = False
    conflict_desc: str | None = None
    for item in event_list:
        if not isinstance(item, dict):
            continue
        item_matcher = item.get("matcher")
        for h in item.get("hooks") or []:
            if isinstance(h, dict) and h.get("command") == command:
                if item_matcher == matcher:
                    same_matcher_hit = True
                elif conflict_desc is None:
                    conflict_desc = repr(item_matcher) if isinstance(item_matcher, str) else "no matcher"
    if conflict_desc is not None:
        raise HookActivationError(
            f"{command} is already registered under matcher {conflict_desc}, "
            f"expected {matcher!r} — deactivate first"
        )
    if same_matcher_hit:
        return data, False
    event_list = event_list + [new_entry]
    hooks_cfg[event] = event_list
    merged = dict(data)
    merged["hooks"] = hooks_cfg
    return merged, True


def _remove_command(data: dict, event: str, matcher: str, command: str) -> tuple[dict, bool]:
    """The deactivate-side twin of :func:`_merge_snippet` (D-a — deactivate
    is surgical, never a whole-file restore): removes exactly the hook
    dict whose ``command`` equals ``command``, inside the ``event`` item
    whose ``matcher`` equals ``matcher`` — this record's own
    registration, and only it. If that item's ``hooks`` list still has
    other commands afterwards, the item stays with the survivors; it is
    dropped only when its list empties, and the ``event`` key itself is
    dropped only when ITS list empties (so a deactivation that undoes
    the only entry ever added restores the file to exactly what it
    looked like before — no stray empty containers). Every other item,
    every other event, and every other key on ``data`` is untouched
    byte-for-byte in content. Callers must confirm (via
    :func:`_registered_matcher_for`) that ``command`` really IS
    registered under ``matcher`` before calling this — it silently
    reports "unchanged" for a matcher mismatch, exactly like a genuine
    absence, which is why :func:`deactivate` never calls this without
    that check first (fold r2, item D's removal-side half)."""
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
    unlink_settings: bool = False,
    backup_path: Path | None = None,
    backup_bytes: bytes | None = None,
    remove_backup: Path | None = None,
    prune_backups: tuple[Path, ...] = (),
) -> None:
    """THE single function that performs every raw filesystem mutation
    under the user's Claude runtime directory. Every other function in
    this module only computes WHAT should happen; this is the only
    place any of it actually lands on disk. The caller
    (``verbs.hook_activate``/``hook_deactivate``) invokes this module's
    calls from INSIDE the same ``with _ledger_write(home)`` span the
    ledger's own history-entry write uses, so ``tests/
    test_lock_invariant.py``'s walker finds this function lock-reachable
    directly — no ``NOT_REPO_TRUTH`` exemption needed (these writes
    still are never ledger TRUTH in content — the ledger's own receipt
    is the separate history-entry write below — but "not ledger truth"
    and "not lock-reachable" are different questions; only the second
    one is what that exemption list is for).

    Each of ``link``/``settings_path``/``backup_path``/``remove_backup``/
    ``prune_backups`` is its OWN independent effect — a single call may
    combine them, but :func:`activate`/:func:`deactivate` (fold r2) each
    fire them as SEPARATE calls in a deliberate order (see the module
    docstring), never bundled, so a caller's own eager progress-marking
    lines up one-to-one with one raw effect per call. ``backup_bytes``
    is the CALLER's already-read bytes to preserve as the backup — this
    function never reads ``settings_path`` itself to decide what the
    backup should contain, closing the late-read lost-update window a
    re-read would open. ``unlink_settings``/``remove_backup`` are undo
    primitives ("this call created a file and must now un-create it")
    — never used on any success path; both are ``missing_ok=True``
    underneath (via ``Path.unlink(missing_ok=True)``), tolerating a
    marked-but-never-landed effect (see the module docstring's eager-
    marking paragraph)."""
    if link is not None:
        link.parent.mkdir(parents=True, exist_ok=True)
        if unlink:
            link.unlink(missing_ok=True)
        else:
            assert link_target is not None
            tmp = link.parent / f".{link.name}.tmp-{os.getpid()}-{time.time_ns()}"
            os.symlink(link_target, tmp)
            try:
                os.replace(tmp, link)
            except OSError:
                # Opus N10 (ii): an `os.replace` failure must never
                # leave the temp symlink littering `hooks/` for the
                # doctor (and every future listing) to trip over.
                tmp.unlink(missing_ok=True)
                raise
    if settings_path is not None:
        if unlink_settings:
            settings_path.unlink(missing_ok=True)
        elif settings_bytes is not None:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            fsops.atomic_write(settings_path, settings_bytes)
    if backup_path is not None and backup_bytes is not None:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        fsops.atomic_write(backup_path, backup_bytes)
    if remove_backup is not None:
        remove_backup.unlink(missing_ok=True)
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
    module docstring for the three steps, the prepare-first phase
    split, and the undo-on-failure guarantee."""
    home = Path(home)
    claude_dir = _absolute_claude_dir(claude_dir)
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

    # ------------------------------------------------- Phase 1: prepare
    # Fold r2, item A: everything decidable WITHOUT touching disk lives
    # here — the byte check, the symlink's current classification, the
    # merge/matcher decision, the backup path. Zero raw writes below
    # this point until Phase 2 begins.
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

    classification = _classify_symlink(link, script_abs)
    if classification == "conflict":
        raise HookActivationError(
            f"{link} already exists and does not point at {script_abs} — "
            "refusing to overwrite (a different hook or a hand-edit owns it)"
        )
    needs_placement = classification == "absent"

    start_bytes: bytes | None = None
    command: str | None = None
    entry_json: str | None = None
    script_sha256: str | None = None
    entry_event: str | None = None
    matcher = None
    changed = False
    new_settings_bytes: bytes | None = None
    backup_path: Path | None = None
    if register:
        start_bytes, data, problem = _read_settings(settings_path)
        if problem is not None:
            raise HookActivationError(f"{problem} — settings.json left untouched")

        command = _command_for(name, claude_dir)
        snippet = settings_snippet(list(tools), name, claude_dir=claude_dir)
        entry_event, entry = _snippet_fragment(snippet)
        matcher = entry.get("matcher")
        entry_json = json.dumps(entry, sort_keys=True)
        script_sha256 = hashlib.sha256(current_script.encode("utf-8")).hexdigest()
        # May raise HookActivationError (matcher conflict) -- still
        # Phase 1, zero writes so far.
        merged, changed = _merge_snippet(data, snippet, command)
        if changed:
            new_settings_bytes = (json.dumps(merged, indent=2) + "\n").encode("utf-8")
            if start_bytes is not None:
                backup_path = claude_dir / f"settings.json.self-learn-bak.{time.time_ns()}"
        else:
            # Idempotent: fold r2, item F (Astra 9) -- the receipt must
            # show the ACTUAL registered item, not the proposed one.
            actual = _registered_item(data, entry_event, matcher, command)
            if actual is not None:
                entry_json = json.dumps(actual, sort_keys=True)

    # -------------------------------------------------- Phase 2: writes
    progress = _Progress(link=link, settings_path=settings_path, start_bytes=start_bytes)
    try:
        # (1) backup file -- independent of the symlink; every logical
        # refusal above already fired in Phase 1, so by the time we are
        # here writing it is safe.
        if changed and backup_path is not None:
            progress.backup_path = backup_path
            progress.backup_written = True
            assert start_bytes is not None
            _write_claude_runtime(backup_path=backup_path, backup_bytes=start_bytes)

        # (2) symlink placement
        if needs_placement:
            progress.link_placed = True
            _write_claude_runtime(link=link, link_target=script_abs, unlink=False)
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
            # O-2b: `ActivationResult.backup_note` is what the CALLER's
            # own `hook-activated` history entry records (`verbs.
            # _hook_commit_or_undo` writes `result.backup_note` verbatim
            # as the entry's `note`) — left at its dataclass default here
            # before this fix, this branch's history entry read "no
            # settings.json change (already registered)" on a record
            # that was never registered at all, a false statement no
            # caller had ever exercised (`hook_activate` hardcoded
            # `register=True`, so this early return was unreached until
            # O-2b's `batch._dispatch` became the first caller to pass
            # `register=False`). The step's own detail text is the same
            # truthful sentence, reused so the two can never drift.
            #
            # Fold r1 (F1): every reader of this SAME string --
            # `ItemResult.detail` (via `hook_result.post_notes`), the
            # `hook-activated` history entry's own `note`, and the CLI's
            # printed line (which just echoes `ItemResult.detail`) --
            # must name the two manual steps a human still owes (route's
            # own Apply text already names them for the human path;
            # `verbs._hook_manual_steps` is the one place that renders
            # them, reused here so the two can never drift apart).
            manual_snippet = settings_snippet(list(tools), name, claude_dir=claude_dir)
            manual_steps = verbs._hook_manual_steps(manual_snippet, name)  # noqa: SLF001
            delegated_note = (
                "activation is delegated but switched off "
                "(overseer.hook_activation is false) — placed only; "
                "registration and check are the human's two manual "
                "steps: " + " ".join(manual_steps[1:])
            )
            steps.append(StepReceipt("delegated", delegated_note))
            return ActivationResult(
                steps=tuple(steps), progress=progress, backup_note=delegated_note,
            )

        # [CHECK] replay against the placed SYMLINK, BEFORE registering
        # -- a dangling or wrong-target link (or a broken guard) must
        # never be written into settings.json.
        bucket_dir = path.parent.parent
        examples = _examples_for(record, bucket_dir)
        n_examples = len(examples.get("allow", []) or []) + len(examples.get("deny", []) or [])
        mismatches = replay_examples(link, examples)
        if mismatches:
            raise HookActivationError(
                "guard replay failed against the placed symlink — aborting "
                "before registering (13 §7.4):\n  " + "\n  ".join(mismatches)
            )

        # (3) settings replace
        if changed:
            assert new_settings_bytes is not None
            progress.settings_written = True
            _write_claude_runtime(settings_path=settings_path, settings_bytes=new_settings_bytes)
            backup_note = str(backup_path) if backup_path is not None else (
                "settings.json created — no prior file to back up"
            )
            steps.append(
                StepReceipt(
                    "registered",
                    f"inserted the PreToolUse entry for {name}: {entry_json} "
                    f"(script {script_abs}, sha256 {script_sha256})",
                )
            )
        else:
            backup_note = "no settings.json change (already registered)"
            steps.append(
                StepReceipt(
                    "registered",
                    f"{command} already registered (idempotent): {entry_json} "
                    f"(script {script_abs}, sha256 {script_sha256})",
                )
            )

        # (4) doctor verdict
        verdict, message = selfcheck._check_hooks(home, claude_dir)  # noqa: SLF001
        if verdict is not selfcheck.Verdict.PASS:
            raise HookActivationError(
                f"registration did not verify as live: {message}"
            )

        reload_caveat = "Claude Code's own reload of settings.json was NOT observed (FW-154)"
        if n_examples:
            step_label = "activation-checked"
            replay_status: Literal["ran", "skipped-no-examples"] = "ran"
            replay_note = f"{n_examples} example(s) replayed clean against the symlink"
        else:
            # Fold r1, D-e; fold r2, item G: honest either way -- a
            # record with no persisted examples never reads as "replay
            # clean", and the STEP LABEL itself (not only the detail
            # text) says a replay never ran.
            step_label = "doctor-checked"
            replay_status = "skipped-no-examples"
            replay_note = (
                "no examples recorded on this record — replay skipped; "
                "doctor verdict governs"
            )
        steps.append(
            StepReceipt(
                step_label,
                f"{replay_note}; the doctor confirms the approved bytes at "
                "the host path and that the symlink resolves — it does not "
                "read the bytes through the symlink itself; " + reload_caveat,
            )
        )
        return ActivationResult(
            steps=tuple(steps),
            backup_path=backup_path,
            backup_note=backup_note,
            hook_registered_entry=entry_json,
            hook_script_path=str(script_abs),
            hook_script_sha256=script_sha256,
            replay=replay_status,
            reload_caveat=reload_caveat,
            progress=progress,
        )
    except BaseException as exc:
        residual = _undo(progress)
        for line in residual:
            exc.add_note(line)
        raise


def deactivate(
    home: Path | str,
    record_id: str,
    *,
    claude_dir: Path,
) -> ActivationResult:
    """Reverse :func:`activate`: surgically remove only this hook's own
    registration from ``settings.json`` (every other registration —
    this record's siblings, another record's, or a human's own hand-
    edit — is left byte-for-byte untouched, D-a), THEN remove the
    symlink (only if it still points at the expected target) — fold r2,
    item C's deliberately REVERSED write order relative to
    :func:`activate` (settings first, symlink second): a half-state
    where the registration is gone but the (now-inert, unreferenced)
    symlink still sits in ``hooks/`` is strictly safer than one where
    the symlink is gone but ``settings.json`` still names it, which
    would leave Claude Code invoking a dangling command. Never restores
    a whole-file backup: the settings.json backup a REGISTRATION wrote
    is kept purely as a human/rollback artefact, never read back by
    this function. A command found registered under a DIFFERENT
    matcher than this record's own is a refusal naming the matcher
    found — fold r2, item D's removal-side half — never silently
    reported as "already absent"."""
    home = Path(home)
    claude_dir = _absolute_claude_dir(claude_dir)
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
    tools = meta.get("tools")
    # Fold r2, item H (Opus N9): the same two-key completeness check
    # `activate` has always required -- deactivate used to accept a
    # record with `script_path` but no `tools`, which yields an empty
    # matcher (`"|".join([])`) and takes the exact silent-absence path
    # item D's own fix closes below for a DIFFERENT reason.
    if not meta.get("script_path") or not tools:
        raise HookActivationError(
            f"record {record_id}'s hook routing is incomplete (no "
            "script_path/tools) — re-route before deactivating"
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

    # ------------------------------------------------- Phase 1: prepare
    classification = _classify_symlink(link, script_abs)

    command = _command_for(name, claude_dir)
    snippet = settings_snippet(list(tools), name, claude_dir=claude_dir)
    event, entry = _snippet_fragment(snippet)
    matcher = entry.get("matcher")
    # `settings_snippet` always sets a string "matcher" key -- narrows
    # the type for pyright, not a runtime-load-bearing check.
    assert isinstance(matcher, str)

    start_bytes, data, problem = _read_settings(settings_path)
    settings_changed = False
    new_settings_bytes: bytes | None = None
    if problem is None:
        found_matchers = _registered_matcher_for(data, event, command)
        if isinstance(found_matchers, list):
            # Fold r3, S4: collect-all — refuse when ANY entry names a
            # matcher other than this record's own, even when the own
            # matcher ALSO appears elsewhere in the same array (D-a's
            # ownership boundary must not depend on array order).
            foreign = [m for m in found_matchers if m != matcher]
            if foreign:
                desc = repr(foreign[0]) if isinstance(foreign[0], str) else "no matcher"
                raise HookActivationError(
                    f"{command} is also registered under matcher {desc}, "
                    f"expected {matcher!r} — refusing to remove a "
                    "registration this call does not own (deactivate the "
                    "record that owns it, or fix settings.json by hand)"
                )
            merged, settings_changed = _remove_command(data, event, matcher, command)
            if settings_changed:
                new_settings_bytes = (json.dumps(merged, indent=2) + "\n").encode("utf-8")

    # -------------------------------------------------- Phase 2: writes
    # (settings replace THEN symlink removal -- see this function's own
    # docstring for why the order is reversed relative to activate())
    progress = _Progress(link=link, settings_path=settings_path, start_bytes=start_bytes)
    try:
        if settings_changed:
            assert new_settings_bytes is not None
            progress.settings_written = True
            _write_claude_runtime(settings_path=settings_path, settings_bytes=new_settings_bytes)
            steps.append(
                StepReceipt(
                    "unregistered",
                    f"removed the PreToolUse entry for {name} (surgical — "
                    "every other registration untouched)",
                )
            )
            backup_note = f"removed the {matcher!r} registration for {command}; symlink {link}"
        elif problem is not None:
            steps.append(
                StepReceipt("unregistered", f"{problem} — settings.json left untouched")
            )
            backup_note = f"{problem} — settings.json left untouched"
        else:
            steps.append(StepReceipt("unregistered", f"{command} already absent (idempotent)"))
            backup_note = "no settings.json change (already absent)"

        if classification == "matches":
            progress.link_removed = True
            progress.link_target = script_abs
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

        return ActivationResult(
            steps=tuple(steps), backup_path=None, backup_note=backup_note, progress=progress
        )
    except BaseException as exc:
        residual = _undo(progress)
        for line in residual:
            exc.add_note(line)
        raise
