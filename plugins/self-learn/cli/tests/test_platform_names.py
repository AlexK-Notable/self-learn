"""S-167. Historical Linux storage names and native Windows names and folders."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from self_learn.primitives import names

if os.name != "nt":
    from self_learn import (
        cache_gc, compiled, compilers, gitops, hook_compiler, hosts, ledger, ledger_ops,
        miner, reconcile, refread, refs, report, selfcheck, serve, session_copies,
        settings, skill_reference, worker,
    )
    from self_learn.mining import tasks
    from self_learn.overseer import run as overseer
    from support import git, init_repo, make_env, make_knowledge

windows = pytest.mark.skipif(os.name != "nt", reason="native Windows storage contract")
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


def test_native_backend_is_selected_lazily():
    script = """
        import os, sys
        from unittest.mock import patch
        from pathlib import Path
        with (patch.object(Path, "home", side_effect=AssertionError),
              patch.object(Path, "expanduser", side_effect=AssertionError),
              patch.object(Path, "resolve", side_effect=AssertionError)):
            from self_learn.primitives import names
            prefix = "self_learn.primitives._names_"
            assert not any(k.startswith(prefix) for k in sys.modules)
            assert names.path_fingerprint("text", length=8) == "982d9e3e"
            selected = "windows" if os.name == "nt" else "posix"
            assert [k for k in sys.modules if k.startswith(prefix)] == [prefix + selected]
            assert "platformdirs" not in sys.modules
    """
    subprocess.run([sys.executable, "-B", "-c", textwrap.dedent(script)], check=True, timeout=30)


@windows
def test_windows_project_vectors(monkeypatch):
    # Supply OS answers for fixed drive/UNC names without probing a network share.
    calls = []

    def existing(path, *, strict):
        calls.append((path, strict))
        return path

    monkeypatch.setattr(Path, "resolve", existing)
    vectors = {
        r"C:\A\B": "w1-b-6337bd8590408e37ec96ceca7af3b8a1",
        r"\\SERVER\Share\A B": "w1-a-b-165c372e1c5a8e064ee1cf82ab8253b2",
        r"C:\first\Same": "w1-same-230c66397ee7d4ef0f54d90ac7c3cb3d",
        r"C:\second\Same": "w1-same-70680ee2e1a091fddefc4a671d58b629",
        r"C:\space here\A -- B": "w1-a-b-c35670b4b8398fe5fb20d9f21a1fbe49",
        r"C:\w\é": "w1-project-aa0cf228f238e200fe4035a0170547ca",
        "C:/w/e\u0301": "w1-e-f8f87be736a20a8b7794b69040fac9bb",
        r"C:\w\資料": "w1-project-cf5235a4eda27cd6ecb184eced89e728",
        "C:/" + "Long Folder/" * 42 + "T" * 48: "w1-" + "t" * 32 + "-3865dc7b571aec7ff3c20ed0d39e1aed",
    }
    for raw, expected in vectors.items():
        calls.clear()
        assert names.project_slug(raw) == expected
        assert names.project_digest(raw) == expected.rpartition("-")[2][:8]
        assert calls == [(Path(raw), True)] * 2


@windows
def test_windows_project_alias_and_refusals(tmp_path, monkeypatch):
    project = tmp_path / "Mixed café"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    key = os.path.normcase(str(project.resolve(strict=True)))
    digest = hashlib.sha256(key.encode()).hexdigest()
    for alias in (project, "mixed CAFÉ", project.as_posix().upper()):
        assert Path(alias).samefile(project)
        assert names.project_slug(alias) == "w1-mixed-caf-" + digest[:32]
        assert names.project_digest(alias) == digest[:8]
        assert names.registration_key(alias) == key

    deep = project.joinpath(*(["long folder " + "x" * 40] * 6), "Final Folder")
    deep.mkdir(parents=True)
    deep_key = os.path.normcase(str(deep.resolve(strict=True)))
    assert len(deep_key) > 260
    assert names.project_slug(deep) == "w1-final-folder-" + hashlib.sha256(deep_key.encode()).hexdigest()[:32]
    with pytest.raises(FileNotFoundError):
        names.project_slug(tmp_path / "missing")
    monkeypatch.setattr(Path, "resolve", lambda *a, **kw: pytest.fail("resolved invalid input"))
    for raw in ("C:place", "C:", "/place", r"\\?\C:\place", r"\\.\NUL", "a:b:c",
                "C:/base/file:stream", r"\\host\share:stream\x", "NUL.txt", "bad.", "bad "):
        with pytest.raises(ValueError):
            names.project_slug(raw)


@windows
def test_windows_components(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    assert names.component_path(root, "résumé [1]", suffix=".yaml") == root / "résumé [1].yaml"
    assert names.component_path(root, "😀" * 127 + "a").parent == root
    assert list(root.iterdir()) == []

    invalid = ["", ".", "..", "C:x", "/base", r"\\.\NUL", "end ", "end.", "x" * 256, "😀" * 128]
    invalid += ["a" + char + "b" for char in '<>:"/\\|?*\0\n\x1f']
    devices = ["con", "PRN", "Aux", "NUL", *(f"{p}{n}" for p in ("com", "LPT") for n in range(1, 10))]
    invalid += [d + ext for d in devices for ext in ("", ".txt")]
    bad_pairs = [(n, ".ok") for n in invalid] + [
        ("valid", "."), ("valid", " "), ("valid", "/escape"), ("CO", "N.log"), ("a" * 255, "b")]
    with monkeypatch.context() as patch:
        patch.setattr(Path, "__truediv__", lambda *a: pytest.fail("joined invalid input"))
        for name, suffix in bad_pairs:
            with pytest.raises(ValueError):
                names.component_path(root, name, suffix=suffix)


@windows
def test_windows_junction_boundary(tmp_path):
    import _winapi

    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    _marker(outside, b"outside")
    link = repo / "junction"
    _winapi.CreateJunction(str(outside), str(link))
    assert (link / "marker").samefile(outside / "marker")
    assert names.project_slug(link) == names.project_slug(outside)
    assert names.home_spelling(link) == names.home_spelling(outside)
    assert names.home_cache_for(repo, link) == names.home_cache_for(repo, outside)
    assert names.component_path(repo, "ordinary") == repo / "ordinary"
    with pytest.raises(ValueError):
        names.component_path(repo, "junction")
    with pytest.raises(ValueError):
        names.component_path(link / "absent", "new")
    assert names.git_arg(repo, link) == "junction"
    with pytest.raises(ValueError):
        names.git_arg(repo, link / "marker")
    assert set(outside.iterdir()) == {outside / "marker"}
    assert (outside / "marker").read_bytes() == b"outside"


@windows
def test_windows_cache_and_ledger_in_fresh_processes(tmp_path):
    profile, local, roaming = (tmp_path / n for n in ("profile", "local", "roaming"))
    for folder in (profile, local, roaming):
        _marker(folder, folder.name.encode())
    project = profile / "Mixed Home"
    project.mkdir()
    before = set(tmp_path.rglob("*"))
    env = dict(os.environ, HOME=str(profile), USERPROFILE=str(profile),
               WIN_PD_OVERRIDE_LOCAL_APPDATA=str(local), WIN_PD_OVERRIDE_APPDATA=str(roaming))
    for key in ("SELF_LEARN_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        env.pop(key, None)
    script = """
        import json, os, sys
        from pathlib import Path
        from self_learn.primitives import names
        from platformdirs import user_data_path
        home = sys.argv[1]
        # Independent real lookup checks that the other Known Folder is isolated too.
        assert (user_data_path(roaming=True) / "marker").read_bytes() == b"roaming"
        print(json.dumps([str(p) for p in (
            names.user_home(), names.ledger_home(), names.ledger_home(default="~/custom"),
            names.cache_root(), names.home_spelling(home), names.home_digest(home),
            names.home_cache(home), names.home_cache_for(names.cache_root(), Path(home)),
            names.runtime_root(home), names.runtime_root(fallback=lambda: Path("fallback")),
            names.home_cache(), names.ledger_home({"SELF_LEARN_HOME": "~/injected"}),
            names.cache_root({"XDG_CACHE_HOME": "~/injected"}),
        )]))
    """
    key = os.path.normcase(str(project.resolve(strict=True)))
    digest = _digest(key)
    for mode, alias in (("default", str(project)), ("empty", project.as_posix().upper()),
                        ("override", "Mixed Home")):
        child_env = env.copy()
        cache, ledger = local / "self-learn/Cache", profile / ".self-learn"
        custom, run_base = profile / "custom", None
        if mode == "empty":
            child_env.update(SELF_LEARN_HOME="", XDG_CACHE_HOME="", XDG_RUNTIME_DIR="")
        elif mode == "override":
            child_env.update(SELF_LEARN_HOME=str(project), XDG_CACHE_HOME=str(profile / "xdg"),
                             XDG_RUNTIME_DIR=str(profile / "run"))
            cache, ledger, custom = profile / "xdg/self-learn", project, project
            run_base = profile / "run/self-learn"
        result = subprocess.check_output([sys.executable, "-B", "-c", textwrap.dedent(script), alias],
                                         env=child_env, cwd=profile, text=True, timeout=30)
        per_home = cache / ("home-" + digest)
        default_cache = cache / ("home-" + _digest(os.path.normcase(str(ledger))))
        assert json.loads(result) == [str(p) for p in (
            profile, ledger, custom, cache, key, digest, per_home, per_home, run_base or per_home,
            run_base or Path("fallback"), default_cache, profile / "injected", profile / "injected/self-learn")]
        assert set(tmp_path.rglob("*")) == before
        assert (local / "marker").read_bytes() == b"local"


@windows
def test_windows_claude_roots_and_hints(tmp_path, monkeypatch):
    profile, config, override, explicit = (tmp_path / n for n in ("profile", "config", "override", "explicit"))
    monkeypatch.setenv("HOME", str(profile))
    monkeypatch.setenv("USERPROFILE", str(profile))
    for folder in (profile / ".claude", config, override, explicit):
        _marker(folder, folder.name.encode())
    monkeypatch.delenv("SELF_LEARN_CLAUDE_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    for env, expected in (({}, profile / ".claude"), ({"CLAUDE_CONFIG_DIR": str(config)}, config),
                          ({"SELF_LEARN_CLAUDE_DIR": str(override)}, override),
                          ({"SELF_LEARN_CLAUDE_DIR": ""}, config)):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        for use in ("default", "runtime", "transcripts", "reference"):
            assert (names.claude_root(use=use) / "marker").read_bytes() == expected.name.encode()
            assert names.claude_root(use=use, env={}) == profile / ".claude"
        assert names.user_claude_file(Path("~/.claude/CLAUDE.md")) == expected / "CLAUDE.md"
        assert names.user_claude_file(explicit / "marker").read_bytes() == b"explicit"
    for style in ("transcript", "miner"):
        assert names.claude_folder_hint(r"C:\A-b\c é", style=style) == "C--A-b-c--"


@windows
def test_windows_git_operands_keys_and_pointers(tmp_path, monkeypatch):
    from self_learn.primitives import procs

    def unexpected_launch(*args, **kwargs):
        pytest.fail("Git operand validation launched a command")

    monkeypatch.setattr(procs, "run_command", unexpected_launch)
    monkeypatch.setattr(subprocess, "Popen", unexpected_launch)
    repo = tmp_path / "repo"
    profile = tmp_path / "profile"
    repo.mkdir()
    _marker(repo / "in repo", b"in repository")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(profile))
    monkeypatch.setenv("USERPROFILE", str(profile))
    target = repo / "in repo/é[1].md"
    target.touch()
    relative = r"in repo\é[1].md"
    assert not Path(relative).exists() and target.exists()
    assert names.git_arg(repo, relative) == names.git_arg(repo, target) == "in repo/é[1].md"
    other = Path("Z:/" if repo.drive.upper() != "Z:" else "Y:/") / "elsewhere"
    for bad in ("../outside", "..", r"\rooted", r"C:relative", r"\\?\C:\file", other):
        with pytest.raises(ValueError):
            names.git_arg(repo, bad)
    assert names.relative_key(repo, target) == "in repo/é[1].md"
    assert names.relative_key(repo, profile / "item", method="relpath") == "../profile/item"
    with pytest.raises(ValueError):
        names.relative_key(repo, profile)
    surface = repo / "CLAUDE.md"
    assert names.pointer_token(surface, target) == "in repo/é[1].md"
    assert names.pointer_token(other / "surface", profile / "notes") == "~/notes"
    assert names.pointer_token(surface, other) == str(other)
    assert names.worktree_label_path(Path("A/.claude/worktrees/branch")) == "A/.claude/worktrees/branch"


@windows
def test_windows_porcelain_bytes(tmp_path):
    # The integration lane supplies the output of git status --porcelain -z.
    parser = names._backend().porcelain_paths
    data = "R  new é[1]\0old -> é\0?? another é\0 C copied\0from\0".encode()
    assert parser(tmp_path, data) == [("R ", tmp_path / "new é[1]"), ("??", tmp_path / "another é"),
                                      (" C", tmp_path / "copied")]
    assert parser(tmp_path, b"") == []
    for invalid in (b"?? bad\xff\0", b"R  good\0bad\xff\0"):
        with pytest.raises(UnicodeDecodeError):
            parser(tmp_path, invalid)
    for truncated in (b"?? path", b"R  new\0", b"M\0"):
        with pytest.raises(ValueError):
            parser(tmp_path, truncated)
