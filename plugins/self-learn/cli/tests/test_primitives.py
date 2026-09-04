"""tests for ``self_learn.primitives`` (Sprint 1 M-J, plan v2 §2 M-J).

M-B built the leaf package and shipped ``chrono``; M-J adds ``text``
(the shared ``HEADING_RE``), ``yamlio`` (the shared round-trip YAML
factory + null policy) and ``truncate`` (the shared log rotator), and
migrates the 12 ``_now_iso``/4 ``_HEADING_RE``/5 YAML-factory/2
``_truncate_oldest`` sites this move names onto them.

Every test here proves something a docstring claim alone would not:
the MULTILINE bug is demonstrated directly against the regex (not
through ``ledger_ops.record_title``, whose per-line ``.match()`` call
never exercises ``MULTILINE`` either way — see the class docstring
below); the null policy is proven against actual dumped bytes; the P1
scan proves every one of the 21 migrated call sites is a genuine thin
facade, not a docstring claim, by inspecting each function's live
source.
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn.primitives import chrono, text, truncate, yamlio

CLI_SRC = Path(__file__).resolve().parent.parent / "src" / "self_learn"
UI_SRC = Path(__file__).resolve().parent.parent.parent / "ui" / "src" / "self_learn_ui"


# --------------------------------------------------------------- chrono


class TestChronoNowIso:
    def test_default_format_is_z_suffixed_no_microseconds(self):
        out = chrono.now_iso()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", out), out

    def test_explicit_now_is_not_resampled(self):
        """``telemetry._now_iso``'s whole reason to keep a ``now:``
        parameter: a caller with its own clock reading must get THAT
        reading formatted, never a fresh ``datetime.now()`` call."""
        fixed = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert chrono.now_iso(fixed) == "2020-01-01T00:00:00Z"

    def test_iso_format_constant_matches_what_now_iso_produces(self):
        """P1 anchor: the format lives in ONE constant a facade can
        reference instead of duplicating the literal (mutation control
        below proves the constant is what ``now_iso`` actually uses)."""
        fixed = datetime(2021, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
        assert chrono.now_iso(fixed) == fixed.strftime(chrono.ISO_FORMAT)

    def test_mutation_breaking_iso_format_breaks_now_iso(self, monkeypatch):
        monkeypatch.setattr(chrono, "ISO_FORMAT", "%Y/%m/%d")
        fixed = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert chrono.now_iso(fixed) == "2020/01/01"
        assert chrono.now_iso(fixed) != "2020-01-01T00:00:00Z"


# ----------------------------------------------------------------- text


class TestHeadingRePreventsTheMultilineBug:
    """M-J's ``primitives.text`` fix: ``ledger_ops.py`` carried a THIRD
    copy of this pattern missing ``re.MULTILINE`` alongside the two
    correct copies in ``records.py``/``compilers.py``. That module's
    only call site (``record_title``) matches line-by-line against an
    already-``.split("\\n")``-ed body, where ``MULTILINE`` can never
    bite (a single line has no embedded newline for ``^``/``$`` to
    differ over) — so the proof below deliberately does NOT go through
    ``record_title``. It exercises the regex directly against a whole
    multi-line body, and separately through ``compilers._body_sections``
    (which already used ``.finditer(body)`` on the full body and
    already had ``MULTILINE`` — the correct shape every call site now
    shares)."""

    BODY = (
        "## Trigger\n"
        "first section text\n"
        "## Instruction\n"
        "second section text\n"
        "## Context\n"
        "third section text\n"
    )

    def test_multiline_pattern_finds_every_heading(self):
        assert text.HEADING_RE.findall(self.BODY) == [
            "Trigger",
            "Instruction",
            "Context",
        ]

    def test_the_old_non_multiline_pattern_misses_non_leading_headings(self):
        """The exact bug being closed: the SAME pattern text, compiled
        WITHOUT ``re.MULTILINE`` (``ledger_ops.py``'s old copy), applied
        the same way (``.findall()`` on a whole body) -- misses every
        heading after the first, because ``^``/``$`` bind only to the
        start/end of the WHOLE string, not each line."""
        old_pattern = re.compile(r"^## +(.+?)\s*$")  # no MULTILINE
        assert old_pattern.findall(self.BODY) == []  # body doesn't START with ##

    def test_heading_re_is_compiled_with_multiline(self):
        assert text.HEADING_RE.flags & re.MULTILINE

    def test_mutation_dropping_multiline_reproduces_the_miss(self, monkeypatch):
        broken = re.compile(text.HEADING_RE.pattern)  # same text, no flag
        monkeypatch.setattr(text, "HEADING_RE", broken)
        assert text.HEADING_RE.findall(self.BODY) == []

    def test_compilers_body_sections_already_correct_shares_the_pattern(self):
        """``compilers.py``'s own call site was already right (whole-body
        ``.finditer``, already ``MULTILINE``) -- confirming a real
        consumer, not just the bare pattern, sees every heading.
        ``_body_sections`` wants a record-shaped object (``.body``);
        a bare namespace is enough, it never touches anything else."""
        from types import SimpleNamespace

        from self_learn.compilers import _body_sections

        sections = _body_sections(SimpleNamespace(body=self.BODY))
        assert set(sections) == {"Trigger", "Instruction", "Context"}


# --------------------------------------------------------------- yamlio


class TestRtYamlNullPolicy:
    def test_none_dumps_as_explicit_null_not_a_bare_scalar(self):
        y = yamlio.rt_yaml()
        import io

        buf = io.StringIO()
        y.dump({"a": None, "b": 1}, buf)
        assert buf.getvalue() == "a: null\nb: 1\n"

    def test_a_bare_yaml_without_the_policy_would_emit_the_empty_form(self):
        """Positive control: prove the null policy is doing something --
        an UNCONFIGURED ``YAML(typ="rt")`` (ledger_ops.py's old,
        divergent shape) renders the SAME dict as a bare empty scalar.
        This also proves ``rt_yaml``'s null policy is scoped to its own
        returned instance, never leaked process-wide onto an unrelated
        bare ``YAML(typ="rt")`` created after it (see
        ``primitives/yamlio.py``'s "second hazard" -- ``add_representer``
        would have mutated a class-level dict shared by every instance;
        this test runs in the SAME process as, and after, the tests
        above that already called :func:`yamlio.rt_yaml`)."""
        import io

        y = YAML(typ="rt")
        buf = io.StringIO()
        y.dump({"a": None, "b": 1}, buf)
        assert buf.getvalue() == "a:\nb: 1\n"

    def test_mutation_changing_the_representer_changes_every_caller(
        self, monkeypatch
    ):
        """A real mutation of the shipped module (not a reimplemented
        copy): ``rt_yaml()`` looks up ``_represent_none`` as a module
        global at CALL time, so patching it changes what every one of
        the 5 migrated factories renders for ``None`` -- proving the
        null policy is centrally wired, not copy-pasted per factory."""
        import io

        def _represent_as_tilde(representer, _data):
            return representer.represent_scalar("tag:yaml.org,2002:null", "~")

        monkeypatch.setattr(yamlio, "_represent_none", _represent_as_tilde)
        buf = io.StringIO()
        yamlio.rt_yaml().dump({"a": None}, buf)
        assert buf.getvalue() == "a: ~\n"


class TestRtYamlNullPolicyIsInstanceScopedNotProcessWide:
    """The second hazard found empirically while writing this module
    (``primitives/yamlio.py``'s own docstring): ``add_representer`` is a
    ``@classmethod`` that would mutate ``RoundTripRepresenter``'s CLASS
    dict, shared by every ``YAML(typ="rt")`` instance in the process --
    including ``compilers.py:390``'s own untouched, out-of-scope inline
    factory. ``rt_yaml`` shadows an INSTANCE dict instead; this proves
    the shadow actually stops the leak, using the real ruamel class
    (not a copy), in the same process as every other test in this file
    that already called :func:`yamlio.rt_yaml`."""

    def test_an_unrelated_bare_yaml_instance_is_unaffected(self):
        import io

        yamlio.rt_yaml()  # exercise the factory at least once first
        unrelated = YAML(typ="rt")
        buf = io.StringIO()
        unrelated.dump({"a": None}, buf)
        assert buf.getvalue() == "a:\n"

    def test_mutation_using_add_representer_would_leak_process_wide(self):
        """Positive control: the naive implementation this module's
        docstring warns against, demonstrated directly against the real
        ruamel class -- proving the test above would have caught it.
        Captures and restores the EXACT prior class-dict entry (rather
        than assuming it was absent) so this test cannot leave the
        shared ``RoundTripRepresenter`` class in a different state for
        whatever runs after it in the same pytest process."""
        from ruamel.yaml.representer import RoundTripRepresenter

        had_entry, original = type(None) in RoundTripRepresenter.yaml_representers, (
            RoundTripRepresenter.yaml_representers.get(type(None))
        )
        try:
            y = YAML(typ="rt")
            y.representer.add_representer(
                type(None),
                lambda r, _d: r.represent_scalar("tag:yaml.org,2002:null", "~"),
            )
            import io

            unrelated = YAML(typ="rt")
            buf = io.StringIO()
            unrelated.dump({"a": None}, buf)
            assert buf.getvalue() == "a: ~\n"
        finally:
            if had_entry:
                RoundTripRepresenter.yaml_representers[type(None)] = original
            else:
                RoundTripRepresenter.yaml_representers.pop(type(None), None)


class TestRtYamlPreservesPerCallerConfig:
    """The advisor-flagged hazard this factory exists to avoid: the five
    migrated call sites carry TWO distinct pre-existing shapes
    (measured, not assumed -- see ``primitives/yamlio.py``'s module
    docstring). Collapsing them onto one fixed config would silently
    rewrite ``hosts.yaml``/``config.yaml``/compiled-record formatting
    that no defect in this move's list names."""

    def test_records_style_knobs_are_opt_in_and_applied(self):
        y = yamlio.rt_yaml(preserve_quotes=True, width=4096, sequence_indent=(2, 4, 2))
        assert y.preserve_quotes is True
        assert y.width == 4096

    def test_hosts_style_call_gets_no_width_or_quote_override(self):
        """``hosts.py``/``config.py``/``compiled.py`` never set
        ``preserve_quotes``/``width``/a custom sequence indent -- only
        ``default_flow_style``. A caller that doesn't pass those knobs
        must not inherit ruamel's records-style-configured defaults."""
        y = yamlio.rt_yaml(default_flow_style=False)
        assert not y.preserve_quotes  # ruamel's own default (None, falsy)
        assert y.default_flow_style is False

    def test_two_call_shapes_produce_different_sequence_indent_on_disk(self):
        """The measured, real formatting difference the module docstring
        describes, proven on actual dumped bytes: the records-style
        factory's custom 2/4/2 sequence indent vs. the hosts-style
        factory's ruamel default."""
        import io

        records_style = yamlio.rt_yaml(
            preserve_quotes=True, width=4096, sequence_indent=(2, 4, 2)
        )
        hosts_style = yamlio.rt_yaml(default_flow_style=False)
        data = {"projects": ["a", "b"]}

        buf1 = io.StringIO()
        records_style.dump(data, buf1)
        buf2 = io.StringIO()
        hosts_style.dump(data, buf2)
        assert buf1.getvalue() != buf2.getvalue()


# ------------------------------------------------------------- truncate


class TestTruncateOldest:
    def test_under_cap_is_untouched(self, tmp_path):
        p = tmp_path / "x.log"
        p.write_text("one\ntwo\n", encoding="utf-8")
        truncate.truncate_oldest(p, cap=1_000_000)
        assert p.read_text(encoding="utf-8") == "one\ntwo\n"

    def test_over_cap_keeps_the_newest_lines(self, tmp_path):
        p = tmp_path / "x.log"
        lines = [f"line-{i}\n" for i in range(100)]
        p.write_text("".join(lines), encoding="utf-8")
        cap = len("line-99\n") * 10  # room for ~10 lines
        truncate.truncate_oldest(p, cap=cap)
        kept = p.read_text(encoding="utf-8").splitlines()
        assert kept[-1] == "line-99"
        assert kept[0] != "line-0"  # the oldest lines are gone
        assert p.stat().st_size <= cap

    def test_a_missing_path_is_silent_not_a_crash(self, tmp_path):
        truncate.truncate_oldest(tmp_path / "nope.log", cap=10)  # no raise

    def test_mutation_removing_the_size_guard_truncates_a_small_file(
        self, tmp_path, monkeypatch
    ):
        """Positive control: without the ``st_size <= cap`` early return,
        even an already-small file gets rewritten (and, for a big
        enough gap between line sizes, can lose content it should have
        kept) -- proving the guard is load-bearing, not decorative."""
        p = tmp_path / "x.log"
        p.write_text("keep-me\n", encoding="utf-8")
        original = p.stat().st_size

        def _broken(path, cap):
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            keep: list[str] = []
            size = 0
            for line in reversed(lines):
                size += len(line.encode("utf-8"))
                if size > cap:
                    break
                keep.append(line)
            path.write_text("".join(reversed(keep)), encoding="utf-8")

        monkeypatch.setattr(truncate, "truncate_oldest", _broken)
        truncate.truncate_oldest(p, cap=0)
        assert p.stat().st_size != original
        assert p.read_text(encoding="utf-8") == ""


# --------------------------------------------------- P1: the facade scan


#: qual -> (module path, function/attribute name, must-contain substring
#: proving delegation, must-not-contain substring proving the raw
#: reimplementation is gone). Exactly the 12 + 4 + 5 + 2 = 23 sites this
#: move names (``primitives/chrono.py`` is the source, not a consumer,
#: and is excluded below). Fold r1: ``compilers.py`` was originally
#: excluded here alongside ``records.py`` on the theory both were
#: "sources, not consumers" of ``text.HEADING_RE`` -- false for
#: ``records.py`` (it was already an alias in the M-J commit) and, at
#: the time, also false for the CLAIM that ``compilers.py`` was
#: migrated (it wasn't; this list simply never checked it, so nothing
#: caught the miss). Both are now in ``_HEADING_RE_FACADES`` below,
#: making it 4 of 4 real sites, matching the 23-site total.
_NOW_ISO_FACADES = [
    CLI_SRC / "records.py",
    CLI_SRC / "ledger_ops.py",
    CLI_SRC / "verbs.py",
    CLI_SRC / "worker.py",
    CLI_SRC / "hosts.py",
    CLI_SRC / "miner.py",
    CLI_SRC / "compiled.py",
    CLI_SRC / "import_backlog.py",
    CLI_SRC / "teach.py",
    CLI_SRC / "telemetry.py",
    UI_SRC / "uilog.py",
    UI_SRC / "store.py",
]

_HEADING_RE_FACADES = [
    CLI_SRC / "records.py",
    CLI_SRC / "ledger_ops.py",
    CLI_SRC / "compilers.py",
    UI_SRC / "models.py",
]

_YAML_FACTORY_FACADES = [
    (CLI_SRC / "records.py", "_make_yaml"),
    (CLI_SRC / "ledger_ops.py", "_yaml"),
    (CLI_SRC / "hosts.py", "_yaml"),
    (CLI_SRC / "config.py", "_rt_yaml"),
    (CLI_SRC / "compiled.py", "_yaml"),
]

_TRUNCATE_FACADES = [
    CLI_SRC / "worker.py",
    UI_SRC / "uilog.py",
]


def _find_def(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} has no def {name}")


def _source_of(path: Path, name: str) -> str:
    node = _find_def(path, name)
    return ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""


def _heading_re_assignment_rhs(source_text: str) -> str | None:
    """Parse arbitrary source text (a real file's contents, or a
    synthetic snippet for a positive control) and return the unparsed
    RHS of a module-level ``_HEADING_RE = ...`` assignment, or ``None``
    if the source has no such assignment."""
    tree = ast.parse(source_text)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_HEADING_RE"
        ):
            return ast.unparse(node.value)
    return None


