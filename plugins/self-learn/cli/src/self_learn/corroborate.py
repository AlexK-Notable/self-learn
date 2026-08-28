"""U-corrob — the in-memory corroborator of an `SdkOutcome`'s captured
`tool_events` against the filesystem census the caller already computes.

`S-44` (03-decisions.md): "the filesystem diff remains the authority.
Tool events are corroboration, never the primary record of what the
model wrote." This module never adjudicates -- it reports a distinct-
resolved-path AGREEMENT check, counts only, and it never changes what a
run does (`UN4`).

Top level (`src/self_learn/corroborate.py`), not `invocation_sdk/`
(spec §4.0): this module consumes OUTCOMES already returned by the
invocation seam and a filesystem census the caller already computes --
it is not part of that seam.

**The one rule that makes everything else safe (spec §6.1):** no file is
ever read back. Every input is an `SdkOutcome` attribute already in
memory at the call site, or a filesystem census the caller already
took. `RunEvidence` never opens a path, never globs a directory, never
reads a byte off disk.

Import-bounded: stdlib + `.invocation_sdk.charter` (the write family,
`W`) + `.sdksession.toolpaths` (`extract_target_path`, the same
function both charters use to decide "which key names the path") only
-- this module spells no other import, at SOURCE level: no `.worker`,
no `.miner`, no `.invocation_sdk.events`, no `self_learn_ui` anywhere
in this file.

**That claim is about what this file WRITES, not what importing it
PULLS IN (code gate r1, M-2).** `.invocation_sdk.charter` is a
sub-import of the `invocation_sdk` PACKAGE -- `invocation_sdk/
__init__.py` eagerly imports `backend.py`, which imports `worker` (and
`provider`) at ITS top level. `import self_learn.corroborate` therefore
transitively loads `worker.py` (and everything IT imports) regardless
of this module's own two-line import list. This is why the two
relative imports below sit AFTER `RunEvidence`'s full definition, not
before it: `worker.py`'s own top-level `from .corroborate import
MISMATCH, NO_EVIDENCE, RunEvidence` re-enters this module mid-exec via
that same transitive chain, and needs all three names already bound
when it does. See `test_m2_fresh_interpreter_import_does_not_
circular_import`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# code gate r1 N-1: `__all__` now names all three public symbols --
# `NO_EVIDENCE`/`MISMATCH` are genuinely part of the public contract
# (imported by name from both `worker.py` and `miner.py`), so
# `["RunEvidence"]` alone was not the truth.
__all__ = ["RunEvidence", "NO_EVIDENCE", "MISMATCH"]

#: The two verdict tags `RunEvidence.verdict` can return, alongside
#: `None` ("say nothing"). A caller wires each tag to its own
#: surface-specific wording (`{fs} file(s) on disk` on the worker,
#: `{fs} artifact(s) in the spool` on the reader) -- this module spells
#: neither noun, only the fact that decides between them.
NO_EVIDENCE = "no-evidence"
MISMATCH = "mismatch"


class RunEvidence:
    """One invocation's write-family corroboration state.

    `RunEvidence(root, *, flat)` -- `root` is the granted write root the
    caller already knows (`worker.stage_dir()`, `miner.spool_dir()`);
    `flat` selects which surface's filesystem census this evidence must
    mirror (spec §6.2's table, `COR13`):

    - `flat=True` (the worker): a resolved accepted path counts as
      **inside** iff its PARENT is exactly `root` -- mirroring
      `staged_paths()`'s deliberately flat `iterdir()` listing, never
      the grant's own recursive `Edit(/{stage_dir()}/**)` shape. A
      nested-but-inside-root path (e.g. `root/sub/x.json`) lands in
      NEITHER `inside` nor `outside`: the flat census cannot see it, and
      it is not out of scope either.
    - `flat=False` (the miner-reader): a resolved accepted path counts
      as **inside** iff it is under `root` at ANY depth -- mirroring the
      recursive `rglob` census and the equally recursive
      `write_globs=(f"{spool_dir}/**",)` grant.

    Attributes, all set only by :meth:`observe`:

    - ``seen`` -- an outcome was observed at all.
    - ``failure`` -- the observed outcome's ``failure`` field.
    - ``events_present`` -- the outcome HAS a ``tool_events`` attribute
      at all (``hasattr``, never truthiness -- a bare ``Outcome`` and an
      ``SdkOutcome(tool_events=())`` must not collapse into one case).
    - ``had_events`` -- that attribute, if present, held >= 1 event.
    - ``inside`` / ``outside`` -- DISTINCT RESOLVED accepted write-family
      paths, never event counts (a ``Write`` then ``Edit`` on one staged
      file is two events for one path).
    - ``unresolved`` -- write-family ``tool_use`` events with no paired
      ``tool_result``.
    """

    def __init__(self, root: Path, *, flat: bool) -> None:
        self._root = Path(root).resolve()
        self._flat = flat
        self.seen = False
        self.failure: str | None = None
        self.events_present = False
        self.had_events = False
        self.inside: set[str] = set()
        self.outside: set[str] = set()
        self.unresolved = 0

    def observe(self, outcome: Any) -> None:
        """Fold one `SdkOutcome` (or any bare stand-in) into this
        evidence. Never raises -- an outcome with no `tool_events`
        attribute at all (`events_present=False`) is a valid, silent
        input (`COR6`), not an error."""
        self.seen = True
        self.failure = getattr(outcome, "failure", None)
        self.events_present = hasattr(outcome, "tool_events")
        events = getattr(outcome, "tool_events", ()) or ()
        self.had_events = bool(events)
        if not events:
            return

        # code gate r1 N-2: a MALFORMED event (not a dict at all -- a
        # stray string, say) must be skipped, never raised on. `observe`
        # is documented "Never raises"; before this fix that promise
        # held only for the documented `events_present=False` case, not
        # for garbage INSIDE a present `tool_events` tuple.
        results_by_id: dict[str, dict[str, Any]] = {}
        uses: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = event.get("kind")
            if kind == "tool_result":
                tool_use_id = event.get("tool_use_id")
                if isinstance(tool_use_id, str):
                    results_by_id[tool_use_id] = event
            elif kind == "tool_use":
                uses.append(event)

        for use in uses:
            if use.get("name") not in W:
                continue
            use_id = use.get("id")
            result = results_by_id.get(use_id) if isinstance(use_id, str) else None
            if result is None:
                self.unresolved += 1
                continue
            if result.get("is_error"):
                continue
            # N-2: a malformed `input` (a string, say, instead of a
            # mapping) must be skipped, never raised on --
            # `extract_target_path` calls `.get(key)` on it, which is
            # not a `str` method. A MISSING `input` (`None`) is the
            # normal, well-formed "no target" case and still falls
            # through to `extract_target_path({})` -> `None`.
            tool_input = use.get("input")
            if tool_input is None:
                tool_input = {}
            if not isinstance(tool_input, dict):
                continue
            raw_target = extract_target_path(tool_input)
            if raw_target is None:
                continue
            resolved = self._resolve(raw_target)
            if resolved is None:
                continue
            classification = self._classify(resolved)
            if classification == "inside":
                self.inside.add(str(resolved))
            elif classification == "outside":
                self.outside.add(str(resolved))
            # "neither" -- a nested-but-inside-root write on a flat
            # surface -- is counted in neither set (`COR13`).

    def _resolve(self, raw_target: str) -> Path | None:
        # `P-b` (charter.py): resolve the trusted PARENT only, never the
        # leaf -- the leaf is exactly where a planted symlink would
        # rebase the expectation.
        #
        # code gate r1 N-2: spec §6.2 promises a RELATIVE target
        # resolves against `root`, not the process's CWD. `Path.resolve()`
        # on a relative path resolves against `os.getcwd()` by itself --
        # a bare `p.parent.resolve()` on a relative `raw_target` silently
        # answered "relative to wherever this process happens to be
        # running from" instead. Anchor a relative path onto `root`
        # BEFORE the `P-b` parent-resolve; an already-absolute path is
        # unaffected (`Path.__truediv__` on an absolute right-hand side
        # is a no-op left-discard, but we only ever prefix a RELATIVE
        # `p` here, so that edge case never arises).
        p = Path(raw_target)
        if not p.is_absolute():
            p = self._root / p
        try:
            return p.parent.resolve() / p.name
        except OSError:
            return None

    def _under_root(self, resolved: Path) -> bool:
        try:
            resolved.relative_to(self._root)
        except ValueError:
            return False
        return True

    def _classify(self, resolved: Path) -> str:
        under_root = self._under_root(resolved)
        if not under_root:
            return "outside"
        if not self._flat:
            return "inside"
        return "inside" if resolved.parent == self._root else "neither"

    def _should_emit(self) -> bool:
        # Rule 1 (spec §6.3): nothing at all unless an outcome was seen
        # and it did not fail. Rule 2: nothing at all unless the outcome
        # even HAS a `tool_events` attribute.
        return self.seen and self.failure is None and self.events_present

    def verdict(self, fs_count: int) -> str | None:
        """The primary verdict tag for this evidence against `fs_count`
        (the caller's own filesystem census) -- `NO_EVIDENCE`,
        `MISMATCH`, or `None` ("say nothing"). Independent of
        :meth:`outside_paths`, which the caller checks separately
        (`COR5` -- the two lines are not mutually exclusive)."""
        if not self._should_emit():
            return None
        if not self.had_events:
            return NO_EVIDENCE
        if len(self.inside) != fs_count:
            return MISMATCH
        return None

    def outside_paths(self) -> frozenset[str]:
        """The distinct resolved paths reported accepted but outside
        `root` -- empty unless this evidence would emit at all (same
        rule-1/rule-2 guard as :meth:`verdict`)."""
        if not self._should_emit():
            return frozenset()
        return frozenset(self.outside)


# M-2 (code gate r1, 2026-08-28): these two imports must come AFTER
# `RunEvidence`'s full definition, not before it. `W`/`extract_target_
# path` are referenced only inside method BODIES (`observe`), resolved
# at CALL time via the module's global namespace -- never at class-
# DEFINITION time -- so the class parses fine without them existing
# yet. Every shipped entry path imports `worker` (or `miner`) before
# ever touching `corroborate` directly, and `worker.py`/`miner.py` both
# do `from .corroborate import MISMATCH, NO_EVIDENCE, RunEvidence`.
# Placed BEFORE `RunEvidence`, this import statement re-enters
# `self_learn.invocation_sdk` (`.charter` triggers `invocation_sdk/
# __init__.py` -> `backend.py` -> `from .. import provider, worker` ->
# `worker.py`'s own top-level `from .corroborate import ...`) while
# `corroborate` is still mid-exec and has not yet defined `RunEvidence`
# -- `ImportError: cannot import name 'RunEvidence' from partially
# initialized module`. Moved here, the cascade finds all three names
# already bound. Verified with a FRESH interpreter, not just this
# process's already-warm `sys.modules` cache (which would silently
# hide the defect): `test_m2_fresh_interpreter_import_does_not_
# circular_import`.
from .invocation_sdk.charter import W
from .sdksession.toolpaths import extract_target_path
