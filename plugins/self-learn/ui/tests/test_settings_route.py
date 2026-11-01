"""U-settings Phase 2 -- the settings page (`GET /settings`, `POST
/settings/set`). Sits on the U-settings Phase 1 CLI registry (`self-learn
config get|set`, `plugins/self-learn/cli`); this file covers only the UI
half -- route rendering, tier enforcement, and the runner seam.

Reads (`GET /settings`) shell the REAL CLI (`ledger.settings` ->
`self-learn config get --json`), exactly like `/report` -- a FakeRunner
queued result controls NOTHING for a page read (this repo's own trap,
`TestHumanizeTsRenderSites.test_holding_section_heading_is_defined`'s own
docstring). The "all four sources" test below is therefore the positive
control: a real temp ledger with a real `config.yaml`, a real env var, a
real override var, and one untouched key, so all four `source` values
are produced by the REAL CLI, not asserted from a canned fixture.

Writes (`POST /settings/set`) run through `VerbRunner` like every other
mutation in this app -- `FakeRunner` for argv/rendering assertions, one
`RealRunner` test proving the whole path end-to-end against the real CLI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from ruamel.yaml import YAML
from starlette.testclient import TestClient

from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.runner import FakeRunner, RealRunner, RunResult

from support import commit_all, make_env

TOKEN = "test-token"


def make_client(sb, *, runner=None, port: int = 7357):
    runner = runner if runner is not None else FakeRunner()
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url=f"http://127.0.0.1:{port}")
    c.cookies.set("slu_token", TOKEN)
    return c, runner


def _row_html(text: str, row_id: str) -> str:
    """One setting's markup: from its own `<li id=...>` to the `</li>` that
    closes it (a row holds no nested list). Humane lane 4: rows were
    `<tr>`s; the tests' meaning is unchanged."""
    start = text.index(f'id="{row_id}"')
    return text[start : text.index("</li>", start)]


def _write_config(home: Path, section: str, dotted_key: str, value: object) -> None:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.yaml"
    yaml = YAML(typ="safe")
    data: dict = {}
    if path.is_file():
        loaded = yaml.load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    node = data.setdefault(section, {})
    node[dotted_key] = value
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh)


# ===================================================================== #
# GET /settings
# ===================================================================== #


