"""U-pointer: reference-route pointer emission, the ALWAYS-surface write,
and the R14 backfill (docs/specs/self-learn/drafts/
u-pointer-reference-pointer-spec.md, r3).

Test names/docstrings below cross-reference the spec's §4 criterion ids
(A1-A9, B1-B5, C1-C7, D1-D3, E1-E8, F1-F8) so the mutation sweep (§5) can
find its target directly. G1 (suite + pyright) and G2 (no new literals)
are not per-test criteria -- G1 is the whole-suite run itself; G2 is
self-enforced by importing every marker/label/cap from `compilers`/
`verbs` throughout this file rather than retyping any of them.
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from self_learn import cli, selfcheck, verbs
from self_learn import compilers as compilers_mod
from self_learn.compilers import (
    BEGIN_MARKER,
    END_MARKER,
    POINTER_BEGIN_MARKER,
    POINTER_END_MARKER,
    CompileError,
    ReferenceResult,
    apply_pointer,
    compile_managed_text,
    compile_pointer_text,
    compile_reference,
    pointer_line,
    pointer_token,
    surface_names_target,
)
from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import create_record, resolve_record
from self_learn.records import Record
from self_learn.selfcheck import _loaded_surface
from self_learn.verbs import POINTER_LABELS, TargetSpec

from support import commit_all, git, make_behavior, make_env, make_knowledge, verb_files


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


# --------------------------------------------------------------- helpers


def _write_bad_bytes(path: Path, prefix: str = "") -> None:
    """`prefix` (valid UTF-8) + a byte that is not a valid UTF-8 lead byte
    anywhere -- guaranteed to raise ``UnicodeDecodeError`` on decode (same
    fixture shape as test_selftest.py's own ``_write_bad_bytes``)."""
    path.write_bytes(prefix.encode("utf-8") + b"\xff\xfe garbage")


def _skill_fixture(tmp_path: Path, name: str = "s") -> tuple[Path, Path]:
    skill_dir = tmp_path / "plugins" / "p" / "skills" / name
    skill_dir.mkdir(parents=True)
    surface = skill_dir / "SKILL.md"
    surface.write_text(f"# {name} skill\n\nAuthored prose stays put.\n", encoding="utf-8")
    target = skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Learnings\n", encoding="utf-8")
    return surface, target


def _project_fixture(tmp_path: Path, name: str = "host") -> tuple[Path, Path]:
    host = tmp_path / name
    host.mkdir()
    surface = host / "CLAUDE.md"
    surface.write_text("# host project\n\nAuthored context stays put.\n", encoding="utf-8")
    target = host / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Learnings\n", encoding="utf-8")
    return surface, target


def _routed_record(scope: str = "skill:s", n: int = 0) -> Record:
    record = make_knowledge(scope=scope, record_id=f"lrn-{n:08x}" if n else None,
                             fact=f"fact number {n} for regeneration fixtures.")
    destination = "skill-md" if scope.startswith("skill:") else "claude-md"
    record.set_routing({
        "routed_at": "2026-08-09T00:00:00Z", "destination": destination, "by": "human",
    })
    record.set_status("routed")
    return record


def _seed_skill_reference_record(
    env, *, entry_present: bool = True, pointer_present: bool = False,
    fact: str = "captured fact for the R14 backfill fixture.",
) -> Record:
    """A skill-scope reference-routed record -- the R14 shape when
    ``entry_present=True, pointer_present=False``: the ledger says
    ``reference``, the entry already lives in LEARNINGS.md, and SKILL.md
    names nothing. Commits the host so a later dirty-check sees a clean
    tree unless the caller dirties it afterwards."""
    record = make_knowledge(scope="skill:s", fact=fact)
    create_record(env.ledger, record)
    resolve_record(
        env.ledger, record.id, "routed",
        destination="reference", by="human", routed_at="2026-08-09T00:00:00Z",
        reference_file=None,
    )
    resolved = Record.from_path(
        env.ledger / "skills" / "s" / "resolved" / f"{record.id}.md"
    )
    refs_dir = env.skill_dir / "references"
    if entry_present:
        compile_reference(refs_dir, resolved)
    if pointer_present:
        apply_pointer(
            env.skill_md, refs_dir / "LEARNINGS.md", label=POINTER_LABELS["skill"]
        )
    if git(env.host, "status", "--porcelain").stdout.strip():
        commit_all(env.host, "seed R14-shape fixture")
    return resolved


# ============================================================ A. contract


class TestPointerContract:
    def test_a1_move_is_a_move_not_a_rewrite(self):
        """A1: identity, not equality. M1 copies the predicate's body into
        selfcheck.py instead of importing it -- the six behaviour
        assertions in test_selftest.py:296-332 (`selfcheck._surface_names_
        target(...)`) would still pass under M1 (a faithful copy behaves
        identically); only this identity leg tells the two apart."""
        assert selfcheck._surface_names_target is compilers_mod.surface_names_target

    def test_a2_token_form_both_live_scopes(self, tmp_path):
        skill_surface, skill_target = _skill_fixture(tmp_path)
        assert pointer_token(skill_surface, skill_target) == "references/LEARNINGS.md"

        proj_surface, proj_target = _project_fixture(tmp_path)
        assert pointer_token(proj_surface, proj_target) == "references/LEARNINGS.md"

    def test_a3_post_condition_is_the_contract(self, tmp_path):
        for surface, target in (_skill_fixture(tmp_path), _project_fixture(tmp_path)):
            # vacuity guard: False before the call, on the SAME fixture.
            assert surface_names_target(surface, target) is False
            apply_pointer(surface, target, label=POINTER_LABELS["skill"])
            assert selfcheck._surface_names_target(surface, target) is True

    @pytest.mark.parametrize("bad_token", [
        "LEARNINGS.md",
        "../references/LEARNINGS.md",
        "docs/LEARNINGS.md",
        "references/myLEARNINGS.md",
    ])
    def test_a4_negative_controls_token_is_load_bearing(self, tmp_path, bad_token):
        surface, target = _skill_fixture(tmp_path)
        surface.write_text(
            surface.read_text(encoding="utf-8") + f"\nsee {bad_token}\n",
            encoding="utf-8",
        )
        assert surface_names_target(surface, target) is False

    def test_a5_block_shape_on_empty_surface(self, tmp_path):
        skill_dir = tmp_path / "plugins" / "p" / "skills" / "s"
        skill_dir.mkdir(parents=True)
        surface = skill_dir / "SKILL.md"
        surface.write_text("", encoding="utf-8")
        target = skill_dir / "references" / "LEARNINGS.md"
        target.parent.mkdir(parents=True)
        target.write_text("x\n", encoding="utf-8")

        result = apply_pointer(surface, target, label=POINTER_LABELS["skill"])

        text = surface.read_text(encoding="utf-8")
        assert text.count(POINTER_BEGIN_MARKER) == 1
        assert text.count(POINTER_END_MARKER) == 1
        assert text.index(POINTER_BEGIN_MARKER) < text.index(POINTER_END_MARKER)
        lines = [ln for ln in text.splitlines() if ln.startswith("- `")]
        assert lines == [
            pointer_line("references/LEARNINGS.md", POINTER_LABELS["skill"])

        ]
        assert result.bootstrapped is True
        assert text.endswith("\n") and not text.endswith("\n\n")

    def test_a5b_block_preamble_present_and_nonvacuous(self, tmp_path):
        """§3.1 P-BLOCK / NOTE 6 (closes carried X5): the block's preamble
        text has no criterion of its own -- `_POINTER_PREAMBLE = ""`
        would survive every other A/B assertion untouched. The non-empty
        leg is load-bearing, not decorative: with an emptied preamble
        the `in` check below passes VACUOUSLY (an empty string is a
        substring of anything), so without it this test would be
        vacuous under exactly the mutation it exists to catch."""
        preamble = compilers_mod._POINTER_PREAMBLE
        assert preamble != ""  # load-bearing -- see docstring

        surface, target = _skill_fixture(tmp_path)
        apply_pointer(surface, target, label=POINTER_LABELS["skill"])

        text = surface.read_text(encoding="utf-8")
        assert preamble in text

    def test_a6_absolute_dest_leg_home_and_non_home(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        surface1, _ = _skill_fixture(tmp_path, name="s1")
        under_home = fake_home / ".cache" / "self-learn" / "LEARNINGS.md"
        under_home.parent.mkdir(parents=True)
        under_home.write_text("x\n", encoding="utf-8")
        assert pointer_token(surface1, under_home) == "~/.cache/self-learn/LEARNINGS.md"
        apply_pointer(surface1, under_home, label=POINTER_LABELS["skill"])
        assert surface_names_target(surface1, under_home) is True

        surface2, _ = _skill_fixture(tmp_path, name="s2")
        outside = tmp_path / "elsewhere" / "LEARNINGS.md"
        outside.parent.mkdir(parents=True)
        outside.write_text("y\n", encoding="utf-8")
        assert pointer_token(surface2, outside) == str(outside)
        apply_pointer(surface2, outside, label=POINTER_LABELS["skill"])
        assert surface_names_target(surface2, outside) is True

    def test_a7_broken_markers_refuse(self):
        two_begins = (
            f"{POINTER_BEGIN_MARKER}\n{POINTER_BEGIN_MARKER}\nx\n{POINTER_END_MARKER}\n"
        )
        with pytest.raises(CompileError) as exc:
            compile_pointer_text(two_begins, "- `x` — y")
        msg = str(exc.value)
        assert "begin" in msg and "end" in msg
        assert "2 begin" in msg and "1 end" in msg

        end_before_begin = f"{POINTER_END_MARKER}\n{POINTER_BEGIN_MARKER}\n"
        with pytest.raises(CompileError, match="end marker precedes begin marker"):
            compile_pointer_text(end_before_begin, "- `x` — y")

    def test_a8_post_condition_fires_and_reverts(self, tmp_path):
        surface, target = _skill_fixture(tmp_path)
        before = surface.read_text(encoding="utf-8")
        assert surface_names_target(surface, target) is False

        with mock.patch.object(compilers_mod, "pointer_token", return_value="nope/NOWHERE.md"):
            with pytest.raises(CompileError) as exc:
                apply_pointer(surface, target, label=POINTER_LABELS["skill"])
        msg = str(exc.value)
        assert str(surface) in msg
        assert str(target) in msg
        assert "nope/NOWHERE.md" in msg
        assert "the write was reverted" in msg  # r4 NOTE 1: honest clause, restore succeeded

        # r3 (NOTE 4): the surface is byte-unchanged after the raise.
        assert surface.read_text(encoding="utf-8") == before

    def test_a8x_restore_failure_does_not_mask_compile_error(self, tmp_path, monkeypatch):
        """MAJOR 1 (r4 fold): if the restore write ITSELF fails (e.g.
        OSError/ENOSPC), the OSError must not escape and mask the
        CompileError -- an unmasked OSError would leave the wedged
        surface on disk, which later routes/recompiles refuse, blocking
        its own repair. Same post-condition trigger as test_a8 (mock
        `pointer_token` so the written token cannot resolve); this test
        additionally makes the restore write -- and only the restore
        write -- fail."""
        surface, target = _skill_fixture(tmp_path)
        original_text = surface.read_text(encoding="utf-8")
        real_write_text = Path.write_text

        def flaky_write_text(self, data, *args, **kwargs):
            if self == surface and data == original_text:
                raise OSError("ENOSPC (simulated): restore write failed")
            return real_write_text(self, data, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", flaky_write_text)

        with mock.patch.object(compilers_mod, "pointer_token", return_value="nope/NOWHERE.md"):
            with pytest.raises(CompileError) as exc:
                apply_pointer(surface, target, label=POINTER_LABELS["skill"])
        msg = str(exc.value)
        assert "post-condition failed" in msg
        # r4 NOTE 1: the honest failure clause, not the (false) reverted one.
        assert "could NOT be reverted" in msg
        assert "the write was reverted" not in msg

    def test_a9_no_write_path_reports_usable_token(self, tmp_path):
        surface, target = _skill_fixture(tmp_path)
        apply_pointer(surface, target, label=POINTER_LABELS["skill"])

        result = apply_pointer(surface, target, label=POINTER_LABELS["skill"])
        assert result.changed is False
        assert result.token == pointer_token(surface, target)
        assert result.token not in ("", None)


# ==================================== B. non-interference w/ managed section


class TestManagedSectionNonInterference:
    def test_b1_pointer_outside_markers_section_less(self, tmp_path):
        surface, target = _skill_fixture(tmp_path)
        assert surface.read_text(encoding="utf-8").count(BEGIN_MARKER) == 0
        apply_pointer(surface, target, label=POINTER_LABELS["skill"])
        text = surface.read_text(encoding="utf-8")
        assert POINTER_BEGIN_MARKER in text and POINTER_END_MARKER in text
        assert text.count(BEGIN_MARKER) == 0  # apply_pointer created no managed section

    def test_b1_pointer_outside_markers_with_managed_section(self, tmp_path):
        surface, target = _skill_fixture(tmp_path)
        rec = _routed_record(scope="skill:s")
        managed = compile_managed_text(surface.read_text(encoding="utf-8"), [rec])
        surface.write_text(managed.text, encoding="utf-8")
        assert surface.read_text(encoding="utf-8").count(BEGIN_MARKER) == 1

        apply_pointer(surface, target, label=POINTER_LABELS["skill"])
        text = surface.read_text(encoding="utf-8")
        assert text.count(BEGIN_MARKER) == 1  # unchanged by the pointer call
        section = text[text.index(BEGIN_MARKER):text.index(END_MARKER)]
        assert pointer_token(surface, target) not in section

    def test_b1_regression_guard(self, tmp_path):
        # U-cap: the old cap is retired, but the guarded invariant survives
        # — the pointer block must not be counted as a managed entry.
        # `entry_count` (kept, §6.1) is the assertion now.
        records = [_routed_record(scope="skill:s", n=i + 1) for i in range(10)]
        surface, target = _skill_fixture(tmp_path)
        managed = compile_managed_text(surface.read_text(encoding="utf-8"), records)
        surface.write_text(managed.text, encoding="utf-8")

        apply_pointer(surface, target, label=POINTER_LABELS["skill"])
        text = surface.read_text(encoding="utf-8")
        result = compile_managed_text(text, records)
        assert result.entry_count == 10

    def test_b2_pointer_survives_regeneration_byte_identical(self, tmp_path):
        surface, target = _skill_fixture(tmp_path)
        apply_pointer(surface, target, label=POINTER_LABELS["skill"])
        text_with_pointer = surface.read_text(encoding="utf-8")
        pointer_block = text_with_pointer[text_with_pointer.index(POINTER_BEGIN_MARKER):]

        rec = _routed_record(scope="skill:s")
        result = compile_managed_text(text_with_pointer, [rec])
        assert pointer_block in result.text

        surface.write_text(result.text, encoding="utf-8")
        assert selfcheck._surface_names_target(surface, target) is True

    def test_b3_marker_counts_untouched(self, tmp_path):
        surface, target = _skill_fixture(tmp_path)
        rec = _routed_record(scope="skill:s")
        managed = compile_managed_text(surface.read_text(encoding="utf-8"), [rec])
        surface.write_text(managed.text, encoding="utf-8")

        apply_pointer(surface, target, label=POINTER_LABELS["skill"])
        text = surface.read_text(encoding="utf-8")
        assert text.count(BEGIN_MARKER) == 1
        assert text.count(END_MARKER) == 1
        assert text.count(POINTER_BEGIN_MARKER) == 1
        assert text.count(POINTER_END_MARKER) == 1
        ok, _msg = selfcheck._check_markers({surface: [rec]})
        assert ok is True
        assert BEGIN_MARKER not in POINTER_BEGIN_MARKER
        assert END_MARKER not in POINTER_END_MARKER

    def test_b4_managed_compilers_never_called_section_less(self, env):
        """The home-assistant shape: a SKILL.md with no managed section at
        all -- the criterion that catches the wrong reading of "ALWAYS
        recompile" (§3.4)."""
        record = make_knowledge(scope="skill:s")
        create_record(env.ledger, record)
        verbs.route(env.ledger, record.id, dest="reference", no_push=True)
        text = env.skill_md.read_text(encoding="utf-8")
        assert text.count(BEGIN_MARKER) == 0

    def test_b5_route_survives_next_managed_section_route_project_scope(self, env):
        rec1 = make_knowledge(scope="project")
        create_record(env.ledger, rec1, project_path=env.host)
        verbs.route(env.ledger, rec1.id, dest="reference", no_push=True)
        ok1, msg1 = selfcheck._check_reach(env.ledger)
        assert ok1 is True, msg1

        rec2 = make_knowledge(scope="project", fact="A second, unrelated project fact.")
        create_record(env.ledger, rec2, project_path=env.host)
        verbs.route(env.ledger, rec2.id, dest="claude-md", no_push=True)

        ok2, msg2 = selfcheck._check_reach(env.ledger)
        assert ok2 is True, msg2

    def test_b5_mandatory_section_less_surface_re_run(self, env):
        """§5's closing paragraph (mandatory, not a suggestion): re-run the
        B group against a SECTION-LESS surface -- the R14/home-assistant
        shape -- at skill scope, where reproducing the regeneration needs
        a skill-md route to the SAME skill (not project scope's claude-md,
        which B5's own fixture above already covers)."""
        rec1 = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec1)
        verbs.route(env.ledger, rec1.id, dest="reference", no_push=True)
        ok1, msg1 = selfcheck._check_reach(env.ledger)
        assert ok1 is True, msg1
        assert env.skill_md.read_text(encoding="utf-8").count(BEGIN_MARKER) == 0

        rec2 = make_behavior(scope="skill:s", record_id="lrn-00000002")
        create_record(env.ledger, rec2)
        verbs.route(env.ledger, rec2.id, dest="skill-md", no_push=True)

        ok2, msg2 = selfcheck._check_reach(env.ledger)
        assert ok2 is True, msg2
        text = env.skill_md.read_text(encoding="utf-8")
        assert text.count(BEGIN_MARKER) == 1  # the skill-md route DID bootstrap one
        assert text.count(POINTER_BEGIN_MARKER) == 1


# ==================================== C. threading and the route path


class TestThreadingRoutePath:
    def test_c1_pointer_surface_matches_loaded_surface_skill(self, env):
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)
        bucket = next(b for b in discover_buckets(env.ledger) if b.name == "s")
        spec = verbs._resolve_target(
            env.ledger, bucket.path, "skill:s", "reference", None, check_dirty=False,
        )
        expected = _loaded_surface(env.ledger, bucket, rec)[0]
        assert spec.pointer_surface.resolve() == expected.resolve()

    def test_c1_pointer_surface_matches_loaded_surface_project(self, env):
        rec = make_knowledge(scope="project")
        create_record(env.ledger, rec, project_path=env.host)
        bucket = next(b for b in discover_buckets(env.ledger) if b.scope == "project")
        spec = verbs._resolve_target(
            env.ledger, bucket.path, "project", "reference", None,
            check_dirty=False, project_path=env.host,
        )
        expected = _loaded_surface(env.ledger, bucket, rec)[0]
        assert spec.pointer_surface.resolve() == expected.resolve()

    def test_c2_fresh_route_makes_reach_pass_end_to_end(self, env):
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)
        verbs.route(env.ledger, rec.id, dest="reference", no_push=True)

        ok, msg = selfcheck._check_reach(env.ledger)
        assert ok is True
        assert "1 reference-routed record(s) reachable" in msg

        # Mandatory positive control, same test: same ledger state, the
        # pointer block stripped back out -- must go back to ok=False.
        env.skill_md.write_text(
            "# s skill\n\nAuthored prose stays put.\n", encoding="utf-8"
        )
        ok2, _msg2 = selfcheck._check_reach(env.ledger)
        assert ok2 is False

    def test_c3_pointer_staged_and_committed_with_route(self, env):
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)
        verbs.route(env.ledger, rec.id, dest="reference", no_push=True)

        files = verb_files(env.host)
        assert "plugins/s-plugin/skills/s/references/LEARNINGS.md" in files
        assert "plugins/s-plugin/skills/s/SKILL.md" in files
        assert git(env.host, "status", "--porcelain").stdout.strip() == ""

    def test_c4_human_is_told(self, env):
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)
        result = verbs.route(env.ledger, rec.id, dest="reference", no_push=True)
        assert any(str(env.skill_md) in w for w in result.warnings)

        rec2 = make_knowledge(scope="skill:s", fact="A second fact, same skill, same file.")
        create_record(env.ledger, rec2)
        result2 = verbs.route(env.ledger, rec2.id, dest="reference", no_push=True)
        assert not any(str(env.skill_md) in w for w in result2.warnings)

    def test_c5_idempotence_across_routes(self, env):
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)
        verbs.route(env.ledger, rec.id, dest="reference", no_push=True)
        text_after_first = env.skill_md.read_text(encoding="utf-8")

        rec2 = make_knowledge(scope="skill:s", fact="Another distinct fact, same file.")
        create_record(env.ledger, rec2)
        verbs.route(env.ledger, rec2.id, dest="reference", no_push=True)
        text_after_second = env.skill_md.read_text(encoding="utf-8")

        assert text_after_second == text_after_first
        assert text_after_second.count("references/LEARNINGS.md") == 1

    def test_c6_hand_written_pointer_respected(self, env):
        env.skill_md.write_text(
            "# s skill\n\nAuthored prose stays put.\n\nSee references/LEARNINGS.md.\n",
            encoding="utf-8",
        )
        commit_all(env.host, "hand-written pointer")
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)
        before = env.skill_md.read_text(encoding="utf-8")

        verbs.route(env.ledger, rec.id, dest="reference", no_push=True)

        after = env.skill_md.read_text(encoding="utf-8")
        assert after == before
        assert POINTER_BEGIN_MARKER not in after

    def test_c7_two_reference_files_one_block_route_order(self, env):
        refs_dir = env.skill_dir / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        second_ref = refs_dir / "GOTCHAS2.md"
        second_ref.write_text("# Gotchas\n", encoding="utf-8")
        commit_all(env.host, "seed second references file")

        rec1 = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec1)
        verbs.route(env.ledger, rec1.id, dest="reference", no_push=True)

        rec2 = make_knowledge(scope="skill:s", fact="Second fact, second reference file.")
        create_record(env.ledger, rec2)
        verbs.route(env.ledger, rec2.id, dest="reference:GOTCHAS2.md", no_push=True)

        text = env.skill_md.read_text(encoding="utf-8")
        assert text.count(POINTER_BEGIN_MARKER) == 1
        lines = [ln for ln in text.splitlines() if ln.startswith("- `")]
        assert len(lines) == 2
        assert selfcheck._surface_names_target(env.skill_md, refs_dir / "LEARNINGS.md")
        assert selfcheck._surface_names_target(env.skill_md, second_ref)
        assert lines[-1].startswith("- `references/GOTCHAS2.md`")


