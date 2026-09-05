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

import fcntl
import json
import time
from pathlib import Path

import pytest

from self_learn import cli as cli_mod
from self_learn import gitops, settings

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
            # M-S (S-58, r5-m1(c)): `note` -- the fold detail, `None`
            # here since nothing folded anything for this entry.
            "name", "value", "source", "kind", "default", "description", "tier", "warn", "note",
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
            "note": None,
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
                "note": None,
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
        # M-S (S-58 code-gate fold r1, nit-4): `provider.name` and the
        # whole `invocation.backend` family (the general key AND all
        # four per-surface siblings — splitting the general key's tier
        # from its own siblings would make no sense, it is the SAME
        # emergency-rollback lever) join the two pre-existing
        # spawn-containment switches as tier "C".
        assert c_names == {
            "worker.autokick",
            "miner.autokick",
            "provider.name",
            "invocation.backend",
            "invocation.backend_worker",
            "invocation.backend_worker-repair",
            "invocation.backend_miner-reader",
            "invocation.backend_analyst",
        }
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

    def test_setting_an_inactive_key_names_both_written_and_committed(
        self, tmp_path, monkeypatch, capsys
    ):
        """M-S (S-58 code-gate fold r1, nit-3): `config set` on an
        INACTIVE key (here, a bedrock-only key under the default
        `provider=anthropic`) already writes AND commits the value --
        `row["source"]` just reports `"inactive (provider=...)"` with
        the entry's own DEFAULT as `value`, which alone reads as "the
        write didn't take". A second, explicit line must name both
        facts the plain row masks."""
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", "provider.bedrock.region", "us-west-2"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "inactive (provider=anthropic)" in out
        assert "written and committed" in out
        # the write DID land on disk, git-committed -- a fresh registry
        # read under provider=bedrock proves it, and the log has a
        # commit for it.
        assert "config set provider.bedrock.region=" in _log_subjects(home)[0]
        value, source = settings.resolve_setting(home, settings.by_name("provider.name"))
        assert (value, source) == ("anthropic", "default")

    def test_setting_a_masked_paired_key_names_both_written_and_committed(
        self, tmp_path, monkeypatch, capsys
    ):
        """M-S delta gate r2, nit-1: `config set` on a paired entry
        (`invocation.backend_worker`) whose GENERAL env var
        (`SELF_LEARN_BACKEND`) is active writes the value AND commits
        it, but the printed row shows `source = env:SELF_LEARN_BACKEND`
        -- not this key's own `config:invocation.backend_worker` rung
        -- with no confirmation the write landed. nit-3's original fix
        only caught the "inactive" flavor of this same underlying fact
        (the shown source isn't the key's own config rung); this is the
        SAME masked-write line, reached via the source-agnostic
        comparison rather than a literal `startswith("inactive")`."""
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
        rc = cli_mod.main(["config", "set", "invocation.backend_worker", "sdk"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "env:SELF_LEARN_BACKEND" in out
        assert "written and committed" in out
        assert "config set invocation.backend_worker=" in _log_subjects(home)[0]
        monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)
        value, source = settings.resolve_setting(home, settings.by_name("invocation.backend_worker"))
        assert (value, source) == ("sdk", "config:invocation.backend_worker")

    def test_setting_an_unmasked_key_prints_no_masked_write_line(
        self, tmp_path, monkeypatch, capsys
    ):
        """Positive control for the two tests above: an ORDINARY
        `config set` whose own config rung is what actually answers
        (nothing overrides, no env var, no general sibling, not
        inactive) must print NO "written and committed" line -- that
        line exists only to name a mask, and this write has none."""
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", "worker.autokick", "0"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "config:worker.autokick" in out
        assert "written and committed" not in out

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

    def test_bool_hint_absent_from_a_non_bool_parse_failure(
        self, tmp_path, monkeypatch, capsys
    ):
        """MINOR-3 (review r1 2026-09-01): the "(bool settings take 1 or
        0)" hint used to be appended to EVERY kind's parse-failure
        message, including this one -- a float setting's own error
        talked about bool syntax that has nothing to do with it."""
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", "worker.coalesce_secs", "not-a-float"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "worker.coalesce_secs" in err
        assert "float" in err
        assert "bool settings take 1 or 0" not in err

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
        # NIT-1 (review r1 2026-09-01): the refusal used to only name
        # the TYPE ("out of range for float"), never the bound -- now it
        # says what would have been accepted (the entry's own
        # `validate_hint`).
        assert "must be > 0" in err
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

    def test_setting_the_same_float_value_twice_is_a_clean_no_op(
        self, tmp_path, monkeypatch, capsys
    ):
        """MINOR-1 (review r2 2026-09-02) regression: the idempotent
        check moved from `config.settings_leaf` (`YAML(typ="safe")`,
        plain `float`) to `config.present` (`load_editable`, round-trip
        mode) -- ruamel's round-trip loader wraps EVERY float scalar in
        `ScalarFloat`, never bare `float` (confirmed empirically, not
        just for specially-formatted values), so an unnormalized
        `type(...) is type(...)` compare would NEVER match for a
        float-kind setting even when the value is unchanged --
        `ScalarFloat is not float`. That reintroduces the exact bug the
        idempotent check exists to prevent (see the bool-only pin right
        above this test): a byte-identical re-`set` would reach
        `set_leaf`, `git commit` would refuse "nothing to commit", and
        the write-already-happened wrapper would misreport a false
        HALF-WRITTEN state (rc 7). `worker.no_notify` above is a `bool`
        -- the one kind round-trip mode can never subclass -- so it
        could not have caught this; this test uses a REAL float-kind
        setting instead."""
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc1 = cli_mod.main(["config", "set", "worker.coalesce_secs", "12.5"])
        assert rc1 == 0
        capsys.readouterr()
        before = _log_subjects(home)
        rc2 = cli_mod.main(["config", "set", "worker.coalesce_secs", "12.5"])
        out = capsys.readouterr()
        assert rc2 == 0
        assert "WRITE NOT COMMITTED" not in out.err
        assert "Traceback" not in out.err
        assert _log_subjects(home) == before  # no second commit

    def test_a_no_op_set_still_refuses_on_a_dirty_config_yaml(
        self, tmp_path, monkeypatch, capsys
    ):
        """MINOR-1 (review r1 2026-09-01): the idempotent short-circuit
        used to run BEFORE the dirty-check -- a `set` whose value
        already matches printed a clean "success" even though
        config.yaml itself had unrelated uncommitted changes sitting on
        disk. Dirty check now runs first; the short-circuit only ever
        fires against a tree already known clean."""
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc1 = cli_mod.main(["config", "set", "worker.no_notify", "1"])
        assert rc1 == 0
        capsys.readouterr()
        before = _log_subjects(home)
        # an unrelated, uncommitted edit to config.yaml -- the dirty check's
        # target, left dirty on purpose
        text = (home / "config.yaml").read_text(encoding="utf-8")
        (home / "config.yaml").write_text(text + "  # a hand edit\n", encoding="utf-8")
        rc2 = cli_mod.main(["config", "set", "worker.no_notify", "1"])  # same value
        err = capsys.readouterr().err
        assert rc2 == 1
        assert "uncommitted" in err
        assert _log_subjects(home) == before  # no commit happened


# ===================================================================== #
# config set -- secret scan (MAJOR-2)
# ===================================================================== #


class TestConfigSetSecretScan:
    """MAJOR-2 (review r1 2026-09-01): `config set --note` was the one
    note-bearing verb that skipped the secret scan every OTHER verb
    runs (`verbs._scan_or_refuse`) -- measured live: `reject --note
    "...ghp_..."` refused rc 1, `config set --note "...ghp_..."`
    committed rc 0. Coordinator's ruling: a typed int/float/bool VALUE
    can't carry a token (skip stays right there), but `note` is free
    prose landing in a committed+pushed commit BODY regardless of kind,
    and a `str`-kind VALUE can itself be a token (`ledger.actor` lands
    in the commit SUBJECT itself)."""

    GHP_TOKEN = "ghp_" + "a" * 36  # fires the github-token scan rule

    def test_note_with_a_token_is_refused(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(
            [
                "config",
                "set",
                "worker.no_notify",
                "1",
                "--note",
                f"key is {self.GHP_TOKEN}",
            ]
        )
        err = capsys.readouterr().err
        assert rc == 1
        assert "secret scan" in err
        assert _log_subjects(home) == before  # no commit happened
        assert not (home / "config.yaml").exists()

    def test_str_kind_value_carrying_a_token_is_refused(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(["config", "set", "ledger.actor", self.GHP_TOKEN])
        err = capsys.readouterr().err
        assert rc == 1
        assert "secret scan" in err
        assert _log_subjects(home) == before
        assert not (home / "config.yaml").exists()

    def test_int_value_is_not_scanned_positive_control(self, tmp_path, monkeypatch, capsys):
        """The scan must not be over-broad: a plain digit-string VALUE
        for an int-kind setting commits normally, exactly like before
        this fix -- proving the scan targets `note`/`str`-kind VALUEs
        only, never every argument on the command line."""
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", "miner.cap_max", "7"])
        assert rc == 0
        assert capsys.readouterr().err == ""


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


# ===================================================================== #
# MAJOR-1 (review r1 2026-09-01): four reachable committed-but-malformed
# config.yaml states used to exit `config set`/`unset` with a raw Python
# traceback (absolute paths and all) instead of a refusal sentence --
# `config.ConfigWriteError` propagated uncaught past `cli._cmd_config`'s
# except chain. Each of these seeds config.yaml with a malformed shape,
# COMMITS it (a clean tree -- so the dirty-check does not short-circuit
# before the write attempt ever runs), then asserts rc 1, the class's
# own composed message, and NO "Traceback" anywhere in stderr.
# ===================================================================== #


def _seed_committed_config(home: Path, text: str) -> None:
    (home / "config.yaml").write_text(text, encoding="utf-8")
    git(home, "add", "-A")
    git(home, "commit", "-q", "-m", "seed a malformed config.yaml")


class TestConfigSetMalformedConfigYaml:
    def test_scalar_section_refuses_cleanly(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        _seed_committed_config(home, "worker: 5\n")
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(["config", "set", "worker.no_notify", "1"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Traceback" not in err
        assert "worker" in err
        assert "not a mapping" in err
        assert _log_subjects(home) == before  # no commit happened

    def test_unparseable_file_refuses_cleanly(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        _seed_committed_config(home, "key: [1, 2\n")  # unclosed flow sequence
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(["config", "set", "worker.no_notify", "1"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Traceback" not in err
        assert "unparseable" in err
        assert _log_subjects(home) == before

    def test_non_mapping_top_level_refuses_cleanly(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        _seed_committed_config(home, "- a\n- b\n- c\n")  # a YAML list, not a mapping
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(["config", "set", "worker.no_notify", "1"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Traceback" not in err
        assert "must be a YAML mapping" in err
        assert _log_subjects(home) == before

    def test_mid_walk_scalar_refuses_cleanly(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        _seed_committed_config(home, "sdk:\n  max_turns: 5\n")
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        # sdk.max_turns.worker walks THROUGH sdk.max_turns -- a scalar
        # (5) in the committed file, mid-path toward the leaf.
        rc = cli_mod.main(["config", "set", "sdk.max_turns.worker", "3"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Traceback" not in err
        assert "max_turns" in err
        assert "not a mapping" in err
        assert _log_subjects(home) == before


# ===================================================================== #
# MINOR-1 (code-gate review r2 2026-09-02): `config set`'s idempotent
# short-circuit used to read via the LENIENT `config.settings_leaf`
# (silent `None` on a malformed config.yaml), so a malformed committed
# file fell all the way through to `gitops.commit_lock` before anything
# noticed. If another producer already held that lock, `set` sat out
# the FULL `gitops.COMMIT_LOCK_TIMEOUT` (150s) before reporting "another
# self-learn producer is wedged mid-commit" -- misdiagnosing a malformed
# file as lock contention and sending the operator hunting a producer
# that does not exist. Fixed the same way `config_unset` already was
# (MINOR-2, review r1): the idempotent check now uses the strict,
# pre-lock `config.present`, which raises before the lock is ever
# requested. Proved here by genuinely holding the lock (a raw flock on
# `gitops.commit_lock_path`, bypassing `_flock_lock` entirely so the
# OS-level conflict is real) and timing the call.
# ===================================================================== #


class TestConfigSetLockMisdiagnosis:
    def test_a_malformed_config_refuses_fast_even_with_the_lock_held(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        _seed_committed_config(home, "worker: 5\n")
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        lock_path = gitops.commit_lock_path(home)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # "another self-learn producer"
        try:
            start = time.monotonic()
            rc = cli_mod.main(["config", "set", "worker.no_notify", "1"])
            elapsed = time.monotonic() - start
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()

        err = capsys.readouterr().err
        assert rc == 1
        assert "not a mapping" in err
        assert "worker" in err
        assert "wedged" not in err  # never reached the lock-contention path at all
        # miles under COMMIT_LOCK_TIMEOUT (150s) -- proves the lock was
        # never even requested, not just that it timed out quickly.
        assert elapsed < 5.0


class TestConfigUnsetMalformedConfigYaml:
    def test_scalar_section_refuses_same_as_set(self, tmp_path, monkeypatch, capsys):
        """MINOR-2 (review r1 2026-09-01): `config unset` used to report
        "already unset, nothing to remove" against a malformed
        config.yaml -- the exact file `config set` refuses outright.
        Same file, same refusal now."""
        home = make_home(tmp_path)
        _seed_committed_config(home, "worker: 5\n")
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        before = _log_subjects(home)
        rc = cli_mod.main(["config", "unset", "worker.no_notify"])
        out = capsys.readouterr()
        assert rc == 1
        assert "already unset" not in out.out
        assert "Traceback" not in out.err
        assert "not a mapping" in out.err
        assert _log_subjects(home) == before


# ===================================================================== #
# MINOR-4 (review r1 2026-09-01): a `config_section=None` REGISTRY entry
# (reserved for a future bootstrap var with no config.yaml rung) used to
# hit a bare `assert` in `config_set`/`config_unset` instead of a typed
# refusal. No REAL registry entry has this shape today (the registry-
# time invariant added alongside this fix makes it impossible to
# register one with the wrong tier), so this exercises the refusal
# directly against a synthetic entry, monkeypatched into `by_name`'s
# lookup table for the duration of the test.
# ===================================================================== #


class TestConfigNoConfigRungError:
    @pytest.fixture
    def bootstrap_setting(self, monkeypatch):
        from self_learn.settings import Setting

        synthetic = Setting(
            name="bootstrap.no-rung",
            env_var="SELF_LEARN_BOOTSTRAP_NO_RUNG",
            config_section=None,
            config_key=None,
            kind="str",
            default="x",
            description="test-only: no config.yaml rung",
            tier="C",
        )
        monkeypatch.setitem(settings._BY_NAME, synthetic.name, synthetic)
        return synthetic

    def test_config_set_refuses_with_a_typed_message(
        self, tmp_path, monkeypatch, capsys, bootstrap_setting
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", bootstrap_setting.name, "y"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Traceback" not in err
        assert bootstrap_setting.name in err
        assert not (home / "config.yaml").exists()

    def test_config_unset_refuses_with_a_typed_message(
        self, tmp_path, monkeypatch, capsys, bootstrap_setting
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "unset", bootstrap_setting.name])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Traceback" not in err
        assert bootstrap_setting.name in err


# ===================================================================== #
# NIT-2 (review r1 2026-09-01): a `config set` VALUE beginning with `-`
# that is not a bare negative number is swallowed by argparse's own
# optional-argument matching before `_cmd_config` ever runs -- these pin
# the narrow pre-check `cli._swallowed_config_set_value` that catches
# exactly that shape and refuses with a message pointing at `--`,
# instead of argparse's generic "the following arguments are required:
# value".
# ===================================================================== #


class TestConfigSetNegativeValueHandling:
    # `-5`/`-5.5`/`-` are the shapes argparse's own "looks like a
    # negative number" heuristic lets through unassisted on EVERY
    # Python version this repo runs on (measured on 3.13 and 3.14 --
    # more exotic shapes like `-5e10`/`-1abc`/`-5.` sit right on a
    # boundary argparse's internal regex has actually changed ACROSS
    # those two versions, which is exactly why
    # `_swallowed_config_set_value` asks argparse's own matcher
    # directly (`_looks_option_like`) instead of a hand-written regex
    # guess -- these parametrized cases stick to the shapes stable on
    # every version, not the version-sensitive boundary itself).
    @pytest.mark.parametrize(
        "value", ["-5", "-5.5", "-"],
        ids=["int", "float", "bare-dash"],
    )
    def test_values_argparse_already_parses_are_left_alone(self, value):
        assert cli_mod._swallowed_config_set_value(["config", "set", "n", value]) is None

    @pytest.mark.parametrize(
        "value", ["-abc", "-x", "--foo", "-n5"],
        ids=["alpha", "short-flag-like", "long-flag-like", "letter-then-digit"],
    )
    def test_flag_like_values_are_flagged(self, value):
        assert cli_mod._swallowed_config_set_value(["config", "set", "n", value]) == value

    def test_a_correctly_escaped_value_is_left_alone(self):
        argv = ["config", "set", "n", "--", "-abc"]
        assert cli_mod._swallowed_config_set_value(argv) is None

    def test_flags_before_the_value_are_skipped_correctly(self):
        argv = ["config", "set", "n", "--json", "--note", "hi", "-abc"]
        assert cli_mod._swallowed_config_set_value(argv) == "-abc"

    def test_other_verbs_are_not_this_checks_concern(self):
        assert cli_mod._swallowed_config_set_value(["config", "get", "-abc"]) is None
        assert cli_mod._swallowed_config_set_value(["config", "unset", "-abc"]) is None
        assert cli_mod._swallowed_config_set_value(["host", "add", "-abc"]) is None

    def test_end_to_end_prints_a_clear_refusal_not_argparse_noise(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", "worker.no_notify", "-abc"])
        err = capsys.readouterr().err
        assert rc == 2
        assert "-abc" in err
        assert "--" in err
        assert not (home / "config.yaml").exists()

    def test_end_to_end_a_bare_negative_number_still_works_unassisted(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli_mod.main(["config", "set", "worker.coalesce_secs", "-5.5"])
        assert rc == 0
