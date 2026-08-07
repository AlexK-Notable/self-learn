"""S-10 amendment (user ruling 2026-07-16): the one-motion refusal for
hook/new-skill is CONFIGURABLE via a committed <home>/config.yaml —
default unchanged (refuse, same messages, safe degrade), opt-in flips it,
parsing is fail-closed, and the enabled hook path still runs the FULL
integrity chain (validation, secret scan, replay pre-commit) and prints
the applied script bytes. Activation stays manual regardless."""

from __future__ import annotations

import json
import stat
import subprocess

import pytest

from self_learn import cli, verbs
from self_learn.config import one_motion_enabled
from self_learn.hook_compiler import script_name
from self_learn.ledger_ops import validate_proposal
from self_learn.records import Record
from support import git, make_behavior, make_env


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


class Env:
    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.bucket = self.home / "skills" / "s"

    def enable(self, *destinations):
        text = "one_motion_route:\n" + "".join(
            f"  {d}: true\n" for d in destinations
        )
        (self.home / "config.yaml").write_text(text, encoding="utf-8")

    def write_config(self, text):
        (self.home / "config.yaml").write_text(text, encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


TRIGGER = "About to edit `.storage/*.json` while HA is running."


def hook_input(**overrides) -> dict:
    base = {
        "rationale": "deterministic guard; over-block: denies stopped-container edits too",
        "alternates": ["skill-md"],
        "hook": {
            "tools": ["Edit", "Write"],
            "path_regex": r"\.storage/",
            "deny_message": "stop the HA container first",
        },
        "examples": {
            "allow": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/config.yaml"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
            ],
            "deny": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/a"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/b"}},
            ],
        },
    }
    base.update(overrides)
    return base


def record_for(env):
    return make_behavior(scope="skill:s", trigger=TRIGGER)


# ------------------------------------------------------------ fail-closed


class TestConfigFailClosed:
    def test_no_config_disabled_silently(self, env, capsys):
        assert one_motion_enabled(env.home, "hook") is False
        assert capsys.readouterr().err == ""

    def test_enabled_only_by_yaml_true(self, env):
        env.enable("hook")
        assert one_motion_enabled(env.home, "hook") is True
        assert one_motion_enabled(env.home, "new-skill") is False

    @pytest.mark.parametrize(
        "text",
        [
            "one_motion_route: {hook: [not-a-bool]}",  # wrong value type
            'one_motion_route: {hook: "true"}',  # string, not boolean
            "one_motion_route: [hook]",  # wrong section shape
            "[ this is not : valid yaml",  # unparseable
            "- top level is a list",  # wrong top-level shape
        ],
    )
    def test_malformed_refuses_and_warns(self, env, capsys, text):
        env.write_config(text)
        assert one_motion_enabled(env.home, "hook") is False
        assert "config.yaml ignored" in capsys.readouterr().err

    def test_explicit_false_is_silent(self, env, capsys):
        env.write_config("one_motion_route: {hook: false}")
        assert one_motion_enabled(env.home, "hook") is False
        assert capsys.readouterr().err == ""


# -------------------------------------------------------- default refusal


class TestDefaultUnchanged:
    def test_route_direct_hook_refused_same_message(self, env):
        with pytest.raises(
            verbs.VerbError, match="cannot be routed in one motion"
        ):
            verbs.route_direct(env.home, record_for(env), dest="hook")

    def test_route_direct_new_skill_refused(self, env):
        with pytest.raises(
            verbs.VerbError, match="cannot be routed in one motion"
        ):
            verbs.route_direct(env.home, record_for(env), dest="new-skill:x")

    def test_teach_cli_precheck_refuses_default(self, env, capsys):
        rc = cli.main(
            ["teach", "l", "--skill", "s", "--type", "behavior",
             "--trigger", "t", "--instruction", "i",
             "--route", "--dest", "hook"]
        )
        assert rc != 0
        err = capsys.readouterr().err
        assert "cannot be routed in one motion" in err
        # safe degrade: nothing landed anywhere
        assert not list((env.bucket / "pending").glob("*.md")) if (
            env.bucket / "pending"
        ).is_dir() else True


# ---------------------------------------------------------- enabled: hook


