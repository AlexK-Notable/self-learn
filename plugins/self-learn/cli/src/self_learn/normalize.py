"""THE single normalization function — one definition, two uses (08 §7.1).

Both hash consumers share :func:`normalize_body`:

1. ``evidence.origin`` content anchors (02 §2): ``<path>#sha256:<12 hex>`` of
   the normalized entry text when the source has no heading/date anchor.
2. Proposal ``record_sha`` staleness stamps: the hash of the normalized
   record at analysis time (02 §1) — staleness is a hash mismatch, never
   file mtime.

Hash-length pin (structural decision, recorded here): 02 §1's example shows
``record_sha: sha256:a1b2c3d4e5f6`` — 12 hex — and 02 §2 pins the origin
anchor as ``sha256:<first-12-hex>``. Both uses therefore take the FIRST 12
hex of the full sha256, rendered as ``sha256:<12hex>``. :func:`content_hash`
still exposes the full 64-hex digest for callers that want it; the shared
short form is :func:`origin_hash` / :func:`sha_anchor`.

Never define a second normalization: any other module needing "normalized
text" imports from here (08 §1 Dedupe-key pin, §7.1 worker pin).
"""

from __future__ import annotations

import hashlib

#: Length of the short hash used by evidence.origin anchors and record_sha.
SHORT_HASH_LEN = 12


def normalize_body(text: str) -> str:
    """Normalize text for hashing: CRLF->LF, strip per-line trailing
    whitespace, strip leading/trailing blank lines.

    Interior blank lines and leading indentation are preserved — only the
    noise that editors/git churn (line endings, trailing spaces, padding
    blank lines) is removed, so the hash is stable across such rewrites.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def content_hash(text: str) -> str:
    """Full sha256 hex digest (64 chars) of the normalized text."""
    return hashlib.sha256(normalize_body(text).encode("utf-8")).hexdigest()


def origin_hash(text: str) -> str:
    """First 12 hex of the normalized text's sha256 (02 §2 anchor form)."""
    return content_hash(text)[:SHORT_HASH_LEN]


def sha_anchor(text: str) -> str:
    """The pinned rendered form ``sha256:<12hex>`` — used verbatim both as
    the ``evidence.origin`` anchor suffix and as proposal ``record_sha``."""
    return f"sha256:{origin_hash(text)}"
