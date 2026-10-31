"""SK-R: the owned-skills registry (``self_learn.skill_registry``).

The plan's five tests, each red on master (the module does not exist there):

(a) a missing file loads as an empty registry;
(b) an unknown key or status is refused by name, on load and on update;
(c) ``is_owned`` is false for a retired row and true for a live one;
(d) ``with_update`` commits once, and a second identical update commits nothing;
(e) the lock invariant sees ``with_update`` under the commit lock, with no
    walker edit and no ``NOT_REPO_TRUTH`` entry.

Plus the authored hash (D4's compare-and-swap rests on it), the file's
round trip, and crash recovery. Absence assertions ("nothing was
committed", "nothing was written") each sit beside a positive control that
shows the same check CAN see a commit or a file.
"""

from __future__ import annotations

import copy
import io
import re
import shutil
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import compilers, gitops, intents
from self_learn import skill_registry as sr
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from support import git, make_home
from test_lock_invariant import NOT_REPO_TRUTH, SRC, _Analysis

CASE = "case-0123abcd"
CASE_2 = "case-fedcba98"
STATEMENT = "stmt-0a1b2c3d"
SHA = "ab" * 32
AT = "2026-10-30T12:00:00Z"
AT_2 = "2026-11-02T04:15:00Z"
NAME = "demo-skill"


# ------------------------------------------------------------------ helpers


def _row(name: str = NAME, **overrides) -> dict:
    row = {
        "status": "live",
        "plugin": f"plugins/{name}",
        "created": {"at": AT, "case": CASE, "by": "overseer"},
        "last_write": {"at": AT, "case": CASE, "by": "overseer", "authored_sha256": SHA},
    }
    row.update(overrides)
    return row


def _retired_row(name: str = NAME) -> dict:
    return _row(name, status="retired", retired={"at": AT_2, "case": CASE_2, "by": "human"})


def _data(**skills: dict) -> dict:
    return {"version": 1, "skills": dict(skills), "vetoed": []}


def _dump(data: dict) -> str:
    buf = io.StringIO()
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    yaml.dump(data, buf)
    return buf.getvalue()


def _put(home: Path, text: str) -> Path:
    path = home / sr.REGISTRY_FILENAME
    path.write_text(text, encoding="utf-8")
    return path


def _head(home: Path) -> str:
    return git(home, "rev-parse", "HEAD").stdout.strip()


def _commit_count(home: Path) -> int:
    return int(git(home, "rev-list", "--count", "HEAD").stdout.strip())


def _subject(home: Path) -> str:
    return git(home, "log", "-1", "--format=%s").stdout.strip()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return make_home(tmp_path)


def _add_row(registry: sr.Registry, name: str = NAME, row: dict | None = None) -> None:
    registry.skills[name] = row if row is not None else _row(name)


# ============================================================ (a) missing file


class TestMissingFile:
    def test_a_missing_file_loads_as_an_empty_registry(self, home):
        # positive control: the home is a real ledger, and the file is
        # genuinely absent rather than the home being wrong.
        assert (home / "hosts.yaml").is_file()
        assert not (home / sr.REGISTRY_FILENAME).exists()
        registry = sr.load(home)
        assert registry.skills == {}
        assert registry.vetoed == []
        assert registry.live() == []
        assert registry.vetoed_names() == []
        assert registry.is_owned(NAME) is False
        assert registry.row(NAME) is None

    def test_loading_writes_nothing(self, home):
        sr.load(home)
        assert not (home / sr.REGISTRY_FILENAME).exists()

    def test_a_no_change_update_leaves_a_missing_file_missing_and_commits_nothing(self, home):
        before = _head(home)
        assert sr.with_update(home, lambda registry: None, subject="noop") is None
        assert not (home / sr.REGISTRY_FILENAME).exists()
        assert _head(home) == before

    def test_a_present_but_empty_file_is_refused_not_read_as_empty(self, home):
        _put(home, "")
        with pytest.raises(sr.SkillRegistryError, match="version"):
            sr.load(home)

    def test_an_unparseable_file_is_refused(self, home):
        _put(home, "skills: [unclosed\n")
        with pytest.raises(sr.SkillRegistryError, match="unparseable"):
            sr.load(home)


# ================================================== (b) unknown keys and values


def _mut(fn):
    """A mutator of the good one-skill data, for the parametrised cases."""

    def apply() -> dict:
        data = _data(**{NAME: _row()})
        fn(data)
        return data

    return apply


_ROW = lambda data: data["skills"][NAME]  # noqa: E731

