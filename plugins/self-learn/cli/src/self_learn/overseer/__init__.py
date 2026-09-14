"""The overseer's own package (S-66, `03-decisions.md`).

O-1 (`population.py`) is the first unit: a pure case reader with no
ledger writes of its own. `coverage.yaml` under `<ledger>/overseer/` (13
§3 layout) is written by the overseer's RUNNER (O-3), inside its own
`intents.ledger_write` span, using `render_coverage`/`load_coverage`.

Deliberately no re-exports here (unlike `invocation/__init__.py`'s
pattern): `population.py` names its own main entry point `population`,
the SAME name as the module itself. Re-exporting it as
`self_learn.overseer.population` would rebind that attribute on this
package to the function, shadowing the submodule for any later
`import self_learn.overseer.population` / attribute access — while
`sys.modules['self_learn.overseer.population']` would still hold the
real module, `self_learn.overseer.population` (dotted attribute access)
would not, a confusing split (measured empirically while building this
unit). Import directly from the submodule instead:
`from self_learn.overseer.population import population, BlindCase, ...`.
"""

from __future__ import annotations
