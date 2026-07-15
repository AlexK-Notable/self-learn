"""T16 collapse verb + 11 §2.5 rider verbs (confirm-recurrence,
confirm-held, link contradicts) + the proposal `contradicts:` field.
"""

import json
import subprocess

import pytest

from self_learn import cli, telemetry, verbs
from self_learn.ledger_ops import (
    ProposalError,
    create_record,
    validate_proposal,
    write_proposal,
)
from self_learn.records import Record
from support import (
    commit_all,
    git,
    make_behavior,
    make_home,
    merge_proposal_text,
    proposal_dict,
)

SKILL_MD = "# s skill\n\nAuthored prose stays put.\n"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


class Env:
    def __init__(self, tmp_path):
        self.home = make_home(tmp_path)
        self.skill_dir = self.home / "plugins" / "s-plugin" / "skills" / "s"
        self.skill_md = self.skill_dir / "SKILL.md"
        self.skill_md.write_text(SKILL_MD, encoding="utf-8")
        self.bare = tmp_path / "remote.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.bare)],
            check=True,
        )
        git(self.home, "remote", "add", "origin", str(self.bare))
        commit_all(self.home, "seed")
        git(self.home, "push", "-q", "-u", "origin", "main")
        self.ledger = self.skill_dir / ".self-learn"

    def subject(self):
        return git(self.home, "log", "-1", "--format=%s").stdout.strip()

    def commits_since_seed(self):
        return int(
            git(self.home, "rev-list", "--count", "HEAD", "^HEAD~1").stdout.strip()
        )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


SURVIVOR = "lrn-0000aaaa"
LOSER = "lrn-0000bbbb"
CLUSTER = "merge-0000cccc"


def seed_cluster(env):
    a = make_behavior(record_id=SURVIVOR, trigger="Editing .storage live.")
    b = make_behavior(record_id=LOSER, trigger="Editing .storage while HA runs.")
    create_record(env.home, a)
    create_record(env.home, b)
    # loser carries evidence + its own analysis proposal (both must be
    # cleaned up by the collapse)
    lpath = env.ledger / "pending" / f"{LOSER}.md"
    lrec = Record.from_path(lpath)
    lrec.append_evidence({"session": "sess-b", "ts": "2026-07-14T00:00:00Z"})
    lrec.write(lpath)
    write_proposal(env.home, SURVIVOR, proposal_dict())
    write_proposal(env.home, LOSER, proposal_dict())
    (env.ledger / "proposals" / f"{CLUSTER}.yaml").write_text(
        merge_proposal_text(CLUSTER, [SURVIVOR, LOSER], SURVIVOR),
        encoding="utf-8",
    )
    commit_all(env.home, "cluster seeded")


# ----------------------------------------------------------------- collapse


def test_collapse_one_commit_full_mechanics(env):
    seed_cluster(env)
    head_before = git(env.home, "rev-parse", "HEAD").stdout.strip()
    rc = cli.main(["route", SURVIVOR, "--collapse", CLUSTER, "--no-push"])
    assert rc == 0

    # pinned commit-message shape, ONE commit
    assert env.subject() == (
        f"self-learn: route {SURVIVOR} → skill-md "
        f"(collapse {CLUSTER}, supersedes {LOSER})"
    )
    count = git(
        env.home, "rev-list", "--count", f"{head_before}..HEAD"
    ).stdout.strip()
    assert count == "1"

    # survivor routed with merged evidence + cluster sightings
    survivor = Record.from_path(env.ledger / "resolved" / f"{SURVIVOR}.md")
    assert survivor.status == "routed"
    assert survivor.sightings == 2
    assert any(e.get("session") == "sess-b" for e in survivor.evidence)

    # loser superseded by the survivor, in resolved/
    loser = Record.from_path(env.ledger / "resolved" / f"{LOSER}.md")
    assert loser.status == "superseded"
    assert loser.superseded_by == SURVIVOR

    # merge proposal + both analysis proposals gone
    pdir = env.ledger / "proposals"
    assert not list(pdir.glob("*.yaml"))

    # compiled target carries the survivor's rule (trigger-first form)
    assert "editing .storage live" in env.skill_md.read_text(encoding="utf-8")


def test_collapse_invalidated_cluster_refused(env):
    seed_cluster(env)
    assert cli.main(["reject", LOSER, "--no-push"]) == 0  # member resolves first
    rc = cli.main(["route", SURVIVOR, "--collapse", CLUSTER, "--no-push"])
    assert rc == 1  # VerbError: invalidated