def _assert_heading_re_rhs_is_an_alias(label: str, rhs: str | None) -> None:
    """The actual delegation check (fold r1: pulled out of the
    parametrized test so a positive control can exercise the exact
    same assertions against a synthetic ``rhs``, not just a real
    file's live content)."""
    assert rhs is not None, f"{label} has no _HEADING_RE assignment"
    assert "re.compile(" not in rhs, f"{label} still compiles its own pattern"
    assert "HEADING_RE" in rhs  # text.HEADING_RE / sl_text.HEADING_RE


class TestP1FacadeScan:
    """P1 corrected: match the OWNER-QUALIFIED body, not the public
    name -- a rename or a private alias (``ledger_ops._yaml``,
    ``hosts._yaml``, ``compiled._yaml`` are three DIFFERENT private
    names for the same shared factory) must not be able to hide a
    reimplementation. Every assertion below inspects the actual
    function BODY text, not a docstring or a file's mere presence."""

    @pytest.mark.parametrize("path", _NOW_ISO_FACADES, ids=lambda p: p.name)
    def test_now_iso_site_is_a_facade(self, path):
        src = _source_of(path, "_now_iso")
        assert "chrono.now_iso(" in src, f"{path} does not delegate to chrono.now_iso"
        assert "datetime.now(" not in src, f"{path} still reimplements the clock"

    @pytest.mark.parametrize("path", _HEADING_RE_FACADES, ids=lambda p: p.name)
    def test_heading_re_site_is_an_alias(self, path):
        rhs = _heading_re_assignment_rhs(path.read_text(encoding="utf-8"))
        _assert_heading_re_rhs_is_an_alias(str(path), rhs)

    def test_heading_re_scan_would_have_caught_the_compilers_py_regression(self):
        """Positive control (fold r1). Before this fold, ``compilers.py``
        was simply absent from ``_HEADING_RE_FACADES`` -- the AST-based
        assertion below was never run against it, so the M-J commit's
        "4 of 4 migrated" claim went unchecked and was false (3 of 4).
        This reproduces ``compilers.py:184``'s EXACT pre-fold source,
        byte-for-byte, and proves the assertion logic itself -- not just
        list membership -- would have failed loudly had that site been
        included."""
        slipped_through_source = (
            '_HEADING_RE = re.compile(r"^## +(.+?)\\s*$", re.MULTILINE)\n'
        )
        rhs = _heading_re_assignment_rhs(slipped_through_source)
        with pytest.raises(AssertionError, match="still compiles its own pattern"):
            _assert_heading_re_rhs_is_an_alias("compilers.py (pre-fold)", rhs)

    @pytest.mark.parametrize(
        "path,name", _YAML_FACTORY_FACADES, ids=[f"{p.name}:{n}" for p, n in _YAML_FACTORY_FACADES]
    )
    def test_yaml_factory_site_is_a_facade(self, path, name):
        src = _source_of(path, name)
        assert "yamlio.rt_yaml(" in src, f"{path}:{name} does not delegate to yamlio.rt_yaml"
        assert 'YAML(typ="rt")' not in src, f"{path}:{name} still builds its own YAML()"

    @pytest.mark.parametrize("path", _TRUNCATE_FACADES, ids=lambda p: p.name)
    def test_truncate_oldest_site_is_a_facade(self, path):
        src = _source_of(path, "_truncate_oldest")
        assert "truncate.truncate_oldest(" in src, f"{path} does not delegate"
        assert "splitlines(keepends=True)" not in src, f"{path} still reimplements the algorithm"

    def test_the_scan_itself_is_not_vacuous(self):
        """Positive control: a deliberately unmigrated body (the exact
        shape every one of the 23 sites had before this move) must FAIL
        the facade assertion the same way a real regression would."""
        old_body = (
            "def _now_iso() -> str:\n"
            '    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")\n'
        )
        assert "chrono.now_iso(" not in old_body
        assert "datetime.now(" in old_body


