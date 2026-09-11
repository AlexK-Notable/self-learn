"""Sprint 3 M-I wave 3 -- the eight host-canon raw writes onto
``fsops.atomic_write`` (D6: ``follow_symlinks=True``).

Each of the eight migrated sites (`compilers.compile_managed_file`,
`compilers.apply_paths_frontmatter`, `compilers.apply_pointer`,
`compilers.compile_reference`, `compilers.retire_reference`,
`hosts._write_host_marker`, `verbs._apply_target`,
`verbs._apply_new_skill`) gets three tests here, adapted to what that
site's write actually does (a rewrite of an existing file gets a
preserve-mode test; a create-only site -- one whose write only ever
fires when the target does not exist yet, so there is no prior mode to
preserve -- gets the `test_d2`-shaped default-mode-under-umask test
`test_fsops.py` already established for exactly this case):

1. A scoped failing ``os.replace`` (never a global monkeypatch) leaves
   the OLD bytes (or, for a create-only site, no file at all) and no
   orphan ``.{name}.<pid>.<token>.tmp``.
2. A symlink at the target is FOLLOWED: the real file's content
   changes, the link itself is untouched and still points where it did.
3. Mode preserved (existing-file sites) or the umask-masked default
   applies (create-only sites), verified under ``umask 0o077`` --
   tighter than this host's ambient umask, so a preserve-vs-default bug
   cannot hide behind an accommodating ambient value (test_fsops.py's
   own `test_e2` fold-r2 lesson).

Criteria 4 (the site's `RAW_WRITE_ALLOWLIST` entry removed, proven by
the rot test) and 5 (the armor-pinned e2e files run unedited) are not
per-site tests -- they are `test_raw_write_gate.py`'s own suite and the
pinned files' own suites, both run and reported separately in the build
report, not duplicated here.

Records/fixtures are built with `test_compilers.py`'s own
`golden_records`/`rules_record` helpers (imported by name -- the same
convention `test_settings.py`, `test_attrib.py`, and others already use
for cross-test-file helpers) rather than hand-rolled duplicates.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from self_learn import hosts as hosts_mod
from self_learn import verbs
from self_learn.compilers import (
    POINTER_BEGIN_MARKER,
    apply_paths_frontmatter,
    apply_pointer,
    compile_managed_file,
    compile_reference,
    retire_reference,
)
from self_learn.verbs import POINTER_LABELS, TargetSpec

from test_compilers import golden_records, rules_record


# ====================================================================
# compilers.compile_managed_file -- rewrite of an EXISTING file
# ====================================================================


def test_compile_managed_file_crash_leaves_old_bytes_no_orphan_temp(tmp_path, monkeypatch):
    target = tmp_path / "SKILL.md"
    target.write_text("# T\n\nProse.\n", encoding="utf-8")
    compile_managed_file(target, golden_records()[:1])
    old = target.read_text(encoding="utf-8")
    real_replace = os.replace

    def scoped_boom(src, dst):
        if Path(dst) == target:
            raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        compile_managed_file(target, golden_records())

    assert target.read_text(encoding="utf-8") == old
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_compile_managed_file_follows_symlinked_target(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = real_dir / "SKILL.md"
    real.write_text("# T\n\nProse.\n", encoding="utf-8")
    link_dir = tmp_path / "link"
    link_dir.mkdir()
    link = link_dir / "SKILL.md"
    link.symlink_to(real)

    compile_managed_file(link, golden_records())

    assert link.is_symlink()
    assert Path(os.readlink(link)) == real
    text = real.read_text(encoding="utf-8")
    assert "lrn-4c1e9a2f" in text and "lrn-77ab01cd" in text


def test_compile_managed_file_preserves_mode_under_tight_umask(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("# T\n\nProse.\n", encoding="utf-8")
    target.chmod(0o640)
    old_umask = os.umask(0o077)
    try:
        result = compile_managed_file(target, golden_records())
    finally:
        os.umask(old_umask)
    assert result.changed is True
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


# ====================================================================
# compilers.apply_paths_frontmatter -- rewrite of an EXISTING file
# ====================================================================

_FRONTMATTER_SEED = "---\npaths:\n  - a/**\n---\nBODY\n"


def test_apply_paths_frontmatter_crash_leaves_old_bytes_no_orphan_temp(tmp_path, monkeypatch):
    target = tmp_path / "t.md"
    target.write_text(_FRONTMATTER_SEED, encoding="utf-8")
    old = target.read_text(encoding="utf-8")
    r = rules_record("lrn-aaaaaaa1", rules_paths=["b/**"])
    real_replace = os.replace

    def scoped_boom(src, dst):
        if Path(dst) == target:
            raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        apply_paths_frontmatter(target, [r])

    assert target.read_text(encoding="utf-8") == old
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_apply_paths_frontmatter_follows_symlinked_target(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = real_dir / "t.md"
    real.write_text(_FRONTMATTER_SEED, encoding="utf-8")
    link_dir = tmp_path / "link"
    link_dir.mkdir()
    link = link_dir / "t.md"
    link.symlink_to(real)
    r = rules_record("lrn-aaaaaaa1", rules_paths=["b/**"])

    result = apply_paths_frontmatter(link, [r])

    assert result.changed is True
    assert link.is_symlink()
    assert Path(os.readlink(link)) == real
    assert "b/**" in real.read_text(encoding="utf-8")


def test_apply_paths_frontmatter_preserves_mode_under_tight_umask(tmp_path):
    target = tmp_path / "t.md"
    target.write_text(_FRONTMATTER_SEED, encoding="utf-8")
    target.chmod(0o640)
    r = rules_record("lrn-aaaaaaa1", rules_paths=["b/**"])
    old_umask = os.umask(0o077)
    try:
        result = apply_paths_frontmatter(target, [r])
    finally:
        os.umask(old_umask)
    assert result.changed is True
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


# ====================================================================
# compilers.apply_pointer -- rewrite of an EXISTING surface (the
# bootstrap-into-existing-file leg; the create-empty and revert legs
# share the identical fsops.atomic_write(..., follow_symlinks=True)
# call shape, exercised by test_pointer.py's own a1-a9/f1-f8 suite,
# re-run unedited as part of this build).
# ====================================================================


def _pointer_fixture(tmp_path: Path) -> tuple[Path, Path]:
    skill_dir = tmp_path / "plugins" / "p" / "skills" / "s"
    skill_dir.mkdir(parents=True)
    surface = skill_dir / "SKILL.md"
    surface.write_text("# s skill\n\nAuthored prose stays put.\n", encoding="utf-8")
    target = skill_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Learnings\n", encoding="utf-8")
    return surface, target


def test_apply_pointer_crash_leaves_old_bytes_no_orphan_temp(tmp_path, monkeypatch):
    surface, target = _pointer_fixture(tmp_path)
    old = surface.read_text(encoding="utf-8")
    real_replace = os.replace

    def scoped_boom(src, dst):
        if Path(dst) == surface:
            raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        apply_pointer(surface, target, label=POINTER_LABELS["skill"])

    assert surface.read_text(encoding="utf-8") == old
    assert list(surface.parent.glob(f".{surface.name}.*.tmp")) == []


def test_apply_pointer_follows_symlinked_surface(tmp_path):
    real_dir = tmp_path / "real-skill"
    real_dir.mkdir()
    real_surface = real_dir / "SKILL.md"
    real_surface.write_text("# s skill\n\nAuthored prose stays put.\n", encoding="utf-8")
    target = real_dir / "references" / "LEARNINGS.md"
    target.parent.mkdir()
    target.write_text("# Learnings\n", encoding="utf-8")
    link_dir = tmp_path / "link-skill"
    link_dir.mkdir()
    link_surface = link_dir / "SKILL.md"
    link_surface.symlink_to(real_surface)

    apply_pointer(link_surface, target, label=POINTER_LABELS["skill"])

    assert link_surface.is_symlink()
    assert Path(os.readlink(link_surface)) == real_surface
    assert POINTER_BEGIN_MARKER in real_surface.read_text(encoding="utf-8")


def test_apply_pointer_preserves_mode_under_tight_umask(tmp_path):
    surface, target = _pointer_fixture(tmp_path)
    surface.chmod(0o640)
    old_umask = os.umask(0o077)
    try:
        result = apply_pointer(surface, target, label=POINTER_LABELS["skill"])
    finally:
        os.umask(old_umask)
    assert result.changed is True
    assert stat.S_IMODE(surface.stat().st_mode) == 0o640


# ====================================================================
# compilers.compile_reference -- rewrite of an EXISTING references file
# (the create-a-fresh-LEARNINGS.md leg is create-only, same class as
# _apply_target's bootstrap below, and shares the identical call shape)
# ====================================================================


def test_compile_reference_crash_leaves_old_bytes_no_orphan_temp(tmp_path, monkeypatch):
    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    target = refs_dir / "LEARNINGS.md"
    target.write_text("# Learnings\n", encoding="utf-8")
    old = target.read_text(encoding="utf-8")
    record = golden_records()[0]
    real_replace = os.replace

    def scoped_boom(src, dst):
        if Path(dst) == target:
            raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        compile_reference(refs_dir, record)

    assert target.read_text(encoding="utf-8") == old
    assert list(refs_dir.glob(f".{target.name}.*.tmp")) == []


def test_compile_reference_follows_symlinked_target(tmp_path):
    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    real_dir = tmp_path / "real-refs"
    real_dir.mkdir()
    real = real_dir / "LEARNINGS.md"
    real.write_text("# Learnings\n", encoding="utf-8")
    link = refs_dir / "LEARNINGS.md"
    link.symlink_to(real)
    record = golden_records()[0]

    result = compile_reference(refs_dir, record)

    assert result.applied is True
    assert link.is_symlink()
    assert Path(os.readlink(link)) == real
    assert record.id in real.read_text(encoding="utf-8")


def test_compile_reference_preserves_mode_under_tight_umask(tmp_path):
    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    target = refs_dir / "LEARNINGS.md"
    target.write_text("# Learnings\n", encoding="utf-8")
    target.chmod(0o640)
    record = golden_records()[0]
    old_umask = os.umask(0o077)
    try:
        result = compile_reference(refs_dir, record)
    finally:
        os.umask(old_umask)
    assert result.applied is True
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


# ====================================================================
# compilers.retire_reference -- rewrite of an EXISTING references file
# (only ever fires when the file already exists -- an absent target
# returns early with no write at all).
# ====================================================================


def test_retire_reference_crash_leaves_old_bytes_no_orphan_temp(tmp_path, monkeypatch):
    record = golden_records()[0]
    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    compile_reference(refs_dir, record)
    target = refs_dir / "LEARNINGS.md"
    old = target.read_text(encoding="utf-8")
    real_replace = os.replace

    def scoped_boom(src, dst):
        if Path(dst) == target:
            raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        retire_reference(refs_dir, record.id)

    assert target.read_text(encoding="utf-8") == old
    assert list(refs_dir.glob(f".{target.name}.*.tmp")) == []


def test_retire_reference_follows_symlinked_target(tmp_path):
    record = golden_records()[0]
    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    compile_reference(refs_dir, record)
    real_dir = tmp_path / "real-refs"
    real_dir.mkdir()
    real = real_dir / "LEARNINGS.md"
    link = refs_dir / "LEARNINGS.md"
    link.rename(real)  # move the content compile_reference just wrote
    link.symlink_to(real)
    assert record.id in real.read_text(encoding="utf-8")

    result = retire_reference(refs_dir, record.id)

    assert result.applied is True
    assert link.is_symlink()
    assert Path(os.readlink(link)) == real
    assert record.id not in real.read_text(encoding="utf-8")


def test_retire_reference_preserves_mode_under_tight_umask(tmp_path):
    record = golden_records()[0]
    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    compile_reference(refs_dir, record)
    target = refs_dir / "LEARNINGS.md"
    target.chmod(0o640)
    old_umask = os.umask(0o077)
    try:
        result = retire_reference(refs_dir, record.id)
    finally:
        os.umask(old_umask)
    assert result.applied is True
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


# ====================================================================
# hosts._write_host_marker -- can rewrite an EXISTING marker (host_add's
# M-4 repair leg, and a direct re-call); the crash test drives the
# public host_add's own first-registration leg (its "if mode == 'plain':
# _write_host_marker(...)" branch, unconditional the first time), the
# symlink/mode tests call the private function directly -- host_add's
# own repair guard (`not (target / MARKER_FILENAME).is_file()`) would
# never re-call it against an already-marked (real OR symlinked) host.
# ====================================================================


def test_write_host_marker_crash_leaves_no_marker_no_orphan_temp(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    home = tmp_path / "ledger-home"
    home.mkdir()
    plain_host = tmp_path / "plain-host"
    plain_host.mkdir()
    marker = plain_host / hosts_mod.MARKER_FILENAME
    real_replace = os.replace

    def scoped_boom(src, dst):
        if Path(dst) == marker:
            raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        hosts_mod.host_add(home, plain_host, "project", mode="plain")

    assert not marker.exists()
    assert list(plain_host.glob(f".{marker.name}.*.tmp")) == []


def test_write_host_marker_follows_symlinked_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    home = tmp_path / "ledger-home"
    plain_host = tmp_path / "plain-host"
    plain_host.mkdir()
    real_dir = tmp_path / "real-marker-dir"
    real_dir.mkdir()
    real = real_dir / hosts_mod.MARKER_FILENAME
    real.write_text("home=old at=old\n", encoding="utf-8")
    link = plain_host / hosts_mod.MARKER_FILENAME
    link.symlink_to(real)

    hosts_mod._write_host_marker(home, plain_host)

    assert link.is_symlink()
    assert Path(os.readlink(link)) == real
    assert str(home.resolve()) in real.read_text(encoding="utf-8")


def test_write_host_marker_preserves_mode_under_tight_umask(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    home = tmp_path / "ledger-home"
    plain_host = tmp_path / "plain-host"
    plain_host.mkdir()
    marker = plain_host / hosts_mod.MARKER_FILENAME
    marker.write_text("home=old at=old\n", encoding="utf-8")
    marker.chmod(0o640)
    old_umask = os.umask(0o077)
    try:
        hosts_mod._write_host_marker(home, plain_host)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(marker.stat().st_mode) == 0o640


# ====================================================================
# verbs._apply_target -- the "first-time empty CLAUDE.md bootstrap"
# leg, create-only by construction (guarded by `if not
# spec.target.is_file()`): no existing mode to preserve, so criterion 3
# is the create-only shape (default umask-masked mode, `test_fsops.py`'s
# own `test_d2`). `_compile_set` is monkeypatched to skip building a
# real ledger/bucket -- this function's own contract for THIS write does
# not depend on what `_compile_set` returns, only on `spec.target`'s
# prior existence.
# ====================================================================


def _claude_md_spec(tmp_path: Path, target: Path) -> TargetSpec:
    host = target.parent
    return TargetSpec("claude-md", "project", tmp_path / "bucket", target, host)


def test_apply_target_bootstrap_crash_leaves_no_file_no_orphan_temp(tmp_path, monkeypatch):
    host = tmp_path / "host"
    host.mkdir()
    target = host / "CLAUDE.md"
    spec = _claude_md_spec(tmp_path, target)
    monkeypatch.setattr(verbs, "_compile_set", lambda home, spec: golden_records())
    real_replace = os.replace
    calls = {"n": 0}

    def scoped_boom(src, dst):
        if Path(dst) == target:
            calls["n"] += 1
            if calls["n"] == 1:  # the bootstrap write only -- not compile_managed_file's own
                raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        verbs._apply_target(tmp_path / "home", spec, None)

    assert not target.exists()
    assert list(host.glob(f".{target.name}.*.tmp")) == []


def test_apply_target_bootstrap_follows_symlinked_target(tmp_path, monkeypatch):
    host = tmp_path / "host"
    host.mkdir()
    real_dir = tmp_path / "real-host"
    real_dir.mkdir()
    real = real_dir / "CLAUDE.md"  # does not exist yet -- dangling link
    link = host / "CLAUDE.md"
    link.symlink_to(real)
    spec = _claude_md_spec(tmp_path, link)
    monkeypatch.setattr(verbs, "_compile_set", lambda home, spec: golden_records())

    verbs._apply_target(tmp_path / "home", spec, None)

    assert link.is_symlink()
    assert Path(os.readlink(link)) == real
    text = real.read_text(encoding="utf-8")
    assert "lrn-4c1e9a2f" in text and "lrn-77ab01cd" in text


def test_apply_target_bootstrap_default_mode_under_tight_umask(tmp_path, monkeypatch):
    host = tmp_path / "host"
    host.mkdir()
    target = host / "CLAUDE.md"
    spec = _claude_md_spec(tmp_path, target)
    monkeypatch.setattr(verbs, "_compile_set", lambda home, spec: golden_records())
    old_umask = os.umask(0o077)
    try:
        verbs._apply_target(tmp_path / "home", spec, None)
    finally:
        os.umask(old_umask)
    # No pre-existing file -- the umask-masked platform default applies,
    # same as test_fsops.py's test_d2 for any other fresh atomic_write.
    expected = 0o666 & ~0o077
    assert stat.S_IMODE(target.stat().st_mode) == expected


# ====================================================================
# verbs._apply_new_skill -- three create-only writes (manifest,
# SKILL.md seed, marketplace's FIRST route) sharing one function; one
# fault type is exercised per sub-write, spreading coverage across all
# three rather than tripling the test count. marketplace.json already
# exists (a real host always seeds one before the first new-skill
# route), so its write IS a rewrite -- the one preserve-mode-meaningful
# case among the three.
# ====================================================================

_MARKETPLACE_SEED = {"name": "sandbox-skills", "plugins": []}


def _new_skill_fixture(tmp_path: Path, name: str) -> tuple[TargetSpec, Path, Path]:
    host = tmp_path / "host"
    host.mkdir()
    (host / ".claude-plugin").mkdir()
    (host / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(_MARKETPLACE_SEED, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    target = host / "plugins" / name / "skills" / name / "SKILL.md"
    spec = TargetSpec("new-skill", "skill", tmp_path / "bucket", target, host, new_skill=name)
    return spec, host, target


def test_apply_new_skill_manifest_crash_leaves_no_manifest_no_orphan_temp(tmp_path, monkeypatch):
    spec, host, target = _new_skill_fixture(tmp_path, "widget-a")
    monkeypatch.setattr(verbs, "_compile_set", lambda home, spec: golden_records())
    manifest = host / "plugins" / "widget-a" / ".claude-plugin" / "plugin.json"
    real_replace = os.replace

    def scoped_boom(src, dst):
        if Path(dst) == manifest:
            raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        verbs._apply_new_skill(tmp_path / "home", spec)

    assert not manifest.exists()
    assert list(manifest.parent.glob(f".{manifest.name}.*.tmp")) == []


def test_apply_new_skill_skill_md_follows_symlinked_target(tmp_path, monkeypatch):
    spec, host, target = _new_skill_fixture(tmp_path, "widget-b")
    monkeypatch.setattr(verbs, "_compile_set", lambda home, spec: golden_records())
    target.parent.mkdir(parents=True)
    real_dir = tmp_path / "real-skillmd"
    real_dir.mkdir()
    real = real_dir / "SKILL.md"  # dangling link -- does not exist yet
    target.symlink_to(real)

    verbs._apply_new_skill(tmp_path / "home", spec)

    assert target.is_symlink()
    assert Path(os.readlink(target)) == real
    assert real.is_file()
    assert "widget-b" in real.read_text(encoding="utf-8")


def test_apply_new_skill_marketplace_preserves_mode_under_tight_umask(tmp_path, monkeypatch):
    spec, host, target = _new_skill_fixture(tmp_path, "widget-c")
    monkeypatch.setattr(verbs, "_compile_set", lambda home, spec: golden_records())
    marketplace = host / ".claude-plugin" / "marketplace.json"
    marketplace.chmod(0o640)
    old_umask = os.umask(0o077)
    try:
        result, _ = verbs._apply_new_skill(tmp_path / "home", spec)
    finally:
        os.umask(old_umask)
    assert result.changed is True
    data = json.loads(marketplace.read_text(encoding="utf-8"))
    assert [p["name"] for p in data["plugins"]] == ["widget-c"]
    assert stat.S_IMODE(marketplace.stat().st_mode) == 0o640
