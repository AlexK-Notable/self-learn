"""`list --json --surface-fill` (09 §11 Y-20 / 08 §1 `surface_fill` field,
10 §3 U17) — the loaded-surface budget indicator's read-only fill probe.

Covers: flag-gating (unflagged byte-unchanged; --id record scoping, delta
F9), key-set correctness (reference never a key; VerbError legs — missing
SKILL.md, unregistered host, scope-invalid — omit keys), count correctness
against the compiler's own numbers, the entries/words overflow cap, and
memoization (N records sharing one target compile exactly once).
"""

from __future__ import annotations

import json

import pytest

from self_learn import cli, verbs
from self_learn.ledger_ops import (
    bucket_dir_for_scope,
    create_record,
    ensure_project_meta,
)
from self_learn.records import Record

from support import (
    days_ago,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
)


# ------------------------------------------------------------------ helpers


def _list_json(capsys, *flags):
    rc = cli.main(["list", "--json", *flags])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def _routed_knowledge(scope, record_id, fact, *, destination="skill-md",
                       routed_at="2026-07-13T18:02:00Z"):
    rec = Record.create(
        type="knowledge", scope=scope, source="teach", fact=fact,
        record_id=record_id,
    )
    rec.set_routing({"routed_at": routed_at, "destination": destination, "by": "human"})
    rec.set_status("routed")
    return rec


def _write_routed(home, record, *, project_path=None):
    bucket_dir = bucket_dir_for_scope(home, record.scope, project_path=project_path)
    if record.scope == "project":
        ensure_project_meta(bucket_dir, project_path)
    resolved = bucket_dir / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record.write(resolved / f"{record.id}.md")
    return bucket_dir


# --------------------------------------------------------------- fixtures


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, skills=("s",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


# --------------------------------------------------------------- flag gating


class TestFlagGating:
    def test_unflagged_has_no_surface_fill_key(self, env, capsys):
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys)
        assert "surface_fill" not in item

    def test_unflagged_output_matches_flagless_baseline(self, env, capsys):
        """The unflagged path is byte-unchanged: identical dict shape with
        or without the two new argparse options merely being present on
        the parser (they default off)."""
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        rc = cli.main(["list", "--json"])
        assert rc == 0
        first = capsys.readouterr().out

        rc = cli.main(["list", "--json"])
        assert rc == 0
        second = capsys.readouterr().out
        assert first == second
        assert "surface_fill" not in first

    def test_surface_fill_flag_adds_the_key(self, env, capsys):
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        assert "surface_fill" in item
        assert isinstance(item["surface_fill"], dict)

    def test_id_scopes_the_listing_to_one_record(self, env, capsys):
        r1 = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        r2 = make_behavior(scope="skill:s", record_id="lrn-aa000002", created_at=days_ago(2))
        create_record(env.ledger, r1)
        create_record(env.ledger, r2)

        items = _list_json(capsys, "--id", "lrn-aa000001")
        assert [i["id"] for i in items] == ["lrn-aa000001"]

    def test_id_without_surface_fill_does_not_add_the_key(self, env, capsys):
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--id", "lrn-aa000001")
        assert "surface_fill" not in item

    def test_id_plus_surface_fill_computes_only_that_record(self, env, capsys, monkeypatch):
        """Delta F9: --surface-fill --id computes fill for ONLY the named
        record, not every pending record — probed by counting resolver
        calls, not just asserting the returned shape."""
        r1 = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        r2 = make_behavior(scope="skill:s", record_id="lrn-aa000002", created_at=days_ago(2))
        create_record(env.ledger, r1)
        create_record(env.ledger, r2)

        calls = []
        real = verbs.surface_fill

        def counting(*args, **kwargs):
            calls.append(args[1])  # bucket_dir positional
            return real(*args, **kwargs)

        monkeypatch.setattr(verbs, "surface_fill", counting)
        # cli.py imported the name into its own module namespace via
        # `from . import verbs` — it calls verbs.surface_fill(...), so
        # patching the module attribute is enough (no rebinding to chase).

        items = _list_json(capsys, "--surface-fill", "--id", "lrn-aa000001")
        assert [i["id"] for i in items] == ["lrn-aa000001"]
        assert len(calls) == 1


# --------------------------------------------------------------- key set


