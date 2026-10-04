"""`recompile --adopt` could only adopt a MANAGED region; a pointer region
(the block a reference route writes into the host CLAUDE.md/SKILL.md) had no
adopt path although it is a separate compile-record entry (S-74). A target
now names its region the way the record's keys do: PATH / PATH#managed /
PATH#pointer, and --adopt repeats."""

from __future__ import annotations

import subprocess

import pytest

from self_learn import cli, compiled, verbs
from self_learn.hosts import host_slug
from self_learn.ledger_ops import create_record
from self_learn.compilers import POINTER_BEGIN_MARKER

from support import make_behavior, make_env


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    return None


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


def _route(env, rid, dest):
    create_record(env.ledger, make_behavior(scope="project", record_id=rid, instruction=f"Do {rid}."),
                  project_path=env.host)
    verbs.route(env.ledger, rid, dest=dest, no_push=True)


def _both_regions(env):
    _route(env, "lrn-0000c001", "reference")  # writes the pointer region
    _route(env, "lrn-0000c002", "claude-md")  # writes the managed region
    return env.host / "CLAUDE.md"


def _commit(env, msg):
    subprocess.run(["git", "-C", str(env.host), "commit", "-qam", msg], check=True)


def _hand_edit(env, kind):
    claude = env.host / "CLAUDE.md"
    text = claude.read_text(encoding="utf-8")
    marker = POINTER_BEGIN_MARKER if kind == "pointer" else compiled.BEGIN_MARKER
    assert marker in text  # the region exists
    claude.write_text(text.replace(marker, marker + "\nhand edit"), encoding="utf-8")
    _commit(env, f"hand edit {kind}")


def _verdict(env, kind):
    claude = env.host / "CLAUDE.md"
    region = compiled.region_bytes(claude.read_text(encoding="utf-8"), kind)
    slug = host_slug(env.ledger, env.host, scope_kind="project")
    entry = compiled.entry_for(
        compiled.load_record(env.ledger, slug),
        compiled.region_key(env.host, claude, kind), region=kind,
    )
    return compiled.verdict_for(entry, None if region is None else compiled.sha256_hex(region))


def _entry(env, kind):
    claude = env.host / "CLAUDE.md"
    slug = host_slug(env.ledger, env.host, scope_kind="project")
    return compiled.entry_for(
        compiled.load_record(env.ledger, slug),
        compiled.region_key(env.host, claude, kind), region=kind,
    )


def test_pointer_only_adopt(env):
    claude = _both_regions(env)
    assert (_verdict(env, "managed"), _verdict(env, "pointer")) == ("clean", "clean")  # control
    _hand_edit(env, "pointer")
    assert _verdict(env, "pointer") == "edited"  # control: the thing adopt must clear
    managed_before = _entry(env, "managed")
    bytes_before = claude.read_bytes()

    result = verbs.recompile(env.ledger, no_push=True, adopt=f"{claude}#pointer")

    assert _verdict(env, "pointer") == "clean"
    assert _entry(env, "managed") == managed_before  # the other region's entry is untouched
    assert claude.read_bytes() == bytes_before  # content is never changed
    assert not any("--adopt" in w for w in result.warnings), result.warnings
    log = subprocess.run(["git", "-C", str(env.ledger), "log", "--format=%s", "-6"],
                         capture_output=True, text=True, check=True).stdout
    assert "self-learn: recompile --adopt CLAUDE.md#pointer" in log


def test_a_file_with_both_regions_adopts_both_when_both_are_named(env):
    claude = _both_regions(env)
    _hand_edit(env, "pointer")
    _hand_edit(env, "managed")
    assert (_verdict(env, "managed"), _verdict(env, "pointer")) == ("edited", "edited")  # control
    bytes_before = claude.read_bytes()

    result = verbs.recompile(env.ledger, no_push=True, adopt=[str(claude), f"{claude}#pointer"])

    assert (_verdict(env, "managed"), _verdict(env, "pointer")) == ("clean", "clean")
    assert claude.read_bytes() == bytes_before
    assert not any("nothing adopted" in w for w in result.warnings), result.warnings


def test_a_bare_path_still_means_the_managed_region_only(env):
    claude = _both_regions(env)
    _hand_edit(env, "pointer")
    verbs.recompile(env.ledger, no_push=True, adopt=claude)
    assert _verdict(env, "pointer") == "edited"  # bare path did not adopt the pointer


def test_explicit_managed_selector_equals_the_bare_path(env):
    claude = _both_regions(env)
    _hand_edit(env, "managed")
    assert _verdict(env, "managed") == "edited"
    bytes_before = claude.read_bytes()
    verbs.recompile(env.ledger, no_push=True, adopt=f"{claude}#managed")
    assert _verdict(env, "managed") == "clean"
    assert claude.read_bytes() == bytes_before  # adopted, not re-rendered over


def test_naming_an_absent_pointer_region_warns_and_writes_nothing(env):
    claude = _both_regions(env)
    text = claude.read_text(encoding="utf-8")
    begin = text.index(POINTER_BEGIN_MARKER)
    end_marker = compiled.POINTER_END_MARKER
    end = text.index(end_marker) + len(end_marker)
    claude.write_text(text[:begin] + text[end:], encoding="utf-8")
    _commit(env, "remove pointer block")
    before = _entry(env, "pointer")
    assert before is not None and _verdict(env, "pointer") == "missing"  # control

    result = verbs.recompile(env.ledger, no_push=True, adopt=f"{claude}#pointer")

    assert any("no pointer region on disk" in w for w in result.warnings), result.warnings
    assert _entry(env, "pointer") == before


def test_naming_a_pointer_on_a_path_with_no_reference_route_warns(env):
    _route(env, "lrn-0000c002", "claude-md")  # managed only: no reference route, no pointer surface
    claude = env.host / "CLAUDE.md"
    result = verbs.recompile(env.ledger, no_push=True, adopt=f"{claude}#pointer")
    assert any("no reference-routed pointer surface" in w for w in result.warnings), result.warnings
    assert _entry(env, "pointer") is None


def test_cli_adopt_repeats(env, capsys):
    claude = _both_regions(env)
    _hand_edit(env, "pointer")
    _hand_edit(env, "managed")
    rc = cli.main(["recompile", "--no-push", "--adopt", str(claude), "--adopt", f"{claude}#pointer"])
    assert rc == 0
    assert (_verdict(env, "managed"), _verdict(env, "pointer")) == ("clean", "clean")