class TestKnownDivergentSitesLeftAlone:
    """Measured during this move and deliberately NOT touched (out of
    the 12/4/5/2 the brief names) -- listed here so a future scan
    doesn't have to re-discover them, and so this move's own facade
    scan above doesn't silently widen to flag them. Each formats an
    ARBITRARY passed-in value, not "now", or lives in a file this
    move's Files list never names:

    - ``analyst.py``'s ``proposal["analyzed_at"] = datetime.now(...)
      .strftime(...)`` -- an inline literal, not a named ``_now_iso``
      site; the brief's 12-site list does not include analyst.py.
    - ``sentinel.py``'s ``now.strftime(...)`` -- formats a caller-given
      clock reading, not ``datetime.now()`` itself.
    - ``ledger_ops._ts_str`` / ``compilers``'s date formatter -- both
      format an arbitrary VALUE argument, never "now".
    - ``compilers.py:390``'s own inline ``YAML(typ="rt")`` -- not one
      of the 5 named YAML-factory sites (records/ledger_ops/hosts/
      config/compiled); left alone per scope.
    - ``report._LRN_ID_RE`` / UI ``runner.py``'s ``_RECORD_ID_RE`` --
      both intentionally UNANCHORED variants of ``records.RECORD_ID_RE``
      used for embedded-token extraction (``.findall``/``.fullmatch``
      against a whole string), not full-value validation; not
      byte-identical to the anchored validator, so not consolidated
      (advisor guidance: consolidate an ID-regex duplicate only if
      byte-identical, otherwise leave and list it -- the brief's own
      "two regexes" pairs with the 4 ``_HEADING_RE`` sites, not these)."""

    def test_analyst_py_inline_site_is_unchanged_and_out_of_scope(self):
        src = (CLI_SRC / "analyst.py").read_text(encoding="utf-8")
        assert 'datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")' in src

    def test_compilers_py_inline_yaml_factory_is_unchanged_and_out_of_scope(self):
        src = (CLI_SRC / "compilers.py").read_text(encoding="utf-8")
        assert 'YAML(typ="rt")' in src

    def test_report_lrn_id_re_stays_unanchored_and_distinct_from_record_id_re(self):
        from self_learn.records import RECORD_ID_RE
        from self_learn.report import _LRN_ID_RE

        assert RECORD_ID_RE.pattern != _LRN_ID_RE.pattern
        # the anchored validator rejects an embedded id; the unanchored
        # extractor is exactly what makes findall() over a commit
        # subject line work at all.
        assert RECORD_ID_RE.match("see lrn-deadbeef here") is None
        assert _LRN_ID_RE.findall("see lrn-deadbeef here") == ["lrn-deadbeef"]
