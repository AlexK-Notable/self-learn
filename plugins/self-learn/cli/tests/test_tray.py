"""The tray icon (attention-design-r2 §3.5, §3.10, §5.6; 09 §2.5; 13 §7.6).

`plugins/self-learn/scripts/self-learn-tray` runs under the SYSTEM python
(`#!/usr/bin/python3 -I`, because the uv venv has no `gi`), so every test here
runs it as a subprocess under `/usr/bin/python3 -I`, never imports it. The
tray's own commands are faked on a scratch PATH: `self-learn` (prints a
fixture `attention --json` and logs its argv) and `systemd-run` (logs its
argv). `timeout`, `bash`, `cat` and `sleep` are the real ones. Nothing here
touches the real ledger, a real unit or the user's session bus: test 4 runs
inside its own `dbus-run-session`.

Each test names the mutation that turns it red (§5.6)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
TRAY = REPO_ROOT / "plugins" / "self-learn" / "scripts" / "self-learn-tray"
ICON_DIR = REPO_ROOT / "plugins" / "self-learn" / "assets" / "tray"
UNIT = REPO_ROOT / "systemd" / "self-learn-tray.service"
INSTALL_SH = REPO_ROOT / "install.sh"
SYSTEM_PYTHON = "/usr/bin/python3"

_GI_PROBE = 'import gi; gi.require_version("Gio", "2.0"); from gi.repository import Gio, GLib'


def _gi_missing() -> str | None:
    if not os.access(SYSTEM_PYTHON, os.X_OK):
        return f"{SYSTEM_PYTHON} does not exist"
    probe = subprocess.run([SYSTEM_PYTHON, "-I", "-c", _GI_PROBE], capture_output=True, text=True)
    if probe.returncode != 0:
        return f"{SYSTEM_PYTHON} -I cannot import gi (Gio): {probe.stderr.strip()[-200:]}"
    return None


_WHY = _gi_missing()
if _WHY is not None:  # critique 30: a runner without gi skips, loudly, rather than errors
    pytest.skip(f"self-learn-tray needs PyGObject for the system python: {_WHY}", allow_module_level=True)

_FAKE_SELF_LEARN = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    printf '%s\\n' "$*" >> "$FAKE_LOG"
    if [ "$1 $2" = "attention --json" ]; then
      [ -n "${FAKE_KILL:-}" ] && kill -KILL $$
      [ -n "${FAKE_SLEEP:-}" ] && sleep "$FAKE_SLEEP"
      cat "$FAKE_JSON"
      exit "${FAKE_RC:-0}"
    fi
    exit 0
    """
)
_FAKE_SYSTEMD_RUN = '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$FAKE_LOG.systemd-run"\n'


def _item(**over) -> dict:
    """One item in the §4.1 contract's shape."""
    base = {
        "id": "att-000000000001", "class": "decided", "kind": "decided.steward-run", "because": None,
        "subject": "run-1", "title": "The steward decided 3 lessons", "meanwhile": None, "state": "open",
        "flagged": False, "seen": False, "partial": False, "since": "2026-10-31T03:30:00Z",
        "updated_at": "2026-10-31T03:40:00Z", "source": {"by": "steward", "run": "run-1", "report": None},
        "refs": [], "options": [], "undo": None, "conversation": {"turns": 0, "last_at": None},
        "answer": None, "run": None,
    }
    base.update(over)
    return base


def _attention(state: str, tooltip: str, items: list[dict], cache_dir: Path, error=None) -> dict:
    return {
        "version": 2, "generated_at": "2026-11-01T11:30:12Z", "cache_dir": str(cache_dir), "state": state,
        "counts": {"needs_you": sum(i["class"] == "needs-you" for i in items),
                   "new": sum(i["flagged"] and not i["seen"] for i in items),
                   "decided_unseen": sum(i["class"] == "decided" and not i["seen"] for i in items),
                   "approved": 0},
        "tooltip": tooltip, "error": error, "items": items,
    }