def test_collapse_survivor_must_be_member(env):
    seed_cluster(env)
    outsider = "lrn-0000dddd"
    create_record(env.home, make_behavior(record_id=outsider))
    write_proposal(env.home, outsider, proposal_dict())
    commit_all(env.home, "outsider")
    with pytest.raises(verbs.VerbError, match="not a member"):
        verbs.route(env.home, outsider, collapse=CLUSTER, no_push=True)


# ------------------------------------------------------ proposal contradicts


def test_proposal_contradicts_field_validates():
    validate_proposal(proposal_dict(contradicts=["lrn-889241d9", "chezmoi/SKILL.md#cd"]))
    with pytest.raises(ProposalError, match="contradicts"):
        validate_proposal(proposal_dict(contradicts=[]))
    with pytest.raises(ProposalError, match="contradicts"):
        validate_proposal(proposal_dict(contradicts=["  "]))


# --------------------------------------------------------------- rider verbs


def seed_routed(env, rid="lrn-0000aaaa"):
    create_record(env.home, make_behavior(record_id=rid))
    write_proposal(env.home, rid, proposal_dict())
    commit_all(env.home, "pending")
    assert cli.main(["route", rid, "--no-push"]) == 0
    return rid


def spool_suspect(env, routed, origin="lrn-0000eeee"):
    telemetry.spool_event(
        "recurrence-suspect", record=routed, origin=origin, basis="origin-match"
    )
    telemetry.flush(env.home)
    event = next(
        e
        for e in telemetry.read_events(env.home)
        if e["kind"] == "recurrence-suspect"
    )
    return event["nonce"]


def test_confirm_recurrence_copies_event_facts(env):
    rid = seed_routed(env)
    nonce = spool_suspect(env, rid)
    rc = cli.main(
        ["confirm-recurrence", rid, "--event", nonce, "--no-push"]
    )
    assert rc == 0
    assert env.subject() == f"self-learn: recurrence confirmed on {rid}"
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    assert len(record.recurrences) == 1
    entry = record.recurrences[0]
    assert entry["origin"] == "lrn-0000eeee"
    assert entry["ref"] == nonce
    assert entry["ts"]  # copied from the event — the record stands alone


def test_confirm_recurrence_tolerate_needs_note(env):
    rid = seed_routed(env)
    nonce = spool_suspect(env, rid)
    with pytest.raises(verbs.VerbError, match="--tolerate needs --note"):
        verbs.confirm_recurrence(
            env.home, rid, event_ref=nonce, tolerate=True, no_push=True
        )
    result = verbs.confirm_recurrence(
        env.home,
        rid,
        event_ref=nonce,
        tolerate=True,
        note="the rule stays; recurrence was a stale session",
        no_push=True,
    )
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    # tolerate-why lives in recurrences[].note, NEVER resolution_note
    assert record.recurrences[0]["note"].startswith("the rule stays")
    assert record.resolution_note is None


def test_confirm_recurrence_unknown_event_refused(env):
    rid = seed_routed(env)
    with pytest.raises(verbs.VerbError, match="no recurrence-suspect event"):
        verbs.confirm_recurrence(env.home, rid, event_ref="deadbeef", no_push=True)


def test_confirm_held_writes_last_confirmed(env):
    rid = seed_routed(env)
    rc = cli.main(["confirm-held", rid, "--no-push"])
    assert rc == 0
    assert env.subject() == f"self-learn: confirmed holding {rid}"
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    assert record.last_confirmed is not None


def test_confirm_held_refuses_non_routed(env):
    rid = seed_routed(env)
    assert cli.main(["graduate", rid, "--no-push"]) == 0
    rc = cli.main(["confirm-held", rid, "--no-push"])
    assert rc == 1


def test_link_contradicts_appends_edge(env):
    rid = seed_routed(env)
    rc = cli.main(
        ["link", "contradicts", rid, "chezmoi/SKILL.md#cd-rule", "--no-push"]
    )
    assert rc == 0
    assert env.subject() == (
        f"self-learn: link {rid} contradicts chezmoi/SKILL.md#cd-rule"
    )
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    assert record.contradicts == ("chezmoi/SKILL.md#cd-rule",)
    # duplicate edge refused
    rc = cli.main(
        ["link", "contradicts", rid, "chezmoi/SKILL.md#cd-rule", "--no-push"]
    )
    assert rc == 1


def test_report_lists_recurrence_and_contradiction_state(env, capsys):
    rid = seed_routed(env)
    nonce = spool_suspect(env, rid)
    assert cli.main(["confirm-recurrence", rid, "--event", nonce, "--no-push"]) == 0
    capsys.readouterr()
    assert cli.main(["report", "--json"]) == 0
    facts = json.loads(capsys.readouterr().out)
    live = [r for r in facts["routed_live"] if r["id"] == rid]
    assert live and live[0]["recurrences"] == 1
