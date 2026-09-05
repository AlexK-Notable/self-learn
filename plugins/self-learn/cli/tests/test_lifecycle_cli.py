"""11 now-tranche CLI surfaces: `route --follow-up`, `followup done`,
`telemetry note`/`telemetry flush`, flush-in-verbs, capture events, and
`report` v1.

Sandbox git repos with bare remotes; XDG cache + actor redirected per
test; SELF_LEARN_HOME pointed at the sandbox.
"""

import json
import subprocess

import pytest

from self_learn import cli, telemetry
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record
from support import (
    SKILL_MD_SEED,
    commit_all,
    git,
    make_behavior,
    make_env,
    proposal_dict,
    verb_files,
    verb_subject,
)

SKILL_MD = SKILL_MD_SEED.format(name="s")


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


class Env:
    """doc-13 sandbox pair: LEDGER home (records + hosts.yaml) with a bare
    remote, plus the HOST repo (compiled canon) with its own bare remote so
    two-phase routing pushes cleanly."""

    def __init__(self, tmp_path):
        e = make_env(tmp_path)
        self.home = e.ledger
        self.host = e.host
        self.skill_dir = e.skill_dir  # host-side
        self.skill_md = e.skill_md  # host-side (seeded by make_env)
        self.bare = tmp_path / "remote.git"
        self.host_bare = tmp_path / "host-remote.git"
        for bare, repo in ((self.bare, self.home), (self.host_bare, self.host)):
            subprocess.run(
                ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
            )
            git(repo, "remote", "add", "origin", str(bare))
            git(repo, "push", "-q", "-u", "origin", "main")
        self.seed_subject = self.local_subject()

    # The verb's own commit = newest non-telemetry-flush commit (doc 13
    # H-5: telemetry commits itself now — audit 2026-07-16 MAJOR 3).
    def local_subject(self):
        return verb_subject(self.home)

    def committed_paths(self):
        return verb_files(self.home)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


def seed_pending(env, record_id="lrn-0000aaaa"):
    # skill-scoped record → lands in the LEDGER skills/s bucket.
    record = make_behavior(record_id=record_id)
    create_record(env.home, record)
    write_proposal(env.home, record_id, proposal_dict())
    commit_all(env.home, "pending record")
    return record_id


def resolved_record(env, record_id="lrn-0000aaaa"):
    # resolved records live in the LEDGER, not the host skill dir (doc 13 §3)
    return Record.from_path(
        env.home / "skills" / "s" / "resolved" / f"{record_id}.md"
    )


# ------------------------------------------------------ route --follow-up


def test_route_follow_up_rides_routing_block(env):
    rid = seed_pending(env)
    rc = cli.main(
        [
            "route",
            rid,
            "--follow-up",
            "upgrade-to-hook",
            "--unblocks-on",
            "M3",
            "--follow-up-note",
            "advisory text is the weak form",
        ]
    )
    assert rc == 0
    record = resolved_record(env)
    assert record.follow_up == {
        "action": "upgrade-to-hook",
        "unblocks_on": "M3",
        "note": "advisory text is the weak form",
    }
    assert record.status == "routed"  # no new lifecycle status (11 §2.1)


def test_route_follow_up_flags_need_follow_up(env, capsys):
    rid = seed_pending(env)
    rc = cli.main(["route", rid, "--unblocks-on", "M3"])
    assert rc == 64
    assert "--follow-up" in capsys.readouterr().err


# ---------------------------------------------------------- followup done


def test_followup_done_clears_and_commits_pinned_subject(env):
    rid = seed_pending(env)
    assert cli.main(["route", rid, "--follow-up", "upgrade-to-hook"]) == 0
    rc = cli.main(["followup", "done", rid, "--note", "hook landed"])
    assert rc == 0
    assert env.local_subject() == f"self-learn: follow-up done on {rid}"
    record = resolved_record(env)
    assert record.follow_up is None
    assert record.follow_up_done["action"] == "upgrade-to-hook"
    assert record.follow_up_done["done_note"] == "hook landed"
    assert record.follow_up_done["done_at"]
    # resolution_note untouched — write-once, reserved (02 §2)
    assert record.resolution_note is None


