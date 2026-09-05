"""primitives.yamlio -- ONE round-trip YAML factory, ONE null policy
(Sprint 1 M-J, plan v2 SS2 M-J).

Five modules (``records.py``, ``ledger_ops.py``, ``hosts.py``,
``config.py``, ``compiled.py``) each built their own
``ruamel.yaml.YAML(typ="rt")`` instance for round-trip load/dump. They
were NOT all configured alike -- measured, not assumed, before this
move: ``records.py``/``ledger_ops.py`` share one shape
(``preserve_quotes=True``, ``width=4096``, a custom 2/4/2 sequence
indent, for the 02 SS1 example's byte-identical re-emission);
``hosts.py``/``config.py``/``compiled.py`` share a DIFFERENT shape
(``default_flow_style=False`` only -- ruamel's own default indent/width/
quote-preservation otherwise). Collapsing all five onto ONE fixed
config would silently rewrite ``hosts.yaml``/``config.yaml``/compiled
record on-disk formatting (line-wrap width, sequence indent, quote
style) that no defect in this move's list names -- a formatting
regression, not a fix. So :func:`rt_yaml` takes each caller's own
pre-existing knobs as explicit, opt-in keyword arguments: migrating a
call site to it changes nothing about that site's output.

What IS unified, unconditionally, for all five: the null policy. A bare
ruamel round-trip ``YAML(typ="rt")`` renders a Python ``None`` as an
empty scalar (``key:\\n``) unless a representer is registered for
``NoneType``; ``records.py``'s factory already did this (the reference
shape), ``ledger_ops.py``'s did not (A-class bug this move closes --
the only DIVERGENCE between two otherwise byte-identical factories).
Measured before applying it everywhere (2026-09, this move): no test in
either package byte-pins the bare-empty rendering at any of the five
call sites (``hosts.py``'s ``skills_root: None`` round-trip, a fresh
``Hosts`` registry; ``compiled.py``'s ``based_on_sha256: None``, the
pre-flight-observed-hash-absent row; ``config.py``'s writer never emits
``None`` today -- ``unset_leaf`` deletes the key outright rather than
nulling it) -- so applying the null policy to all five, not just
``ledger_ops.py``, is a safe uniform fix, not a guess.

**A second hazard, found empirically while writing this module's own
test (measured, not assumed -- exactly the discipline this whole move
is about): ``RoundTripRepresenter.add_representer`` is a ``@classmethod``
that mutates ``RoundTripRepresenter.yaml_representers``, a dict shared
by EVERY ``YAML(typ="rt")`` instance in the process** -- ruamel's own
API for registering a representer for a custom TYPE once, process-wide,
not for scoping one factory's behavior. Calling it the naive way (as an
early version of this function did) would mean the FIRST call to
:func:`rt_yaml` anywhere in a process silently changes how every OTHER
``YAML(typ="rt")`` instance in that same process renders ``None``
from then on -- including ``compilers.py:390``'s own untouched, explicitly
out-of-scope inline factory, and any ad-hoc ``YAML(typ="rt")`` a test
creates. :func:`rt_yaml` instead shadows the class dict with a fresh
INSTANCE dict (``y.representer.yaml_representers = {...}``) so the null
policy applies only to the ``YAML`` instance this call returns --
verified in ``tests/test_primitives.py`` by checking a freshly
constructed, unrelated ``YAML(typ="rt")`` renders the bare form
UNCHANGED after :func:`rt_yaml` has already been called.
"""

from __future__ import annotations

from ruamel.yaml import YAML


def _represent_none(representer, _data):
    return representer.represent_scalar("tag:yaml.org,2002:null", "null")


def rt_yaml(
    *,
    preserve_quotes: bool = False,
    width: int | None = None,
    sequence_indent: tuple[int, int, int] | None = None,
    default_flow_style: bool | None = None,
) -> YAML:
    """A round-trip ``YAML()`` instance with the null policy applied.
    Every other knob defaults to ruamel's own default and is opt-in --
    pass exactly the config the pre-migration factory at your call site
    used (see the module docstring's two shapes) so migrating changes
    nothing but the ``None`` rendering.

    The null policy is scoped to the returned instance ONLY -- see the
    module docstring's "second hazard" -- never registered through
    ``add_representer`` (a process-wide side effect)."""
    y = YAML(typ="rt")
    if preserve_quotes:
        y.preserve_quotes = True
    if width is not None:
        y.width = width
    if sequence_indent is not None:
        mapping, sequence, offset = sequence_indent
        y.indent(mapping=mapping, sequence=sequence, offset=offset)
    if default_flow_style is not None:
        y.default_flow_style = default_flow_style
    # Instance-level shadow, NOT `add_representer` (a classmethod that
    # would mutate the shared `RoundTripRepresenter.yaml_representers`
    # class dict -- see module docstring).
    y.representer.yaml_representers = dict(y.representer.yaml_representers)
    y.representer.yaml_representers[type(None)] = _represent_none
    return y
