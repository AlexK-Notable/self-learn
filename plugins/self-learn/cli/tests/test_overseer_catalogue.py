"""The catalogue the overseer's skill-discovery step reads (K3a).

``overseer/catalogue.py`` builds two read-only views: every routed lesson by
the surface it is loaded from, and every skill Claude Code loads on this
machine. These tests run it over a fixture ledger, a fixture ``~/.claude`` and
a fixture host repo. Nothing here touches the real ledger or the real cache.

How the assertions are guarded:

* Every claim that something is ABSENT (a superseded lesson, a rejected one, a
  fire outside the window, a skill switched off) sits next to a control that
  shows the same shape PRESENT: the lesson was listed before it was superseded,
  a neighbour in the same ledger is listed, a fire inside the window is counted.
* Expected word counts and lines are written out by hand, never recomputed with
  the function under test.
* ``test_building_the_catalogue_writes_nothing`` hashes every file and lists
  every directory entry of the ledger (``.git`` included), the ``~/.claude``
  fixture, the host repo and the cache, before and after, and first checks the
  snapshot is not empty.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import hosts, report, verbs
from self_learn.ledger import Bucket, discover_buckets
from self_learn.overseer import catalogue
from self_learn.records import Record, format_covered_by
from support import commit_all, git, iso, make_home

#: Every age and window in these tests is measured from this instant, so no
#: assertion depends on the day the suite runs.
NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

#: A lesson id is eight hex digits after ``lrn-``.
_ID = "lrn-{:08x}"


def _ago(days: int) -> str:
    return iso(NOW - timedelta(days=days))


# ------------------------------------------------------------------ world


class World:
    """A fixture ledger, host repo (skills root and project in one), a
    ``~/.claude`` directory and a cache directory."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.home = make_home(tmp_path)
        self.host = tmp_path / "host-repo"
        self.claude = tmp_path / "claude"
        self.cache = tmp_path / "cache"
        (self.claude / "skills").mkdir(parents=True)
        (self.claude / "CLAUDE.md").write_text("# user\n", encoding="utf-8")
        (self.cache / "self-learn").mkdir(parents=True)
        (self.cache / "self-learn" / "marker").write_text("pre-existing\n", encoding="utf-8")
        monkeypatch.setenv("XDG_CACHE_HOME", str(self.cache))
        monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(self.claude))
        self.slug = hosts.slug_for(self.host)
        self.project_bucket = self.home / "projects" / self.slug
        self.project_bucket.mkdir(parents=True)
        (self.project_bucket / "meta.yaml").write_text(
            f"path: {self.host}\n", encoding="utf-8"
        )
        # The skill the fixture host carries gets frontmatter, so it has a
        # description to list. It sits at plugins/s-plugin/skills/s, NOT the
        # plugins/<name>/skills/<name> layout a new-skill route resolves to.
        self.skill_dir = self.host / "plugins" / "s-plugin" / "skills" / "s"
        (self.skill_dir / "SKILL.md").write_text(
            "---\nname: s\ndescription: The s skill, for fixtures.\n---\n\n# s\n",
            encoding="utf-8",
        )
        # A new-skill route needs the skills root's marketplace.json (the
        # compiler refuses one without it); committed, so no target is dirty.
        (self.host / ".claude-plugin").mkdir()
        (self.host / ".claude-plugin" / "marketplace.json").write_text(
            '{"plugins": []}\n', encoding="utf-8"
        )
        commit_all(self.host, "fixture skill frontmatter + marketplace")

    @property
    def project_label(self) -> str:
        return f"host-repo-{self.slug[-8:]}"

    def record(self, record_id: str) -> tuple[Bucket, Record]:
        path = next(self.home.rglob(f"{record_id}.md"))
        bucket = next(b for b in discover_buckets(self.home) if b.path == path.parent.parent)
        return bucket, Record.from_path(path)

    def compiler_target(self, record_id: str) -> Path:
        """The file the COMPILER resolves a managed-section lesson to,
        asked of ``verbs.managed_target_for`` directly (the oracle the
        catalogue is checked against, not a copy of its logic)."""
        bucket, record = self.record(record_id)
        target = verbs.managed_target_for(
            self.home, bucket, record, user_claude_md=self.claude / "CLAUDE.md"
        )
        assert target is not None, record_id
        return target

    def bucket(self, scope: str) -> Path:
        """The bucket directory a record of *scope* is written into."""
        if scope == "user":
            return self.home / "user"
        if scope == "project":
            return self.project_bucket
        return self.home / "skills" / scope.partition(":")[2]

    def lesson(
        self,
        number: int,
        *,
        scope: str = "user",
        destination: str = "claude-md",
        variant: str | None = None,
        rules_topic: str | None = None,
        new_skill: str | None = None,
        reference_file: str | None = None,
        by: str = "human",
        status: str = "routed",
        superseded_by: str | None = None,
        age: int = 40,
        trigger: str | None = None,
        instruction: str = "Stop first.",
        fact: str | None = None,
        where: str = "resolved",
    ) -> str:
        """Write one lesson (a behavior lesson, or a knowledge lesson when
        *fact* is given) into its bucket and return its id."""
        record_id = _ID.format(number)
        if fact is not None:
            record = Record.create(
                type="knowledge",
                scope=scope,
                source="teach",
                fact=fact,
                record_id=record_id,
                created_at=_ago(age),
            )
        else:
            record = Record.create(
                type="behavior",
                scope=scope,
                source="teach",
                kind="anti-pattern",
                trigger=trigger or "About to edit the thing.",
                instruction=instruction,
                record_id=record_id,
                created_at=_ago(age),
            )
        routing: dict = {"routed_at": _ago(age - 1), "destination": destination, "by": by}
        if variant is not None:
            routing["variant"] = variant
        if rules_topic is not None:
            routing["rules_topic"] = rules_topic
        if new_skill is not None:
            routing["new_skill"] = new_skill
        if reference_file is not None:
            routing["reference_file"] = reference_file
        record.set_routing(routing)
        record.set_status(status)
        if superseded_by is not None:
            record.set_superseded_by(superseded_by)
        directory = self.bucket(scope) / where
        directory.mkdir(parents=True, exist_ok=True)
        record.write(directory / f"{record_id}.md")
        return record_id

    def fire(self, record_id: str, days: int) -> None:
        line = json.dumps(
            {
                "ts": _ago(days),
                "kind": "fire",
                "record": record_id,
                "outcome": "suspected-compliance",
            }
        )
        telemetry = self.home / "telemetry"
        telemetry.mkdir(parents=True, exist_ok=True)
        with (telemetry / "fires.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def placed(self) -> catalogue.PlacedLessons:
        return catalogue.placed_lessons(self.home, claude_dir=self.claude, now=NOW)

    def machine(self) -> catalogue.SkillsOnMachine:
        return catalogue.skills_on_machine(self.home, claude_dir=self.claude)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def _by_file(placed: catalogue.PlacedLessons) -> dict[Path, list[str]]:
    """``{surface file: [lesson ids, in order]}``. Fails if two surfaces
    name the same file."""
    files = [surface.target for surface in placed.surfaces.values()]
    assert len(files) == len(set(files)), f"two surfaces share a file: {files}"
    return {s.target: [x.id for x in s.lessons] for s in placed.surfaces.values()}


def _surface_at(placed: catalogue.PlacedLessons, target: Path) -> catalogue.Surface:
    """The one surface whose file is *target*."""
    found = [s for s in placed.surfaces.values() if s.target == target.resolve()]
    assert len(found) == 1, f"{len(found)} surfaces for {target}: {list(placed.surfaces)}"
    return found[0]


def _rows(placed: catalogue.PlacedLessons) -> dict[str, catalogue.PlacedLesson]:
    """Every listed lesson by id. Fails if one id is listed twice."""
    counts = Counter(
        lesson.id for surface in placed.surfaces.values() for lesson in surface.lessons
    )
    assert all(n == 1 for n in counts.values()), f"a lesson is listed twice: {counts}"
    return {
        lesson.id: lesson
        for surface in placed.surfaces.values()
        for lesson in surface.lessons
    }


# --------------------------------------------- (a) each lesson once, on its surface


def test_each_routed_lesson_appears_once_under_the_file_the_compiler_writes(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    u1 = world.lesson(1)
    u2 = world.lesson(2, by="steward", age=3, trigger="About to run the other thing.")
    p1 = world.lesson(3, scope="project", by="overseer")
    p2 = world.lesson(4, scope="project", variant="local")
    r1 = world.lesson(5, variant="rules", rules_topic="git-style")
    s1 = world.lesson(6, scope="skill:s", destination="skill-md")
    # A new-skill route named s: the compiler resolves it to
    # plugins/s/skills/s/SKILL.md, NOT the s-plugin folder skill s lives in.
    n1 = world.lesson(7, destination="new-skill", new_skill="s")
    ref = world.lesson(8, scope="skill:s", destination="reference")
    k1 = world.lesson(9, fact="The router is at 192.0.2.1.", age=12)
    # A named shelf file is its own surface, apart from LEARNINGS.md (the
    # compiler appends only to a named shelf that exists).
    (world.skill_dir / "references").mkdir()
    (world.skill_dir / "references" / "gotchas.md").write_text("# gotchas\n", encoding="utf-8")
    # CLAUDE.local.md is git-ignored, as a route to it requires.
    (world.host / ".gitignore").write_text("CLAUDE.local.md\n", encoding="utf-8")
    commit_all(world.host, "gotchas shelf + .gitignore")
    ref2 = world.lesson(10, scope="skill:s", destination="reference", reference_file="gotchas.md")
    # u1 fired twice inside 30 days and once outside; u2 never.
    world.fire(u1, 5)
    world.fire(u1, 10)
    world.fire(u1, 45)

    placed = world.placed()

    # Every expected file written out by hand.
    shelf = world.skill_dir / "references"
    expected = {
        world.claude / "CLAUDE.md": [u1, k1, u2],  # oldest routing first
        world.host / "CLAUDE.md": [p1],
        world.host / "CLAUDE.local.md": [p2],
        world.claude / "rules" / "git-style.md": [r1],
        world.skill_dir / "SKILL.md": [s1],
        world.host / "plugins" / "s" / "skills" / "s" / "SKILL.md": [n1],
        shelf / "LEARNINGS.md": [ref],
        shelf / "gotchas.md": [ref2],
    }
    assert _by_file(placed) == {path.resolve(): ids for path, ids in expected.items()}
    # ...and each managed-section lesson's file is the one the compiler
    # itself resolves (asked of managed_target_for, not of the catalogue).
    for lesson in (u1, u2, k1, p1, p2, r1, s1, n1):
        listed = next(s for s in placed.surfaces.values() if lesson in [x.id for x in s.lessons])
        assert listed.target == world.compiler_target(lesson), lesson
    # One key per file, each filesystem-safe.
    assert len(placed.surfaces) == len(expected)
    for key in placed.surfaces:
        assert re.fullmatch(r"[A-Za-z0-9._-]+", key) and not key.startswith("."), key

    rows = _rows(placed)  # also proves no id is listed twice
    assert set(rows) == {u1, u2, p1, p2, r1, s1, n1, ref, ref2, k1}

    # The line is the compiler's, word for word; 10 words by hand:
    # "-", "**When", "about", "to", "edit", "the", "thing:**", "stop", "first.", "*(id)*"
    assert rows[u1].line == f"- **When about to edit the thing:** stop first. *({u1})*"
    assert rows[u1].words == 10
    assert rows[u1].fires == 2  # the 45-day-old fire is outside the window
    assert rows[u1].placed_by == "human"
    assert rows[u1].age_days == 40
    # A knowledge lesson compiles to its fact: 7 words by hand.
    assert rows[k1].line == f"- The router is at 192.0.2.1. *({k1})*"
    assert rows[k1].words == 7
    assert rows[k1].age_days == 12
    assert rows[u2].fires == 0
    assert rows[u2].placed_by == "steward"
    assert rows[u2].age_days == 3
    assert rows[p1].placed_by == "overseer"

    # A reference shelf holds the block as compiled, not a one-line entry.
    assert rows[ref].line.startswith(f"## {_ago(39)[:10]} — {ref}\n")
    assert "**Trigger:** About to edit the thing." in rows[ref].line
    assert "**Instruction:** Stop first." in rows[ref].line

    assert placed.unlisted == ()
    assert placed.unreadable == ()

    # POSITIVE CHECK AGAINST THE COMPILER: a real recompile of this scratch
    # ledger writes every listed line into the file it is listed under, and
    # into no other listed file.
    monkeypatch.setenv("HOME", str(world.tmp / "home"))  # never the real ~/.claude
    result = verbs.recompile(world.home, no_push=True, user_claude_md=world.claude / "CLAUDE.md")
    # The one warning this git-mode fixture gives: the git-ignored
    # CLAUDE.local.md cannot be committed to the host repo. Its line is still
    # written to the file, which the loop below checks like every other.
    local = (world.host / "CLAUDE.local.md").resolve()
    assert [w for w in result.warnings if not w.startswith(f"{local}: host commit refused")] == []
    written = {entry.target.resolve() for entry in result.entries if entry.changed}
    assert set(_by_file(placed)) - {local} <= written, "the compiler skipped a listed file"
    for surface in placed.surfaces.values():
        text = surface.target.read_text(encoding="utf-8")
        others = [o for o in placed.surfaces.values() if o.target != surface.target]
        for lesson in surface.lessons:
            assert lesson.line in text, f"{lesson.id} is not in {surface.target}"
            for other in others:
                assert lesson.id not in other.target.read_text(encoding="utf-8"), (
                    f"{lesson.id} is also in {other.target}"
                )


def test_a_file_reached_by_a_project_and_by_the_skills_root_is_one_surface(
    world: World, tmp_path: Path
) -> None:
    # The fixture host is registered as a project AND as the skills root:
    # its CLAUDE.md takes project claude-md lessons and skill-scope
    # claude-md lessons alike.
    p1 = world.lesson(1, scope="project", trigger="About to touch the project.")
    q1 = world.lesson(2, scope="skill:s", trigger="About to touch the skills root.")
    # A second project bucket whose host path is a symlink to the same repo
    # (named by hand: slug_for resolves the link, so it would name the first).
    link = tmp_path / "host-link"
    link.symlink_to(world.host)
    linked_bucket = world.home / "projects" / "-host-link-0badf00d"
    linked_bucket.mkdir(parents=True)
    (linked_bucket / "meta.yaml").write_text(f"path: {link}\n", encoding="utf-8")
    l1 = _ID.format(3)
    record = Record.create(
        type="behavior", scope="project", source="teach", kind="anti-pattern",
        trigger="About to touch the link.", instruction="Stop first.",
        record_id=l1, created_at=_ago(40),
    )
    record.set_routing({"routed_at": _ago(39), "destination": "claude-md", "by": "human"})
    record.set_status("routed")
    (linked_bucket / "resolved").mkdir()
    record.write(linked_bucket / "resolved" / f"{l1}.md")
    # CONTROL: a user lesson is on its own surface, so "one surface" below
    # is the grouping, not a catalogue that only ever makes one.
    u1 = world.lesson(4)

    placed = world.placed()

    assert len(placed.surfaces) == 2
    shared = _surface_at(placed, world.host / "CLAUDE.md")
    assert sorted(x.id for x in shared.lessons) == sorted([p1, q1, l1])
    assert [x.id for x in _surface_at(placed, world.claude / "CLAUDE.md").lessons] == [u1]
    # Full word count, by hand: "- **When about to touch the project:**
    # stop first. *(id)*" is 10 words, the link's line 10, and the skills
    # root's line 11 ("skills root:**" is two words).
    words = {x.id: x.words for x in shared.lessons}
    assert words == {p1: 10, q1: 11, l1: 10}
    assert "- Lessons: 3 · words: 31 ·" in catalogue.render_surface(shared)
    # The title names every owner that reaches the file.
    assert shared.owners == (
        "project host-link-0badf00d (claude-md)",
        f"project {world.project_label} (claude-md)",
        "skill s (claude-md)",
    )
    for owner in shared.owners:
        assert owner in shared.title


def test_a_skill_and_another_skills_shelf_with_the_same_readable_name_stay_apart(
    world: World,
) -> None:
    # Skill "s-reference-gotchas" (its SKILL.md) and skill s's "gotchas"
    # shelf read the same in a key ("skill-s-reference-gotchas"), but they
    # are two files, so they are two surfaces with two keys.
    odd_dir = world.host / "plugins" / "odd-plugin" / "skills" / "s-reference-gotchas"
    odd_dir.mkdir(parents=True)
    (odd_dir / "SKILL.md").write_text("# odd\n", encoding="utf-8")
    on_skill = world.lesson(1, scope="skill:s-reference-gotchas", destination="skill-md")
    on_shelf = world.lesson(2, scope="skill:s", destination="reference", reference_file="gotchas.md")

    placed = world.placed()

    by_file = _by_file(placed)
    assert by_file == {
        (odd_dir / "SKILL.md").resolve(): [on_skill],
        (world.skill_dir / "references" / "gotchas.md").resolve(): [on_shelf],
    }
    keys = list(placed.surfaces)
    assert len(set(keys)) == 2
    # Both keys carry the same readable part; the file's digest tells them apart.
    assert all(key.startswith("skill-s-reference-gotchas-") for key in keys)


def test_rendered_surface_shows_the_line_verbatim_and_its_numbers(world: World) -> None:
    u1 = world.lesson(1)
    world.fire(u1, 5)
    world.fire(u1, 10)

    texts = catalogue.render_surfaces(world.placed())

    # Positive control: the surface exists and is rendered.
    assert len(texts) == 1
    key, text = next(iter(texts.items()))
    assert re.fullmatch(r"user-claude-md-[0-9a-f]{8}", key)
    assert text.startswith(f"# {key}\n\nCLAUDE.md, reached by user (claude-md)\n")
    assert f"- File: {(world.claude / 'CLAUDE.md').resolve()}" in text
    assert "- Loaded: every session, in every project" in text
    assert "- Lessons: 1 · words: 10 · fires counted over the last 30 days" in text
    # The line, then its numbers on the next line, in the configured order.
    assert (
        f"- **When about to edit the thing:** stop first. *({u1})*\n"
        "  - words: 10 · fires in the last 30 days: 2 · placed by: human · age in days: 40\n"
    ) in text


def test_surface_keys_are_filesystem_safe_and_stable(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    safe = world.lesson(1, variant="rules", rules_topic="plain-topic")
    odd = world.lesson(2, variant="rules", rules_topic="a/b c")
    other = world.lesson(3, variant="rules", rules_topic="a b/c")
    long_topic = "/".join(["segment"] * 20)
    deep = world.lesson(4, variant="rules", rules_topic=long_topic)

    placed = world.placed()

    keys = {x.id: k for k, v in placed.surfaces.items() for x in v.lessons}
    assert len(set(keys.values())) == 4
    for key in keys.values():
        assert re.fullmatch(r"[A-Za-z0-9._-]+", key), key
        assert not key.startswith("."), key
        assert len(key) <= catalogue.KEY_MAX, key
    # The readable part comes from the file; the digest is of its path.
    assert re.fullmatch(r"user-rules-plain-topic-[0-9a-f]{8}", keys[safe])
    assert keys[deep].startswith("user-rules-segment-segment-")
    # "a/b c" and "a b/c" are two files whose readable parts are the same
    # text; their keys still differ.
    assert keys[odd].startswith("user-rules-a-b-c-") and keys[other].startswith("user-rules-a-b-c-")
    assert keys[odd] != keys[other]
    # A key stays the same when another surface is added...
    world.lesson(5)  # a user CLAUDE.md lesson appears
    again = {x.id: k for k, v in world.placed().surfaces.items() for x in v.lessons}
    assert {lesson: again[lesson] for lesson in keys} == keys
    # ...and when the knob changes, every key obeys the new limit.
    monkeypatch.setattr(catalogue, "KEY_MAX", 30)
    for key in world.placed().surfaces:
        assert len(key) <= 30, key


# -------------------------------------------- (b) a superseded lesson is not listed


def test_a_superseded_lesson_is_not_listed_but_was_before(world: World) -> None:
    keep = world.lesson(1)
    old = world.lesson(2, trigger="About to do the old thing.")

    before = _rows(world.placed())
    # CONTROL: the lesson is listed while it is still routed.
    assert old in before and keep in before

    new = world.lesson(3, trigger="About to do the new thing.")
    world.lesson(2, status="superseded", superseded_by=new, trigger="About to do the old thing.")

    after = _rows(world.placed())
    assert old not in after, "a superseded lesson is still listed"
    assert new in after and keep in after


def test_rejected_deferred_and_pending_lessons_are_not_listed(world: World) -> None:
    routed = world.lesson(1)
    # A rejected lesson that still carries its old routing block, a deferred
    # one and a pending one, the last two where such lessons live.
    rejected = world.lesson(2, status="rejected")
    deferred = world.lesson(3, status="deferred", where="pending")
    pending = world.lesson(4, status="pending", where="pending")

    rows = _rows(world.placed())

    # CONTROL: the same ledger lists the routed lesson, so the absences below
    # are the status filter, not an empty walk. And the rejected record IS on
    # disk in resolved/, where the walk reads.
    assert routed in rows
    assert (world.home / "user" / "resolved" / f"{rejected}.md").is_file()
    for hidden in (rejected, deferred, pending):
        assert hidden not in rows, f"{hidden} is listed but is not placed"


# ----------------------------------------- (c) a successor carries the fires


def test_a_replaced_lessons_successor_carries_its_fires(world: World) -> None:
    # Chain 1: old -> new. The old line fired twice in the window and once
    # outside it; the new line fired once under its own id.
    old1 = _ID.format(0x101)
    new1 = world.lesson(0x102, trigger="About to do the rewritten thing.")
    world.lesson(0x101, status="superseded", superseded_by=new1)
    world.fire(old1, 4)
    world.fire(old1, 12)
    world.fire(old1, 50)
    world.fire(new1, 2)
    # Chain 2, two steps: x -> y -> z. Only x fired.
    x = _ID.format(0x201)
    y = _ID.format(0x202)
    z = world.lesson(0x203, trigger="About to do the third thing.")
    world.lesson(0x202, status="superseded", superseded_by=z)
    world.lesson(0x201, status="superseded", superseded_by=y)
    world.fire(x, 6)
    # Chain 3: the only fire on the old line is outside the window.
    old3 = _ID.format(0x301)
    new3 = world.lesson(0x302, trigger="About to do the stale thing.")
    world.lesson(0x301, status="superseded", superseded_by=new3)
    world.fire(old3, 45)
    # An unrelated lesson with one fire, and one with none.
    quiet = world.lesson(0x401, trigger="About to do the quiet thing.")
    busy = world.lesson(0x402, trigger="About to do the busy thing.")
    world.fire(busy, 1)
    # A lesson retired into a surface (covered_by) is not live either.
    retired = _ID.format(0x501)
    world.lesson(0x501, status="superseded", superseded_by=format_covered_by("skill-md", "s"))
    world.fire(retired, 3)

    rows = _rows(world.placed())

    assert rows[new1].fires == 3, "the successor must carry 2 predecessor fires plus its own"
    assert rows[z].fires == 1, "a fire two steps up the chain must reach the live lesson"
    # The window applies BEFORE the credit: control is chain 1, where an
    # in-window fire on the old line does credit.
    assert rows[new3].fires == 0
    # Credit does not leak past its chain.
    assert rows[busy].fires == 1
    assert rows[quiet].fires == 0
    # The replaced lessons themselves are not listed.
    for gone in (old1, x, y, old3, retired):
        assert gone not in rows


# ------------------------------------------------------- (d) skills on the machine


def _skill_md(directory: Path, description_line: str | None, name: str = "x") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if description_line is None:
        body = f"# {name}\n\nno frontmatter here\n"
    else:
        body = f"---\nname: {name}\ndescription: {description_line}\n---\n\n# {name}\n"
    (directory / "SKILL.md").write_text(body, encoding="utf-8")


def _plugin(world: World, key: str, skills: dict[str, str]) -> Path:
    """An installed, enabled plugin whose folder is named in
    installed_plugins.json."""
    root = world.tmp / "plugin-cache" / key.replace("@", "-")
    for name, description in skills.items():
        _skill_md(root / "skills" / name, description, name)
    plugins_dir = world.claude / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    installed_path = plugins_dir / "installed_plugins.json"
    installed = json.loads(installed_path.read_text()) if installed_path.exists() else {"plugins": {}}
    installed["plugins"][key] = [{"scope": "user", "installPath": str(root)}]
    installed_path.write_text(json.dumps(installed), encoding="utf-8")
    return root


def _settings(world: World, **keys: object) -> None:
    path = world.claude / "settings.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data.update(keys)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_skills_index_lists_personal_symlinked_plugin_and_host_skills(world: World) -> None:
    # One lesson is compiled into skill s's SKILL.md (plugins/s-plugin/...).
    world.lesson(6, scope="skill:s", destination="skill-md")
    # A new-skill route named s resolves to plugins/s/skills/s/SKILL.md, a
    # different file (absent here): it is NOT one of skill s's lessons.
    world.lesson(7, destination="new-skill", new_skill="s")
    # A new-skill route named n IS compiled into skill n's SKILL.md, which
    # sits where new-skill puts it (plugins/n/skills/n).
    n_dir = world.host / "plugins" / "n" / "skills" / "n"
    _skill_md(n_dir, "The n skill.", "n")
    (world.claude / "skills" / "n").symlink_to(n_dir)
    world.lesson(9, destination="new-skill", new_skill="n")
    # A superseded lesson routed there must not count (control: it was counted
    # in the ledger before it was superseded, see the superseded test).
    world.lesson(8, scope="skill:s", destination="skill-md", status="superseded", superseded_by=_ID.format(6))
    # personal: a real folder (its description holds ": ", which is not plain
    # YAML, so it comes through report.py's lenient extractor)
    _skill_md(world.claude / "skills" / "personal-one", "Does a thing: carefully.", "personal-one")
    # personal, no frontmatter: listed, with no description
    _skill_md(world.claude / "skills" / "bare", None)
    # personal, a symlink into the skills root (claude-skills)
    (world.claude / "skills" / "s").symlink_to(world.skill_dir)
    # plugin
    _plugin(world, "demo@market", {"drawing": "Draw diagrams."})
    _settings(world, enabledPlugins={"demo@market": True})
    # host project skill
    _skill_md(world.host / ".claude" / "skills" / "hostskill", "A host skill.", "hostskill")

    machine = world.machine()

    by_name = {s.name: s for s in machine.skills}
    assert set(by_name) == {"personal-one", "bare", "s", "n", "demo:drawing", "hostskill"}

    personal = by_name["personal-one"]
    assert personal.where == "personal"
    assert personal.path == str(world.claude / "skills" / "personal-one")
    assert personal.resolves_to is None and personal.repo is None
    assert personal.description == "Does a thing: carefully."
    assert personal.lessons == 0
    assert by_name["bare"].description is None

    linked = by_name["s"]
    assert linked.where == "personal"
    assert linked.path == str(world.claude / "skills" / "s")
    assert linked.resolves_to == str(world.skill_dir.resolve())
    assert linked.repo == "host-repo"
    assert linked.description == "The s skill, for fixtures."
    assert linked.lessons == 1
    assert by_name["n"].lessons == 1

    plugin = by_name["demo:drawing"]
    assert plugin.where == "plugin"
    assert plugin.plugin == "demo@market"
    assert plugin.description == "Draw diagrams."
    assert plugin.path == str(world.tmp / "plugin-cache" / "demo-market" / "skills" / "drawing")

    host = by_name["hostskill"]
    assert host.where == "host"
    assert host.host == str(world.host)
    assert host.description == "A host skill."
    # The fixture repo is registered as a project AND as the skills root: one
    # host, so its skill is not listed as reachable "also" through itself.
    assert host.also == ()

    assert machine.not_loaded == ()
    assert machine.problems == ()


def test_the_skills_index_renders_as_yaml_ready_data(world: World) -> None:
    world.lesson(6, scope="skill:s", destination="skill-md")
    (world.claude / "skills" / "s").symlink_to(world.skill_dir)
    _skill_md(world.claude / "skills" / "personal-one", "A personal skill.", "personal-one")

    index = catalogue.render_skills_index(world.machine())

    # Plain data: it survives a round trip through the safe YAML dumper.
    import io

    yaml = YAML(typ="safe")
    buffer = io.StringIO()
    yaml.dump(index, buffer)
    assert yaml.load(buffer.getvalue()) == index

    rows = {row["name"]: row for row in index["skills"]}
    assert list(rows["s"]) == [
        "name", "description", "where", "path", "resolves_to", "repo", "lessons",
    ]
    assert rows["s"]["lessons"] == 1
    # Empty optional fields are left out of the row.
    assert list(rows["personal-one"]) == ["name", "description", "where", "path", "lessons"]
    assert index["counts"] == {"total": 2, "personal": 2}
    assert index["not_loaded"] == [] and index["problems"] == []


def test_a_skill_switched_off_is_not_listed_as_loaded(world: World) -> None:
    _skill_md(world.claude / "skills" / "on", "Loaded.", "on")
    _skill_md(world.claude / "skills" / "off", "Switched off.", "off")
    _plugin(world, "demo@market", {"drawing": "Draw.", "muted": "Muted."})
    _settings(
        world,
        enabledPlugins={"demo@market": True},
        skillOverrides={"off": "off", "demo:muted": "off"},
    )

    machine = world.machine()

    # CONTROL: the on-skills of the same two places are listed.
    assert {s.name for s in machine.skills} == {"on", "demo:drawing"}
    assert {n["name"] for n in machine.not_loaded} == {"off", "demo:muted"}


def test_a_disabled_plugin_contributes_no_skills(world: World) -> None:
    _plugin(world, "live@market", {"one": "Live."})
    _plugin(world, "dead@market", {"two": "Dead."})
    _settings(world, enabledPlugins={"live@market": True, "dead@market": False})

    names = {s.name for s in world.machine().skills}

    assert names == {"live:one"}  # control: the enabled plugin's skill is there


def test_a_plugin_whose_install_is_not_recorded_is_found_through_its_marketplace(
    world: World,
) -> None:
    # No installed_plugins.json: the marketplace names the plugin's folder.
    market = world.tmp / "market"
    (market / ".claude-plugin").mkdir(parents=True)
    (market / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "viaindex", "source": "./plugins/viaindex"}]}),
        encoding="utf-8",
    )
    _skill_md(market / "plugins" / "viaindex" / "skills" / "found", "Found.", "found")
    (world.claude / "plugins").mkdir()
    (world.claude / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"mkt": {"installLocation": str(market)}}), encoding="utf-8"
    )
    _settings(world, enabledPlugins={"viaindex@mkt": True, "ghost@mkt": True})

    machine = world.machine()

    assert [s.name for s in machine.skills] == ["viaindex:found"]
    # An enabled plugin that cannot be found is named, not skipped in silence.
    assert any("ghost@mkt" in p for p in machine.problems)