#: (id, build the bad data, every needle the refusal must contain)
_REFUSED = [
    ("top-key", _mut(lambda d: d.update(extra=1)), ["extra"]),
    ("row-key", _mut(lambda d: _ROW(d).update(colour="blue")), ["colour", NAME]),
    ("status", _mut(lambda d: _ROW(d).update(status="paused")), ["paused", NAME, "status"]),
    ("status-missing", _mut(lambda d: _ROW(d).pop("status")), ["status", NAME]),
    ("created-key", _mut(lambda d: _ROW(d)["created"].update(who="x")), ["who", "created"]),
    ("created-missing", _mut(lambda d: _ROW(d).pop("created")), ["created", NAME]),
    ("last-write-missing", _mut(lambda d: _ROW(d).pop("last_write")), ["last_write", NAME]),
    (
        "last-write-key",
        _mut(lambda d: _ROW(d)["last_write"].update(note="x")),
        ["note", "last_write"],
    ),
    (
        "sha-not-hex",
        _mut(lambda d: _ROW(d)["last_write"].update(authored_sha256="xyz")),
        ["authored_sha256", "xyz"],
    ),
    (
        "sha-upper-case",
        _mut(lambda d: _ROW(d)["last_write"].update(authored_sha256="AB" * 32)),
        ["authored_sha256"],
    ),
    (
        "sha-missing",
        _mut(lambda d: _ROW(d)["last_write"].pop("authored_sha256")),
        ["authored_sha256"],
    ),
    ("case", _mut(lambda d: _ROW(d)["created"].update(case="case-xyz")), ["case-xyz", "case id"]),
    ("by", _mut(lambda d: _ROW(d)["created"].update(by="steward")), ["steward", "overseer"]),
    ("at", _mut(lambda d: _ROW(d)["created"].update(at="yesterday")), ["yesterday", "timestamp"]),
    (
        "plugin-climbs",
        _mut(lambda d: _ROW(d).update(plugin="plugins/../elsewhere")),
        ["plugin", "plugins/../elsewhere"],
    ),
    ("plugin-absolute", _mut(lambda d: _ROW(d).update(plugin="/etc")), ["plugin", "/etc"]),
    (
        "plugin-nested",
        _mut(lambda d: _ROW(d).update(plugin="plugins/a/b")),
        ["plugin", "plugins/a/b"],
    ),
    (
        "plugin-of-another-skill",
        _mut(lambda d: _ROW(d).update(plugin="plugins/other-skill")),
        ["plugin", "plugins/other-skill", f"plugins/{NAME}", NAME],
    ),
    (
        "two-rows-one-folder",
        _mut(lambda d: d["skills"].update({"other-skill": _row("other-skill", plugin=f"plugins/{NAME}")})),
        ["plugin", f"plugins/{NAME}", "other-skill"],
    ),
    ("name-not-kebab", _mut(lambda d: d["skills"].update({"Bad_Name": _row("bad")})), ["Bad_Name"]),
    ("retired-block-on-live", _mut(lambda d: _ROW(d).update(retired={})), ["retired", "live"]),
    (
        "retired-without-block",
        _mut(lambda d: _ROW(d).update(status="retired")),
        ["retired", NAME],
    ),
    (
        "renamed-from-self",
        _mut(lambda d: _ROW(d).update(renamed_from=[NAME])),
        ["renamed_from", NAME],
    ),
    (
        "renamed-from-twice",
        _mut(lambda d: _ROW(d).update(renamed_from=["old-one", "old-one"])),
        ["renamed_from", "old-one"],
    ),
    (
        "renamed-from-not-a-list",
        _mut(lambda d: _ROW(d).update(renamed_from="old-one")),
        ["renamed_from"],
    ),
    (
        "veto-key",
        _mut(lambda d: d.update(vetoed=[{"name": "x", "at": AT, "statement": STATEMENT, "why": "y"}])),
        ["why", "vetoed[0]"],
    ),
    (
        "veto-statement",
        _mut(lambda d: d.update(vetoed=[{"name": "x", "at": AT, "statement": "said it"}])),
        ["said it", "statement id"],
    ),
    (
        "veto-twice",
        _mut(
            lambda d: d.update(
                vetoed=[
                    {"name": "dup-name", "at": AT, "statement": STATEMENT},
                    {"name": "dup-name", "at": AT_2, "statement": STATEMENT},
                ]
            )
        ),
        ["vetoed[1]", "already vetoed"],
    ),
    ("version-missing", _mut(lambda d: d.pop("version")), ["version"]),
    ("version-two", _mut(lambda d: d.update(version=2)), ["version", "2"]),
    ("version-true", _mut(lambda d: d.update(version=True)), ["version", "True"]),
]

