"""The tray icon (attention-design-r2 §3.5, §3.10, §5.6; 09 §2.6; 13 §7.7).

`plugins/self-learn/scripts/self-learn-tray` runs under the SYSTEM python
(`#!/usr/bin/python3 -I`, because the uv venv has no `gi`), so every test here
runs it as a subprocess under `/usr/bin/python3 -I`, never imports it. The
tray's own commands are faked on a scratch PATH: `self-learn` (prints a
fixture `attention --json` and logs its argv), `systemd-run` and
`systemctl` (each logs its argv). `timeout`, `bash`, `cat` and `sleep` are the real ones. Nothing here
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
import threading
import time
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
    if [ "$1 $2" = "serve --restart" ]; then
      [ -n "${FAKE_RESTART_SLEEP:-}" ] && sleep "$FAKE_RESTART_SLEEP"
      cat "$FAKE_RECEIPT"
      exit "${FAKE_RESTART_RC:-0}"
    fi
    exit 0
    """
)
_FAKE_SYSTEMD_RUN = ('#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$FAKE_LOG.systemd-run"\n'
                     'if [ -n "${FAKE_LAUNCH_SLEEP:-}" ]; then sleep "$FAKE_LAUNCH_SLEEP"; '
                     'echo done > "$FAKE_LOG.launch-done"; fi\n')
