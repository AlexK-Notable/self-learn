"""The lesson index and related-lesson search (U2, 2026-09-26; spec
02-schema.md §3a.7).

A cache-only index over every ledger record: FTS5 word search plus, when a
Gemini key is in the environment, embeddings from ``gemini-embedding-2``.
Built on it: :func:`related.related` (are two lessons related?) and
:func:`related.group_for_steward` (batches of at most 10, at most 5 of them
unrelated).

The embedding client, the provider protocol, the fake provider, FTS5
search, reciprocal-rank fusion, hybrid search and the blob vector store are
ported from the user's own ``keys`` project (``keys/embed``,
``keys/search``, ``keys/storage/vectors.py``); each module names its source
file. Nothing here writes the ledger: the index lives in the cache.
"""
