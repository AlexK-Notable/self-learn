r"""S-67 rename guard: `graduate` is `retire`'s hidden alias for one
release (build-u13.md; 03-decisions.md S-67; 02-schema.md §2 as
amended). This test pins WHERE the OLD word may still appear — the
alias implementation itself, its unchanged machine tokens (`GRADUATE`
the decision-trace outcome; `gates.py`'s return; `ledger_ops.py`'s
`TRACE_OUTCOMES`/`_FALLBACK_RECOMMENDATIONS` key), `report.py`'s
commit-subject backward-compat regex, and prose comments elsewhere that
name the pre-rename word for HISTORY, never as today's current verb —
so a fresh function, a new UI label, or any other current-tense mention
of `graduate` drifts back in as a RED test instead of unnoticed.

`ui/src/**` carries the allowlist's empty set: S-67's ruling is that
every UI label, notice, SSE payload, and runner call carries the new
word — `graduate` never had to survive there at all (unlike the CLI,
the UI never shipped a graduate-shaped script/sheet to keep working).

Design notes (same discipline as `test_personal_literals.py`, this
tree's other whole-tree word scanner):

- The repo root is resolved from THIS file's on-disk location via
  `git rev-parse --show-toplevel`, never the pytest process's cwd
  (lrn-ca690038's cwd-relative-pathspec trap: a pathspec that silently
  resolves against the wrong directory returns an empty, vacuously
  "clean" result).
- File enumeration goes through `git ls-files`, so only TRACKED files
  are scanned — an untracked scratch file could otherwise carry a stray
  `graduate` invisibly.
- A positive control proves the scanner is not silently finding zero
  everywhere (the exact failure shape lrn-ea833a5b warns about): it
  asserts the scanner DOES find `verbs.py`, a file known today to carry
  the alias implementation. If that control goes red, the allowlist
  tests below cannot be trusted regardless of their own result.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from self_learn import cli, ledger_ops, verbs
from self_learn.ledger_ops import create_record, validate_proposal
from self_learn.records import Record
from support import commit_all, default_trace_for, make_behavior, make_home

_PATTERN = re.compile("graduate", re.IGNORECASE)

#: cli/src/self_learn: files that legitimately still say "graduate" —
#: the alias's own implementation (verbs.py: `graduate`/`_retire_impl`;
#: cli.py: the hidden sub-parser + dispatch; batch.py: the sheet-verb
#: branch/keys; ledger_ops.py: `TRACE_OUTCOMES`'s `GRADUATE` token and
#: `_FALLBACK_RECOMMENDATIONS`'s key, both unchanged per the
#: orchestrator's 2026-09-13 ruling), report.py's `_RESOLUTION_SUBJECT_RE`
#: (must keep matching a pre-rename ledger's real history AND the
#: alias's own unchanged commit subject) and its `graduated`/`GRADUATE`
#: JSON-key/dict-key machine names (same unchanged-token posture),
#: import_backlog.py's `GRADUATE` decision-trace outcome (the internal
#: token; its `recommendation` VALUE was changed to "retire" — see
#: `_retire_gates`), gates.py's `GRADUATE` return (G3, unchanged), and
#: selfcheck.py/hosts.py/gitops.py/cases.py/compilers.py's prose
#: comments naming the pre-rename word to explain PAST behaviour, never
#: presenting it as today's current verb.
_CLI_ALLOWLIST = frozenset(
    {
        "plugins/self-learn/cli/src/self_learn/batch.py",
        "plugins/self-learn/cli/src/self_learn/cases.py",
        "plugins/self-learn/cli/src/self_learn/cli.py",
        "plugins/self-learn/cli/src/self_learn/compilers.py",
        "plugins/self-learn/cli/src/self_learn/gates.py",
        "plugins/self-learn/cli/src/self_learn/gitops.py",
        "plugins/self-learn/cli/src/self_learn/hosts.py",
        "plugins/self-learn/cli/src/self_learn/import_backlog.py",
        "plugins/self-learn/cli/src/self_learn/ledger_ops.py",
        "plugins/self-learn/cli/src/self_learn/report.py",
        "plugins/self-learn/cli/src/self_learn/selfcheck.py",
        "plugins/self-learn/cli/src/self_learn/verbs.py",
    }
)

#: ui/src/self_learn_ui: nothing is allowlisted — S-67's UI ruling is
#: unconditional (every label/notice/SSE payload/runner call carries
#: the new word).
_UI_ALLOWLIST: frozenset[str] = frozenset()


def _repo_root() -> Path:
    """Resolved from THIS file's on-disk location, never the pytest
    process's cwd (the ac28695/lrn-ca690038 cwd trap)."""
    out = subprocess.run(
        ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    root = Path(out)
    assert root.is_dir(), f"git rev-parse --show-toplevel gave a non-directory: {root!r}"
    return root


def _tracked_files(root: Path, pathspec: str) -> list[Path]:
    """Every git-tracked file under `pathspec`, resolved against `root`
    explicitly (`git -C root ls-files -- pathspec`) — never the ambient
    cwd."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", pathspec],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [root / line for line in out]


def _files_with_hits(root: Path, pathspec: str) -> set[str]:
    hits: set[str] = set()
    for path in _tracked_files(root, pathspec):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _PATTERN.search(text):
            hits.add(str(path.relative_to(root)))
    return hits


def test_graduate_confined_to_the_alias_allowlist_in_cli_src():
    root = _repo_root()
    hits = _files_with_hits(root, "plugins/self-learn/cli/src")
    extra = hits - _CLI_ALLOWLIST
    stale = _CLI_ALLOWLIST - hits
    assert not extra, (
        f"S-67: 'graduate' appears outside the allowlist: {sorted(extra)} — "
        "either it's a genuine drift (fix it) or a new legitimate alias "
        "site (add it to _CLI_ALLOWLIST with a reason)"
    )
    assert not stale, (
        f"S-67: allowlisted file(s) no longer mention 'graduate': "
        f"{sorted(stale)} — prune them from _CLI_ALLOWLIST so it stays honest"
    )


def test_graduate_absent_from_ui_src():
    root = _repo_root()
    hits = _files_with_hits(root, "plugins/self-learn/ui/src")
    assert hits == _UI_ALLOWLIST, f"S-67: 'graduate' leaked into the UI: {sorted(hits)}"


def test_positive_control_the_scanner_finds_the_known_alias_site():
    """Proves the pattern/pathspec/root resolution actually work — a
    scanner silently matching nothing (wrong root, typo'd pattern, an
    empty pathspec) would make both tests above pass VACUOUSLY even
    with a real 'graduate' leak sitting right there unscanned."""
    root = _repo_root()
    hits = _files_with_hits(root, "plugins/self-learn/cli/src")
    assert "plugins/self-learn/cli/src/self_learn/verbs.py" in hits


# =================================================================== --help
#
# Tests item... (build-u13.md doesn't number this one explicitly, but
# CLAUDE.md's mutation-verification bar applies to every test added or
# relied on): `graduate` must be a HIDDEN alias -- absent from
# `self-learn --help`'s own command listing, `retire` present. This
# pins a REAL defect found while building this unit: `_verb()`'s
# `help=argparse.SUPPRESS if hidden else help_text` alone does NOT hide
# a subcommand's row (measured directly against `argparse` on Python
# 3.13.11: `sub.add_parser("hidden", help=argparse.SUPPRESS)` still
# lists a `hidden` row, with the literal string "==SUPPRESS==" as its
# help text -- `_format_action`/`HelpFormatter` only special-case
# `action.help is SUPPRESS` for ordinary arguments, not a subparsers
# choice-pseudo-action). The fix (`cli.py`'s `_verb()`) strips the
# pseudo-action `add_parser` appends to the subparsers action's own
# `_choices_actions` list -- what `HelpFormatter` actually iterates to
# build the listing.


def test_cli_help_hides_graduate_but_shows_retire():
    parser = cli._build_parser()
    text = parser.format_help()
    assert "graduate" not in text, (
        "S-67: `graduate` must not appear in `self-learn --help`'s "
        f"listing (hidden alias) -- got:\n{text}"
    )
    assert re.search(r"(?m)^\s+retire\s", text), f"retire must be listed:\n{text}"


def test_cli_graduate_subcommand_still_resolves_directly(capsys):
    """The alias is HIDDEN from the listing, not GONE: `self-learn
    graduate --help` still resolves straight to its own sub-parser --
    that resolution never goes through the stripped `_choices_actions`
    list, which only feeds the PARENT listing."""
    parser = cli._build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["graduate", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--covered-by" in out
    assert "graduate" in out  # usage: self-learn graduate ...


# =================================================================== reopen
#
# Tests item 4: `reopen` admits a wrongly RETIRED record (both
# `covered_by:` and legacy `canon` flavors) and still refuses a
# REPLACED one. Two INDEPENDENT mutations, hand-verified (see
# build-u13.md): (a) reverting `_REOPEN_ADMITTED_STATUSES` to plain
# `REOPENABLE_STATUSES` (deleting the `| frozenset({"superseded"})`)
# turns both admit-tests red; (b) deleting the `is_replacement` guard
# block in `verbs.reopen` turns the refuses-replacement test red (it
# would wrongly admit the replacement instead of raising). Reverting
# EITHER guard alone reproduces exactly what its own test pins -- a fold
# that weakens one without the other still goes red.

OLD_R = "lrn-0000d001"
NEW_R = "lrn-0000d002"


def _seed_pending_r(home, rid, *, scope="skill:s"):
    create_record(home, make_behavior(record_id=rid, scope=scope))
    commit_all(home, "seed")
    return rid


class TestReopenWidening:
    def test_admits_covered_by_retirement(self, tmp_path, monkeypatch):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        _seed_pending_r(home, OLD_R)
        verbs.retire(home, OLD_R, covered_by="claude-md:rules", no_push=True)

        result = verbs.reopen(home, OLD_R, no_push=True)

        assert result.action == "reopen"
        record = Record.from_path(home / "skills" / "s" / "pending" / f"{OLD_R}.md")
        assert record.status == "pending"
        assert record.superseded_by is None

    def test_admits_legacy_canon_retirement(self, tmp_path, monkeypatch):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        _seed_pending_r(home, OLD_R)
        verbs.graduate(home, OLD_R, no_push=True)  # legacy: no covered_by
        before = Record.from_path(home / "skills" / "s" / "resolved" / f"{OLD_R}.md")
        assert before.superseded_by == "canon"  # positive control: really legacy-retired

        result = verbs.reopen(home, OLD_R, no_push=True)

        assert result.action == "reopen"
        record = Record.from_path(home / "skills" / "s" / "pending" / f"{OLD_R}.md")
        assert record.status == "pending"
        assert record.superseded_by is None

    def test_refuses_replacement(self, tmp_path, monkeypatch):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        _seed_pending_r(home, OLD_R)
        _seed_pending_r(home, NEW_R)
        verbs.supersede(home, OLD_R, NEW_R, no_push=True)

        with pytest.raises(verbs.VerbError) as excinfo:
            verbs.reopen(home, OLD_R, no_push=True)
        message = str(excinfo.value)
        assert "superseded" in message
        assert "replacement" in message
        assert "reconsider" in message  # names the correct verb instead
        record = Record.from_path(home / "skills" / "s" / "resolved" / f"{OLD_R}.md")
        assert record.status == "superseded"  # untouched by the refusal
        assert record.superseded_by == NEW_R


# =================================================================== retire
#
# Tests item 2: `retire` without `covered_by` refused (verb + CLI);
# unknown kind refused BY NAME.


class TestRetireRequiresCoveredBy:
    def test_verb_call_without_covered_by_is_a_type_error(self, tmp_path, monkeypatch):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        _seed_pending_r(home, OLD_R)
        with pytest.raises(TypeError):
            verbs.retire(home, OLD_R, no_push=True)  # covered_by omitted entirely

    def test_cli_refuses_missing_covered_by(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        parser = cli._build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["retire", OLD_R])
        assert excinfo.value.code == 2  # argparse: required option missing
        err = capsys.readouterr().err
        assert "--covered-by" in err

    def test_unknown_kind_refused_by_name(self, tmp_path, monkeypatch):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        _seed_pending_r(home, OLD_R)
        with pytest.raises(verbs.VerbError) as excinfo:
            verbs.retire(home, OLD_R, covered_by="bogus-kind:foo", no_push=True)
        message = str(excinfo.value)
        assert "bogus-kind" in message
        assert "claude-md" in message  # names a real kind in the refusal


# =================================================================== display
#
# Tests item 5: the three phrases from the ONE display helper
# (`records.supersession_display`), plus a grep test that no other
# module independently builds an equivalent second phrase set. File-
# level allowlisting, same discipline as this file's own graduate-word
# scanner above: every hit file below is either `records.py` itself (the
# one true source) or a file that only MENTIONS a phrase inside a
# comment/docstring for documentation -- never a second `f"..."`
# construction of the same text.

_DISPLAY_PATTERN = re.compile(
    r"replaced by |retired, covered by |retired, covering surface unrecorded"
)

_DISPLAY_ALLOWLIST = frozenset(
    {
        "plugins/self-learn/cli/src/self_learn/records.py",  # the one true source
        "plugins/self-learn/cli/src/self_learn/cli.py",  # comment naming the phrases
        "plugins/self-learn/cli/src/self_learn/verbs.py",  # comment naming the phrases
        # coincidental match on "replaced by " -- unrelated to supersession
        # display at all ("replaced by a real pid", worker process bookkeeping).
        "plugins/self-learn/cli/src/self_learn/worker.py",
    }
)

_UI_DISPLAY_ALLOWLIST = frozenset(
    {
        "plugins/self-learn/ui/src/self_learn_ui/models.py",  # comment naming the phrases
    }
)


def test_supersession_display_three_phrases():
    from self_learn.records import supersession_display

    replacement = make_behavior(record_id="lrn-d0000001")
    replacement.set_status("superseded")
    replacement.set_superseded_by("lrn-d0000002")
    assert supersession_display(replacement) == "replaced by lrn-d0000002"

    covered = make_behavior(record_id="lrn-d0000003")
    covered.set_status("superseded")
    covered.set_superseded_by("covered_by:claude-md:rules")
    assert supersession_display(covered) == "retired, covered by claude-md:rules"

    legacy = make_behavior(record_id="lrn-d0000004")
    legacy.set_status("superseded")
    legacy.set_superseded_by("canon")
    assert supersession_display(legacy) == "retired, covering surface unrecorded"

    live = make_behavior(record_id="lrn-d0000005")
    assert supersession_display(live) == ""  # superseded_by is None: no phrase


def test_coverage_kinds_round_trip_through_the_one_display_helper():
    from self_learn.records import COVERAGE_KINDS, build_covered_by, supersession_display

    expected = frozenset({"claude-md", "skill-md", "reference", "output-style"})
    assert COVERAGE_KINDS == expected
    for kind in sorted(expected):
        record = make_behavior(record_id="lrn-d0000006")
        stored = build_covered_by(f"{kind}:surface")
        record.set_superseded_by(stored)
        assert supersession_display(record) == f"retired, covered by {kind}:surface"


def test_show_uses_the_display_helper_for_legacy_and_pending_supersessions(
    tmp_path, monkeypatch, capsys
):
    """The raw field is a machine value; both dict and text use its phrase."""
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))

    _seed_pending_r(home, OLD_R)
    verbs.graduate(home, OLD_R, no_push=True)

    pending_id = "lrn-0000d003"
    _seed_pending_r(home, pending_id)
    pending_path = home / "skills" / "s" / "pending" / f"{pending_id}.md"
    pending = Record.from_path(pending_path)
    pending.set_superseded_by(OLD_R)
    pending.write(pending_path)

    cases = (
        (OLD_R, "canon", "retired, covering surface unrecorded"),
        (pending_id, OLD_R, f"replaced by {OLD_R}"),
    )
    for record_id, raw, phrase in cases:
        data = verbs.show(home, record_id)
        assert data["superseded_by"] == raw  # positive control: raw field is present
        assert data["supersession"] == phrase

        capsys.readouterr()
        assert cli.main(["show", record_id]) == 0
        text = capsys.readouterr().out
        assert f"  superseded by: {phrase}\n" in text
        assert f"  superseded by: {raw}\n" not in text


def test_no_second_phrase_set_in_cli_src():
    root = _repo_root()
    hits = set()
    for path in _tracked_files(root, "plugins/self-learn/cli/src"):
        if path.is_file() and _DISPLAY_PATTERN.search(
            path.read_text(encoding="utf-8", errors="replace")
        ):
            hits.add(str(path.relative_to(root)))
    extra = hits - _DISPLAY_ALLOWLIST
    assert not extra, f"a second supersession phrase appeared outside records.py: {sorted(extra)}"
    assert "plugins/self-learn/cli/src/self_learn/records.py" in hits  # positive control


def test_no_second_phrase_set_in_ui_src():
    root = _repo_root()
    hits = set()
    for path in _tracked_files(root, "plugins/self-learn/ui/src"):
        if path.is_file() and _DISPLAY_PATTERN.search(
            path.read_text(encoding="utf-8", errors="replace")
        ):
            hits.add(str(path.relative_to(root)))
    extra = hits - _UI_DISPLAY_ALLOWLIST
    assert not extra, f"a second supersession phrase appeared in the UI: {sorted(extra)}"


# =================================================================== analyst
#
# Tests item 6: recommendation `retire` round-trips through
# `validate_proposal` (the real validator, not a hand-rolled shadow of
# it); the S-67 read-side compatibility rule admits an already-stored
# `recommendation: graduate` and normalizes the value to `retire` at
# the shared proposal boundary. `TRACE_RECOMMENDATIONS` stays narrowed,
# so new analyses cannot emit the old value. `GRADUATE` itself stays a
# valid `gates.outcome` token
# (positive control: the machine token is UNCHANGED, only the
# `recommendation` VALUE it renders was renamed).


def test_trace_recommendations_dropped_graduate_kept_grade_outcome_token():
    assert ledger_ops.TRACE_RECOMMENDATIONS == ("route", "reject", "defer", "retire")
    assert "graduate" not in ledger_ops.TRACE_RECOMMENDATIONS
    assert "GRADUATE" in ledger_ops.TRACE_OUTCOMES  # positive control: unchanged token
    assert ledger_ops._FALLBACK_RECOMMENDATIONS["GRADUATE"] == "retire"


def test_recommendation_retire_round_trips_and_legacy_graduate_reads_as_retire():
    base = {
        "destination": "claude-md",
        "rationale": "deterministic guard beats advisory text",
        "already_canon": False,
        "already_canon_reason": "",
        "record_sha": "sha256:000000000000",
        "model": "claude-opus-4-8",
        "analyzed_at": "2026-07-13T00:00:00Z",
    }
    trace = default_trace_for(base, "skill:s")  # a real ALWAYS-shaped gates block

    retiring = {**base, **trace, "recommendation": "retire"}
    validate_proposal(retiring)  # must not raise: retire round-trips

    stale = {**base, **trace, "recommendation": "graduate"}
    validate_proposal(stale)
    assert stale["recommendation"] == "retire"