#: Refusals about the file itself (its version, its top-level keys). An
#: update only edits the two collections, so these have no update form.
_FILE_ONLY = {"top-key", "version-missing", "version-two", "version-true"}


class TestRefusedByName:
    def test_control_the_good_data_loads(self, home):
        # Every refusal below is a one-edit variation of this; if the base
        # did not load, all of them would pass for the wrong reason.
        _put(home, _dump(_data(**{NAME: _row()})))
        registry = sr.load(home)
        assert registry.is_owned(NAME)

    @pytest.mark.parametrize("build, needles", [(c[1], c[2]) for c in _REFUSED], ids=[c[0] for c in _REFUSED])
    def test_a_bad_file_is_refused_and_the_refusal_names_what_is_wrong(self, home, build, needles):
        _put(home, _dump(build()))
        with pytest.raises(sr.SkillRegistryError) as caught:
            sr.load(home)
        message = str(caught.value)
        for needle in needles:
            assert needle in message, (needle, message)

    @pytest.mark.parametrize(
        "build, needles",
        [(c[1], c[2]) for c in _REFUSED if c[0] not in _FILE_ONLY],
        ids=[c[0] for c in _REFUSED if c[0] not in _FILE_ONLY],
    )
    def test_an_update_that_would_make_it_bad_is_refused_and_writes_nothing(
        self, home, build, needles
    ):
        # Start from a committed good file so "unchanged" is a real,
        # comparable state, not "no file".
        sr.with_update(home, lambda registry: _add_row(registry), subject="seed")
        good_text = (home / sr.REGISTRY_FILENAME).read_text(encoding="utf-8")
        head = _head(home)
        bad = build()

        def apply(registry: sr.Registry) -> None:
            registry.skills = copy.deepcopy(bad["skills"])
            registry.vetoed = copy.deepcopy(bad["vetoed"])

        with pytest.raises(sr.SkillRegistryError) as caught:
            sr.with_update(home, apply, subject="bad")
        for needle in needles:
            assert needle in str(caught.value), (needle, str(caught.value))
        assert (home / sr.REGISTRY_FILENAME).read_text(encoding="utf-8") == good_text
        assert _head(home) == head

    def test_a_callback_that_returns_something_else_is_refused(self, home):
        with pytest.raises(sr.SkillRegistryError, match="Registry"):
            sr.with_update(home, lambda registry: {"skills": {}}, subject="bad")  # type: ignore[arg-type,return-value]
        assert not (home / sr.REGISTRY_FILENAME).exists()

    def test_a_callback_that_raises_writes_nothing(self, home):
        def boom(registry: sr.Registry) -> None:
            _add_row(registry)
            raise RuntimeError("callback failed")

        with pytest.raises(RuntimeError, match="callback failed"):
            sr.with_update(home, boom, subject="never")
        assert not (home / sr.REGISTRY_FILENAME).exists()

    def test_a_bad_subject_is_refused_before_anything_happens(self, home):
        for subject in ("", "   ", "two\nlines"):
            with pytest.raises(sr.SkillRegistryError, match="subject"):
                sr.with_update(home, lambda registry: _add_row(registry), subject=subject)
        assert not (home / sr.REGISTRY_FILENAME).exists()


# ========================================================= (c) live vs retired


class TestOwnership:
    def test_is_owned_is_true_for_a_live_row_and_false_for_a_retired_one(self, home):
        _put(
            home,
            _dump(_data(**{"live-one": _row("live-one"), "gone-one": _retired_row("gone-one")})),
        )
        registry = sr.load(home)
        assert registry.is_owned("live-one") is True
        assert registry.is_owned("gone-one") is False
        assert registry.is_owned("never-heard-of-it") is False

    def test_live_lists_only_live_rows_sorted(self, home):
        _put(
            home,
            _dump(
                _data(
                    **{
                        "zeta-skill": _row("zeta-skill"),
                        "alpha-skill": _row("alpha-skill"),
                        "gone-one": _retired_row("gone-one"),
                    }
                )
            ),
        )
        assert sr.load(home).live() == ["alpha-skill", "zeta-skill"]

    def test_row_returns_a_retired_row_too_and_a_copy(self, home):
        _put(home, _dump(_data(**{"gone-one": _retired_row("gone-one")})))
        registry = sr.load(home)
        row = registry.row("gone-one")
        assert row is not None
        assert row["status"] == "retired"
        assert row["retired"] == {"at": AT_2, "case": CASE_2, "by": "human"}
        row["status"] = "live"  # editing the copy
        assert registry.is_owned("gone-one") is False

    def test_vetoed_names_and_the_row_for_a_renamed_skill(self, home):
        data = _data(**{NAME: _row(renamed_from=["old-name"])})
        data["vetoed"] = [{"name": "old-name", "at": AT, "statement": STATEMENT}]
        _put(home, _dump(data))
        registry = sr.load(home)
        assert registry.vetoed_names() == ["old-name"]
        assert registry.row(NAME)["renamed_from"] == ["old-name"]

    def test_a_non_string_name_is_not_owned(self, home):
        registry = sr.load(home)
        assert registry.is_owned(None) is False  # type: ignore[arg-type]
        assert registry.row(None) is None  # type: ignore[arg-type]

    def test_add_veto_is_idempotent_and_compares_without_regard_to_case(self):
        registry = sr.Registry()
        assert registry.add_veto("Bad-Name", at=AT, statement=STATEMENT) is True
        assert registry.add_veto("bad-name", at=AT_2, statement="stmt-ffffffff") is False
        assert registry.vetoed == [{"name": "Bad-Name", "at": AT, "statement": STATEMENT}]


