"""Telling an open window where to go, and the walk world (attention round
2026-10-31c, design r2 §4.7 "/navigate" and "Sandbox switch"; §5.5 tests 9,
12 and 16; critique 10 and 16).

- `POST /navigate` publishes `{"type": "navigate"}` to connected pages
  (204), answers 409 with none connected, and refuses any path outside
  /inbox and /overseer-report (400).
- `self-learn-ui-open --page`: with no window it opens the tokened URL;
  with one it POSTs /navigate (curl shim) and only focuses it; on 409 it
  opens the URL after all. Hermetic PATH (test_launcher's harness).
- The world `attention` seeds the five §2.3 shapes into a scratch ledger,
  read back through the REAL `self-learn attention --json`, and the UI it
  starts uses the scripted ask fake with every agent marker removed and
  systemd-run/systemctl shimmed. It runs in a child process: the sandbox
  sets its redirects in os.environ, which must never touch this one.

Each test names the mutation it was checked against.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from starlette.testclient import TestClient

import support
from self_learn_ui.app import create_app
from self_learn_ui.env import EnvConfig
from self_learn_ui.runner import FakeRunner
from self_learn_ui.sse import AppEventHub
from test_launcher import (
    _HYPRCTL_BODY_TMPL,
    _LOGGING_LAUNCH_TMPL,
    _env,
    _hermetic_bindir,
    _run,
    _wait_for_nonempty,
)

TOKEN = "test-token"
HX = {"HX-Request": "true"}
UI_ROOT = Path(__file__).resolve().parents[1]


def _client(tmp_path):
    hub = AppEventHub()
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = EnvConfig(self_learn_home=home, ui_port=7357, ui_browser=None, pane_model="m",
                    pane_budget_usd=1.0, pane_max_turns=5, pane_engine="sdk")
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), app_hub=hub, start_watcher=False)
    client = TestClient(app, base_url="http://127.0.0.1:7357")
    client.cookies.set("slu_token", TOKEN)
    support.enter_client(client)
    return client, hub


async def _subscribe(hub):
    return hub.subscribe()


async def _drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


# ----------------------------------------------------------------- 12. the route


def test_navigate_reaches_a_connected_page(tmp_path):
    client, hub = _client(tmp_path)
    queue = client.portal.call(_subscribe, hub)
    resp = client.post("/navigate", data={"path": "/inbox/att-0000000000a1"}, headers=HX)
    assert resp.status_code == 204
    assert client.portal.call(_drain, queue) == [{"type": "navigate", "path": "/inbox/att-0000000000a1"}]


def test_navigate_with_no_page_connected_is_409(tmp_path):
    client, _hub = _client(tmp_path)
    assert client.post("/navigate", data={"path": "/inbox"}, headers=HX).status_code == 409


def test_navigate_refuses_paths_outside_the_inbox_and_the_report(tmp_path):
    """Mutation: drop the prefix check -> red."""
    client, hub = _client(tmp_path)
    queue = client.portal.call(_subscribe, hub)
    # Positive control: an allowed path goes through on the same client.
    assert client.post("/navigate", data={"path": "/overseer-report"}, headers=HX).status_code == 204
    for bad in ("/settings", "https://example.org/inbox", "//evil/inbox", "/inbox/../settings",
                "/record/lrn-00000001", ""):
        assert client.post("/navigate", data={"path": bad}, headers=HX).status_code == 400, bad
    assert client.portal.call(_drain, queue) == [{"type": "navigate", "path": "/overseer-report"}]


def test_navigate_needs_the_cookie_and_hx_request(tmp_path):
    client, _hub = _client(tmp_path)
    assert client.post("/navigate", data={"path": "/inbox"}).status_code == 403


def test_the_page_script_follows_only_inbox_and_report_paths() -> None:
    app_js = (UI_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'case "navigate":' in app_js and "followNavigate(envelope.path)" in app_js
    assert "window.location.assign(path)" in app_js
    assert "NAVIGATE_PATH = /^\\/(inbox|overseer-report)" in app_js
    base = (UI_ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert '<script src="/static/app.js" defer></script>' in base


# ----------------------------------------------------------------- 9. the opener


_CURL_TMPL = """
cat > "{stdin}"
printf '%s\\n' "$@" > "{args}"
printf '%s' "{status}"
exit 0
"""

PAGE = "/inbox/att-0000000000a1"


def _opener_env(tmp_path, **fakes):
    bindir = _hermetic_bindir(tmp_path, **fakes)
    runtime = tmp_path / "runtime"
    (runtime / "self-learn").mkdir(parents=True)
    (runtime / "self-learn" / "ui-token").write_text("tok123", encoding="utf-8")
    return _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime))


def test_page_with_no_window_opens_the_tokened_url(tmp_path):
    chromium = tmp_path / "chromium.log"
    curl_args = tmp_path / "curl.args"
    env = _opener_env(
        tmp_path,
        hyprctl=_HYPRCTL_BODY_TMPL.format(log=tmp_path / "hyprctl.log", clients_json="[]"),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium),
        curl=_CURL_TMPL.format(stdin=tmp_path / "curl.stdin", args=curl_args, status="204"),
    )
    result = _run(env, "--page", PAGE)
    assert result.returncode == 0, result.stderr
    content = _wait_for_nonempty(chromium)
    assert f"--app=http://127.0.0.1:7357{PAGE}?token=tok123" in content
    assert not curl_args.exists(), "no window: nothing to navigate"


def test_page_with_a_window_posts_navigate_and_only_focuses(tmp_path):
    """Mutation: focus only (never POST) -> red."""
    chromium = tmp_path / "chromium.log"
    hyprctl = tmp_path / "hyprctl.log"
    curl_args = tmp_path / "curl.args"
    curl_stdin = tmp_path / "curl.stdin"
    env = _opener_env(
        tmp_path,
        hyprctl=_HYPRCTL_BODY_TMPL.format(
            log=hyprctl,
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Inbox"}]'),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium),
        curl=_CURL_TMPL.format(stdin=curl_stdin, args=curl_args, status="204"),
    )
    result = _run(env, "--page", PAGE)
    assert result.returncode == 0, result.stderr
    args = curl_args.read_text(encoding="utf-8").splitlines()
    assert "http://127.0.0.1:7357/navigate" in args
    assert "HX-Request: true" in args
    assert f"path={PAGE}" in args
    # The token travels on stdin as the cookie header, never in argv.
    assert "Cookie: slu_token=tok123" in curl_stdin.read_text(encoding="utf-8")
    assert not any("tok123" in a for a in args)
    assert "dispatch focuswindow address:0xAAA" in _wait_for_nonempty(hyprctl)
    assert not chromium.exists() or chromium.stat().st_size == 0


def test_page_with_a_window_and_no_page_connected_opens_the_url(tmp_path):
    chromium = tmp_path / "chromium.log"
    env = _opener_env(
        tmp_path,
        hyprctl=_HYPRCTL_BODY_TMPL.format(
            log=tmp_path / "hyprctl.log",
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Inbox"}]'),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium),
        curl=_CURL_TMPL.format(stdin=tmp_path / "curl.stdin", args=tmp_path / "curl.args",
                               status="409"),
    )
    result = _run(env, "--page", "/inbox")
    assert result.returncode == 0, result.stderr
    assert "--app=http://127.0.0.1:7357/inbox?token=tok123" in _wait_for_nonempty(chromium)


def test_page_refuses_other_paths(tmp_path):
    env = _opener_env(tmp_path)
    for bad in ("/settings", "/inbox/../settings", "https://example.org/"):
        result = _run(env, "--page", bad)
        assert result.returncode == 2, bad
        assert "--page takes an /inbox or /overseer-report path" in result.stderr


# ----------------------------------------------------------------- 16. the walk world


_WORLD_CHILD = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import sandbox_ui as sb
state = Path(sys.argv[2])
for sub in sb.SUBDIRS:
    (sb.live_dir(state) / sub).mkdir(parents=True, exist_ok=True)
sb.apply_redirects(state)
sb.assert_isolated(state)
sb.prepare_world_env(state, ["attention"])
host = sb.build_host(state)
ledger = sb.build_ledger(state, host)
sb.seed_corpus(ledger, host, 3)
sb.apply_worlds(state, host, ledger, ["attention"])
import subprocess
proc = subprocess.run(["self-learn", "attention", "--json"], capture_output=True, text=True,
                      stdin=subprocess.DEVNULL)
from self_learn.settings import AGENT_CALLER_MARKERS
from self_learn_ui.app import create_app
from self_learn_ui.ask_runner import FakeAskRunner
from self_learn_ui.env import EnvConfig
env = EnvConfig(self_learn_home=ledger, ui_port=7357, ui_browser=None, pane_model="m",
                pane_budget_usd=1.0, pane_max_turns=5, pane_engine="sdk", ui_idle_exit_seconds=0)
app = create_app(env=env, token="t", start_watcher=False)
import shutil
print(json.dumps({
    "rc": proc.returncode, "stderr": proc.stderr[-800:], "doc": json.loads(proc.stdout),
    "fake": isinstance(app.state.ask_runner, FakeAskRunner) and app.state.ask_runner.seal,
    "fake_env": os.environ.get("SELF_LEARN_UI_FAKE_ASK"),
    "markers": [m for m in AGENT_CALLER_MARKERS if m in os.environ],
    "systemd_run": shutil.which("systemd-run"), "systemctl": shutil.which("systemctl"),
    "shims": str(sb.shim_dir(state)), "ledger": str(ledger),
}))
'''


def test_the_attention_world_seeds_the_five_walk_shapes_and_starts_safely(tmp_path):
    """§5.5 test 16 and the post-landing walk rules. Mutation: drop the
    hold seed -> red; leave the markers in -> red; drop the shims -> red."""
    import os

    child = tmp_path / "world_child.py"
    child.write_text(_WORLD_CHILD, encoding="utf-8")
    env = dict(os.environ)
    env["CLAUDECODE"] = "1"  # an agent's shell: the world must remove it
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        [sys.executable, str(child), str(UI_ROOT / "tools"), str(tmp_path / "state")],
        capture_output=True, text=True, env=env, timeout=240, stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["rc"] == 0, out["stderr"]
    kinds = sorted(i["kind"] for i in out["doc"]["items"])
    assert kinds.count("ask.system-change") == 2
    for kind in ("hold.credentials", "ask.conflict", "decided.hook-activated"):
        assert kind in kinds, kinds
    conflict = next(i for i in out["doc"]["items"] if i["kind"] == "ask.conflict")
    assert len([r for r in conflict["refs"] if r.startswith("stmt-")]) == 2
    with_conditions = [o for i in out["doc"]["items"] for o in i["options"]
                       if o["id"] == "opt-yes-conditions"]
    assert with_conditions and all(o["note"] == "required" for o in with_conditions)
    assert out["fake"] is True and out["fake_env"] == "1"
    assert out["markers"] == []
    assert out["systemd_run"] == str(Path(out["shims"]) / "systemd-run")
    assert out["systemctl"] == str(Path(out["shims"]) / "systemctl")
    assert out["ledger"].startswith(str(tmp_path))