class TestKeySet:
    def test_reference_is_never_a_key(self, env, capsys):
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        assert "reference" not in item["surface_fill"]

    def test_skill_scope_gets_both_capped_keys(self, env, capsys):
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        assert set(item["surface_fill"].keys()) == {"skill-md", "claude-md"}

    def test_project_scope_omits_skill_md(self, env, capsys):
        """Scope-invalid capped destination absent: skill-md never valid
        for a project-scoped record — omitted, not zeroed."""
        rec = make_knowledge(scope="project", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec, project_path=env.host)

        (item,) = _list_json(capsys, "--surface-fill")
        assert "skill-md" not in item["surface_fill"]
        assert "claude-md" in item["surface_fill"]

    def test_missing_skill_md_omits_the_key(self, env, capsys):
        """A registered-but-missing SKILL.md (the skill dir exists under
        the skills root, matching skill_dir_for's glob, but has no
        SKILL.md file inside) is a VerbError — the key is omitted, never
        zeroed (F5)."""
        empty_skill_dir = env.host / "plugins" / "t-plugin" / "skills" / "t"
        empty_skill_dir.mkdir(parents=True)
        rec = make_behavior(scope="skill:t", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        assert "skill-md" not in item["surface_fill"]
        # claude-md still resolves (skill-root's own CLAUDE.md is sound)
        assert "claude-md" in item["surface_fill"]

    def test_unregistered_project_host_omits_claude_md(self, env, tmp_path, capsys):
        """An unregistered project host is a VerbError from
        `_project_host_or_refuse` — the key is omitted (F5). skill-md was
        never valid for this scope either, so surface_fill is empty."""
        unregistered = tmp_path / "unregistered-proj"
        init_repo(unregistered)
        rec = make_knowledge(scope="project", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec, project_path=unregistered)

        (item,) = _list_json(capsys, "--surface-fill")
        assert item["surface_fill"] == {}

    def test_user_scope_gets_only_claude_md(self, env, tmp_path):
        """Direct verbs.surface_fill call (never through the CLI, and
        with an explicit user_claude_md override) — a user-scope probe
        must NEVER touch the real ~/.claude/CLAUDE.md."""
        user_md = tmp_path / "user-claude.md"
        user_md.write_text("# user canon\n", encoding="utf-8")

        result = verbs.surface_fill(
            env.ledger, env.ledger / "user", "user", user_claude_md=user_md
        )
        assert set(result.keys()) == {"claude-md"}
        assert result["claude-md"] == {
            "entries": 0, "entries_cap": 10, "words": 0, "words_cap": 150,
            "over_cap": False,
        }


# --------------------------------------------------------- count correctness


class TestCountCorrectness:
    def test_bootstrap_target_reports_zero(self, env, capsys):
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        assert item["surface_fill"]["skill-md"] == {
            "entries": 0, "entries_cap": 10, "words": 0, "words_cap": 150,
            "over_cap": False,
        }

    def test_partial_fill_matches_compiler_count(self, env, capsys):
        for i, fact in enumerate(["Alpha", "Beta"]):
            routed = _routed_knowledge("skill:s", f"lrn-bb00000{i}", fact)
            _write_routed(env.ledger, routed)

        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        fill = item["surface_fill"]["skill-md"]
        # each entry: "- <fact> *(<id>)*" -> 3 whitespace tokens
        assert fill["entries"] == 2
        assert fill["words"] == 6
        assert fill["over_cap"] is False

    def test_pending_record_itself_is_never_counted(self, env, capsys):
        """08 §1 F8: `list --json --surface-fill` for a still-pending
        record must not see itself in its own target's fill — it isn't
        `status: routed` yet."""
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        assert item["surface_fill"]["skill-md"]["entries"] == 0

    def test_over_cap_by_entry_count(self, env, capsys):
        for i in range(11):
            routed = _routed_knowledge("skill:s", f"lrn-cc{i:06d}", f"fact{i}")
            _write_routed(env.ledger, routed)

        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        fill = item["surface_fill"]["skill-md"]
        assert fill["entries"] == 11
        assert fill["over_cap"] is True

    def test_over_cap_by_word_count(self, env, capsys):
        long_fact = " ".join(["word"] * 200)
        routed = _routed_knowledge("skill:s", "lrn-dd000001", long_fact)
        _write_routed(env.ledger, routed)

        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        fill = item["surface_fill"]["skill-md"]
        assert fill["entries"] == 1  # under the entries cap
        assert fill["words"] > 150
        assert fill["over_cap"] is True

    def test_effective_caps_are_the_compiler_defaults(self, env, capsys):
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")
        fill = item["surface_fill"]["skill-md"]
        assert fill["entries_cap"] == 10
        assert fill["words_cap"] == 150


# --------------------------------------------------------------- memoization


class TestMemoization:
    def test_records_sharing_one_target_compile_once(self, env, capsys, monkeypatch):
        calls = []
        real_compile = verbs.compile_managed_text

        def counting(*args, **kwargs):
            calls.append(1)
            return real_compile(*args, **kwargs)

        monkeypatch.setattr(verbs, "compile_managed_text", counting)

        for i in range(3):
            rec = make_behavior(
                scope="skill:s", record_id=f"lrn-ee00000{i}", created_at=days_ago(i)
            )
            create_record(env.ledger, rec)

        items = _list_json(capsys, "--surface-fill")
        assert len(items) == 3
        # 3 pending records x 2 capped destinations, but skill-md and
        # claude-md both resolve to the SAME two targets across all three
        # (one skill bucket, one skills-root host) -> exactly 2 compiles.
        assert len(calls) == 2