def test_personal_skills_match_the_report_skills_index(world: World) -> None:
    """The catalogue reuses report.py's description extractor and its
    de-duplication on the resolved SKILL.md. This pins that the personal part
    of the two indexes names the same skills."""
    _skill_md(world.claude / "skills" / "plain", "Plain.", "plain")
    _skill_md(world.claude / "skills" / "colon", "Has a colon: here.", "colon")
    _skill_md(world.claude / "skills" / "bare", None)
    (world.claude / "skills" / "s").symlink_to(world.skill_dir)
    # A second link to the same SKILL.md: both indexes list it once.
    (world.claude / "skills" / "s-again").symlink_to(world.skill_dir)

    row = report._skill_description_row(world.home)
    machine = world.machine()

    in_report = {s["name"] for s in row["skills"]}
    in_catalogue = {
        Path(s.path).name
        for s in machine.skills
        if s.where == "personal" and s.description is not None
    }
    assert in_report, "positive control: the report index found skills"
    assert in_report == in_catalogue
    # The same skill reached by two links is one entry, with the second link kept.
    linked = [s for s in machine.skills if s.resolves_to == str(world.skill_dir.resolve())]
    assert len(linked) == 1
    assert len(linked[0].also) == 1


# ------------------------------------------------------------ (e) nothing written


