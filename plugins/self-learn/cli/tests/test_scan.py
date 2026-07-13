"""T4 · Secret-scan module tests.

Pin under test: docs/specs/self-learn/08-build-plan.md §1 "Secret scan" row.
Includes the F2 gate-check regressions: 40-hex git SHAs and 8-hex record ids
MUST pass clean; the hex threshold is >= 48.

Token-shaped fixtures are assembled by concatenation so no string in this
file looks like a real credential to external scanners.
"""

from __future__ import annotations

import pytest

from self_learn.scan import Hit, format_refusal, redact, scan


def rules_of(text: str) -> list[str]:
    return [h.rule for h in scan(text)]


# ---------------------------------------------------------------- fixtures

GHP_TOKEN = "ghp_" + "Ab1" * 12  # 36-char classic-token body
GHO_TOKEN = "gho_" + "Cd2" * 12
GITHUB_PAT = "github_pat_" + "Ef3G" * 6  # 24 chars >= 22
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"  # AKIA + 16 upper/digit
SLACK_TOKEN = "xoxb-" + "1234567890-abcdefghij"
JWT_FULL = "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjMifQ" + "." + "sig-part_01"
JWT_NO_SIG = "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjMifQ"

HEX_40 = "4c1e9a2f" * 5  # git SHA shape — must pass
HEX_48 = "a1b2c3d4" * 6  # 48 — must fire
B64_39 = "gA" * 19 + "g"  # 39-char base64 run (contains non-hex 'g')
B64_40 = "gA" * 20  # 40-char base64 run (contains non-hex 'g')


# --------------------------------------------------- every rule class fires


def test_private_key_fires() -> None:
    assert "private-key" in rules_of("blob\n-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
    assert "private-key" in rules_of("-----BEGIN PRIVATE KEY-----")
    assert "private-key" in rules_of("-----BEGIN OPENSSH PRIVATE KEY-----")


def test_aws_key_fires() -> None:
    assert rules_of(f"key is {AWS_KEY} ok") == ["aws-key"]


def test_github_token_fires() -> None:
    assert rules_of(f"use {GHP_TOKEN} here") == ["github-token"]
    assert rules_of(f"use {GHO_TOKEN} here") == ["github-token"]
    assert rules_of(f"use {GITHUB_PAT} here") == ["github-token"]


def test_slack_token_fires() -> None:
    assert rules_of(f"bot auth {SLACK_TOKEN} end") == ["slack-token"]


def test_jwt_fires_with_and_without_signature() -> None:
    assert rules_of(f"bearer {JWT_FULL} sent") == ["jwt"]
    assert rules_of(f"bearer {JWT_NO_SIG} sent") == ["jwt"]


def test_credential_assignment_fires() -> None:
    assert rules_of("password = hunter2hunter2") == ["credential-assignment"]
    assert rules_of("api_key: abcd1234efgh") == ["credential-assignment"]
    assert rules_of("SECRET=verylongvalue99") == ["credential-assignment"]


def test_high_entropy_base64_fires() -> None:
    assert rules_of(f"blob {B64_40} end") == ["high-entropy-base64"]


def test_high_entropy_hex_fires() -> None:
    assert rules_of(f"digest {HEX_48} end") == ["high-entropy-hex"]


# ------------------------------------------------------------- clean passes


def test_clean_prose_passes() -> None:
    text = (
        "The install script symlinks each skill into place, and the\n"
        "watcher commits repo changes within a few seconds of a write.\n"
    )
    assert scan(text) == []


# ------------------------------------------------- F2 regression (hex >= 48)


def test_f2_git_sha_40_hex_passes() -> None:
    assert scan(f"fixed in commit {HEX_40} on master") == []


def test_f2_record_id_passes() -> None:
    assert scan("see record lrn-4c1e9a2f for details") == []


def test_f2_48_hex_run_fires() -> None:
    hits = scan(f"dump: {HEX_48}")
    assert [h.rule for h in hits] == ["high-entropy-hex"]


def test_base64_threshold_39_passes_40_fires() -> None:
    assert scan(f"pad {B64_39} pad") == []
    assert rules_of(f"pad {B64_40} pad") == ["high-entropy-base64"]


# ------------------------------------------------------- dedupe interactions


def test_pure_hex_run_reports_one_hit_hex_rule_wins() -> None:
    # A 48-hex run is also a >=40 base64-charset run; it must surface as
    # exactly ONE hit, attributed to high-entropy-hex.
    hits = scan(HEX_48)
    assert len(hits) == 1
    assert hits[0].rule == "high-entropy-hex"


def test_credential_assignment_wins_over_embedded_token() -> None:
    hits = scan(f"token = {GHP_TOKEN}")
    assert len(hits) == 1
    assert hits[0].rule == "credential-assignment"
    assert GHP_TOKEN in hits[0].span


# ---------------------------------------------------------------- redaction


def test_redact_replaces_span_with_marker() -> None:
    text = f"key is {AWS_KEY} ok"
    redacted, hits = redact(text)
    assert "[redacted:aws-key]" in redacted
    assert AWS_KEY not in redacted
    assert redacted == "key is [redacted:aws-key] ok"
    assert [h.rule for h in hits] == ["aws-key"]


def test_redact_clean_text_unchanged() -> None:
    text = "nothing secretive in here, just prose"
    # ("secretive in here," has no assignment shape — value check)
    redacted, hits = redact(text)
    assert redacted == text
    assert hits == []


def test_redact_multiple_hits() -> None:
    text = f"a {AWS_KEY} b {SLACK_TOKEN} c"
    redacted, hits = redact(text)
    assert AWS_KEY not in redacted
    assert SLACK_TOKEN not in redacted
    assert "[redacted:aws-key]" in redacted
    assert "[redacted:slack-token]" in redacted
    assert len(hits) == 2


# ----------------------------------------------------------------- refusal


def test_format_refusal_contains_span_and_rule() -> None:
    hits = scan(f"key is {AWS_KEY} ok")
    msg = format_refusal(hits)
    assert AWS_KEY in msg
    assert "aws-key" in msg


def test_format_refusal_lists_every_hit() -> None:
    hits = scan(f"a {AWS_KEY} b {SLACK_TOKEN} c")
    msg = format_refusal(hits)
    assert AWS_KEY in msg and "aws-key" in msg
    assert SLACK_TOKEN in msg and "slack-token" in msg


# ------------------------------------------------------------ hit mechanics


def test_multi_hit_text_reports_all_sorted_by_offset() -> None:
    text = f"one {AWS_KEY} two {SLACK_TOKEN} three {HEX_48} ."
    hits = scan(text)
    assert [h.rule for h in hits] == ["aws-key", "slack-token", "high-entropy-hex"]
    assert hits == sorted(hits, key=lambda h: h.start)


def test_hit_offsets_match_span() -> None:
    text = f"pre {SLACK_TOKEN} post"
    for h in scan(text):
        assert text[h.start : h.end] == h.span


def test_hit_is_frozen() -> None:
    h = Hit(rule="aws-key", span="x", start=0, end=1)
    with pytest.raises(AttributeError):
        h.rule = "other"  # type: ignore[misc]
