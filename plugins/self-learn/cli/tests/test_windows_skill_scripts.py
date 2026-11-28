"""Skill scripts on Windows: a verified managed copy and a declared interpreter.

Windows has no mode bits and no kernel shebang. An active script there is the
managed copy activation already writes (exclusive create, never a link). ``skill
script run`` reads it once under the ledger lock, checks the SHA-256 of exactly
those bytes against the ledger's committed activation, and runs that snapshot
from a private folder: Python scripts under ``sys.executable -I``, Bash scripts
under Git for Windows' bash.exe (``--noprofile --norc``) when the git.exe that
self-learn runs belongs to an installation that has one. No real model: the
review session is faked at the SDK backend, as in ``test_skill_scripts.py``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import test_skill_write as sk1
from self_learn import cli, skill_scripts as scripts, skill_writer
from self_learn.invocation_sdk import backend as sdk
from self_learn.primitives import capabilities, links, procs
from support import git

windows = pytest.mark.skipif(os.name != "nt", reason="Windows skill script contract")
posix = pytest.mark.skipif(os.name == "nt", reason="Linux skill script surface")

PY = "#!/usr/bin/env python3\n"
SH = "#!/usr/bin/env bash\nset -o noclobber\n"
COUNT_PY = PY + "import sys\nprint(len(sys.argv))\n"
COUNT_SH = SH + 'wc -l "$1"\n'
ARGV_PY = PY + "import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(3)\n"
ARGV_SH = SH + 'printf "[%s]" "$1" "$2" "$3" "$4" "$5" "$6"\ntest -f "$7"\n'
ARGV0_PY = PY + "import sys\nprint(sys.argv[0])\n"
# A literal "--", an empty word, spaces, a quote, a trailing backslash, a glob.
ARGS = ["--", "", "a b", 'q"uote', "trail\\", "a*b"]
USAGE = "Run with a local input path to count."
UNAVAILABLE = "unavailable on this machine"


def fake_review(monkeypatch):
    def run(self, spec):
        content = json.dumps({"verdict": "approve", "reasons": ["inspected effects"], "changes": [],
                              "version": json.loads(spec.prompt)["version"]})
        messages = ({"type": "init", "model": scripts.MODEL, "session": "fake-session"},
                    {"type": "assistant", "model": scripts.MODEL, "text": content, "tool_use": False})
        return sdk.SdkOutcome(ok=True, rc=0, stdout=content, detail="", failure=None, session_id="fake-session",
                              cost_usd=.12, init_models=(scripts.MODEL,), assistant_models=(scripts.MODEL,),
                              review_messages=messages)

    monkeypatch.setattr(sdk.SdkBackend, "text_session", run)


def _product_git() -> str:
    from self_learn.primitives import _procs_windows
    found = _procs_windows._executable("git", None, None)
    assert found, os.environ["PATH"]
    return os.path.realpath(found)


def _hide_git_bash(tmp_path: Path, monkeypatch) -> None:
    """A Git with no Bash, the shape of MinGit: the runner's real ``mingw64``
    runtime (hard links, or copies across volumes) in a scratch folder first on
    PATH, and every PATH entry inside the real Git installation removed."""
    real = Path(_product_git())
    exec_path = procs.run_bounded([str(real), "--exec-path"], timeout=60, check=True).stdout.strip()
    prefix = Path(exec_path).parent.parent
    top = prefix.parent
    assert (prefix / "bin" / "git.exe").is_file() and (top / "usr" / "bin" / "bash.exe").is_file(), (real, exec_path)
    fake = tmp_path / "MinGit" / "mingw64"
    for part in ("bin", "libexec", "share/git-core"):
        for folder, _dirs, files in os.walk(prefix / part):
            into = fake / Path(folder).relative_to(prefix)
            into.mkdir(parents=True, exist_ok=True)
            for name in files:
                try:
                    os.link(Path(folder) / name, into / name)
                except OSError:
                    shutil.copy2(Path(folder) / name, into / name)
    inside = os.path.normcase(str(top)) + os.sep
    kept = [e for e in os.environ["PATH"].split(os.pathsep)
            if e and not os.path.normcase(os.path.abspath(e) + os.sep).startswith(inside)]
    monkeypatch.setenv("PATH", os.pathsep.join([str(fake / "bin"), *kept]))
    # The Git the product resolves is the scratch one, and it works.
    assert os.path.normcase(_product_git()).startswith(os.path.normcase(str(fake)) + os.sep)
    assert procs.run_bounded(["git", "--version"], timeout=60).returncode == 0
    assert subprocess.run(["git", "--version"], capture_output=True, timeout=60).returncode == 0
    assert scripts._git_bash() is None


def _open_gate(monkeypatch):
    # ``skill`` is refused in the Windows capture profile until an integration
    # stage switches ledger and canon on; these tests open the gate themselves
    # (test_windows_production_defaults_refuse_run keeps them closed).
    monkeypatch.setitem(capabilities.AVAILABLE, "ledger", True)
    monkeypatch.setitem(capabilities.AVAILABLE, "canon", True)


def _make_env(tmp_path, monkeypatch):
    _open_gate(monkeypatch)
    env = sk1.Env(tmp_path, monkeypatch)
    result = skill_writer.write(env.home, sk1.NAME, sk1.draft(), case=None, by="human", no_push=True)
    assert result.ok, result
    fake_review(monkeypatch)
    return env


@pytest.fixture
def env(tmp_path, monkeypatch, request):
    if getattr(request, "param", "git-bash") == "no-git-bash":
        _hide_git_bash(tmp_path, monkeypatch)
    return _make_env(tmp_path, monkeypatch)


def main(capsys, *argv):
    capsys.readouterr()
    code = cli.main(["skill", "script", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def draft(env, capsys, tmp_path, name, data: bytes) -> str:
    source = tmp_path / (name + ".src")
    source.write_bytes(data)
    code, out, err = main(capsys, "draft", sk1.NAME, "--file", str(source), "--name", name,
                          "--usage", USAGE, "--note", "repeatable count")
    assert code == 0, err
    return json.loads(out)["id"]


def activate(env, capsys, tmp_path, name, data: bytes) -> dict:
    code, out, err = main(capsys, "review", draft(env, capsys, tmp_path, name, data), "--note", "review now")
    assert code == 0, err
    row = json.loads(out)
    assert row["state"] == "active", row
    return row


def rel(env, name) -> str:
    return (env.skill_dir() / "scripts" / name).relative_to(env.root).as_posix()


def tree_digest(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


@windows
@pytest.mark.parametrize("env", ["git-bash", "no-git-bash"], indirect=True)
def test_windows_lifecycle_python_and_bash(env, capsys, tmp_path, request):
    with_bash = request.node.callspec.params["env"] == "git-bash"
    data = tmp_path / "input.txt"
    data.write_bytes(b"one\ntwo\nthree\n")
    python = activate(env, capsys, tmp_path, "argv-py", ARGV_PY.encode())

    # The Bash script's first activation is held (a dirty SKILL.md); the
    # explicit activate verb then applies the existing approval.
    md = env.skill_md()
    clean = md.read_bytes()
    md.write_bytes(clean + b"\nlocal edit\n")
    code, out, err = main(capsys, "review", draft(env, capsys, tmp_path, "argv-sh", ARGV_SH.encode()), "--note", "review")
    held = json.loads(out)
    assert code == 0 and held["state"] == "approved" and "dirty" in held["activation_error"], (out, err)
    md.write_bytes(clean)
    code, out, err = main(capsys, "activate", held["id"])
    bash = json.loads(out)
    assert code == 0 and bash["state"] == "active", (out, err)

    # Activation says what would run each script on this machine.
    assert python["interpreter"]["available"] and python["interpreter"]["program"] == sys.executable
    assert "managed copy" in python["interpreter"]["copy"] and python["script_sha256"] in python["interpreter"]["copy"]
    assert bash["interpreter"]["available"] is with_bash
    if with_bash:
        program = bash["interpreter"]["program"]
        assert Path(program).name.lower() == "bash.exe" and "system32" not in program.lower()
    else:
        assert UNAVAILABLE in bash["interpreter"]["detail"]

    # The copy is an ordinary file, not a link; no mode check fires; the host
    # commit records the script at 100755, the mode Linux commits.
    for name, row in (("argv-py", python), ("argv-sh", bash)):
        copy = env.skill_dir() / "scripts" / name
        assert not links.is_any_link(copy)
        assert git(env.root, "ls-files", "-s", "--", rel(env, name)).stdout.startswith("100755 ")
        assert git(env.root, "ls-tree", "HEAD", "--", rel(env, name)).stdout.startswith("100755 ")
        assert git(env.root, "status", "--porcelain", "--", rel(env, name)).stdout == ""
    assert python["host_commit"] != bash["host_commit"] == git(env.root, "rev-parse", "HEAD").stdout.strip()
    assert scripts.inspect(env.home) == []

    code, out, err = main(capsys, "list")
    assert code == 0, err
    listed = {r["name"]: r for r in json.loads(out)}
    assert listed["argv-py"]["interpreter"]["copy_check"] == "verified"
    assert listed["argv-sh"]["interpreter"]["available"] is with_bash
    assert (UNAVAILABLE in listed["argv-sh"]["interpreter"].get("detail", "")) is not with_bash
    code, out, err = main(capsys, "show", bash["id"])
    assert code == 0, err
    shown = json.loads(out)
    assert shown["interpreter"]["available"] is with_bash and shown["script"] == ARGV_SH
    assert (UNAVAILABLE in shown["interpreter"].get("detail", "")) is not with_bash

    code, out, err = main(capsys, "run", sk1.NAME + "/argv-py", "--", *ARGS)
    assert (code, json.loads(out), err) == (3, ARGS, "")
    code, out, err = main(capsys, "run", sk1.NAME + "/argv-sh", "--", *ARGS)
    if with_bash:
        assert (code, out, err) == (1, "".join(f"[{a}]" for a in ARGS), "")
    else:
        assert code == 1 and out == "" and UNAVAILABLE in err

    for row in (python, bash):
        code, out, err = main(capsys, "deactivate", row["id"], "--note", "done")
        assert code == 0 and "deactivated" in out, err
    assert not (env.skill_dir() / "scripts" / "argv-py").exists()
    assert not (env.skill_dir() / "scripts" / "argv-sh").exists()
    code, out, err = main(capsys, "run", sk1.NAME + "/argv-py")
    assert code == 1 and "no active script" in err


@windows
def test_windows_runs_a_private_snapshot_of_the_verified_bytes(env, capsys, tmp_path, monkeypatch):
    from self_learn.primitives import _fsops_windows
    row = activate(env, capsys, tmp_path, "where-py", ARGV0_PY.encode())
    installed = env.skill_dir() / "scripts" / "where-py"
    runs = scripts.names.runtime_root(env.home) / "script-runs"
    seen = []
    real = procs.run_bounded

    def swap_then_launch(command, **kwargs):
        if command[0] != sys.executable:  # Git calls share the interface
            return real(command, **kwargs)
        # A writer replaces the installed copy after verification: the child
        # must still run the verified bytes.
        installed.write_bytes(PY.encode() + b"print('TAMPERED')\n")
        snapshot = Path(command[-1])
        private = _fsops_windows._existing_private_parent(snapshot.parent) is None
        seen.append((snapshot, snapshot.read_bytes(), private))
        return real(command, **kwargs)

    monkeypatch.setattr(procs, "run_bounded", swap_then_launch)
    code, out, err = main(capsys, "run", sk1.NAME + "/where-py")
    assert code == 0 and err == "", (code, out, err)
    snapshot, data, private = seen[0]
    assert (snapshot.parent.parent, snapshot.name, data, private) == (runs, "where-py", ARGV0_PY.encode(), True)
    assert "TAMPERED" not in out and Path(out.strip()) == snapshot and not snapshot.parent.exists()

    # The folder is removed when the launch fails, too.
    def fail(command, **kwargs):
        if command[0] != sys.executable:
            return real(command, **kwargs)
        seen.append((Path(command[-1]), b"", True))
        raise OSError(5, "launch refused")

    installed.write_bytes(ARGV0_PY.encode())
    monkeypatch.setattr(procs, "run_bounded", fail)
    code, out, err = main(capsys, "run", sk1.NAME + "/where-py")
    assert code == 1 and "launch refused" in err and not seen[-1][0].parent.exists()
    assert row["state"] == "active"


@windows
def test_windows_interpreter_settings_are_not_inherited(env, capsys, tmp_path, monkeypatch):
    activate(env, capsys, tmp_path, "argv-py", ARGV_PY.encode())
    activate(env, capsys, tmp_path, "argv-sh", ARGV_SH.encode())
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text("print('SITE-RAN')\n")
    startup = tmp_path / "startup.py"
    startup.write_text("print('STARTUP-RAN')\n")
    profile = tmp_path / "bashenv"
    profile.write_text("echo BASHENV-RAN\n")
    for key, value in (("PYTHONPATH", site), ("PYTHONSTARTUP", startup), ("PYTHONINSPECT", "1"),
                       ("BASH_ENV", profile), ("ENV", profile)):
        monkeypatch.setenv(key, str(value))
    code, out, err = main(capsys, "run", sk1.NAME + "/argv-py", "--", "x")
    assert (code, json.loads(out), err) == (3, ["x"], "")
    code, out, err = main(capsys, "run", sk1.NAME + "/argv-sh", "--", "x")
    assert (code, out, err) == (1, "[x][][][][][]", "")


@windows
def test_windows_stdin_only_on_request(env, capsys, tmp_path, monkeypatch):
    import io
    activate(env, capsys, tmp_path, "upper-py", (PY + "import sys\nprint(sys.stdin.read().upper())\n").encode())
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"piped words")))
    code, out, err = main(capsys, "run", "--stdin", sk1.NAME + "/upper-py")
    assert (code, out.strip(), err) == (0, "PIPED WORDS", "")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"never read")))
    code, out, err = main(capsys, "run", sk1.NAME + "/upper-py")
    assert (code, out.strip(), err) == (0, "", "")


@windows
def test_windows_changed_copy_is_refused(env, capsys, tmp_path):
    activate(env, capsys, tmp_path, "count-py", COUNT_PY.encode())
    copy = env.skill_dir() / "scripts" / "count-py"
    copy.write_bytes(PY.encode() + b"print('TAMPERED')\n")
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert code == 1 and "TAMPERED" not in out and "script bytes changed" in err
    code, out, err = main(capsys, "list")
    assert json.loads(out)[0]["interpreter"]["copy_check"] == "script bytes changed"


@windows
def test_windows_restored_index_cannot_revive_a_deactivation(env, capsys, tmp_path):
    row = activate(env, capsys, tmp_path, "count-py", COUNT_PY.encode())
    index = env.home / scripts.INDEX
    copy = env.skill_dir() / "scripts" / "count-py"
    saved_index, saved_copy = index.read_bytes(), copy.read_bytes()

    # A pending activation in the working index is refused.
    working = json.loads(saved_index)
    working["scripts"][0]["activation_pending"] = True
    index.write_text(json.dumps(working, indent=2) + "\n")
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert code == 1 and "not the ledger's committed state" in err
    index.write_bytes(saved_index)
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert (code, out.strip()) == (0, "1"), err

    code, out, err = main(capsys, "deactivate", row["id"], "--note", "retired")
    assert code == 0, err
    index.write_bytes(saved_index)
    copy.parent.mkdir(exist_ok=True)
    copy.write_bytes(saved_copy)
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert code == 1 and out == "" and "not the ledger's committed state" in err


@windows
def test_windows_junction_in_place_of_scripts_folder_is_refused(env, capsys, tmp_path):
    activate(env, capsys, tmp_path, "count-py", COUNT_PY.encode())
    folder = env.skill_dir() / "scripts"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "count-py").write_bytes(COUNT_PY.encode())
    (folder / "count-py").unlink()
    folder.rmdir()
    links.create(folder, elsewhere, directory=True)
    # Path.is_symlink() is False for a junction; the link check must see it.
    assert not folder.is_symlink() and links.is_any_link(folder)
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert code == 1 and out == "" and "refuses symlink paths" in err


@windows
@pytest.mark.parametrize("foreign", ["same-bytes", "changed-bytes"])
def test_windows_redirect_above_the_skill_folder(env, capsys, tmp_path, foreign):
    """A junction at plugins/<skill>/skills: list, run, doctor and the nightly
    check all see it; nothing outside the skills tree is opened for writing,
    moved or rewritten, and the junction is left in place."""
    activate(env, capsys, tmp_path, "count-py", COUNT_PY.encode())
    skills = env.plugin_dir() / "skills"
    outside = tmp_path / "outside"
    shutil.copytree(skills, outside)
    (outside / "sentinel.txt").write_text("must stay")
    if foreign == "changed-bytes":
        (outside / sk1.NAME / "scripts" / "count-py").write_bytes(PY.encode() + b"print('FOREIGN')\n")
    shutil.rmtree(skills)
    links.create(skills, outside, directory=True)
    before = tree_digest(outside)

    code, out, err = main(capsys, "list")
    assert code == 0 and "redirected entry" in json.loads(out)[0]["interpreter"]["copy_check"], (out, err)
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert code == 1 and out == "" and "symlink" in err
    assert any("redirected entry" in note for note in scripts.inspect(env.home))
    notices = scripts.audit(env.home)
    assert any("left in place" in n for n in notices), notices
    assert scripts.rows(env.home)[0]["state"] == "drafted"
    assert links.is_any_link(skills) and tree_digest(outside) == before


@windows
def test_windows_cross_volume_quarantine_moves_the_entry_never_its_contents(tmp_path, monkeypatch, capsys):
    """A junction at the scripts folder, with the cache on another volume: the
    cache quarantine cannot rename it and must not copy through it; recovery
    then moves the entry itself (same volume)."""
    other = Path(os.environ.get("RUNNER_TEMP", ""))
    if not other.drive or other.drive.lower() == tmp_path.drive.lower():
        pytest.fail(f"needs a second volume: RUNNER_TEMP={other!s} tmp={tmp_path!s}")
    work = other / ("w5-" + uuid.uuid4().hex[:8])
    work.mkdir()
    try:
        env = _make_env(work, monkeypatch)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache-elsewhere"))
        activate(env, capsys, work, "count-py", COUNT_PY.encode())
        folder = env.skill_dir() / "scripts"
        outside = work / "outside"
        outside.mkdir()
        (outside / "count-py").write_bytes(COUNT_PY.encode())
        (outside / "sentinel.txt").write_text("must stay")
        (folder / "count-py").unlink()
        folder.rmdir()
        links.create(folder, outside, directory=True)
        before = tree_digest(outside)
        notices = scripts.audit(env.home)
        assert any("cannot move redirected entry" in n for n in notices), notices
        assert any("preserved at" in n for n in notices), notices
        assert not os.path.lexists(folder) and tree_digest(outside) == before
        copied = [p for p in (tmp_path / "cache-elsewhere").rglob("sentinel.txt")]
        assert copied == []
        assert scripts.rows(env.home)[0]["state"] == "drafted"
    finally:
        shutil.rmtree(work, ignore_errors=True)


@windows
def test_windows_crlf_digest_contract(env, capsys, tmp_path):
    """The digest covers the exact UTF-8 bytes submitted, carriage returns
    included: they are held, reviewed, installed, committed and run unchanged,
    and the LF spelling of the same script is a different version."""
    git(env.root, "config", "core.autocrlf", "false")
    crlf = COUNT_PY.replace("\n", "\r\n").encode()
    row = activate(env, capsys, tmp_path, "count-py", crlf)
    assert row["script_sha256"] == hashlib.sha256(crlf).hexdigest()
    assert scripts._held(env.home, row).read_bytes() == crlf
    copy = env.skill_dir() / "scripts" / "count-py"
    assert copy.read_bytes() == crlf
    blob = subprocess.run(["git", "-C", str(env.root), "cat-file", "blob", "HEAD:" + rel(env, "count-py")],
                          capture_output=True, timeout=60).stdout
    assert blob == crlf
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py", "--", "x")
    assert (code, out.strip(), err) == (0, "2", "")
    assert scripts.version(COUNT_PY, USAGE) != row["version"]
    copy.write_bytes(COUNT_PY.encode())
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert code == 1 and "script bytes changed" in err


@windows
def test_windows_converted_line_endings_are_refused(env, capsys, tmp_path):
    git(env.root, "config", "core.autocrlf", "true")
    head = git(env.root, "rev-parse", "HEAD").stdout
    ident = draft(env, capsys, tmp_path, "count-py", COUNT_PY.replace("\n", "\r\n").encode())
    code, out, err = main(capsys, "review", ident, "--note", "review")
    row = json.loads(out)
    assert code == 0 and row["state"] == "approved" and "line endings" in row["activation_error"], (out, err)
    assert not (env.skill_dir() / "scripts" / "count-py").exists()
    assert git(env.root, "rev-parse", "HEAD").stdout == head


@windows
def test_windows_show_reads_exact_bytes_from_a_checked_path(env, capsys, tmp_path):
    text = (PY + "import sys\nprint('café', len(sys.argv))\n").replace("\n", "\r\n")
    ident = draft(env, capsys, tmp_path, "cafe-py", text.encode())
    code, out, err = main(capsys, "show", ident)
    assert code == 0 and json.loads(out)["script"] == text, err
    row = scripts.get(env.home, ident)
    version = scripts._held(env.home, row).parent
    moved = tmp_path / "held-elsewhere"
    shutil.copytree(version, moved)
    shutil.rmtree(version)
    links.create(version, moved, directory=True)
    code, out, err = main(capsys, "show", ident)
    assert code == 1 and "refuses symlink paths" in err


@windows
def test_windows_list_survives_an_unavailable_host(env, capsys, tmp_path):
    activate(env, capsys, tmp_path, "count-py", COUNT_PY.encode())
    hosts = env.home / "hosts.yaml"
    hosts.write_text(hosts.read_text().replace(str(env.root), str(tmp_path / "gone")))
    code, out, err = main(capsys, "list")
    assert code == 0 and json.loads(out)[0]["interpreter"]["copy_check"].startswith("unreadable"), (out, err)
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert code == 1 and out == "" and err.startswith("self-learn skill script: ")


@windows
def test_windows_device_names_and_timeouts_are_refused(env, capsys, tmp_path):
    source = tmp_path / "count.src"
    source.write_bytes(COUNT_PY.encode())
    code, out, err = main(capsys, "draft", sk1.NAME, "--file", str(source), "--name", "con",
                          "--usage", USAGE, "--note", "device")
    assert code == 1 and "reserved Windows device name" in err
    assert not (env.home / "skill-scripts").exists()
    code, out, err = main(capsys, "run", sk1.NAME + "/nul")
    assert code == 1 and "reserved Windows device name" in err
    for value in ("601", "0", "-1", "inf", "nan"):
        code, out, err = main(capsys, "run", "--timeout", value, sk1.NAME + "/count-py")
        assert code == 1 and "--timeout must be" in err, value
    code, out, err = main(capsys, "run", "--help")
    assert code == 0 and "run [--timeout SECONDS] [--stdin] SKILL/NAME [-- ARGS ...]" in out


@windows
def test_windows_production_defaults_refuse_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home"))
    assert all(not capabilities.AVAILABLE[c] for c in ("ledger", "canon"))
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert (code, out, err) == (1, "", "self-learn skill: unavailable in Windows capture mode\n")


@windows
def test_windows_git_bash_discovery(tmp_path, monkeypatch):
    def layout(top: Path, git_name: str, bash: str | None) -> Path:
        (top / git_name).parent.mkdir(parents=True, exist_ok=True)
        (top / git_name).write_bytes(b"")
        if bash:
            (top / bash).parent.mkdir(parents=True, exist_ok=True)
            (top / bash).write_bytes(b"")
        return (top / git_name).parent

    def found(*entries: Path) -> Path | None:
        monkeypatch.setenv("PATH", os.pathsep.join(map(str, entries)))
        return scripts._git_bash()

    for top, git_name, bash in [("Git", "cmd/git.exe", "bin/bash.exe"), ("Bin", "bin/git.exe", "bin/bash.exe"),
                                ("Mingw", "mingw64/bin/git.exe", "usr/bin/bash.exe")]:
        assert found(layout(tmp_path / top, git_name, bash)) == Path(os.path.realpath(tmp_path / top / bash)), top
    assert found(layout(tmp_path / "MinGit", "cmd/git.exe", None)) is None
    # A .cmd shim first on PATH is no Git, even with a real one later.
    assert found(layout(tmp_path / "Shim", "cmd/git.cmd", "bin/bash.exe"), tmp_path / "Git" / "cmd") is None
    # git.exe's real path names the installation.
    (tmp_path / "Link" / "cmd").mkdir(parents=True)
    os.symlink(tmp_path / "Git" / "cmd" / "git.exe", tmp_path / "Link" / "cmd" / "git.exe")
    assert found(tmp_path / "Link" / "cmd") == Path(os.path.realpath(tmp_path / "Git" / "bin" / "bash.exe"))
    # bash.exe must resolve inside the installation.
    outside = tmp_path / "Outside"
    outside.mkdir()
    (outside / "bash.exe").write_bytes(b"")
    layout(tmp_path / "Jx", "cmd/git.exe", None)
    links.create(tmp_path / "Jx" / "bin", outside, directory=True)
    assert found(tmp_path / "Jx" / "cmd") is None
    # The real system directories are refused by identity, not spelling.
    system = tmp_path / "System"
    monkeypatch.setattr(scripts, "_system_dirs", lambda: [os.path.realpath(system)])
    layout(system / "Git", "cmd/git.exe", "bin/bash.exe")
    links.create(tmp_path / "Alias", system, directory=True)
    assert found(tmp_path / "Alias" / "Git" / "cmd") is None
    monkeypatch.undo()
    # The current folder is never searched, even when it holds a Git layout.
    here = layout(tmp_path / "Here", "cmd/git.exe", "bin/bash.exe")
    monkeypatch.chdir(here)
    assert found(Path("."), here, tmp_path / "MinGit" / "cmd") is None


@posix
def test_linux_surface_has_no_windows_launcher(tmp_path, monkeypatch, capsys):
    assert cli.main(["skill", "script", "run", "s/x"]) == 2
    assert "invalid choice: 'run'" in capsys.readouterr().err
    with pytest.raises(ValueError, match="Windows launcher"):
        scripts.run(tmp_path, "s/x", [])


@posix
def test_linux_checkout_mode_decides_the_mode_check(tmp_path, monkeypatch):
    """What Linux's check sees for a tree: a 100755 script (what Windows now
    commits) checks out executable and passes; a 100644 one (what a plain
    Windows commit would record) checks out 0644 and is reported."""
    env = sk1.Env(tmp_path, monkeypatch)
    assert skill_writer.write(env.home, sk1.NAME, sk1.draft(), case=None, by="human", no_push=True).ok
    fake_review(monkeypatch)
    row = scripts.review(env.home, scripts.draft(env.home, sk1.NAME, name="count-py", text=COUNT_PY,
                                                 usage=USAGE, note="n")["id"], note="r")
    assert row["state"] == "active"
    path, name = env.skill_dir() / "scripts" / "count-py", rel(env, "count-py")
    assert git(env.root, "ls-tree", "HEAD", "--", name).stdout.startswith("100755 ")
    path.unlink()
    git(env.root, "checkout", "HEAD", "--", name)
    assert stat.S_IMODE(path.stat().st_mode) == 0o755 and scripts.inspect(env.home) == []
    git(env.root, "update-index", "--chmod=-x", "--", name)
    git(env.root, "commit", "-q", "-m", "as a plain Windows commit would record it")
    assert git(env.root, "ls-tree", "HEAD", "--", name).stdout.startswith("100644 ")
    path.unlink()
    git(env.root, "checkout", "HEAD", "--", name)
    assert any("script mode changed" in note for note in scripts.inspect(env.home))
