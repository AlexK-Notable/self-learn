"""Content assertions on the authored ``pane-charter.md`` (10 §3 task U5
bullet 5): its job, its limits, and the Y-9 communication-register pin
must all actually be present in the shipped file — not just described in
a commit message. Deliberately light-touch (substring/structure checks,
not a prose-quality grader): the file is prose for a model, and its exact
wording is expected to evolve.
"""

from __future__ import annotations

from self_learn_ui.doctrine import pane_charter_path


def _text() -> str:
    return pane_charter_path().read_text(encoding="utf-8")


def test_charter_file_exists_and_is_non_trivial() -> None:
    text = _text()
    assert len(text) > 500


def test_charter_states_the_job() -> None:
    text = _text().lower()
    assert "improve" in text
    assert "pending" in text and "record" in text
    assert "proposal" in text
    assert "canon" in text


def test_charter_states_the_allow_deny_surface_limits() -> None:
    text = _text().lower()
    assert "read" in text
    assert "denied" in text or "refused" in text
    assert "pending/lrn-" in text or "lrn-<id>" in text


def _flat() -> str:
    """The charter with emphasis marks dropped and every run of
    whitespace (line wraps included) collapsed to one space, so a policy
    sentence can be matched whole."""
    return " ".join(_text().replace("**", "").split())


def test_charter_states_no_path_to_route() -> None:
    # The sentence, not loose keywords: independent `"route" in text` and
    # `"never" in text` checks passed when this rule was reversed (test
    # audit L10-2).
    assert (
        "You have no path to `route`, `reject`, `defer`, or `retire` — ever."
        in _flat()
    )


def test_charter_states_proposer_never_equals_approver() -> None:
    assert (
        "You are the proposer. The human is the approver. "
        "These are never the same party"
    ) in _flat()


def test_charter_includes_the_routing_doctrine_section_8_register(tmp_path=None) -> None:
    """Y-9: the pane charter must include the routing-doctrine §8
    communication register — pane prose renders directly to the human,
    so plain-language and no-system-vocabulary rules must be restated
    here, not merely cross-referenced."""
    text = _text().lower()
    assert "plain human language" in text or "plain language" in text
    assert "system vocabulary" in text
    # The register names concrete forbidden categories (enum values,
    # record ids, jargon) — not just an abstract "be nice" instruction.
    assert "record id" in text or "lrn-" in text
    assert "enum" in text
    assert "jargon" in text


def test_charter_is_addressed_to_the_agent_not_about_it() -> None:
    """Prose meant to be compiled straight into a system prompt should
    read as instructions ('you'), not third-person documentation."""
    text = _text()
    assert "\nYou " in text or text.startswith("You ") or " you " in text.lower()
