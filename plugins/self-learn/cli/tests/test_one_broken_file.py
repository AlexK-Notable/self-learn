"""2026-09-26 (agenda item 18 = N8, N9): one broken file no longer ends a
whole batch.

N8. A USER-scope claude-md route whose target CLAUDE.md already carries a
managed region with no compile record computes the region self-learn would
have written (`_expected_managed_region` -> `_compile_set` ->
`_target_matched_records` -> `managed_target_for`); with a routed
skill-scope claude-md lesson in the ledger that reads `hosts.yaml`. A
malformed `hosts.yaml` now refuses THAT item (`needs-person`), and the
sheet's other items apply.

N9. The compile-set readers skip a resolved record whose frontmatter is
not YAML, as they already skipped one that failed to validate.

Sandbox ledgers under pytest's tmpdir (`support.make_env`); HOME points
into the tmpdir, so the user CLAUDE.md is a sandbox file.
"""

from __future__ import annotations

import pytest

from self_learn import batch, verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.ledger_ops import create_record, find_record_path, write_proposal
from self_learn.records import Record
from support import commit_all, make_behavior, make_env, proposal_dict

MALFORMED_HOSTS = "skills_root: [unclosed\n"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _env(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    return env


def _seed(home, rid, *, scope="skill:s", destination=None):
    create_record(home, make_behavior(record_id=rid, scope=scope))
    fields = {"destination": destination} if destination else {}
    write_proposal(home, rid, proposal_dict(scope=scope, **fields))
    commit_all(home, f"seed {rid}")
    return rid


def _run(home, tmp_path, body):
    path = tmp_path / "sheet.yaml"
    path.write_text("version: 1\nitems:\n" + body, encoding="utf-8")
    return batch.run(home, batch.load_sheet(path), no_push=True)


def _user_claude_md_with_an_unrecorded_region(tmp_path):
    target = tmp_path / "home" / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        f"# me\n\n{BEGIN_MARKER}\n- a rule nobody recorded\n{END_MARKER}\n", encoding="utf-8"
    )
    return target


def test_n8_a_malformed_hosts_yaml_refuses_the_user_route_not_the_sheet(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    skill_claude = _seed(env.ledger, "lrn-d1000001")
    verbs.route(env.ledger, skill_claude, dest="claude-md", no_push=True)
    assert Record.from_path(find_record_path(env.ledger, skill_claude)).status == "routed"
    user = _seed(env.ledger, "lrn-d1000002", scope="user", destination="claude-md")
    plain = _seed(env.ledger, "lrn-d1000003")
    _user_claude_md_with_an_unrecorded_region(tmp_path)
    (env.ledger / "hosts.yaml").write_text(MALFORMED_HOSTS, encoding="utf-8")

    result = _run(
        env.ledger, tmp_path,
        f"  - id: {user}\n    verb: route\n    dest: claude-md\n"
        f"  - id: {plain}\n    verb: reject\n",
    )

    first, second = result.items
    assert first.state == "refused", (first.state, first.detail)
    assert first.kind == "needs-person", (first.kind, first.detail)
    assert "hosts.yaml" in (first.detail or "")
    assert second.state == "applied", (second.state, second.detail)
    assert Record.from_path(find_record_path(env.ledger, plain)).status == "rejected"


@pytest.mark.parametrize("dest", ["skill-md", "claude-md"])
def test_n9_a_resolved_record_whose_frontmatter_is_not_yaml_is_skipped(
    tmp_path, monkeypatch, dest
):
    env = _env(tmp_path, monkeypatch)
    first = _seed(env.ledger, "lrn-d1000004")
    second = _seed(env.ledger, "lrn-d1000005")
    resolved = find_record_path(env.ledger, first).parent.parent / "resolved"
    resolved.mkdir(exist_ok=True)
    broken = resolved / "lrn-d10000ff.md"
    broken.write_text("---\nid: [unclosed\n---\n\nbody\n", encoding="utf-8")
    commit_all(env.ledger, "a resolved file that is not YAML")
    with pytest.raises(Exception) as caught:  # positive control: it does not read
        Record.from_path(broken)
    assert "YAML" in type(caught.value).__name__ or "yaml" in type(caught.value).__module__

    result = _run(
        env.ledger, tmp_path,
        f"  - id: {first}\n    verb: route\n    dest: {dest}\n"
        f"  - id: {second}\n    verb: reject\n",
    )

    one, two = result.items
    assert one.state == "applied", (one.state, one.detail)
    assert two.state == "applied", (two.state, two.detail)
    assert Record.from_path(find_record_path(env.ledger, first)).status == "routed"
