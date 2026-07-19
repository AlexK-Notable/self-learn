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
    make_env,
    merge_proposal_text,
    proposal_dict,
    verb_subject,
)

SKILL_MD = "# s skill\n\nAuthored prose stays put.\n"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


class Env:
    """doc-13 pair: `home` is the LEDGER; `ledger` is its skill:s bucket;
    canon (skill_md) lives in the paired HOST repo."""

    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir  # HOST skill dir
        self.skill_md = sandbox.skill_md    # make_env seeded identical content
        self.bare = tmp_path / "remote.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.bare)],
            check=True,
        )
        git(self.home, "remote", "add", "origin", str(self.bare))
        git(self.home, "push", "-q", "-u", "origin", "main")
        self.ledger = self.home / "skills" / "s"  # LEDGER skill bucket

    def subject(self):
        return verb_subject(self.home)  # newest non-telemetry-flush commit

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
    # ONE verb commit: the collapse is atomic. Telemetry's own flush
    # commit may ride on top (doc 13 H-5 — audit 2026-07-16 MAJOR 3), so
    # count what the VERB wrote, which is what "one commit" ever meant.
    subjects = git(
        env.home, "log", "--format=%s", f"{head_before}..HEAD"
    ).stdout.splitlines()
    verb_commits = [
        s for s in subjects if not s.startswith("self-learn: telemetry flush")
    ]
    assert len(verb_commits) == 1

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
    # Regression guard (FW-32/Y-23): the contradicts field's validation
    # is untouched by the destination-bounded contradiction rider — only
    # the worker-prompt wording and the doctrine narrowed, never this
    # shape check.
    validate_proposal(proposal_dict(contradicts=["lrn-889241d9", "chezmoi/SKILL.md#cd"]))
    with pytest.raises(ProposalError, match="contradicts"):
        validate_proposal(proposal_dict(contradicts=[]))
    with pytest.raises(ProposalError, match="contradicts"):
        validate_proposal(proposal_dict(contradicts=["  "]))


# ------------------------------------------------------------ proposal lint


def test_proposal_lint_field_well_formed_validates():
    validate_proposal(
        proposal_dict(
            lint={
                "trigger_recognizable": "partial",
                "why_present": True,
                "sharpening": "name the .storage/*.json glob, not 'HA files'",
            }
        )
    )


def test_proposal_lint_absent_stays_valid():
    validate_proposal(proposal_dict())  # no `lint` key at all — baseline sane


def test_proposal_lint_sharpening_is_optional():
    validate_proposal(
        proposal_dict(lint={"trigger_recognizable": "yes", "why_present": True})
    )


def test_proposal_lint_rejects_non_mapping():
    with pytest.raises(ProposalError, match="lint must be a mapping"):
        validate_proposal(proposal_dict(lint="partial"))


def test_proposal_lint_rejects_enum_out_of_set():
    with pytest.raises(ProposalError, match="trigger_recognizable"):
        validate_proposal(
            proposal_dict(lint={"trigger_recognizable": "maybe", "why_present": True})
        )


def test_proposal_lint_rejects_non_bool_why_present():
    with pytest.raises(ProposalError, match="why_present"):
        validate_proposal(
            proposal_dict(lint={"trigger_recognizable": "yes", "why_present": "true"})
        )


def test_proposal_lint_rejects_empty_sharpening():
    with pytest.raises(ProposalError, match="sharpening"):
        validate_proposal(
            proposal_dict(
                lint={
                    "trigger_recognizable": "yes",
                    "why_present": True,
                    "sharpening": "   ",
                }
            )
        )


def test_proposal_lint_rejects_non_string_sharpening():
    with pytest.raises(ProposalError, match="sharpening"):
        validate_proposal(
            proposal_dict(
                lint={
                    "trigger_recognizable": "no",
                    "why_present": False,
                    "sharpening": 3,
                }
            )
        )


def test_reasoning_pattern_record_with_soft_trigger_lint_is_not_rejected():
    """Kind-aware MUST (routing-doctrine.md §9): a `kind:
    reasoning-pattern` record's inherent trigger softness is never a
    route-blocker signal — lint is advisory only and no code path
    inspects record kind to escalate a lint verdict. A `trigger_
    recognizable: partial` judgment on a reasoning-pattern record
    validates exactly like it would on any other record; the non-punitive
    framing rule itself lives in doctrine text (asserted in
    test_worker.py's doctrine-content tests), never enforced here."""
    record = Record.create(
        type="behavior",
        scope="skill:s",
        source="teach",
        kind="reasoning-pattern",
        trigger="When deciding how to route ambiguous work.",
        instruction=(
            "Prefer the narrowest surface that still fires — recognizing "
            "'ambiguous work' takes judgment, not a fixed pattern."
        ),
    )
    assert record.kind == "reasoning-pattern"
    validate_proposal(
        proposal_dict(
            lint={
                "trigger_recognizable": "partial",
                "why_present": True,
            }
        )
    )


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


# ------------------------------------------- audit 2026-07-15 regressions


def test_collapse_abort_leaves_pending_pristine_then_retry_clean(env):
    """The blocker: a routine DirtyTargetError abort must leave the
    survivor's pending file UNTOUCHED (the old pre-write left a
    half-merged file that autosync published, and the prescribed retry
    double-merged: sightings 3-for-2, duplicated evidence)."""
    seed_cluster(env)
    env.skill_md.write_text(SKILL_MD + "\nunrelated drift\n", encoding="utf-8")
    rc = cli.main(["route", SURVIVOR, "--collapse", CLUSTER, "--no-push"])
    assert rc == 1  # dirty target refused

    pristine = Record.from_path(env.ledger / "pending" / f"{SURVIVOR}.md")
    assert pristine.sightings == 1
    assert not any(e.get("session") == "sess-b" for e in pristine.evidence)
    assert not any(e.get("merged_from") for e in pristine.evidence)

    # the documented recovery: clean the target, re-run — exactly once
    # merged. The dirty target lives in the HOST repo now (doc 13 §4).
    commit_all(env.host, "commit the drift")
    rc = cli.main(["route", SURVIVOR, "--collapse", CLUSTER, "--no-push"])
    assert rc == 0
    survivor = Record.from_path(env.ledger / "resolved" / f"{SURVIVOR}.md")
    assert survivor.sightings == 2
    assert sum(1 for e in survivor.evidence if e.get("session") == "sess-b") == 1
    assert sum(1 for e in survivor.evidence if e.get("merged_from") == LOSER) == 1


def test_confirm_same_event_twice_refused(env):
    rid = seed_routed(env)
    nonce = spool_suspect(env, rid)
    assert cli.main(["confirm-recurrence", rid, "--event", nonce, "--no-push"]) == 0
    rc = cli.main(["confirm-recurrence", rid, "--event", nonce, "--no-push"])
    assert rc == 1  # double-confirm would overstate recurrence pressure
    record = Record.from_path(env.ledger / "resolved" / f"{rid}.md")
    assert len(record.recurrences) == 1


def test_link_contradicts_self_and_missing_target_refused(env, capsys):
    rid = seed_routed(env)
    rc = cli.main(["link", "contradicts", rid, rid, "--no-push"])
    assert rc == 1
    assert "itself" in capsys.readouterr().err
    rc = cli.main(["link", "contradicts", rid, "lrn-99999999", "--no-push"])
    assert rc == 64  # record-id target must exist (unknown id = usage)
