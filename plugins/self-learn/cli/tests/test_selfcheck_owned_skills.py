"""SK9 (S-NEXT-sk9-selftest): the `owned_skills` row of `self-learn --selftest`.

The skill-writing plan (§4.1, unit SK9): every LIVE row of the ledger's
owned-skills registry (``owned-skills.yaml``, `skill_registry`) must have its
skill folder in the skills root, an entry in the skills root's
``marketplace.json``, the ``metadata.self-learn`` stamp in its SKILL.md and a
``<claude dir>/skills/<name>`` link that resolves to the folder; a stamped
skill with no row at all is named; a RETIRED row expects nothing on disk.

Every fixture points the ledger, the skills root and the claude dir at
scratch directories under ``tmp_path``. Each failing case first asserts the
same healthy fixture PASSes (the positive control), so a row that never looks
cannot pass an absence assertion by looking at nothing. The registry file is
written directly (``skill_registry.render``), not through ``with_update``:
this row only reads it.

Mutation checks a gate can run (each should turn the named test red):

- make `_check_owned_skills` skip the link check: the ``link`` tests;
- make `_owned_skill_problems` read a retired row too (drop the `registry.live()`
  filter): the retired-row tests;
- make the stray scan treat a name in `registry.skills` as unknown (drop the
  `continue`): `test_a_stamped_skill_on_a_retired_row_is_not_a_stray`;
- make the stray scan skip the stamp test (flag every unlisted skill that
  merely mentions the key): `test_a_name_that_only_mentions_the_stamp_key_is_not_a_stray`;
  make it skip the key prefilter and the stamp test both (flag every
  unlisted skill): the hand-made-skill control in
  `test_the_healthy_fixture_passes`;
- return `Verdict.PASS` from the `SkillRegistryError` handler:
  `test_an_unreadable_registry_fails`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from self_learn import cli, selfcheck, skill_registry
from self_learn.selfcheck import Verdict
from self_learn.skill_scaffold import marketplace_with_entry

from support import init_repo, make_env

ROW = "owned_skills"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel probes go to a per-test XDG cache, never the real ~/.cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


@pytest.fixture
def claude_dir(tmp_path, monkeypatch):
    """A scratch claude dir with its ``skills/`` folder, and the env
    variable the selftest reads it from, so `--selftest` and the direct
    calls below look at the same place."""
    directory = tmp_path / "claude"
    (directory / "skills").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(directory))
    return directory


# ------------------------------------------------------------------ fixtures


def _row(name: str, *, status: str = "live", plugin: str | None = None) -> dict:
    stamp = {"at": "2026-10-31T01:00:00Z", "case": "case-0a1b2c3d", "by": "overseer"}
    row = {
        "status": status,
        "plugin": plugin or f"plugins/{name}",
        "created": dict(stamp),
        "last_write": {**stamp, "authored_sha256": "a" * 64},
    }
    if status == "retired":
        row["retired"] = dict(stamp)
    return row


def _write_registry(env, rows: dict[str, dict]) -> None:
    registry = skill_registry.Registry(dict(rows), [])
    skill_registry.registry_path(env.ledger).write_text(
        skill_registry.render(registry), encoding="utf-8"
    )


STAMPED = """\
---
name: {name}
description: "Use when exercising the {name} skill."
metadata:
  self-learn:
    authored_by: overseer
    case: case-0a1b2c3d
    created: "2026-10-31"
---

# {name}

Authored prose.
"""

UNSTAMPED = """\
---
name: {name}
description: "Use when exercising the {name} skill."
---

# {name}

