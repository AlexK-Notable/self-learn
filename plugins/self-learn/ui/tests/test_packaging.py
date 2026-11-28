"""The web UI as an installed wheel (Windows port, 8K).

A wheel has no repository around it, so the pages, the static files and the
pane's doctrine sources ride inside it as package data (``hatch_build.py``,
under ``self_learn_ui/_data/``; the CLI wheel carries the skill's references
under ``self_learn/_data/``). Each lookup decides the layout from its own
package's location: the checkout folders on a checkout, the packaged copies
on an installed wheel.

Two tests run in every UI suite run, cheaply: the live checkout resolves to
exactly the paths it always did, and the checkout detection needs its full
marker. The other three build wheels, so they need uv and a prepared package
cache; they run only with ``SELF_LEARN_PACKAGING_TESTS=1`` (the "UI package
data" steps of the Linux and Windows CI jobs) and otherwise skip, saying so.
They build both wheels with ``uv build --wheel``, install them into a fresh
virtual environment in a scratch folder (third-party wheels pinned by
``uv export`` from this package's lockfile), start ``self-learn-ui serve`` from
it against a scratch ledger on an ephemeral loopback port and fetch the home
page and two static files; plant a checkout layout around a copy of the
installed packages; and build an sdist and then a wheel from it.

Every child process gets a hermetic environment: no inherited ``GIT_*``
variable, Git's global and system configuration pinned to scratch files or
empty scratch files, ``HOME`` in the scratch root, and Git discovery stopped above
it.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[1]
PLUGIN_DIR = UI_DIR.parent
CLI_DIR = PLUGIN_DIR / "cli"
REFS_DIR = PLUGIN_DIR / "skills" / "self-learn" / "references"

PACKAGING_ENV = "SELF_LEARN_PACKAGING_TESTS"
needs_packaging = pytest.mark.skipif(
    os.environ.get(PACKAGING_ENV) != "1",
    reason=(
        f"wheel-building packaging test: runs only with {PACKAGING_ENV}=1, because it builds "
        "and installs wheels (uv and a prepared package cache); CI runs it in the "
        "'UI package data' steps"
    ),
)

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


# ------------------------------------------------------------ default suite


def test_live_checkout_resolves_to_its_own_folders() -> None:
    """This checkout's own import (the live install's case): each lookup
    returns exactly what its old expression gave."""
    from self_learn import _package_data as cli_data
    from self_learn import lesson_writing, worker
    from self_learn_ui import _package_data as ui_data
    from self_learn_ui import app, doctrine

    assert ui_data.checkout_project() == UI_DIR
    assert cli_data.checkout_project() == CLI_DIR
    # The expressions the lookups used before package data existed.
    assert app.TEMPLATES_DIR == Path(app.__file__).resolve().parents[2] / "templates"
    assert app.STATIC_DIR == Path(app.__file__).resolve().parents[2] / "static"
    refs = "skills", "self-learn", "references"
    assert doctrine.plugin_references_dir() == Path(doctrine.__file__).resolve().parents[3].joinpath(*refs)
    assert worker.package_skill_refs() == Path(worker.__file__).resolve().parents[3].joinpath(*refs)
    assert lesson_writing.path() == Path(lesson_writing.__file__).resolve().parents[3].joinpath(
        *refs, "lesson-writing.md"
    )
    # And those are this repository's folders.
    assert app.TEMPLATES_DIR == UI_DIR / "templates"
    assert doctrine.plugin_references_dir() == REFS_DIR


def _plant_layout(root: Path, project: str, declared: str) -> Path:
    """``root/plugins/self-learn/<project>/src/pkg/mod.py`` with the
    project's ``pyproject.toml`` and the plugin's ``plugin.json``."""
    plugin = root / "plugins" / "self-learn"
    module = plugin / project / "src" / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    (plugin / project / "pyproject.toml").write_text(
        f'[project]\nname = "{declared}"\nversion = "0"\n', encoding="utf-8"
    )
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    return module


@pytest.mark.parametrize("project, declared", [("cli", "self-learn-cli"), ("ui", "self-learn-ui")])
def test_checkout_detection_needs_the_full_marker(tmp_path: Path, project: str, declared: str) -> None:
    from self_learn._package_data import detect_checkout

    module = _plant_layout(tmp_path / "full", project, declared)
    assert detect_checkout(module, declared) == module.parents[2]

    # Each marker missing on its own: not a checkout.
    no_plugin = _plant_layout(tmp_path / "no-plugin", project, declared)
    (no_plugin.parents[3] / ".claude-plugin" / "plugin.json").unlink()
    assert detect_checkout(no_plugin, declared) is None
    wrong_name = _plant_layout(tmp_path / "wrong-name", project, "someone-else")
    assert detect_checkout(wrong_name, declared) is None
    broken = _plant_layout(tmp_path / "broken-toml", project, declared)
    (broken.parents[2] / "pyproject.toml").write_text("[project\nname=", encoding="utf-8")
    assert detect_checkout(broken, declared) is None

    # An installed package with same-named neighbours where the old
    # arithmetic looked (``<venv>/lib/templates``, ``<venv>/skills/...``,
    # even a pyproject.toml and a plugin.json): its parent is not ``src``.
    venv = tmp_path / "venv"
    installed = venv / "Lib" / "site-packages" / "pkg" / "mod.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="utf-8")
    (venv / "Lib" / "templates").mkdir()
    (venv / "Lib" / "static").write_text("a file, not a folder", encoding="utf-8")
    (venv / "skills" / "self-learn" / "references").mkdir(parents=True)
    (venv / "Lib" / "pyproject.toml").write_text(f'[project]\nname = "{declared}"\n', encoding="utf-8")
    (venv / ".claude-plugin").mkdir()
    (venv / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    assert detect_checkout(installed, declared) is None

    # Too few parents for the layout (a shallow install target): no IndexError.
    for shallow in (Path("/mod.py"), Path("/pkg/mod.py"), Path("/deps/pkg/mod.py")):
        assert detect_checkout(shallow, declared) is None


# ------------------------------------------------------- packaging (opt-in)


def _uv() -> str:
    uv = shutil.which("uv")
    assert uv, "uv is not on PATH: the packaging tests build and install with it"
    return uv


def _clean_env() -> dict[str, str]:
    """The test's environment without anything that would point uv or Python
    back at a project or the checkout, and without any Git override."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
        and key not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT", "UV_PYTHON")
    }
    return env


