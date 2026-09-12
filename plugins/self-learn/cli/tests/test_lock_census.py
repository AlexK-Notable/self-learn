"""S-62 / §7.2a.5(1), H-8: the recover-or-refuse contract's own
fail-closed census — SEPARATE from ``test_lock_invariant.py``'s
call-graph walker (the spec is explicit: "pinned by a SEPARATE
fail-closed census test, not by bending the walker"). That walker
proves every mutating leaf sits under SOME lock; it cannot express
WHICH lock-acquisition primitive a site uses, so it would wave through
a site that still takes a bare ``gitops.commit_lock(<ledger home>)``
instead of converting to ``intents.ledger_write`` — exactly the bug
this sprint's contract exists to close.

This module finds every ``commit_lock`` CALL under ``src/self_learn/``
— both spellings, the attribute form ``gitops.commit_lock(`` used
everywhere else, and the bare ``commit_lock(`` name that only resolves
inside ``gitops.py`` itself (``push_with_retry``'s host-repo branch,
the census's own positive control per §7.2a.5(1)) — and checks it
against :data:`_CENSUS` by ``(module, qualified function name)``.
Fail-closed BOTH ways: an unlisted call site turns the test red (a new,
un-reviewed ``commit_lock`` site), and so does a listed entry with no
matching call site left (a stale exemption nobody re-checked after a
rename or deletion) — the same discipline
``test_lock_invariant.test_the_exemption_list_cannot_rot`` applies to
``NOT_REPO_TRUTH``.

The walker cannot see ORDERING (a ledger-exempt site recovering before
the caller's own first mutation) — that is proven by §7.2a's mutation
test plan, not a structural test; this one only proves WHICH primitive
each site uses."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "self_learn"

#: (module stem, qualified function name) -> category, one entry per
#: real ``commit_lock`` call site at `a221d3c` + this sprint's guard
#: lane. "wrapper" is the ledger-write seam itself (§7.2a.5(1)(a));
#: "ledger-exempt" is a named ledger-scoped site on the exempt list
#: (§7.2a.5(1)(b)) — it takes the lock the way the wrapper's callers do
#: but must not recurse into a second recovery pass; "host-repo" is a
#: site whose *repo* argument is a HOST checkout, never the ledger, so
#: the contract (ledger-scoped by definition) does not reach it
#: (§7.2a.5(1)(c)). A qualified name may own more than one real call
#: site (``ledger.init_home`` takes it twice — steps 3 and 5 — and
#: ``verbs.recompile`` twice too); the census names the FUNCTION once,
#: not each line.
_CENSUS: dict[tuple[str, str], str] = {
    ("intents", "ledger_write"): "wrapper",
    ("intents", "recover"): "ledger-exempt",
    ("intents", "clear_stopped"): "ledger-exempt",
    ("ledger", "init_home"): "ledger-exempt",
    ("gitops", "push_with_retry"): "host-repo",
    ("verbs", "commit_drift"): "host-repo",
    ("verbs", "recompile"): "host-repo",
}


class _Found(ast.NodeVisitor):
    """Collects every ``commit_lock`` `ast.Call`, attributed to its
    INNERMOST enclosing function by qualified dotted name (a nested
    closure inside a verb gets its own name, never its parent's —
    ``generic_visit`` walks each node exactly once, so a nested
    `FunctionDef` never has its calls double-counted against the
    function that contains it)."""

    def __init__(self, module: str, *, bare_matches: bool) -> None:
        self.module = module
        self.bare_matches = bare_matches
        self.stack: list[str] = []
        #: (qualname, lineno, form) — form is "attribute" or "bare",
        #: kept so the positive control can assert BOTH spellings are
        #: exercised somewhere in the whole census, not just one.
        self.sites: list[tuple[str, int, str]] = []

    def _visit_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        for child in ast.iter_child_nodes(node):
            self.visit(child)
        self.stack.pop()

    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        form = None
        if isinstance(func, ast.Attribute) and func.attr == "commit_lock":
            form = "attribute"
        elif (
            self.bare_matches
            and isinstance(func, ast.Name)
            and func.id == "commit_lock"
        ):
            form = "bare"
        if form is not None and self.stack:
            self.sites.append((".".join(self.stack), node.lineno, form))
        self.generic_visit(node)


def _collect() -> dict[tuple[str, str], list[tuple[int, str]]]:
    """(module, qualname) -> [(lineno, form), ...] for every real call
    site found under ``src/self_learn/``."""
    found: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for path in sorted(_SRC.glob("*.py")):
        module = path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # The bare `Name` spelling only resolves inside `gitops.py` —
        # every other module imports `gitops` as a module and can only
        # spell this call `gitops.commit_lock(`, so restricting the
        # bare-form detector to that one file is precision, not a
        # narrower net (a bare `commit_lock(` anywhere else would be a
        # `NameError` at runtime, not a real site to classify).
        visitor = _Found(module, bare_matches=module == "gitops")
        visitor.visit(tree)
        for qualname, lineno, form in visitor.sites:
            found.setdefault((module, qualname), []).append((lineno, form))
    return found


class TestLockCensus:
    def test_every_found_site_is_on_the_census(self):
        found = _collect()
        unlisted = sorted(set(found) - set(_CENSUS))
        assert not unlisted, (
            "commit_lock call site(s) not on the H-8 census (module, "
            f"function): {unlisted} — a new site must convert to "
            "`intents.ledger_write` (if it acquires the LEDGER lock) or "
            "be added to _CENSUS with its category and reason (if it is "
            "a host-repo acquisition, or a named ledger-exempt site per "
            "§7.2a.5(1))"
        )

    def test_every_census_entry_still_matches_a_real_site(self):
        found = _collect()
        stale = sorted(set(_CENSUS) - set(found))
        assert not stale, (
            f"H-8 census entries with no matching call site left: {stale} "
            "— a rename or deletion made the exemption stop matching "
            "what it exempted; update or remove the entry rather than "
            "leave it looking like a considered decision for something "
            "that no longer exists"
        )

    def test_the_wrapper_is_exactly_one_site(self):
        wrapper_entries = [k for k, v in _CENSUS.items() if v == "wrapper"]
        assert wrapper_entries == [("intents", "ledger_write")]

    def test_positive_control_the_bare_form_in_gitops_is_detected(self):
        """§7.2a.5(1): "the census's positive control is the bare
        `commit_lock(repo)` in `gitops.py`" — the attribute-form
        detector alone would miss it silently (a bare `Name` looks
        nothing like an `Attribute`), so this asserts the bare-form
        branch specifically fired, not just that SOME form of the
        push_with_retry site was found."""
        found = _collect()
        forms = {form for _, form in found[("gitops", "push_with_retry")]}
        assert "bare" in forms, (
            "push_with_retry's host-repo branch is the positive control "
            "for the bare `commit_lock(` spelling — it was not detected "
            "as bare, so the detector's bare-form branch is dead"
        )

    def test_ledger_write_itself_uses_the_attribute_form(self):
        """The wrapper's own acquisition is `gitops.commit_lock(home)`
        (intents.py cannot spell it bare — `commit_lock` is not a name
        in that module's scope), proving the attribute-form branch
        fires on the wrapper specifically, not only on host-repo sites."""
        found = _collect()
        forms = {form for _, form in found[("intents", "ledger_write")]}
        assert forms == {"attribute"}
