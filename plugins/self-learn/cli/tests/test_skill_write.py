"""SK1 -- ``skill write``: self-learn deploys a skill it owns
(``skill_writer.write`` / ``check``, ``self-learn skill write``;
skill-writing plan §2 step 5, D4, D7, §4.1 row SK1 tests (a)-(f) and (h)).

Every test builds a scratch ledger and a scratch skills root (``make_env``:
one host repo registered as the skills root), points
``SELF_LEARN_CLAUDE_DIR`` (where ``~/.claude/skills/<name>`` links live),
``XDG_CACHE_HOME`` and ``HOME`` at scratch folders, and clears the agent-shell
markers so the CLI's person-only refusal is off unless a test sets one.

Red on master: ``self_learn.skill_writer`` does not exist there, so every
test here fails at import.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import test_skill_template as k1a
from self_learn import (
    cli,
    gitops,
    intents,
    sentinel,
    settings,
    skill_registry,
    skill_writer,
    verbs,
)
from self_learn.compilers import (
    BEGIN_MARKER,
    END_MARKER,
    POINTER_BEGIN_MARKER,
    POINTER_END_MARKER,
)
from self_learn.ledger_ops import create_record
from self_learn.skill_scaffold import _read_frontmatter
from support import commit_all, git, make_behavior, make_env

NAME = "mouse-care"
CASE = "case-1a2b3c4d"
CASE2 = "case-5e6f7a8b"
DESCRIPTION = (
    "Use when flashing, remapping or recovering a gaming mouse's onboard memory over hidraw."
)
REF = "references/buttons.md"
REF_TEXT = "# Buttons\n\nThe three-byte action codes, one row per button.\n"
RID = "lrn-0000aaaa"
RID2 = "lrn-0000bbbb"

#: The seed marketplace is in the ``ensure_ascii=True`` layout the real
#: claude-skills file uses (its em dashes are written ``—``), so a
#: writer that re-dumps it the other way would change bytes it must not.
MARKETPLACE_SEED = {
    "name": "sandbox-skills",
    "metadata": {"description": "Personal skills — a sandbox."},
    "plugins": [
        {
            "name": "s-plugin",
            "source": "./plugins/s-plugin",
            "description": "seeded — plugin",
            "version": "1.0.0",
        }
    ],
}


def draft(
    name: str = NAME,
    *,
    description: str = DESCRIPTION,
    extra: str = "",
    ref_text: str = REF_TEXT,
    metadata: dict | None = None,
) -> dict[str, str]:
    """A valid two-file skill draft: SKILL.md linking one reference."""
    front = [f"name: {name}", f"description: {json.dumps(description)}"]
    if metadata is not None:
        front.append(f"metadata: {json.dumps(metadata)}")
    skill_md = (
        "---\n" + "\n".join(front) + "\n---\n\n# Mouse care\n\n"
        f"How the pieces fit together; the codes are in [the button map]({REF}).\n" + extra
    )
    return {"SKILL.md": skill_md, REF: ref_text}


class Env:
    """A scratch ledger, a scratch skills root with a marketplace, and a
    scratch ``~/.claude``."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for marker in settings.AGENT_CALLER_MARKERS:
            monkeypatch.delenv(marker, raising=False)
        self.tmp = tmp_path
        (tmp_path / "home").mkdir()
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        self.claude = tmp_path / "claude"
        (self.claude / "skills").mkdir(parents=True)
        monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(self.claude))
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.root = sandbox.host
        monkeypatch.setenv("SELF_LEARN_HOME", str(self.home))
        self.marketplace = self.root / ".claude-plugin" / "marketplace.json"
        self.marketplace.parent.mkdir()
        self.marketplace.write_text(
            json.dumps(MARKETPLACE_SEED, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        commit_all(self.root, "marketplace seed")
        self.marketplace_seed = self.marketplace.read_text(encoding="utf-8")

    # -- paths
    def plugin_dir(self, name: str = NAME) -> Path:
        return self.root / "plugins" / name

    def skill_dir(self, name: str = NAME) -> Path:
        return self.plugin_dir(name) / "skills" / name

    def skill_md(self, name: str = NAME) -> Path:
        return self.skill_dir(name) / "SKILL.md"

    def link(self, name: str = NAME) -> Path:
        return self.claude / "skills" / name

    # -- git
    def head(self, repo: Path) -> str:
        return git(repo, "rev-parse", "HEAD").stdout.strip()

    def count(self, repo: Path) -> int:
        return int(git(repo, "rev-list", "--count", "HEAD").stdout)

    def status(self, repo: Path) -> str:
        return git(repo, "status", "--porcelain", "--untracked-files=all").stdout

    def snapshot(self) -> tuple:
        """Everything a refused write must leave as it was."""
        links = sorted(p.name for p in (self.claude / "skills").iterdir())
        return (
            self.head(self.home), self.status(self.home),
            self.head(self.root), self.status(self.root),
            links, (self.home / skill_registry.REGISTRY_FILENAME).exists(),
        )

    def row(self, name: str = NAME) -> dict | None:
        return skill_registry.load(self.home).row(name)

    # -- the verb
    def write(self, files: dict | None = None, *, name: str = NAME, **kwargs):
        kwargs.setdefault("case", CASE)
        kwargs.setdefault("by", "overseer")
        kwargs.setdefault("no_push", True)
        return skill_writer.write(self.home, name, files if files is not None else draft(name), **kwargs)

    def personal_skill(self, name: str) -> None:
        folder = self.claude / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: a personal skill\n---\n\n# {name}\n", encoding="utf-8"
        )

    def veto(self, name: str) -> None:
        def add(registry):
            registry.add_veto(name, at="2026-10-31T00:00:00Z", statement="stmt-0000aaaa")

        skill_registry.with_update(self.home, add, subject=f"veto {name}")


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    return Env(tmp_path, monkeypatch)


def _rules(problems) -> set[str]:
    return {p.split(":", 1)[0] for p in problems}


# ======================================================== (a) the template


def test_control_a_valid_draft_writes(env):
    """The positive control for every refusal below: the same environment
    and a valid draft write the skill."""
    before = env.snapshot()
    result = env.write()
    assert result.ok, result.problems
    assert result.ledger_sha and result.host_sha and result.link == "created"
    assert env.snapshot() != before
    assert env.skill_md().is_file() and env.link().is_symlink()


def test_control_the_template_cases_valid_skill_writes(env):
    """The K1a control skill (reference, managed section, paths, metadata)
    writes under its own name: the cases below differ from it in one thing."""
    result = env.write(k1a.skill(), name=k1a.NAME)
    assert result.ok, result.problems


@pytest.mark.parametrize("case_id", list(k1a.CASES))
def test_each_template_rule_refuses_with_nothing_written(env, case_id):
    case = k1a.CASES[case_id]
    assert case.files != k1a.skill() or case.kwargs  # not the control
    name = case.kwargs.get("expected_name", k1a.NAME)
    for loaded in case.kwargs.get("loaded_names", ()):
        env.personal_skill(loaded)
    for vetoed in case.kwargs.get("vetoed_names", ()):
        env.veto(vetoed)
    before = env.snapshot()

    result = env.write(case.files, name=name)

    assert not result.ok
    assert result.kind == "bad-line"
    assert set(case.expect) <= _rules(result.problems), result.problems
    assert env.snapshot() == before
    assert not env.plugin_dir(name).exists()


def test_check_reports_the_same_refusal_and_writes_nothing(env):
    files = k1a.CASES["name-containing-claude"].files
    before = env.snapshot()
    found = skill_writer.check(env.home, k1a.NAME, files)
    assert not found.ok and found.kind == "bad-line"
    assert "name-reserved-word" in _rules(found.problems)
    assert env.snapshot() == before
    # control: the valid draft checks clean, and still writes nothing
    clean = skill_writer.check(env.home, NAME, draft())
    assert clean.ok and not clean.updating and clean.current_sha is None
    assert env.snapshot() == before


# ===================================================== (b) the secret scan


def test_a_secret_in_a_reference_refuses_and_is_not_repeated(env):
    secret = "AKIA" + "QZ7X" * 4  # the aws-key shape, built here so no literal is committed
    files = draft(ref_text=f"# Buttons\n\nThe vendor key is {secret} for the flasher.\n")
    before = env.snapshot()
    result = env.write(files)
    assert not result.ok and result.kind == "bad-line"
    assert any("secret scan" in p and REF in p for p in result.problems), result.problems
    assert all(secret not in p for p in result.problems)
    assert env.snapshot() == before


def test_a_secret_in_skill_md_refuses_too(env):
    secret = "ghp_" + "a1B2" * 9
    result = env.write(draft(extra=f"\nThe token is {secret}.\n"))
    assert not result.ok and any("secret scan" in p and "SKILL.md" in p for p in result.problems)


# =============================================================== (c) names


def _plugin(env: Env, key: str, skill_name: str) -> None:
    """An installed, enabled plugin carrying one skill."""
    root = env.tmp / "plugin-cache" / key.replace("@", "-")
    folder = root / "skills" / skill_name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {skill_name}\ndescription: a plugin skill\n---\n", encoding="utf-8"
    )
    (env.claude / "plugins").mkdir(parents=True, exist_ok=True)
    (env.claude / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {key: [{"scope": "user", "installPath": str(root)}]}}),
        encoding="utf-8",
    )
    (env.claude / "settings.json").write_text(
        json.dumps({"enabledPlugins": {key: True}}), encoding="utf-8"
    )


