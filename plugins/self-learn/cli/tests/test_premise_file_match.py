"""Lane P6 (S-104 amended 2026-10-31): a `file-match`/`git-file` premise that can
never fire is refused at validation, by name. The probes read the token
`present`/`absent` (or a line-range hash), so a literal `match` is never
found in the value."""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import premise_tool, premises
from self_learn.premises import ProbeEnv
from self_learn.records import ValidationError
from support import make_behavior


def _p(kind: str, probe_extra: dict, **extra) -> list[dict]:
    probe = {"kind": kind, "path": "/etc/x.conf"}
    if kind == "git-file":
        probe["repo"] = "/etc"
        probe["path"] = "x.conf"
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
        with pytest.raises(premises.PremiseError, match="can never be judged"):
            premises.validate_premises(_p(kind, probe_extra, holds_if=holds_if, match="BindsTo=x"))

    def test_the_refusal_names_the_form(self, kind):
        with pytest.raises(premises.PremiseError, match="holds_if: equals` with `match: absent"):
            premises.validate_premises(
                _p(kind, {"contains": "x"}, holds_if="absent", match="x"))

    @pytest.mark.parametrize("holds_if", ["equals", "present", "absent"])
    def test_lines_take_changed_only(self, kind, holds_if):
        with pytest.raises(premises.PremiseError, match="only holds_if changed"):
            premises.validate_premises(
                _p(kind, {"lines": "1-2"}, holds_if=holds_if, match="absent"))

    def test_equals_with_a_literal_is_refused(self, kind):
        with pytest.raises(premises.PremiseError, match="can never be judged"):
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


def test_a_token_form_is_told_to_write_equals():
    with pytest.raises(premises.PremiseError, match="write it as `holds_if: equals` with `match: present`"):
        premises.validate_premises(
            _p("file-match", {"contains": "x"}, holds_if="present", match="present"))


def test_an_old_record_still_loads_without_policy():
    # structure at load, policy at write: the refusal is policy
    premises.validate_premises(
        _p("file-match", {"contains": "x"}, holds_if="absent", match="x"), policy=False)


def test_the_record_path_refuses():
    record = make_behavior(record_id="lrn-0000000d")
    with pytest.raises(ValidationError, match="can never be judged"):
        record.set_premises(_p("file-match", {"contains": "x"}, holds_if="absent", match="x"))
    with pytest.raises(premises.PremiseError, match="can never be judged"):
        premises.normalize_premises(
            _p("git-file", {"line": "x"}, holds_if="equals", match="x"))


def test_the_tool_refuses_and_names_the_form(tmp_path: Path):
    tool = premise_tool.PremiseProbeTool(
        tmp_path / "no-ledger",
        env=ProbeEnv(home=tmp_path, now=lambda: "2026-10-30T00:00:00Z"),
    )
    reply = tool.dispatch({"probe": {"kind": "file-match", "path": str(tmp_path / "f"),
                                     "contains": "x"}, "holds_if": "absent", "match": "x"})
    assert reply.is_error
    assert "holds_if: equals" in reply.text


def test_equals_absent_holds_while_the_literal_is_not_found_and_moves_when_it_appears(
    tmp_path: Path,
):
    conf = tmp_path / "app.conf"
    conf.write_text("Type=simple\n", encoding="utf-8")
    env = ProbeEnv(home=tmp_path, now=lambda: "2026-10-30T00:00:00Z")
    premise = {"id": "p1", "claim": "c", "holds_if": "equals", "match": "absent",
               "probe": {"kind": "file-match", "path": "~/app.conf", "contains": "BindsTo=x"}}
    premises.validate_premises([premise])
    first = premises.observe(premise, env)
    assert first.claim == premises.CLAIM_HOLDS
    premise["baseline"] = premises.make_baseline(first)
    conf.write_text("Type=simple\nBindsTo=x\n", encoding="utf-8")
    second = premises.observe(premise, env)
    assert second.claim == premises.CLAIM_CONTRADICTED
    assert premises.verdict(premise, second) == "moved"


def test_an_old_record_form_observes_unavailable_not_judged(tmp_path: Path):
    conf = tmp_path / "app.conf"
    conf.write_text("BindsTo=x\n", encoding="utf-8")
    env = ProbeEnv(home=tmp_path, now=lambda: "2026-10-30T00:00:00Z")
    premise = {"id": "p1", "claim": "c", "holds_if": "absent", "match": "BindsTo=x",
               "probe": {"kind": "file-match", "path": "~/app.conf",
                         "contains": "BindsTo=x"}}
    premises.validate_premises([premise], policy=False)
    obs = premises.observe(premise, env)
    assert obs.state == premises.OBS_UNAVAILABLE
    assert "invalid premise" in obs.reason