Authored prose.
"""


def _marketplace_path(env) -> Path:
    return env.host / ".claude-plugin" / "marketplace.json"


def _add_marketplace_entry(env, plugin_name: str) -> None:
    path = _marketplace_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.read_text(encoding="utf-8") if path.is_file() else '{"name": "m", "plugins": []}'
    text, _ = marketplace_with_entry(raw, plugin_name, f"The {plugin_name} plugin.")
    path.write_text(text, encoding="utf-8")


def _skill_folder(env, name: str, plugin_name: str | None = None) -> Path:
    return env.host / "plugins" / (plugin_name or name) / "skills" / name


def _deploy(
    env,
    claude_dir: Path,
    name: str,
    *,
    plugin_name: str | None = None,
    stamped: bool = True,
    entry: bool = True,
    link: bool = True,
) -> Path:
    """One skill as `skill write` leaves it: the folder with its SKILL.md,
    the marketplace entry, the link. Returns the skill folder."""
    folder = _skill_folder(env, name, plugin_name)
    folder.mkdir(parents=True, exist_ok=True)
    template = STAMPED if stamped else UNSTAMPED
    (folder / "SKILL.md").write_text(template.format(name=name), encoding="utf-8")
    if entry:
        _add_marketplace_entry(env, plugin_name or name)
    if link:
        (claude_dir / "skills" / name).symlink_to(folder, target_is_directory=True)
    return folder


def _healthy(env, claude_dir: Path) -> None:
    """Two live owned skills, one retired row with nothing on disk, and one
    hand-made skill (no stamp, no row) that is none of self-learn's
    business."""
    _write_registry(
        env,
        {
            "alpha": _row("alpha"),
            "beta": _row("beta"),
            "gamma": _row("gamma", status="retired"),
        },
    )
    _deploy(env, claude_dir, "alpha")
    _deploy(env, claude_dir, "beta")
    _deploy(env, claude_dir, "hand-made", stamped=False, entry=False, link=False)


def _check(env, claude_dir: Path) -> tuple[Verdict, str]:
    return selfcheck._check_owned_skills(env.ledger, claude_dir)


def _assert_healthy(env, claude_dir: Path) -> None:
    """The positive control: the fixture as built is a PASS."""
    verdict, message = _check(env, claude_dir)
    assert verdict is Verdict.PASS, message


def _tree_digest(*roots: Path) -> str:
    """One hash over every file name and content under *roots* (git
    internals left out), and over every link's target."""
    digest = hashlib.sha256()
    for root in roots:
        for path in sorted(root.rglob("*")):
            if ".git" in path.parts:
                continue
            digest.update(str(path).encode())
            if path.is_symlink():
                digest.update(os.readlink(path).encode())
            elif path.is_file():
                digest.update(path.read_bytes())
    return digest.hexdigest()


# ------------------------------------------------------------------- healthy


def test_the_healthy_fixture_passes(env, claude_dir):
    """The control for every failing case below: two live skills intact, one
    retired row with nothing on disk (it expects nothing), and a hand-made
    skill with no stamp and no row, which is not named."""
    _healthy(env, claude_dir)

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.PASS, message
    assert "2 live owned skill(s) intact" in message
    assert "1 retired" in message
    assert "hand-made" not in message
    # the fixture really is a registry with live rows over real folders: the
    # PASS above is not "nothing to look at"
    assert skill_registry.load(env.ledger).live() == ["alpha", "beta"]
    assert (_skill_folder(env, "alpha") / "SKILL.md").is_file()
    assert (claude_dir / "skills" / "alpha").resolve() == _skill_folder(env, "alpha").resolve()


def test_no_registry_is_a_pass_with_nothing_owed(env, claude_dir):
    assert not skill_registry.registry_path(env.ledger).exists()

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.PASS, message
    assert message == "no owned skills"


def test_a_skill_row_naming_another_skills_plugin_folder_fails(env, claude_dir):
    """A row's `plugin` is always `plugins/<its own name>` (02-schema.md §3;
    `skill rename` moves the folder, the entry and the link with the name,
    and retire and rename delete and move the folder a row names). So a row
    naming another skill's folder is a registry the selftest cannot read, and
    the row FAILs naming why, rather than checking the other skill's files.
    (This test first asserted the opposite: that such a row passes.)"""
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    rows = {"alpha": _row("alpha"), "beta": _row("beta", plugin="plugins/alpha")}
    # Written raw: `skill_registry.render` refuses the row itself.
    skill_registry.registry_path(env.ledger).write_text(
        json.dumps({"version": 1, "skills": rows, "vetoed": []}), encoding="utf-8"
    )

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "owned-skills.yaml unreadable" in message
    assert "skills.beta.plugin: 'plugins/alpha' must be plugins/beta" in message


# ------------------------------------------------------------------ the link