# =========================================================== (d) one commit


class TestWriting:
    def test_an_update_writes_the_file_and_makes_exactly_one_commit(self, home):
        before_head, before_count = _head(home), _commit_count(home)
        sha = sr.with_update(home, lambda registry: _add_row(registry), subject="skill write demo-skill")
        assert sha == _head(home)
        assert sha != before_head
        assert _commit_count(home) == before_count + 1
        assert _subject(home) == "self-learn: skill write demo-skill"
        assert git(home, "show", "--name-only", "--format=", "HEAD").stdout.split() == [
            sr.REGISTRY_FILENAME
        ]
        loaded = sr.load(home)
        assert loaded.is_owned(NAME)
        assert loaded.row(NAME) == _row()

    def test_a_subject_that_already_has_the_prefix_is_not_prefixed_twice(self, home):
        sr.with_update(home, lambda registry: _add_row(registry), subject="self-learn: skill write")
        assert _subject(home) == "self-learn: skill write"

    def test_a_second_identical_update_makes_no_commit(self, home):
        first = sr.with_update(home, lambda registry: _add_row(registry), subject="first")
        assert first is not None
        head, count = _head(home), _commit_count(home)
        text = (home / sr.REGISTRY_FILENAME).read_text(encoding="utf-8")

        second = sr.with_update(home, lambda registry: _add_row(registry), subject="second")

        assert second is None
        assert _head(home) == head
        assert _commit_count(home) == count
        assert (home / sr.REGISTRY_FILENAME).read_text(encoding="utf-8") == text

    def test_control_a_different_update_does_make_a_second_commit(self, home):
        # Positive control for the no-commit assertion above: the same
        # counting DOES see a commit when the data really changes.
        sr.with_update(home, lambda registry: _add_row(registry), subject="first")
        count = _commit_count(home)
        sha = sr.with_update(
            home, lambda registry: _add_row(registry, "other-skill"), subject="second"
        )
        assert sha is not None
        assert _commit_count(home) == count + 1
        assert sr.load(home).live() == [NAME, "other-skill"]

    def test_the_callback_sees_the_registry_as_it_is_now_and_edits_a_copy(self, home):
        sr.with_update(home, lambda registry: _add_row(registry), subject="first")
        seen = {}

        def second(registry: sr.Registry) -> None:
            seen["owned"] = registry.is_owned(NAME)
            registry.skills[NAME]["status"] = "retired"
            registry.skills[NAME]["retired"] = {"at": AT_2, "case": CASE_2, "by": "human"}

        sr.with_update(home, second, subject="retire")
        assert seen == {"owned": True}
        assert sr.load(home).is_owned(NAME) is False
        assert sr.load(home).row(NAME)["retired"]["case"] == CASE_2

    def test_a_callback_may_return_a_replacement_registry(self, home):
        replacement = sr.Registry({NAME: _row()}, [])
        sr.with_update(home, lambda registry: replacement, subject="replace")
        assert sr.load(home).is_owned(NAME)

    def test_a_veto_is_recorded_and_kept_in_the_order_added(self, home):
        def veto(name: str, statement: str):
            def apply(registry: sr.Registry) -> None:
                registry.add_veto(name, at=AT, statement=statement)

            return apply

        sr.with_update(home, veto("zz-first", STATEMENT), subject="veto one")
        sr.with_update(home, veto("aa-second", "stmt-ffffffff"), subject="veto two")
        assert sr.load(home).vetoed_names() == ["zz-first", "aa-second"]