# ============================================================ D. commit gate


class TestCommitGate:
    def test_d1_no_op_append_with_new_pointer_still_commits(self, env):
        refs_dir = env.skill_dir / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        learnings = refs_dir / "LEARNINGS.md"
        record = make_knowledge(scope="skill:s")
        record.set_routing({
            "routed_at": "2026-08-09T00:00:00Z", "destination": "reference", "by": "human",
        })
        record.set_status("routed")
        learnings.write_text(
            f"# Learnings\n\n## 2026-08-09 — {record.id}\n\n**Fact:** x\n",
            encoding="utf-8",
        )
        commit_all(env.host, "entry already present")

        spec = TargetSpec(
            "reference", "skill", env.ledger / "skills" / "s", None, env.host,
            refs_dir=refs_dir, ref_name=None, pointer_surface=env.skill_md,
        )
        warnings: list[str] = []
        compile_result, host_sha = verbs._host_phase(
            env.ledger, spec, record.id, routed_record=record, note=None,
            chezmoi_bin="chezmoi", message="self-learn: apply", warnings=warnings,
        )

        assert compile_result.applied is False
        assert compile_result.pointer_changed is True
        assert host_sha is not None
        assert "plugins/s-plugin/skills/s/SKILL.md" in verb_files(env.host)
        assert git(env.host, "status", "--porcelain").stdout.strip() == ""

    def test_d2_other_destinations_gate_byte_identical_clean_no_op(self, env):
        rec = make_behavior(scope="skill:s")
        create_record(env.ledger, rec)
        verbs.route(env.ledger, rec.id, dest="skill-md", no_push=True)
        resolved_rec = Record.from_path(
            env.ledger / "skills" / "s" / "resolved" / f"{rec.id}.md"
        )

        # A second _host_phase call against the SAME already-compiled
        # state reproduces `SectionResult.changed=False` -- the clean
        # no-op D2 pins.
        spec = TargetSpec(
            "skill-md", "skill", env.ledger / "skills" / "s", env.skill_md, env.host,
        )
        warnings: list[str] = []
        compile_result, host_sha = verbs._host_phase(
            env.ledger, spec, rec.id, routed_record=resolved_rec, note=None,
            chezmoi_bin="chezmoi", message="self-learn: apply", warnings=warnings,
        )
        assert compile_result.changed is False
        assert host_sha is None  # (a) no commit

        result = verbs.VerbResult(
            action="route", record_id=rec.id, commit_message="x", commit_sha="y",
            compile_result=compile_result, host_commit_sha=host_sha,
        )
        assert cli._outcome_state(result) == "no_op"  # (b)
        assert not any("HOST PHASE FAILED" in w for w in warnings)  # (c)
        assert git(env.host, "status", "--porcelain").stdout.strip() == ""

    def test_d3_cli_reports_no_change_never_learns_about_pointer_changed(self):
        # (i) structural: the short-circuit at cli.py precedes the
        # `_reports_no_change` consult -- verified two ways.
        assert "pointer_changed" not in inspect.getsource(cli._reports_no_change)
        fake_result = verbs.VerbResult(
            action="route", record_id="lrn-00000001", commit_message="x",
            commit_sha="y", host_commit_sha="deadbeef",
            compile_result=ReferenceResult(
                path=Path("/tmp/x"), applied=False, created=False, entry=None,
            ),
        )
        assert cli._outcome_state(fake_result) == "landed"

    def test_d3_leg_ii_both_present_is_a_genuine_no_op(self, env):
        # (ii) behavioural, honestly scoped: entry AND pointer both already
        # present -> no_op. (Cannot redden under M17 alone -- see A8/D3
        # commentary; leg (i) above is the one that actually distinguishes
        # the mutation.)
        record = make_knowledge(scope="skill:s")
        record.set_routing({
            "routed_at": "2026-08-09T00:00:00Z", "destination": "reference", "by": "human",
        })
        record.set_status("routed")
        refs_dir = env.skill_dir / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        (refs_dir / "LEARNINGS.md").write_text(
            f"# Learnings\n\n## 2026-08-09 — {record.id}\n\n**Fact:** x\n",
            encoding="utf-8",
        )
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nsee references/LEARNINGS.md\n",
            encoding="utf-8",
        )
        commit_all(env.host, "both entry and pointer already present")

        spec = TargetSpec(
            "reference", "skill", env.ledger / "skills" / "s", None, env.host,
            refs_dir=refs_dir, ref_name=None, pointer_surface=env.skill_md,
        )
        warnings: list[str] = []
        compile_result, host_sha = verbs._host_phase(
            env.ledger, spec, record.id, routed_record=record, note=None,
            chezmoi_bin="chezmoi", message="self-learn: apply", warnings=warnings,
        )
        result = verbs.VerbResult(
            action="route", record_id=record.id, commit_message="x", commit_sha="y",
            compile_result=compile_result, host_commit_sha=host_sha,
        )
        assert cli._outcome_state(result) == "no_op"