class Env:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "ledger"  # a fixture SELF_LEARN_HOME, never ~/.self-learn
        self.cache = tmp_path / "cache" / "self-learn" / "slug"
        self.log = tmp_path / "calls.log"
        self.json = tmp_path / "attention.json"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in (("self-learn", _FAKE_SELF_LEARN), ("systemd-run", _FAKE_SYSTEMD_RUN)):
            (bin_dir / name).write_text(body, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        for name in ("bash", "cat", "sleep", "timeout", "env"):
            real = shutil.which(name)
            assert real, f"{name} must exist on this host to build the harness"
            (bin_dir / name).symlink_to(real)
        # Run the tray through a symlink, as the unit runs `~/.local/bin/self-learn-tray`:
        # only a resolved `__file__` finds `assets/tray` beside the real script.
        self.tray = bin_dir / "self-learn-tray"
        self.tray.symlink_to(TRAY)
        self.vars = {
            "PATH": str(bin_dir), "HOME": str(tmp_path / "home"), "SELF_LEARN_HOME": str(self.home),
            "FAKE_LOG": str(self.log), "FAKE_JSON": str(self.json),
        }
        self.write(_attention("idle", "self-learn: nothing needs you", [], self.cache))

    def write(self, data) -> None:
        self.json.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def env(self, **extra) -> dict[str, str]:
        return {**self.vars, **extra}

    def pure(self, step: str, *args: str, **extra) -> dict:
        res = subprocess.run([SYSTEM_PYTHON, "-I", str(self.tray), "--pure", step, *args], env=self.env(**extra),
                             capture_output=True, text=True, timeout=60)
        assert res.returncode == 0, (res.stdout, res.stderr)
        return json.loads(res.stdout)

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def _face(out: dict) -> tuple[str, str, str]:
    v = out["view"]
    return v["status"], v["icon_name"], v["tooltip_title"]


# ------------------------------------------------------------------ 1


def test_1_four_states_map_to_status_icon_and_tooltip(env):
    """§3.5 / answer 8: the reader's `state` maps to (Status, IconName, tooltip);
    idle is `Passive` with the grey icon, so Waybar (show-passive-items) still
    shows it. The fixtures are real §4.1 payloads: `new` carries a flagged unseen
    item, and the idle one carries an unseen steward digest (never flagged), which
    must not light anything. The tray maps `state`; it never re-derives it.
    Mutation: hide idle (idle's Status or icon changed) -> red. Mutation (gate r1
    MINOR 2): `ICON_DIR` from `os.path.abspath(__file__)` instead of `realpath`
    -> red, because the tray runs through a symlink here as it does deployed."""
    digest = _item()  # unseen, not flagged
    flagged = _item(id="att-000000000002", kind="decided.overseer-run", flagged=True, subject="2026-10-25",
                    source={"by": "overseer", "run": "run-2", "report": "2026-10-25"})
    ask = _item(id="att-000000000003", **{"class": "needs-you"}, kind="ask.system-change",
                because="system-change", title="Bind oo7-daemon to the session bus?")
    broken = _item(id="att-000000000004", **{"class": "needs-you"}, kind="broken.host", because="broken")
    cases = {
        "idle": (_attention("idle", "self-learn: nothing needs you", [digest], env.cache),
                 ("Passive", "self-learn-tray-idle", "self-learn: nothing needs you")),
        "new": (_attention("new", "self-learn: 1 new", [digest, flagged], env.cache),
                ("Active", "self-learn-tray-new", "self-learn: 1 new")),
        "needs-you": (_attention("needs-you", "self-learn: 1 needs you (a change to your system)", [ask], env.cache),
                      ("NeedsAttention", "self-learn-tray-needs-you",
                       "self-learn: 1 needs you (a change to your system)")),
        "broken": (_attention("broken", "self-learn: the host service is down", [broken], env.cache),
                   ("NeedsAttention", "self-learn-tray-broken", "self-learn: the host service is down")),
    }
    for state, (payload, want) in cases.items():
        env.write(payload)
        out = env.pure("poll")
        assert _face(out) == want, (state, out)
        assert out["view"]["state"] == state
        assert out["error"] is None
        # the named icon ships beside the script (published through IconThemePath),
        # found through the deployed symlink (`env.tray`), not beside the link
        assert out["icon_dir"] == str(ICON_DIR.resolve()), out["icon_dir"]
        assert (ICON_DIR / f"{want[1]}.svg").is_file(), want[1]

    # "idle grey": every colour in the idle icon is a grey (r == g == b)
    idle_svg = (ICON_DIR / "self-learn-tray-idle.svg").read_text(encoding="utf-8")
    colours = re.findall(r'(?:fill|stroke)="#([0-9a-fA-F]{6})"', idle_svg)
    assert colours, "positive control: the idle icon draws something"
    assert all(_near_grey(c) for c in colours), colours


_PIXBUF_LOAD = """
import sys, gi
try:
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
except (ImportError, ValueError) as exc:
    print("SKIP", exc); sys.exit(0)
for path in sys.argv[1:]:
    print(path, GdkPixbuf.Pixbuf.new_from_file_at_size(path, 22, 22).get_width())
"""


def test_1b_every_icon_loads_through_gdk_pixbuf():
    """Waybar draws the icon through GTK's icon theme, which loads the SVG with
    gdk-pixbuf. On this host's gdk-pixbuf an XML declaration followed by a
    leading comment hides the file's type ("Couldn't recognize the image file
    format"; measured on the launcher icon `assets/self-learn-ui.svg`), and the
    tray would show `image-missing`. Measured: the type is found only while
    `<svg` starts within the first 256 bytes (shared-mime-info's magic window), so
    the structural check below holds even where the system python has no
    GdkPixbuf. Mutation: put a 300-character comment above `<svg` -> red."""
    icons = sorted(ICON_DIR.glob("self-learn-tray-*.svg"))
    assert [p.stem for p in icons] == sorted(f"self-learn-tray-{s}" for s in ("idle", "new", "needs-you", "broken"))
    for icon in icons:
        assert 0 <= icon.read_bytes().find(b"<svg") < 200, f"{icon.name}: <svg must open within the sniff window"
    res = subprocess.run([SYSTEM_PYTHON, "-I", "-c", _PIXBUF_LOAD, *map(str, icons)],
                         capture_output=True, text=True, timeout=60)
    if res.stdout.startswith("SKIP"):
        pytest.skip(f"no GdkPixbuf for the system python: {res.stdout.strip()}")
    assert res.returncode == 0, res.stderr
    assert [line.rsplit(" ", 1)[1] for line in res.stdout.splitlines()] == ["22"] * 4, res.stdout


def _near_grey(hex6: str) -> bool:
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    return max(r, g, b) - min(r, g, b) <= 12


# ------------------------------------------------------------------ 2


def test_2_timeout_and_nonzero_exit_map_to_broken(env):
    """§3.10: a timed-out or non-zero `attention` call, or output that is not the
    contract's JSON, shows `broken` with the error in the tooltip.
    Mutation: map it to idle -> red."""
    env.write(_attention("idle", "self-learn: nothing needs you", [], env.cache))
    ok = env.pure("poll")
    assert _face(ok)[0:2] == ("Passive", "self-learn-tray-idle"), "positive control: the same payload reads idle"

    slow = env.pure("poll", "--timeout-secs", "1", FAKE_SLEEP="20")
    assert _face(slow) == ("NeedsAttention", "self-learn-tray-broken", "self-learn: could not check what needs you"), slow
    assert "did not answer within 1 s" in slow["view"]["tooltip_description"]

    # killed outright (timeout(1) reports 137): stopped, not "failed with 137"
    # (gate r1 NIT 2; mutation: drop the SIGKILL branch -> red)
    killed = env.pure("poll", FAKE_KILL="1")
    assert _face(killed)[0:2] == ("NeedsAttention", "self-learn-tray-broken"), killed
    assert "stopped before it answered" in killed["error"], killed

    # exit 1 with the contract's broken JSON: its own error reaches the tooltip
    env.write(_attention("broken", "self-learn: broken", [], env.cache, error="cannot read open-questions.yaml"))
    failed = env.pure("poll", FAKE_RC="1")
    assert _face(failed)[0:2] == ("NeedsAttention", "self-learn-tray-broken"), failed
    assert failed["view"]["tooltip_description"] == "cannot read open-questions.yaml (exit 1)", failed

    # a non-zero exit is broken even when the JSON it printed says idle
    env.write(_attention("idle", "self-learn: nothing needs you", [], env.cache))
    odd = env.pure("poll", FAKE_RC="3")
    assert _face(odd)[0:2] == ("NeedsAttention", "self-learn-tray-broken"), odd

    env.write("{not json")
    garbled = env.pure("poll")
    assert _face(garbled)[0:2] == ("NeedsAttention", "self-learn-tray-broken"), garbled
    assert garbled["error"].startswith("its output was not readable: not JSON"), garbled

    # every poll ran the contract's command, nothing else
    assert set(env.calls()) == {"attention --json"}, env.calls()


# ------------------------------------------------------------------ 3


def test_3_activate_runs_exactly_the_inbox_launcher(env):
    """§3.10: a left click runs exactly
    `systemd-run --user --collect --quiet -- self-learn-ui-open --page /inbox`
    (the fake `systemd-run` logs its argv). Mutation: any other argv -> red."""
    out = env.pure("activate")
    assert out["rc"] == 0
    argv = (env.tmp / "calls.log.systemd-run").read_text(encoding="utf-8").splitlines()
    assert argv == ["--user", "--collect", "--quiet", "--", "self-learn-ui-open", "--page", "/inbox"]
    assert env.calls() == [], "a click runs no `self-learn` itself"


def test_3b_middle_click_marks_decided_seen_then_polls(env):
    """§3.5: the middle click runs `self-learn attention seen --all-decided`, then
    polls at once so the icon drops `new`. Mutation: drop the re-poll -> red."""
    env.write(_attention("idle", "self-learn: nothing needs you", [], env.cache))
    out = env.pure("secondary")
    assert out["rc"] == 0
    assert env.calls() == ["attention seen --all-decided", "attention --json"]
    assert out["view"]["state"] == "idle"


# ------------------------------------------------------------------ 4

_DRIVER = r'''
import json, os, subprocess, sys, time
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

tray, out_path, ledger, cache = sys.argv[1:5]
addr = os.environ["DBUS_SESSION_BUS_ADDRESS"]
XML = """<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg name="service" type="s" direction="in"/></method>
<property name="RegisteredStatusNotifierItems" type="as" access="read"/>
<property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
<property name="ProtocolVersion" type="i" access="read"/></interface></node>"""
IFACE = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
regs, signals, result = [], [], {}
ctx = GLib.MainContext.default()


def connect():
    flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    return Gio.DBusConnection.new_for_address_sync(addr, flags, None, None)


class Watcher:
    """A fake StatusNotifierWatcher on its own connection, so a second one is a new owner."""
    def __init__(self, n):
        self.n, self.conn = n, connect()
        self.reg = self.conn.register_object("/StatusNotifierWatcher", IFACE, self.call, self.get, None)
        self.own = Gio.bus_own_name_on_connection(self.conn, "org.kde.StatusNotifierWatcher",
                                                  Gio.BusNameOwnerFlags.NONE, None, None)
    def call(self, conn, sender, path, iface, method, params, inv):
        regs.append({"watcher": self.n, "sender": sender, "service": params.unpack()[0]})
        inv.return_value(None)
    def get(self, conn, sender, path, iface, prop):
        return {"RegisteredStatusNotifierItems": GLib.Variant("as", [r["service"] for r in regs]),
                "IsStatusNotifierHostRegistered": GLib.Variant("b", True),
                "ProtocolVersion": GLib.Variant("i", 0)}[prop]
    def close(self):
        Gio.bus_unown_name(self.own)
        self.conn.unregister_object(self.reg)
        self.conn.close_sync(None)


def wait(cond, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.02)
    return bool(cond())


def calls():
    try:
        return open(os.environ["FAKE_LOG"]).read().splitlines()
    except FileNotFoundError:
        return []


def polls():
    return calls().count("attention --json")


def seen_then_polled(start):
    tail = calls()[start:]
    if "attention seen --all-decided" not in tail:
        return False
    return "attention --json" in tail[tail.index("attention seen --all-decided") + 1:]


w1 = Watcher(1)
proc = subprocess.Popen([sys.executable, "-I", tray], stderr=open(out_path + ".stderr", "w"))
try:
    result["registered_1"] = wait(lambda: any(r["watcher"] == 1 for r in regs), 15)
    result["first_poll"] = wait(lambda: polls() >= 1, 15)
    client = connect()
    client.signal_subscribe(None, "org.kde.StatusNotifierItem", None, "/StatusNotifierItem", None,
                            Gio.DBusSignalFlags.NONE,
                            lambda c, s, p, i, name, params: signals.append([name, params.unpack()]), )
    service = regs[0]["service"] if regs else ""
    wait(lambda: False, 0.5)
    props = client.call_sync(service, "/StatusNotifierItem", "org.freedesktop.DBus.Properties", "GetAll",
                             GLib.Variant("(s)", ("org.kde.StatusNotifierItem",)), None,
                             Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    result["props"] = {k: props[k] for k in ("Id", "Category", "Status", "IconName", "IconThemePath", "ToolTip")}

    w1.close()  # Waybar restarts: the watcher's owner changes
    w2 = Watcher(2)
    result["registered_2"] = wait(lambda: any(r["watcher"] == 2 for r in regs), 15)

    client.call_sync(service, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "Activate",
                     GLib.Variant("(ii)", (0, 0)), None, Gio.DBusCallFlags.NONE, 5000, None)
    sr = os.environ["FAKE_LOG"] + ".systemd-run"
    result["activated"] = wait(lambda: os.path.exists(sr), 10) and open(sr).read().splitlines()

    # A middle click over the bus marks every decided item seen, then polls.
    start = len(calls())
    client.call_sync(service, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "SecondaryActivate",
                     GLib.Variant("(ii)", (0, 0)), None, Gio.DBusCallFlags.NONE, 5000, None)
    result["secondary"] = wait(lambda: seen_then_polled(start), 10)
    result["secondary_calls"] = calls()[start:]

    # File monitors: a change in each watched directory polls at once. The ledger
    # root is watched by itself (not recursively): a typed reply's statement.
    for key, d in (("ledger_root", ledger),
                   ("ledger_attention", os.path.join(ledger, "attention")),
                   ("ledger_overseer", os.path.join(ledger, "overseer")),
                   ("cache_attention", os.path.join(cache, "attention"))):
        wait(lambda: False, 1.5)  # past the quiet window after the last poll
        before = polls()
        os.makedirs(d, exist_ok=True)
        name = "user-statements.jsonl" if key == "ledger_root" else "touched-" + key
        with open(os.path.join(d, name), "a") as f:
            f.write("x")
        result["poll_on_" + key] = wait(lambda: polls() > before, 10)

    # A state change reaches the host as NewStatus + NewIcon.
    with open(os.environ["FAKE_JSON"], "w") as f:
        f.write(os.environ["NEXT_JSON"])
    wait(lambda: False, 1.5)
    with open(os.path.join(ledger, "overseer", "report.md"), "w") as f:
        f.write("new")
    wait(lambda: ["NewStatus", ("NeedsAttention",)] in [[n, tuple(p)] for n, p in signals], 10)
    result["signals"] = [n for n, _p in signals]
    result["new_status"] = [p for n, p in signals if n == "NewStatus"]
finally:
    proc.terminate()
    result["tray_rc"] = proc.wait(10)
    result["regs"] = regs
    json.dump(result, open(out_path, "w"))
'''


def test_4_registers_with_the_watcher_and_again_after_its_owner_changes(env):
    """§3.10 / r1 §4.2: under its own `dbus-run-session`, with a fake
    StatusNotifierWatcher, the tray registers, and registers again after the
    watcher's owner changes (Waybar restarting). The same live run checks the
    D-Bus face (Id, Category, Status, IconName, IconThemePath), that Activate
    over the bus runs the launcher, that a change in each watched directory polls
    at once (test 6's live half), and that a state change emits NewStatus.
    Mutation: drop the re-register on watcher appearance -> `registered_2` red.
    Gate r1 additions, each mutation-verified: SecondaryActivate over the bus
    (mutation: `on_call` ignores it -> `secondary` red); the tray runs through a
    symlink as deployed (mutation: `abspath` for `realpath` -> IconThemePath red);
    the title is markup-escaped (mutation: drop the escape -> ToolTip red); the
    ledger root is watched (mutation: drop it -> `poll_on_ledger_root` red)."""
    if shutil.which("dbus-run-session") is None or shutil.which("dbus-daemon") is None:
        pytest.skip("dbus-run-session/dbus-daemon is not installed: cannot run a private session bus for the tray")
    driver = env.tmp / "driver.py"
    driver.write_text(_DRIVER, encoding="utf-8")
    out = env.tmp / "driver.json"
    # The two ledger subdirectories exist before the tray starts, so a write inside
    # one is seen only by that directory's own monitor, never as a CREATED in the root.
    (env.home / "attention").mkdir(parents=True)
    (env.home / "overseer").mkdir()
    env.write(_attention("idle", "self-learn: 0 need you & <none> new", [], env.cache))
    nxt = _attention("needs-you", "self-learn: 1 needs you", [_item(**{"class": "needs-you"})], env.cache)
    run = subprocess.run(
        [shutil.which("dbus-run-session"), f"--dbus-daemon={shutil.which('dbus-daemon')}", "--", SYSTEM_PYTHON, "-I",
         str(driver), str(env.tray), str(out), str(env.home), str(env.cache)],
        env=env.env(NEXT_JSON=json.dumps(nxt)), capture_output=True, text=True, timeout=180,
    )
    assert out.exists(), (run.returncode, run.stdout, run.stderr)
    res = json.loads(out.read_text(encoding="utf-8"))
    tray_log = Path(str(out) + ".stderr").read_text(encoding="utf-8")
    assert res.get("registered_1"), (res, tray_log)
    assert res.get("registered_2"), (res, tray_log)
    services = {r["service"] for r in res["regs"]}
    assert len(services) == 1 and services.pop().startswith("org.kde.StatusNotifierItem-"), res["regs"]

    props = res["props"]
    assert props["Id"] == "self-learn" and props["Category"] == "ApplicationStatus"
    assert props["Status"] == "Passive" and props["IconName"] == "self-learn-tray-idle"
    assert Path(props["IconThemePath"]).resolve() == ICON_DIR.resolve()
    # Waybar renders the title as markup: the reader's text is escaped once
    assert props["ToolTip"][2] == "self-learn: 0 need you &amp; &lt;none&gt; new", props["ToolTip"]

    assert res["activated"] == ["--user", "--collect", "--quiet", "--", "self-learn-ui-open", "--page", "/inbox"]
    assert res["secondary"], (res["secondary_calls"], tray_log)
    for key in ("ledger_root", "ledger_attention", "ledger_overseer", "cache_attention"):
        assert res["poll_on_" + key], (key, res, tray_log)
    assert ["NeedsAttention"] in res["new_status"], (res, tray_log)
    assert "NewIcon" in res["signals"] and "NewToolTip" in res["signals"]
    assert res["tray_rc"] == 0, tray_log  # SIGTERM reaches the handler (a clean stop)
    assert "PyGIDeprecationWarning" not in tray_log, tray_log  # gate r1 NIT 1


# ------------------------------------------------------------------ 5


def _install_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    shims = tmp_path / "install-shims"
    shims.mkdir()
    log = tmp_path / "systemctl.log"
    log.touch()
    for name, body in (("systemctl", 'echo "$@" >> "$SYSTEMCTL_LOG"\nexit 0\n'), ("uv", "exit 0\n"),
                       ("update-desktop-database", "exit 0\n")):
        (shims / name).write_text(f"#!/usr/bin/env bash\n{body}", encoding="utf-8")
        (shims / name).chmod(0o755)
    for name in ("bash", "env", "dirname", "mkdir", "mv", "ln", "date", "readlink", "sed", "timeout", "cat", "rm"):
        (shims / name).symlink_to(shutil.which(name))
    home = tmp_path / "install-home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": str(shims), "SYSTEMCTL_LOG": str(log),
           "XDG_CONFIG_HOME": str(home / ".config")}
    return env, home, log


