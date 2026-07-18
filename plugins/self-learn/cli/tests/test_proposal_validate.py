"""T11 (verb pulled forward from T13 — 08 §7.1 Proposal-validate-verb row):
`self-learn proposal validate <id>` — scan + schema + stamp for attended
iteration.

Pinned exit codes (P2-8): 0 = valid + scan-clean (stamped) · 1 =
schema-invalid (REPORT, never delete — file byte-intact) · 2 = scan hit
(wins when both apply). Stamps in place on success; commits nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import cli
from self_learn.ledger_ops import create_record, read_proposal, write_proposal
from self_learn.normalize import sha_anchor
from self_learn.records import Record

from support import commit_all, git, make_home, make_knowledge, proposal_dict

GHP_TOKEN = "ghp_" + "a" * 36  # fires the github-token scan rule


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


def seed_record(home: Path, fact: str = "The Nova serves Glances on :61208.") -> Record:
    # user scope: a single flat bucket needing no project_path (doc 13 §3),
    # keeping this suite focused on the validate verb, not bucket routing.
    record = make_knowledge(scope="user", fact=fact)
    create_record(home, record)
    return record


def proposal_path(home: Path, rid: str) -> Path:
    return home / "user" / "proposals" / f"{rid}.yaml"


def commit_count(home: Path) -> int:
    return int(git(home, "rev-list", "--count", "HEAD").stdout.strip())


# ------------------------------------------------- case 1: valid + clean → 0


def test_valid_clean_exits_0_and_stamps_over_model_sha(home, capsys):
    record = seed_record(home)
    write_proposal(home, record.id, proposal_dict(record_sha="sha256:000000000000"))
    commit_all(home, "seed")
    before = commit_count(home)

    rc = cli.main(["proposal", "validate", record.id])

    assert rc == 0
    # The CLI stamps: the model-emitted sha is overwritten with the hash of
    # the record's CURRENT normalized body (never trusted — 08 §7.1).
    data = read_proposal(proposal_path(home, record.id))
    assert data["record_sha"] == sha_anchor(record.body)
    assert data["record_sha"] != "sha256:000000000000"
    out = capsys.readouterr().out
    assert record.id in out and "stamped" in out
    # Commits nothing: proposals/records are working files pre-resolution.
    assert commit_count(home) == before
    assert "proposals/" in git(home, "status", "--porcelain").stdout


# --------------------------------------------- case 2: schema-invalid → 1


def test_schema_invalid_exits_1_file_byte_intact(home, capsys):
    record = seed_record(home)
    path = proposal_path(home, record.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # destination outside the 02 §1 enum → schema-invalid
    path.write_text(
        "destination: bogus\nrationale: r\nmodel: m\n"
        "analyzed_at: 2026-07-13T00:00:00Z\n",
        encoding="utf-8",
    )
    before = path.read_bytes()

    rc = cli.main(["proposal", "validate", record.id])

    assert rc == 1
    assert path.read_bytes() == before  # REPORT, never delete/rewrite
    err = capsys.readouterr().err
    assert "destination" in err  # the reason is reported


def test_missing_proposal_sibling_exits_1(home, capsys):
    record = seed_record(home)
    rc = cli.main(["proposal", "validate", record.id])
    assert rc == 1
    assert "no proposal sibling" in capsys.readouterr().err


# ------------------------------------------- case 3: scan hit in record → 2


def test_scan_hit_in_record_body_exits_2_with_span_report(home, capsys):
    record = seed_record(home, fact=f"Leaked {GHP_TOKEN} in the build log.")
    write_proposal(home, record.id, proposal_dict(record_sha="sha256:000000000000"))
    ppath = proposal_path(home, record.id)
    before = ppath.read_bytes()

    rc = cli.main(["proposal", "validate", record.id])

    assert rc == 2
    err = capsys.readouterr().err
    assert "github-token" in err and GHP_TOKEN in err  # span + rule
    # never deletes, never auto-redacts, never stamps
    assert ppath.read_bytes() == before
    record_file = home / "user" / "pending" / f"{record.id}.md"
    assert GHP_TOKEN in record_file.read_text(encoding="utf-8")


def test_scan_hit_in_proposal_free_text_exits_2(home, capsys):
    # The scan covers ALL proposal siblings incl. rationale free text (P2-1).
    record = seed_record(home)
    write_proposal(
        home,
        record.id,
        proposal_dict(rationale=f"model pasted {GHP_TOKEN} into its rationale"),
    )
    rc = cli.main(["proposal", "validate", record.id])
    assert rc == 2
    assert "github-token" in capsys.readouterr().err


# ------------------------------------------------------ case 4: both → 2


def test_scan_hit_in_edited_episode_brief_exits_2(home, capsys):
    """02 §1/§2 (10 §3 U18): a human-added/edited '## Episode brief' rides
    the SAME proposal-validate checkpoint as any other body text — no
    special-cased hole. A secret added to the brief on the Discuss/pane
    edit path (not the miner's own compose-before-scan write) is caught
    at the next `proposal validate` re-scan."""
    record = seed_record(home)
    write_proposal(home, record.id, proposal_dict(record_sha="sha256:000000000000"))
    record_path = home / "user" / "pending" / f"{record.id}.md"
    fresh = Record.from_path(record_path)
    fresh.set_body(
        fresh.body.rstrip("\n")
        + f"\n\n## Episode brief\nRotated the leaked {GHP_TOKEN} token immediately.\n"
    )
    fresh.write(record_path)

    rc = cli.main(["proposal", "validate", record.id])

    assert rc == 2
    assert "github-token" in capsys.readouterr().err


def test_scan_hit_wins_over_schema_invalid(home, capsys):
    record = seed_record(home, fact=f"Leaked {GHP_TOKEN} in the build log.")
    path = proposal_path(home, record.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("destination: bogus\n", encoding="utf-8")  # invalid too
    before = path.read_bytes()

    rc = cli.main(["proposal", "validate", record.id])

    assert rc == 2  # scan hit wins when both apply (P2-8)
    assert path.read_bytes() == before


# ------------------------------------------------------------ id handling


def test_unknown_record_id_is_a_usage_error(home, capsys):
    rc = cli.main(["proposal", "validate", "lrn-deadbeef"])
    assert rc == 64
    assert "not found" in capsys.readouterr().err


def test_proposal_without_verb_is_usage_error(home, capsys):
    rc = cli.main(["proposal"])
    assert rc == 64