# ======================================================= the file's own shape


class TestFileShape:
    def test_what_is_written_loads_back_equal(self, home):
        def build(registry: sr.Registry) -> None:
            _add_row(registry, NAME, _row(renamed_from=["old-name"]))
            _add_row(registry, "gone-one", _retired_row("gone-one"))
            registry.add_veto("old-name", at=AT, statement=STATEMENT)

        sr.with_update(home, build, subject="shape")
        loaded = sr.load(home)
        assert loaded.skills == {
            NAME: _row(renamed_from=["old-name"]),
            "gone-one": _retired_row("gone-one"),
        }
        assert loaded.vetoed == [{"name": "old-name", "at": AT, "statement": STATEMENT}]

    def test_a_sha_made_only_of_digits_and_timestamps_stay_text_through_the_round_trip(self, home):
        digits = "1" * 64
        row = _row()
        row["last_write"]["authored_sha256"] = digits
        sr.with_update(home, lambda registry: _add_row(registry, NAME, row), subject="digits")
        loaded = sr.load(home).row(NAME)
        assert loaded["last_write"]["authored_sha256"] == digits
        assert loaded["created"]["at"] == AT  # a string again, not a datetime

    def test_the_text_is_in_a_fixed_order_with_skills_sorted(self, home):
        def build(registry: sr.Registry) -> None:
            _add_row(registry, "zeta-skill")
            _add_row(registry, "alpha-skill")

        sr.with_update(home, build, subject="order")
        text = (home / sr.REGISTRY_FILENAME).read_text(encoding="utf-8")
        assert text.startswith("version: 1\n")
        assert text.index("alpha-skill:") < text.index("zeta-skill:")
        alpha = text[text.index("alpha-skill:") : text.index("zeta-skill:")]
        positions = [alpha.index(key) for key in ("status:", "plugin:", "created:", "last_write:")]
        assert positions == sorted(positions)

    def test_a_hand_written_file_with_unquoted_timestamps_loads_with_text_timestamps(self, home):
        _put(
            home,
            "version: 1\n"
            "skills:\n"
            f"  {NAME}:\n"
            "    status: live\n"
            f"    plugin: plugins/{NAME}\n"
            f"    created: {{at: 2026-10-30T12:00:00Z, case: {CASE}, by: human}}\n"
            f"    last_write: {{at: 2026-10-30T12:00:00Z, case: {CASE}, by: human, authored_sha256: {SHA}}}\n",
        )
        row = sr.load(home).row(NAME)
        assert row["created"]["at"] == AT
        assert row["last_write"]["at"] == AT

    def test_a_file_with_only_the_version_is_an_empty_registry(self, home):
        _put(home, "version: 1\n")
        registry = sr.load(home)
        assert registry.skills == {} and registry.vetoed == []

    def test_a_load_is_a_private_copy(self, home):
        sr.with_update(home, lambda registry: _add_row(registry), subject="first")
        registry = sr.load(home)
        registry.skills.clear()
        assert sr.load(home).is_owned(NAME)


# ============================================================ crash recovery


class TestCrashBetweenWriteAndCommit:
    def test_a_crash_before_the_commit_is_finished_by_the_next_ledger_write(self, home, monkeypatch):
        head = _head(home)

        def crash(*args, **kwargs):
            raise RuntimeError("killed before the commit")

        with monkeypatch.context() as patched:
            patched.setattr(gitops, "stage_and_commit", crash)
            with pytest.raises(RuntimeError, match="killed before the commit"):
                sr.with_update(home, lambda registry: _add_row(registry), subject="crash test")
        # The write landed, the commit did not, and the intent is waiting.
        assert _head(home) == head
        assert sr.load(home).is_owned(NAME)
        assert list((home / ".intents").glob("*.json"))

        # Any later ledger write recovers first: a no-op update still takes the lock.
        assert sr.with_update(home, lambda registry: None, subject="noop") is None

        assert _head(home) != head
        assert _subject(home) == "self-learn: crash test"
        assert not list((home / ".intents").glob("*.json"))
        assert sr.load(home).is_owned(NAME)


# ========================================================= (e) the lock itself


