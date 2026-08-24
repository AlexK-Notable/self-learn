"""`list --json --surface-fill` (09 §11 Y-20 / 08 §1 `surface_fill` field,
10 §3 U17) — the loaded-surface budget indicator's read-only fill probe.

Covers: flag-gating (unflagged byte-unchanged; --id record scoping, delta
F9), key-set correctness (reference never a key; VerbError/CompileError
legs — missing SKILL.md, unregistered host, scope-invalid, a corrupted
managed-section marker pair — omit keys without crashing the whole `list`
call), count correctness against the compiler's own numbers, the
entries/words overflow cap, and memoization (N records sharing one target
compile exactly once).

Hygiene trap (blind-review F5): ``verbs.surface_fill`` resolves a
user-scope ``claude-md`` target to the REAL chezmoi-managed
``~/.claude/CLAUDE.md`` unless ``user_claude_md`` is explicitly
overridden — exactly like every other ``_resolve_target`` call site
(``route`` included). Never call it, or ``cli._add_surface_fill``, on a
user-scope record without passing ``user_claude_md`` — a CLI-path test
that forgets this reads (never writes) the real file.
"""

from __future__ import annotations

import json

import pytest

from self_learn import cli, verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
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

    def test_unflagged_list_is_deterministic_across_repeated_calls(self, env, capsys):
        """The unflagged path is byte-unchanged and deterministic: two
        back-to-back unflagged calls, with the two new argparse options
        merely present on the parser (defaulted off), produce identical
        output — no `surface_fill` key crept in either."""
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

    def test_reference_probe_is_never_even_attempted(self, env, capsys, monkeypatch):
        """F4: strengthen the above — a mutation that adds "reference" to
        SURFACE_FILL_CAPPED_DESTINATIONS is otherwise absorbed by the
        target-is-None guard inside surface_fill (the key never makes it
        into the object, so the assertion above still passes), which
        means that assertion alone does NOT kill the mutation. Spy on the
        resolver itself and assert "reference" is never among the
        destinations it was asked to resolve at all."""
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        probed: list[str] = []
        real_resolve = verbs._resolve_target

        def spying(home, bucket_dir, scope, destination, ref_name, **kwargs):
            probed.append(destination)
            return real_resolve(home, bucket_dir, scope, destination, ref_name, **kwargs)

        monkeypatch.setattr(verbs, "_resolve_target", spying)

        _list_json(capsys, "--surface-fill")
        assert "reference" not in probed
        assert set(probed) == {"skill-md", "claude-md"}

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
            # A2 §8: the raw topic-file count, claude-md only — 0 here,
            # no ~/.claude/rules/ dir under the tmp_path override.
            "rules_topic_count": 0,
            # U-glob §5.3: the co-firing datum, empty for a missing
            # rules dir — no trigger fires, no cap_reason key.
            "rules_cofire": {
                "topics": [], "unpathed": [], "pairs": [], "max_fanin": 0,
            },
        }


# ------------------------------------------------------------ degraded legs


class TestDegradedLegs:
    def test_corrupted_marker_pair_omits_the_key_without_crashing_list(
        self, env, capsys
    ):
        """F2 (blind-review, live-demonstrated): a corrupted managed-
        section marker pair (two BEGIN markers, one END) makes
        `compile_managed_text` raise `CompileError` — that must degrade
        exactly like a `VerbError` (omit this ONE destination's key) and
        must NOT crash the whole `list --json` call. Before the fix this
        propagated uncaught, `list` exited non-zero, and the UI's
        `_load_detail` fell back to a synthesized item that loses the
        ENTIRE proposal/why/change region for every record sharing that
        target — not just the corrupted one."""
        env.skill_md.write_text(
            f"{BEGIN_MARKER}\nstray\n{BEGIN_MARKER}\nstray2\n{END_MARKER}\n",
            encoding="utf-8",
        )
        rec = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        create_record(env.ledger, rec)

        (item,) = _list_json(capsys, "--surface-fill")  # asserts rc == 0
        assert "skill-md" not in item["surface_fill"]
        # claude-md is a DIFFERENT target (the skills-root host's own
        # CLAUDE.md) — untouched by the skill-md corruption, still present.
        assert "claude-md" in item["surface_fill"]

    def test_corrupted_marker_pair_does_not_blank_other_records_sharing_the_target(
        self, env, capsys
    ):
        """The reviewer's exact failure mode: a SECOND pending record in
        the SAME skill bucket (so it shares the corrupted skill-md
        target) must still get a clean `list --json --surface-fill`
        response — its OWN claude-md key present, only skill-md
        omitted — not an exit-nonzero that would blank its whole Detail
        page."""
        env.skill_md.write_text(
            f"{BEGIN_MARKER}\nstray\n{BEGIN_MARKER}\nstray2\n{END_MARKER}\n",
            encoding="utf-8",
        )
        r1 = make_behavior(scope="skill:s", record_id="lrn-aa000001", created_at=days_ago(1))
        r2 = make_behavior(scope="skill:s", record_id="lrn-aa000002", created_at=days_ago(2))
        create_record(env.ledger, r1)
        create_record(env.ledger, r2)

        items = _list_json(capsys, "--surface-fill")
        assert len(items) == 2
        for item in items:
            assert "skill-md" not in item["surface_fill"]
            assert "claude-md" in item["surface_fill"]


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