_FAKE_SYSTEMCTL = '#!/usr/bin/env bash\necho "$*" >> "$FAKE_LOG.systemctl"\nif [ "$2" = "is-active" ]; then [ -n "${FAKE_ACTIVE_SLEEP:-}" ] && sleep "$FAKE_ACTIVE_SLEEP"; exit "${FAKE_ACTIVE_RC:-0}"; fi\n[ -n "${FAKE_SYSTEMCTL_SLEEP:-}" ] && sleep "$FAKE_SYSTEMCTL_SLEEP"\nexit "${FAKE_SYSTEMCTL_RC:-0}"\n'


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
        for name, body in (("self-learn", _FAKE_SELF_LEARN), ("systemd-run", _FAKE_SYSTEMD_RUN),
                           ("systemctl", _FAKE_SYSTEMCTL)):
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
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
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

    def side(self, suffix: str) -> list[str]:
        path = Path(f"{self.log}.{suffix}")
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []



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
    for icon in [*icons, ICON_DIR.parent / "self-learn-ui.svg"]:
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
    `systemd-run --user --scope --collect --quiet -- self-learn-ui-open --page /inbox`
    (the fake `systemd-run` logs its argv). `--scope`: a transient service
    kills the browser the launcher leaves behind when the launcher exits.
    Mutation: any other argv -> red."""
    out = env.pure("activate")
    assert out["rc"] == 0
    argv = (env.tmp / "calls.log.systemd-run").read_text(encoding="utf-8").splitlines()
    assert argv == ["--user", "--scope", "--collect", "--quiet", "--", "self-learn-ui-open", "--page", "/inbox"]
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
    result["props"] = {k: props[k] for k in ("Id", "Category", "Status", "IconName", "IconThemePath", "ToolTip",
                                             "Menu")}

    # The right-click menu (dbusmenu) at the path the item names.
    menu_path = props["Menu"]
    layout = client.call_sync(service, menu_path, "com.canonical.dbusmenu", "GetLayout",
                              GLib.Variant("(iias)", (0, -1, [])), None, Gio.DBusCallFlags.NONE, 5000, None).unpack()
    result["menu_revision"] = layout[0]
    result["menu_root"] = layout[1][1]
    result["menu"] = [[kid[0], kid[1].get("type", "standard"), kid[1].get("label"), kid[1].get("enabled")]
                      for kid in layout[1][2]]
    menu_ids = {label: mid for mid, _t, label, _e in result["menu"]}
    result["menu_version"] = client.call_sync(
        service, menu_path, "org.freedesktop.DBus.Properties", "Get",
        GLib.Variant("(ss)", ("com.canonical.dbusmenu", "Version")), None, Gio.DBusCallFlags.NONE, 5000,
        None).unpack()[0]
    # A click on the greyed-out state line does nothing; "Check now" polls.
    before = polls()
    status_id = result["menu"][0][0]
    client.call_sync(service, menu_path, "com.canonical.dbusmenu", "Event",
                     GLib.Variant("(isvu)", (status_id, "clicked", GLib.Variant("i", 0), 0)), None,
                     Gio.DBusCallFlags.NONE, 5000, None)
    wait(lambda: False, 0.1)
    result["status_click_polled"] = polls() > before
    client.call_sync(service, menu_path, "com.canonical.dbusmenu", "Event",
                     GLib.Variant("(isvu)", (menu_ids["Check now"], "clicked", GLib.Variant("i", 0), 0)), None,
                     Gio.DBusCallFlags.NONE, 5000, None)
    result["check_now_polled"] = wait(lambda: polls() > before, 10)
    try:
        client.call_sync(service, menu_path, "com.canonical.dbusmenu", "EventGroup",
                         GLib.Variant("(a(isvu))", ([(99, "clicked", GLib.Variant("i", 0), 0)],)), None,
                         Gio.DBusCallFlags.NONE, 5000, None)
        result["all_invalid_error"] = False
    except GLib.Error:
        result["all_invalid_error"] = True
    result["about_to_show"] = client.call_sync(service, menu_path, "com.canonical.dbusmenu", "AboutToShow",
                                               GLib.Variant("(i)", (0,)), None, Gio.DBusCallFlags.NONE, 5000,
                                               None).unpack()[0]

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
    # Separate run: a fast periodic timer must not mask broken file monitors
    # in the preceding run, which retains the production 120-second interval.
    proc.terminate()
    result["first_tray_rc"] = proc.wait(10)
    w2.close()
    before = polls()
    proc = subprocess.Popen([sys.executable, "-I", tray, "--poll-secs", "1"],
                            stderr=open(out_path + ".stderr", "a"))
    result["periodic_first_poll"] = wait(lambda: polls() > before, 5)
    before = polls()
    result["periodic_without_file_change"] = wait(lambda: polls() > before, 3)
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
    assert run.returncode == 0, (run.stdout, run.stderr)
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

    # 09 §2.6: the right-click menu, served as com.canonical.dbusmenu at the item's Menu path.
    assert props["Menu"] == "/MenuBar"
    assert res["menu_version"] == 3 and res["menu_root"] == {"children-display": "submenu"}
    labels = [label for _id, kind, label, _e in res["menu"] if kind != "separator"]
    assert labels == ["self-learn: 0 need you & <none> new", "Open the inbox", "Open self-learn", "Check now",
                      "Mark everything decided as seen", "Restart the web UI", "Restart the background service",
                      "Quit (hide this icon until next login)"], res["menu"]
    assert res["menu"][0][3] is False, "the state line is greyed out"
    assert not res["status_click_polled"], "a click on the state line does nothing"
    assert res["check_now_polled"], ("Check now over the bus polls", tray_log)
    assert res["all_invalid_error"]
    assert res["periodic_first_poll"]
    assert res["periodic_without_file_change"]
    assert res["first_tray_rc"] == 0
    assert res["about_to_show"] is False, "an unchanged menu needs no update"

    assert res["activated"] == ["--user", "--scope", "--collect", "--quiet", "--", "self-learn-ui-open", "--page", "/inbox"]
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


# ------------------------------------------------------------------ 7


def test_7_menu_lists_the_state_then_the_controls(env):
    """09 §2.6: the right-click menu's first line is the tooltip's own text,
    greyed out, then open, check, seen, the two restarts and quit, with
    separators between the groups. Mutation: drop an item, or enable the state
    line -> red."""
    env.write(_attention("needs-you", "self-learn: 1 needs you", [_item(**{"class": "needs-you"})], env.cache))
    out = env.pure("menu")
    menu = out["menu"]
    assert [m["type"] for m in menu] == ["standard", "separator", "standard", "standard", "separator",
                                         "standard", "standard", "separator", "standard", "standard",
                                         "separator", "standard"]
    standard = [m for m in menu if m["type"] == "standard"]
    assert [(m["key"], m["label"], m["enabled"]) for m in standard] == [
        ("status", "self-learn: 1 needs you", False),
        ("open-inbox", "Open the inbox", True),
        ("open", "Open self-learn", True),
        ("check", "Check now", True),
        ("seen", "Mark everything decided as seen", True),
        ("restart-ui", "Restart the web UI", True),
        ("restart-host", "Restart the background service", True),
        ("quit", "Quit (hide this icon until next login)", True),
    ]
    assert len({m["id"] for m in menu}) == len(menu) and 0 not in {m["id"] for m in menu}


@pytest.mark.parametrize(("item", "side", "argv"), [
    ("open-inbox", "systemd-run",
     ["--user", "--scope", "--collect", "--quiet", "--", "self-learn-ui-open", "--page", "/inbox"]),
    ("open", "systemd-run", ["--user", "--scope", "--collect", "--quiet", "--", "self-learn-ui-open"]),
    ("restart-ui", "systemctl", ["--user restart self-learn-ui.service"]),
    ("quit", "systemctl", ["--user --no-block stop self-learn-tray.service"]),
])
def test_7b_each_menu_item_runs_exactly_its_command(env, item, side, argv):
    """09 §2.6: each item's exact command (the fakes log their argv). Quit
    stops the unit with `--no-block`, since a plain exit comes back in 5 s
    (Restart=always) and systemd stops the tray itself. Mutation: any other
    argv, or quit by exiting -> red."""
    out = env.pure("click", "--item", item)
    assert out["rc"] == 0
    assert env.side(side) == argv
    other = {"systemd-run": "systemctl", "systemctl": "systemd-run"}[side]
    assert env.side(other) == [], "one command per item"
    assert env.calls() == ["attention --json"], "only the pure step's own first poll runs `self-learn`"


def test_7c_check_now_polls_and_seen_marks_then_polls(env):
    """"Check now" polls; "Mark everything decided as seen" is the middle
    click. Mutation: either item does nothing -> red."""
    env.pure("click", "--item", "check")
    assert env.calls() == ["attention --json", "attention --json"]
    env.log.unlink()
    env.pure("click", "--item", "seen")
    assert env.calls() == ["attention --json", "attention seen --all-decided", "attention --json"]


def test_7d_restart_notifies_and_reports_a_failure(env):
    """A restart says it happened, or that it failed with systemctl's exit.
    Mutation: drop either notification -> red."""
    out = env.pure("click", "--item", "restart-ui")
    assert out["notices"] == [["self-learn: the web UI restarted", ""]]
    out = env.pure("click", "--item", "restart-ui", FAKE_SYSTEMCTL_RC="5")
    assert out["rc"] == 5
    assert out["notices"][0][0] == "self-learn: could not restart the web UI"
    assert "exited 5" in out["notices"][0][1]


def test_7e_background_restart_waits_for_correlated_result(env):
    env.cache.mkdir(parents=True)
    result = env.cache / "serve.restart-result"
    receipt = env.tmp / "receipt.json"
    receipt.write_text(json.dumps({"requested": True, "id": "fixture", "result_path": str(result)}))
    during_wait = []
    def finish():
        time.sleep(2.5)
        during_wait.extend(env.side("systemctl"))
        result.write_text(json.dumps({"id": "fixture", "status": "restarted", "error": None, "at": time.time()}))
    ender = threading.Thread(target=finish)
    ender.start()
    try:
        out = env.pure("click", "--item", "restart-host", "--wait-secs", "1", FAKE_RECEIPT=str(receipt))
    finally:
        ender.join()
    assert during_wait == ["--user is-active --quiet self-learn-host.service"]
    assert env.side("systemctl") == during_wait
    assert env.calls() == ["attention --json", "serve --restart"]
    assert out["rc"] == 0
    assert "between jobs" in out["notices"][0][1]
    assert out["notices"][-1] == ["self-learn: the background service restarted", ""]
    assert any(m[9]["label"] == "Restarting the background service…" and not m[9]["enabled"] for m in out["menus"])
    assert out["menu"][9]["enabled"]


@pytest.mark.parametrize("active_rc", ["1", "3", "4", "127"])
def test_7f_inactive_service_uses_systemctl(env, active_rc):
    out = env.pure("click", "--item", "restart-host", FAKE_ACTIVE_RC=active_rc)
    assert out["rc"] == 0
    assert env.side("systemctl") == ["--user is-active --quiet self-learn-host.service",
                                     "--user start self-learn-host.service"]
    assert env.calls() == ["attention --json"]
    assert out["notices"] == [["self-learn: the background service started", ""]]
    failed = env.pure("click", "--item", "restart-host", FAKE_ACTIVE_RC=active_rc, FAKE_SYSTEMCTL_RC="5")
    assert failed["rc"] == 5 and failed["menu"][9]["enabled"]
    assert failed["notices"] == [["self-learn: could not start the background service",
                                  "systemctl exited 5; see its journal."]]


_MENU_DRIVER = r'''
import json, math, os, runpy, sys, time
from pathlib import Path
m = runpy.run_path(sys.argv[1])
Gio, GLib = m["Gio"], m["GLib"]
ctx = GLib.MainContext.default()
def wait(cond, secs=2):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        while ctx.pending(): ctx.iteration(False)
        if cond(): return True
        time.sleep(.005)
    return bool(cond())
def connect():
    return Gio.DBusConnection.new_for_address_sync(os.environ["DBUS_SESSION_BUS_ADDRESS"],
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
server, client = connect(), connect()
tray = m["Tray"]()
menu = m["MenuServer"](tray)
menu.attach(server)
signals = []
client.signal_subscribe(server.get_unique_name(), m["MENU_IFACE"], "LayoutUpdated", m["MENU_PATH"],
    None, Gio.DBusSignalFlags.NONE, lambda *args: signals.append(args[-1].unpack()))
def call(method, sig, args, error=False):
    reply = []
    def done(conn, res):
        try: reply.append(conn.call_finish(res).unpack())
        except GLib.Error as exc: reply.append(exc)
    client.call(server.get_unique_name(), m["MENU_PATH"], m["MENU_IFACE"], method,
                GLib.Variant(sig, args), None, Gio.DBusCallFlags.NONE, 1000, None, done)
    assert wait(lambda: reply), method
    if error:
        assert isinstance(reply[0], GLib.Error), (method, reply)
        assert "UnknownId" in str(reply[0]) or "UnknownProperty" in str(reply[0])
    else:
        assert not isinstance(reply[0], GLib.Error), (method, reply)
    return reply[0]
def event(mid, kind="clicked"):
    return call("Event", "(isvu)", (mid, kind, GLib.Variant("i", 0), 0))

menu.refresh()
assert wait(lambda: len(signals) == 1), signals
initial = call("GetLayout", "(iias)", (0, -1, []))
assert len(initial[1][2]) == 12
assert call("GetLayout", "(iias)", (0, 0, []))[1][2] == []
assert call("GetProperty", "(is)", (0, "children-display")) == ("submenu",)
assert call("GetProperty", "(is)", (9, "label")) == ("Restart the web UI",)
assert call("GetProperty", "(is)", (1, "enabled")) == (False,)
call("GetProperty", "(is)", (99, "label"), error=True)
assert call("GetGroupProperties", "(aias)", ([9, 99], ["label"])) == ([(9, {"label": "Restart the web UI"})],)
assert len(call("GetGroupProperties", "(aias)", ([], []))[0]) == 13
assert call("GetLayout", "(iias)", (9, 0, ["enabled"]))[1] == (9, {"enabled": True}, [])
assert call("AboutToShow", "(i)", (0,)) == (False,)
# Partial/full reads cannot consume an unpublished change.
tray.result["tooltip"] = "changed_state"
assert call("GetLayout", "(iias)", (1, 0, ["label"]))[1][1] == {"label": "changed__state"}
call("GetLayout", "(iias)", (0, -1, []))
assert call("AboutToShow", "(i)", (0,)) == (True,)
assert wait(lambda: len(signals) == 2), signals
updated = call("GetLayout", "(iias)", (0, -1, []))
assert updated[0] == initial[0] + 1 and signals[-1] == (updated[0], 0)
assert call("AboutToShow", "(i)", (0,)) == (False,)
call("AboutToShow", "(i)", (99,), error=True)
call("AboutToShowGroup", "(ai)", ([99],), error=True)
call("EventGroup", "(a(isvu))", ([(99, "clicked", GLib.Variant("i", 0), 0)],), error=True)
assert call("EventGroup", "(a(isvu))", ([(0, "opened", GLib.Variant("i", 0), 0),
    (99, "clicked", GLib.Variant("i", 0), 0)],)) == ([99],)
assert call("AboutToShowGroup", "(ai)", ([0, 99],)) == ([], [99])
tray.result["tooltip"] = "another state"
assert call("AboutToShowGroup", "(ai)", ([1, 99],)) == ([1], [99])
assert call("AboutToShowGroup", "(ai)", ([0, 1, 99],)) == ([], [99])

# Controlled subprocess callbacks: actual menu events, no executable runs.
g = m["Tray"].click.__globals__
assert all(m["command_timed_out"](rc) for rc in (124, 137, -9, -15))
assert not any(m["command_timed_out"](rc) for rc in (0, 1, 3, 127))
for argv, seconds in ((m["HOST_ACTIVE_ARGV"], 15), (m["RESTART_REQUEST_ARGV"], 30),
                      (m["START_HOST_ARGV"], 120), (m["RESTART_UI_ARGV"], 120)):
    assert m["control_argv"](argv) == ["timeout", "--kill-after=5", str(seconds), *argv]
spawned, captured, timers, notices, finished = [], [], [], [], []
g["spawn"] = lambda argv, done=None: spawned.append((argv, done))
g["capture"] = lambda argv, done: captured.append((argv, done))
tray.notify = lambda *args: notices.append(args)
tray.on_change = menu.refresh
original_timer = GLib.timeout_add_seconds
GLib.timeout_add_seconds = lambda secs, cb: timers.append(cb)
for kind in ("hovered", "opened", "closed"):
    event(9, kind)
assert spawned == [], spawned
for mid, key, argv in ((9, "restart-ui", m["RESTART_UI_ARGV"]), (10, "restart-host", m["HOST_ACTIVE_ARGV"])):
    start = len(spawned)
    event(mid)
    tray.click(key)  # guard also protects direct callers
    event(mid)
    assert len(spawned) == start + 1 and spawned[-1][0] == argv
    assert call("GetProperty", "(is)", (mid, "enabled")) == (False,)
    assert call("GetProperty", "(is)", (mid, "label"))[0].startswith("Restarting the ")
    spawned[-1][1](0 if mid == 9 else 3)
    if mid == 10:
        assert spawned[-1][0] == m["START_HOST_ARGV"]
        before = len(spawned)
        event(mid)
        tray.click(key)
        assert len(spawned) == before
        spawned[-1][1](0)
    assert call("GetProperty", "(is)", (mid, "enabled")) == (True,)

# Active-service request remains pending through command exit AND result watch.
tray.click("restart-host", lambda rc: finished.append(rc))
spawned[-1][1](0)
assert captured[-1][0] == ["self-learn", "serve", "--restart"]
result_path = Path(os.environ["XDG_CACHE_HOME"]) / "serve.restart-result"
result_path.parent.mkdir(parents=True, exist_ok=True)
receipt = {"requested": True, "id": "fixture", "result_path": str(result_path)}
captured[-1][1](0, json.dumps(receipt), "")
assert "between jobs" in notices[-1][1]
check = timers[-1]
assert check() is True  # missing result
before = len(spawned)
event(10)
tray.click("restart-host")
assert len(spawned) == before and not finished
base = {"id": "fixture", "status": "restarted", "error": None, "at": time.time()}
result_path.write_text(json.dumps({**base, "status": "restarting"}))
assert check() is True and not finished and "restart-host" in tray.restarting
invalid = [[], {**base, "id": "older"}, {**base, "status": []}, {**base, "error": 3},
    {**base, "status": "refused"}, *[{**base, "at": v} for v in (float("nan"), float("inf"), True, "1", None, 10**400)]]
for data in invalid:
    result_path.write_text(json.dumps(data))
    assert check() is True and not finished, data
result_path.write_bytes(b"\xff")
assert check() is True
result_path.write_text(json.dumps({**base, "status": "refused", "error": "fixture import failure"}))
assert check() is False and finished == [1]
assert notices[-1][1] == "fixture import failure"
assert "restart-host" not in tray.restarting
# Deadline leaves the request intact and releases the pending item.
tray.click("restart-host")
spawned[-1][1](0)
captured[-1][1](0, json.dumps({**receipt, "id": "next"}), "")
old_monotonic = g["time"].monotonic
now = old_monotonic()
g["time"].monotonic = lambda: now + 10801
assert timers[-1]() is False
assert "not been cancelled" in notices[-1][1] and "restart-host" not in tray.restarting
g["time"].monotonic = old_monotonic
# Receipt and command failures release pending state too.
for rc, text in [(2, ""), (0, "{}"), (0, json.dumps({**receipt, "id": 3})),
                 (0, json.dumps({**receipt, "requested": 1})),
                 (0, json.dumps({**receipt, "result_path": "relative"}))]:
    tray.click("restart-host")
    spawned[-1][1](0)
    captured[-1][1](rc, text, "fixture command error")
    assert "restart-host" not in tray.restarting
    assert "could not request" in notices[-1][0]
GLib.timeout_add_seconds = original_timer

# Real Notify calls to a daemon fixture, then a missing daemon on the same private bus.
notify_conn = connect()
notify_conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
    GLib.Variant("(su)", (m["NOTIFY"], 0)), None, Gio.DBusCallFlags.NONE, 1000, None)
xml = ''' + '"""' + r'''<node><interface name="org.freedesktop.Notifications"><method name="Notify">
<arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
<arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/>
</method></interface></node>''' + '"""' + r'''
received = []
def notify_call(conn, sender, path, iface, method, params, inv):
    received.append(params.unpack())
    inv.return_value(GLib.Variant("(u)", (1,)))