def _hermetic_env(root: Path, uv_cache: str) -> dict[str, str]:
    """Every child's environment: no inherited ``GIT_*`` variable, Git's
    global and system configuration pinned to empty scratch files,
    ``HOME`` (and Windows' ``USERPROFILE``) and the XDG config home in
    the scratch root, Git discovery stopped above the scratch root, and uv
    pointed at the package cache the caller prepared."""
    home = root / "home"
    home.mkdir(exist_ok=True)
    gitconfig = root / "gitconfig"
    gitconfig.touch()
    system_gitconfig = root / "gitconfig-system"
    system_gitconfig.touch()
    env = _clean_env()
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        XDG_CONFIG_HOME=str(root / "xdg-config"),
        GIT_CONFIG_GLOBAL=str(gitconfig),
        GIT_CONFIG_SYSTEM=str(system_gitconfig),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CEILING_DIRECTORIES=str(root.parent),
        UV_CACHE_DIR=uv_cache,
    )
    return env


def _run(argv: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    proc = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
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
        # in the captured output (``-rA``) as the record of what was fetched.
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


def _package_data_members(wheel: Path) -> dict[str, str]:
    with zipfile.ZipFile(wheel) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if "/_data/" in name
        }


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Both wheels built from this checkout and installed, with the
    lockfile's third-party wheels, into a fresh environment in a scratch
    folder that no checkout path reaches."""
    uv = _uv()
    root = tmp_path_factory.mktemp("packaging")
    # The package cache the caller prepared (CI: setup-uv's; locally: the
    # one UV_CACHE_DIR or the default names), read before HOME moves.
    uv_cache = _run([uv, "cache", "dir"], cwd=root, env=_clean_env()).strip()
    env = _hermetic_env(root, uv_cache)
    dist = root / "dist"
    for project in (CLI_DIR, UI_DIR):
        _run([uv, "build", "--wheel", "--project", str(project), "--out-dir", str(dist)], cwd=root, env=env)
    wheels = {path.name.split("-")[0]: path for path in dist.glob("*.whl")}
    assert set(wheels) == {"self_learn_cli", "self_learn_ui"}, sorted(dist.iterdir())

    requirements = root / "requirements.txt"
    _run(
        [
            uv, "export", "--project", str(UI_DIR), "--frozen", "--no-dev",
            "--no-emit-project", "--no-emit-package", "self-learn-cli",
            "--no-header", "--output-file", str(requirements),
        ],
        cwd=root, env=env,
    )
    venv = root / "venv"
    _run([uv, "venv", str(venv), "--python", sys.executable], cwd=root, env=env)
    python = _bin_dir(venv) / ("python.exe" if os.name == "nt" else "python")
    _run([uv, "pip", "install", "--python", str(python), "-r", str(requirements)], cwd=root, env=env)
    _run(
        [
            uv, "pip", "install", "--python", str(python), "--no-deps",
            str(wheels["self_learn_cli"]), str(wheels["self_learn_ui"]),
        ],
        cwd=root, env=env,
    )
    site = Path(
        _run([str(python), "-I", "-c", "import self_learn_ui; print(self_learn_ui.__file__)"], cwd=root, env=env)
        .strip()
    ).resolve().parents[1]
    return {"root": root, "venv": venv, "python": python, "env": env, "wheels": wheels, "site": site, "uv": uv}


def _probe(installed: dict, cwd: Path, *path_entries: Path) -> dict[str, str]:
    out = _run(
        [str(installed["python"]), "-I", "-c", _PROBE, *map(str, path_entries)], cwd=cwd, env=installed["env"]
    )
    return json.loads(out)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        conn.close()


def _scratch_ledger(home: Path, env: dict[str, str]) -> None:
    """The bare-ledger layout the UI suite uses (``support.bare_ledger``),
    built here so this file needs nothing beyond pytest's own fixtures. The
    repository it initializes must be the scratch ledger's own."""
    home.mkdir(parents=True)
    _run(["git", "init", "-q", "-b", "main"], cwd=home, env=env)
    git_dir = _run(["git", "rev-parse", "--absolute-git-dir"], cwd=home, env=env).strip()
    assert Path(git_dir).resolve() == (home / ".git").resolve(), git_dir
    _run(["git", "config", "user.email", "test@example.com"], cwd=home, env=env)
    _run(["git", "config", "user.name", "Test"], cwd=home, env=env)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()


