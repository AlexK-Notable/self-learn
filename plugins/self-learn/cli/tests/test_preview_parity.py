"""S-71 §6: `batch.dry_run` checks what the verb checks.

The preview calls each verb's OWN pre-lock checks (`verbs._preflight_*`,
plus the later checks the verb runs from the same functions: `defer`'s
date, a retirement's host-side preflight), never a second copy. This file
is the parity table: every row sets up a scratch ledger on which the REAL
verb refuses. For every row, `batch.dry_run` on the untouched ledger says
`would-refuse` with the same words and the same kind, and then `batch.run`
refuses with them.

All ledger homes are throwaway sandbox repos under pytest tmpdirs
(`support.make_env`), never the real `~/.self-learn`.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Callable

import pytest
from ruamel.yaml import YAML

from self_learn import batch, cases, telemetry, verbs
from self_learn.ledger_ops import create_record, find_record_path, write_proposal
from self_learn.records import Record
from support import commit_all, make_behavior, make_env, proposal_dict


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


A = "lrn-e0000001"
B = "lrn-e0000002"
MISSING = "lrn-e0ffffff"
SECRET = "key is ghp_" + "c" * 36


# --------------------------------------------------------------- setup


def _pending(env, rid, *, record=None):
    create_record(env.ledger, record or make_behavior(record_id=rid, scope="skill:s"))
    write_proposal(env.ledger, rid, proposal_dict(scope="skill:s"))
    commit_all(env.ledger, f"seed {rid}")
    return rid


def _routed(env, rid):
    _pending(env, rid)
    verbs.route(env.ledger, rid, dest="skill-md", no_push=True)
    return rid


def _rejected(env, rid):
    _pending(env, rid)
    verbs.reject(env.ledger, rid, no_push=True)
    return rid


def _dirty_skill_md(env):
    env.skill_md.write_text(
        env.skill_md.read_text(encoding="utf-8") + "\nan edit nobody committed\n",
        encoding="utf-8",
    )


def _suspect(env, record, origin="lrn-e00000ee"):
    before = {
        e["nonce"] for e in telemetry.read_events(env.ledger)
        if e.get("kind") == "recurrence-suspect"
    }
    telemetry.spool_event(
        "recurrence-suspect", record=record, origin=origin, basis="miner-match"
    )
    telemetry.flush(env.ledger)
    return next(
        e["nonce"] for e in telemetry.read_events(env.ledger)
        if e.get("kind") == "recurrence-suspect" and e["nonce"] not in before
    )


def _clash(env, rid, to):
    """A same-id file already in the move's target bucket, under
    `resolved/` so `find_record_path` (pending first) still finds the real
    source record."""
    _scope, bucket, _project = verbs._resolve_move_target(env.ledger, to)
    clash = bucket / "resolved" / f"{rid}.md"
    clash.parent.mkdir(parents=True, exist_ok=True)
    clash.write_text("imposter\n", encoding="utf-8")


# ---------------------------------------------------------------- rows


@dataclass
class Row:
    id: str
    setup: Callable  # (env) -> dict of sheet item fields
    fragment: str
    kind: str


def _secret_rows():
    return [
        Row("route-secret-in-note",
            lambda e: {"id": _pending(e, A), "verb": "route", "dest": "skill-md",
                       "note": SECRET},
            "secret scan hit", "bad-line"),
        Row("reject-secret-in-note",
            lambda e: {"id": _pending(e, A), "verb": "reject", "note": SECRET},
            "secret scan hit", "bad-line"),
        Row("retire-secret-in-note",
            lambda e: {"id": _pending(e, A), "verb": "retire",
                       "covered_by": "skill-md:s", "note": SECRET},
            "secret scan hit", "bad-line"),
        Row("supersede-secret-in-note",
            lambda e: {"id": _pending(e, A), "verb": "supersede",
                       "new_id": _pending(e, B), "note": SECRET},
            "secret scan hit", "bad-line"),
        Row("rehome-secret-in-note",
            lambda e: {"id": _pending(e, A), "verb": "rehome", "to": str(e.host),
                       "note": SECRET},
            "secret scan hit", "bad-line"),
        Row("note-secret-in-append",
            lambda e: {"id": _pending(e, A), "verb": "note", "append": SECRET},
            "secret scan hit", "bad-line"),
        Row("revise-secret-in-text",
            lambda e: {"id": _pending(e, A), "verb": "revise", "section": "Trigger",
                       "text": SECRET, "because": "clearer"},
            "secret scan hit", "bad-line"),
        Row("revise-secret-in-because",
            lambda e: {"id": _pending(e, A), "verb": "revise", "section": "Trigger",
                       "text": "A clearer trigger.", "because": SECRET},
            "secret scan hit", "bad-line"),
        Row("link-contradicts-secret-in-target",
            lambda e: {"id": _pending(e, A), "verb": "link-contradicts",
                       "target": SECRET},
            "secret scan hit in the contradicts target", "bad-line"),
        Row("confirm-held-secret-in-note",
            lambda e: {"id": _routed(e, A), "verb": "confirm-held", "note": SECRET},
            "secret scan hit", "bad-line"),
    ]


def _supersede_rows():
    def cycle(e):
        _pending(e, A)
        rec = make_behavior(record_id=B, scope="skill:s")
        rec.set_superseded_by(A)  # a stale pointer on a live record (hand edit)
        _pending(e, B, record=rec)
        return {"id": A, "verb": "supersede", "new_id": B}

    def routed_host_busy(e):
        _routed(e, A)
        _pending(e, B)
        _dirty_skill_md(e)
        return {"id": A, "verb": "supersede", "new_id": B}

    return [
        Row("supersede-self",
            lambda e: {"id": _pending(e, A), "verb": "supersede", "new_id": A},
            "cannot supersede itself", "bad-line"),
        Row("supersede-replacement-missing",
            lambda e: {"id": _pending(e, A), "verb": "supersede", "new_id": MISSING},
            f"record {MISSING} not found", "status"),
        Row("supersede-old-status",
            lambda e: {"id": _rejected(e, A), "verb": "supersede",
                       "new_id": _pending(e, B)},
            f"record {A} is 'rejected'", "status"),
        Row("supersede-new-status",
            lambda e: {"id": _pending(e, A), "verb": "supersede",
                       "new_id": _rejected(e, B)},
            f"record {B} is 'rejected'", "status"),
        Row("supersede-cycle", cycle, "would create a cycle", "bad-line"),
        Row("supersede-routed-retirement-preflight", routed_host_busy,
            verbs.GITOPS_DIRTY_MARKER, "target-busy"),
    ]


def _retire_rows():
    def routed_host_busy(verb, covered_by):
        def setup(e):
            _routed(e, A)
            _dirty_skill_md(e)
            item = {"id": A, "verb": verb}
            if covered_by is not None:
                item["covered_by"] = covered_by
            return item
        return setup

    return [
        Row("retire-covered-by-malformed",
            lambda e: {"id": _pending(e, A), "verb": "retire",
                       "covered_by": "bogus-kind:foo"},
            "unknown coverage kind 'bogus-kind'", "bad-line"),
        Row("retire-routed-retirement-preflight",
            routed_host_busy("retire", "skill-md:s"),
            verbs.GITOPS_DIRTY_MARKER, "target-busy"),
        Row("graduate-routed-retirement-preflight",
            routed_host_busy("graduate", None),
            verbs.GITOPS_DIRTY_MARKER, "target-busy"),
    ]


def _revise_rows():
    def ambiguous(e):
        rec = make_behavior(record_id=A, scope="skill:s")
        _pending(e, A, record=rec)
        path = find_record_path(e.ledger, A)
        text = path.read_text(encoding="utf-8").rstrip("\n")
        path.write_text(text + "\n\n## Aside\none\n\n## Aside\ntwo\n", encoding="utf-8")
        Record.from_path(path)  # still a valid record: `Aside` is not a known section
        commit_all(e.ledger, "two Aside sections")
        return {"id": A, "verb": "revise", "section": "Aside", "text": "three",
                "because": "clearer"}

    return [
        Row("revise-blank-section",
            lambda e: {"id": _pending(e, A), "verb": "revise", "section": "   ",
                       "text": "A clearer trigger.", "because": "clearer"},
            "revise needs --section", "bad-line"),
        Row("revise-heading-in-text",
            lambda e: {"id": _pending(e, A), "verb": "revise", "section": "Trigger",
                       "text": "A trigger.\n## Smuggled\nmore", "because": "clearer"},
            "may not itself contain a '## ' heading", "bad-line"),
        Row("revise-section-missing",
            lambda e: {"id": _pending(e, A), "verb": "revise", "section": "Nope",
                       "text": "x", "because": "clearer"},
            "has no 'Nope' section", "bad-line"),
        Row("revise-section-ambiguous", ambiguous, "ambiguous", "bad-line"),
    ]


def _other_rows():
    def rehome_collision(e):
        _pending(e, A)
        _clash(e, A, str(e.host))
        return {"id": A, "verb": "rehome", "to": str(e.host)}

    def rescope_collision(e):
        _pending(e, A)
        _clash(e, A, "user")
        return {"id": A, "verb": "rescope", "to": "user"}

    def foreign_nonce(verb):
        def setup(e):
            _routed(e, A)
            _routed(e, B)
            item = {"id": A, "verb": verb, "event": _suspect(e, B)}
            if verb == "dismiss-suspect":
                item["why"] = "rule-followed"
            return item
        return setup

    def dismiss_confirmed(e):
        _routed(e, A)
        nonce = _suspect(e, A)
        verbs.confirm_recurrence(e.ledger, A, event_ref=nonce, no_push=True)
        return {"id": A, "verb": "dismiss-suspect", "event": nonce,
                "why": "rule-followed"}

    def reopen_replaced(e):
        _pending(e, A)
        _pending(e, B)
        verbs.supersede(e.ledger, A, B, no_push=True)
        return {"id": A, "verb": "reopen"}

    return [
        Row("defer-until-in-the-past",
            lambda e: {"id": _pending(e, A), "verb": "defer", "until": "2000-01-01"},
            "is in the past", "bad-line"),
        Row("defer-until-not-a-date",
            lambda e: {"id": _pending(e, A), "verb": "defer", "until": "someday"},
            "is not a date", "bad-line"),
        Row("rehome-id-collision", rehome_collision, "already exists in", "needs-person"),
        Row("rescope-id-collision", rescope_collision, "already exists in",
            "needs-person"),
        Row("link-contradicts-self",
            lambda e: {"id": _pending(e, A), "verb": "link-contradicts", "target": A},
            "cannot contradict itself", "bad-line"),
        Row("link-contradicts-target-missing",
            lambda e: {"id": _pending(e, A), "verb": "link-contradicts",
                       "target": MISSING},
            f"record {MISSING} not found", "bad-line"),
        Row("followup-done-none-open",
            lambda e: {"id": _routed(e, A), "verb": "followup-done"},
            "has no open follow-up", "bad-line"),
        Row("confirm-recurrence-unknown-nonce",
            lambda e: {"id": _routed(e, A), "verb": "confirm-recurrence",
                       "event": "nonce-nobody-raised"},
            "no recurrence-suspect event", "bad-line"),
        Row("confirm-recurrence-foreign-nonce", foreign_nonce("confirm-recurrence"),
            "was raised against", "bad-line"),
        Row("dismiss-suspect-unknown-nonce",
            lambda e: {"id": _routed(e, A), "verb": "dismiss-suspect",
                       "event": "nonce-nobody-raised", "why": "rule-followed"},
            "no recurrence-suspect event", "bad-line"),
        Row("dismiss-suspect-foreign-nonce", foreign_nonce("dismiss-suspect"),
            "was raised against", "bad-line"),
        Row("dismiss-suspect-already-confirmed", dismiss_confirmed,
            "cannot dismiss a suspect that was confirmed", "bad-line"),
        Row("reopen-a-replaced-lesson", reopen_replaced,
            "use reconsider instead of reopen", "bad-line"),
        Row("undefer-a-pending-lesson",
            lambda e: {"id": _pending(e, A), "verb": "undefer"},
            f"record {A} is 'pending'", "status"),
        Row("confirm-held-a-pending-lesson",
            lambda e: {"id": _pending(e, A), "verb": "confirm-held"},
            f"record {A} is 'pending'", "status"),
    ]


ROWS = _secret_rows() + _supersede_rows() + _retire_rows() + _revise_rows() + _other_rows()


def _sheet(tmp_path, item, *, case=None):
    lines = [f"  - id: {item.pop('id')}"]
    lines += [f"    {k}: {json.dumps(v)}" for k, v in item.items()]
    head = "version: 1\n" + (f"case: {case}\n" if case else "") + "items:\n"
    path = tmp_path / "sheet.yaml"
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return batch.load_sheet(path)


def _tree_bytes(root):
    """Every file under *root* except git's own bookkeeping (a `git status`
    may refresh the index's stat cache without changing anything)."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


