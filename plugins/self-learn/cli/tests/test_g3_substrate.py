"""U0 — G-3 surface substrate (10 §3 task U0; 08 §1 dated edit,
2026-07-17; 09 §11 Y-2/Y-4/Y-11).

Genuinely NEW pieces only (``mine status --json`` and ``report --json
.open_followups`` already exist and are out of scope here):

- ``list --json`` items gain ``bucket`` / ``host_registered`` / ``source``.
- ``report --json`` gains ``recurrence_suspects`` (rows ``{id, nonce,
  seen_at}``) — exposes the existing M2 deterministic suspect detection
  (``worker._recurrence_suspects``), never reimplements it.
- ``hosts.canon_read_roots()`` — the pane read-scope helper (Y-2).
- ``host add`` prints a one-line consent note (Y-2 companion).

All ledger homes here are throwaway sandbox repos under pytest tmpdirs
(``support.make_env`` / hand-rolled bare ledgers) — never the real
``~/.self-learn``.
"""

from __future__ import annotations

import json

import pytest

from self_learn import cli, telemetry
from self_learn.hosts import Hosts, canon_read_roots, slug_for
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.report import gather

from support import (
    commit_all,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    proposal_dict,
)


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    # Every test redirects the cache — the suite must never see a real one.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    sandbox = make_env(tmp_path, skills=("s",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(sandbox.ledger))
    return sandbox


