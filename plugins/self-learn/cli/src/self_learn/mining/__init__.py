"""The session miner (U4): the output contract and the engine.

This package keeps no imports on purpose, so the lane that adds the engine
modules never edits it. ``contract`` is the one place the output shapes are
defined (docs/specs/self-learn/02-schema.md, "Session miner output"); the
engine reads it unchanged (the offline ``compare`` harness was removed on
2026-10-24, S-93).
"""