@pytest.mark.parametrize("row", ROWS, ids=[r.id for r in ROWS])
def test_the_preview_refuses_what_the_verb_refuses(tmp_path, monkeypatch, row):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    items = _sheet(tmp_path, row.setup(env))

    before = (_tree_bytes(env.ledger), _tree_bytes(env.host))
    preview = batch.dry_run(env.ledger, items)
    # BAT9: the checks the preview now runs write nothing, ledger or host.
    assert (_tree_bytes(env.ledger), _tree_bytes(env.host)) == before
    (p,) = preview.items
    applied = batch.run(env.ledger, items, no_push=True)
    (r,) = applied.items

    # The verb itself refuses, with these words and this kind ...
    assert r.state == "refused", (r.state, r.detail)
    assert row.fragment in (r.detail or ""), r.detail
    assert r.kind == row.kind, (r.kind, r.detail)
    # ... and the preview, run first on the untouched ledger, said so.
    assert p.state == "would-refuse", (p.state, p.detail)
    assert row.fragment in (p.detail or ""), p.detail
    assert p.kind == r.kind, (p.kind, p.detail)


def test_every_non_route_verb_has_a_preview():
    assert set(batch._PREVIEW_CHECKS) == batch.PERMITTED_VERBS - {"route"}


def test_a_clean_line_previews_would_apply_and_applies(tmp_path, monkeypatch):
    """Positive control for the table: the same setup helpers, a line the
    verb accepts — the preview says `would-apply`, the run applies."""
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    items = _sheet(tmp_path, {"id": _pending(env, A), "verb": "defer",
                              "until": "2999-01-01", "note": "later"})
    (p,) = batch.dry_run(env.ledger, items).items
    assert (p.state, p.kind) == ("would-apply", None), p.detail
    (r,) = batch.run(env.ledger, items, no_push=True).items
    assert r.state == "applied", r.detail