def test_a_missing_link_fails_the_row_and_names_it(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    (claude_dir / "skills" / "alpha").unlink()

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "1 of 2 live owned skill(s) broken" in message
    assert f"alpha: link {claude_dir / 'skills' / 'alpha'} is missing" in message
    assert "beta" not in message


def test_a_dangling_link_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    link = claude_dir / "skills" / "beta"
    link.unlink()
    link.symlink_to(env.host / "plugins" / "nowhere", target_is_directory=True)

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "beta: link" in message and "is dangling" in message
    assert "alpha" not in message


def test_a_link_to_another_folder_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    link = claude_dir / "skills" / "alpha"
    link.unlink()
    link.symlink_to(_skill_folder(env, "beta"), target_is_directory=True)

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "alpha: link" in message and "not " + str(_skill_folder(env, "alpha")) in message


def test_a_real_folder_where_the_link_belongs_fails(env, claude_dir):
    """A real directory at ``~/.claude/skills/<name>`` shadows the skill with
    a copy that no self-learn write reaches."""
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    link = claude_dir / "skills" / "alpha"
    link.unlink()
    link.mkdir()

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert f"{link} is not a link to" in message


def test_no_claude_dir_at_all_fails_with_live_rows(env, tmp_path):
    """A live skill with no link anywhere is a missing link, not an
    unmeasurable one: the filesystem was looked at and the link is not
    there."""
    _write_registry(env, {"alpha": _row("alpha")})
    folder = _deploy(env, tmp_path / "unused", "alpha", link=False)
    assert folder.is_dir()
    absent = tmp_path / "no-such-claude-dir"

    verdict, message = _check(env, absent)

    assert verdict is Verdict.FAIL
    assert "alpha: link" in message and "is missing" in message


# -------------------------------------------------------- folder, stamp, entry


def test_a_missing_skill_folder_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    (_skill_folder(env, "beta") / "SKILL.md").unlink()
    (_skill_folder(env, "beta")).rmdir()

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert f"beta: skill folder {_skill_folder(env, 'beta')} is missing" in message
    assert "alpha" not in message


def test_a_folder_without_skill_md_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    (_skill_folder(env, "beta") / "SKILL.md").unlink()

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "beta: SKILL.md is missing from" in message


def test_a_missing_stamp_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    (_skill_folder(env, "alpha") / "SKILL.md").write_text(
        UNSTAMPED.format(name="alpha"), encoding="utf-8"
    )

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "alpha: no metadata.self-learn stamp in" in message
    assert "beta" not in message


def test_a_skill_md_with_no_frontmatter_fails_naming_why(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    (_skill_folder(env, "alpha") / "SKILL.md").write_text("# alpha\n\nno frontmatter\n", encoding="utf-8")

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "alpha: SKILL.md has no readable frontmatter, so its stamp cannot be checked" in message


def test_a_skill_md_that_is_not_text_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    (_skill_folder(env, "alpha") / "SKILL.md").write_bytes(b"---\nname: alpha\n\xff\xfe\n---\n")

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "alpha: SKILL.md cannot be read (UnicodeDecodeError)" in message


def _rewrite_marketplace(env, entries: list[dict]) -> None:
    _marketplace_path(env).write_text(
        json.dumps({"name": "m", "plugins": entries}, indent=2) + "\n", encoding="utf-8"
    )


def test_a_missing_marketplace_entry_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    _rewrite_marketplace(
        env, [{"name": "alpha", "source": "./plugins/alpha", "description": "d", "version": "0.1.0"}]
    )

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "beta: no marketplace entry named beta" in message
    assert "alpha" not in message


def test_a_duplicated_marketplace_entry_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    entry = {"name": "alpha", "source": "./plugins/alpha", "description": "d", "version": "0.1.0"}
    beta = {"name": "beta", "source": "./plugins/beta", "description": "d", "version": "0.1.0"}
    _rewrite_marketplace(env, [entry, entry, beta])

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "alpha: 2 marketplace entries named alpha" in message


def test_a_marketplace_entry_pointing_elsewhere_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    _rewrite_marketplace(
        env,
        [
            {"name": "alpha", "source": "./plugins/elsewhere", "description": "d", "version": "0.1.0"},
            {"name": "beta", "source": "./plugins/beta", "description": "d", "version": "0.1.0"},
        ],
    )

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "alpha: marketplace entry alpha has source './plugins/elsewhere', not ./plugins/alpha" in message


def test_a_missing_marketplace_file_fails_once(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    _marketplace_path(env).unlink()

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert message.count("marketplace.json is missing") == 1
    # the file is the problem, so neither skill is also named for "no entry"
    assert "no marketplace entry" not in message


def test_an_unparseable_marketplace_file_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    _marketplace_path(env).write_text("{not json", encoding="utf-8")

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "marketplace.json cannot be read as JSON" in message


# ------------------------------------------------------------------ retired


def test_a_retired_row_expects_nothing_on_disk(env, claude_dir):
    """Nothing of a retired skill is on disk (no folder, no entry, no link),
    and the row still PASSes; the live skill beside it is checked as usual."""
    _write_registry(env, {"alpha": _row("alpha"), "gamma": _row("gamma", status="retired")})
    _deploy(env, claude_dir, "alpha")
    assert not _skill_folder(env, "gamma").exists()
    assert not (claude_dir / "skills" / "gamma").is_symlink()

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.PASS, message
    assert "1 live owned skill(s) intact" in message
    assert "1 retired" in message


def test_only_retired_rows_pass_as_no_owned_skills(env, claude_dir):
    _write_registry(env, {"gamma": _row("gamma", status="retired")})

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.PASS, message
    assert message.startswith("no owned skills")
    assert "1 retired" in message


def test_a_retired_row_is_not_checked_even_when_leftovers_are_broken(env, claude_dir):
    """The plan reads a retired row as expecting nothing: a leftover
    dangling link is not this row's concern (the live skills are)."""
    _healthy(env, claude_dir)
    (claude_dir / "skills" / "gamma").symlink_to(env.host / "plugins" / "gone", target_is_directory=True)

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.PASS, message
    assert "gamma" not in message


# -------------------------------------------------------------------- strays


def test_a_stamped_skill_with_no_row_is_named(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    _deploy(env, claude_dir, "orphan", entry=False, link=False)

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "stamped by self-learn (metadata.self-learn) but with no row in owned-skills.yaml: orphan" in message
    # the live skills are fine and are not named
    assert "alpha" not in message and "beta" not in message


def test_a_stamped_skill_is_named_when_there_are_no_live_rows_at_all(env, claude_dir):
    """The stray scan does not depend on the registry having rows: a home
    whose registry file was lost still names the skills that say they are
    self-learn's."""
    assert not skill_registry.registry_path(env.ledger).exists()
    _assert_healthy(env, claude_dir)
    _deploy(env, claude_dir, "orphan", entry=False, link=False)

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "with no row in owned-skills.yaml: orphan" in message


def test_every_stray_is_named(env, claude_dir):
    _deploy(env, claude_dir, "orphan-a", entry=False, link=False)
    _deploy(env, claude_dir, "orphan-b", entry=False, link=False)

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "orphan-a, orphan-b" in message


def test_a_stamped_skill_on_a_retired_row_is_not_a_stray(env, claude_dir):
    """A name with a row of any status is known to the registry: a retired
    skill's leftover folder is not "a stamped skill with no row"."""
    _write_registry(env, {"gamma": _row("gamma", status="retired")})
    _deploy(env, claude_dir, "gamma", entry=False, link=False)

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.PASS, message


def test_a_name_that_only_mentions_the_stamp_key_is_not_a_stray(env, claude_dir):
    """The key as plain text (a managed-section lesson about self-learn, a
    `metadata:` block with other keys) is not the stamp."""
    folder = _skill_folder(env, "talks-about-it")
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: talks-about-it\ndescription: \"Use when.\"\nmetadata:\n  other: 1\n---\n\n"
        "A lesson says self-learn writes metadata.self-learn into skills.\n",
        encoding="utf-8",
    )
    _assert_healthy(env, claude_dir)
    assert "self-learn" in (folder / "SKILL.md").read_text(encoding="utf-8")

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.PASS, message


# ------------------------------------------------- registry and hosts problems


def test_an_unreadable_registry_fails(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    skill_registry.registry_path(env.ledger).write_text(
        "version: 1\nskills:\n  alpha:\n    status: sleeping\n", encoding="utf-8"
    )

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "owned-skills.yaml unreadable" in message
    assert "alpha" in message  # the registry's own refusal names the skill


def test_live_rows_with_no_skills_root_fail(env, claude_dir):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    (env.ledger / "hosts.yaml").write_text(f"projects:\n  - path: {env.host}\n", encoding="utf-8")

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert "2 live owned skill(s) (alpha, beta) but the skills root cannot be found" in message
    assert "no skills root is registered" in message


def test_no_skills_root_and_no_rows_passes(env, claude_dir):
    (env.ledger / "hosts.yaml").write_text(f"projects:\n  - path: {env.host}\n", encoding="utf-8")

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.PASS, message
    assert "no owned skills" in message


def test_a_skills_root_that_is_not_a_directory_fails_with_live_rows(env, claude_dir, tmp_path):
    _healthy(env, claude_dir)
    _assert_healthy(env, claude_dir)
    gone = tmp_path / "gone-skills-root"
    (env.ledger / "hosts.yaml").write_text(f"skills_root: {gone}\nprojects: []\n", encoding="utf-8")

    verdict, message = _check(env, claude_dir)

    assert verdict is Verdict.FAIL
    assert f"the skills root {gone} is not a directory" in message


def test_hosts_yaml_absent_with_no_rows_is_unmeasured_and_with_rows_a_fail(tmp_path, monkeypatch):
    """A bare ledger has no skills root to look in. With nothing owned that
    is unmeasured, like the drift row; with live rows it is a failure (a
    registry that says a skill exists, and nowhere to find it)."""
    bare = tmp_path / "bare-ledger"
    init_repo(bare)
    monkeypatch.setenv("SELF_LEARN_HOME", str(bare))
    claude = tmp_path / "claude"
    (claude / "skills").mkdir(parents=True)

    verdict, message = selfcheck._check_owned_skills(bare, claude)
    assert verdict is Verdict.UNMEASURED
    assert "hosts.yaml absent" in message

    skill_registry.registry_path(bare).write_text(
        skill_registry.render(skill_registry.Registry({"alpha": _row("alpha")}, [])), encoding="utf-8"
    )
    verdict, message = selfcheck._check_owned_skills(bare, claude)
    assert verdict is Verdict.FAIL
    assert "hosts.yaml absent" in message


def test_a_missing_home_fails_loud(tmp_path):
    verdict, message = selfcheck._check_owned_skills(tmp_path / "no-such-home", tmp_path)

    assert verdict is Verdict.FAIL
    assert "does not exist" in message


# ----------------------------------------------------------- through --selftest


def test_selftest_prints_the_row_and_exits_1_on_a_missing_link(env, claude_dir, capsys):
    _healthy(env, claude_dir)
    assert cli.main(["--selftest"]) != 1  # no row fails on the healthy fixture
    healthy_out = capsys.readouterr().out
    assert "selftest: PASS owned_skills — 2 live owned skill(s) intact" in healthy_out
    assert "FAIL" not in healthy_out

    (claude_dir / "skills" / "alpha").unlink()

    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "selftest: FAIL owned_skills — 1 of 2 live owned skill(s) broken" in out
    assert "alpha: link" in out
    # the row sits right after `hosts`, which it depends on, and before `sentinel`
    names = [line.split()[2] for line in out.splitlines() if line.startswith("selftest: ") and " — " in line]
    assert names.index("owned_skills") == names.index("hosts") + 1


def test_the_row_writes_nothing(env, claude_dir):
    """Read-only: the ledger, the skills root and the claude dir are
    byte-for-byte the same after the row has looked, broken fixture or not."""
    _healthy(env, claude_dir)
    (claude_dir / "skills" / "alpha").unlink()
    _deploy(env, claude_dir, "orphan", entry=False, link=False)
    before = _tree_digest(env.ledger, env.host, claude_dir)
    assert before == _tree_digest(env.ledger, env.host, claude_dir)  # the digest is stable

    verdict, _ = _check(env, claude_dir)

    assert verdict is Verdict.FAIL  # it really looked
    assert _tree_digest(env.ledger, env.host, claude_dir) == before
