"""Skill scripts on Windows: a verified managed copy and a declared interpreter.

Windows has no mode bits and no kernel shebang. An active script there is the
managed copy activation already writes (exclusive create, never a link); its
SHA-256 over the exact reviewed bytes and its approval are verified before every
``skill script run``, which launches Python scripts with ``sys.executable`` and
Bash scripts with Git for Windows' bash.exe when the git.exe on PATH belongs to
an installation that has one. No real model: the review session is faked at the
SDK backend, as in ``test_skill_scripts.py``.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import test_skill_write as sk1
from self_learn import cli, skill_scripts as scripts, skill_writer
from self_learn.invocation_sdk import backend as sdk
from self_learn.primitives import capabilities, links, procs

windows = pytest.mark.skipif(os.name != "nt", reason="Windows skill script contract")
posix = pytest.mark.skipif(os.name == "nt", reason="Linux skill script surface")

PY = "#!/usr/bin/env python3\n"
SH = "#!/usr/bin/env bash\nset -o noclobber\n"
COUNT_PY = PY + "import sys\nprint(len(sys.argv))\n"
COUNT_SH = SH + 'wc -l "$1"\n'
USAGE = "Run with a local input path to count."


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


def _git_top(git: Path) -> Path:
    folder = git.parent
    if folder.name.lower() == "bin" and folder.parent.name.lower() == "mingw64":
        return folder.parent.parent
    return folder.parent


def _hide_git_bash(tmp_path: Path, monkeypatch) -> None:
    """A Git with no Bash, the shape of MinGit: hard links to the runner's real
    ``mingw64`` binaries in a scratch folder first on PATH, and every PATH entry
    inside the real Git installation removed."""
    real = next(Path(e) / "git.exe" for e in os.environ["PATH"].split(os.pathsep)
                if e and (Path(e) / "git.exe").is_file())
    top = _git_top(real)
    assert (top / "bin" / "bash.exe").is_file() or (top / "usr" / "bin" / "bash.exe").is_file()
    prefix, fake = top / "mingw64", tmp_path / "MinGit" / "mingw64"
    for part in ("bin", "libexec", "share/git-core"):
        for folder, _dirs, files in os.walk(prefix / part):
            into = fake / Path(folder).relative_to(prefix)
            into.mkdir(parents=True, exist_ok=True)
            for name in files:
                os.link(Path(folder) / name, into / name)
    inside = os.path.normcase(str(top)) + os.sep
    kept = [e for e in os.environ["PATH"].split(os.pathsep)
            if e and not os.path.normcase(os.path.abspath(e) + os.sep).startswith(inside)]
    monkeypatch.setenv("PATH", os.pathsep.join([str(fake / "bin"), *kept]))
    assert scripts._git_bash() is None
    assert (fake / "bin" / "git.exe").is_file(), (real, sorted(p.name for p in (fake / "bin").iterdir())[:40])
    probe = procs.run_bounded(["git", "--version"], timeout=60)
    assert probe.returncode == 0, (real, probe)
    bare = subprocess.run(["git", "--version"], capture_output=True, timeout=60)
    assert bare.returncode == 0, (real, bare)


@pytest.fixture
def env(tmp_path, monkeypatch, request):
    if getattr(request, "param", "git-bash") == "no-git-bash":
        _hide_git_bash(tmp_path, monkeypatch)
    # ``skill`` is refused in the Windows capture profile until an integration
    # stage switches ledger and canon on; these tests open the gate themselves.
    monkeypatch.setitem(capabilities.AVAILABLE, "ledger", True)
    monkeypatch.setitem(capabilities.AVAILABLE, "canon", True)
    env = sk1.Env(tmp_path, monkeypatch)
    result = skill_writer.write(env.home, sk1.NAME, sk1.draft(), case=None, by="human", no_push=True)
    assert result.ok, result
    fake_review(monkeypatch)
    return env


def main(capsys, *argv):
    capsys.readouterr()
    code = cli.main(["skill", "script", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def activate(env, capsys, tmp_path, name, data: bytes) -> dict:
    source = tmp_path / (name + ".src")
    source.write_bytes(data)
    code, out, err = main(capsys, "draft", sk1.NAME, "--file", str(source), "--name", name,
                          "--usage", USAGE, "--note", "repeatable count")
    assert code == 0, err
    code, out, err = main(capsys, "review", json.loads(out)["id"], "--note", "review now")
    assert code == 0, err
    row = json.loads(out)
    assert row["state"] == "active", row
    return row


@windows
@pytest.mark.parametrize("env", ["git-bash", "no-git-bash"], indirect=True)
def test_windows_lifecycle_python_and_bash(env, capsys, tmp_path, request):
    with_bash = request.node.callspec.params["env"] == "git-bash"
    data = tmp_path / "input.txt"
    data.write_bytes(b"one\ntwo\nthree\n")
    python = activate(env, capsys, tmp_path, "count-py", COUNT_PY.encode())
    bash = activate(env, capsys, tmp_path, "count-sh", COUNT_SH.encode())

    # Activation says what would run each script on this machine.
    assert python["interpreter"]["available"] and python["interpreter"]["program"] == sys.executable
    assert "managed copy" in python["interpreter"]["copy"] and python["script_sha256"] in python["interpreter"]["copy"]
    assert bash["interpreter"]["available"] is with_bash
    if with_bash:
        assert Path(bash["interpreter"]["program"]).name.lower() == "bash.exe"
        assert "system32" not in bash["interpreter"]["program"].lower()
    else:
        assert bash["interpreter"]["detail"] == scripts.BASH_UNAVAILABLE

    # The copy is an ordinary file, not a link, and no mode check fires.
    copy = env.skill_dir() / "scripts" / "count-py"
    assert copy.read_bytes() == COUNT_PY.encode() and not links.is_any_link(copy)
    assert scripts.inspect(env.home) == []

    code, out, err = main(capsys, "list")
    assert code == 0, err
    listed = {r["name"]: r for r in json.loads(out)}
    assert listed["count-py"]["interpreter"]["copy_check"] == "verified"
    assert listed["count-sh"]["interpreter"]["available"] is with_bash
    code, out, err = main(capsys, "show", bash["id"])
    assert code == 0, err
    shown = json.loads(out)
    assert shown["interpreter"]["available"] is with_bash and shown["script"] == COUNT_SH

    code, out, err = main(capsys, "run", sk1.NAME + "/count-py", "--", "a", "b")
    assert (code, out.strip(), err) == (0, "3", "")
    code, out, err = main(capsys, "run", sk1.NAME + "/count-sh", "--", data.as_posix())
    if with_bash:
        assert code == 0 and out.split()[0] == "3", (out, err)
    else:
        assert code == 1 and out == "" and scripts.BASH_UNAVAILABLE in err

    for row in (python, bash):
        code, out, err = main(capsys, "deactivate", row["id"], "--note", "done")
        assert code == 0 and "deactivated" in out, err
    assert not copy.exists() and not (env.skill_dir() / "scripts" / "count-sh").exists()
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert code == 1 and "no active script" in err


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
def test_windows_crlf_digest_contract(env, capsys, tmp_path):
    """The digest covers the exact UTF-8 bytes submitted, carriage returns
    included: they are held, reviewed, installed and run unchanged, and the LF
    spelling of the same script is a different version."""
    crlf = COUNT_PY.replace("\n", "\r\n").encode()
    row = activate(env, capsys, tmp_path, "count-py", crlf)
    assert row["script_sha256"] == hashlib.sha256(crlf).hexdigest()
    assert scripts._held(env.home, row).read_bytes() == crlf
    copy = env.skill_dir() / "scripts" / "count-py"
    assert copy.read_bytes() == crlf
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py", "--", "x")
    assert (code, out.strip(), err) == (0, "2", "")
    assert scripts.version(COUNT_PY, USAGE) != row["version"]
    copy.write_bytes(COUNT_PY.encode())
    code, out, err = main(capsys, "run", sk1.NAME + "/count-py")
    assert code == 1 and "script bytes changed" in err


@windows
def test_windows_git_bash_discovery(tmp_path, monkeypatch):
    def layout(top: Path, git: str, bash: str | None) -> Path:
        (top / git).parent.mkdir(parents=True, exist_ok=True)
        (top / git).write_bytes(b"")
        if bash:
            (top / bash).parent.mkdir(parents=True, exist_ok=True)
            (top / bash).write_bytes(b"")
        return (top / git).parent

    cases = [("Git", "cmd/git.exe", "bin/bash.exe", "bin/bash.exe"),
             ("Bin", "bin/git.exe", "bin/bash.exe", "bin/bash.exe"),
             ("Mingw", "mingw64/bin/git.exe", "usr/bin/bash.exe", "usr/bin/bash.exe"),
             ("MinGit", "cmd/git.exe", None, None)]
    for top, git, bash, expected in cases:
        entry = layout(tmp_path / top, git, bash)
        monkeypatch.setenv("PATH", str(entry))
        found = scripts._git_bash()
        assert found == (tmp_path / top / expected if expected else None), (top, found)
    # The current folder is never searched, even when it holds a Git layout.
    here = layout(tmp_path / "Here", "cmd/git.exe", "bin/bash.exe")
    monkeypatch.chdir(here)
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(here), str(tmp_path / "MinGit" / "cmd")]))
    assert scripts._git_bash() is None


@posix
def test_linux_surface_has_no_windows_launcher(tmp_path, monkeypatch, capsys):
    assert cli.main(["skill", "script", "run", "s/x"]) == 2
    assert "invalid choice: 'run'" in capsys.readouterr().err
    with pytest.raises(ValueError, match="Windows launcher"):
        scripts.run(tmp_path, "s/x", [])
