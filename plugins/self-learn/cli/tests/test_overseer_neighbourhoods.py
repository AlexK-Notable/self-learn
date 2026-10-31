"""Lesson neighbourhoods (SK5, D12): ``overseer/catalogue.py``'s third view.

``lesson_neighbourhoods`` groups the placed and pending lessons that sit near
each other, across every bucket, from the lesson index in the cache, with no
model call; ``render_neighbourhoods`` writes the groups as one markdown text.

How the assertions are guarded:

* Every claim that a lesson is ABSENT from a group (an unrelated lesson, a
  superseded one, a rejected one) sits next to a control that shows the same
  fixture grouping its neighbours: the group exists, and the lesson is
  counted as considered (or, for the superseded and rejected ones, a lesson
  with the same text that IS listed is in the group).
* Embeddings come from ``FakeEmbeddingProvider`` (text -> a fixed vector, so
  identical text means cosine 1.0 and different text means a vector with no
  relation to it) or from a tiny provider defined here that puts texts on
  chosen axes. Both are given an explicit cosine threshold, because the fake
  model has no measured one in ``index/related.py``. Nothing reaches a real
  embedding API and no model is called.
* The "words only" cases use fillers whose words do not overlap the group's,
  so BM25 has a corpus to weigh against; the identical-text lessons then
  score 1.0 against each other by construction and the fillers score 0.
* The read-only claims are checked three ways: every file and directory under
  the ledger and the cache is hashed before and after; every
  ``sqlite3.connect`` the call makes is recorded (a file is opened
  ``mode=ro``, the in-memory fallback is ``:memory:``); and a damaged index
  file is left byte for byte as it was.

Nothing here touches the real ledger or the real cache: ``SELF_LEARN_HOME``
and ``XDG_CACHE_HOME`` point into ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from pathlib import Path

import pytest

from self_learn.index import gemini, registry
from self_learn.index.fake import FakeEmbeddingProvider
from self_learn.index.store import LessonIndex, index_path
from self_learn.overseer import catalogue
from self_learn.records import Record

#: The text three lessons share (and the fake provider therefore embeds to
#: one vector). Its words appear in no filler.
SAME_TRIGGER = "About to restart the docker daemon."
SAME_INSTRUCTION = "Check the compose file first."

#: Lessons about other things, with words that do not overlap each other or
#: the shared text.
FILLERS = (
    ("About to dim the bedroom lights.", "Use the scene preset."),
    ("Printing the benchmark table.", "Round every figure."),
    ("Renaming a branch.", "Push the new name afterwards."),
    ("Writing a changelog entry.", "Link the pull request."),
    ("Opening the garage door.", "Wait for the beep."),
    ("Updating a dependency pin.", "Read the release notes."),
)


def _id(number: int) -> str:
    return f"lrn-{number:08x}"


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in gemini.KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv(registry.PROVIDER_ENV, raising=False)


class World:
    """A fixture ledger and a cache directory that already holds one file."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "ledger"
        for sub in ("skills", "projects", "user"):
            (self.home / sub).mkdir(parents=True)
        self.cache = tmp_path / "cache"
        (self.cache / "self-learn").mkdir(parents=True)
        (self.cache / "self-learn" / "marker").write_text("pre-existing\n", encoding="utf-8")
        monkeypatch.setenv("SELF_LEARN_HOME", str(self.home))
        monkeypatch.setenv("XDG_CACHE_HOME", str(self.cache))

    def _bucket_dir(self, bucket: str) -> Path:
        if bucket == "user":
            return self.home / "user"
        scope, _, name = bucket.partition(":")
        assert scope == "project", bucket
        return self.home / "projects" / name

    def lesson(
        self,
        number: int,
        *,
        bucket: str = "user",
        status: str = "routed",
        trigger: str = SAME_TRIGGER,
        instruction: str = SAME_INSTRUCTION,
        superseded_by: str | None = None,
    ) -> str:
        """Write one behavior lesson and return its id. ``bucket`` is
        ``user`` or ``project:<name>``; ``pending`` goes to ``pending/``,
        every other status to ``resolved/``."""
        record_id = _id(number)
        record = Record.create(
            type="behavior",
            scope="user" if bucket == "user" else "project",
            source="teach",
            kind="anti-pattern",
            trigger=trigger,
            instruction=instruction,
            record_id=record_id,
            created_at="2026-09-01T00:00:00Z",
        )
        if status != "pending":
            record.set_routing(
                {"routed_at": "2026-09-02T00:00:00Z", "destination": "claude-md", "by": "human"}
            )
        record.set_status(status)
        if superseded_by is not None:
            record.set_superseded_by(superseded_by)
        folder = self._bucket_dir(bucket) / ("pending" if status == "pending" else "resolved")
        folder.mkdir(parents=True, exist_ok=True)
        record.write(folder / f"{record_id}.md")
        return record_id

    def trio(self) -> tuple[str, str, str]:
        """Three placed lessons with the same text: one in the user bucket,
        one in each of two project buckets."""
        return (
            self.lesson(1),
            self.lesson(2, bucket="project:proj-a"),
            self.lesson(3, bucket="project:proj-b"),
        )

    def fillers(self) -> list[str]:
        return [
            self.lesson(10 + n, trigger=trigger, instruction=instruction)
            for n, (trigger, instruction) in enumerate(FILLERS)
        ]

    def build_index(self, provider) -> None:
        """Build the cache's lesson index the way ``index build`` does."""
        index = LessonIndex.open(self.home)
        index.build(provider)
        index.close()

    @property
    def index_file(self) -> Path:
        return index_path(self.home, create=False)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def _snapshot(*roots: Path) -> dict[str, str]:
    """Every entry under each root: a file by the hash of its bytes, a
    directory or a link by its kind. A stray ``mkdir``, a journal file or a
    rewritten index shows up here."""
    seen: dict[str, str] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            key = str(path)
            if path.is_symlink():
                seen[key] = f"link:{path.readlink()}"
            elif path.is_dir():
                seen[key] = "dir"
            else:
                seen[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return seen


def _grouped_ids(hoods: catalogue.Neighbourhoods) -> list[set[str]]:
    return [{lesson.id for lesson in group.lessons} for group in hoods.groups]


class AxisProvider:
    """Puts a text on an axis by the marker word it contains: ``alpha`` on
    the first, ``beta`` between the first and second, ``gamma`` on the
    second, ``delta`` on the third. The cosines are fixed by construction:
    alpha~beta and beta~gamma are 0.707, alpha~gamma is 0, delta is 0 to all."""

    dim = 3
    model_id = "axis-test-v1"

    _AXES = {
        "alpha": [1.0, 0.0, 0.0],
        "beta": [math.sqrt(0.5), math.sqrt(0.5), 0.0],
        "gamma": [0.0, 1.0, 0.0],
        "delta": [0.0, 0.0, 1.0],
    }

    def embed(self, texts):
        out = []
        for text in texts:
            marker = next(word for word in self._AXES if word in text.lower())
            out.append(list(self._AXES[marker]))
        return out


# ------------------------------------------- (a) one group across buckets


def test_three_lessons_with_one_text_in_three_buckets_form_one_group(world: World) -> None:
    one, two, three = world.trio()
    unrelated = world.lesson(
        4, trigger="About to dim the bedroom lights.", instruction="Use the scene preset."
    )
    world.build_index(FakeEmbeddingProvider())

    hoods = catalogue.lesson_neighbourhoods(world.home, cosine_threshold=0.9)

    # The groups are found from the embeddings, not from a silent fall-back
    # to words: the basis says so.
    assert hoods.basis == "cosine"
    assert hoods.basis_note.startswith("embeddings")
    assert _grouped_ids(hoods) == [{one, two, three}]
    group = hoods.groups[0]
    assert {lesson.bucket for lesson in group.lessons} == {
        "user",
        "project proj-a",
        "project proj-b",
    }
    assert [lesson.state for lesson in group.lessons] == ["placed"] * 3
    assert {link.basis for link in group.links} == {"cosine"}
    assert all(link.score >= 0.9 for link in group.links)
    assert len(group.links) == 3  # every pair of the three

    # CONTROL for the absence below: the unrelated lesson was read, indexed
    # and compared (it is counted, and is not among the lessons the index
    # lacks); it just reached no neighbour.
    assert hoods.considered == 4
    assert hoods.not_indexed == ()
    assert unrelated not in {i for ids in _grouped_ids(hoods) for i in ids}
    text = catalogue.render_neighbourhoods(hoods)
    assert one in text and two in text and three in text  # the text rendered the group
    assert unrelated not in text


def test_a_pending_lesson_joins_a_group_and_is_shown_as_pending(world: World) -> None:
    one, two, _three = world.trio()
    waiting = world.lesson(5, status="pending")
    world.build_index(FakeEmbeddingProvider())

    hoods = catalogue.lesson_neighbourhoods(world.home, cosine_threshold=0.9)

    assert len(hoods.groups) == 1
    states = {lesson.id: lesson.state for lesson in hoods.groups[0].lessons}
    assert states[waiting] == "pending"
    assert states[one] == states[two] == "placed"  # control: the placed ones say placed
    assert f"- {waiting} [user; pending]" in catalogue.render_neighbourhoods(hoods)


def test_neighbours_are_joined_by_a_chain_not_only_by_direct_pairs(world: World) -> None:
    a = world.lesson(1, trigger="alpha one", instruction="Do the alpha thing.")
    b = world.lesson(2, bucket="project:proj-a", trigger="beta two", instruction="Do the beta thing.")
    c = world.lesson(3, bucket="project:proj-b", trigger="gamma three", instruction="Do the gamma thing.")
    d = world.lesson(4, trigger="delta four", instruction="Do the delta thing.")
    world.build_index(AxisProvider())

    hoods = catalogue.lesson_neighbourhoods(world.home, cosine_threshold=0.6)

    assert _grouped_ids(hoods) == [{a, b, c}]  # a and c are 0 apart; b joins them
    pairs = {(link.a, link.b) for link in hoods.groups[0].links}
    assert pairs == {(a, b), (b, c)}
    assert (a, c) not in pairs  # control: only the pairs that reached the threshold
    assert d not in _grouped_ids(hoods)[0]  # control: delta was compared and is 0 from all
    assert hoods.considered == 4 and hoods.not_indexed == ()
    # Raise the bar above 0.707 and the chain breaks into nothing: the
    # threshold is what decides, not the shape of the fixture.
    assert catalogue.lesson_neighbourhoods(world.home, cosine_threshold=0.8).groups == ()


# ------------------------------------------- (b) lessons that are not listed


def test_a_superseded_or_rejected_lesson_is_not_listed(world: World) -> None:
    placed = world.lesson(1)
    successor = world.lesson(2, bucket="project:proj-a")
    old = world.lesson(3, status="superseded", superseded_by=successor)
    rejected = world.lesson(4, status="rejected")
    world.build_index(FakeEmbeddingProvider())

    hoods = catalogue.lesson_neighbourhoods(world.home, cosine_threshold=0.9)

    # CONTROL: the superseded and rejected lessons have the same text as the
    # two listed ones, so the index holds them and they would be neighbours;
    # the listed pair is a group.
    index = LessonIndex.open_existing(world.home)
    assert index is not None
    try:
        assert {old, rejected} <= set(index.docs())
    finally:
        index.close()
    assert _grouped_ids(hoods) == [{placed, successor}]
    assert hoods.considered == 2
    text = catalogue.render_neighbourhoods(hoods)
    assert placed in text and successor in text
    assert old not in text and rejected not in text


def test_the_ledger_not_the_index_decides_which_lessons_are_listed(world: World) -> None:
    # A lesson routed since the index was built is listed (the ledger says
    # so) but cannot be compared yet: it is named, not dropped.
    one, two, three = world.trio()
    world.fillers()
    world.build_index(None)
    late = world.lesson(9)

    hoods = catalogue.lesson_neighbourhoods(world.home)

    assert hoods.not_indexed == (late,)
    assert hoods.considered == 3 + len(FILLERS) + 1
    assert _grouped_ids(hoods) == [{one, two, three}]  # control: the others still group
    text = catalogue.render_neighbourhoods(hoods)
    assert f"Not in the index yet, so not compared: {late}." in text


# ------------------------------------- (c) no index: words only, nothing written


def test_with_no_index_the_text_says_words_only_and_nothing_is_written(world: World) -> None:
    one, two, three = world.trio()
    world.fillers()
    roots = (world.home, world.cache)
    # CONTROL: there really is no index, and the snapshot sees files in both
    # roots (the cache marker, the ledger's records), so "unchanged" is not
    # "saw nothing".
    assert not world.index_file.exists()
    before = _snapshot(*roots)
    assert str(world.cache / "self-learn" / "marker") in before
    assert any(key.endswith(f"{_id(1)}.md") for key in before)

    hoods = catalogue.lesson_neighbourhoods(world.home)
    text = catalogue.render_neighbourhoods(hoods)

    assert hoods.basis_note == "word match only (index not built)"
    assert "Compared by: word match only (index not built)." in text
    # The words alone still find the three (control: the file is not empty
    # because it could not look).
    assert _grouped_ids(hoods) == [{one, two, three}]
    assert {link.basis for link in hoods.groups[0].links} == {"lexical"}
    assert _snapshot(*roots) == before
    assert not world.index_file.exists()  # still none: nothing built it


def test_an_index_built_without_embeddings_says_words_only_and_why(world: World) -> None:
    one, two, three = world.trio()
    world.fillers()
    world.build_index(None)

    hoods = catalogue.lesson_neighbourhoods(world.home)

    assert hoods.basis == "lexical"
    assert hoods.basis_note.startswith("word match only (")
    assert "index not built" not in hoods.basis_note  # it was built; it just has no vectors
    assert _grouped_ids(hoods) == [{one, two, three}]


def test_a_damaged_index_falls_back_to_words_and_is_left_alone(world: World) -> None:
    one, two, three = world.trio()
    world.fillers()
    path = world.index_file
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a database " * 40)
    before = _snapshot(world.home, world.cache)

    hoods = catalogue.lesson_neighbourhoods(world.home)

    assert hoods.basis_note.startswith("word match only (index could not be read: ")
    assert _grouped_ids(hoods) == [{one, two, three}]
    assert _snapshot(world.home, world.cache) == before  # not repaired, not replaced


def test_a_ledger_with_nothing_near_anything_says_so(world: World) -> None:
    world.fillers()

    hoods = catalogue.lesson_neighbourhoods(world.home)
    text = catalogue.render_neighbourhoods(hoods)

    assert hoods.groups == ()
    assert hoods.considered == len(FILLERS)
    # CONTROL: the file rendered (its header and basis line are there), so
    # the empty answer is the answer and not a failure to render.
    assert "# Lesson neighbourhoods" in text
    assert f"Lessons compared: {len(FILLERS)}. Groups found: 0." in text
    assert "No lesson sits near enough another to form a group." in text


# -------------------------------------------------- (d) nothing is written


def test_building_the_neighbourhoods_writes_nothing(world: World) -> None:
    world.trio()
    world.fillers()
    world.lesson(5, status="pending")
    roots = (world.home, world.cache)

    # The index exists and is read. Every public entry point runs.
    world.build_index(FakeEmbeddingProvider())
    before = _snapshot(*roots)
    assert str(world.index_file) in before  # CONTROL: the index file is in the snapshot
    assert len(before) > 10
    hoods = catalogue.lesson_neighbourhoods(world.home, cosine_threshold=0.9)
    catalogue.render_neighbourhoods(hoods)
    assert hoods.groups  # CONTROL: the call did real work
    assert _snapshot(*roots) == before  # no byte of the index, no journal file, no directory

    # No index at all: the same, from the ledger alone.
    world.index_file.unlink()
    before = _snapshot(*roots)
    hoods = catalogue.lesson_neighbourhoods(world.home)
    assert hoods.groups
    assert _snapshot(*roots) == before


def test_the_index_file_is_opened_read_only_and_the_fallback_is_in_memory(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.trio()
    world.build_index(FakeEmbeddingProvider())
    real_connect = sqlite3.connect
    opened: list[str] = []

    def spy(database, *args, **kwargs):
        opened.append(str(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)

    catalogue.lesson_neighbourhoods(world.home, cosine_threshold=0.9)
    assert opened  # CONTROL: the spy saw the open
    assert all("mode=ro" in target for target in opened), opened
    assert all(target.startswith("file:") for target in opened), opened

    opened.clear()
    world.index_file.unlink()
    catalogue.lesson_neighbourhoods(world.home)
    assert opened == [":memory:"]  # no index: a throwaway one, never a file


def test_a_given_index_is_used_as_it_stands_and_left_open(world: World) -> None:
    one, two, three = world.trio()
    world.build_index(FakeEmbeddingProvider())
    index = LessonIndex.open(world.home)
    try:
        hoods = catalogue.lesson_neighbourhoods(world.home, index=index, cosine_threshold=0.9)
        assert _grouped_ids(hoods) == [{one, two, three}]
        assert index.docs()  # still open: the caller's to close
    finally:
        index.close()


# ------------------------------------------------------------- the knobs


def test_the_thresholds_and_the_limit_are_read_when_the_function_runs(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    one, two, three = world.trio()
    world.fillers()
    # CONTROL: with the shipped knobs the trio is one group.
    assert _grouped_ids(catalogue.lesson_neighbourhoods(world.home)) == [{one, two, three}]

    # Word similarity never exceeds 1.0, so a bar above it makes no pair.
    with monkeypatch.context() as patch:
        patch.setattr(catalogue, "NEIGHBOUR_LEXICAL_THRESHOLD", 1.5)
        assert catalogue.lesson_neighbourhoods(world.home).groups == ()

    # Each lesson compared with its single nearest still joins the three
    # (each one's nearest is another of the three); a limit of zero
    # compares nothing.
    assert _grouped_ids(catalogue.lesson_neighbourhoods(world.home, limit=1)) == [{one, two, three}]
    assert catalogue.lesson_neighbourhoods(world.home, limit=0).groups == ()


def test_a_long_line_is_cut_and_a_short_one_is_whole(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.trio()
    world.fillers()
    with monkeypatch.context() as patch:
        patch.setattr(catalogue, "NEIGHBOUR_LINE_CHARS", 40)
        cut = catalogue.lesson_neighbourhoods(world.home).groups[0].lessons
    assert all(len(lesson.line) == 40 and lesson.line.endswith("…") for lesson in cut), cut
    whole = catalogue.lesson_neighbourhoods(world.home).groups[0].lessons[0].line
    assert whole.startswith("**When about to restart the docker daemon:**")  # no leading dash
    assert "check the compose file first" in whole


# ------------------------------------------------------------- the text


def _placed(lesson_id: str) -> catalogue.PlacedLessons:
    """A catalogue that lists *lesson_id* on one surface, built by hand."""
    surface = catalogue.Surface(
        key="user-claude-md-surface",
        kind=catalogue.KIND_CLAUDE_MD,
        title="CLAUDE.md, reached by user (claude-md)",
        loaded="every session, in every project",
        target=Path("/fixture/CLAUDE.md"),
        window_days=30,
        lessons=(
            catalogue.PlacedLesson(
                id=lesson_id, line="- x", words=1, fires=0, placed_by="human", age_days=3
            ),
        ),
    )
    return catalogue.PlacedLessons(
        surfaces={surface.key: surface}, unlisted=(), unreadable=()
    )


def test_the_text_names_each_lessons_surface_when_given_the_catalogue(world: World) -> None:
    one, two, three = world.trio()
    waiting = world.lesson(5, status="pending")
    world.fillers()
    hoods = catalogue.lesson_neighbourhoods(world.home)
    assert {one, two, three, waiting} == set().union(*_grouped_ids(hoods))

    with_surfaces = catalogue.render_neighbourhoods(hoods, _placed(one))
    assert f"- {one} [user; placed, surface user-claude-md-surface]" in with_surfaces
    assert f"- {two} [project proj-a; placed, on no loaded surface]" in with_surfaces
    assert f"- {waiting} [user; pending]" in with_surfaces  # pending lessons have no surface

    bare = catalogue.render_neighbourhoods(hoods)
    assert f"- {one} [user; placed]" in bare
    assert ", surface " in with_surfaces  # control: the text above did name one
    assert ", surface " not in bare and "on no loaded surface" not in bare


def test_the_text_lists_the_nearest_neighbours_of_each_lesson(world: World) -> None:
    one, two, three = world.trio()
    world.fillers()
    text = catalogue.render_neighbourhoods(catalogue.lesson_neighbourhoods(world.home))

    assert "## Group 1: 3 lessons in 3 bucket(s)" in text
    assert "Buckets: project proj-a; project proj-b; user" in text
    assert f"  near: {two} 1.00 (words), {three} 1.00 (words)" in text  # under the first lesson
    assert text.endswith("\n") and not text.endswith("\n\n")
    # The same ledger gives the same text, byte for byte.
    assert catalogue.render_neighbourhoods(catalogue.lesson_neighbourhoods(world.home)) == text
    assert one in text


def test_only_the_nearest_few_are_shown_under_a_lesson(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.trio()
    world.lesson(4, bucket="project:proj-a")
    world.fillers()
    hoods = catalogue.lesson_neighbourhoods(world.home)
    assert len(hoods.groups[0].lessons) == 4

    full = catalogue.render_neighbourhoods(hoods)
    assert full.count("  near: ") == 4
    assert max(line.count("(words)") for line in full.splitlines() if "near:" in line) == 3

    monkeypatch.setattr(catalogue, "NEIGHBOUR_NEAR_SHOWN", 1)
    narrow = catalogue.render_neighbourhoods(hoods)
    assert max(line.count("(words)") for line in narrow.splitlines() if "near:" in line) == 1
