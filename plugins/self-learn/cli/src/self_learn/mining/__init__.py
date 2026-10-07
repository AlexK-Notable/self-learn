"""The session miner (U4): the output contract, the offline comparison and,
in a later wave, the engine.

This package keeps no imports on purpose, so the lane that adds the engine
modules never edits it. ``contract`` is the one place the output shapes are
defined (docs/specs/self-learn/02-schema.md, "Session miner output"); the
engine and the offline ``compare`` harness both read it unchanged.
"""