def _snapshot(*roots: Path) -> dict[str, str]:
    """Every entry under each root: a file by the hash of its bytes, a
    directory or a link by its kind. A stray ``mkdir`` shows up here."""
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


def test_building_the_catalogue_writes_nothing(world: World) -> None:
    u1 = world.lesson(1)
    new = world.lesson(3, trigger="About to do the new thing.")
    world.lesson(2, status="superseded", superseded_by=new)
    world.lesson(4, scope="skill:s", destination="skill-md")
    world.lesson(5, scope="skill:s", destination="reference")
    world.lesson(6, destination="hook")
    world.fire(u1, 5)
    (world.claude / "skills" / "s").symlink_to(world.skill_dir)
    _plugin(world, "demo@market", {"drawing": "Draw."})
    _settings(world, enabledPlugins={"demo@market": True})
    roots = (world.home, world.host, world.claude, world.cache, world.tmp / "plugin-cache")

    before = _snapshot(*roots)
    head_before = git(world.home, "rev-parse", "HEAD").stdout
    # CONTROL: the snapshot sees files in every root, including the cache
    # marker and the ledger's .git, so "unchanged" is not "saw nothing".
    assert len(before) > 20
    assert str(world.cache / "self-learn" / "marker") in before
    assert any("/.git/" in key for key in before)
    assert any(key.endswith("fires.jsonl") for key in before)

    # Every public entry point, including both renderers.
    placed = catalogue.placed_lessons(world.home, claude_dir=world.claude, now=NOW)
    catalogue.render_surfaces(placed)
    machine = catalogue.skills_on_machine(world.home, claude_dir=world.claude, placed=placed)
    catalogue.render_skills_index(machine)
    built = catalogue.build_catalogue(world.home, claude_dir=world.claude, now=NOW)
    # CONTROL: the calls did real work.
    assert built.surfaces and built.skills_index["skills"]

    assert _snapshot(*roots) == before
    assert git(world.home, "rev-parse", "HEAD").stdout == head_before


