"""Secret scan for record-body writes (T4).

Pin (docs/specs/self-learn/08-build-plan.md §1 "Secret scan" row): a
built-in regex module — no external tool dependency. Rule classes:

- ``private-key``            PEM private-key headers
- ``aws-key``                ``AKIA`` + 16 upper/digit
- ``github-token``           ``ghp_`` / ``gho_`` / ``github_pat_`` shapes
- ``slack-token``            ``xox<letter>-…``
- ``jwt``                    two dot-separated ``eyJ…`` segments, optional
                             signature segment
- ``credential-assignment``  ``(password|passwd|secret|token|api[_-]?key)``
                             ``\\s*[=:]\\s*\\S{8,}``, case-insensitive
- ``high-entropy-base64``    runs of ``[A-Za-z0-9+/=]`` length >= 40; a
                             path-shaped run is judged per segment
                             (segments of length >= 20), see below
- ``high-entropy-hex``       runs of ``[0-9a-fA-F]`` length >= 48

The hex threshold of **48** is load-bearing (gate-check F2): 40-hex git
SHAs and 8-hex record ids must pass clean.

This module only detects and rewrites; the refuse-vs-redact POLICY lives
in the callers (T5/T7 verbs — default refuse, ``--redact`` opt-in, no
bypass flag in v1).

Overlap / dedupe choices (documented per the T4 brief):

- Entropy runs are *maximal* charset runs (``finditer`` on a greedy
  ``{N,}`` pattern yields exactly the maximal runs of length >= N).
- A base64-charset run that consists **only** of hex characters is
  classified under the hex rule alone: it fires ``high-entropy-hex`` iff
  its length >= 48, and never fires ``high-entropy-base64``. This is both
  halves of F2 — a 40..47-char pure-hex run (e.g. a git SHA) passes clean
  instead of tripping the base64 rule, and a 48+ hex run reports exactly
  one hit under one rule (hex wins on pure-hex runs).
- Overlapping hits from different rules are merged so one span reports
  one rule: hits are kept in order of (earlier start, then longer span,
  then rule-table order), and any hit overlapping an already-kept hit is
  dropped. "Longer/earlier matches win." Consequently a
  ``credential-assignment`` whose value is itself a token (e.g.
  ``token = ghp_…``) reports once, as ``credential-assignment`` — its
  match starts earlier and contains the token span.

Folder paths (2026-09-26, steward run ``run-1ca3de428b35``): ``/`` is in
the base64 charset and the base64 rule never measures entropy, so any
folder path of 40+ characters with no ``.``, ``-``, ``_`` or space read as
a secret — that run's whole packet was refused over an evidence quote
holding ``/data/SteamLibrary/steamapps/compatdata/3669870/pfx/drive``.
Entropy does not separate the two (real paths measured 3.75-4.34
bits/char, random 40-char base64 as low as 4.28), so the carve-out is
STRUCTURAL:

- A base64 candidate run (not pure hex) is *path-shaped* when it starts
  with ``/`` and holds at least 3 ``/``. For a random 40-char base64
  string both happen roughly 1 time in 2,500, so the carve-out almost
  never swallows a real random secret whole.
- A path-shaped run is judged per segment (split on ``/``) instead of as
  one run: a segment of length >= 20 that is not pure hex fires
  ``high-entropy-base64`` with THAT SEGMENT's span and offsets, so a
  token hidden as a path segment (``/api/v1/tokens/<random>``) is still
  caught. Every other rule (the pattern table and the hex rule) already
  sweeps the whole text on its own, so a ``ghp_…`` segment or a 48+ hex
  segment is caught by that rule unchanged; a pure-hex segment keeps its
  hex behaviour (hex >= 48 fires, shorter passes, as for a git SHA).
- Why 20 per segment: a random 20-char base64 string carries ~120 bits,
  and the credential bodies worth catching are that long or longer (AWS
  secret keys 40, GitHub token bodies 36, most API keys 32+), while an
  ordinary folder name of 20+ characters with no ``.``, ``-``, ``_`` or
  space is rare. It is never set below 16 (~96 bits), where ordinary
  CamelCase folder names begin to fire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Hit", "scan", "redact", "format_refusal"]


@dataclass(frozen=True)
class Hit:
    """One secret-scan finding: rule name, matched span text, offsets."""

    rule: str
    span: str
    start: int
    end: int


# Pattern-rule table, in tie-break priority order (used only when two hits
# share the same start offset and length). Boundary lookarounds on the
# token rules keep a token embedded in a longer alphanumeric word from
# double-firing; they are a judgment call, noted in the module docstring.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws-key", re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![0-9A-Z])")),
    (
        "github-token",
        re.compile(
            r"(?<![A-Za-z0-9])(?:gh[po]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"
        ),
    ),
    ("slack-token", re.compile(r"(?<![A-Za-z0-9])xox[a-zA-Z]-[A-Za-z0-9-]{5,}")),
    (
        "jwt",
        re.compile(
            r"eyJ[A-Za-z0-9_-]{4,}\.eyJ[A-Za-z0-9_-]{4,}(?:\.[A-Za-z0-9_-]+)?"
        ),
    ),
    (
        "credential-assignment",
        re.compile(
            r"(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S{8,}",
            re.IGNORECASE,
        ),
    ),
]

_RULE_PRIORITY: dict[str, int] = {name: i for i, (name, _) in enumerate(_RULES)}
_RULE_PRIORITY["high-entropy-hex"] = len(_RULE_PRIORITY)
_RULE_PRIORITY["high-entropy-base64"] = len(_RULE_PRIORITY)

# Greedy {N,} + finditer == exactly the maximal charset runs of length >= N.
_HEX_RUN = re.compile(r"[0-9a-fA-F]{48,}")  # threshold 48 is F2-load-bearing
_B64_RUN = re.compile(r"[A-Za-z0-9+/=]{40,}")
_PURE_HEX = re.compile(r"[0-9a-fA-F]+")
# Path carve-out (2026-09-26): see the module docstring.
_PATH_MIN_SLASHES = 3
_PATH_SEGMENT_MIN = 20  # never below 16


def _is_path_shaped(run: str) -> bool:
    return run.startswith("/") and run.count("/") >= _PATH_MIN_SLASHES


def _path_segment_hits(run: str, offset: int) -> list[Hit]:
    """A path-shaped run's own base64 hits: each long non-hex segment."""
    hits: list[Hit] = []
    pos = 0
    for segment in run.split("/"):
        if len(segment) >= _PATH_SEGMENT_MIN and not _PURE_HEX.fullmatch(segment):
            start = offset + pos
            hits.append(Hit("high-entropy-base64", segment, start, start + len(segment)))
        pos += len(segment) + 1
    return hits