def _replace_atomically(path: Path, data: bytes) -> None:
    """A new file renamed over *path*: never a write into a file the
    installer may have hard-linked from its cache."""
    staged = path.with_name(path.name + ".packaging-test")
    staged.write_bytes(data)
    os.replace(staged, path)


@needs_packaging
def test_wheel_install_serves_pages_and_files_from_package_data(installed: dict) -> None:
    root, venv, site, env = installed["root"], installed["venv"], installed["site"], installed["env"]
    work = root / "work"
    work.mkdir(exist_ok=True)

    # Same-named neighbours where the old ancestor arithmetic looked: a
    # templates folder and a regular FILE named static beside site-packages,
    # and a references folder above that. An installed copy must ignore them.
    (site.parent / "templates").mkdir(exist_ok=True)
    (site.parent / "static").write_text("not the static folder", encoding="utf-8")
    (site.parents[1] / "skills" / "self-learn" / "references").mkdir(parents=True, exist_ok=True)

    # The installed copy imports from the fresh environment, and every lookup
    # lands on its package data, which carries the repository's files byte
    # for byte (no file missing, none extra).
    found = _probe(installed, work)
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
        _scratch_ledger(home, env)
    port = _free_port()
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    (root / "cache").mkdir(exist_ok=True)
    server_env = dict(env)
    server_env.update(
        SELF_LEARN_HOME=str(home),
        XDG_RUNTIME_DIR=str(runtime),
        XDG_CACHE_HOME=str(root / "cache"),
        SELF_LEARN_UI_PORT=str(port),
        SELF_LEARN_UI_CLI_BIN=str(_exe(venv, "self-learn")),
        SELF_LEARN_SDK_CLI_PATH=str(root / "no-claude-here"),
        PATH=os.pathsep.join([str(_bin_dir(venv)), env.get("PATH", "")]),
    )
    ui = _exe(venv, "self-learn-ui")
    expected_token = runtime / "self-learn" / "ui-token"
    reported = Path(json.loads(_run([str(ui), "paths", "--json"], cwd=work, env=server_env))["token_path"])
    assert reported == expected_token, reported
    assert not expected_token.exists(), "the scratch runtime folder already holds a token"
    proc = subprocess.Popen(
        [str(ui), "serve"], cwd=work, env=server_env,
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
                if expected_token.is_file() and expected_token.stat().st_size > 0:
                    break
            except OSError:
                pass
            assert time.monotonic() < deadline, "serve never opened its port and wrote its token"
            time.sleep(0.1)
        token = expected_token.read_text(encoding="utf-8").strip()

        # A marker only the installed base.html carries, put there after the
        # server started: the page must come from that very file, read live,
        # not from any other copy of it (a snapshot would lack the marker).
        marker = f"<!-- packaging-test {uuid.uuid4().hex} -->"
        installed_base = Path(found["templates"]) / "base.html"
        _replace_atomically(installed_base, installed_base.read_bytes() + f"\n{marker}\n".encode("utf-8"))

        status, headers, body = _get(port, f"/?token={token}")
        assert status == 303, (status, body[:500])
        cookie = headers.get("set-cookie", "").split(";", 1)[0]
        assert cookie.startswith("slu_token="), cookie
        authed = {"Cookie": cookie}

        status, headers, body = _get(port, "/", authed)
        page = body.decode("utf-8")
        assert status == 200, (status, page[:2000])
        assert "text/html" in headers.get("content-type", "")
        assert marker in page, page[-2000:]

        for name in ("style.css", "app.js"):
            status, _headers, served = _get(port, f"/static/{name}", authed)
            assert status == 200, (name, status)
            assert served == (UI_DIR / "static" / name).read_bytes(), name
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@needs_packaging
def test_checkout_folders_win_over_package_data(installed: dict) -> None:
    """A checkout layout, with its full marker, planted around a copy of the
    INSTALLED packages (which carry ``_data``): every lookup takes the
    checkout's folder, and the text read is the checkout's. Without the
    plugin marker the same tree is an installed copy again."""
    site = installed["site"]
    layout = installed["root"] / "checkout" / "plugins" / "self-learn"
    if layout.exists():
        shutil.rmtree(layout)
    ui_src, cli_src = layout / "ui" / "src", layout / "cli" / "src"
    shutil.copytree(site / "self_learn_ui", ui_src / "self_learn_ui")
    shutil.copytree(site / "self_learn", cli_src / "self_learn")
    assert (ui_src / "self_learn_ui" / "_data" / "templates").is_dir()
    assert (cli_src / "self_learn" / "_data" / "references").is_dir()
    shutil.copy2(UI_DIR / "pyproject.toml", layout / "ui" / "pyproject.toml")
    shutil.copy2(CLI_DIR / "pyproject.toml", layout / "cli" / "pyproject.toml")
    shutil.copytree(PLUGIN_DIR / ".claude-plugin", layout / ".claude-plugin")
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
    found = _probe(installed, work, ui_src, cli_src)
    assert Path(found["self_learn_ui"]).resolve() == (ui_src / "self_learn_ui" / "__init__.py").resolve()
    assert Path(found["self_learn"]).resolve() == (cli_src / "self_learn" / "__init__.py").resolve()
    for key, folder in planted.items():
        assert Path(found[key]).resolve() == folder.resolve(), (key, found[key])
    assert Path(found["lesson_writing"]).resolve() == (planted["ui_references"] / "lesson-writing.md").resolve()
    assert found["lesson_text"].endswith(marker)
    assert found["charter_text"].endswith(marker)

    # Control: the plugin marker gone, the same tree reads its package data.
    (layout / ".claude-plugin" / "plugin.json").unlink()
    found = _probe(installed, work, ui_src, cli_src)
    assert Path(found["templates"]).resolve() == (ui_src / "self_learn_ui" / "_data" / "templates").resolve()
    assert Path(found["cli_references"]).resolve() == (cli_src / "self_learn" / "_data" / "references").resolve()
    assert not found["lesson_text"].endswith(marker)


@needs_packaging
def test_sdist_then_wheel_carries_the_same_package_data(installed: dict) -> None:
    """The ordinary release route: ``uv build`` makes an sdist and builds the
    wheel FROM it. That wheel must carry the same package data, file for file
    and byte for byte, as the wheel built straight from the checkout."""
    root, env = installed["root"], installed["env"]
    out = root / "dist-sdist"
    for project in (CLI_DIR, UI_DIR):
        _run([installed["uv"], "build", "--project", str(project), "--out-dir", str(out)], cwd=root, env=env)
    for name, direct in installed["wheels"].items():
        (from_sdist,) = out.glob(f"{name}-*.whl")
        (sdist,) = out.glob(f"{name}-*.tar.gz")
        assert sdist.is_file()
        direct_members = _package_data_members(direct)
        assert direct_members, name
        assert _package_data_members(from_sdist) == direct_members, name
