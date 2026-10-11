"""E1 (2026-10-10): the case writer's decision keys -- `decision.rewrite`,
`decision.skill`, and the refusal of every key it does not know.

D-AUTHOR §1.5 measured the gap this closes: `cases.record` checked, rendered,
hashed and scanned only the decision keys it knew, so any other key was
accepted and then dropped from the case without a word. A `decision.rewrite`
block (D-AUTHOR §2.4, the account of where each idea of a rewritten lesson's
old text went) written before this build would have vanished. The build plan
(SP-E) adds the general rule: a case with an unknown key under `decision` is
refused by name.

Every test runs on a sandbox ledger (`support.make_home` under pytest's
tmpdir). Ids and texts are synthetic.
"""

from __future__ import annotations

import pytest

from self_learn import cases
from support import make_home
from test_cases import _record, _write_stage

REWRITE = {
    "ideas": [
        {"idea": "a flat yield per round is a steady state, not convergence", "now": "loaded"},
        {"idea": "the user rejected a round cap on 2026-09-13", "now": "context"},
        {"idea": "strings on 2.1.283 still finds the message", "now": "field:verified_how"},
        {"idea": "the old trigger named one shell only", "now": "dropped",
         "why": "said by lrn-0000beef in the same file"},
    ]
}
SKILL = {"name": "drawing-diagrams", "why": "two lessons share one procedure",
         "lessons": ["lrn-08ed825b"]}


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _case_text(home, case_id: str) -> str:
    return next(home.glob(f"cases/*/{case_id}.md")).read_text(encoding="utf-8")


def _decision_section(text: str) -> str:
    return text.split("## Decision\n", 1)[1].split("\n## ", 1)[0]


# ------------------------------------------------ (b) unknown keys refused


def test_an_unknown_decision_key_is_refused_by_name(tmp_path):
    """SP-E (b): master accepted `decision.mood`, wrote the case, and the
    key was in neither the file nor its hash. Now it is refused by name,
    and nothing is written. Control first: the same case without the key
    records."""
    home = make_home(tmp_path)
    control = _record(tmp_path, home)
    assert cases.CASE_ID_RE.match(control)
    before = sorted(home.glob("cases/*/*.md"))

    with pytest.raises(cases.CaseUsageError) as exc:
        _record(tmp_path, home, overrides={"decision.mood": "cheerful"})
    assert "unknown key(s) ['mood']" in str(exc.value)
    assert sorted(home.glob("cases/*/*.md")) == before


def test_the_stage_check_refuses_an_unknown_decision_key_too(tmp_path):
    """The runners' stage check (`check_case_data`, the steward's repair
    turn reads it) is the same copy of the rule, so the model hears it while
    it can still fix the case."""
    import copy

    from test_cases import STAGE_BASE

    data = copy.deepcopy(STAGE_BASE)
    cases.check_case_data(data)  # control
    data["decision"]["rewrites"] = REWRITE  # a misspelt `rewrite`
    with pytest.raises(cases.CaseUsageError) as exc:
        cases.check_case_data(data)
    assert "'rewrites'" in str(exc.value)


_OPTIONAL_KEYS = ("always_loaded", "covered_by", "rewrite", "skill", "verb", "what_would_change")


def test_the_closed_set_is_exactly_the_keys_the_writer_reads():
    assert cases.DECISION_KEYS == frozenset({"because", "confidence", *_OPTIONAL_KEYS})


@pytest.mark.parametrize("key", _OPTIONAL_KEYS)
def test_every_known_decision_key_is_still_accepted(tmp_path, key):
    """The closed set is not narrower than what the writer already read:
    each known key, given a well-formed value, records (on master the first
    four are controls; `rewrite` and `skill` were silently dropped)."""
    values = {
        "verb": "reject",
        "covered_by": "claude-md:user",
        "what_would_change": ["a later fire"],
        "always_loaded": {"always_applies": {"because": "any session", "refs": ["transcript:9c1e#L2210"]}},
        "rewrite": REWRITE,
        "skill": SKILL,
    }
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home, overrides={f"decision.{key}": values[key]})
    assert cases.CASE_ID_RE.match(case_id)


# ------------------------------------------------------- decision.rewrite


def test_the_rewrite_block_is_rendered_and_frozen(tmp_path):
    """D-AUTHOR §2.4: rendered under the Decision section, so it is in the
    freeze hash -- an edit to the rendered account is caught as tampering."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home, outcome="replaced",
                      overrides={"decision.verb": "replace", "decision.rewrite": REWRITE})
    text = _case_text(home, case_id)
    decision = _decision_section(text)
    assert "Rewrite (where each idea of the old text went):" in decision
    for idea in REWRITE["ideas"]:
        assert idea["idea"] in decision
    assert "→ field:verified_how" in decision
    assert "→ dropped (why: said by lrn-0000beef in the same file)" in decision

    cases.show(home, case_id)  # control: the hash verifies as written
    path = next(home.glob(f"cases/*/{case_id}.md"))
    path.write_text(text.replace("→ context", "→ loaded"), encoding="utf-8")
    with pytest.raises(cases.CaseError):
        cases.show(home, case_id)


def test_a_case_without_the_new_blocks_renders_as_before(tmp_path):
    """No new block, no new line: the frozen text of an ordinary case is
    unchanged by this build, so every existing case still verifies."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    decision = _decision_section(_case_text(home, case_id))
    assert decision.startswith("- verb: reject\n- because:")
    assert "Rewrite" not in decision and "Skill:" not in decision
    rendered = cases._render_decision(dict(_write_stage_data()["decision"]))
    assert rendered == (
        "## Decision\n- verb: reject\n- because: the standing order is about the hypr "
        "subrepo\n- confidence: settled\n"
    )


