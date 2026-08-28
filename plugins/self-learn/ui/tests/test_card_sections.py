"""card-sections.yaml's registry-driven render order — CARD3
(`u-ancestry-ancestor-canon-spec.md` §9): the shelf-evidence section
S-52/§7 adds renders in its registered position (order 35, between
`impact` at 30 and `discuss` at 40), read through the SAME generic
registry path every other section uses (`ledger.read_registry` +
`models.build_card_sections`) — no section name is hardcoded here or
anywhere downstream (CARD2, `cli/tests/test_u_ancestry.py`).
"""

from __future__ import annotations

from self_learn_ui.ledger import read_registry
from self_learn_ui.models import build_card_sections


def test_card3_shelf_evidence_section_renders_between_impact_and_discuss():
    registry = read_registry()
    by_key = {r["key"] for r in registry}
    assert "already_kept" in by_key

    row = next(r for r in registry if r["key"] == "already_kept")
    assert row["order"] == 35

    card = {
        "headline": "the headline",
        "impact": "the impact section",
        "already_kept": "the shelf-evidence section",
        "discuss": "the discuss section",
    }
    sections = build_card_sections(card, registry)
    keys_in_order = [s.key for s in sections]
    assert keys_in_order.index("impact") < keys_in_order.index("already_kept")
    assert keys_in_order.index("already_kept") < keys_in_order.index("discuss")

    shelf = next(s for s in sections if s.key == "already_kept")
    assert shelf.order == 35
    assert shelf.text == "the shelf-evidence section"


def test_card3_shelf_evidence_section_absent_when_card_omits_it():
    """Registered as `required: optional` (§7): a card that never writes
    this section renders no `already_kept` `CardSection` at all — the
    registry lists the key as available, not mandatory."""
    registry = read_registry()
    card = {"headline": "the headline", "impact": "the impact section"}
    sections = build_card_sections(card, registry)
    assert "already_kept" not in [s.key for s in sections]
