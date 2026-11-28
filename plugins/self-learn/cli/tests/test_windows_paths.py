"""Lane w6-paths: Windows paths in premises and in host matching.

- A premise path on Windows may be drive-rooted (``C:\\x``, ``C:/x``) or
  home-relative (``~\\x``, ``~/x``). Network (UNC), device (``\\\\?\\``,
  ``\\\\.\\``), drive-relative (``C:x``) and root-relative (``\\x``) paths
  are refused, and so is a component Windows would not open as the name
  typed: a reserved device name, an alternate data stream, a trailing dot
  or space, an 8.3 short name, a wildcard.
- The credential rules hold on Windows: every Linux name, split on both
  separators and compared case-insensitively, plus the Windows stores and
  system trees.
- A path from Linux (``/x``, or a ``~/`` path Windows cannot name) still
  loads on Windows and its probe is ``unavailable`` with cause ``platform``
  (S-178's rule): never run, never broken.
- A removed worktree whose recorded path differs in case files under its
  registered host; a junction at a host's own entry is refused at the gate
  every write passes.

The pure rules (``PureWindowsPath`` and ``ntpath``, no filesystem) run on
both platforms; the tests that touch the real filesystem run on Windows.
The Linux tests pin the unchanged Linux answers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from self_learn import hosts, premise_sweep, premises

windows = pytest.mark.skipif(os.name != "nt", reason="native Windows path contract")
linux = pytest.mark.skipif(os.name == "nt", reason="Linux path contract")

# ------------------------------------------------------- pure: both platforms

_NATIVE_SHAPES = [
    ("C:\\Users\\me\\notes.txt", None),
    ("C:/Users/me/notes.txt", None),
    ("c:\\x\\y", None),
    ("~\\notes\\a.md", None),
    ("~/notes/a.md", None),
    ("C:\\Program Files\\Git\\cmd\\git.exe", None),
    ("C:\\x\\console", None),  # a control: not a device name
    ("\\\\server\\share\\x", "network (UNC) path"),
    ("//server/share/x", "network (UNC) path"),
    ("\\\\?\\C:\\x", "device path"),
    ("\\\\.\\COM1", "device path"),
    ("//./pipe/x", "device path"),
    ("C:foo\\bar", "drive-relative"),
    ("\\foo\\bar", "no drive letter"),
    ("/home/me/x", "no drive letter"),
    ("~user\\x", "must start with a drive"),
    ("relative\\x", "must start with a drive"),
    ("C:\\x\\..\\y", "'.' or '..' segments"),
    ("C:\\x\\\\y", "'.' or '..' segments"),
    ("C:\\", "'.' or '..' segments"),
    ("C:\\x\\CON", "reserved Windows device name"),
    ("C:\\x\\nul.txt", "reserved Windows device name"),
    ("C:\\x\\COM1.log", "reserved Windows device name"),
    ("C:\\x\\LPT¹", "reserved Windows device name"),
    ("C:\\x\\CONIN$", "reserved Windows device name"),
    ("C:\\x\\file.txt:secret", "alternate data stream"),
    ("C:\\x\\file.txt::$DATA", "alternate data stream"),
    ("C:\\x\\name.", "ends in a dot or a space"),
    ("C:\\x\\name ", "ends in a dot or a space"),
    ("C:\\PROGRA~1\\x", "8.3 short name"),
    ("~\\APPDAT~1\\x", "8.3 short name"),
    ("C:\\x\\a*b", "character Windows does not allow"),
    ("C:\\x\\a?b", "character Windows does not allow"),
    ('C:\\x\\a"b', "character Windows does not allow"),
]


@pytest.mark.parametrize("value, refused", _NATIVE_SHAPES)
def test_windows_native_path_rules(value, refused):
    problem = premises._windows_native_problem(value, "path")  # noqa: SLF001
    if refused is None:
        assert problem is None
    else:
        assert problem is not None and refused in problem, problem


_REFUSED_CREDENTIALS = [
    "C:\\Users\\me\\.ssh\\config",
    "c:/users/me/.SSH/config",
    "~\\.aws\\credentials",
    "~/.claude/.credentials.json",
    "C:\\Users\\me\\.claude\\.CREDENTIALS.JSON",
    "C:\\Users\\me\\AppData\\Roaming\\Microsoft\\Protect\\S-1-5-21\\key",
    "C:\\Users\\me\\AppData\\Local\\Microsoft\\Credentials\\ABC",
    "C:\\Users\\me\\AppData\\Local\\Microsoft\\Vault\\4BF4C442",
    "C:\\Users\\me\\AppData\\Roaming\\Microsoft\\Crypto\\RSA\\x",
    "C:\\Users\\me\\AppData\\Roaming\\Microsoft\\SystemCertificates\\My\\x",
    "C:\\Users\\me\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\Preferences",
    "C:\\Users\\me\\AppData\\Local\\Microsoft\\Edge\\User Data\\Local State",
    "C:\\Users\\me\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\a.default\\prefs.js",
    "C:\\Users\\me\\AppData\\Roaming\\GitHub CLI\\hosts.yml",
    "C:\\Users\\me\\AppData\\Roaming\\Microsoft\\Windows\\PowerShell\\PSReadLine\\ConsoleHost_history.txt",
    "C:\\Windows\\System32\\config\\SAM",
    "c:\\windows\\SERVICEPROFILES\\NetworkService\\x",
    "C:\\ProgramData\\ssh\\sshd_config",
    "C:\\ProgramData\\Microsoft\\Wlansvc\\Profiles\\x.xml",
    "C:\\Users\\me\\NTUSER.DAT",
    "C:\\Users\\me\\ntuser.dat.LOG1",
    "C:\\pagefile.sys",
    "C:\\keys\\server.ppk",
    "C:\\x\\.ssh.\\config",
    "C:\\x\\.ssh \\config",
    "\\\\server\\share\\x",
    "\\\\?\\UNC\\server\\share\\x",
    "\\\\.\\pipe\\x",
    "\\\\?\\C:\\Users\\me\\.ssh\\id_rsa",
    "C:\\repo\\.git\\config",
    "/proc/self/environ",
    "/home/me/.ssh/config",
]


@pytest.mark.parametrize("path", _REFUSED_CREDENTIALS)
def test_windows_credential_locations_are_refused(path):
    assert premises._windows_credential_problem(path, reads_content=True) is not None  # noqa: SLF001


@pytest.mark.parametrize(
    "path",
    [
        "C:\\Users\\me\\notes\\plan.md",
        "~/.claude/settings.json",
        "~\\.claude\\settings.json",
        "C:\\Program Files\\Git\\cmd\\git.exe",
        "\\\\?\\C:\\Users\\me\\notes.md",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "/home/me/notes.md",
    ],
)
def test_windows_ordinary_locations_pass_the_credential_rules(path):
    assert premises._windows_credential_problem(path, reads_content=True) is None  # noqa: SLF001


def test_windows_git_directory_is_refused_only_for_content():
    path = "C:\\repo\\.git\\config"
    assert premises._windows_credential_problem(path, reads_content=False) is None  # noqa: SLF001
    assert premises._windows_credential_problem(path, reads_content=True) is not None  # noqa: SLF001


@pytest.mark.parametrize("name", sorted(premises._CREDENTIAL_COMPONENTS))  # noqa: SLF001
def test_windows_refuses_every_linux_credential_name(name):
    # Upper-cased and between backslashes: case- and separator-insensitive.
    path = f"C:\\Users\\me\\{name.upper()}\\x"
    assert premises._windows_credential_problem(path, reads_content=False) is not None  # noqa: SLF001


@pytest.mark.parametrize(
    "value, foreign",
    [
        ("/home/me/.config/x.conf", "names a file on Linux"),
        ("/etc/fstab", "names a file on Linux"),
        ("~/notes/a:b", "alternate data stream"),
        ("~/x/NUL", "reserved Windows device name"),
        ("~/x/name.", "ends in a dot or a space"),
        ("~/notes/plan.md", None),
        ("C:\\x\\y", None),
        ("C:/x/NUL", None),  # written on Windows: refused by the policy, not foreign
        ("~\\x\\a:b", None),  # a backslash: written on Windows, refused
        ("\\\\server\\share\\x", None),
        (None, None),
    ],
)
def test_windows_foreign_paths(value, foreign):
    reason = premises._windows_foreign_reason(value)  # noqa: SLF001
    if foreign is None:
        assert reason is None
    else:
        assert reason is not None and reason.startswith("unavailable on Windows: ")
        assert foreign in reason


@pytest.mark.parametrize(
    "value, structure, policy",
    [
        ("C:\\Users\\me\\notes.md", True, True),
        ("~\\notes.md", True, True),
        ("~/notes.md", True, True),
        # A record written on Linux loads, and its probe is never refused.
        ("/home/me/notes.md", True, True),
        ("~/notes/a:b", True, True),
        # Shape is structure; the component rules are policy.
        ("C:\\x\\NUL", True, False),
        ("~\\a:b", True, False),
        ("C:\\Users\\me\\.ssh\\config", True, False),
        ("/home/me/.ssh/config", True, False),
        ("\\\\server\\share\\x", False, False),
        ("C:foo", False, False),
        ("\\foo", False, False),
        ("relative\\x", False, False),
    ],
)
def test_windows_probe_path_structure_and_policy(value, structure, policy):
    def ok(with_policy: bool) -> bool:
        return premises._windows_probe_path_problem(  # noqa: SLF001
            value, "path", reads_content=True, policy=with_policy) is None

    assert (ok(False), ok(True)) == (structure, policy)


@pytest.mark.parametrize(
    "value, stored",
    [
        ("~\\a\\b.md", "~/a/b.md"),
        ("~/a\\b.md", "~/a/b.md"),
        ("~/a/b.md", "~/a/b.md"),
        ("c:/a/b.md", "C:\\a\\b.md"),
        ("C:\\a/b.md", "C:\\a\\b.md"),
        ("/home/me/x", "/home/me/x"),
        (42, 42),
    ],
)
def test_windows_stored_spelling(value, stored):
    assert premises._windows_spelling(value) == stored  # noqa: SLF001


def test_windows_respelling_keeps_every_other_field():
    premise = {"id": "p1", "claim": "c", "probe": {"kind": "file-match", "path": "~\\a",
                                                    "contains": "c:/x"}, "holds_if": "equals"}
    out = premises._windows_respelled(premise)  # noqa: SLF001
    assert out == {**premise, "probe": {"kind": "file-match", "path": "~/a", "contains": "c:/x"}}
    assert list(out["probe"]) == ["kind", "path", "contains"]
    assert premises._windows_respelled({"id": "p2", "probe": None}) == {"id": "p2", "probe": None}  # noqa: SLF001


@pytest.mark.parametrize(
    "point, target, covered",
    [
        ("C:\\Fence", "c:\\fence\\a.txt", True),
        ("C:\\fence", "C:\\FENCE", True),
        ("C:\\fence\\", "C:/fence/a", True),
        ("\\\\?\\C:\\fence", "C:\\fence\\a", True),
        ("C:\\", "C:\\a", True),
        ("C:\\fence", "C:\\fencexy\\a", False),
        ("C:\\fence", "D:\\fence\\a", False),
    ],
)
def test_windows_fence_covers(point, target, covered):
    assert premises._windows_covers(point, target) is covered  # noqa: SLF001


def test_windows_which_looks_only_in_drive_rooted_path_entries():
    usable, skipped = premises._windows_path_entries(  # noqa: SLF001
        'C:\\bin;.;relative;\\\\srv\\share\\bin;"C:\\Program Files\\x";;D:/tools')
    assert usable == ["C:\\bin", "C:\\Program Files\\x", "D:/tools"]
    assert skipped == ["\\\\srv\\share\\bin"]


@pytest.mark.parametrize(
    "parts, found",
    [
        (("C:\\", "Repo", ".Claude", "Worktrees", "w1"), [2]),
        (("C:\\", "repo", ".claude", "worktrees", "w1", "sub"), [2]),
        (("C:\\", "repo", ".claude", "worktrees"), []),
        (("C:\\", "a", ".claude", "worktrees", "b", ".CLAUDE", "WORKTREES", "c"), [5, 2]),
        (("C:\\", ".claude", "worktrees", "x"), [1]),
        (("C:\\", "repo", ".claude", "work", "x"), []),
    ],
)
def test_windows_worktree_segments_match_case_insensitively(parts, found):
    assert hosts._worktree_segments_at(parts) == found  # noqa: SLF001


# ------------------------------------------------------------ Linux controls


@linux
def test_linux_premise_paths_unchanged():
    refused = premises._path_problem("C:\\Users\\me\\x", "p", reads_content=True)  # noqa: SLF001
    assert refused == "p must be absolute or start with ~/ (got 'C:\\\\Users\\\\me\\\\x')"
    assert premises._path_problem("/home/me/notes.md", "p", reads_content=True) is None  # noqa: SLF001
    assert premises._path_problem("~/notes.md", "p", reads_content=True) is None  # noqa: SLF001
    # Linux has no Windows credential names: a folder named "vault" stays probeable.
    assert premises.credential_path_problem("/home/me/vault/notes.md") is None
    assert premises._expand("~\\x", Path("/h")) == "~\\x"  # noqa: SLF001


@linux
def test_linux_removed_worktree_match_stays_case_sensitive(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = hosts.Hosts(projects=[repo])
    gone = repo / ".claude" / "worktrees" / "gone"
    assert hosts._removed_worktree_host(registry, gone) == repo.resolve()  # noqa: SLF001
    assert hosts._removed_worktree_host(registry, repo / ".Claude" / "Worktrees" / "gone") is None  # noqa: SLF001


# ------------------------------------------------- real filesystem: Windows


def _junction(link: Path, target: Path) -> None:
    import _winapi  # type: ignore[import-not-found]

    _winapi.CreateJunction(str(target), str(link))


def _sha(value: str) -> str | None:
    return premises.value_sha(premises.normalize_value(value))


@pytest.fixture
def base(tmp_path):
    """The temporary folder by its long name: a runner's TEMP can be an
    8.3 alias (RUNNER~1), which the premise rules refuse by design."""
    return tmp_path.resolve()


def _probe(kind: str, path: str, **extra) -> dict:
    return {"kind": kind, "path": path, **extra}


@windows
def test_windows_device_rule_agrees_with_the_names_facade():
    from self_learn.primitives import _names_windows

    for name in ("CON", "con.txt", "NUL", "nul.tar.gz", "COM1", "LPT9", "COM¹", "CONIN$",
                 "conout$.log", "AUX", "PRN", "console", "COM0", "LPT10", "nul_", "CON .txt",
                 "notes.md", "x.", "a:b", "a*b"):
        try:
            _names_windows._check_component(name)  # noqa: SLF001
            facade_refuses = False
        except ValueError:
            facade_refuses = True
        assert (premises._windows_component_problem(name) is not None) is facade_refuses, name  # noqa: SLF001


@windows
def test_windows_premises_validate_and_store_native_spellings():
    def premise(path: str, pid: str = "p1") -> dict:
        return {"id": pid, "claim": "the file is there", "probe": _probe("path", path)}

    for path in ("C:\\Users\\me\\notes.md", "c:/Users/me/notes.md", "~\\notes.md",
                 "~/notes.md", "/home/me/notes.md"):
        premises.validate_premises([premise(path)])
        premises.validate_premises([premise(path)], policy=False)
    for path in ("\\\\server\\share\\x", "C:notes.md", "\\notes.md", "C:\\x\\NUL",
                 "C:\\x\\a.txt:s", "~\\.ssh\\config", "C:\\Users\\me\\AppData\\Local\\Microsoft\\Vault\\x"):
        with pytest.raises(premises.PremiseError):
            premises.validate_premises([premise(path)])
    stored = premises.normalize_premises([premise("~\\notes\\a.md", "p1"), premise("c:/x/y.md", "p2"),
                                          premise("/home/me/z.md", "p3")])
    assert [p["probe"]["path"] for p in stored] == ["~/notes/a.md", "C:\\x\\y.md", "/home/me/z.md"]


@windows
def test_windows_native_paths_are_probed(base):
    (base / "notes.txt").write_text("hello premise\n", encoding="utf-8")
    (base / "conf.json").write_text(json.dumps({"mode": "plain"}), encoding="utf-8")
    env = premises.ProbeEnv(home=base)
    native = str(base / "notes.txt")
    for path in (native, native.replace("\\", "/"), "~\\notes.txt", "~/notes.txt"):
        obs = premises.run_probe(_probe("path", path), env)
        assert (obs.state, obs.shown) == (premises.OBS_OK, "file"), (path, obs.reason)
    assert premises.run_probe(_probe("path", str(base / "gone.txt")), env).shown == premises.MISSING
    found = premises.run_probe(_probe("file-match", "~\\notes.txt", contains="premise"), env)
    assert (found.state, found.shown) == (premises.OBS_OK, premises.PRESENT)
    key = premises.run_probe(_probe("json-key", str(base / "conf.json"), key="mode"), env)
    assert (key.state, key.shown) == (premises.OBS_OK, '"plain"')


@windows
def test_windows_home_path_with_the_home_gone_is_unavailable(base):
    # A ~\ path with the home folder gone is unavailable, never "missing".
    gone_home = premises.ProbeEnv(home=base / "no-such-home")
    obs = premises.run_probe(_probe("path", "~\\notes.txt"), gone_home)
    assert obs.state == premises.OBS_UNAVAILABLE and "home directory does not exist" in obs.reason


@windows
def test_windows_foreign_paths_are_platform_unavailable_and_never_broken(base):
    env = premises.ProbeEnv(home=base)
    for path in ("/home/me/notes.md", "~/x/NUL", "~/notes/a:b"):
        premise = {"id": "p1", "claim": "x", "probe": _probe("path", path)}
        obs = premises.observe(premise, env)
        assert obs is not None
        assert (obs.state, obs.cause) == (premises.OBS_UNAVAILABLE, premises.CAUSE_PLATFORM), path
        assert obs.reason.startswith("unavailable on Windows: "), obs.reason
        sig = premise_sweep._premise_sig(premise)  # noqa: SLF001
        rows = [premise_sweep._row(f"2026-11-2{n}T00:00:00Z", "lrn-00000001", "p1", "probe",  # noqa: SLF001
                                   obs, sig=sig) for n in range(premise_sweep.BROKEN_PROBE_SWEEPS)]
        assert premise_sweep.broken_tail(premise, rows) is None


@windows
def test_windows_ssh_folder_reached_through_a_junction_is_refused(base):
    secret = base / ".ssh"
    secret.mkdir()
    (secret / "config").write_text("Host x\n", encoding="utf-8")
    _junction(base / "innocent", secret)
    env = premises.ProbeEnv(home=base)
    for probe in (_probe("path", str(base / "innocent" / "config")),
                  _probe("file-match", "~\\innocent\\config", contains="Host")):
        obs = premises.run_probe(probe, env)
        assert obs.state == premises.OBS_UNAVAILABLE
        assert "resolves to a refused location" in obs.reason, obs.reason


@windows
def test_windows_junction_is_reported_as_a_link(base):
    real = base / "real"
    real.mkdir()
    _junction(base / "linked", real)
    env = premises.ProbeEnv(home=base)
    assert premises.run_probe(_probe("path", str(real)), env).shown == "dir"
    link = base / "linked"
    obs = premises.run_probe(_probe("path", str(link)), env)
    assert obs.state == premises.OBS_OK, obs.reason
    assert obs.value_sha == _sha("symlink:" + os.readlink(link)), obs.shown


@windows
def test_windows_read_fence_covers_children_in_any_case(base):
    for folder in ("Fence", "other"):
        (base / folder).mkdir()
        (base / folder / "a.txt").write_text("x", encoding="utf-8")
    env = premises.ProbeEnv(home=base, denied_roots=(str(base / "Fence"),))
    for path in (str(base / "Fence" / "a.txt"), str(base / "fence" / "A.TXT"),
                 str(base / "FENCE" / "a.txt").replace("\\", "/")):
        obs = premises.run_probe(_probe("path", path), env)
        assert obs.state == premises.OBS_UNAVAILABLE and "may not read" in obs.reason, (path, obs)
    assert premises.run_probe(_probe("path", str(base / "other" / "a.txt")), env).shown == "file"


@windows
def test_windows_which_never_answers_from_the_current_folder(base, monkeypatch):
    cwd, bin_dir = base / "cwd", base / "bin"
    cwd.mkdir()
    bin_dir.mkdir()
    (cwd / "tool.exe").write_bytes(b"")
    monkeypatch.chdir(cwd)
    probe = {"kind": "which", "name": "tool"}
    for path_env in (str(bin_dir), f".;{bin_dir}", f"cwd;{bin_dir}"):
        obs = premises.run_probe(probe, premises.ProbeEnv(home=base, path_env=path_env))
        assert obs.shown == premises.NOT_FOUND, (path_env, obs)
    (bin_dir / "tool.exe").write_bytes(b"")
    obs = premises.run_probe(probe, premises.ProbeEnv(home=base, path_env=f".;{bin_dir}"))
    # Windows matches PATHEXT case-insensitively, so the answer carries its spelling.
    exts = [e for e in os.environ.get("PATHEXT", ".EXE").split(";") if e]
    assert obs.value_sha in {_sha(str(bin_dir / ("tool" + e))) for e in exts}, obs


@windows
def test_windows_link_at_a_skills_root_is_refused_where_writes_resolve_it(base):
    from self_learn import skill_writer

    home = base / "ledger"
    home.mkdir()
    real = base / "skills"
    real.mkdir()
    link = base / "skills-link"
    _junction(link, real)
    assert hosts.host_path_problem(home, real, "skills-root", mode="plain", check_marker=False) is None
    problem = hosts.host_path_problem(home, link, "skills-root", mode="plain", check_marker=False)
    assert problem is not None and "junction or symbolic link" in problem
    with pytest.raises(hosts.HostsError, match="junction or symbolic link"):
        hosts.validate_host_path(home, link, "skills-root", mode="git")
    hosts.save_hosts(home, hosts.Hosts(skills_root=link))
    with pytest.raises(skill_writer._Refused, match="junction or symbolic link"):  # noqa: SLF001
        skill_writer._skills_root(home)  # noqa: SLF001


@windows
def test_windows_removed_worktree_in_another_case_files_under_its_host(base):
    home = base / "ledger"
    home.mkdir()
    repo = base / "Repo"
    repo.mkdir()
    hosts.save_hosts(home, hosts.Hosts(projects=[repo]))
    gone = base / "repo" / ".Claude" / "Worktrees" / "gone" / "sub"
    spelled = str(gone)
    for path in (spelled, spelled.replace("\\", "/"), spelled[0].lower() + spelled[1:]):
        assert hosts.capture_host_path(home, path) == repo.resolve(), path
    elsewhere = base / "other" / ".Claude" / "Worktrees" / "gone"
    assert hosts.capture_host_path(home, elsewhere) == elsewhere
