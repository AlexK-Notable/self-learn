"""U-dismiss — the `dismiss-suspect` verb (11 §2.2; spec
docs/specs/self-learn/drafts/u-dismiss-false-recurrence-spec.md).

The third door out of `report --json`'s `recurrence_suspects` block: a
human judges a recurrence-suspect telemetry claim to be a matcher
false-positive and clears it WITHOUT overstating a real recurrence and
WITHOUT deleting the underlying telemetry event (append-only, preserved
as analyst fuel — `basis × why` is the contingency table §2.4 needs).

Covers (§11 of the spec, all 24 tests that land in this file —
T-SHIPPED-NOT-ROUTED-GUARD lives in test_m2_verbs.py beside the sibling
`confirm_recurrence` tests, per §13 N1):

- the record-layer mechanism: `dismissed_suspects[]` append-only list,
  `ref` REQUIRED (§4.3 asymmetry with `recurrences[]`), the CLI `--why`
  enum vs the record validator's non-empty-string check (§5)
- every refusal in verbs.dismiss_suspect's step order (§6.3) and its exit
  code (§8): unknown event, cross-record event, non-routed record,
  already-confirmed, already-dismissed, secret scan, unknown id, no home
- the §6.4 deliberate directional guard asymmetry (dismiss refuses an
  already-confirmed nonce; confirm does NOT refuse an already-dismissed
  one)
- the report surface (§7): the `recurrence_suspects` filter clause, the
  `routed_live[].dismissed_suspects` count, and the NEW top-level
  `suspects_dismissed` facts key — including that it survives the target
  record later being superseded (§7c's load-bearing placement)

All ledger homes are throwaway sandbox repos under pytest tmpdirs
(`support.make_env`) — never the real `~/.self-learn`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from self_learn import cli, telemetry, verbs
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record, ValidationError
from self_learn.report import gather
from support import (
    commit_all,
    git,
    make_behavior,
    make_env,
    proposal_dict,
    verb_subject,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


class Env:
    """doc-13 pair: `home` is the LEDGER; `ledger` is its skill:s bucket."""

    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir
        self.skill_md = sandbox.skill_md
        self.ledger = self.home / "skills" / "s"

    def subject(self):
        return verb_subject(self.home)  # newest non-telemetry-flush commit


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


def seed_routed(env, rid="lrn-0000aaaa"):
    create_record(env.home, make_behavior(record_id=rid))
    write_proposal(env.home, rid, proposal_dict())
    commit_all(env.home, "pending")
    assert cli.main(["route", rid, "--no-push"]) == 0
    return rid


def spool_suspect(env, routed_id, *, origin="lrn-0000eeee", basis="miner-match", now=None):
    """Spool + flush ONE new recurrence-suspect event and return its
    (nonce, ts) — set-difference on the nonce so a SECOND call on the
    same record returns the newly-spooled event, not the first one
    found (nonces are random per event, `telemetry.py`'s uniqueness
    guarantee)."""
    before = {
        e["nonce"]
        for e in telemetry.read_events(env.home)
        if e.get("kind") == "recurrence-suspect"
    }
    telemetry.spool_event(
        "recurrence-suspect", record=routed_id, origin=origin, basis=basis, now=now
    )
    telemetry.flush(env.home)
    event = next(
        e
        for e in telemetry.read_events(env.home)
        if e.get("kind") == "recurrence-suspect" and e["nonce"] not in before
    )
    return event["nonce"], event["ts"]


# ------------------------------------------------------------- T-CLEARS


def test_clears_the_recurrence_suspects_row(env):
    rid = seed_routed(env)
    nonce, _ts = spool_suspect(env, rid)
    rc = cli.main(
        ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
    )
    assert rc == 0
    assert gather(env.home)["recurrence_suspects"] == []


# ------------------------------------------ T-SECOND-SIGHTING-SURVIVES


def test_second_sighting_survives_a_dismissal(env):
    rid = seed_routed(env)
    nonce1, _ = spool_suspect(env, rid, origin="lrn-0000eeee")
    nonce2, _ = spool_suspect(env, rid, origin="lrn-0000ffff")
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce1, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    rows = gather(env.home)["recurrence_suspects"]
    assert [r["nonce"] for r in rows] == [nonce2]


# ------------------------------------------------------- T-ENTRY-SHAPE


def test_entry_shape_carries_the_events_facts_not_now(env):
    rid = seed_routed(env)
    nonce, ts = spool_suspect(env, rid, origin="lrn-0000eeee", basis="fire-violated")
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    entry = record.dismissed_suspects[0]
    assert entry["ref"] == nonce
    assert entry["ts"] == ts
    assert entry["origin"] == "lrn-0000eeee"
    assert entry["basis"] == "fire-violated"
    assert entry["why"] == "rule-followed"
    assert entry["dismissed_at"]


# ------------------------------------------------------- T-BASIS-COPIED


def test_basis_is_copied_for_a_non_default_value(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid, basis="fire-violated")
    assert (
        cli.main(
            [
                "dismiss-suspect",
                rid,
                "--event",
                nonce,
                "--why",
                "unrelated",
                "--no-push",
            ]
        )
        == 0
    )
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    assert record.dismissed_suspects[0]["basis"] == "fire-violated"


# --------------------------------------------------------- T-TWO-CLOCKS


def test_dismissed_at_and_ts_are_two_different_clocks(env):
    rid = seed_routed(env)
    past = datetime.now(timezone.utc) - timedelta(days=5)
    nonce, ts = spool_suspect(env, rid, now=past)
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    entry = record.dismissed_suspects[0]
    assert entry["ts"] == ts
    today = datetime.now(timezone.utc).date().isoformat()
    assert entry["dismissed_at"] == today
    assert entry["dismissed_at"] != ts[:10]


# --------------------------------------------------- T-NOT-A-RECURRENCE


def test_dismissal_is_not_a_recurrence(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    assert record.recurrences == ()
    assert record.resolution_note is None


# ------------------------------------------------------ T-DOUBLE-DISMISS


def test_double_dismiss_refused(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    rc = cli.main(
        ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
    )
    assert rc == 1
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    assert len(record.dismissed_suspects) == 1


# ----------------------------------------------- T-CONFIRMED-THEN-DISMISS


def test_confirmed_then_dismiss_refused(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    assert cli.main(["confirm-recurrence", rid, "--event", nonce, "--no-push"]) == 0
    rc = cli.main(
        ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
    )
    assert rc == 1
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    assert record.dismissed_suspects == ()


# ----------------------------------------------- T-DISMISSED-THEN-CONFIRM


def test_dismissed_then_confirm_allowed(env):
    """§6.4's deliberate directional asymmetry: dismissal refuses an
    already-confirmed nonce, but confirmation does NOT refuse an
    already-dismissed one — dismissal is cheap/reversible-by-confirm,
    confirmation is the expensive action that may override it."""
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    rc = cli.main(["confirm-recurrence", rid, "--event", nonce, "--no-push"])
    assert rc == 0
    assert gather(env.home)["recurrence_suspects"] == []


# ----------------------------------------------------------- T-NOT-ROUTED


def test_not_routed_refused(env, capsys):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    assert cli.main(["graduate", rid, "--no-push"]) == 0
    capsys.readouterr()
    rc = cli.main(
        ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
    )
    assert rc == 1
    assert "suspects only exist against LIVE routed coverage" in capsys.readouterr().err


# ------------------------------------------------------- T-UNKNOWN-EVENT


def test_unknown_event_refused(env):
    rid = seed_routed(env)
    with pytest.raises(verbs.VerbError, match="no recurrence-suspect event"):
        verbs.dismiss_suspect(
            env.home, rid, event_ref="deadbeef", why="rule-followed", no_push=True
        )


# ------------------------------------------------------- T-EVENT-BELONGS


def test_event_belonging_to_a_different_record_refused(env):
    rid_a = seed_routed(env, rid="lrn-0000aaaa")
    rid_b = seed_routed(env, rid="lrn-0000bbbb")
    nonce, _ = spool_suspect(env, rid_b)
    rc = cli.main(
        ["dismiss-suspect", rid_a, "--event", nonce, "--why", "rule-followed", "--no-push"]
    )
    assert rc == 1
    record_a = Record.from_path(env.ledger / "resolved" / f"{rid_a}.md")
    assert record_a.dismissed_suspects == ()


# -------------------------------------------------------- T-WHY-REQUIRED


def test_why_is_required(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    rc = cli.main(["dismiss-suspect", rid, "--event", nonce, "--no-push"])
    assert rc == 2


# ------------------------------------------------------------ T-WHY-ENUM


def test_why_enum_rejects_unknown_accepts_every_live_value(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    rc = cli.main(
        ["dismiss-suspect", rid, "--event", nonce, "--why", "banana", "--no-push"]
    )
    assert rc == 2
    for reason in verbs.DISMISS_REASONS:
        nonce, _ = spool_suspect(env, rid)
        rc = cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", reason, "--no-push"]
        )
        assert rc == 0


# -------------------------------------------------------- T-VALIDATOR-REF


def test_validator_requires_ref():
    r = make_behavior()
    with pytest.raises(ValidationError, match="ref"):
        r.append_dismissed_suspect(
            {"ts": "2026-08-19T10:39:13Z", "why": "rule-followed"}
        )
    r.append_dismissed_suspect(
        {"ref": "b68b5811", "ts": "2026-08-19T10:39:13Z", "why": "rule-followed"}
    )
    assert len(r.dismissed_suspects) == 1


# --------------------------------------------------------------- T-SUBJECT


def test_commit_subject_pinned(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    assert env.subject() == f"self-learn: suspect dismissed on {rid}"


# ---------------------------------------------------- T-SCAN-BEFORE-WRITE


def test_secret_in_note_refuses_before_any_write(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    head_before = git(env.home, "rev-parse", "HEAD").stdout.strip()
    rc = cli.main(
        [
            "dismiss-suspect",
            rid,
            "--event",
            nonce,
            "--why",
            "rule-followed",
            "--note",
            "key is ghp_" + "a" * 36,
            "--no-push",
        ]
    )
    assert rc == 1
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    assert record.dismissed_suspects == ()
    assert git(env.home, "rev-parse", "HEAD").stdout.strip() == head_before


# ----------------------------------------------------- T-EVENT-PRESERVED


def test_event_preserved_byte_for_byte(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    suspect_before = next(
        e
        for e in telemetry.read_events(env.home)
        if e["kind"] == "recurrence-suspect"
    )
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    suspect_after = next(
        e
        for e in telemetry.read_events(env.home)
        if e["kind"] == "recurrence-suspect"
    )
    assert suspect_after == suspect_before


# ---------------------------------------------------------- T-UNKNOWN-ID


def test_unknown_record_id_exits_64(env):
    telemetry.spool_event(
        "recurrence-suspect",
        record="lrn-deadbeef",
        origin="lrn-0000eeee",
        basis="miner-match",
    )
    telemetry.flush(env.home)
    event = next(
        e
        for e in telemetry.read_events(env.home)
        if e["kind"] == "recurrence-suspect"
    )
    rc = cli.main(
        [
            "dismiss-suspect",
            "lrn-deadbeef",
            "--event",
            event["nonce"],
            "--why",
            "rule-followed",
            "--no-push",
        ]
    )
    assert rc == 64


# -------------------------------------------------------------- T-NO-HOME


def test_no_home_exits_5(tmp_path, monkeypatch):
    missing = tmp_path / "not-a-repo"
    monkeypatch.setenv("SELF_LEARN_HOME", str(missing))
    rc = cli.main(
        [
            "dismiss-suspect",
            "lrn-00000000",
            "--event",
            "deadbeef",
            "--why",
            "rule-followed",
            "--no-push",
        ]
    )
    assert rc == 5
    assert not missing.exists()


# -------------------------------------------------- T-ROUTED-LIVE-COUNT


def test_routed_live_count_increments(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    facts = gather(env.home)
    row = next(r for r in facts["routed_live"] if r["id"] == rid)
    assert row["dismissed_suspects"] == 1


# ------------------------------------------ T-DISMISSALS-SURVIVE-SUPERSEDE


def test_dismissals_survive_supersession(env):
    rid = seed_routed(env)
    nonce, _ = spool_suspect(env, rid)
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    successor = "lrn-0000cccc"
    create_record(env.home, make_behavior(record_id=successor))
    commit_all(env.home, "successor pending")
    assert cli.main(["supersede", rid, successor, "--no-push"]) == 0
    facts = gather(env.home)
    rows = [r for r in facts["suspects_dismissed"] if r["id"] == rid]
    assert len(rows) == 1
    assert rows[0]["ref"] == nonce


# -------------------------------------------------------- T-REPORT-JSON


def test_report_json_carries_suspects_dismissed(env, capsys):
    rid = seed_routed(env)
    nonce, ts = spool_suspect(env, rid, basis="miner-match")
    assert (
        cli.main(
            ["dismiss-suspect", rid, "--event", nonce, "--why", "rule-followed", "--no-push"]
        )
        == 0
    )
    capsys.readouterr()  # discard dismiss-suspect's own stdout
    rc = cli.main(["report", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    rows = [r for r in payload["suspects_dismissed"] if r["id"] == rid]
    assert len(rows) == 1
    row = rows[0]
    assert row["ref"] == nonce
    assert row["ts"] == ts
    assert row["basis"] == "miner-match"
    assert row["why"] == "rule-followed"
    assert row["dismissed_at"]


# ------------------------------------------------- T-OLD-RECORD-STILL-VALID


def test_old_record_without_dismissed_suspects_key_stays_valid():
    r = make_behavior()
    assert r.dismissed_suspects == ()
    reparsed = Record.from_text(r.to_text())
    assert reparsed.dismissed_suspects == ()