def test_5_install_links_the_unit_and_script_and_enables_nothing(tmp_path):
    """§5.6 item 5: `install.sh --dry-run` plans the tray links and touches
    nothing; a real run links the unit and the script, and runs no systemctl
    verb but `daemon-reload` (and the read-only `is-enabled`).
    Mutations: drop the unit link -> red; add `systemctl --user enable` -> red."""
    env, home, log = _install_env(tmp_path)
    unit_dir = Path(env["XDG_CONFIG_HOME"]) / "systemd" / "user"
    dry = subprocess.run(["bash", str(INSTALL_SH), "--dry-run"], env=env, capture_output=True, text=True, timeout=60)
    assert dry.returncode == 0, (dry.stdout, dry.stderr)
    planned = [line for line in dry.stdout.splitlines() if "[dry] ln -sfn" in line]
    assert any(str(UNIT) in line and line.endswith(str(unit_dir / "self-learn-tray.service")) for line in planned), planned
    assert any(str(TRAY) in line and line.endswith(str(home / ".local" / "bin" / "self-learn-tray"))
               for line in planned), planned
    assert not any(re.search(r"\benable\b", line) for line in dry.stdout.splitlines() if "[dry]" in line), dry.stdout
    assert log.read_text() == "" and not unit_dir.exists(), "a dry run executed something"

    real = subprocess.run(["bash", str(INSTALL_SH)], env=env, capture_output=True, text=True, timeout=60)
    assert real.returncode == 0, (real.stdout, real.stderr)
    assert (unit_dir / "self-learn-tray.service").resolve() == UNIT.resolve()
    assert (home / ".local" / "bin" / "self-learn-tray").resolve() == TRAY.resolve()
    verbs = [line.split()[1] if line.split()[:1] == ["--user"] else "<no --user>"
             for line in log.read_text().splitlines() if line.strip()]
    assert "daemon-reload" in verbs, "positive control: the systemctl shim saw the reloads"
    assert set(verbs) <= {"daemon-reload", "is-enabled"}, verbs
    assert "systemctl --user enable --now self-learn-tray.service" in real.stdout  # printed, never run