notify_conn.register_object("/org/freedesktop/Notifications", Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0], notify_call, None, None)
sni = m["SniItem"].__new__(m["SniItem"])
sni.conn = server
tray.notify = sni.notify
tray.click("restart-ui")
spawned[-1][1](0)
assert wait(lambda: received)
assert received[-1][3:5] == ("self-learn: the web UI restarted", "")
notify_conn.close_sync(None)
logs = []
g["log"] = logs.append
tray.click("restart-ui")
spawned[-1][1](5)
assert wait(lambda: any("could not show a notification" in line for line in logs)), logs
assert "restart-ui" not in tray.restarting
assert call("GetProperty", "(is)", (9, "enabled")) == (True,)
print("menu protocol, pending restarts, validation, and notification transport verified")
'''


def test_8_menu_protocol_pending_restarts_and_notification_transport(env):
    """Private exported object; controlled command completions; actual Notify transport."""
    driver = env.tmp / "menu-driver"
    driver.write_text(_MENU_DRIVER)
    # No service activation directories: absence cannot launch a desktop daemon.
    config = env.tmp / "private-bus.conf"
    config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen>'
                     '<policy context="default"><allow send_destination="*"/>'
                     '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
    res = subprocess.run([shutil.which("dbus-run-session"), f"--config-file={config}",
                          f"--dbus-daemon={shutil.which('dbus-daemon')}", "--", SYSTEM_PYTHON, "-I",
                          str(driver), str(TRAY)], env=env.env(), capture_output=True, text=True, timeout=40)
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert "notification transport verified" in res.stdout


@pytest.mark.parametrize(("item", "extra", "notice"), [
    ("restart-host", {"FAKE_ACTIVE_SLEEP": "1"}, "no start or restart was requested"),
    ("restart-host", {"FAKE_RESTART_SLEEP": "1"}, "not known whether the request was recorded; the service may still restart"),
    ("restart-host", {"FAKE_ACTIVE_RC": "3", "FAKE_SYSTEMCTL_SLEEP": "1"}, "operation may still complete"),
    ("restart-ui", {"FAKE_SYSTEMCTL_SLEEP": "1"}, "operation may still complete"),
])
def test_9_each_control_command_timeout_releases_item(env, item, extra, notice):
    """Run sleeping command fixtures through real timeout, never signal a host."""
    started = time.monotonic()
    out = env.pure("click", "--item", item, "--control-timeout-secs", "0.1", **extra)
    assert time.monotonic() - started < .9
    assert out["rc"] in (124, 137) or out["rc"] < 0
    row = next(row for row in out["menu"] if row["key"] == item)
    assert row["enabled"]
    assert notice in out["notices"][-1][1]
    if "FAKE_ACTIVE_SLEEP" in extra:
        assert env.side("systemctl") == ["--user is-active --quiet self-learn-host.service"]
        assert "serve --restart" not in env.calls()


@pytest.mark.parametrize("item", ["open-inbox", "open"])
def test_9_launchers_are_never_bounded_by_the_control_timeout(env, item):
    """GNU timeout signals its whole process group on expiry, and a browser the
    launcher starts stays in that group, so a bounded launcher that ran long
    could close the browser it had just opened. The launchers run unbounded
    (review r2-verify (a)). Mutation: wrap them in `timeout` -> the slow fake
    launcher is killed before it finishes -> red."""
    out = env.pure("click", "--item", item, "--control-timeout-secs", "0.3", FAKE_LAUNCH_SLEEP="1")
    assert out["rc"] == 0
    assert env.side("launch-done") == ["done"], "the launcher was killed by the control timeout"


def _waiting_receipt(env):
    env.cache.mkdir(parents=True, exist_ok=True)
    receipt = env.tmp / "receipt.json"
    receipt.write_text(json.dumps({"requested": True, "id": "fixture",
                                   "result_path": str(env.cache / "never-written.json")}))
    return receipt


def test_10_force_restart_is_offered_only_while_a_restart_waits(env):
    """09 §2.6 (S-143): "Force restart now (stops the running job)" is listed
    only while a background restart request waits for the service to be between
    jobs; a click runs the plain systemd restart, which ends the wait. Mutations:
    list it always -> red (test 7's exact list); never list it -> red here;
    leave the wait running after a successful force -> red (rc/menus)."""
    receipt = _waiting_receipt(env)
    assert "force-restart-host" not in [m["key"] for m in env.pure("menu")["menu"]]
    out = env.pure("click", "--item", "restart-host", "--then", "force-restart-host", "--then-after", "1.5",
                   "--wait-secs", "1", FAKE_RECEIPT=str(receipt))
    force = [m for m in out["then_menu"] if m["key"] == "force-restart-host"]
    assert force == [{"id": 13, "key": "force-restart-host", "type": "standard",
                      "label": "Force restart now (stops the running job)", "enabled": True}]
    assert [m["key"] for m in out["then_menu"]].index("force-restart-host") == \
        [m["key"] for m in out["then_menu"]].index("restart-host") + 1
    assert env.side("systemctl") == ["--user is-active --quiet self-learn-host.service",
                                     "--user restart self-learn-host.service"]
    assert out["rc"] == 0 and out["then_rc"] == 0, out
    assert out["notices"][-1] == ["self-learn: the background service restarted", ""]
    assert any(m["key"] == "force-restart-host" and not m["enabled"]
               and m["label"] == "Force restarting the background service…"
               for menu in out["menus"] for m in menu)
    final = {m["key"]: m for m in out["menus"][-1]}
    assert "force-restart-host" not in final and final["restart-host"]["enabled"]


def test_10b_a_failed_force_restart_keeps_the_request_waiting(env):
    """When the systemd restart fails, the original request keeps waiting and the
    force item comes back. Mutation: end the wait on failure -> red."""
    receipt = _waiting_receipt(env)
    out = env.pure("click", "--item", "restart-host", "--then", "force-restart-host", "--then-after", "1.5",
                   "--wait-secs", "1", "--timeout-secs", "1", FAKE_RECEIPT=str(receipt), FAKE_SYSTEMCTL_RC="5")
    assert out.get("then_rc") == 5, out
    assert "rc" not in out, "the waiting restart must not have ended"
    assert any(n[0] == "self-learn: could not restart the background service" for n in out["notices"])
    last = {m["key"]: m for m in out["menus"][-1]}
    assert last["force-restart-host"]["enabled"] and not last["restart-host"]["enabled"]