def test_followup_done_without_open_followup_refuses(env, capsys):
    rid = seed_pending(env)
    assert cli.main(["route", rid]) == 0
    rc = cli.main(["followup", "done", rid])
    assert rc == 1
    assert "no open follow-up" in capsys.readouterr().err


def test_followup_done_unknown_id_is_usage(env, capsys):
    rc = cli.main(["followup", "done", "lrn-99999999"])
    assert rc == 64


def test_followup_done_refuses_after_status_leaves_routed(env, capsys):
    """FW-51 M-3 (code gate r1): followup_done's own docstring says
    "Clear a ROUTED record's follow-up" — nothing enforced it. Measured:
    route with a follow_up, then graduate (status -> superseded; the
    follow_up block SURVIVES the transition, graduate only WARNS about
    it) -> followup_done used to still succeed, clear it, and commit,
    even though open_followups() had already stopped listing it as open
    (11 §2.5's status gate). Now gated the same way: exit 1, nothing
    written, the follow_up block untouched."""
    rid = seed_pending(env)
    assert cli.main(["route", rid, "--follow-up", "upgrade-to-hook"]) == 0
    assert cli.main(["graduate", rid]) == 0
    record = resolved_record(env)
    assert record.status == "superseded"
    assert record.follow_up == {"action": "upgrade-to-hook"}  # survives graduate
    path = env.home / "skills" / "s" / "resolved" / f"{rid}.md"
    before_bytes = path.read_bytes()
    before_head = git(env.home, "rev-parse", "HEAD").stdout.strip()

    rc = cli.main(["followup", "done", rid])

    assert rc == 1
    err = capsys.readouterr().err
    assert "'superseded'" in err
    assert path.read_bytes() == before_bytes
    assert git(env.home, "rev-parse", "HEAD").stdout.strip() == before_head
    record = resolved_record(env)
    assert record.status == "superseded"
    assert record.follow_up == {"action": "upgrade-to-hook"}  # unchanged