def test_5b_unit_shape():
    """§5.6: Type=simple, Restart=always, RestartSec=5, the same PATH floor and
    SELF_LEARN_HOME pin as the host unit, WantedBy=default.target."""
    unit = UNIT.read_text(encoding="utf-8")
    host = (REPO_ROOT / "systemd" / "self-learn-host.service").read_text(encoding="utf-8")
    lines = {line for line in unit.splitlines() if line and not line.startswith("#")}
    for want in ("Type=simple", "Restart=always", "RestartSec=5", "WantedBy=default.target",
                 "ExecStart=%h/.local/bin/self-learn-tray"):
        assert want in lines, want
    for pin in ("Environment=SELF_LEARN_HOME=", "Environment=PATH="):
        host_line = next(line for line in host.splitlines() if line.startswith(pin))
        assert host_line in lines, pin


# ------------------------------------------------------------------ 6


def test_6_watches_the_fixture_ledger_and_the_cache_dir_named_by_the_json(env):
    """§3.10 / critique 30: the monitors watch `$SELF_LEARN_HOME/overseer/` and
    `$SELF_LEARN_HOME/attention/` for a fixture SELF_LEARN_HOME, and
    `<cache_dir>/attention/` with `cache_dir` taken from the JSON. With
    SELF_LEARN_HOME unset it falls back to `~/.self-learn` under HOME. Gate r1
    MINOR 3: `$SELF_LEARN_HOME` itself too (not recursively), where a typed
    reply's statement lands (`user-statements.jsonl`).
    The live half (a change in each directory polls at once) is in test 4.
    Mutation: hard-code `~/.self-learn` -> red."""
    out = env.pure("poll")
    assert out["home"] == str(env.home)
    assert out["watch"] == sorted([str(env.home), str(env.home / "overseer"), str(env.home / "attention"),
                                   str(env.cache / "attention")])

    other = env.tmp / "elsewhere"
    env.write(_attention("idle", "self-learn: nothing needs you", [], other))
    assert str(other / "attention") in env.pure("poll")["watch"], "cache_dir comes from the JSON"

    vars_without_home = {k: v for k, v in env.vars.items() if k != "SELF_LEARN_HOME"}
    res = subprocess.run([SYSTEM_PYTHON, "-I", str(env.tray), "--pure", "poll"], env=vars_without_home,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["home"] == str(env.tmp / "home" / ".self-learn")