# ================================== E. recompile -- the backfill mechanism


class TestRecompileBackfill:
    def test_e1_r14_shape_reproduced_and_repaired(self, env):
        _seed_skill_reference_record(env, entry_present=True, pointer_present=False)
        ok_before, _msg = selfcheck._check_reach(env.ledger)
        assert ok_before is False  # positive control -- must be asserted, not assumed

        verbs.recompile(env.ledger, no_push=True)

        ok_after, msg_after = selfcheck._check_reach(env.ledger)
        assert ok_after is True, msg_after

    def test_e2_old_continue_is_dead(self, env):
        _seed_skill_reference_record(env, entry_present=True, pointer_present=False)
        verbs.recompile(env.ledger, no_push=True)

        subject = git(env.host, "log", "-1", "--format=%s").stdout.strip()
        files = git(
            env.host, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()
        assert subject.startswith("self-learn: pointer ")
        assert files == ["plugins/s-plugin/skills/s/SKILL.md"]

    def test_e3_reference_commit_unchanged_when_entries_also_land(self, env):
        _seed_skill_reference_record(env, entry_present=False, pointer_present=False)
        result = verbs.recompile(env.ledger, no_push=True)

        assert result.committed == 2
        subjects = git(env.host, "log", "--format=%s", "-n", "2").stdout.strip().splitlines()
        assert any(
            s == "self-learn: recompile plugins/s-plugin/skills/s/references/LEARNINGS.md"
            for s in subjects
        )
        assert any(
            s == "self-learn: pointer plugins/s-plugin/skills/s/SKILL.md" for s in subjects
        )

    def test_e4_idempotence_second_run_zero_commits(self, env):
        _seed_skill_reference_record(env, entry_present=True, pointer_present=False)
        verbs.recompile(env.ledger, no_push=True)

        result2 = verbs.recompile(env.ledger, no_push=True)
        assert result2.committed == 0

    def test_e5_dirty_surface_skipped_loudly_appends_proceed(self, env):
        record = _seed_skill_reference_record(env, entry_present=False, pointer_present=False)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8"
        )

        result = verbs.recompile(env.ledger, no_push=True)

        learnings = env.skill_dir / "references" / "LEARNINGS.md"
        assert learnings.is_file() and record.id in learnings.read_text(encoding="utf-8")
        skipped = [e for e in result.entries if e.skipped == "dirty"]
        assert any(e.target == env.skill_md for e in skipped)
        assert any(str(env.skill_md) in w for w in result.warnings)
        assert "local edit" in env.skill_md.read_text(encoding="utf-8")

    def test_e6_unresolvable_host_still_only_warns(self, env):
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)
        resolve_record(
            env.ledger, rec.id, "routed",
            destination="reference", by="human", routed_at="2026-08-09T00:00:00Z",
            reference_file=None,
        )
        (env.ledger / "hosts.yaml").write_text(
            f"projects:\n  - path: {env.host}\n", encoding="utf-8"
        )
        commit_all(env.ledger, "deregister skills root")

        result = verbs.recompile(env.ledger, no_push=True)
        assert any(rec.id in w for w in result.warnings)

    def test_e7_undecodable_surface_does_not_abort_batch(self, tmp_path):
        env2 = make_env(tmp_path, skills=("bad", "good"))
        bad_skill_md = env2.host / "plugins" / "bad-plugin" / "skills" / "bad" / "SKILL.md"
        good_skill_dir = env2.host / "plugins" / "good-plugin" / "skills" / "good"
        good_skill_md = good_skill_dir / "SKILL.md"
        _write_bad_bytes(bad_skill_md, "# bad skill\n\n")
        commit_all(env2.host, "corrupt bad SKILL.md")

        bad_rec = make_knowledge(scope="skill:bad")
        create_record(env2.ledger, bad_rec)
        resolve_record(
            env2.ledger, bad_rec.id, "routed",
            destination="reference", by="human", routed_at="2026-08-09T00:00:00Z",
            reference_file=None,
        )
        good_rec = make_knowledge(scope="skill:good")
        create_record(env2.ledger, good_rec)
        resolve_record(
            env2.ledger, good_rec.id, "routed",
            destination="reference", by="human", routed_at="2026-08-09T00:00:00Z",
            reference_file=None,
        )

        result = verbs.recompile(env2.ledger, no_push=True)  # must not raise

        assert any(str(bad_skill_md) in w for w in result.warnings)
        # Vacuity guard: the SECOND host's repair actually happened, not
        # merely "no exception was raised".
        good_entries = [
            e for e in result.entries if e.target == good_skill_md and e.changed
        ]
        assert good_entries, result.entries
        good_learnings = good_skill_dir / "references" / "LEARNINGS.md"
        assert good_learnings.is_file()
        assert good_rec.id in good_learnings.read_text(encoding="utf-8")
        assert selfcheck._surface_names_target(good_skill_md, good_learnings)

    def test_e8_backfill_is_pushed(self, tmp_path):
        env2 = make_env(tmp_path)
        host_bare = tmp_path / "host-remote.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(host_bare)], check=True
        )
        git(env2.host, "remote", "add", "origin", str(host_bare))
        git(env2.host, "push", "-q", "-u", "origin", "main")

        _seed_skill_reference_record(env2, entry_present=True, pointer_present=False)
        verbs.recompile(env2.ledger, no_push=False)

        remote_head = git(host_bare, "rev-parse", "HEAD").stdout.strip()
        local_head = git(env2.host, "rev-parse", "HEAD").stdout.strip()
        assert remote_head == local_head
        subject = git(host_bare, "log", "-1", "--format=%s").stdout.strip()
        assert subject.startswith("self-learn: pointer ")