class TestSettingsPageRender:
    def test_renders_every_registry_row_with_the_four_source_badges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The positive control (dispatch pin): a config.yaml key, an
        env var, an active override, and an untouched (default) key --
        all four `source` values driven by the REAL CLI against a real
        temp ledger, never a canned fixture."""
        sb = make_env(tmp_path)
        # CONFIG source
        _write_config(sb.ledger, "worker", "no_notify", True)
        from self_learn import settings as settings_mod  # noqa: PLC0415 -- test-local, avoids a package-level cli dep

        # Ambient-leakage guard (this repo's own suite-runner rule: env
        # exports distort settings resolution into false readings) --
        # clear every registered key's OWN env var and override var
        # before setting the two this test deliberately uses, so a
        # host shell's ambient exports (or this package's own autouse
        # AUTOKICK=0 fixture) can never leak into the "default"/"env"
        # rows this test asserts on.
        for s in settings_mod.REGISTRY:
            # M-S (S-58): `env_var` is `str | None` now (the four
            # `provider.bedrock.models.*` entries with no env rung).
            if s.env_var is not None:
                monkeypatch.delenv(s.env_var, raising=False)
            monkeypatch.delenv(settings_mod._override_env_var(s.name), raising=False)  # noqa: SLF001
        # ENV source
        monkeypatch.setenv("SELF_LEARN_MINE_PENDING_GATE", "50")
        # OVERRIDE source
        monkeypatch.setenv("SELF_LEARN_OVERRIDE_SDK_EVENT_LOGS", "5")
        # DEFAULT source: `serve.tick_secs` -- left untouched.

        c, _runner = make_client(sb)
        r = c.get("/settings")
        assert r.status_code == 200
        text = r.text

        for s in settings_mod.REGISTRY:
            assert s.name in text, f"{s.name} missing from the rendered page"

        assert 'id="setting-row-worker-no_notify"' in text
        assert "badge-source-config" in text

        assert 'id="setting-row-miner-pending_gate"' in text
        assert "badge-source-env" in text

        assert 'id="setting-row-sdk-event_logs"' in text
        assert "badge-source-override" in text
        assert "ACTIVE OVERRIDE" in text  # the warn banner, verbatim

        assert 'id="setting-row-serve-tick_secs"' in text
        assert "badge-source-default" in text

    def test_grouped_by_what_a_person_is_trying_to_do_in_the_cli_group_order(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/settings")
        text = r.text
        from self_learn.settings_plain import GROUPS  # noqa: PLC0415 -- test-local cli dep

        # Every group's heading is on the page, in `settings_plain.GROUPS`
        # order (not the registry's component order, which would put
        # "worker" first, nor alphabetical).
        positions = [text.index(f">{g.title}<") for g in GROUPS]
        assert positions == sorted(positions)
        assert len(set(positions)) == len(GROUPS)
        # A row sits inside its own group's block: "Read my sessions
        # overnight" is under "What runs on its own", not under "Limits".
        runs = text.index('id="group-runs"')
        limits = text.index('id="group-limits"')
        assert runs < text.index('id="setting-row-miner-enabled"') < limits
        assert limits < text.index('id="setting-row-miner-max_run_usd"') < text.index('id="group-models"')

    def test_each_setting_shows_its_plain_name_and_sentence_on_the_page(
        self, tmp_path: Path
    ) -> None:
        """The words come from the CLI's `config get --json` (`label`,
        `plain`), shown as text on the row, not only as a hover title; the
        key stays, small, for checking against the command line."""
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        text = c.get("/settings").text
        from markupsafe import escape  # noqa: PLC0415
        from self_learn.settings_plain import plain_for  # noqa: PLC0415

        row_html = _row_html(text, "setting-row-miner-enabled")
        words = plain_for("miner.enabled")
        assert f'<p class="setting-label">{escape(words.label)}</p>' in row_html
        assert f'<p class="setting-plain">{escape(words.plain)}</p>' in row_html
        assert '<code class="setting-key">miner.enabled</code>' in row_html
        # The technical note is folded away, not the row's main text.
        assert "Technical note" in row_html
        assert "title=\"suppress" not in row_html

    def test_a_group_the_cli_marks_folded_is_closed_and_the_others_are_open(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        text = c.get("/settings").text
        from self_learn.settings_plain import GROUPS  # noqa: PLC0415

        for g in GROUPS:
            start = text.index(f'id="group-{g.id}"')
            opening = text[text.rindex("<", 0, start) : text.index(">", start)]
            if g.folded:
                assert opening.startswith("<details") and " open" not in opening, g.id
            else:
                assert opening.startswith("<section"), g.id

    def test_the_attention_classes_are_one_table_with_plain_choices(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        text = c.get("/settings").text
        assert text.count("Where each kind of item goes") == 1
        row_html = _row_html(text, "setting-row-attention-class-hold-credentials")
        assert "Login problems" in row_html and "Inbox: " not in row_html
        for words in ("Waits for you", "Shows as decided", "Stays silent", "Its kind&#39;s default"):
            assert words in row_html, words
        assert 'hx-post="/settings/set"' in row_html
        # the twenty rows share one sentence, said once above them
        assert row_html.count("setting-plain") == 0

    def test_tier_c_rows_have_no_editor(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/settings")
        text = r.text
        for row_id in ("setting-row-worker-autokick", "setting-row-miner-autokick"):
            row_html = _row_html(text, row_id)
            assert 'hx-post="/settings/set"' not in row_html
            assert "only you can change this" in row_html

    def test_tier_a_rows_have_an_editor(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/settings")
        text = r.text
        row_html = _row_html(text, "setting-row-worker-no_notify")
        assert 'hx-post="/settings/set"' in row_html
        assert 'name="name" value="worker.no_notify"' in row_html

    def test_m_s_fold_r1_provider_name_is_tier_c_with_no_editor(self, tmp_path: Path) -> None:
        """M-S (S-58 code-gate fold r1, nit-4): `provider.name` (and the
        whole `invocation.backend` family) moved to tier "C" -- an
        emergency-rollback lever, same character as the two
        spawn-containment switches `test_tier_c_rows_have_no_editor`
        already covers. `worker.no_notify` (asserted above) is the
        positive control this negative depends on: it proves the
        template CAN render an inline editor at all, so `provider.
        name`'s absence of one is a real tier gate, not a template that
        renders no editor for anything."""
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/settings")
        text = r.text
        assert 'hx-post="/settings/set"' in text  # the positive control fired somewhere on the page
        row_html = _row_html(text, "setting-row-provider-name")
        assert 'hx-post="/settings/set"' not in row_html
        assert "only you can change this" in row_html

    def test_degrades_to_an_error_strip_never_a_500_on_a_cli_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from self_learn_ui import ledger as ledger_mod
        from self_learn_ui.models import CliRead

        sb = make_env(tmp_path)
        monkeypatch.setattr(
            ledger_mod, "settings", lambda home, **kw: CliRead(data=None, error="boom: settings unreadable")
        )
        c, _runner = make_client(sb)
        r = c.get("/settings")
        assert r.status_code == 200
        assert "boom: settings unreadable" in r.text


def _opening_tag(text: str, row_id: str) -> str:
    html = _row_html(text, row_id)
    return html[: html.index(">")]


def _is_hidden(text: str, row_id: str) -> bool:
    return " hidden" in _opening_tag(text, row_id)


class TestSettingsFind:
    """"Find a setting": the server applies the same filter the page script
    does (`?q=`), so the box works without script. A row that does not
    match is `hidden`, not dropped, so clearing the box in the page brings
    it back."""

    def _get(self, tmp_path: Path, q: str) -> str:
        base = tmp_path / f"find-{len(list(tmp_path.iterdir()))}"  # a test may ask twice
        base.mkdir()
        sb = make_env(base)
        c, _runner = make_client(sb)
        r = c.get("/settings", params={"q": q})
        assert r.status_code == 200
        return r.text

    def test_no_query_hides_nothing(self, tmp_path: Path) -> None:
        text = self._get(tmp_path, "")
        assert 'id="setting-row-miner-enabled"' in text  # positive control: rows rendered
        assert not _is_hidden(text, "setting-row-miner-enabled")
        assert not _is_hidden(text, "setting-row-provider-bedrock-region")
        none_tag = text[text.index("data-settings-none") : text.index("data-settings-none") + 40]
        assert "hidden" in none_tag

    def test_a_query_keeps_matching_rows_and_hides_the_rest(self, tmp_path: Path) -> None:
        text = self._get(tmp_path, "bedrock")
        assert not _is_hidden(text, "setting-row-provider-bedrock-region")  # positive control
        assert _is_hidden(text, "setting-row-miner-enabled")

    def test_it_searches_the_plain_name_and_the_sentence(self, tmp_path: Path) -> None:
        # "overnight" is in the plain name "Read my sessions overnight"
        # (miner.enabled); "coalesce" only in the key of worker.coalesce_secs.
        text = self._get(tmp_path, "my sessions overnight")
        assert not _is_hidden(text, "setting-row-miner-enabled")
        assert _is_hidden(text, "setting-row-worker-coalesce_secs")
        # a word only in the plain sentence of models.miner ("writes lessons")
        text = self._get(tmp_path, "writes lessons")
        assert not _is_hidden(text, "setting-row-models-miner")

    def test_it_searches_the_technical_note_too(self, tmp_path: Path) -> None:
        # "sleeps" appears only in worker.coalesce_secs's technical note.
        text = self._get(tmp_path, "sleeps")
        assert not _is_hidden(text, "setting-row-worker-coalesce_secs")
        assert _is_hidden(text, "setting-row-miner-enabled")

    def test_every_typed_word_must_match(self, tmp_path: Path) -> None:
        text = self._get(tmp_path, "sleeps overnight")
        assert _is_hidden(text, "setting-row-worker-coalesce_secs")
        assert _is_hidden(text, "setting-row-miner-enabled")
        i = text.index("data-settings-none")
        assert "hidden" not in text[i : i + 40]  # the "nothing matches" line shows
        assert "No setting matches" in text

    def test_a_match_in_a_folded_group_opens_that_group(self, tmp_path: Path) -> None:
        text = self._get(tmp_path, "sleeps")
        start = text.index('id="group-time"')
        opening = text[text.rindex("<", 0, start) : text.index(">", start)]
        assert opening.startswith("<details") and " open" in opening
        # and a group with no match is hidden, not opened
        start = text.index('id="group-bedrock"')
        assert " hidden" in text[text.rindex("<", 0, start) : text.index(">", start)]

    def test_the_status_line_counts_the_matches(self, tmp_path: Path) -> None:
        text = self._get(tmp_path, "sleeps")
        assert "1 setting matches" in text


# ===================================================================== #
# POST /settings/set
# ===================================================================== #


class TestSettingsSetRoute:
    def test_builds_the_exact_argv_and_reruns_with_the_runner_output(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        runner = FakeRunner()
        row = {
            "name": "worker.no_notify",
            "value": True,
            "source": "config:worker.no_notify",
            "kind": "bool",
            "default": False,
            "description": "suppress the desktop notifications the worker would otherwise send",
            "tier": "A",
            "warn": None,
        }
        runner.queue_result(RunResult(0, stdout=json.dumps(row)))
        c, runner = make_client(sb, runner=runner)
        r = c.post("/settings/set", data={"name": "worker.no_notify", "value": "1"}, headers={"HX-Request": "true"})
        assert r.status_code == 200
        # NIT-1 (review r2 2026-09-02): VALUE sits after `--` (with
        # `--json` before it) so a leading `-` in a posted value can
        # never be swallowed by argparse -- see `routes.py`'s
        # `settings_set` docstring.
        assert runner.calls == [["config", "set", "worker.no_notify", "--json", "--", "1"]]
        assert 'id="setting-row-worker-no_notify"' in r.text
        assert "badge-source-config" in r.text
        assert "Set in config.yaml" in r.text
        assert "Saved." in r.text
        # a row from a CLI without the plain words still reads: its key is the name
        assert '<p class="setting-label">worker.no_notify</p>' in r.text

    def test_renders_the_warn_line_when_an_override_masks_the_write(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        runner = FakeRunner()
        warn_text = (
            "ACTIVE OVERRIDE, outranks config.yaml. Unset "
            "SELF_LEARN_OVERRIDE_WORKER_NO_NOTIFY to stop overriding."
        )
        row = {
            "name": "worker.no_notify",
            "value": False,
            "source": "override:worker.no_notify",
            "kind": "bool",
            "default": False,
            "description": "suppress the desktop notifications the worker would otherwise send",
            "tier": "A",
            "warn": warn_text,
        }
        runner.queue_result(RunResult(0, stdout=json.dumps(row)))
        c, runner = make_client(sb, runner=runner)
        r = c.post("/settings/set", data={"name": "worker.no_notify", "value": "1"}, headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert "badge-source-override" in r.text
        assert warn_text in r.text  # reused VERBATIM, not paraphrased
        # one line in plain words up front, the full note in a fold
        assert "Set for this terminal only" in r.text
        assert f"<details><summary>The full note</summary><p>{warn_text}</p></details>" in r.text

    def test_a_refused_write_re_renders_the_row_with_the_verb_error(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        runner = FakeRunner()
        runner.queue_result(
            RunResult(1, stderr="worker.no_notify='true' is not a valid bool (bool settings take 1 or 0)")
        )
        c, runner = make_client(sb, runner=runner)
        r = c.post("/settings/set", data={"name": "worker.no_notify", "value": "true"}, headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert runner.calls == [["config", "set", "worker.no_notify", "--json", "--", "true"]]
        assert 'id="setting-row-worker-no_notify"' in r.text
        assert "not a valid bool" in r.text
        assert "Saved." not in r.text  # a refused write is never reported as saved
        # the refusal holds off the broadcast page reload that would wipe it (Y-16 leg a)
        assert 'data-setting-error data-verb-error="true"' in r.text

    def test_refuses_a_tier_c_name_before_touching_the_runner(
        self, tmp_path: Path
    ) -> None:
        """Y-17-style server enforcement: the template never renders an
        editor for a tier-C row, but a forged POST must ALSO refuse --
        `worker.autokick` is a spawn-containment kill switch, not a
        preference (2026-08-09 incident)."""
        sb = make_env(tmp_path)
        c, runner = make_client(sb)
        r = c.post("/settings/set", data={"name": "worker.autokick", "value": "0"}, headers={"HX-Request": "true"})
        assert r.status_code == 400
        assert runner.calls == []  # never reached the verb

    def test_refuses_an_unknown_name(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, runner = make_client(sb)
        r = c.post("/settings/set", data={"name": "nope.nope", "value": "1"}, headers={"HX-Request": "true"})
        assert r.status_code == 404
        assert runner.calls == []


# ===================================================================== #
# End-to-end: a REAL runner against the REAL CLI
# ===================================================================== #


class TestSettingsSetRealRunner:
    @pytest.mark.asyncio
    async def test_value_set_from_the_page_is_visible_in_doctor_settings(
        self, tmp_path: Path
    ) -> None:
        """`RealRunner`, no fake anywhere -- the whole path: POST
        /settings/set -> RealRunner -> a real `self-learn config set`
        subprocess -> a real commit -> a SECOND real CLI read
        (`self-learn doctor settings`) proves the value the page wrote
        is visible with source `config:...`, not just this process's
        own return value."""
        sb = make_env(tmp_path)
        runner = RealRunner(home=sb.ledger, env=sb.env)
        app = create_app(env=load_env(sb.env), token=TOKEN, runner=runner, start_watcher=False)
        c = TestClient(app, base_url="http://127.0.0.1:7357")
        c.cookies.set("slu_token", TOKEN)

        r = c.post("/settings/set", data={"name": "miner.cap_max", "value": "7"}, headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert "badge-source-config" in r.text

        import subprocess
        import sys

        from self_learn_ui.runner import resolve_self_learn_argv_prefix

        prefix = resolve_self_learn_argv_prefix(sb.env)
        full_env = dict(sb.env)
        full_env["SELF_LEARN_HOME"] = str(sb.ledger)
        proc = subprocess.run(
            [*prefix, "doctor", "settings"],
            env=full_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0
        assert "miner.cap_max = 7 (config:miner.cap_max)" in proc.stdout

        log = subprocess.run(
            ["git", "-C", str(sb.ledger), "log", "-1", "--format=%s"],
            capture_output=True, text=True, check=True,
        )
        assert log.stdout.strip() == "self-learn: config set miner.cap_max=7"

    @pytest.mark.asyncio
    async def test_a_leading_dash_value_sets_cleanly_from_the_page(
        self, tmp_path: Path
    ) -> None:
        """NIT-1 (code-gate review r2 2026-09-02): a VALUE beginning
        with `-` (`ledger.actor = -alex`) used to be swallowed by
        argparse's own optional-argument matching before `_cmd_config`
        ever ran -- the CLI's `_swallowed_config_set_value` pre-check
        caught the shape and printed terminal advice ("put `--` before
        it, e.g. `self-learn config set NAME -- -alex`") that this
        row's error strip then rendered verbatim on a WEB page, where
        typing `--` in a form field means nothing. `settings_set` now
        inserts `--` into the argv itself (`routes.py`), so the real
        subprocess never sees the ambiguity -- proved end-to-end here,
        `RealRunner` and all: rc 0, the value actually lands in
        config.yaml (a second, independent `doctor settings` read
        proves it), and no `--` advice text reaches the row."""
        sb = make_env(tmp_path)
        runner = RealRunner(home=sb.ledger, env=sb.env)
        app = create_app(env=load_env(sb.env), token=TOKEN, runner=runner, start_watcher=False)
        c = TestClient(app, base_url="http://127.0.0.1:7357")
        c.cookies.set("slu_token", TOKEN)

        r = c.post(
            "/settings/set", data={"name": "ledger.actor", "value": "-alex"}, headers={"HX-Request": "true"}
        )
        assert r.status_code == 200
        assert "badge-source-config" in r.text
        assert "--" not in r.text  # no leftover `--` advice text in the row
        assert "looks like a flag" not in r.text

        import subprocess

        from self_learn_ui.runner import resolve_self_learn_argv_prefix

        prefix = resolve_self_learn_argv_prefix(sb.env)
        full_env = dict(sb.env)
        full_env["SELF_LEARN_HOME"] = str(sb.ledger)
        proc = subprocess.run(
            [*prefix, "doctor", "settings"],
            env=full_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0
        assert "ledger.actor = '-alex' (config:ledger.actor)" in proc.stdout


# ===================================================================== #
# MINOR-2 (code-gate review r2 2026-09-02): the row error strip used to
# forward the CLI's stderr WHOLE -- on a malformed config.yaml, the
# CLI's read path ALSO warns once per OTHER known setting it resolves
# on the way to this one (two of which, on the way to resolving
# `worker.no_notify`/`sdk.max_turns.worker`, come from settings this
# handler's own `ledger.settings` read touches), landing above the
# actual refusal (worst case measured: ~24 lines in one `<td>`).
# `routes.py`'s `settings_set` now trims to the `self-learn config
# set:` marker onward. Each of MAJOR-1's four malformed shapes (review
# r1 2026-09-01) is proved here end-to-end -- `RealRunner`, a real
# committed config.yaml, a real subprocess -- the row must carry
# EXACTLY the refusal sentence and nothing above it.
# ===================================================================== #


def _error_strip_text(html: str) -> str:
    m = re.search(r'<p class="error-strip settings-row-error"[^>]*>(.*)</p>', html, re.S)
    assert m is not None, html
    return m.group(1).strip()


class TestSettingsSetMalformedConfigYamlErrorStripTrim:
    async def _post(self, tmp_path: Path, config_text: str, name: str, value: str) -> str:
        sb = make_env(tmp_path)
        (sb.ledger / "config.yaml").write_text(config_text, encoding="utf-8")
        commit_all(sb.ledger, "seed a malformed config.yaml")
        runner = RealRunner(home=sb.ledger, env=sb.env)
        app = create_app(env=load_env(sb.env), token=TOKEN, runner=runner, start_watcher=False)
        c = TestClient(app, base_url="http://127.0.0.1:7357")
        c.cookies.set("slu_token", TOKEN)
        r = c.post("/settings/set", data={"name": name, "value": value}, headers={"HX-Request": "true"})
        assert r.status_code == 200
        return _error_strip_text(r.text)

    @pytest.mark.asyncio
    async def test_scalar_section(self, tmp_path: Path) -> None:
        err = await self._post(tmp_path, "worker: 5\n", "worker.no_notify", "1")
        assert err == (
            "self-learn config set: worker: already a int, not a mapping "
            "-- refusing to write worker.no_notify over it"
        )

    @pytest.mark.asyncio
    async def test_unparseable(self, tmp_path: Path) -> None:
        err = await self._post(tmp_path, "key: [1, 2\n", "worker.no_notify", "1")
        assert err.startswith("self-learn config set: ")
        assert "is unparseable" in err
        assert "refusing to write over it" in err
        assert "config.yaml ignored" not in err
        assert "miner.enabled ignored" not in err
        assert "miner.autokick ignored" not in err

    @pytest.mark.asyncio
    async def test_non_mapping_top_level(self, tmp_path: Path) -> None:
        err = await self._post(tmp_path, "- a\n- b\n- c\n", "worker.no_notify", "1")
        assert err.startswith("self-learn config set: ")
        assert "must be a YAML mapping, got CommentedSeq" in err
        assert "refusing to write over it" in err
        assert "config.yaml ignored" not in err

    @pytest.mark.asyncio
    async def test_mid_walk_scalar(self, tmp_path: Path) -> None:
        err = await self._post(tmp_path, "sdk:\n  max_turns: 5\n", "sdk.max_turns.worker", "3")
        assert err == (
            "self-learn config set: sdk.max_turns: already a int, not a mapping "
            "-- refusing to write sdk.max_turns.worker over it"
        )