def scan(text: str) -> list[Hit]:
    """Return all secret hits in *text*, merged so one span reports one rule.

    Hits come back sorted by start offset.
    """
    raw: list[Hit] = []
    for rule, pattern in _RULES:
        for m in pattern.finditer(text):
            raw.append(Hit(rule, m.group(0), m.start(), m.end()))

    for m in _HEX_RUN.finditer(text):
        raw.append(Hit("high-entropy-hex", m.group(0), m.start(), m.end()))

    for m in _B64_RUN.finditer(text):
        if _PURE_HEX.fullmatch(m.group(0)):
            # Pure-hex run: the hex rule (threshold 48) owns it — F2.
            continue
        if _is_path_shaped(m.group(0)):
            # A folder path is judged per segment (2026-09-26).
            raw.extend(_path_segment_hits(m.group(0), m.start()))
            continue
        raw.append(Hit("high-entropy-base64", m.group(0), m.start(), m.end()))

    return _merge(raw)


def redact(text: str) -> tuple[str, list[Hit]]:
    """Replace every hit span with ``[redacted:<rule>]``.

    Returns the rewritten text and the hits that were redacted (the same
    list :func:`scan` would report). Clean text comes back unchanged.
    """
    hits = scan(text)
    out = text
    for h in reversed(hits):  # right-to-left keeps earlier offsets valid
        out = out[: h.start] + f"[redacted:{h.rule}]" + out[h.end :]
    return out, hits


def format_refusal(hits: list[Hit]) -> str:
    """Human-readable refusal message: matched span + rule per hit.

    Callers (T5/T7) print this when refusing a write; this module does not
    decide refuse-vs-redact.
    """
    n = len(hits)
    lines = [f"secret scan: {n} hit{'s' if n != 1 else ''} — refusing this write"]
    for h in hits:
        lines.append(f"  - [{h.rule}] at {h.start}..{h.end}: {h.span}")
    return "\n".join(lines)


def _merge(raw: list[Hit]) -> list[Hit]:
    """Dedupe overlapping hits: earlier start, then longer span, wins."""
    ordered = sorted(
        raw,
        key=lambda h: (h.start, -(h.end - h.start), _RULE_PRIORITY[h.rule]),
    )
    kept: list[Hit] = []
    for hit in ordered:
        if any(hit.start < k.end and k.start < hit.end for k in kept):
            continue
        kept.append(hit)
    return kept  # already sorted by start
