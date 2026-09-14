"""U2 · User-statement store (`02-schema.md` §3a.3, S-65).

Mutation check pinned here (recorded red-then-green in the U2 report):
(c) a bearer-token-shaped `verbatim` is refused.
(f) the dedupe check runs under the lock (Astra 4/10, fold-u2-r1 item 6).
(dc) D-c — `conversation:<id>` requires the `obs-<8hex>` shape.
"""

from __future__ import annotations

import contextlib
import json

import pytest

from self_learn import statements
from support import make_home


def test_add_appends_one_jsonl_line(tmp_path):
    home = make_home(tmp_path)
    stmt_id = statements.add(
        home,
        verbatim="definitely push the configs",
        source={"message_ref": "transcript:9c1e#L2214", "surface": "conversation"},
        recorded_by="steward",
    )
    assert statements.STMT_ID_RE.match(stmt_id)
    path = home / "user-statements.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["id"] == stmt_id
    assert row["verbatim"] == "definitely push the configs"
    assert row["recorded_by"] == "steward"
    assert row["source"]["message_ref"] == "transcript:9c1e#L2214"


def test_add_rejects_recorded_by_outside_closed_set(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(statements.StatementUsageError):
        statements.add(
            home, verbatim="x",
            source={"message_ref": "transcript:s#L1"},
            recorded_by="analyst",
        )


def test_add_rejects_malformed_message_ref(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(statements.StatementUsageError):
        statements.add(
            home, verbatim="x",
            source={"message_ref": "case:deadbeef"},
            recorded_by="human",
        )


def test_dedupe_key_is_message_ref_and_verbatim(tmp_path):
    home = make_home(tmp_path)
    id1 = statements.add(
        home, verbatim="same words",
        source={"message_ref": "transcript:s#L1"}, recorded_by="human",
    )
    id2 = statements.add(
        home, verbatim="same words",
        source={"message_ref": "transcript:s#L1"}, recorded_by="human",
    )
    assert id1 == id2
    path = home / "user-statements.jsonl"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    # different message_ref, same words -> a genuinely new line
    id3 = statements.add(
        home, verbatim="same words",
        source={"message_ref": "transcript:s#L2"}, recorded_by="human",
    )
    assert id3 != id1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_amends_must_reference_a_known_statement(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(statements.StatementUsageError):
        statements.add(
            home, verbatim="a correction",
            source={"message_ref": "transcript:s#L9"}, recorded_by="human",
            amends="stmt-deadbeef",
        )


def test_list_statements_filters(tmp_path):
    home = make_home(tmp_path)
    statements.add(
        home, verbatim="user scope one",
        source={"message_ref": "transcript:s#L1"}, recorded_by="human",
        scope={"level": "user"},
    )
    statements.add(
        home, verbatim="project scope one",
        source={"message_ref": "transcript:s#L2"}, recorded_by="steward",
        scope={"level": "project", "host": "/some/host"},
    )
    user_only = statements.list_statements(home, scope_level="user")
    assert len(user_only) == 1
    assert user_only[0]["verbatim"] == "user scope one"
    by_steward = statements.list_statements(home, recorded_by="steward")
    assert len(by_steward) == 1
    assert by_steward[0]["verbatim"] == "project scope one"


# ------------------------------------------------------- (c) secret scan


def test_c_bearer_token_shaped_verbatim_is_refused(tmp_path):
    home = make_home(tmp_path)
    # A concrete rule this scanner actually fires on (github-token shape,
    # confirmed against `scan.scan` directly below, not guessed) — see
    # `scan.py`'s own rule table; the classic-token body is 36 chars.
    from self_learn.scan import scan as secret_scan

    token = "ghp_" + "Ab1" * 12
    positive_control_hits = secret_scan(token)
    assert positive_control_hits, "positive control: the scanner must actually fire on this token"
    assert positive_control_hits[0].rule == "github-token"

    with pytest.raises(statements.StatementError):
        statements.add(
            home, verbatim=f"the deploy token is {token}",
            source={"message_ref": "transcript:s#L1"}, recorded_by="human",
        )
    assert not (home / "user-statements.jsonl").exists()


# --------------------------------------------------- (dc) message_ref grammar


def test_dc_conversation_ref_requires_obs_id_shape(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(statements.StatementUsageError):
        statements.add(
            home, verbatim="x",
            source={"message_ref": "conversation:banana"}, recorded_by="human",
        )
    # positive control: the well-shaped form is accepted
    stmt_id = statements.add(
        home, verbatim="y",
        source={"message_ref": "conversation:obs-1234abcd"}, recorded_by="human",
    )
    assert statements.STMT_ID_RE.match(stmt_id)


# ------------------------------------------- (f) load/dedupe under the lock


def test_f_dedupe_check_runs_under_the_lock(tmp_path, monkeypatch):
    """Astra 4/10 (fold-u2-r1 item 6). A peer write lands the exact same
    (message_ref, verbatim) pair between lock-acquisition and this call's
    own read. Hooked by wrapping `intents.ledger_write` so the injection
    happens the instant the lock is held — before `add`'s own first read.
    Fixed code (dedupe computed under the lock) sees the peer and returns
    its id, writing nothing new. Pre-fix code (dedupe computed before the
    lock) misses the peer and writes a second, duplicate line."""
    home = make_home(tmp_path)
    real_ledger_write = statements.intents.ledger_write
    state = {"injected": False}

    @contextlib.contextmanager
    def hook(home_arg, **kwargs):
        with real_ledger_write(home_arg, **kwargs) as recovered:
            if not state["injected"]:
                state["injected"] = True
                path = statements._path(home_arg)
                peer_row = {
                    "id": "stmt-deadbeef",
                    "at": "2026-01-01T00:00:00Z",
                    "verbatim": "same words",
                    "answers": {"kind": "proposition", "ref": None, "text": None},
                    "source": {"message_ref": "transcript:s#L1"},
                    "scope": {"level": "user", "host": None},
                    "uncertainty": None,
                    "recorded_by": "human",
                    "amends": None,
                }
                line = json.dumps(peer_row, sort_keys=True)
                prior = path.read_text(encoding="utf-8") if path.exists() else ""
                if prior and not prior.endswith("\n"):
                    prior += "\n"
                statements.fsops.atomic_write(path, prior + line + "\n", fsync=True)
                statements.gitops.stage_and_commit(
                    home_arg, [path], "peer: statement add stmt-deadbeef", None
                )
            yield recovered

    monkeypatch.setattr(statements.intents, "ledger_write", hook)

    result_id = statements.add(
        home, verbatim="same words",
        source={"message_ref": "transcript:s#L1"}, recorded_by="human",
    )
    assert result_id == "stmt-deadbeef"
    lines = statements._path(home).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