class TestEnabledHook:
    def test_end_to_end_full_chain_and_visibility(self, env):
        env.enable("hook")
        record = record_for(env)
        result = verbs.route_direct(
            env.home, record, dest="hook", hook_input=hook_input()
        )
        name = script_name(record.id, TRIGGER)
        script = env.host / "plugins" / "s-plugin" / "hooks" / name
        assert script.is_file()
        assert script.stat().st_mode & stat.S_IXUSR
        # verbatim: committed bytes are the generated bytes, and the
        # human gets them PRINTED — the diff opens with the full script
        assert result.diff.startswith("#!/usr/bin/env bash")
        assert script.read_text(encoding="utf-8") == result.diff.split(
            "\n--- ledger ---\n"
        )[0]
        # manual activation reminder survives (settings.json stays manual)
        notes = "\n".join(result.post_notes)
        assert "settings.json" in notes and "./install.sh" in notes
        # ledger truth: routed record carries the approved artifacts
        routed = Record.from_path(
            env.bucket / "resolved" / f"{record.id}.md"
        )
        assert routed.routing["hook"]["script_path"] == (
            f"plugins/s-plugin/hooks/{name}"
        )
        # the guard actually guards
        deny = subprocess.run(
            [str(script)],
            input=json.dumps(
                {"tool_name": "Edit", "tool_input": {"file_path": "/.storage/x"}}
            ),
            capture_output=True,
            text=True,
        )
        assert deny.returncode == 2

    def test_enabled_without_input_names_the_flag(self, env):
        env.enable("hook")
        with pytest.raises(verbs.VerbError, match="--hook-input"):
            verbs.route_direct(env.home, record_for(env), dest="hook")

    def test_replay_mismatch_aborts_before_anything_lands(self, env):
        env.enable("hook")
        bad = hook_input()
        # an allow example the guard denies: replay must abort the route
        bad["examples"]["allow"][0] = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/x/.storage/oops"},
        }
        record = record_for(env)
        with pytest.raises(verbs.VerbError, match="replay"):
            verbs.route_direct(env.home, record, dest="hook", hook_input=bad)
        assert not (env.bucket / "resolved" / f"{record.id}.md").exists()
        assert not list((env.host / "plugins").rglob("self-learn-*.sh"))

    def test_secret_in_compile_input_refused(self, env):
        env.enable("hook")
        bad = hook_input(
            rationale="key: -----BEGIN RSA PRIVATE KEY----- oops"
        )
        with pytest.raises(verbs.SecretRefusal):
            verbs.route_direct(
                env.home, record_for(env), dest="hook", hook_input=bad
            )

    def test_invalid_input_schema_refused(self, env):
        env.enable("hook")
        bad = hook_input()
        del bad["examples"]  # M3-12: replay cases are mandatory
        with pytest.raises(verbs.VerbError, match="examples"):
            verbs.route_direct(
                env.home, record_for(env), dest="hook", hook_input=bad
            )

    def test_teach_cli_hook_input_end_to_end(self, env, tmp_path, capsys):
        env.enable("hook")
        payload = tmp_path / "guard.yaml"
        import io

        from ruamel.yaml import YAML

        buf = io.StringIO()
        YAML(typ="safe").dump(hook_input(), buf)
        payload.write_text(buf.getvalue(), encoding="utf-8")
        rc = cli.main(
            ["teach", "chezmoi guard", "--skill", "s", "--type", "behavior",
             "--trigger", TRIGGER, "--instruction", "Stop the container first.",
             "--route", "--dest", "hook", "--hook-input", str(payload),
             "--no-push"]
        )
        out = capsys.readouterr().out
        assert rc == 0
        # requirement: the applied script bytes are PRINTED
        assert "#!/usr/bin/env bash" in out
        assert "settings.json" in out
        scripts = list((env.host / "plugins").rglob("self-learn-*.sh"))
        assert len(scripts) == 1

    def test_hook_input_flag_needs_route_dest_hook(self, env, tmp_path, capsys):
        (tmp_path / "x.yaml").write_text("hook: {}\n", encoding="utf-8")
        rc = cli.main(
            ["teach", "l", "--skill", "s", "--type", "behavior",
             "--trigger", "t", "--instruction", "i",
             "--hook-input", str(tmp_path / "x.yaml")]
        )
        assert rc != 0
        assert "--hook-input" in capsys.readouterr().err


# ----------------------------------------------------- enabled: new-skill


class TestEnabledNewSkill:
    def seed_marketplace(self, env):
        mp = env.host / ".claude-plugin" / "marketplace.json"
        mp.parent.mkdir(exist_ok=True)
        mp.write_text(
            json.dumps({"name": "sandbox", "plugins": []}, indent=2) + "\n",
            encoding="utf-8",
        )
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "marketplace seed")

    def test_end_to_end_scaffold(self, env):
        self.seed_marketplace(env)
        env.enable("new-skill")
        record = record_for(env)
        result = verbs.route_direct(
            env.home, record, dest="new-skill:storage-guard"
        )
        skill_md = (
            env.host / "plugins" / "storage-guard" / "skills" / "storage-guard" / "SKILL.md"
        )
        assert skill_md.is_file()
        assert f"*({record.id})*" in skill_md.read_text(encoding="utf-8")
        data = json.loads(
            (env.host / ".claude-plugin" / "marketplace.json").read_text()
        )
        assert [p["name"] for p in data["plugins"]] == ["storage-guard"]
        routed = Record.from_path(env.bucket / "resolved" / f"{record.id}.md")
        assert routed.routing["new_skill"] == "storage-guard"
        assert result.commit_message.endswith("→ new-skill:storage-guard")
        assert any("install.sh" in n for n in result.post_notes)

    def test_hook_enabled_does_not_unlock_new_skill(self, env):
        env.enable("hook")  # per-destination gates are independent
        with pytest.raises(
            verbs.VerbError, match="cannot be routed in one motion"
        ):
            verbs.route_direct(env.home, record_for(env), dest="new-skill:x")


