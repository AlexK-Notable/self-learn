"""The web UI as an installed wheel (Windows port, 8K).

A wheel has no repository around it, so the pages, the static files and the
pane's doctrine sources ride inside it as package data (``pyproject.toml``'s
force-include, under ``self_learn_ui/_data/``; the CLI wheel carries the
skill's references under ``self_learn/_data/``). The lookups read the
checkout's own folders first and use the packaged copies only when those
are absent.

These tests build both wheels with ``uv build --wheel``, install them into a
fresh virtual environment in a scratch folder (the third-party wheels pinned
by ``uv export`` from this package's lockfile, so the versions are the
lockfile's), start ``self-learn-ui serve`` from that environment against a
scratch ledger on an ephemeral loopback port, and fetch the home page and two
static files. A second test plants a checkout layout around a copy of the
installed packages and shows the checkout's folders win. The third pins the
live checkout's own resolution. They run on Linux and on GitHub's Windows
runner (the ``windows-canary`` job's "Windows UI package data" step).
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[1]
PLUGIN_DIR = UI_DIR.parent
CLI_DIR = PLUGIN_DIR / "cli"
REFS_DIR = PLUGIN_DIR / "skills" / "self-learn" / "references"

_STARTUP_TIMEOUT_S = 60.0
_STEP_TIMEOUT_S = 600

#: What the installed copy must resolve each lookup to, and the repository
#: folder whose files it must carry byte for byte.
_LOOKUPS = {
    "templates": UI_DIR / "templates",
    "static": UI_DIR / "static",
    "ui_references": REFS_DIR,
    "cli_references": REFS_DIR,
}

#: Prints, as JSON, where each lookup resolves and which files were imported.
_PROBE = r"""
import json, sys
for entry in reversed(sys.argv[1:]):
    sys.path.insert(0, entry)
import self_learn, self_learn_ui
from self_learn import lesson_writing, worker
from self_learn_ui import app, doctrine
print(json.dumps({
    "self_learn": self_learn.__file__,
    "self_learn_ui": self_learn_ui.__file__,
    "templates": str(app.TEMPLATES_DIR),
    "static": str(app.STATIC_DIR),
    "ui_references": str(doctrine.plugin_references_dir()),
    "cli_references": str(worker.package_skill_refs()),
    "lesson_writing": str(lesson_writing.path()),
    "lesson_text": lesson_writing.text(),
    "charter_text": doctrine.pane_charter_path().read_text(encoding="utf-8"),
}))
"""


def _uv() -> str:
    uv = shutil.which("uv")
    assert uv, "uv is not on PATH: the packaging tests build and install with it"
    return uv


def _clean_env() -> dict[str, str]:
    """The test's environment without anything that would point uv or Python
    back at a project or the checkout."""
    env = dict(os.environ)
    for key in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT", "UV_PYTHON"):
        env.pop(key, None)
    return env


def _run(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        argv,
        cwd=cwd,
        env=env if env is not None else _clean_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_STEP_TIMEOUT_S,
    )
    assert proc.returncode == 0, (
        f"{argv!r} exited {proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    if Path(argv[0]).stem == "uv":
        # uv says on stderr what it resolved, downloaded and installed: kept
        # in the captured output (``-rA``) as the record of what the build
        # and the install fetched.
        print(f"$ uv {' '.join(argv[1:3])}\n{proc.stderr.strip()}")
    return proc.stdout


def _bin_dir(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def _exe(venv: Path, name: str) -> Path:
    path = _bin_dir(venv) / (f"{name}.exe" if os.name == "nt" else name)
    assert path.is_file(), f"{path} is missing from the fresh environment"
    return path


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.relative_to(root).parts
    }


def _probe(python: Path, cwd: Path, *path_entries: Path) -> dict[str, str]:
    out = _run([str(python), "-I", "-c", _PROBE, *map(str, path_entries)], cwd=cwd)
    return json.loads(out)


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Both wheels built from this checkout and installed, with the
    lockfile's third-party wheels, into a fresh environment in a scratch
    folder that no checkout path reaches."""
    uv = _uv()
    root = tmp_path_factory.mktemp("packaging")
    dist = root / "dist"
    for project in (CLI_DIR, UI_DIR):
        _run([uv, "build", "--wheel", "--project", str(project), "--out-dir", str(dist)], cwd=root)
    wheels = {path.name.split("-")[0]: path for path in dist.glob("*.whl")}
    assert set(wheels) == {"self_learn_cli", "self_learn_ui"}, sorted(dist.iterdir())

    requirements = root / "requirements.txt"
    _run(
        [
            uv, "export", "--project", str(UI_DIR), "--frozen", "--no-dev",
            "--no-emit-project", "--no-emit-package", "self-learn-cli",
            "--no-header", "--output-file", str(requirements),
        ],
        cwd=root,
    )
    venv = root / "venv"
    _run([uv, "venv", str(venv), "--python", sys.executable], cwd=root)
    python = _bin_dir(venv) / ("python.exe" if os.name == "nt" else "python")
    _run([uv, "pip", "install", "--python", str(python), "-r", str(requirements)], cwd=root)
    _run(
        [
            uv, "pip", "install", "--python", str(python), "--no-deps",
            str(wheels["self_learn_cli"]), str(wheels["self_learn_ui"]),
        ],
        cwd=root,
    )
    return {"root": root, "venv": venv, "python": python}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, path: str, headers: dict[str, str] | None = None) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("GET", path, headers=headers or {})
    response = conn.getresponse()
    response.body = response.read()  # type: ignore[attr-defined]
    conn.close()
    return response