def _seed_case(env, tmp_path, *, records, outcome, kind="resolution", supersedes=None):
    data = {
        "kind": kind,
        "trigger": "reconsider" if kind == "reconsider" else "nightly",
        "outcome": outcome,
        "records": list(records),
        "scope": "skill:s",
        "question": "preview parity test case",
        "evidence": [{"ref": "transcript:paritytest#L1", "quote": "parity quote"}],
        "decision": {"verb": outcome, "because": "parity test", "confidence": "settled"},
    }
    if supersedes is not None:
        data["supersedes"] = supersedes
    stage = tmp_path / f"stage-{kind}-{outcome}.yaml"
    y = YAML(typ="safe")
    y.default_flow_style = False
    buf = io.StringIO()
    y.dump(data, buf)
    stage.write_text(buf.getvalue(), encoding="utf-8")
    return cases.record(env.ledger, stage, actor="steward")


def test_a_reconsider_case_widens_the_preview_exactly_as_it_widens_the_verb(
    tmp_path, monkeypatch
):
    """`reject` of a ROUTED lesson is admitted only under a validated
    reconsider case over it — the preview gets the same `reconsider_case`
    `_dispatch` passes, so it says `would-apply` where the run applies."""
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    _routed(env, A)
    old_case = _seed_case(env, tmp_path, records=[A], outcome="route")
    reconsider = _seed_case(
        env, tmp_path, records=[A], outcome="reject", kind="reconsider",
        supersedes=old_case,
    )
    items = _sheet(
        tmp_path, {"id": A, "verb": "reject", "note": "the route was wrong"},
        case=reconsider,
    )
    (p,) = batch.dry_run(env.ledger, items).items
    assert (p.state, p.kind) == ("would-apply", None), p.detail
    (r,) = batch.run(env.ledger, items, no_push=True).items
    assert r.state == "applied", r.detail
