"""primitives.text -- ONE ``## Heading`` matcher (Sprint 1 M-J, plan v2
SS2 M-J).

``records.py`` and ``compilers.py`` already carried byte-identical
copies of this pattern, both correctly compiled with ``re.MULTILINE``
(so ``^``/``$`` bind to every line start/end inside a multi-line body,
not just the whole string's). ``ledger_ops.py`` carried a THIRD copy
missing that flag -- silently correct today only because its one call
site (``record_title``) matches line-by-line against already-split
single-line strings, where ``MULTILINE`` can never make a difference
(see ``tests/test_primitives.py``'s direct proof: applied to a whole
multi-line body via ``.findall()``, the non-``MULTILINE`` pattern misses
every heading but the first). One pattern, one place, so a future call
site that scans a whole body (the way ``compilers._body_sections``
always has) inherits the correct flags for free instead of by luck.
"""

from __future__ import annotations

import re

#: A markdown ``## `` heading line, body captured with trailing
#: whitespace stripped. ``re.MULTILINE`` is load-bearing: without it,
#: ``^``/``$`` anchor only to the start/end of the WHOLE string, so
#: ``.findall()``/``.finditer()`` against a multi-line body finds at
#: most the first heading (or none, if the body doesn't start with
#: one) -- every heading after the first is silently invisible.
HEADING_RE = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