class TestUnderTheCommitLock:
    def test_the_callback_the_write_and_the_commit_all_run_with_the_ledger_lock_held(
        self, home, monkeypatch
    ):
        key = str(gitops.commit_lock_path(home))
        seen: list[tuple[str, bool]] = []
        real_write = sr.fsops.atomic_write
        real_commit = gitops.stage_and_commit

        def write(path, *args, **kwargs):
            seen.append((f"write {Path(path).name}", key in gitops._held_locks))
            return real_write(path, *args, **kwargs)

        def commit(root, paths, subject, *args, **kwargs):
            seen.append((f"commit {Path(paths[0]).name}", key in gitops._held_locks))
            return real_commit(root, paths, subject, *args, **kwargs)

        def callback(registry: sr.Registry) -> None:
            seen.append(("callback", key in gitops._held_locks))
            _add_row(registry)

        # positive control: before the call the lock is not held, so the
        # check can read False.
        assert key not in gitops._held_locks
        monkeypatch.setattr(sr.fsops, "atomic_write", write)
        monkeypatch.setattr(gitops, "stage_and_commit", commit)

        sr.with_update(home, callback, subject="locked")

        labels = [label for label, _held in seen]
        assert "callback" in labels
        assert f"write {sr.REGISTRY_FILENAME}" in labels
        assert f"commit {sr.REGISTRY_FILENAME}" in labels
        assert all(held for _label, held in seen), seen
        assert key not in gitops._held_locks  # released afterwards

    def test_the_registry_is_read_again_inside_the_lock(self, home, monkeypatch):
        """``with_update`` re-reads the file after taking the lock, so two
        writers cannot overwrite each other from a stale read. Moving the
        read ahead of the lock would leave every other test here green."""
        key = str(gitops.commit_lock_path(home))
        reads: list[bool] = []
        real_load = sr.load

        def load(path):
            reads.append(key in gitops._held_locks)
            return real_load(path)

        # positive control: the recorder reads False when the lock is not held.
        monkeypatch.setattr(sr, "load", load)
        sr.load(home)
        assert reads == [False]
        reads.clear()

        sr.with_update(home, lambda registry: _add_row(registry), subject="reread")

        assert reads, "with_update never read the registry"
        assert all(reads), reads

    def test_the_analysis_sees_the_write_and_sees_the_lock_discharge_it(self):
        analysis = _Analysis()
        requires = analysis.requires_lock()
        # positive control: the helper that writes IS seen as a repo mutation ...
        assert "skill_registry._update_locked" in requires
        # ... and the public writer, which wraps it in the ledger lock, is not.
        assert "skill_registry.with_update" not in requires
        callers = analysis.callers()
        assert callers["skill_registry._update_locked"] == {"skill_registry.with_update"}
        roots = [qual for qual in analysis.funcs if not callers[qual]]
        offending = [
            qual for qual in roots if qual.startswith("skill_registry.") and qual in requires
        ]
        assert offending == []

    def test_no_walker_edit_and_no_exemption_was_needed(self):
        assert [name for name in NOT_REPO_TRUTH if name.startswith("skill_registry")] == []

    def test_an_unlocked_caller_of_the_locked_half_is_caught(self, tmp_path):
        """The mutation check: plant the bug this invariant exists for
        (reach the write without the lock) in a copy of the source tree and
        the analysis must flag it. Without this the two tests above could
        pass because the analysis looks at nothing."""
        sandbox = tmp_path / "src" / "self_learn"
        shutil.copytree(SRC, sandbox)
        module = sandbox / "skill_registry.py"
        module.write_text(
            module.read_text(encoding="utf-8")
            + "\n\ndef _planted_violation(home):\n"
            "    _update_locked(home, lambda registry: None, 'self-learn: planted')\n",
            encoding="utf-8",
        )
        requires = _Analysis(sandbox).requires_lock()
        assert "skill_registry._planted_violation" in requires
        assert "skill_registry.with_update" not in requires

    def test_dropping_the_lock_from_with_update_is_caught(self, tmp_path):
        """The other mutation: take the ``with`` away from the real writer."""
        sandbox = tmp_path / "src" / "self_learn"
        shutil.copytree(SRC, sandbox)
        module = sandbox / "skill_registry.py"
        text = module.read_text(encoding="utf-8")
        locked = (
            "        with intents.ledger_write(home) as recovered:\n"
            "            intents.announce_recovered(recovered)\n"
            "            return _update_locked(home, fn, message)\n"
        )
        assert text.count(locked) == 1  # the edit below really changes something
        module.write_text(
            text.replace(locked, "        return _update_locked(home, fn, message)\n"),
            encoding="utf-8",
        )
        requires = _Analysis(sandbox).requires_lock()
        assert "skill_registry.with_update" in requires


# ======================================================== the authored hash

SKILL_MD = "---\nname: demo-skill\ndescription: Use when demoing.\n---\n\n# Demo\n\nWhen to use it.\n"