def _bare_ledger(tmp_path) -> "object":
    """A ledger home with the layout dirs but NO hosts.yaml at all — the
    'nothing registered' state (missing file = empty registry, per
    hosts.load_hosts)."""
    home = tmp_path / "bare-ledger"
    init_repo(home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()
    return home


def _list_json(capsys):
    rc = cli.main(["list", "--json"])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


# ------------------------------------------------------------- list --json


class TestListJsonSubstrate:
    def test_registered_skill_bucket(self, env, capsys):
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001")
        create_record(env.ledger, rec)
        (item,) = _list_json(capsys)
        assert item["bucket"] == "s"
        assert item["host_registered"] is True  # skills_root registered by make_env
        assert item["source"] == "teach"

    def test_source_reflects_record_provenance(self, env, capsys):
        rec = make_knowledge(scope="user", record_id="lrn-aa000001")
        rec.set_source("session")
        create_record(env.ledger, rec)
        (item,) = _list_json(capsys)
        assert item["bucket"] == "user"
        assert item["source"] == "session"

    def test_registered_project_bucket(self, env, capsys):
        # make_env registers env.host as BOTH skills root and a project.
        rec = make_knowledge(scope="project", record_id="lrn-aa000001")
        create_record(env.ledger, rec, project_path=env.host)
        (item,) = _list_json(capsys)
        assert item["bucket"] == slug_for(env.host)
        assert item["host_registered"] is True

    def test_foreign_unregistered_project_bucket(self, env, capsys, tmp_path):
        foreign = tmp_path / "foreign-repo"
        init_repo(foreign)
        rec = make_knowledge(scope="project", record_id="lrn-aa000001")
        create_record(env.ledger, rec, project_path=foreign)
        (item,) = _list_json(capsys)
        assert item["bucket"] == slug_for(foreign)
        assert item["host_registered"] is False

    def test_no_skills_root_unregisters_skill_and_user_buckets(
        self, tmp_path, monkeypatch, capsys
    ):
        home = _bare_ledger(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rec = make_knowledge(scope="user", record_id="lrn-aa000001")
        create_record(home, rec)
        (item,) = _list_json(capsys)
        assert item["bucket"] == "user"
        assert item["host_registered"] is False

    def test_pinned_key_order_includes_new_fields_at_the_end(self, env, capsys):
        create_record(env.ledger, make_behavior(scope="skill:s", record_id="lrn-aa000001"))
        (item,) = _list_json(capsys)
        assert list(item.keys())[-3:] == ["bucket", "host_registered", "source"]


# ---------------------------------------------------------- report --json


def _route(env, rid="lrn-0000aaaa"):
    create_record(env.ledger, make_behavior(scope="skill:s", record_id=rid))
    write_proposal(env.ledger, rid, proposal_dict())
    commit_all(env.ledger, "pending")
    assert cli.main(["route", rid, "--no-push"]) == 0
    return rid


def _spool_suspect(env, routed, origin="lrn-0000eeee"):
    telemetry.spool_event(
        "recurrence-suspect", record=routed, origin=origin, basis="origin-match"
    )
    telemetry.flush(env.ledger)
    event = next(
        e for e in telemetry.read_events(env.ledger) if e["kind"] == "recurrence-suspect"
    )
    return event["nonce"], event["ts"]


class TestReportRecurrenceSuspects:
    def test_planted_suspect_on_a_routed_record_is_exposed(self, env):
        rid = _route(env)
        nonce, ts = _spool_suspect(env, rid)
        facts = gather(env.ledger)
        assert facts["recurrence_suspects"] == [
            {"id": rid, "nonce": nonce, "seen_at": ts}
        ]

    def test_confirmed_suspect_drops_off(self, env):
        rid = _route(env)
        nonce, _ts = _spool_suspect(env, rid)
        assert (
            cli.main(["confirm-recurrence", rid, "--event", nonce, "--no-push"]) == 0
        )
        facts = gather(env.ledger)
        assert facts["recurrence_suspects"] == []

    def test_no_suspects_is_empty_list(self, env):
        _route(env)
        facts = gather(env.ledger)
        assert facts["recurrence_suspects"] == []

    def test_cli_report_json_carries_the_field(self, env, capsys):
        rid = _route(env)
        nonce, ts = _spool_suspect(env, rid)
        capsys.readouterr()  # discard route's own stdout
        rc = cli.main(["report", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["recurrence_suspects"] == [
            {"id": rid, "nonce": nonce, "seen_at": ts}
        ]

    def test_malformed_telemetry_line_is_skipped_not_crashed(self, env):
        # Telemetry is untrusted input (11 §4.2 — any process may spool a
        # line; a hand-edited/corrupt tracked file is not impossible).
        # Wrong-typed `record`/`nonce` fields must never crash report.
        rid = _route(env)
        good_nonce, good_ts = _spool_suspect(env, rid, origin="lrn-0000eeee")
        tdir = telemetry.telemetry_dir(env.ledger)
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "manual.jsonl").write_text(
            "\n".join(
                [
                    # record is an int, not a str — must not blow up a
                    # dict lookup keyed by record id
                    json.dumps({"kind": "recurrence-suspect", "record": 123, "nonce": "aaaa0000"}),
                    # nonce missing entirely
                    json.dumps({"kind": "recurrence-suspect", "record": rid}),
                    # nonce explicitly null
                    json.dumps({"kind": "recurrence-suspect", "record": rid, "nonce": None}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        facts = gather(env.ledger)  # must not raise
        assert facts["recurrence_suspects"] == [
            {"id": rid, "nonce": good_nonce, "seen_at": good_ts}
        ]


# ------------------------------------------------------- canon_read_roots


class TestCanonReadRoots:
    def test_empty_registry_returns_nothing(self):
        assert canon_read_roots(Hosts()) == []

    def test_skills_root_only_yields_skill_trees_and_hook_canon(self, tmp_path):
        host = tmp_path / "host-a"
        init_repo(host)
        skill1 = host / "plugins" / "p1" / "skills" / "skill1"
        skill2 = host / "plugins" / "p2" / "skills" / "skill2"
        skill1.mkdir(parents=True)
        skill2.mkdir(parents=True)
        (skill1 / "SKILL.md").write_text("# skill1\n", encoding="utf-8")
        (skill2 / "SKILL.md").write_text("# skill2\n", encoding="utf-8")
        hooks_self_learn = host / "hooks" / "self-learn"
        hooks_self_learn.mkdir(parents=True)
        p1_hooks = host / "plugins" / "p1" / "hooks"
        p1_hooks.mkdir(parents=True)
        # a non-canon dir that must NEVER leak into the read scope
        (host / "src").mkdir()
        (host / "src" / "secret.py").write_text("x = 1\n", encoding="utf-8")
        commit_all(host, "seed")

        hosts = Hosts(skills_root=host, projects=[])
        roots = set(canon_read_roots(hosts))
        assert roots == {
            skill1.resolve(),
            skill2.resolve(),
            hooks_self_learn.resolve(),
            p1_hooks.resolve(),
        }

    def test_two_host_fixture_full_surface(self, tmp_path):
        """The DoD fixture: skills root (with skill trees + hook-canon dirs)
        plus a second, project-only host — asserts the EXACT surface set."""
        host_a = tmp_path / "host-a"
        init_repo(host_a)
        skill1 = host_a / "plugins" / "p1" / "skills" / "skill1"
        skill1.mkdir(parents=True)
        (skill1 / "SKILL.md").write_text("# skill1\n", encoding="utf-8")
        hooks_self_learn = host_a / "hooks" / "self-learn"
        hooks_self_learn.mkdir(parents=True)
        p1_hooks = host_a / "plugins" / "p1" / "hooks"
        p1_hooks.mkdir(parents=True)
        (host_a / "CLAUDE.md").write_text("# host a\n", encoding="utf-8")
        commit_all(host_a, "seed")

        host_b = tmp_path / "host-b"
        init_repo(host_b)
        (host_b / "CLAUDE.md").write_text("# host b\n", encoding="utf-8")
        (host_b / "references").mkdir()
        (host_b / "references" / "LEARNINGS.md").write_text("# L\n", encoding="utf-8")
        commit_all(host_b, "seed")

        hosts = Hosts(skills_root=host_a, projects=[host_a, host_b])
        roots = set(canon_read_roots(hosts))

        assert roots == {
            skill1.resolve(),
            hooks_self_learn.resolve(),
            p1_hooks.resolve(),
            (host_a / "CLAUDE.md").resolve(),
            (host_a / "references").resolve(),
            (host_b / "CLAUDE.md").resolve(),
            (host_b / "references").resolve(),
        }

    def test_project_host_yields_claude_md_and_references_dir_even_if_absent(
        self, tmp_path
    ):
        host = tmp_path / "host-c"
        init_repo(host)  # no CLAUDE.md, no references/ written yet — no commit needed

        hosts = Hosts(skills_root=None, projects=[host])
        roots = set(canon_read_roots(hosts))
        assert roots == {(host / "CLAUDE.md").resolve(), (host / "references").resolve()}


# --------------------------------------------------------- host add consent


class TestHostAddConsent:
    def test_prints_one_line_consent_note(self, tmp_path, monkeypatch, capsys):
        home = _bare_ledger(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        target = tmp_path / "some-repo"
        init_repo(target)

        rc = cli.main(["host", "add", str(target)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "canon surfaces" in out
        assert "compile target" in out
        assert "analyst-readable" in out
