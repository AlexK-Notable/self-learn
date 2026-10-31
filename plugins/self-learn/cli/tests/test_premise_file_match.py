"""Lane P6 (S-NEXT-ft-file-match): a `file-match`/`git-file` premise that can
never fire is refused at validation, by name. The probes read the token
`present`/`absent` (or a line-range hash), so a literal `match` is never
found in the value."""

from __future__ import annotations

import pytest

from self_learn import premises


def _p(kind: str, probe_extra: dict, **extra) -> list[dict]:
    probe = {"kind": kind, "path": "/etc/x.conf"}
    if kind == "git-file":
        probe["repo"] = "/etc"
    probe.update(probe_extra)
    out = {"id": "p1", "claim": "a fact the lesson rests on", "probe": probe}
    out.update(extra)
    return [out]


KINDS = ["file-match", "git-file"]


@pytest.mark.parametrize("kind", KINDS)
class TestRefused:
    @pytest.mark.parametrize("holds_if", ["absent", "present"])
    @pytest.mark.parametrize("probe_extra", [{"contains": "BindsTo=x"}, {"line": "BindsTo=x"}])
    def test_a_literal_with_present_or_absent_is_refused(self, kind, holds_if, probe_extra):
        with pytest.raises(Exception, match="can never be judged"):
            premises.validate_premises(_p(kind, probe_extra, holds_if=holds_if, match="BindsTo=x"))

    def test_the_refusal_names_the_form(self, kind):
        with pytest.raises(Exception, match="holds_if: equals` with `match: absent"):
            premises.validate_premises(
                _p(kind, {"contains": "x"}, holds_if="absent", match="x"))

    @pytest.mark.parametrize("holds_if", ["equals", "present", "absent"])
    def test_lines_take_changed_only(self, kind, holds_if):
        with pytest.raises(Exception, match="only holds_if changed"):
            premises.validate_premises(
                _p(kind, {"lines": "1-2"}, holds_if=holds_if, match="absent"))

    def test_equals_with_a_literal_is_refused(self, kind):
        with pytest.raises(Exception, match="can never be judged"):
            premises.validate_premises(
                _p(kind, {"contains": "x"}, holds_if="equals", match="BindsTo=x"))


@pytest.mark.parametrize("kind", KINDS)
class TestAccepted:
    @pytest.mark.parametrize("match", ["present", "absent"])
    def test_equals_present_or_absent(self, kind, match):
        premises.validate_premises(_p(kind, {"contains": "x"}, holds_if="equals", match=match))
        premises.validate_premises(_p(kind, {"line": "x"}, holds_if="equals", match=match))

    def test_changed_default_and_lines(self, kind):
        premises.validate_premises(_p(kind, {"contains": "x"}))
        premises.validate_premises(_p(kind, {"lines": "1-2"}, holds_if="changed"))


def test_other_probe_kinds_keep_present_and_absent():
    # control: the new check is scoped to the token-valued probes
    premises.validate_premises([{
        "id": "p1", "claim": "c", "probe": {"kind": "which", "name": "git"},
        "holds_if": "absent", "match": "x"}])


def test_equals_absent_holds_while_the_literal_is_not_found_and_moves_when_it_appears():
    premise = {"id": "p1", "claim": "c", "holds_if": "equals", "match": "absent"}
    assert premises._judge(premise, premises.ABSENT) == premises.CLAIM_HOLDS
    assert premises._judge(premise, premises.PRESENT) == premises.CLAIM_CONTRADICTED