def _with_section(text: str, *entries: str) -> str:
    lines = [BEGIN_MARKER, *entries, END_MARKER]
    return text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n"


def _with_pointer(text: str, token: str = "references/LEARNINGS.md") -> str:
    """*text* as the pointer route leaves it: the compiler's own output."""
    line = compilers.pointer_line(token, "lessons routed here")
    return compilers.compile_pointer_text(text, line)[0]


class TestAuthoredHash:
    def test_it_is_a_sha256_in_hex(self):
        assert re.fullmatch(r"[0-9a-f]{64}", sr.authored_sha256(SKILL_MD, {}))

    def test_the_managed_section_does_not_change_it(self):
        bare = sr.authored_sha256(SKILL_MD, {})
        one = sr.authored_sha256(_with_section(SKILL_MD, "- lesson one"), {})
        two = sr.authored_sha256(_with_section(SKILL_MD, "- lesson one", "- lesson two"), {})
        # positive control: the section is really in the text being hashed
        assert BEGIN_MARKER in _with_section(SKILL_MD, "- lesson one")
        assert bare == one == two

    def test_the_hash_of_a_draft_equals_the_hash_of_the_deployed_file(self):
        # The draft is hashed before the section exists; the deployed file
        # has the section the compiler bootstrapped (one blank line, then
        # the pair, then a newline). They must agree.
        refs = {"references/a.md": "# A\n"}
        assert sr.authored_sha256(SKILL_MD, refs) == sr.authored_sha256(
            _with_section(SKILL_MD, "- lesson"), refs
        )

    def test_changing_the_authored_text_changes_it(self):
        base = sr.authored_sha256(_with_section(SKILL_MD, "- lesson"), {})
        edited = SKILL_MD.replace("When to use it.", "When to use it, or not.")
        assert sr.authored_sha256(_with_section(edited, "- lesson"), {}) != base

    def test_text_added_after_the_managed_section_changes_it(self):
        deployed = _with_section(SKILL_MD, "- lesson")
        assert sr.authored_sha256(deployed + "A person's afterthought.\n", {}) != sr.authored_sha256(
            deployed, {}
        )

    def test_trailing_blank_lines_do_not_change_it(self):
        assert sr.authored_sha256(SKILL_MD + "\n\n\n", {}) == sr.authored_sha256(SKILL_MD, {})

    def test_a_reference_file_is_part_of_it(self):
        base = sr.authored_sha256(SKILL_MD, {"references/a.md": "one"})
        assert sr.authored_sha256(SKILL_MD, {"references/a.md": "two"}) != base
        assert sr.authored_sha256(SKILL_MD, {}) != base
        assert sr.authored_sha256(SKILL_MD, {"references/a.md": "one", "references/b.md": ""}) != base

    def test_the_order_files_are_given_in_does_not_matter(self):
        forward = {"references/a.md": "A", "references/b.md": "B"}
        backward = {"references/b.md": "B", "references/a.md": "A"}
        assert sr.authored_sha256(SKILL_MD, forward) == sr.authored_sha256(SKILL_MD, backward)

    def test_moving_text_between_files_or_renaming_a_file_changes_it(self):
        assert sr.authored_sha256(SKILL_MD, {"references/a.md": "bc"}) != sr.authored_sha256(
            SKILL_MD, {"references/ab.md": "c"}
        )
        assert sr.authored_sha256(SKILL_MD, {"references/a.md": "x"}) != sr.authored_sha256(
            SKILL_MD, {"references/b.md": "x"}
        )
        moved_out = SKILL_MD.replace("When to use it.\n", "")
        assert sr.authored_sha256(moved_out, {"references/a.md": "When to use it.\n"}) != sr.authored_sha256(
            SKILL_MD, {"references/a.md": ""}
        )

    def test_the_pointer_block_does_not_change_it(self):
        # A skill-scoped `reference` route adds this block to SKILL.md; it is
        # the compiler's text, so the first such lesson must not look like a
        # person's edit.
        bare = sr.authored_sha256(SKILL_MD, {})
        one = _with_pointer(SKILL_MD)
        two = _with_pointer(one, "references/other.md")  # a second line, same block
        # positive control: the block is really in the text being hashed
        assert compilers.POINTER_BEGIN_MARKER in one
        assert one.count("- `references/") == 1 and two.count("- `references/") == 2
        assert bare == sr.authored_sha256(one, {}) == sr.authored_sha256(two, {})

    def test_the_pointer_block_and_the_managed_section_together_do_not_change_it(self):
        refs = {"references/a.md": "# A\n"}
        both = _with_pointer(_with_section(SKILL_MD, "- lesson"))
        other_way = _with_section(_with_pointer(SKILL_MD), "- lesson")
        assert compilers.POINTER_BEGIN_MARKER in both and BEGIN_MARKER in both
        assert both != other_way  # control: two different texts, one hash below
        base = sr.authored_sha256(SKILL_MD, refs)
        assert sr.authored_sha256(both, refs) == sr.authored_sha256(other_way, refs) == base

    def test_text_added_after_the_pointer_block_changes_it(self):
        deployed = _with_pointer(SKILL_MD)
        assert sr.authored_sha256(deployed + "A person's afterthought.\n", {}) != sr.authored_sha256(
            deployed, {}
        )

    def test_a_damaged_pointer_block_counts_as_authored_text(self):
        clean = sr.authored_sha256(_with_pointer(SKILL_MD), {})
        no_end = SKILL_MD.rstrip("\n") + "\n\n" + compilers.POINTER_BEGIN_MARKER + "\n- x\n"
        end_first = (
            SKILL_MD.rstrip("\n")
            + "\n\n"
            + compilers.POINTER_END_MARKER
            + "\n"
            + compilers.POINTER_BEGIN_MARKER
            + "\n"
        )
        twice = _with_pointer(SKILL_MD) + "\n"
        twice += compilers.POINTER_BEGIN_MARKER + "\n" + compilers.POINTER_END_MARKER + "\n"
        assert clean == sr.authored_sha256(SKILL_MD, {})  # control: a healthy file matches
        for damaged in (no_end, end_first, twice):
            assert sr.authored_sha256(damaged, {}) != clean

    def test_the_reference_shelf_does_not_change_it(self):
        # `references/LEARNINGS.md` is created and appended to by the
        # reference route. Every other reference file still counts.
        shelf = "references/LEARNINGS.md"
        header = "# Learnings\n\nReference-routed lessons.\n"
        entry = "\n## 2026-10-30 — lrn-0123abcd\n\n**Trigger:** x\n"
        refs = {"references/a.md": "# A\n"}
        base = sr.authored_sha256(SKILL_MD, refs)
        assert sr.authored_sha256(SKILL_MD, {**refs, shelf: header}) == base
        assert sr.authored_sha256(SKILL_MD, {**refs, shelf: header + entry}) == base
        # positive control: the same text under any other name does count
        assert sr.authored_sha256(SKILL_MD, {**refs, "references/other.md": header}) != base
        assert sr.authored_sha256(SKILL_MD, {**refs, "references/learnings.md": header}) != base

    def test_a_deployed_skill_with_a_reference_lesson_matches_its_draft(self):
        # The whole of the pointer-route's output next to the draft it grew from.
        refs = {"references/a.md": "# A\n"}
        deployed_refs = {**refs, "references/LEARNINGS.md": "# Learnings\n\n## d — lrn-0123abcd\n"}
        deployed = _with_pointer(_with_section(SKILL_MD, "- lesson"))
        assert sr.authored_sha256(deployed, deployed_refs) == sr.authored_sha256(SKILL_MD, refs)

    def test_a_damaged_managed_section_counts_as_authored_text(self):
        clean = sr.authored_sha256(_with_section(SKILL_MD, "- lesson"), {})
        no_end = SKILL_MD.rstrip("\n") + "\n\n" + BEGIN_MARKER + "\n- lesson\n"
        end_first = SKILL_MD.rstrip("\n") + "\n\n" + END_MARKER + "\n" + BEGIN_MARKER + "\n"
        twice = _with_section(_with_section(SKILL_MD, "- a"), "- b")
        assert clean == sr.authored_sha256(SKILL_MD, {})  # control: a healthy file matches
        for damaged in (no_end, end_first, twice):
            assert sr.authored_sha256(damaged, {}) != clean

    @pytest.mark.parametrize(
        "key",
        ["", "SKILL.md", "../x.md", "/abs.md", "a\\b.md", "references//x.md", "./x.md", ".."],
    )
    def test_a_bad_file_key_is_refused_by_name(self, key):
        with pytest.raises(sr.SkillRegistryError, match="file key"):
            sr.authored_sha256(SKILL_MD, {key: "x"})

    def test_text_that_is_not_text_is_refused(self):
        with pytest.raises(sr.SkillRegistryError, match="references/a.md"):
            sr.authored_sha256(SKILL_MD, {"references/a.md": b"x"})  # type: ignore[dict-item]
        with pytest.raises(sr.SkillRegistryError, match="SKILL.md"):
            sr.authored_sha256(b"x", {})  # type: ignore[arg-type]
