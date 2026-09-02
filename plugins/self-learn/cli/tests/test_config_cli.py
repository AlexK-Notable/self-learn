"""U-settings Phase 2 -- the `config get`/`set`/`unset` CLI verb group
(`settings.py`'s write path: :func:`settings.config_set`/
:func:`settings.config_unset`/:func:`settings.setting_row`; `cli.py`'s
`_cmd_config*` dispatch). Phase 1's registry mechanics (resolution order,
`doctor settings`, the override channel) are covered in
`test_settings.py`, unchanged by this unit; this file covers only the
NEW write path.

`get` never mutates and needs no git repo (`home.mkdir()` alone, same
convention `test_settings.py`'s own `doctor settings` tests already use).
`set`/`unset` commit to the ledger, so they need a REAL git repo --
`support.make_home` (doc-13 layout, git-initialized, one seed commit).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import cli as cli_mod
from self_learn import settings

from support import git, make_home


def _log_subjects(home: Path) -> list[str]:
    out = git(home, "log", "--format=%s").stdout
    return [line for line in out.splitlines() if line]


# ===================================================================== #
# config get
# ===================================================================== #


class TestConfigGet:
    def test_prints_every_registry_entry_as_name_equals_value_source(
        self, tmp_path, monkeypatch, capsys
    ):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "get"])
        out = capsys.readouterr().out
        assert rc == 0
        for s in settings.REGISTRY:
            assert f"{s.name} = " in out
            assert "(default)" in out  # a pristine home: every entry defaults

    def test_json_shape_lists_every_registry_entry(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "get", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        rows = json.loads(out)
        assert {r["name"] for r in rows} == {s.name for s in settings.REGISTRY}
        # `sdk.event_logs` (unlike `worker.no_notify`/`worker.autokick`/
        # `worker.coalesce_secs`) has no ambient env pin from this
        # package's own `conftest.py::_worker_test_defaults` (autouse,
        # every test) -- a "pristine home" byte-shape assertion needs a
        # key that genuinely still resolves to `default` under it.
        row = next(r for r in rows if r["name"] == "sdk.event_logs")
        assert set(row) == {
            "name", "value", "source", "kind", "default", "description", "tier", "warn",
        }
        assert row == {
            "name": "sdk.event_logs",
            "value": 20,
            "source": "default",
            "kind": "int",
            "default": 20,
            "description": row["description"],
            "tier": "A",
            "warn": None,
        }

    def test_json_default_for_a_none_default_setting_is_json_null(
        self, tmp_path, monkeypatch, capsys
    ):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "get", "sdk.max_budget_usd", "--json"])
        rows = json.loads(capsys.readouterr().out)
        assert rows == [
            {
                "name": "sdk.max_budget_usd",
                "value": None,
                "source": "default",
                "kind": "float",
                "default": None,
                "description": rows[0]["description"],
                "tier": "A",
                "warn": None,
            }
        ]

    def test_single_name_returns_one_row(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "get", "worker.no_notify", "--json"])
        rows = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(rows) == 1
        assert rows[0]["name"] == "worker.no_notify"

    def test_unknown_name_refuses_rc_64(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "get", "nope.nope"])
        err = capsys.readouterr().err
        assert rc == 64
        assert "nope.nope" in err

    def test_tier_field_matches_the_dispatch_ruling(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "get", "--json"])
        rows = json.loads(capsys.readouterr().out)
        assert rc == 0
        c_names = {r["name"] for r in rows if r["tier"] == "C"}
        a_names = {r["name"] for r in rows if r["tier"] == "A"}
        assert c_names == {"worker.autokick", "miner.autokick"}
        assert a_names == {s.name for s in settings.REGISTRY} - c_names


# ===================================================================== #
# config set
# ===================================================================== #


class TestConfigSet:
    @pytest.mark.parametrize(
        "name, raw, expect_value",
        [
            pytest.param("worker.no_notify", "1", True, id="bool"),
            pytest.param("miner.cap_max", "7", 7, id="int"),
            pytest.param("worker.coalesce_secs", "12.5", 12.5, id="float"),
            pytest.param("miner.transcripts_dir", "/tmp/somewhere", "/tmp/somewhere", id="str"),
        ],
    )
    def test_round_trips_every_kind(
        self, tmp_path, monkeypatch, capsys, name, raw, expect_value
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", name, raw, "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        row = json.loads(out)
        assert row["value"] == expect_value
        assert row["source"] == f"config:{name}"
        # A fresh process re-resolving (doctor settings) sees the SAME
        # value -- proves the write actually landed on disk, not just in
        # this process's own return value.
        rc2 = cli_mod.main(["doctor", "settings"])
        doctor_out = capsys.readouterr().out
        assert rc2 == 0
        assert f"{name} = {expect_value!r} (config:{name})" in doctor_out

    def test_refuses_malformed_value_with_registry_message(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", "worker.no_notify", "true"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "worker.no_notify" in err  # names the key
        assert "'true'" in err  # names the offending value
        assert "bool" in err  # names the kind
        # nothing was written
        assert not (home / "config.yaml").exists()

    def test_refuses_a_value_validate_rejects_as_out_of_range(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        # worker.invoke_timeout_secs's own validate: `v if v > 0 else None`
        rc = cli_mod.main(["config", "set", "worker.invoke_timeout_secs", "0"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "worker.invoke_timeout_secs" in err
        assert not (home / "config.yaml").exists()

    def test_refuses_unregistered_name_rc_64(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", "nope.nope", "1"])
        err = capsys.readouterr().err
        assert rc == 64
        assert "nope.nope" in err
        assert not (home / "config.yaml").exists()

    def test_preserves_an_unrelated_key_and_a_comment(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        (home / "config.yaml").write_text(
            "# a hand comment\n"
            "one_motion_route:\n"
            "  hook: true  # inline note\n",
            encoding="utf-8",
        )
        git(home, "add", "-A")
        git(home, "commit", "-q", "-m", "seed config.yaml")
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", "worker.no_notify", "1"])
        assert rc == 0
        text = (home / "config.yaml").read_text(encoding="utf-8")
        assert "# a hand comment" in text
        assert "# inline note" in text
        assert "one_motion_route" in text
        assert "hook: true" in text
        assert "no_notify: true" in text

    def test_makes_exactly_one_commit_with_the_pinned_subject_and_note_body(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(
            ["config", "set", "worker.no_notify", "1", "--note", "a resolution note"]
        )
        assert rc == 0
        after = _log_subjects(home)
        assert len(after) == len(before) + 1
        assert after[0] == "self-learn: config set worker.no_notify=True"
        body = git(home, "log", "-1", "--format=%b").stdout
        assert "a resolution note" in body

    def test_refuses_on_a_dirty_config_yaml(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        (home / "config.yaml").write_text("worker:\n  no_notify: false\n", encoding="utf-8")
        # deliberately left UNCOMMITTED -- dirty
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(["config", "set", "worker.no_notify", "1"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "config.yaml" in err
        assert "uncommitted" in err
        assert _log_subjects(home) == before  # no commit happened
        # the file still holds the operator's OWN uncommitted value --
        # the refusal must not have touched it.
        assert "no_notify: false" in (home / "config.yaml").read_text(encoding="utf-8")

    def test_prints_the_post_write_source_and_warn_when_an_override_masks_it(
        self, tmp_path, monkeypatch, capsys
    ):
        """The positive control: an ACTIVE override outranks the value
        `set` just committed. The printed source must say so
        (`override:worker.no_notify`, not `config:worker.no_notify`),
        and the JSON `warn` field must carry the verbatim `doctor
        settings` override sentence -- never silence."""
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("SELF_LEARN_OVERRIDE_WORKER_NO_NOTIFY", "0")
        rc = cli_mod.main(["config", "set", "worker.no_notify", "1", "--json"])
        row = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert row["source"] == "override:worker.no_notify"
        assert row["value"] is False
        assert row["warn"] is not None
        assert "ACTIVE OVERRIDE" in row["warn"]
        assert "SELF_LEARN_OVERRIDE_WORKER_NO_NOTIFY" in row["warn"]
        # the write to config.yaml itself still landed -- only the
        # RESOLVED/printed value is masked, not the commit.
        text = (home / "config.yaml").read_text(encoding="utf-8")
        assert "no_notify: true" in text

    def test_non_json_warn_line_goes_to_stderr(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("SELF_LEARN_OVERRIDE_WORKER_NO_NOTIFY", "0")
        rc = cli_mod.main(["config", "set", "worker.no_notify", "1"])
        out = capsys.readouterr()
        assert rc == 0
        assert "override:worker.no_notify" in out.out
        assert "ACTIVE OVERRIDE" in out.err

    def test_setting_the_same_value_twice_is_a_clean_no_op(
        self, tmp_path, monkeypatch, capsys
    ):
        """Regression: the first landing of this unit crashed the SECOND
        identical `set` with a false HALF-WRITTEN report -- `git commit`
        refuses "nothing to commit" on a byte-identical write, which the
        write-already-happened wrapper misread as a half-written state.
        Fixed by an idempotent pre-lock check; pinned here so it cannot
        regress silently."""
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc1 = cli_mod.main(["config", "set", "worker.no_notify", "1"])
        assert rc1 == 0
        capsys.readouterr()
        before = _log_subjects(home)
        rc2 = cli_mod.main(["config", "set", "worker.no_notify", "1"])
        out = capsys.readouterr()
        assert rc2 == 0
        assert "Traceback" not in out.err
        assert _log_subjects(home) == before  # no second commit


# ===================================================================== #
# config unset
# ===================================================================== #


class TestConfigUnset:
    def test_removes_the_key_and_commits(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        cli_mod.main(["config", "set", "worker.no_notify", "1"])
        capsys.readouterr()
        before = _log_subjects(home)
        rc = cli_mod.main(["config", "unset", "worker.no_notify"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "worker.no_notify" in out
        text = (home / "config.yaml").read_text(encoding="utf-8")
        assert "no_notify" not in text
        after = _log_subjects(home)
        assert len(after) == len(before) + 1
        assert after[0] == "self-learn: config unset worker.no_notify"

    def test_idempotent_on_an_already_unset_key(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(["config", "unset", "worker.no_notify"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "already unset" in out
        assert _log_subjects(home) == before  # no commit made

    def test_refuses_unregistered_name_rc_64(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "unset", "nope.nope"])
        err = capsys.readouterr().err
        assert rc == 64
        assert "nope.nope" in err

    def test_refuses_on_a_dirty_config_yaml(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        (home / "config.yaml").write_text("worker:\n  no_notify: true\n", encoding="utf-8")
        git(home, "add", "-A")
        git(home, "commit", "-q", "-m", "seed the key to unset")
        # a SECOND, unrelated, uncommitted edit to config.yaml
        (home / "config.yaml").write_text(
            "worker:\n  no_notify: true\n  repair: false\n", encoding="utf-8"
        )
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(["config", "unset", "worker.no_notify"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "config.yaml" in err
        assert "uncommitted" in err
        assert _log_subjects(home) == before
        # the operator's own uncommitted edit is untouched
        assert "repair: false" in (home / "config.yaml").read_text(encoding="utf-8")

    def test_reverts_config_get_source_to_default_after_unset(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        # `conftest.py::_worker_test_defaults` (autouse, every test) pins
        # SELF_LEARN_NO_NOTIFY=1 globally -- clear it here so the
        # post-unset resolution genuinely falls all the way through to
        # `default`, matching this test's own name/intent, rather than
        # landing on that ambient env rung instead.
        monkeypatch.delenv("SELF_LEARN_NO_NOTIFY", raising=False)
        cli_mod.main(["config", "set", "worker.no_notify", "1"])
        capsys.readouterr()
        cli_mod.main(["config", "unset", "worker.no_notify"])
        capsys.readouterr()
        rc = cli_mod.main(["config", "get", "worker.no_notify", "--json"])
        row = json.loads(capsys.readouterr().out)[0]
        assert rc == 0
        assert row["source"] == "default"
        assert row["value"] is False