# ---------------------------------------------------- lessons the catalogue cannot place


def test_a_hook_lesson_and_an_unresolvable_target_are_named_not_dropped(
    world: World,
) -> None:
    listed = world.lesson(1)
    hook = world.lesson(2, destination="hook")
    # A project whose host cannot be found (no meta.yaml) has no target file.
    orphan = world.home / "projects" / "-nowhere-deadbeef"
    (orphan / "resolved").mkdir(parents=True)
    record = Record.create(
        type="behavior", scope="project", source="teach", kind="anti-pattern",
        trigger="About to guess.", instruction="Look first.",
        record_id=_ID.format(3), created_at=_ago(9),
    )
    record.set_routing({"routed_at": _ago(8), "destination": "claude-md", "by": "human"})
    record.set_status("routed")
    record.write(orphan / "resolved" / f"{_ID.format(3)}.md")

    placed = world.placed()

    # CONTROL: the ordinary lesson is listed in the same ledger.
    assert listed in _rows(placed)
    assert hook not in _rows(placed)
    reasons = dict(item.split(": ", 1) for item in placed.unlisted)
    assert set(reasons) == {hook, _ID.format(3)}
    assert "hook" in reasons[hook]
    assert "cannot be resolved" in reasons[_ID.format(3)]

    # CONTROL for the cause: once the project's host is recorded, the same
    # lesson is listed, so it was the missing target that kept it out.
    (orphan / "meta.yaml").write_text(f"path: {world.host}\n", encoding="utf-8")
    fixed = world.placed()
    assert _ID.format(3) in _rows(fixed)
    assert [item.split(": ", 1)[0] for item in fixed.unlisted] == [hook]