def _synced(env: Env, skill_name: str) -> None:
    base = env.claude / "skills" / "synced" / "acct_org"
    (base / skill_name).mkdir(parents=True)
    (base / skill_name / "SKILL.md").write_text(
        f"---\nname: {skill_name}\ndescription: a synced skill\n---\n", encoding="utf-8"
    )
    (base / "manifest.json").write_text(
        json.dumps({"lastUpdated": 1, "skills": [
            {"skillId": skill_name, "name": skill_name, "source": "anthropic"}
        ]}),
        encoding="utf-8",
    )


def _claude_skills(env: Env, plugin: str) -> None:
    folder = env.root / "plugins" / plugin / "skills" / NAME
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {NAME}\ndescription: an authored skill\n---\n", encoding="utf-8"
    )
    commit_all(env.root, "an authored skill")


@pytest.mark.parametrize(
    "where",
    ["personal", "claude-skills", "claude-skills-other-plugin", "plugin", "synced"],
)
def test_a_name_already_used_on_the_machine_refuses(env, where):
    if where == "personal":
        env.personal_skill(NAME)
    elif where == "claude-skills":
        _claude_skills(env, NAME)
    elif where == "claude-skills-other-plugin":
        _claude_skills(env, "someone-elses")
    elif where == "plugin":
        _plugin(env, "demo@market", NAME)
    else:
        _synced(env, NAME)
    before = env.snapshot()
    result = env.write()
    assert not result.ok and result.kind == "bad-line"
    assert "name-collision" in _rules(result.problems), result.problems
    assert env.snapshot() == before
    assert skill_writer.check(env.home, NAME, draft()).kind == "bad-line"


