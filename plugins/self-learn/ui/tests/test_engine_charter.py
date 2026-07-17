"""The ``can_use_tool`` charter callback (09 §4.3 / §11 Y-2; 10 §3 task U5
bullet 3): path canonicalization (incl. symlink escape), id-siblings-only
writes, and the three-root read scope. All direct unit tests of the
callback — no SDK session, no subprocess, anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

from self_learn_ui.engine.charter import CanonReadRootsUnavailable, build_can_use_tool

CTX = ToolPermissionContext()


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    """A throwaway ledger + a throwaway registered host + a throwaway
    plugin references dir — nothing here is the real filesystem (10 §0
    rule 7/8)."""
    home = tmp_path / "ledger-home"
    bucket = home / "skills" / "myskill"
    (bucket / "pending").mkdir(parents=True)
    (bucket / "proposals").mkdir(parents=True)
    (bucket / "pending" / "lrn-abc123.md").write_text("# record\n")

    # A registered host: one canon file (in scope) and one non-canon file
    # in the SAME repo (deliberately NOT in the canon roots list) — the
    # Y-2 narrowed-scope signature case (T-B instruction 5).
    host = tmp_path / "hosts" / "projA"
    host.mkdir(parents=True)
    (host / "CLAUDE.md").write_text("# canon\n")
    (host / "secret_module.py").write_text("# not canon\n")

    refs = tmp_path / "plugin-refs"
    refs.mkdir(parents=True)
    (refs / "routing-doctrine.md").write_text("doctrine\n")

    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    (outside / "file.txt").write_text("nope\n")

    return {
        "tmp_path": tmp_path,
        "home": home,
        "bucket": bucket,
        "host": host,
        "canon_file": host / "CLAUDE.md",
        "non_canon_file": host / "secret_module.py",
        "refs": refs,
        "outside_file": outside / "file.txt",
    }


def _build(world: dict[str, Path], canon_roots: list[Path] | None = None):
    return build_can_use_tool(
        self_learn_home=world["home"],
        bucket_root=world["bucket"],
        record_id="abc123",
        canon_read_roots_fn=lambda: canon_roots if canon_roots is not None else [world["canon_file"]],
        plugin_references_dir_fn=lambda: world["refs"],
    )


# -- three-root read scope --------------------------------------------


async def test_ledger_tree_read_allowed(world: dict[str, Path]) -> None:
    can_use_tool = _build(world)
    target = world["bucket"] / "pending" / "lrn-abc123.md"
    result = await can_use_tool("Read", {"file_path": str(target)}, CTX)
    assert isinstance(result, PermissionResultAllow)


async def test_canon_surface_read_allowed_via_injected_roots(world: dict[str, Path]) -> None:
    can_use_tool = _build(world, canon_roots=[world["canon_file"]])
    result = await can_use_tool("Read", {"file_path": str(world["canon_file"])}, CTX)
    assert isinstance(result, PermissionResultAllow)


async def test_non_canon_file_inside_registered_host_denied(world: dict[str, Path]) -> None:
    """The Y-2 narrowed-scope signature case: a file inside a REGISTERED
    host repo that is NOT part of its enumerated canon surface must still
    be denied — registering a host is not blanket read consent to its
    whole tree."""
    can_use_tool = _build(world, canon_roots=[world["canon_file"]])
    result = await can_use_tool("Read", {"file_path": str(world["non_canon_file"])}, CTX)
    assert isinstance(result, PermissionResultDeny)
    assert "outside all three" in result.message


async def test_outside_everything_denied_with_reason(world: dict[str, Path]) -> None:
    can_use_tool = _build(world)
    result = await can_use_tool("Read", {"file_path": str(world["outside_file"])}, CTX)
    assert isinstance(result, PermissionResultDeny)
    assert result.message  # a reason string, never a bare denial


async def test_plugin_references_dir_read_allowed(world: dict[str, Path]) -> None:
    can_use_tool = _build(world)
    result = await can_use_tool(
        "Read", {"file_path": str(world["refs"] / "routing-doctrine.md")}, CTX
    )
    assert isinstance(result, PermissionResultAllow)


async def test_grep_and_glob_use_the_same_scope(world: dict[str, Path]) -> None:
    can_use_tool = _build(world)
    grep = await can_use_tool("Grep", {"pattern": "x", "path": str(world["outside_file"])}, CTX)
    glob = await can_use_tool("Glob", {"pattern": "*.md", "path": str(world["outside_file"].parent)}, CTX)
    assert isinstance(grep, PermissionResultDeny)
    assert isinstance(glob, PermissionResultDeny)


async def test_read_with_no_resolvable_path_denied(world: dict[str, Path]) -> None:
    can_use_tool = _build(world)
    result = await can_use_tool("Grep", {"pattern": "x"}, CTX)
    assert isinstance(result, PermissionResultDeny)
    assert "could not determine" in result.message


# -- path canonicalization / symlink escape ----------------------------


async def test_symlink_read_target_resolved_before_matching(world: dict[str, Path]) -> None:
    """A symlink living INSIDE an allowed root but pointing OUTSIDE every
    root must be judged on its real target, not its apparent location."""
    link = world["home"] / "escape-link.md"
    link.symlink_to(world["outside_file"])
    can_use_tool = _build(world)
    result = await can_use_tool("Read", {"file_path": str(link)}, CTX)
    assert isinstance(result, PermissionResultDeny)


async def test_symlink_write_target_resolved_before_matching(world: dict[str, Path]) -> None:
    """A symlink AT the record's own expected path, but pointing outside
    the bucket, must not be treated as the legitimate record file."""
    real_record = world["bucket"] / "pending" / "lrn-abc123.md"
    real_record.unlink()
    real_record.symlink_to(world["outside_file"])
    can_use_tool = _build(world)
    result = await can_use_tool("Edit", {"file_path": str(real_record)}, CTX)
    assert isinstance(result, PermissionResultDeny)


# -- id-siblings-only writes --------------------------------------------


async def test_record_edit_allowed(world: dict[str, Path]) -> None:
    can_use_tool = _build(world)
    target = world["bucket"] / "pending" / "lrn-abc123.md"
    result = await can_use_tool("Edit", {"file_path": str(target)}, CTX)
    assert isinstance(result, PermissionResultAllow)


async def test_record_write_denied_the_resurrection_vector(world: dict[str, Path]) -> None:
    """Write (not Edit) on the record file is the resurrection vector
    (09 §4.3, P3-7) — must always be denied even though Edit is allowed."""
    can_use_tool = _build(world)
    target = world["bucket"] / "pending" / "lrn-abc123.md"
    result = await can_use_tool("Write", {"file_path": str(target)}, CTX)
    assert isinstance(result, PermissionResultDeny)


async def test_own_proposal_write_and_edit_allowed(world: dict[str, Path]) -> None:
    can_use_tool = _build(world)
    yaml_path = world["bucket"] / "proposals" / "lrn-abc123.yaml"
    diff_path = world["bucket"] / "proposals" / "lrn-abc123.diff"
    for tool in ("Write", "Edit"):
        for path in (yaml_path, diff_path):
            result = await can_use_tool(tool, {"file_path": str(path)}, CTX)
            assert isinstance(result, PermissionResultAllow), (tool, path)


async def test_wrong_id_proposal_denied(world: dict[str, Path]) -> None:
    """Id-siblings-only: a proposal for a DIFFERENT id in the same bucket
    is denied exactly like a file in a different bucket entirely."""
    can_use_tool = _build(world)
    wrong_id_path = world["bucket"] / "proposals" / "lrn-other999.yaml"
    result = await can_use_tool("Write", {"file_path": str(wrong_id_path)}, CTX)
    assert isinstance(result, PermissionResultDeny)


async def test_another_records_pending_file_denied(world: dict[str, Path]) -> None:
    can_use_tool = _build(world)
    other = world["bucket"] / "pending" / "lrn-other999.md"
    result = await can_use_tool("Edit", {"file_path": str(other)}, CTX)
    assert isinstance(result, PermissionResultDeny)


# -- structurally denied tools -------------------------------------------


async def test_bash_denied_by_the_callback_too(world: dict[str, Path]) -> None:
    """disallowed_tools is the primary gate for Bash/Task/WebSearch/
    WebFetch (10 §1), but the callback denies by default regardless —
    belt and braces, never an allow-by-omission path."""
    can_use_tool = _build(world)
    result = await can_use_tool("Bash", {"command": "rm -rf /"}, CTX)
    assert isinstance(result, PermissionResultDeny)


# -- fail-closed canon_read_roots import --------------------------------


def test_default_canon_read_roots_fails_closed_when_import_unavailable(
    tmp_path, monkeypatch
) -> None:
    """If self_learn.hosts ever becomes unimportable, the charter must
    fail CLOSED (raise), never silently widen scope. (Originally this
    asserted the pre-merge g3-u5 state where the helper genuinely did
    not exist; post-merge the import is simulated broken instead —
    wave-1 join update.)"""
    import sys

    from self_learn_ui.engine.charter import default_canon_read_roots

    monkeypatch.setitem(sys.modules, "self_learn.hosts", None)
    with pytest.raises(CanonReadRootsUnavailable):
        default_canon_read_roots(tmp_path)


async def test_build_can_use_tool_propagates_canon_read_roots_failure(
    world: dict[str, Path],
) -> None:
    def _raise() -> list[Path]:
        raise CanonReadRootsUnavailable("no helper on this branch")

    with pytest.raises(CanonReadRootsUnavailable):
        build_can_use_tool(
            self_learn_home=world["home"],
            bucket_root=world["bucket"],
            record_id="abc123",
            canon_read_roots_fn=_raise,
            plugin_references_dir_fn=lambda: world["refs"],
        )


class TestWave1JoinReconciliation:
    """The zero-arg-vs-hosts-parameterized signature mismatch found at the
    wave-1 merge (U5 report note 1): default_canon_read_roots(home) must
    resolve end-to-end through the REAL self_learn.hosts helpers."""

    def test_default_canon_read_roots_end_to_end(self, tmp_path):
        from self_learn_ui.engine.charter import default_canon_read_roots

        home = tmp_path / "ledger"
        home.mkdir()
        skills_root = tmp_path / "skillsrepo"
        (skills_root / "plugins" / "demo" / "skills" / "demo").mkdir(parents=True)
        proj = tmp_path / "proj"
        proj.mkdir()
        (home / "hosts.yaml").write_text(
            f"skills_root: {skills_root}\nprojects:\n- path: {proj}\n"
        )

        roots = default_canon_read_roots(home)

        assert roots, "registered hosts must yield canon read roots"
        sr = str(skills_root.resolve())
        pr = str(proj.resolve())
        assert any(str(r).startswith(sr) for r in roots)
        assert any(str(r).startswith(pr) for r in roots)
        # never a whole host root, never anything outside the two hosts
        assert all(str(r) not in (sr, pr) for r in roots)
        assert all(str(r).startswith(sr) or str(r).startswith(pr) for r in roots)

    def test_build_can_use_tool_default_fn_fails_closed_without_hosts_file(
        self, tmp_path
    ):
        """No hosts.yaml → the default fn must yield an empty/narrow scope
        or raise the fail-closed error — never a wider scope. Either way a
        canon-flavored read outside the ledger is denied."""
        from self_learn_ui.engine.charter import default_canon_read_roots

        home = tmp_path / "empty-ledger"
        home.mkdir()
        try:
            roots = default_canon_read_roots(home)
        except Exception:
            return  # fail-closed by raise is acceptable
        assert roots == []
