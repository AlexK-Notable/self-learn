"""S-167. Historical Linux names observed through their on-disk consumers."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from self_learn import (
    cache_gc, compiled, compilers, gitops, hook_compiler, hosts, ledger, ledger_ops,
    miner, reconcile, refread, refs, report, selfcheck, serve, session_copies,
    settings, skill_reference, worker,
)
from self_learn.mining import tasks
from self_learn.overseer import run as overseer
from self_learn.primitives import names
from support import git, init_repo, make_env, make_knowledge

posix = pytest.mark.skipif(os.name == "nt", reason="historical POSIX storage contract")


def _digest(spelling):
    return hashlib.sha256(str(spelling).encode("utf-8")).hexdigest()[:8]


def _marker(folder, value):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "marker").write_bytes(value)


@posix
def test_legacy_slug_and_digest_vectors(tmp_path, monkeypatch):
    vectors = {
        "/": "--8a5edab2",
        "/w/a-b": "-w-a-b-da716785",
        "/w/a/b": "-w-a-b-0fce286d",
        "/w/A B": "-w-A B-dd9699d3",
        "/w/a b": "-w-a b-e3b001a5",
        "/w/é": "-w-é-90d941a8",
        "/w/e\u0301": "-w-e\u0301-49b52514",
        r"/w/a\b": r"-w-a\b-c8a3d437",
    }
    env = make_env(tmp_path)
    for spelling, component in vectors.items():
        assert hosts.slug_for(spelling).encode() == component.encode()
        assert names.project_digest(spelling) == component[-8:]

    calls = []
    resolve = Path.resolve

    def count_resolutions(path):
        calls.append(path)
        return resolve(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", count_resolutions)
        assert hosts.slug_for("/w/a-b") == vectors["/w/a-b"]
        assert names.project_digest("/w/a/b") == "0fce286d"
    assert calls == [Path("/w/a-b"), Path("/w/a/b")]
    assert names.registration_key("/w//a/.") == "/w//a/."
    projects = env.ledger / "projects"
    lessons = [("/w/a-b", b"first lesson\r\n"), ("/w/a/b", b"second project\n")]
    for path, payload in lessons:
        pending = projects / vectors[path] / "pending"
        pending.mkdir(parents=True)
        (pending / "lrn-12345678.md").write_bytes(payload)
    for path, payload in lessons:
        stored = hosts._project_bucket_for(env.ledger, vectors[path])
        assert stored == ledger_ops.bucket_dir_for_scope(env.ledger, "project", project_path=Path(path))
        assert (stored / "pending/lrn-12345678.md").read_bytes() == payload
    # Historically the direct join also accepts an already-native operand.
    assert hosts._project_bucket_for(env.ledger, Path(vectors["/w/a-b"])) == projects / vectors["/w/a-b"]
    assert hosts._project_bucket_for(env.ledger, str(env.host)) is None

    fresh = tmp_path / "Fresh project"
    init_repo(fresh)
    for key in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(key, raising=False)
    hosts.host_add(env.ledger, fresh, "project")
    assert hosts.load_hosts(env.ledger).projects[-1] == fresh
    component = str(fresh).replace("/", "-") + "-" + _digest(fresh)
    before = set(projects.iterdir())
    lesson = make_knowledge(record_id="lrn-ab123456", fact="Fresh bucket marker.")
    created = ledger_ops.create_record(env.ledger, lesson, project_path=fresh)
    assert set(projects.iterdir()) - before == {projects / component}
    assert created == projects / component / "pending/lrn-ab123456.md"
    assert b"Fresh bucket marker." in created.read_bytes()
    assert ledger_ops.bucket_project_path(projects / component) == fresh


@posix
def test_registration_report_and_removed_history_share_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(key, raising=False)
    env = make_env(tmp_path)
    home, survivor = env.ledger, env.host
    project = tmp_path / "Project B"
    init_repo(project)
    hosts.host_add(home, project, "project", mode="plain")
    # The first project has a CLAUDE.md, the second only its plain-host marker.
    assert [row["key"] for row in report._resolve_project_rows(home)] == [
        _digest(survivor), _digest(project)]
    for host in [survivor, project]:
        target = host / "references/topic.md"
        target.parent.mkdir()
        target.write_text("evidence")
        evidence = refread.resolve_ref_target(home, target)
        assert evidence is not None and evidence.key == f"project:{_digest(host)}/references/topic.md"
    assert hosts.load_hosts(home).project_modes == {str(project): "plain"}
    hosts.host_remove(home, project, registration="project", note="Retire the second project.")
    sha = git(home, "rev-parse", "--short", "HEAD").stdout.strip()
    assert git(home, "show", "-s", "--format=%s", sha).stdout.strip() == f"self-learn: host remove project {project}"
    registry = git(home, "show", f"{sha}:hosts.yaml").stdout
    assert str(survivor) in registry and str(project) not in registry
    trailer = git(home, "show", "-s", "--format=%(trailers:key=By,valueonly)", sha).stdout.strip()
    assert hosts.removed_hosts(home) == {str(project): (sha, trailer)}
    assert hosts.registration_problem(home, str(project)) == (
        f"{project} was taken out of the registry (ledger commit {sha}, By: {trailer or 'not recorded'}); "
        "a removal undoes a registration and stands, so self-learn never registers it again on its own")
    assert overseer._registered_labels(home, map(str, [project, survivor])) == {
        str(project): "removed", str(survivor): "git"}
    assert refread.resolve_ref_target(home, project / "references/topic.md") is None
    kept = refread.resolve_ref_target(home, survivor / "references/topic.md")
    assert kept is not None and kept.bucket == _digest(survivor)
    assert hosts.load_hosts(home).projects == [survivor]


@posix
def test_roots_and_noncreating_lookup(tmp_path, monkeypatch):
    profile, ambient, cache, runtime = [tmp_path / n for n in ("profile", "decoy", "cache", "run")]
    for folder in (profile, ambient, cache, runtime):
        _marker(folder, folder.name.encode())
    monkeypatch.setenv("HOME", str(profile))
    monkeypatch.chdir(tmp_path)
    legacy = cache / "claude-skills/self-learn"
    _marker(legacy, b"legacy content")
    before = set(cache.rglob("*"))
    for key in ("SELF_LEARN_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(key, raising=False)
    _marker(profile / ".self-learn", b"default ledger")
    _marker(profile / ".cache/self-learn", b"default cache")
    for value in (None, ""):
        if value == "":
            monkeypatch.setenv("SELF_LEARN_HOME", value)
            monkeypatch.setenv("XDG_CACHE_HOME", value)
        assert (ledger.resolve_home() / "marker").read_bytes() == b"default ledger"
        assert (cache_gc.cache_root() / "marker").read_bytes() == b"default cache"

    monkeypatch.setenv("SELF_LEARN_HOME", str(ambient))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    assert (names.user_home() / "marker").read_bytes() == b"profile"
    assert (ledger.resolve_home() / "marker").read_bytes() == b"decoy"
    assert (names.ledger_home({}) / "marker").read_bytes() == b"default ledger"
    assert (names.cache_root({}) / "marker").read_bytes() == b"default cache"
    assert (names.cache_root().parent / "marker").read_bytes() == b"cache"
    assert (names.ledger_home({"SELF_LEARN_HOME": "~/.self-learn"}) / "marker").read_bytes() == b"default ledger"
    assert names.home_digest("relative/home") == "3df6e04b"
    assert names.home_cache("relative/home") == cache / "self-learn/home-3df6e04b"

    link = tmp_path / "link"
    link.symlink_to(profile, target_is_directory=True)
    expected = cache / "self-learn" / ("home-" + _digest(link))
    assert cache_gc.home_digest(link) != cache_gc.home_digest(profile)
    calls = []

    def fallback():
        calls.append(1)
        return serve.cache_dir_readonly(link)

    assert names.runtime_root(fallback=fallback) == runtime / "self-learn"
    assert (names.runtime_root().parent / "marker").read_bytes() == b"run"
    assert calls == []
    monkeypatch.setenv("XDG_RUNTIME_DIR", "")
    assert names.runtime_root(fallback=fallback) == expected
    assert calls == [1]
    assert names.runtime_root(link) == serve.cache_dir_readonly(link) == names.home_cache(link) == expected
    assert set(cache.rglob("*")) == before

    # A call-time resolver changes the ambient cache. Migration and the new
    # directory must both use the base already read before the resolver ran.
    def resolve_and_switch():
        monkeypatch.setenv("XDG_CACHE_HOME", str(ambient))
        return link

    monkeypatch.setattr(worker, "resolve_home", resolve_and_switch)
    assert worker.cache_dir() == expected
    assert (expected / ".home").read_bytes() == (str(link) + "\n").encode()
    assert (expected / "marker").read_bytes() == b"legacy content"
    assert not (legacy / "marker").exists()
    assert set(ambient.iterdir()) == {ambient / "marker"}


@posix
def test_claude_policy_settings_and_identifiers(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    default, runtime, transcripts, reference, explicit = [
        tmp_path / n for n in (".claude", "runtime", "transcripts", "reference", "setting")]
    _marker(default, b"default")
    _marker(runtime, b"runtime")
    _marker(transcripts / "projects", b"transcripts")
    _marker(reference / "skills/synced", b"reference")
    _marker(explicit, b"setting")
    for key in ("SELF_LEARN_CLAUDE_DIR", "SELF_LEARN_TRANSCRIPTS_DIR", "SELF_LEARN_TRANSCRIPT_ROOTS",
                "SELF_LEARN_SKILL_REFERENCE_SYNCED_ROOT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(transcripts))
    assert (selfcheck.claude_runtime_dir() / "marker").read_bytes() == b"default"
    assert (session_copies.claude_projects_dir() / "marker").read_bytes() == b"transcripts"
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(runtime))
    assert (names.claude_root(use="default") / "marker").read_bytes() == b"default"
    assert hook_compiler.command_root(default) == "$HOME/.claude"
    assert (selfcheck.claude_runtime_dir() / "marker").read_bytes() == b"runtime"
    assert session_copies.claude_projects_dir() == runtime / "projects"
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(reference))
    assert (skill_reference.example_roots()[1] / "marker").read_bytes() == b"reference"
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", "")
    assert names.claude_root(use="reference") == Path(".")
    assert skill_reference.example_roots()[1] == Path("skills/synced")
    assert (session_copies.claude_projects_dir() / "marker").read_bytes() == b"transcripts"

    # The reference policy evaluates Path.home() even with an override.
    def missing_home():
        raise RuntimeError("missing profile")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "home", staticmethod(missing_home))
        patch.setenv("SELF_LEARN_CLAUDE_DIR", "~/verbatim")
        assert selfcheck.claude_runtime_dir() == Path("~/verbatim")
        with pytest.raises(RuntimeError, match="missing profile"):
            skill_reference.example_roots()
    assert (names.claude_root(use="default") / "marker").read_bytes() == b"default"
    env = make_env(tmp_path)
    (env.ledger / "config.yaml").write_text(
        'miner:\n  transcripts_dir: "~/setting"\nrefs:\n  transcript_roots: "~/runtime::~/setting"\n')
    assert (miner.transcripts_root(env.ledger) / "marker").read_bytes() == b"setting"
    assert [(p / "marker").read_bytes() for p in refs.transcript_roots(env.ledger)] == [b"runtime", b"setting"]

    project = tmp_path / "Prój-- ect"
    projects = session_copies.claude_projects_dir()
    hint = re.sub(r"[^A-Za-z0-9]", "-", str(project))
    slug = str(project).replace("/", "-") + "-" + _digest(project)
    assert tasks.folder_slug(project) == hint and hosts.slug_for(project) == slug
    # A matching session in the first folder catches an accidental fallback scan.
    for folder, payload in [("!decoy", b"decoy"), (hint, b"transcript")]:
        (projects / folder).mkdir()
        (projects / folder / "session.jsonl").write_bytes(payload)
    match = session_copies._find(projects, "session", project)
    assert match is not None and match.read_bytes() == b"transcript"
    _marker(env.ledger / "projects" / slug, b"ledger")
    bucket = hosts._project_bucket_for(env.ledger, str(project))
    assert bucket is not None and (bucket / "marker").read_bytes() == b"ledger"


@posix
def test_git_literals_tree_paths_and_porcelain(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    init_repo(repo)
    git(repo, "config", "core.quotepath", "true")
    git(repo, "config", "status.renames", "true")
    monkeypatch.chdir(tmp_path)
    absolute = repo / "café.txt"
    relative = Path("relative.txt")
    link = repo / "link"
    link.symlink_to(absolute.name)
    absolute.write_bytes(b"absolute\x00blob\r\n")
    (repo / relative).write_bytes(b"repository bytes\n")
    (repo / "kept").write_bytes(b"keep in index\n")
    git(repo, "add", "--", "kept")
    argv = []
    launch = gitops.procs.run_command

    def observe(args, **kwargs):
        argv.append(list(args))
        return launch(args, **kwargs)

    monkeypatch.setattr(gitops.procs, "run_command", observe)
    assert gitops.stage(repo, [relative, link]) == [link]
    assert argv[-1] == ["git", "-C", str(repo), "add", "--", str(link)]
    relative.write_bytes(b"cwd decoy")
    operands = [absolute, relative, link]
    assert gitops.stage(repo, operands) == operands
    assert argv[-1] == ["git", "-C", str(repo), "add", "--", str(absolute), "relative.txt", str(link)]
    sha = gitops.commit(repo, "scoped paths", paths=operands)
    assert ["git", "-C", str(repo), "commit", "-q", "-m", "scoped paths", "--",
            str(absolute), "relative.txt", str(link)] in argv

    def raw(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args])

    assert raw("ls-tree", "-rz", "--name-only", sha).split(b"\0") == [
        absolute.name.encode(), b"link", b"relative.txt", b""]
    assert raw("show", f"{sha}:{absolute.name}") == absolute.read_bytes()
    assert raw("show", f"{sha}:link") == absolute.name.encode()
    assert raw("show", f"{sha}:relative.txt") == b"repository bytes\n"
    assert raw("diff", "--cached", "--name-only", "-z") == b"kept\0"
    assert raw("show", ":kept") == b"keep in index\n"
    assert raw("ls-files", "-s", "--", "link").startswith(b"120000 ")
    git(repo, "mv", "relative.txt", "renamed.txt")
    absolute.write_bytes(b"changed")
    (repo / "untracked").write_bytes(b"new")
    status = raw("status", "--porcelain", "-uall").decode().splitlines()
    expected = [(s[:2], repo / s[3:].split(" -> ", 1)[-1].strip('"')) for s in status if len(s) >= 4]
    assert set(expected) == {("A ", repo / "kept"), ("R ", repo / "renamed.txt"),
                             ("??", repo / "untracked"), (" M", repo / r"caf\303\251.txt")}
    assert reconcile._porcelain(repo) == expected
    assert argv[-1] == ["git", "-C", str(repo), "status", "--porcelain", "-uall"]


@posix
def test_relative_keys_and_pointer_fallback(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    monkeypatch.setenv("HOME", str(profile))
    root = profile / "project"
    surface = root / "CLAUDE.md"
    target = root / "references/topic.md"
    outside = tmp_path / "outside.md"
    assert names.relative_key(root, root) == "."
    assert names.relative_key(root, outside, method="relpath") == "../../outside.md"
    assert compilers.pointer_token(surface, target) == "references/topic.md"
    assert compilers.pointer_token(surface, root) == "."
    assert compilers.pointer_token(surface, root / "..draft") == "~/project/..draft"
    assert compilers.pointer_token(surface, profile / "notes") == "~/notes"
    assert compilers.pointer_token(surface, outside) == str(outside)
    with pytest.raises(ValueError):
        names.relative_key(root, outside)
    assert names.relative_key(root, target) == "references/topic.md"
    assert compiled.region_key(root, outside) == str(outside)
    key = compiled.region_key(root, surface, "pointer")
    path = compiled.write_entry(tmp_path, "stored", key, region="pointer", sha256="a" * 64,
                                based_on_sha256=None, nbytes=31, by="test", host=str(root), mode="plain")
    assert path == tmp_path / "compiled/stored.yaml"
    assert b"CLAUDE.md#pointer:" in path.read_bytes()
    assert compiled.load_record(tmp_path, "stored")["targets"]["CLAUDE.md#pointer"]["bytes"] == 31


@posix
def test_ledger_default_is_the_module_constant_read_at_call_time(tmp_path, monkeypatch):
    """`ledger.resolve_home()` used to read `ledger.DEFAULT_HOME` on every
    call. The facade keeps its own spelling of the default, so the
    constant is passed through: a rebound constant must still take
    effect, and the environment variable must still win over it."""
    monkeypatch.delenv("SELF_LEARN_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "profile"))
    assert ledger.resolve_home() == tmp_path / "profile" / ".self-learn"  # the shipped default
    monkeypatch.setattr(ledger, "DEFAULT_HOME", str(tmp_path / "rebound"))
    assert ledger.resolve_home() == tmp_path / "rebound"
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "from-env"))
    assert ledger.resolve_home() == tmp_path / "from-env"


def test_windows_import_then_unsupported(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"original")
    script = """
        import os, sys
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch

        root = Path(sys.argv[1])
        assert "self_learn.primitives.names" not in sys.modules
        # Select only the facade's import branch on a POSIX test host.
        with (
            patch.object(os, "name", "nt"),
            patch.object(Path, "home", side_effect=AssertionError("looked up home at import")),
            patch.object(Path, "expanduser", side_effect=AssertionError("expanded at import")),
            patch.object(Path, "resolve", side_effect=AssertionError("resolved at import")),
        ):
            from self_learn.primitives import names
        from self_learn import cli, gitops, hosts, ledger
        if os.name != "nt":
            names.os = gitops.os = SimpleNamespace(name="nt")

        p = root / "sentinel"
        operations = [
            (names.project_slug, (p,), {}), (names.project_digest, (p,), {}),
            (names.home_spelling, (p,), {}), (names.home_digest, (p,), {}),
            (names.path_fingerprint, ("text",), {"length": 8}),
            (names.registration_key, (p,), {}), (names.component_path, (root, "new"), {}),
            (names.ledger_home, (), {}), (names.cache_root, (), {}), (names.user_home, (), {}),
            (names.home_cache, (p,), {}), (names.home_cache_for, (root, p), {}),
            (names.runtime_root, (p,), {}), (names.claude_root, (), {"use": "reference"}),
            (names.user_claude_file, (p,), {}), (names.git_arg, (root, p), {}),
            (names.relative_key, (root, p), {}), (names.pointer_token, (p, p), {}),
            (names.worktree_label_path, (p,), {}),
            (names.claude_folder_hint, (p,), {"style": "miner"}),
            (gitops.porcelain_paths, (root,), {}),
        ]
        assert "self_learn.primitives._names_posix" not in sys.modules
        assert all(callable(fn) for fn, _, _ in operations)
        print("imported", *(fn.__name__ for fn, _, _ in operations), flush=True)
        assert p.read_bytes() == b"original"
        events = []
        def observe(event, args):
            if event in ("open", "os.mkdir", "os.remove", "os.rename", "os.scandir", "subprocess.Popen"):
                events.append(event)
        sys.addaudithook(observe)
        control = root / "control"
        control.mkdir()
        (control / "marker").write_bytes(b"detected")
        assert "os.mkdir" in events and "open" in events
        assert (control / "marker").read_bytes() == b"detected"
        def unexpected_git(*args, **kwargs):
            raise AssertionError("dispatched Git on Windows")
        def unexpected_lookup(*args, **kwargs):
            raise AssertionError("looked up a path before refusing the operation")
        with (
            patch.object(gitops, "_git", unexpected_git),
            patch.multiple(Path, home=unexpected_lookup, expanduser=unexpected_lookup, resolve=unexpected_lookup),
        ):
            for fn, args, kwargs in operations:
                events.clear()
                try:
                    fn(*args, **kwargs)
                except NotImplementedError:
                    pass
                else:
                    raise AssertionError(fn.__name__ + " returned")
                assert not events, (fn.__name__, events)
        assert "self_learn.primitives._names_posix" not in sys.modules
        assert set(root.iterdir()) == {p, control}
        assert p.read_bytes() == b"original"
    """
    done = subprocess.run([sys.executable, "-B", "-c", textwrap.dedent(script), str(tmp_path)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "imported project_slug project_digest home_spelling home_digest path_fingerprint registration_key "
        "component_path ledger_home cache_root user_home home_cache home_cache_for runtime_root claude_root "
        "user_claude_file git_arg relative_key pointer_token worktree_label_path claude_folder_hint porcelain_paths"]
    assert sentinel.read_bytes() == b"original"
    assert (tmp_path / "control/marker").read_bytes() == b"detected"
