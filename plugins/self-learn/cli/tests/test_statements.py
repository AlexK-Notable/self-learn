"""U2 · User-statement store (`02-schema.md` §3a.3, S-65).

Mutation check pinned here (recorded red-then-green in the U2 report):
(c) a bearer-token-shaped `verbatim` is refused.
"""

from __future__ import annotations

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