def test_a_vetoed_name_refuses(env):
    env.veto(NAME)
    before = env.snapshot()
    result = env.write()
    assert not result.ok and result.kind == "bad-line"
    assert "name-vetoed" in _rules(result.problems)
    assert env.snapshot() == before


# ======================================================= (d) a valid write


def test_a_valid_write_deploys_the_skill(env):
    base_ledger, base_root = env.count(env.home), env.count(env.root)
    result = env.write()
    assert result.ok, result.problems

    # one commit in each repo, both trees clean
    assert env.count(env.home) == base_ledger + 1
    assert env.count(env.root) == base_root + 1
    assert env.status(env.home) == "" and env.status(env.root) == ""
    files = git(env.root, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert sorted(files) == sorted([
        ".claude-plugin/marketplace.json",
        f"plugins/{NAME}/.claude-plugin/plugin.json",
        f"plugins/{NAME}/skills/{NAME}/SKILL.md",
        f"plugins/{NAME}/skills/{NAME}/{REF}",
    ])
    assert git(env.root, "log", "-1", "--format=%s").stdout.strip() == (
        f"self-learn: skill write {NAME} ({CASE})"
    )

    # plugin.json
    manifest = json.loads((env.plugin_dir() / ".claude-plugin" / "plugin.json").read_text())
    assert manifest == {"name": NAME, "version": "0.1.0", "description": DESCRIPTION}

    # the marketplace: one new entry, every other byte as it was
    new = env.marketplace.read_text(encoding="utf-8")
    old_data, new_data = json.loads(env.marketplace_seed), json.loads(new)
    assert new_data["plugins"][:-1] == old_data["plugins"]
    assert {k: v for k, v in new_data.items() if k != "plugins"} == {
        k: v for k, v in old_data.items() if k != "plugins"
    }
    assert new_data["plugins"][-1] == {
        "name": NAME, "source": f"./plugins/{NAME}", "description": DESCRIPTION, "version": "0.1.0",
    }
    last_old_entry_end = env.marketplace_seed.rindex("}\n  ]")
    assert new.startswith(env.marketplace_seed[: last_old_entry_end + 1])
    assert "\\u2014" in new and "—" not in new  # the file's own layout kept
    assert sum(1 for p in new_data["plugins"] if p["name"] == NAME) == 1

    # SKILL.md: the draft, stamped, with one managed section last
    text = env.skill_md().read_text(encoding="utf-8")
    front = _read_frontmatter(text).mapping
    row = env.row()
    assert front["metadata"]["self-learn"] == {
        "authored_by": "overseer", "case": CASE, "created": row["created"]["at"],
    }
    assert front["name"] == NAME and front["description"] == DESCRIPTION
    assert text.count(BEGIN_MARKER) == 1 and text.count(END_MARKER) == 1
    assert text.endswith(f"{BEGIN_MARKER}\n{END_MARKER}\n")
    assert "How the pieces fit together" in text
    assert (env.skill_dir() / REF).read_text(encoding="utf-8") == REF_TEXT

    # the link (D7)
    assert env.link().is_symlink()
    assert env.link().resolve() == env.skill_dir().resolve()

    # the registry row, with the hash of what is on disk
    on_disk = skill_registry.authored_sha256(text, {REF: REF_TEXT})
    assert row["status"] == "live" and row["plugin"] == f"plugins/{NAME}"
    assert row["created"]["case"] == CASE and row["created"]["by"] == "overseer"
    assert row["last_write"]["authored_sha256"] == on_disk == result.authored_sha256
    assert skill_writer.deployed_authored_sha256(env.home, NAME) == on_disk


def test_the_draft_s_own_managed_section_is_not_deployed(env):
    """Lessons come in by routing, never through the draft: the K1a control
    carries a lesson line inside its section, and it is dropped."""
    assert "- a lesson routed here" in k1a.skill()["SKILL.md"]  # control
    assert env.write(k1a.skill(), name=k1a.NAME).ok
    text = env.skill_md(k1a.NAME).read_text(encoding="utf-8")
    assert "- a lesson routed here" not in text
    assert text.endswith(f"{BEGIN_MARKER}\n{END_MARKER}\n")
    # an existing metadata mapping keeps its keys beside the stamp
    meta = _read_frontmatter(text).mapping["metadata"]
    assert meta["owner"] == "someone" and meta["self-learn"]["case"] == CASE


def test_both_commits_are_made_with_the_sentinel_and_both_locks_held(env, monkeypatch):
    seen: list[tuple[Path, bool, set[str]]] = []
    real_commit = gitops.commit

    def spy(repo, message, body=None, paths=None):
        seen.append((Path(repo).resolve(), sentinel.is_live(), set(gitops._held_locks)))
        return real_commit(repo, message, body=body, paths=paths)

    monkeypatch.setattr(gitops, "commit", spy)
    assert env.write().ok
    assert [repo for repo, _live, _held in seen] == [env.home.resolve(), env.root.resolve()]
    ledger_lock = str(gitops.commit_lock_path(env.home))
    host_lock = str(gitops.host_lock_path(env.root, "git"))
    for _repo, live, held in seen:
        assert live
        assert ledger_lock in held and host_lock in held
    assert not sentinel.is_live()  # released afterwards


# ===================================================== (e) compare-and-swap


def _hand_edit(env: Env, old: str, new: str) -> None:
    path = env.skill_md()
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
    git(env.root, "add", "-A")
    git(env.root, "commit", "-q", "-m", "a person's edit")


def test_a_stale_expect_refuses_target_busy(env):
    first = env.write()
    assert first.ok
    _hand_edit(env, "How the pieces fit together", "How the parts fit together")
    before = env.snapshot()

    stale = env.write(draft(extra="\nA new paragraph.\n"), case=CASE2, expect_sha=first.authored_sha256)

    assert not stale.ok and stale.kind == "target-busy"
    assert env.snapshot() == before
    assert "parts fit" in env.skill_md().read_text(encoding="utf-8")
    # control: the sha of the files as they are now lets the write through
    current = skill_writer.deployed_authored_sha256(env.home, NAME)
    assert current != first.authored_sha256
    fresh = env.write(draft(extra="\nA new paragraph.\n"), case=CASE2, expect_sha=current)
    assert fresh.ok, fresh.problems
    assert fresh.host_sha and "A new paragraph." in env.skill_md().read_text(encoding="utf-8")
    assert env.row()["last_write"]["case"] == CASE2
    assert env.row()["last_write"]["authored_sha256"] == fresh.authored_sha256


def test_an_update_without_expect_after_a_hand_edit_refuses(env):
    assert env.write().ok
    _hand_edit(env, "How the pieces fit together", "How the parts fit together")
    before = env.snapshot()
    result = env.write(draft(extra="\nMore.\n"), case=CASE2)
    assert not result.ok and result.kind == "target-busy"
    assert any("--expect" in p for p in result.problems)
    assert env.snapshot() == before


def test_resending_self_learn_s_last_version_does_not_undo_a_hand_edit(env):
    """The rerun allowance (a write the registry already records) must not
    let a resent copy of self-learn's last version overwrite a person's
    committed edit."""
    assert env.write().ok
    _hand_edit(env, "How the pieces fit together", "How the parts fit together")
    before = env.snapshot()
    result = env.write(case=CASE2)  # the very draft the row records
    assert not result.ok and result.kind == "target-busy"
    assert env.snapshot() == before
    assert "parts fit" in env.skill_md().read_text(encoding="utf-8")


def test_an_update_with_no_hand_edit_needs_no_expect(env):
    """Control for the test above: the files are as self-learn last wrote
    them, so an update goes through."""
    assert env.write().ok
    result = env.write(draft(extra="\nMore.\n"), case=CASE2)
    assert result.ok and result.updating and result.host_sha


def test_an_uncommitted_edit_in_the_skill_folder_refuses_target_busy(env):
    assert env.write().ok
    (env.skill_dir() / REF).write_text("# Buttons\n\nhalf-typed\n", encoding="utf-8")
    result = env.write(draft(extra="\nMore.\n"), case=CASE2)
    assert not result.ok and result.kind == "target-busy"
    assert (env.skill_dir() / REF).read_text(encoding="utf-8") == "# Buttons\n\nhalf-typed\n"


# =============================================== (f) idempotent by content


def test_a_second_identical_write_commits_nothing(env):
    assert env.write().ok
    ledger, root = env.head(env.home), env.head(env.root)
    again = env.write(case=CASE2)
    assert again.ok and not again.changed
    assert again.ledger_sha is None and again.host_sha is None and again.link == "unchanged"
    assert env.head(env.home) == ledger and env.head(env.root) == root
    assert env.row()["last_write"]["case"] == CASE  # the row was not touched


def test_routed_lessons_do_not_change_the_authored_hash_and_survive_a_rewrite(env):
    first = env.write()
    assert first.ok
    create_record(env.home, make_behavior(scope="skill:s", record_id=RID))
    verbs.route(env.home, RID, dest=f"new-skill:{NAME}", no_push=True)
    text = env.skill_md().read_text(encoding="utf-8")
    assert f"*({RID})*" in text  # control: the lesson compiled into our section
    assert skill_writer.deployed_authored_sha256(env.home, NAME) == first.authored_sha256
    assert skill_writer.routed_lessons(env.home, NAME) == [RID]

    rewrite = env.write(draft(extra="\nA second paragraph.\n"), case=CASE2)

    assert rewrite.ok, rewrite.problems
    text = env.skill_md().read_text(encoding="utf-8")
    assert "A second paragraph." in text
    assert f"*({RID})*" in text and text.count(BEGIN_MARKER) == 1
    assert text.rstrip().endswith(END_MARKER)


def test_draft_view_round_trips_to_a_no_op_write(env):
    files = draft(metadata={"owner": "someone"})
    assert env.write(files).ok
    view = skill_writer.draft_view(skill_writer.deployed_files(env.home, NAME))
    assert set(view) == {"SKILL.md", REF}
    assert "self-learn" not in view["SKILL.md"] and BEGIN_MARKER not in view["SKILL.md"]
    assert _read_frontmatter(view["SKILL.md"]).mapping == _read_frontmatter(files["SKILL.md"]).mapping
    ledger, root = env.head(env.home), env.head(env.root)
    again = env.write(view, case=CASE2)
    assert again.ok and not again.changed
    assert env.head(env.home) == ledger and env.head(env.root) == root


def test_draft_view_of_a_plain_draft_is_byte_identical(env):
    assert env.write().ok
    view = skill_writer.draft_view(skill_writer.deployed_files(env.home, NAME))
    assert view == draft()


def test_a_reference_dropped_from_the_draft_is_removed(env):
    files = draft()
    files["references/extra.md"] = "# Extra\n"
    files["SKILL.md"] += "Also [the extra notes](references/extra.md).\n"
    assert env.write(files).ok
    assert (env.skill_dir() / "references" / "extra.md").is_file()  # control
    result = env.write(draft(), case=CASE2)
    assert result.ok and result.host_sha
    assert not (env.skill_dir() / "references" / "extra.md").exists()
    assert env.status(env.root) == ""


# ===================================== what the compilers own (fix round 1)


def _route_reference(env: Env, rid: str = RID, dest: str = "reference") -> None:
    """A lesson filed in the skill's own bucket and routed as a reference:
    the compiler appends its entry to the shelf (or the ``--dest`` file)
    and adds a pointer block to SKILL.md, after the managed section."""
    create_record(env.home, make_behavior(scope=f"skill:{NAME}", record_id=rid))
    verbs.route(env.home, rid, dest=dest, no_push=True)


def _pointer_block(text: str) -> str:
    return text[text.index(POINTER_BEGIN_MARKER) : text.index(POINTER_END_MARKER) + len(POINTER_END_MARKER)]


def _append_and_commit(env: Env, line: str) -> None:
    path = env.skill_md()
    path.write_text(path.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8")
    commit_all(env.root, "a person's note at the end")


def test_a_reference_route_s_pointer_block_and_shelf_survive_a_rewrite(env):
    """Gate r1 MAJOR 1 (shape 1) and MINOR 2: the pointer block a reference
    route adds after the managed section is carried over byte for byte, the
    shelf is never written or removed, and a lesson on the shelf does not
    stop a write that changes an authored reference."""
    first = env.write()
    assert first.ok
    _route_reference(env)
    text = env.skill_md().read_text(encoding="utf-8")
    shelf = env.skill_dir() / "references" / "LEARNINGS.md"
    # control: the route put its block after the section and its entry on the shelf
    assert text.count(POINTER_BEGIN_MARKER) == 1
    assert text.index(END_MARKER) < text.index(POINTER_BEGIN_MARKER)
    assert RID in shelf.read_text(encoding="utf-8")
    block, shelf_text = _pointer_block(text), shelf.read_text(encoding="utf-8")
    # the route is the compilers' text, not a person's edit
    assert skill_writer.deployed_authored_sha256(env.home, NAME) == first.authored_sha256

    # draft_view leaves out what the compilers own, and writes back as a no-op
    view = skill_writer.draft_view(skill_writer.deployed_files(env.home, NAME))
    assert set(view) == {"SKILL.md", REF}
    assert "self-learn:pointers" not in view["SKILL.md"]
    assert skill_writer.check(env.home, NAME, view).ok
    ledger, root = env.head(env.home), env.head(env.root)
    again = env.write(view, case=CASE2, expect_sha=first.authored_sha256)
    assert again.ok and not again.changed, again.problems
    assert env.head(env.home) == ledger and env.head(env.root) == root

    # a real rewrite of SKILL.md and of the authored reference
    files = draft(extra="\nA second paragraph.\n", ref_text=REF_TEXT + "\nOne more row.\n")
    rewrite = env.write(files, case=CASE2)

    assert rewrite.ok, rewrite.problems
    text = env.skill_md().read_text(encoding="utf-8")
    assert "A second paragraph." in text
    assert text.count(POINTER_BEGIN_MARKER) == 1 and text.endswith(block + "\n")
    assert text.index(END_MARKER) < text.index(POINTER_BEGIN_MARKER)
    assert shelf.read_text(encoding="utf-8") == shelf_text
    assert "One more row." in (env.skill_dir() / REF).read_text(encoding="utf-8")
    assert skill_writer.routed_lessons(env.home, NAME) == [RID]
    assert env.status(env.root) == ""
    assert skill_writer.deployed_authored_sha256(env.home, NAME) == rewrite.authored_sha256


def test_a_person_s_text_after_the_section_is_handed_back_not_dropped(env):
    """Gate r1 MAJOR 1 (shape 2): text a person appended after the managed
    section comes back in draft_view, so a write with --expect keeps it."""
    first = env.write()
    assert first.ok
    note = "A person's note, added at the end of the file."
    _append_and_commit(env, note)
    current = skill_writer.deployed_authored_sha256(env.home, NAME)
    assert current != first.authored_sha256  # control: the hash sees the note

    view = skill_writer.draft_view(skill_writer.deployed_files(env.home, NAME))
    assert note in view["SKILL.md"] and BEGIN_MARKER not in view["SKILL.md"]
    view["SKILL.md"] += "\nA paragraph the overseer adds.\n"
    result = env.write(view, case=CASE2, expect_sha=current)

    assert result.ok, result.problems
    text = env.skill_md().read_text(encoding="utf-8")
    assert note in text and "A paragraph the overseer adds." in text
    assert text.index(note) < text.index(BEGIN_MARKER)
    assert text.rstrip().endswith(END_MARKER)


def test_text_after_the_pointer_block_is_handed_back_and_the_block_stays_last(env):
    assert env.write().ok
    _route_reference(env)
    note = "A note after the pointers."
    _append_and_commit(env, note)
    block = _pointer_block(env.skill_md().read_text(encoding="utf-8"))
    current = skill_writer.deployed_authored_sha256(env.home, NAME)

    view = skill_writer.draft_view(skill_writer.deployed_files(env.home, NAME))
    assert note in view["SKILL.md"] and "self-learn:pointers" not in view["SKILL.md"]
    result = env.write(view, case=CASE2, expect_sha=current)

    assert result.ok, result.problems
    text = env.skill_md().read_text(encoding="utf-8")
    assert text.index(note) < text.index(BEGIN_MARKER)
    assert text.endswith(block + "\n")


@pytest.mark.parametrize("what", ["reference-shelf", "pointer-block"])
def test_a_draft_carrying_what_the_compilers_own_is_refused(env, what):
    """Gate r1 MINOR 2: the shelf and the pointer block are the compilers';
    a draft carrying either is refused, with nothing written."""
    files = draft()
    if what == "reference-shelf":
        files["references/LEARNINGS.md"] = "# Learnings\n"
        files["SKILL.md"] += "See also [the learnings](references/LEARNINGS.md).\n"
    else:
        files["SKILL.md"] += (
            f"\n{POINTER_BEGIN_MARKER}\n- `references/buttons.md` — the map\n{POINTER_END_MARKER}\n"
        )
    before = env.snapshot()

    result = env.write(files)

    assert not result.ok and result.kind == "bad-line"
    assert what in _rules(result.problems), result.problems
    assert env.snapshot() == before
    assert skill_writer.check(env.home, NAME, files).kind == "bad-line"
    # control: the same draft without the compilers' part writes
    control = draft()
    if what == "reference-shelf":
        control["references/learning-notes.md"] = "# Learnings\n"
        control["SKILL.md"] += "See also [the notes](references/learning-notes.md).\n"
    assert env.write(control).ok


def test_a_lesson_filed_in_an_authored_reference_blocks_only_a_change_to_that_file(env):
    assert env.write().ok
    _route_reference(env, dest=f"reference:{Path(REF).name}")
    assert RID in (env.skill_dir() / REF).read_text(encoding="utf-8")  # control
    view = skill_writer.draft_view(skill_writer.deployed_files(env.home, NAME))
    assert RID in view[REF]

    view["SKILL.md"] += "\nAnother paragraph.\n"
    current = skill_writer.deployed_authored_sha256(env.home, NAME)
    only_skill_md = env.write(view, case=CASE2, expect_sha=current)
    assert only_skill_md.ok, only_skill_md.problems

    changed = dict(view)
    changed[REF] = REF_TEXT  # drops the lesson's entry
    current = skill_writer.deployed_authored_sha256(env.home, NAME)
    before = env.snapshot()
    refused = env.write(changed, case=CASE2, expect_sha=current)
    assert not refused.ok and refused.kind == "needs-person"
    assert any(RID in p for p in refused.problems), refused.problems
    assert env.snapshot() == before


def test_both_commits_carry_the_by_trailer(env):
    """Gate r1 MINOR 3: the registry commit is the overseer's by its
    trailer, like the skills-root commit (the weekly census of hand steps
    reads it)."""
    assert env.write().ok
    assert "By: overseer" in git(env.home, "log", "-1", "--format=%b").stdout
    assert "By: overseer" in git(env.root, "log", "-1", "--format=%b").stdout
    assert env.write(draft(extra="\nMore.\n"), case=CASE2, by="human").ok
    assert "By: human" in git(env.home, "log", "-1", "--format=%b").stdout


def test_a_deployed_file_the_hash_cannot_take_is_a_refusal_not_a_traceback(env):
    """Gate r1 NIT 6."""
    assert env.write().ok
    (env.skill_dir() / "odd\\name.md").write_text("# odd\n", encoding="utf-8")
    commit_all(env.root, "an oddly named file")
    files = draft(extra="\nMore.\n")

    result = env.write(files, case=CASE2)

    assert not result.ok and result.kind == "needs-person"
    assert any("cannot be taken" in p for p in result.problems), result.problems
    found = skill_writer.check(env.home, NAME, files)
    assert not found.ok and found.kind == "needs-person"


def test_an_update_notes_another_skill_with_the_same_name_and_skips_its_own(env):
    """Gate r1 NIT 7: on an update only the skill's own entries are left out
    of the name check. Its own plugin, installed from the marketplace, is
    not a clash; another plugin's skill of the same name is named in a
    note (an update is not refused for a name the skill already had)."""
    assert env.write().ok
    _plugin(env, f"{NAME}@sandbox-skills", NAME)  # the skill's own plugin, installed
    own = env.write(draft(extra="\nOne.\n"), case=CASE2)
    assert own.ok, own.problems
    assert not any("name-collision" in n for n in own.notes), own.notes

    _plugin(env, "demo@market", NAME)  # another plugin's skill of the same name
    other = env.write(draft(extra="\nTwo.\n"), case=CASE2)
    assert other.ok, other.problems
    assert any("name-collision" in n and f"demo:{NAME}" in n for n in other.notes), other.notes


# ================================================ (h) interrupted writes


class _Crash(BaseException):
    """A process dying mid-write: nothing in the writer catches it."""


@pytest.mark.parametrize("where", ["before-the-files", "before-the-skills-root-commit"])
def test_a_crash_between_the_ledger_and_host_commits_is_finished_by_a_rerun(
    env, monkeypatch, where
):
    ledger_before = env.count(env.home)
    real_deploy, real_commit = skill_writer._deploy, gitops.commit
    if where == "before-the-files":
        def crash(*_args, **_kwargs):
            raise _Crash()

        monkeypatch.setattr(skill_writer, "_deploy", crash)
    else:
        def crash_on_root(repo, message, body=None, paths=None):
            if Path(repo).resolve() == env.root.resolve():
                raise _Crash()
            return real_commit(repo, message, body=body, paths=paths)

        monkeypatch.setattr(gitops, "commit", crash_on_root)

    with pytest.raises(_Crash):
        env.write()

    # the intent (the registry row) is committed; the skill is not linked
    assert env.count(env.home) == ledger_before + 1
    assert env.row()["status"] == "live"
    assert not env.link().is_symlink() and not env.link().exists()
    if where == "before-the-files":
        assert not env.plugin_dir().exists()
    else:
        assert env.skill_md().is_file() and env.status(env.root) != ""  # written, not committed
    root_head = env.head(env.root)
    monkeypatch.setattr(skill_writer, "_deploy", real_deploy)
    monkeypatch.setattr(gitops, "commit", real_commit)

    rerun = env.write()

    assert rerun.ok, rerun.problems
    assert rerun.ledger_sha is None  # the row already said so
    assert env.count(env.home) == ledger_before + 1
    assert env.head(env.root) != root_head and env.status(env.root) == ""
    assert env.link().resolve() == env.skill_dir().resolve()
    assert env.row()["last_write"]["authored_sha256"] == skill_writer.deployed_authored_sha256(
        env.home, NAME
    )


def test_a_failed_skills_root_commit_is_undone_on_both_sides(env, monkeypatch):
    real_commit = gitops.commit

    def refuse_on_root(repo, message, body=None, paths=None):
        if Path(repo).resolve() == env.root.resolve():
            raise gitops.GitOpsError("simulated: a pre-commit hook said no")
        return real_commit(repo, message, body=body, paths=paths)

    monkeypatch.setattr(gitops, "commit", refuse_on_root)
    root_head = env.head(env.root)
    result = env.write()
    assert not result.ok and result.kind == "git"
    assert env.head(env.root) == root_head and env.status(env.root) == ""
    assert not env.plugin_dir().exists()
    assert env.marketplace.read_text(encoding="utf-8") == env.marketplace_seed
    assert env.row() is None  # the row was put back
    # the undo commit is the overseer's too, by its trailer
    assert "undone" in git(env.home, "log", "-1", "--format=%s").stdout
    assert "By: overseer" in git(env.home, "log", "-1", "--format=%b").stdout
    assert not env.link().exists() and not env.link().is_symlink()


# ================================================================ links


def test_link_skill_refuses_a_missing_folder(env):
    with pytest.raises(skill_writer.SkillLinkError, match="missing folder"):
        skill_writer.link_skill(env.root, "nowhere")
    assert not env.link("nowhere").is_symlink()


def test_link_skill_never_replaces_a_real_folder(env):
    assert env.write().ok
    env.link().unlink()
    env.link().mkdir()
    with pytest.raises(skill_writer.SkillLinkError, match="real file or folder"):
        skill_writer.link_skill(env.root, NAME)
    assert env.link().is_dir() and not env.link().is_symlink()


def test_link_skill_replaces_a_dangling_link(env):
    assert env.write().ok
    env.link().unlink()
    env.link().symlink_to(env.tmp / "gone")
    assert skill_writer.link_skill(env.root, NAME) == "replaced"
    assert env.link().resolve() == env.skill_dir().resolve()


# ================================================================== CLI


def _draft_folder(env: Env, files: dict[str, str]) -> Path:
    folder = env.tmp / "draft"
    for key, text in files.items():
        (folder / key).parent.mkdir(parents=True, exist_ok=True)
        (folder / key).write_text(text, encoding="utf-8")
    return folder


def test_cli_write_creates_the_skill_as_the_person(env, capsys):
    folder = _draft_folder(env, draft())
    code = cli.main(["skill", "write", NAME, "--from", str(folder), "--case", CASE, "--no-push"])
    assert code == 0, capsys.readouterr().err
    assert env.row()["created"]["by"] == "human"
    assert env.link().resolve() == env.skill_dir().resolve()
    assert "created" in capsys.readouterr().out


@pytest.mark.parametrize("marker", ["CLAUDECODE", "CODEX_THREAD_ID"])
@pytest.mark.parametrize("argv_tail", [["write", NAME, "--from", "{draft}", "--case", CASE2],
                                       ["retire", NAME, "--case", CASE2]])
def test_cli_refuses_a_change_from_an_agent_shell(env, monkeypatch, capsys, marker, argv_tail):
    """The skill exists and the draft differs from it, so without the
    refusal each command would change both repos (the person's own run of
    the same commands is the control: ``test_cli_write_creates_the_skill_as_the_person``
    here and ``test_cli_retire_as_the_person`` in test_skill_retire.py)."""
    assert env.write().ok
    folder = _draft_folder(env, draft(extra="\nA paragraph the write would add.\n"))
    argv = ["skill", *[str(folder) if a == "{draft}" else a for a in argv_tail]]
    before = env.snapshot()
    monkeypatch.setenv(marker, "")

    def no_lock(*_a, **_k):
        pytest.fail("the agent-shell refusal must come before any lock")

    monkeypatch.setattr(intents, "ledger_write", no_lock)
    capsys.readouterr()
    assert cli.main([*argv, "--no-push"]) == 1
    err = capsys.readouterr().err
    assert "person's command" in err and marker in err
    assert env.snapshot() == before


def test_cli_by_takes_only_human():
    """Gate r1 NIT 4: a person's run cannot be recorded as the overseer's."""
    parser = cli._build_parser()
    base = ["skill", "write", NAME, "--from", "draft", "--case", CASE]
    assert parser.parse_args([*base, "--by", "human"]).by == "human"  # control
    with pytest.raises(SystemExit):
        parser.parse_args([*base, "--by", "overseer"])
    with pytest.raises(SystemExit):
        parser.parse_args(["skill", "retire", NAME, "--case", CASE, "--by", "overseer"])


def test_cli_check_runs_from_an_agent_shell_and_writes_nothing(env, monkeypatch, capsys):
    folder = _draft_folder(env, draft())
    monkeypatch.setenv("CLAUDECODE", "1")
    before = env.snapshot()
    assert cli.main(["skill", "write", NAME, "--from", str(folder), "--case", CASE, "--check"]) == 0
    assert "would create" in capsys.readouterr().out
    assert env.snapshot() == before


def test_cli_list_reports_the_skill_and_a_hand_edit(env, capsys):
    assert env.write().ok
    capsys.readouterr()
    assert cli.main(["skill", "list", "--json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    (state,) = listing["skills"]
    assert state["name"] == NAME and state["link"] == "ok"
    assert state["files"] == "as self-learn last wrote them"
    _hand_edit(env, "How the pieces fit together", "How the parts fit together")
    assert cli.main(["skill", "list", "--json"]) == 0
    (state,) = json.loads(capsys.readouterr().out)["skills"]
    assert state["files"] == "changed since self-learn last wrote them"


def test_now_is_a_timestamp_the_registry_accepts():
    """The writer stamps rows with chrono.now_iso(); the registry must read
    that shape back (a guard on the seam between the two modules)."""
    from self_learn.primitives import chrono

    stamp = chrono.now_iso(datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc))
    registry = skill_registry.Registry()
    skill_writer._registry_after_write(
        registry, name=NAME, sha="0" * 64, case=CASE, by="overseer", now=stamp
    )
    assert registry.validated().row(NAME)["created"]["at"] == stamp
