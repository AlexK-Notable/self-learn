"""2026-09-26 (agenda item 14, N6): dismiss-suspect writes `why` into the
record, so it is secret-scanned like every other written free text -- in
the verb and in `batch.dry_run` alike (the parity rows
`dismiss-suspect-secret-in-*` in test_preview_parity.py), with no bypass.

Sandbox ledgers under pytest's tmpdir only (`support.make_env`).
"""

from __future__ import annotations

import pytest

from self_learn import batch, verbs
from self_learn.ledger_ops import find_record_path
from self_learn.records import Record
from support import make_env
from test_preview_parity import SECRET, _routed, _sheet, _suspect, _tree_bytes


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


A = "lrn-e1000001"


def test_the_verb_refuses_a_secret_in_why_and_writes_nothing(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    _routed(env, A)
    nonce = _suspect(env, A)
    before = _tree_bytes(env.ledger)

    with pytest.raises(verbs.SecretRefusal) as caught:
        verbs.dismiss_suspect(env.ledger, A, event_ref=nonce, why=SECRET, no_push=True)

    assert "--why:" in str(caught.value) and "github-token" in str(caught.value)
    assert caught.value.where == "item"
    assert _tree_bytes(env.ledger) == before
    assert Record.from_path(find_record_path(env.ledger, A)).dismissed_suspects == ()


def test_a_clean_why_still_applies_in_the_verb_and_the_preview(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    _routed(env, A)
    nonce = _suspect(env, A)
    items = _sheet(tmp_path, {"id": A, "verb": "dismiss-suspect", "event": nonce,
                              "why": "rule-followed"})

    (p,) = batch.dry_run(env.ledger, items).items
    assert (p.state, p.kind) == ("would-apply", None), p.detail
    (r,) = batch.run(env.ledger, items, no_push=True).items
    assert r.state == "applied", r.detail
    (entry,) = Record.from_path(find_record_path(env.ledger, A)).dismissed_suspects
    assert entry["why"] == "rule-followed"