# --------------------------------------------------- gate FOLD 4 follow-up


class TestOneMotionHookGatesSurviveContainmentAndDerivation:
    """Gate FOLD 4: `_one_motion_hook_gates`'s trace used to point t1/t2's
    evidence at a fabricated string ("a human supplied --hook-input: this
    is a hook route by construction") that appears in no record, and its
    proposal never named "reference" in `alternates` even though the
    trace's own t2/t3/tn/t4 answers derive DEMAND as the fallback load
    class (u-table §3.3 R-HOOK). Both survived every existing test only
    because `_prepare_one_motion_hook` calls `validate_proposal(data)`
    bare — no `record_text=`, no `scope=` — so neither containment nor
    Table-1/Render-1 derivation ever ran against it. This pins that a
    caller who DOES supply both gets an honest ACCEPT, not a refusal that
    was merely dormant."""

    def _full_proposal(self, record: Record) -> dict:
        # The exact shape `_prepare_one_motion_hook` builds, assembled
        # directly here so this test exercises `_one_motion_hook_gates`'s
        # trace and the verb's real `alternates` MERGE logic without also
        # exercising script generation/replay (a different concern,
        # already covered end-to-end elsewhere in this file). Uses this
        # module's own `hook_input()` default, which names its OWN
        # `alternates: [skill-md]` — deliberately NOT "reference" — so
        # this exercises the merge path (a caller-supplied list gets
        # "reference" ADDED, never silently replaced or left short).
        data = hook_input()
        data["destination"] = "hook"
        data["model"] = "one-motion-cli"
        data["analyzed_at"] = "2026-08-07T00:00:00Z"
        data["gates"] = verbs._one_motion_hook_gates()
        data["flags"] = ["evidence-gap"]
        data["recommendation"] = "route"
        # Mirrors `_prepare_one_motion_hook`'s own merge exactly (verbs.py):
        # order-preserving, duplicate-free, "reference" always present.
        alternates = list(dict.fromkeys(data.get("alternates") or []))
        if "reference" not in alternates:
            alternates.append("reference")
        data["alternates"] = alternates
        assert data["alternates"] == ["skill-md", "reference"], data["alternates"]
        return data

    def test_accepts_under_record_text(self):
        record = make_behavior(scope="skill:s")
        data = self._full_proposal(record)
        # ACCEPT: raises nothing.
        validate_proposal(data, record_text=record.to_text())

    def test_accepts_under_scope(self):
        record = make_behavior(scope="skill:s")
        data = self._full_proposal(record)
        # ACCEPT: raises nothing.
        validate_proposal(data, scope=record.scope)

    def test_accepts_under_both_together(self):
        record = make_behavior(scope="skill:s")
        data = self._full_proposal(record)
        # ACCEPT under both simultaneously — the actual future-caller shape.
        validate_proposal(data, record_text=record.to_text(), scope=record.scope)

    def test_quote_is_genuinely_contained_not_fabricated(self):
        # Positive control (gate M1 discipline): pin the OLD fabricated
        # string is gone and the new quote is a real substring of the
        # record it accompanies — a future edit that reintroduces a
        # fabricated quote fails THIS assertion even if containment
        # somehow still passed for an unrelated reason.
        record = make_behavior(scope="skill:s")
        gates = verbs._one_motion_hook_gates()
        evidence = gates["t1"]["field_shaped"]["evidence"]
        assert evidence in record.to_text()
        assert "a human supplied --hook-input" not in evidence

    def test_production_call_site_actually_merges_reference_in(self, env, monkeypatch):
        # The `_full_proposal` tests above mirror `_prepare_one_motion_
        # hook`'s merge logic by hand — this test proves the REAL verb
        # does it, not a hand copy that could silently drift from
        # production. Intercepts the exact `data` dict the real
        # `_prepare_one_motion_hook` builds and passes to
        # `validate_proposal`, via the full `route_direct(dest="hook")`
        # pipeline (env.enable("hook"), a real compile input carrying its
        # own `alternates: [skill-md]`), then still calls through so the
        # route completes normally.
        captured: list[dict] = []
        real_validate = verbs.validate_proposal

        def spy(data, **kwargs):
            captured.append(dict(data))
            return real_validate(data, **kwargs)

        monkeypatch.setattr(verbs, "validate_proposal", spy)
        env.enable("hook")
        verbs.route_direct(env.home, record_for(env), dest="hook", hook_input=hook_input())
        assert captured, "validate_proposal was never called"
        assert captured[0]["alternates"] == ["skill-md", "reference"]