def test_an_unreadable_record_is_named_and_the_rest_still_list(world: World) -> None:
    good = world.lesson(1)
    bad = world.home / "user" / "resolved" / "lrn-0000bad1.md"
    bad.write_text("this is not a record\n", encoding="utf-8")

    placed = world.placed()

    assert good in _rows(placed)
    assert placed.unreadable == ("user/user/lrn-0000bad1.md",)


# --------------------------------------------------------------- the knobs


def test_the_knobs_at_the_top_of_the_module_change_the_output(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    u1 = world.lesson(1)
    rejected = world.lesson(2, status="rejected", trigger="About to be rejected.")
    world.fire(u1, 5)
    world.fire(u1, 10)

    # Baseline: window 30, only routed lessons, all four columns.
    base = world.placed()
    assert _rows(base)[u1].fires == 2
    assert rejected not in _rows(base)
    user_md = world.claude / "CLAUDE.md"
    base_text = catalogue.render_surface(_surface_at(base, user_md))
    assert "fires in the last 30 days: 2" in base_text

    monkeypatch.setattr(catalogue, "FIRE_WINDOW_DAYS", 7)
    narrow = world.placed()
    assert _rows(narrow)[u1].fires == 1
    assert "fires in the last 7 days: 1" in catalogue.render_surface(_surface_at(narrow, user_md))
    monkeypatch.setattr(catalogue, "FIRE_WINDOW_DAYS", 30)

    monkeypatch.setattr(catalogue, "PLACED_STATUSES", frozenset({"routed", "rejected"}))
    assert rejected in _rows(world.placed())
    monkeypatch.setattr(catalogue, "PLACED_STATUSES", frozenset({"routed"}))

    monkeypatch.setattr(catalogue, "LESSON_COLUMNS", (("words", "words"),))
    only_words = catalogue.render_surface(_surface_at(world.placed(), user_md))
    assert "  - words: 10\n" in only_words
    assert "placed by" not in only_words

    _skill_md(world.claude / "skills" / "personal-one", "A personal skill.", "personal-one")
    monkeypatch.setattr(catalogue, "SKILL_FIELDS", ("name", "where"))
    row = catalogue.render_skills_index(world.machine())["skills"][0]
    assert row == {"name": "personal-one", "where": "personal"}