def test_status_counts_open_followups(env, capsys):
    rid = seed_pending(env)
    assert cli.main(["route", rid, "--follow-up", "upgrade-to-hook"]) == 0
    capsys.readouterr()
    rc = cli.main(["status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["open_followups"] == 1


# ------------------------------------------------------------- telemetry


def test_telemetry_note_spools_offer_declined(env, capsys):
    rc = cli.main(["telemetry", "note", "offer-declined", "--reason", "later"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "spool" in out
    spool = list(telemetry.spool_dir().glob("*.jsonl"))
    assert len(spool) == 1
    event = json.loads(spool[0].read_text().splitlines()[0])
    assert event["kind"] == "offer-declined"
    assert event["reason"] == "later"
    # spool-only: nothing in the tracked plane, nothing committed (11 §2.5).
    # make_env pre-creates telemetry/, so the pin is that it stays EMPTY.
    assert list((env.home / "telemetry").glob("*.jsonl")) == []
    assert env.local_subject() in ("pending record", env.seed_subject)


def test_telemetry_note_rejects_code_emitted_kinds(env, capsys):
    rc = cli.main(["telemetry", "note", "capture"])
    assert rc == 64
    assert "code-emitted" in capsys.readouterr().err


def test_telemetry_note_rejects_free_text_reason(env, capsys):
    rc = cli.main(["telemetry", "note", "offer-declined", "--reason", "felt like it"])
    assert rc == 64
    assert "closed enum" in capsys.readouterr().err


def test_telemetry_flush_moves_spool(env, capsys):
    cli.main(["telemetry", "note", "offer-made"])
    rc = cli.main(["telemetry", "flush"])
    assert rc == 0
    assert "1 event" in capsys.readouterr().out
    tracked = list((env.home / "telemetry").glob("*.jsonl"))
    assert len(tracked) == 1


def test_resolution_verb_flushes_spool_but_never_commits_telemetry(env):
    rid = seed_pending(env)
    cli.main(["telemetry", "note", "offer-made"])
    rc = cli.main(["route", rid])
    assert rc == 0
    # flushed into the tracked plane by the verb...
    tracked = list((env.home / "telemetry").glob("*.jsonl"))
    assert len(tracked) == 1
    # ...but NEVER swept into the verb's surgical commit (11 §4.2)
    assert env.local_subject().startswith(f"self-learn: route {rid}")
    assert not any("telemetry" in p for p in env.committed_paths())


def test_teach_emits_capture_event(env):
    rc = cli.main(
        [
            "teach",
            "--skill",
            "s",
            "--type",
            "behavior",
            "--kind",
            "anti-pattern",
            "--trigger",
            "About to flush a spool file.",
            "--instruction",
            "Truncate in place, never unlink.",
        ]
    )
    assert rc == 0
    # teach is a flushing verb: the capture event is already tracked
    tracked = list((env.home / "telemetry").glob("*.jsonl"))
    assert len(tracked) == 1
    event = json.loads(tracked[0].read_text().splitlines()[0])
    assert event["kind"] == "capture"
    assert event["source"] == "teach"
    assert event["scope"] == "skill:s"
    assert event["record"].startswith("lrn-")


# ------------------------------------------------- teach capture-time flags


def test_teach_capture_time_fields_land_on_record(env, capsys):
    rc = cli.main(
        [
            "teach",
            "--skill",
            "s",
            "--type",
            "behavior",
            "--kind",
            "anti-pattern",
            "--trigger",
            "About to edit .storage while HA is running.",
            "--instruction",
            "Stop the container first.",
            "--verified",
            "--verified-how",
            "repro'd twice",
            "--incident-cost",
            "an evening",
            "--generality",
            "environment-specific",
            "--env",
            "swaync=0.10.2",
            "--env",
            "model=claude-fable-5",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    rid = next(w for w in out.split() if w.startswith("lrn-"))
    record = Record.from_path(
        env.home / "skills" / "s" / "pending" / f"{rid}.md"
    )
    assert record.verified is True
    assert record.verified_how == "repro'd twice"
    assert record.incident_cost == "an evening"
    assert record.generality == "environment-specific"
    assert record.env == {"swaync": "0.10.2", "model": "claude-fable-5"}


def test_teach_verified_how_needs_verified(env, capsys):
    rc = cli.main(
        ["teach", "--skill", "s", "--type", "knowledge", "--fact", "A fact.",
         "--verified-how", "orphan"]
    )
    assert rc == 64
    assert "--verified" in capsys.readouterr().err


def test_teach_env_needs_key_value(env, capsys):
    rc = cli.main(
        ["teach", "--skill", "s", "--type", "knowledge", "--fact", "A fact.",
         "--env", "swaync"]
    )
    assert rc == 64
    assert "COMPONENT=VERSION" in capsys.readouterr().err


# ----------------------------------------------------------------- report


def test_report_text_carries_honesty_labels(env, capsys):
    rid = seed_pending(env)
    assert cli.main(["route", rid, "--follow-up", "upgrade-to-hook"]) == 0
    cli.main(["telemetry", "note", "offer-declined", "--reason", "later"])
    capsys.readouterr()
    rc = cli.main(["report"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "LOWER bound" in out
    assert "CEILING" in out
    assert "NOT dead weight" in out
    assert "upgrade-to-hook" in out
    assert rid in out


def test_report_json_shape(env, capsys):
    rid = seed_pending(env)
    assert cli.main(["route", rid]) == 0
    capsys.readouterr()
    rc = cli.main(["report", "--json"])
    assert rc == 0
    facts = json.loads(capsys.readouterr().out)
    assert facts["routed_ever"] == 1
    assert facts["destinations"] == {"skill-md": 1}
    assert facts["telemetry"]["captures"] == 0
    assert facts["open_followups"] == []


def test_report_flushes_spool_first(env, capsys):
    cli.main(["telemetry", "note", "offer-made"])
    capsys.readouterr()
    rc = cli.main(["report", "--json"])
    assert rc == 0
    facts = json.loads(capsys.readouterr().out)
    assert facts["telemetry"]["events_by_kind"].get("offer-made") == 1


def test_selftest_ignores_telemetry_files(env):
    rid = seed_pending(env)
    assert cli.main(["route", rid]) == 0
    cli.main(["telemetry", "note", "offer-made"])
    assert cli.main(["telemetry", "flush"]) == 0
    assert cli.main(["--selftest"]) == 9
    # and the queue/status paths never mistake telemetry lines for records
    assert cli.main(["list", "--json"]) == 0
