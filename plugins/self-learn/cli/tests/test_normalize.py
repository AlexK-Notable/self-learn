"""normalize.py — the single normalization function + hash forms (08 §7.1)."""

import hashlib
import re

from self_learn.normalize import (
    SHORT_HASH_LEN,
    content_hash,
    normalize_body,
    origin_hash,
    sha_anchor,
)


class TestNormalizeBody:
    def test_crlf_becomes_lf(self):
        assert normalize_body("a\r\nb\r\nc") == "a\nb\nc"

    def test_bare_cr_becomes_lf(self):
        assert normalize_body("a\rb") == "a\nb"

    def test_trailing_whitespace_stripped_per_line(self):
        assert normalize_body("a  \nb\t\nc ") == "a\nb\nc"

    def test_leading_blank_lines_stripped(self):
        assert normalize_body("\n\n\na\nb") == "a\nb"

    def test_trailing_blank_lines_stripped(self):
        assert normalize_body("a\nb\n\n\n") == "a\nb"

    def test_whitespace_only_lines_at_edges_stripped(self):
        # a line of spaces becomes blank after rstrip, then falls to the edge trim
        assert normalize_body("   \na\n   ") == "a"

    def test_interior_blank_lines_preserved(self):
        assert normalize_body("a\n\nb") == "a\n\nb"

    def test_leading_indentation_preserved(self):
        assert normalize_body("  indented\ncode") == "  indented\ncode"

    def test_empty_and_blank_input(self):
        assert normalize_body("") == ""
        assert normalize_body("\n\n  \n") == ""

    def test_idempotent(self):
        text = "  keep\r\n\r\nme  \n\n"
        assert normalize_body(normalize_body(text)) == normalize_body(text)


class TestHashes:
    def test_content_hash_is_full_sha256_of_normalized(self):
        text = "hello\r\nworld  \n\n"
        expected = hashlib.sha256(b"hello\nworld").hexdigest()
        assert content_hash(text) == expected
        assert len(content_hash(text)) == 64

    def test_origin_hash_is_first_12_of_content_hash(self):
        text = "some lesson text"
        assert origin_hash(text) == content_hash(text)[:SHORT_HASH_LEN]
        assert len(origin_hash(text)) == 12
        assert re.fullmatch(r"[0-9a-f]{12}", origin_hash(text))

    def test_sha_anchor_form(self):
        text = "some lesson text"
        assert sha_anchor(text) == f"sha256:{origin_hash(text)}"
        assert re.fullmatch(r"sha256:[0-9a-f]{12}", sha_anchor(text))

    def test_hash_stable_across_whitespace_noise(self):
        """Same content, different line endings / trailing whitespace /
        padding blank lines -> same hash (the dedupe-key property)."""
        base = "## Fact\nHA rewrites .storage on shutdown."
        noisy = "\n\n## Fact  \r\nHA rewrites .storage on shutdown.\t\r\n\r\n"
        assert content_hash(noisy) == content_hash(base)
        assert origin_hash(noisy) == origin_hash(base)
        assert sha_anchor(noisy) == sha_anchor(base)

    def test_different_content_different_hash(self):
        assert content_hash("lesson one") != content_hash("lesson two")

    def test_interior_blank_line_collapse_changes_hash(self):
        # normalization must NOT be so aggressive that distinct bodies collide
        assert content_hash("a\n\nb") != content_hash("a\nb")
