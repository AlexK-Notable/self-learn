"""What counts as a query token -- the one definition, applied once.

Ported from the user's ``keys`` project, ``keys/search/tokenize.py``
(2026-09-26). The history there (two rounds of keybinding tokens lost to
punctuation deletion and double tokenization) is why the two rules below
exist; lesson text rarely carries keybindings, but paths and flags
(``wl-copy``, ``-n``, ``.storage/core.json``) follow the same rules.

The FTS5 index tokenizes with ``porter unicode61``, which treats every
non-alphanumeric character as a separator. The query side must match that:

- **Tokenize once.** :func:`tokenize` is the only place text becomes query
  tokens; downstream code passes token LISTS, never re-derives them from a
  joined string.
- **A compound word keeps every part.** If a raw word contained
  punctuation, each part is load-bearing -- including one-character parts
  and parts that spell a stopword. Length and stopword filtering apply only
  to standalone words.
"""

from __future__ import annotations

import re

# Natural-language fillers only. Applied to STANDALONE words only.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the",
        "is", "are", "was", "were", "be", "been", "being",
        "do", "does", "did",
        "i", "me", "my", "you", "your",
        "this", "that", "these", "those",
        "in", "on", "to", "of", "for", "with",
        "and", "or", "but",
        "how", "what", "when", "where", "which", "why",
        "all", "any", "some",
        "it", "its",
    }
)

# Used to SPLIT, never to weld. Every emitted token is rebuilt from word
# characters, so no FTS5 syntax survives into a MATCH expression;
# lowercasing keeps operator words (NOT/AND/OR) inert.
_SPLIT = re.compile(r"[^\w]+")


def word_parts(raw: str) -> tuple[list[str], bool]:
    """Split one whitespace-delimited word the way the index does.
    Returns ``(parts, compound)``; ``compound`` is True when the raw word
    contained any punctuation."""
    parts = [p for p in _SPLIT.split(raw) if p]
    compound = bool(parts) and (len(parts) > 1 or parts[0] != raw)
    return parts, compound


def tokenize(query: str) -> list[str]:
    """Lowercase, split like the index, filter noise -- exactly once."""
    tokens: list[str] = []
    for raw in query.lower().split():
        parts, compound = word_parts(raw)
        if compound:
            tokens.extend(parts)
        else:
            tokens.extend(p for p in parts if len(p) >= 2 and p not in STOPWORDS)
    return tokens