def _write_stage_data() -> dict:
    import copy

    from test_cases import STAGE_BASE

    return copy.deepcopy(STAGE_BASE)


@pytest.mark.parametrize(
    "block,needle",
    [
        ({"ideas": []}, "non-empty list"),
        ({"ideas": [{"idea": "x", "now": "kept"}]}, "now must be one of"),
        ({"ideas": [{"idea": "x", "now": "field:colour"}]}, "now must be one of"),
        ({"ideas": [{"idea": "x", "now": "dropped"}]}, "needs a why"),
        ({"ideas": [{"idea": "x", "now": "dropped", "why": "  "}]}, "needs a why"),
        ({"ideas": [{"idea": "x", "now": "loaded", "weight": 2}]}, "unknown key(s) ['weight']"),
        ({"ideas": [{"now": "loaded"}]}, "idea is required text"),
        ({"ideas": [{"idea": "x", "now": "loaded"}], "summary": "y"}, "one key, ideas"),
        (["x"], "one key, ideas"),
    ],
)
def test_a_malformed_rewrite_block_is_refused_by_name(tmp_path, block, needle):
    """Shape only (D-AUTHOR §2.4): a non-empty list, `now` from the closed
    set, a `why` for every dropped idea. Nothing is written."""
    home = make_home(tmp_path)
    with pytest.raises(cases.CaseUsageError) as exc:
        _record(tmp_path, home, overrides={"decision.rewrite": block})
    assert needle in str(exc.value)
    assert not list(home.glob("cases/*/*.md"))


def test_a_secret_in_the_rewrite_block_is_refused(tmp_path):
    """The block's texts join the case's free-text scan (D-AUTHOR §2.6)."""
    home = make_home(tmp_path)
    token = "ghp_" + "Ab1" * 12
    block = {"ideas": [{"idea": f"the token was {token}", "now": "dropped", "why": "a secret"}]}
    with pytest.raises(cases.CaseError):
        _record(tmp_path, home, overrides={"decision.rewrite": block})
    assert not list(home.glob("cases/*/*.md"))
    _record(tmp_path, home, overrides={"decision.rewrite": REWRITE})  # control


def test_a_heading_line_in_the_rewrite_block_is_refused(tmp_path):
    home = make_home(tmp_path)
    block = {"ideas": [{"idea": "x", "now": "dropped", "why": "first\n## Application\nforged"}]}
    with pytest.raises(cases.CaseError) as exc:
        _record(tmp_path, home, overrides={"decision.rewrite": block})
    assert "heading" in str(exc.value)


# --------------------------------------------------------- decision.skill


def test_the_skill_block_is_rendered_and_checked(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home, outcome="route", overrides={"decision.skill": SKILL})
    decision = _decision_section(_case_text(home, case_id))
    assert "Skill: drawing-diagrams — two lessons share one procedure" in decision
    assert "- lessons: lrn-08ed825b" in decision
    for block, needle in (
        ({"name": "Drawing Diagrams", "why": "x"}, "kebab-case"),
        ({"name": "d", "why": ""}, "why is required"),
        ({"name": "d", "why": "x", "lessons": ["nope"]}, "lrn-... ids"),
        ({"name": "d", "why": "x", "tags": []}, "unknown key(s) ['tags']"),
    ):
        with pytest.raises(cases.CaseUsageError) as exc:
            _record(tmp_path, home, overrides={"decision.skill": block})
        assert needle in str(exc.value)


# ------------------------------------------- the runner's required-block rule


def test_a_case_with_a_replace_line_needs_the_rewrite_block():
    """D-AUTHOR §6.2: required on a case with a `replace` item. The case
    writer cannot see the sheet; the runner asks this pure check."""
    case = _write_stage_data()
    items = [{"id": "lrn-08ed825b", "verb": "replace", "because": "shorter"}]
    problem = cases.rewrite_required_problem(case, items, label="case-x.yaml")
    assert problem is not None and "needs decision.rewrite" in problem
    assert "case-x.yaml" in problem
    case["decision"]["rewrite"] = REWRITE
    assert cases.rewrite_required_problem(case, items) is None
    case["decision"]["rewrite"] = {"ideas": []}
    assert "non-empty list" in cases.rewrite_required_problem(case, items)
    # no replace line, or a parked case: nothing to ask
    del case["decision"]["rewrite"]
    assert cases.rewrite_required_problem(case, [{"id": "lrn-08ed825b", "verb": "reject"}]) is None
    case["kind"] = "parked"
    assert cases.rewrite_required_problem(case, items) is None