# ================================= F. scope invariants and refusals


class TestScopeInvariants:
    def test_f1_user_scope_refusal_key_phrases(self, tmp_path, env):
        """F1 -- USER RULING 2026-08-09: key-phrase pinning, not byte-
        exactness. A byte-identical assertion breaks on any wording
        polish that preserves the refusal's effect; pin the rule tag,
        the reason clause, and the redirect guidance instead."""
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        rec = make_behavior(scope="user")
        create_record(env.ledger, rec)

        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.route(
                env.ledger, rec.id, dest="reference", user_claude_md=target, no_push=True
            )
        msg = str(exc_info.value)
        assert "S-23 (2)" in msg  # rule tag
        assert "user scope has no references dir" in msg  # reason clause
        assert "claude-md:rules:" in msg  # redirect guidance (1/2)
        # r4 NOTE 2: "project scope" alone is satisfied by the message's
        # OPENING clause ("...or project scope -- user scope has no
        # references dir"), so deleting the redirect guidance's second
        # half would stay green. Pin a phrase unique to that guidance.
        assert "route it to project scope, or defer" in msg  # redirect guidance (2/2)

    def test_f2_l2_missing_skill_md_refuses_before_ledger_commit(self, env):
        env.skill_md.unlink()
        commit_all(env.host, "remove SKILL.md")
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)

        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.route(env.ledger, rec.id, dest="reference", no_push=True)

        assert str(env.skill_md) in str(exc_info.value)
        assert (env.ledger / "skills" / "s" / "pending" / f"{rec.id}.md").is_file()
        assert not (env.ledger / "skills" / "s" / "resolved" / f"{rec.id}.md").exists()

    def test_f3_l3_missing_project_claude_md_created_and_pointed(self, env):
        (env.host / "CLAUDE.md").unlink()
        commit_all(env.host, "remove CLAUDE.md")
        rec = make_knowledge(scope="project")
        create_record(env.ledger, rec, project_path=env.host)

        verbs.route(env.ledger, rec.id, dest="reference", no_push=True)

        target = env.host / "CLAUDE.md"
        assert target.is_file()
        assert POINTER_BEGIN_MARKER in target.read_text(encoding="utf-8")
        assert "CLAUDE.md" in verb_files(env.host)
        ok, msg = selfcheck._check_reach(env.ledger)
        assert ok is True, msg

    def test_f4_l4_dirty_surface_refuses_before_ledger_commit(self, env):
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted\n", encoding="utf-8"
        )
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)
        before = env.skill_md.read_text(encoding="utf-8")

        with pytest.raises(verbs.DirtyTargetError):
            verbs.route(env.ledger, rec.id, dest="reference", no_push=True)

        assert (env.ledger / "skills" / "s" / "pending" / f"{rec.id}.md").is_file()
        assert env.skill_md.read_text(encoding="utf-8") == before

    def test_f5_l5_undecodable_surface_refuses_at_preflight(self, env):
        _write_bad_bytes(env.skill_md, "# s skill\n\n")
        commit_all(env.host, "corrupt SKILL.md")
        rec = make_knowledge(scope="skill:s")
        create_record(env.ledger, rec)

        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.route(env.ledger, rec.id, dest="reference", no_push=True)

        assert str(env.skill_md) in str(exc_info.value)
        assert (env.ledger / "skills" / "s" / "pending" / f"{rec.id}.md").is_file()

    def test_f6_l8_supersede_graduate_still_refuse(self, env):
        spec = TargetSpec(
            "reference", "skill", env.ledger / "skills" / "s", None, env.host,
            refs_dir=env.skill_dir / "references", ref_name=None,
            pointer_surface=env.skill_md,
        )
        with pytest.raises(verbs.VerbError, match="append-only"):
            verbs._apply_target(env.ledger, spec, None)

    def test_f7_l2_at_recompile_missing_surface_warns_appends_happen(self, env):
        rec = _seed_skill_reference_record(env, entry_present=False, pointer_present=False)
        env.skill_md.unlink()
        commit_all(env.host, "remove SKILL.md")

        result = verbs.recompile(env.ledger, no_push=True)

        learnings = env.skill_dir / "references" / "LEARNINGS.md"
        assert learnings.is_file() and rec.id in learnings.read_text(encoding="utf-8")
        assert any(str(env.skill_md) in w for w in result.warnings)
        assert not env.skill_md.exists()  # no pointer written -- nothing to write into

    def test_f8_l5_at_recompile_undecodable_surface(self, env):
        rec = _seed_skill_reference_record(env, entry_present=False, pointer_present=False)
        _write_bad_bytes(env.skill_md, "# s skill\n\n")
        commit_all(env.host, "corrupt SKILL.md")

        result = verbs.recompile(env.ledger, no_push=True)

        learnings = env.skill_dir / "references" / "LEARNINGS.md"
        assert learnings.is_file() and rec.id in learnings.read_text(encoding="utf-8")
        assert any(str(env.skill_md) in w for w in result.warnings)

    def test_m23_direct_apply_target_missing_surface_never_fabricates(self, env):
        """M23 (r4 fold): `create=True` at the route-write site would
        fabricate an empty SKILL.md when the surface is missing -- but
        F2/F3 cannot see it, because both go through `route()`, which
        always intercepts at L2 (verbs.py's own preflight, §3.9) before
        `_apply_target` is ever reached. This test bypasses `route()`
        and calls `_apply_target` directly (the same direct-call shape
        as test_f6) so `apply_pointer`'s own `create=False` refusal is
        what actually has to hold."""
        rec = _seed_skill_reference_record(env, entry_present=False, pointer_present=False)
        env.skill_md.unlink()
        commit_all(env.host, "remove SKILL.md")
        spec = TargetSpec(
            "reference", "skill", env.ledger / "skills" / "s", None, env.host,
            refs_dir=env.skill_dir / "references", ref_name=None,
            pointer_surface=env.skill_md,
        )

        with pytest.raises(CompileError):
            verbs._apply_target(env.ledger, spec, rec)

        assert not env.skill_md.exists()  # never fabricate a plugin manifest