def _scratch_ledger(home: Path) -> None:
    """The bare-ledger layout the UI suite uses (``support.bare_ledger``),
    built here so this file needs nothing beyond pytest's own fixtures."""
    home.mkdir(parents=True)
    for argv in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
    ):
        _run(argv, cwd=home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()


def test_wheel_install_serves_pages_and_files_from_package_data(installed: dict[str, Path]) -> None:
    root, venv, python = installed["root"], installed["venv"], installed["python"]
    work = root / "work"
    work.mkdir(exist_ok=True)

    # The installed copy imports from the fresh environment, and every lookup
    # lands on its package data, which carries the repository's files byte
    # for byte (no file missing, none extra).
    found = _probe(python, work)
    venv_root = venv.resolve()
    for module in ("self_learn", "self_learn_ui"):
        assert Path(found[module]).resolve().is_relative_to(venv_root), found[module]
    expected_parts = {
        "templates": ("self_learn_ui", "_data", "templates"),
        "static": ("self_learn_ui", "_data", "static"),
        "ui_references": ("self_learn_ui", "_data", "references"),
        "cli_references": ("self_learn", "_data", "references"),
    }
    for key, repo_dir in _LOOKUPS.items():
        resolved = Path(found[key]).resolve()
        assert resolved.is_relative_to(venv_root), (key, resolved)
        assert resolved.parts[-3:] == expected_parts[key], (key, resolved)
        assert _tree(resolved) == _tree(repo_dir), key
    assert Path(found["lesson_writing"]).resolve() == Path(found["cli_references"]).resolve() / "lesson-writing.md"
    assert found["lesson_text"] == (REFS_DIR / "lesson-writing.md").read_bytes().decode("utf-8")

    # Start the installed console script against a scratch ledger and fetch
    # the home page and two static files.
    home = root / "ledger"
    if not home.exists():
        _scratch_ledger(home)
    port = _free_port()
    env = _clean_env()
    env.update(
        SELF_LEARN_HOME=str(home),
        XDG_RUNTIME_DIR=str(root / "runtime"),
        XDG_CACHE_HOME=str(root / "cache"),
        SELF_LEARN_UI_PORT=str(port),
        SELF_LEARN_UI_CLI_BIN=str(_exe(venv, "self-learn")),
        SELF_LEARN_SDK_CLI_PATH=str(root / "no-claude-here"),
        PATH=os.pathsep.join([str(_bin_dir(venv)), env.get("PATH", "")]),
    )
    (root / "runtime").mkdir(exist_ok=True)
    (root / "cache").mkdir(exist_ok=True)
    ui = _exe(venv, "self-learn-ui")
    token_path = Path(json.loads(_run([str(ui), "paths", "--json"], cwd=work, env=env))["token_path"])
    token_path.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [str(ui), "serve"], cwd=work, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    try:
        deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        while True:
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=5)
                pytest.fail(f"serve exited early (rc={proc.returncode})\n{out}\n{err}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    pass
                if token_path.is_file() and token_path.stat().st_size > 0:
                    break
            except OSError:
                pass
            assert time.monotonic() < deadline, "serve never opened its port and wrote its token"
            time.sleep(0.1)
        token = token_path.read_text(encoding="utf-8").strip()

        minted = _get(port, f"/?token={token}")
        assert minted.status == 303, (minted.status, minted.body)  # type: ignore[attr-defined]
        cookie = minted.getheader("set-cookie", "").split(";", 1)[0]
        assert cookie.startswith("slu_token="), cookie
        authed = {"Cookie": cookie}

        page = _get(port, "/", authed)
        body = page.body.decode("utf-8")  # type: ignore[attr-defined]
        assert page.status == 200, (page.status, body[:2000])
        assert "text/html" in page.getheader("content-type", "")
        # base.html's own stylesheet and script links: the page came from the
        # packaged templates, not an error page.
        assert '/static/style.css' in body and '/static/app.js' in body, body[:2000]

        for name in ("style.css", "app.js"):
            served = _get(port, f"/static/{name}", authed)
            assert served.status == 200, (name, served.status)
            assert served.body == (UI_DIR / "static" / name).read_bytes(), name  # type: ignore[attr-defined]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_checkout_folders_win_over_package_data(installed: dict[str, Path]) -> None:
    """A checkout layout planted around a copy of the INSTALLED packages
    (which carry ``_data``): every lookup takes the checkout's folder, and
    the text read is the checkout's, not the packaged copy's."""
    located = _run(
        [str(installed["python"]), "-I", "-c", "import self_learn_ui; print(self_learn_ui.__file__)"],
        cwd=installed["root"],
    )
    site = Path(located.strip()).resolve().parents[1]
    layout = installed["root"] / "checkout" / "plugins" / "self-learn"
    if layout.exists():
        shutil.rmtree(layout)
    ui_src, cli_src = layout / "ui" / "src", layout / "cli" / "src"
    shutil.copytree(site / "self_learn_ui", ui_src / "self_learn_ui")
    shutil.copytree(site / "self_learn", cli_src / "self_learn")
    assert (ui_src / "self_learn_ui" / "_data" / "templates").is_dir()
    assert (cli_src / "self_learn" / "_data" / "references").is_dir()
    planted = {
        "templates": layout / "ui" / "templates",
        "static": layout / "ui" / "static",
        "ui_references": layout / "skills" / "self-learn" / "references",
        "cli_references": layout / "skills" / "self-learn" / "references",
    }
    shutil.copytree(UI_DIR / "templates", planted["templates"])
    shutil.copytree(UI_DIR / "static", planted["static"])
    shutil.copytree(REFS_DIR, planted["ui_references"])
    marker = "\nPLANTED CHECKOUT COPY\n"
    for name in ("lesson-writing.md", "pane-charter.md"):
        with (planted["ui_references"] / name).open("a", encoding="utf-8", newline="") as fh:
            fh.write(marker)

    work = installed["root"] / "work-checkout"
    work.mkdir(exist_ok=True)
    found = _probe(installed["python"], work, ui_src, cli_src)
    assert Path(found["self_learn_ui"]).resolve() == (ui_src / "self_learn_ui" / "__init__.py").resolve()
    assert Path(found["self_learn"]).resolve() == (cli_src / "self_learn" / "__init__.py").resolve()
    for key, folder in planted.items():
        assert Path(found[key]).resolve() == folder.resolve(), (key, found[key])
    assert Path(found["lesson_writing"]).resolve() == (planted["ui_references"] / "lesson-writing.md").resolve()
    assert found["lesson_text"].endswith(marker)
    assert found["charter_text"].endswith(marker)


def test_live_checkout_resolves_to_its_own_folders() -> None:
    """This checkout's own import (the live install's case): exactly the
    paths the lookups always returned."""
    from self_learn import lesson_writing, worker
    from self_learn_ui import app, doctrine

    assert app.TEMPLATES_DIR == UI_DIR / "templates"
    assert app.STATIC_DIR == UI_DIR / "static"
    assert doctrine.plugin_references_dir() == REFS_DIR
    assert worker.package_skill_refs() == REFS_DIR
    assert lesson_writing.path() == REFS_DIR / "lesson-writing.md"
