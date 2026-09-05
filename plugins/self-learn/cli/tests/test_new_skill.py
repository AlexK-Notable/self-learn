"""T18 — `route <id> --dest new-skill:<name>` (08 §8.1 New-skill-compiler
pin): deterministic CLI-owned scaffold, marketplace append (idempotent,
exactly once), foreign-plugin collision refusal, recompile/drift coverage.

Tests assert ONLY the structural facts install.sh actually consumes
(marketplace .plugins[].name + the plugins/<n>/skills/<n>/SKILL.md glob)
plus JSON parseability — per the pin, no invented manifest validation.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from self_learn import verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.ledger_ops import create_record
from support import git, make_behavior, make_env, proposal_dict

RID = "lrn-0000aaaa"
RID2 = "lrn-0000bbbb"

MARKETPLACE_SEED = {
    "name": "sandbox-skills",
    "plugins": [
        {
            "name": "s-plugin",
            "source": "./plugins/s-plugin",
            "description": "seeded plugin",
            "version": "1.0.0",
        }
    ],
}


class Env:
    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.bucket = self.home / "skills" / "s"
        self.marketplace = self.host / ".claude-plugin" / "marketplace.json"
        self.marketplace.parent.mkdir()
        self.marketplace.write_text(
            json.dumps(MARKETPLACE_SEED, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        git(self.host, "add", "-A")
        git(self.host, "commit", "-q", "-m", "marketplace seed")
        self.bare = tmp_path / "ledger-remote.git"
        self.host_bare = tmp_path / "host-remote.git"
        for repo, bare in ((self.home, self.bare), (self.host, self.host_bare)):
            subprocess.run(
                ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
            )
            git(repo, "remote", "add", "origin", str(bare))
            git(repo, "push", "-q", "-u", "origin", "main")

    def host_subject(self):
        return git(self.host, "log", "-1", "--format=%s").stdout.strip()

    def marketplace_names(self):
        data = json.loads(self.marketplace.read_text(encoding="utf-8"))
        return [p["name"] for p in data["plugins"]]

    def pending(self, rid=RID):
        return self.bucket / "pending" / f"{rid}.md"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


TRIGGER = "About to flash the SM809Pro mouse firmware."


def seed(env, rid=RID, trigger=TRIGGER):
    record = make_behavior(scope="skill:s", record_id=rid, trigger=trigger)
    create_record(env.home, record)
    return record


class TestScaffold:
    def test_route_scaffolds_plugin_skill_and_marketplace(self, env):
        seed(env)
        result = verbs.route(env.home, RID, dest="new-skill:mouse-firmware")

        assert result.commit_message == f"self-learn: route {RID} → new-skill:mouse-firmware"

        # plugin.json: parses, carries the shared key set (the pin's
        # {name, version, description} — the keys the repo's real
        # manifests share)
        manifest = env.host / "plugins" / "mouse-firmware" / ".claude-plugin" / "plugin.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["name"] == "mouse-firmware"
        assert data["version"] == "0.1.0"
        assert data["description"]

        # SKILL.md: well-formed frontmatter + managed section holding the
        # routed lesson
        skill_md = env.host / "plugins" / "mouse-firmware" / "skills" / "mouse-firmware" / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "name: mouse-firmware" in text.split("---")[1]
        assert BEGIN_MARKER in text and END_MARKER in text
        assert f"*({RID})*" in text

        # marketplace: entry exactly once, file still parses, seeded
        # entries untouched
        assert env.marketplace_names() == ["s-plugin", "mouse-firmware"]

        # one host commit, pinned apply subject; pushed
        rel = "plugins/mouse-firmware/skills/mouse-firmware/SKILL.md"
        assert env.host_subject() == f"self-learn: apply {RID} → {rel} (new-skill)"
        assert result.host_push is not None and result.host_push.ok

        # routing records the name — recompile/drift read it back
        from self_learn.records import Record

        routed = Record.from_path(env.bucket / "resolved" / f"{RID}.md")
        assert routed.routing["new_skill"] == "mouse-firmware"
        # install.sh prints "run ./install.sh" guidance (M3-11)
        assert any("install.sh" in n for n in result.post_notes)

    def test_second_route_appends_lesson_without_duplicating_entry(self, env):
        seed(env)
        verbs.route(env.home, RID, dest="new-skill:mouse-firmware")
        seed(env, rid=RID2, trigger="About to unpair the mouse dongle.")
        verbs.route(env.home, RID2, dest="new-skill:mouse-firmware")

        skill_md = env.host / "plugins" / "mouse-firmware" / "skills" / "mouse-firmware" / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        assert f"*({RID})*" in text and f"*({RID2})*" in text
        assert env.marketplace_names().count("mouse-firmware") == 1

    def test_foreign_plugin_collision_refused(self, env):
        # plugins/s-plugin exists and was NOT self-learn-scaffolded (no
        # managed section) — never inject into a foreign authored plugin
        # (M3-9).
        seed(env)
        with pytest.raises(verbs.VerbError, match="foreign"):
            verbs.route(env.home, RID, dest="new-skill:s-plugin")
        assert env.pending().is_file()

    def test_bare_new_skill_needs_a_name(self, env):
        # the name slot is the confirmed §4 human call.
        seed(env)
        with pytest.raises(verbs.VerbError, match="name"):
            verbs.route(env.home, RID, dest="new-skill")
        assert env.pending().is_file()

    def test_bad_name_refused(self, env):
        seed(env)
        with pytest.raises(verbs.VerbError, match="name"):
            verbs.route(env.home, RID, dest="new-skill:Bad_Name!")
        assert env.pending().is_file()

    def test_missing_marketplace_refused_before_any_commit(self, env):
        seed(env)
        env.marketplace.unlink()
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "drop marketplace")
        before = git(env.home, "log", "-1", "--format=%s").stdout.strip()
        with pytest.raises(verbs.VerbError, match="marketplace"):
            verbs.route(env.home, RID, dest="new-skill:mouse-firmware")
        assert env.pending().is_file()
        assert git(env.home, "log", "-1", "--format=%s").stdout.strip() == before

    def test_proposal_new_skill_without_name_names_the_human_call(self, env):
        # a worker proposal may say destination: new-skill, but only the
        # human names the skill — route without --dest must say so.
        record = seed(env)
        from self_learn.ledger_ops import stamp_proposal, write_proposal

        write_proposal(env.home, RID, proposal_dict(destination="new-skill"))
        stamp_proposal(env.home, RID)
        with pytest.raises(verbs.VerbError, match="new-skill:<name>"):
            verbs.route(env.home, RID)
        assert env.pending().is_file()


class TestLifecycle:
    def test_supersede_drops_entry_from_scaffolded_skill(self, env):
        seed(env)
        verbs.route(env.home, RID, dest="new-skill:mouse-firmware")
        seed(env, rid=RID2)
        verbs.route(env.home, RID2, dest="new-skill:mouse-firmware")
        new = make_behavior(scope="skill:s", record_id="lrn-0000cccc")
        create_record(env.home, new)
        verbs.supersede(env.home, RID, "lrn-0000cccc")
        skill_md = env.host / "plugins" / "mouse-firmware" / "skills" / "mouse-firmware" / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        assert f"*({RID})*" not in text
        assert f"*({RID2})*" in text  # the sibling lesson survives

    def test_recompile_repairs_deleted_section_content(self, env):
        seed(env)
        verbs.route(env.home, RID, dest="new-skill:mouse-firmware")
        skill_md = env.host / "plugins" / "mouse-firmware" / "skills" / "mouse-firmware" / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        gutted = text.replace(f"*({RID})*", "*(gone)*")
        skill_md.write_text(gutted, encoding="utf-8")
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "simulate drift")
        verbs.recompile(env.home)
        assert f"*({RID})*" in skill_md.read_text(encoding="utf-8")


def test_selftest_drift_covers_new_skill(env, tmp_path, monkeypatch, capsys):
    from self_learn import cli

    monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))

    seed(env)
    verbs.route(env.home, RID, dest="new-skill:mouse-firmware")
    # U-pointer's `surface` row (--selftest) checks whether the compiled
    # skill is actually INDEXED, not merely present -- the healthy-install
    # premise this test relies on needs a personal-skill symlink into the
    # sandbox claude_dir's skills index, exactly as an operator registers
    # a self-learn-hosted skill (§2.2/§5.1B row 6 of the reachability spec).
    (claude / "skills").mkdir(parents=True)
    (claude / "skills" / "mouse-firmware").symlink_to(
        env.host / "plugins" / "mouse-firmware" / "skills" / "mouse-firmware"
    )
    # fold r1, 2026-09-04: a fully healthy home (all 9 real checks PASS,
    # no worker placeholder row) exits 0 again.
    assert cli.main(["--selftest"]) == 0
    capsys.readouterr()

    # break the compiled canon: the marker must be reported as drift
    skill_md = env.host / "plugins" / "mouse-firmware" / "skills" / "mouse-firmware" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8").replace(f"*({RID})*", "")
    skill_md.write_text(text, encoding="utf-8")
    assert cli.main(["--selftest"]) == 1
    out = capsys.readouterr().out
    assert "FAIL drift" in out and "recompile" in out
