"""Parity plan 1.11 and row 7N: the login-hold popup on Windows.

On Windows `overseer.notify.send` runs `self_learn.notify_desktop` under
`pythonw.exe` through the process facade; the helper shows one toast whose
click opens the UI's inbox through protocol activation, and exits. These
tests prove, on GitHub's Windows runner:

- the sender's Windows branch passes the expected argument list, as a list,
  to `procs.run_bounded` with the caller's bound, and never raises;
- its launcher is a GUI-subsystem program (no console window);
- the real helper exits 0 within the bound, writes nothing to standard
  output or error, and logs exactly one line, with and without the
  `desktop` extra (the CI step runs this file once in each environment and
  says which in `SELF_LEARN_NOTIFY_TEST_EXTRA`);
- hostile title and body text crosses the Windows command line verbatim
  and is data, never an option; an `--open` value that is not http or https
  on `127.0.0.1` is refused.

The runner has no person at its desktop: whether a toast becomes visible
and whether a click opens the browser is for the tester checklist in the
builder's report. The argument and text contracts run on Linux too.
"""

from __future__ import annotations

import importlib.util
import json
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from xml.etree.ElementTree import fromstring

import pytest

from self_learn import notify_desktop, worker
from self_learn.overseer import notify
from self_learn.primitives import names, procs

windows = pytest.mark.skipif(os.name != "nt", reason="native Windows notification contract")
linux = pytest.mark.skipif(os.name == "nt", reason="Linux notification contract")

EXTRA_VAR = "SELF_LEARN_NOTIFY_TEST_EXTRA"
UI = "http://127.0.0.1:7357/inbox"

HOSTILE = {
    "leading-dashes": "--open file:///C:/Windows/System32/calc.exe",
    "title-flag": "--title",
    "quotes": 'say "hi" \\" \\\\" \'there\'',
    "newlines": "line one\nline two\r\nline three",
    "non-ascii": "Grüße — 日本語 — emoji \U0001F600",
    "markup": "<toast launch='https://example.com'>&amp;</toast>",
    "trailing-backslash": "C:\\path\\",
}


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    home = tmp_path / "ledger"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("SELF_LEARN_UI_PORT", raising=False)
    return home


def _log_lines() -> list[str]:
    path = notify_desktop.log_path()
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


# --- argument and text contracts (both platforms) -------------------------


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_title_and_body_values_are_taken_verbatim(name):
    text = HOSTILE[name]
    parsed = notify_desktop.parse_args(["--title", text, "--body", text, "--open", UI])
    assert parsed == {"title": text, "body": text, "open": UI}


@pytest.mark.parametrize(
    "argv",
    [
        ["--title", "t"],
        ["--body", "b"],
        ["--title", "t", "--body"],
        ["--title", "t", "--body", "b", "--title", "u"],
        ["--title=t", "--body", "b"],
        ["--titl", "t", "--body", "b"],
        ["--title", "t", "--body", "b", "extra"],
        ["-h"],
        [],
    ],
    ids=["no-body", "no-title", "missing-value", "repeat", "equals-form", "abbreviation",
         "stray", "help", "empty"],
)
def test_malformed_arguments_are_refused(argv):
    with pytest.raises(notify_desktop.Refused):
        notify_desktop.parse_args(argv)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:7357/inbox", "https://127.0.0.1:7357/inbox/att-1?x=1", "http://127.0.0.1/"],
)
def test_ui_loopback_urls_are_accepted(url):
    assert notify_desktop.check_open(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/System32/calc.exe",
        "ms-settings:privacy",
        "javascript:alert(1)",
        "C:\\Windows\\notepad.exe",
        "https://example.com/inbox",
        "http://localhost:7357/inbox",
        "http://[::1]:7357/inbox",
        "http://127.0.0.1.example.com/inbox",
        "http://user@127.0.0.1:7357/inbox",
        "http://127.0.0.1:99999/inbox",
        "http://127.0.0.1:7357/in box",
        "http://127.0.0.1:7357/inbox\n",
        "http://127.0.0.1:7357/" + "x" * 3000,
    ],
    ids=["file", "ms-settings", "javascript", "path", "remote", "localhost", "ipv6",
         "suffix-host", "userinfo", "bad-port", "space", "newline", "long"],
)
def test_other_open_values_are_refused(url):
    with pytest.raises(notify_desktop.Refused):
        notify_desktop.check_open(url)


def test_clean_text_cuts_and_drops_what_xml_and_the_command_line_cannot_carry():
    dirty = "a\x00b\x01c\x1bd\ud800e\tf\ng\uffffh"
    assert notify_desktop.clean_text(dirty, 100) == "ab" + "cd" + "?e\tf\ngh"
    assert notify_desktop.clean_text("a\r\nb\rc", 100) == "a\nb\nc"
    long = notify_desktop.clean_text("y" * 5000, notify_desktop.BODY_LIMIT)
    assert len(long) == notify_desktop.BODY_LIMIT and long.endswith("\u2026")


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_toast_document_carries_text_as_text_and_opens_by_protocol(name):
    text = notify_desktop.clean_text(HOSTILE[name], notify_desktop.BODY_LIMIT)
    root = fromstring(notify_desktop.toast_xml(text, text, UI))
    assert root.tag == "toast"
    assert root.get("activationType") == "protocol" and root.get("launch") == UI
    texts = root.findall("./visual/binding/text")
    assert [element.text for element in texts] == [text, text]
    (action,) = root.findall("./actions/action")
    assert action.get("activationType") == "protocol" and action.get("arguments") == UI
    assert root.find("./visual/binding/toast") is None


def test_toast_without_open_has_no_activation():
    root = fromstring(notify_desktop.toast_xml("t", "b", None))
    assert root.get("activationType") is None and root.get("launch") is None
    assert root.find("actions") is None


def test_helper_argv_is_a_list_with_text_after_its_flag():
    argv = notify_desktop.helper_argv("C:/v/Scripts/pythonw.exe", title="--body",
                                      body=HOSTILE["leading-dashes"], url=UI)
    assert argv == ["C:/v/Scripts/pythonw.exe", "-I", "-m", "self_learn.notify_desktop",
                    "--title", "--body", "--body", HOSTILE["leading-dashes"], "--open", UI]
    assert notify_desktop.parse_args(argv[4:]) == {
        "title": "--body", "body": HOSTILE["leading-dashes"], "open": UI}


def test_ui_url_follows_the_ui_port_setting():
    assert notify_desktop.ui_url("/inbox", {}) == UI
    assert notify_desktop.ui_url("/inbox", {"SELF_LEARN_UI_PORT": "8123"}) == "http://127.0.0.1:8123/inbox"
    assert notify_desktop.ui_url("/inbox", {"SELF_LEARN_UI_PORT": "nope"}) == UI


def test_refused_open_shows_nothing_and_logs_one_line(scratch, monkeypatch):
    shown = []
    monkeypatch.setattr(notify_desktop, "_show", shown.append)
    status = notify_desktop.main(["--title", "t", "--body", "b", "--open", "file:///etc/passwd"])
    assert status == notify_desktop.EXIT_REFUSED
    assert shown == []
    (line,) = _log_lines()
    assert "notify: refused: --open is not an http or https URL" in line


def test_a_failure_inside_the_helper_never_leaves_it(scratch, monkeypatch):
    def explode(document):
        raise RuntimeError("WinRT went away")

    monkeypatch.setattr(notify_desktop, "_show", explode)
    assert notify_desktop.main(["--title", "t", "--body", "b"]) == notify_desktop.EXIT_OK
    (line,) = _log_lines()
    assert "notify: failed: RuntimeError" in line


def test_the_watchdog_ends_a_helper_that_hangs(scratch, monkeypatch):
    release = threading.Event()
    fired = []
    monkeypatch.setattr(notify_desktop, "DEADLINE_SECONDS", 0.3)
    monkeypatch.setattr(notify_desktop, "_show", lambda document: release.wait(5) and "shown")

    def expire():
        fired.append(time.monotonic())
        release.set()

    started = time.monotonic()
    notify_desktop.main(["--title", "t", "--body", "b"], expire=expire)
    assert fired and fired[0] - started < 2.0


@linux
def test_linux_send_keeps_the_companion_script(monkeypatch, tmp_path):
    """The Linux branch is the one it was: never the Windows helper."""
    calls = []
    monkeypatch.setattr(notify.worker, "_notifications_suppressed", lambda actual: False)
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/shim/self-learn-notify")
    monkeypatch.setattr(notify.subprocess, "Popen", lambda argv, **kwargs: calls.append(argv))

    def no_windows(line):
        raise AssertionError("the Windows helper ran on Linux")

    monkeypatch.setattr(notify, "_send_windows", no_windows)
    notify.send(tmp_path, "routine", "log in", ["run-1"], kind=notify.POPUP_KIND)
    assert calls == [["/shim/self-learn-notify", "--line", "log in", "--page", "/inbox"]]


# --- Windows -------------------------------------------------------------


def _extra_installed() -> bool:
    try:
        return importlib.util.find_spec("winrt.windows.ui.notifications") is not None
    except ModuleNotFoundError:
        return False


def _mode() -> str:
    mode = os.environ.get(EXTRA_VAR)
    assert mode in ("present", "absent"), f"{EXTRA_VAR} must say whether the desktop extra is installed"
    return mode


def _child_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["SELF_LEARN_HOME"] = str(home)
    env["XDG_CACHE_HOME"] = os.environ["XDG_CACHE_HOME"]
    return env


def _subsystem(path: Path) -> int:
    data = path.read_bytes()
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[offset:offset + 4] == b"PE\0\0"
    return struct.unpack_from("<H", data, offset + 4 + 20 + 68)[0]


@windows
def test_windows_extra_matches_the_step():
    assert _extra_installed() is (_mode() == "present")


@windows
def test_windows_sender_passes_the_helper_its_arguments_as_a_list(scratch, monkeypatch):
    calls = []
    monkeypatch.setattr(notify.worker, "_notifications_suppressed", lambda actual: False)
    monkeypatch.setattr(procs, "run_bounded", lambda argv, **kwargs: calls.append((argv, kwargs)))
    line = HOSTILE["leading-dashes"]
    notify.send(scratch, "routine", line, ["run-1"], kind=notify.POPUP_KIND)
    monkeypatch.setenv("SELF_LEARN_UI_PORT", "8123")
    notify.send(scratch, "routine", "log in", ["run-1"], kind=notify.POPUP_KIND)
    notify.send(scratch, "routine", "quiet", ["run-1"], kind="silent")
    launcher = str(Path(sys.executable).with_name("pythonw.exe"))
    assert calls == [
        ([launcher, "-I", "-m", "self_learn.notify_desktop", "--title", "self-learn",
          "--body", line, "--open", UI],
         {"timeout": notify_desktop.CALLER_TIMEOUT_SECONDS}),
        ([launcher, "-I", "-m", "self_learn.notify_desktop", "--title", "self-learn",
          "--body", "log in", "--open", "http://127.0.0.1:8123/inbox"],
         {"timeout": notify_desktop.CALLER_TIMEOUT_SECONDS}),
    ]


@windows
@pytest.mark.parametrize("failure", [OSError(5, "denied"), procs.BoundedTimeout(["x"], 10.0),
                                     RuntimeError("anything")], ids=["oserror", "timeout", "other"])
def test_windows_sender_never_raises_into_its_caller(scratch, monkeypatch, failure):
    logged = []
    monkeypatch.setattr(notify.worker, "_notifications_suppressed", lambda actual: False)
    monkeypatch.setattr(notify.worker, "log", logged.append)

    def fail(argv, **kwargs):
        raise failure

    monkeypatch.setattr(procs, "run_bounded", fail)
    notify.send(scratch, "routine", "log in", ["run-1"], kind=notify.POPUP_KIND)
    assert logged == [f"notify: the Windows notification helper failed ({type(failure).__name__})"]


@windows
def test_windows_launcher_is_a_gui_program():
    launcher = notify_desktop.pythonw_beside()
    assert launcher is not None and launcher.name.lower() == "pythonw.exe"
    assert _subsystem(launcher) == 2  # IMAGE_SUBSYSTEM_WINDOWS_GUI: no console
    assert _subsystem(Path(sys.executable)) == 3  # the control: python.exe is a console program


@windows
@pytest.mark.parametrize("program", ["pythonw.exe", "python.exe"])
def test_windows_helper_exits_quietly_within_the_bound(scratch, program):
    """python.exe makes any print or traceback visible; pythonw.exe is the
    launcher the sender uses."""
    launcher = str(Path(sys.executable).with_name(program))
    argv = notify_desktop.helper_argv(launcher, title="self-learn", body="the test is held", url=UI)
    started = time.monotonic()
    result = subprocess.run(argv, capture_output=True, timeout=notify_desktop.CALLER_TIMEOUT_SECONDS,
                            env=_child_env(scratch), stdin=subprocess.DEVNULL)
    elapsed = time.monotonic() - started
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
    assert elapsed < notify_desktop.DEADLINE_SECONDS + 2
    (line,) = _log_lines()
    if _mode() == "absent":
        assert line.endswith("notify: skipped: the desktop extra is not installed")
    else:
        assert line.endswith("notify: shown") or "notify: skipped: " in line
        assert "not installed" not in line
    print(f"{program}: {elapsed:.2f} s, {line}")


@windows
def test_windows_hostile_text_crosses_the_command_line_verbatim(scratch):
    """Through the production facade, `list2cmdline` and the child's own
    command-line parsing: the values arrive as sent, and the real helper
    takes them as data (it shows or skips; it never refuses them)."""
    values = [HOSTILE[name] for name in sorted(HOSTILE)]
    values += ["z" * 40000, "nul \x00 and escape \x1b inside"]
    echo = [sys.executable, "-I", "-c", "import sys, json; sys.stdout.write(json.dumps(sys.argv[1:]))"]
    for value in values:
        argv = notify_desktop.helper_argv(sys.executable, title=value, body=value, url=UI)
        expected = ["--title", notify_desktop.clean_text(value, notify_desktop.TITLE_LIMIT),
                    "--body", notify_desktop.clean_text(value, notify_desktop.BODY_LIMIT), "--open", UI]
        assert argv[4:] == expected
        seen = procs.run_bounded(echo + argv[4:], timeout=30, env=_child_env(scratch))
        assert json.loads(seen.stdout) == expected
    for value in values:
        argv = notify_desktop.helper_argv(sys.executable, title=value, body=value, url=UI)
        assert procs.run_bounded(argv, timeout=notify_desktop.CALLER_TIMEOUT_SECONDS,
                                 env=_child_env(scratch)).returncode == 0
    lines = _log_lines()
    assert len(lines) == len(values)
    assert not [line for line in lines if "refused" in line or "failed" in line]


@windows
def test_windows_refused_open_exits_2_and_logs(scratch):
    argv = [sys.executable, "-I", "-m", "self_learn.notify_desktop", "--title", "t",
            "--body", "b", "--open", "file:///C:/Windows/System32/calc.exe"]
    result = subprocess.run(argv, capture_output=True, timeout=notify_desktop.CALLER_TIMEOUT_SECONDS,
                            env=_child_env(scratch), stdin=subprocess.DEVNULL)
    assert (result.returncode, result.stdout, result.stderr) == (notify_desktop.EXIT_REFUSED, b"", b"")
    (line,) = _log_lines()
    assert "notify: refused: --open is not an http or https URL" in line


@windows
@pytest.mark.skipif(not _extra_installed(), reason="desktop extra not installed")
@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_windows_toast_document_loads_in_winrt(name):
    from winrt.windows.data.xml.dom import XmlDocument
    from winrt.windows.ui.notifications import ToastNotification

    text = notify_desktop.clean_text(HOSTILE[name], notify_desktop.BODY_LIMIT)
    document = XmlDocument()
    document.load_xml(notify_desktop.toast_xml(text, text, UI))
    texts = document.get_elements_by_tag_name("text")
    assert [node.inner_text for node in texts] == [text, text]
    ToastNotification(document)


def _run_helper(home: Path, body: str) -> tuple[subprocess.CompletedProcess, str]:
    argv = notify_desktop.helper_argv(sys.executable, title="self-learn", body=body, url=UI)
    result = subprocess.run(argv, capture_output=True, timeout=notify_desktop.CALLER_TIMEOUT_SECONDS,
                            env=_child_env(home), stdin=subprocess.DEVNULL)
    (line,) = _log_lines()
    return result, line


@windows
@pytest.mark.skipif(not _extra_installed(), reason="desktop extra not installed")
def test_windows_shown_toast_stays_in_action_center(scratch):
    """After the helper has exited, its toast is in this user's notification
    history under the registered identity, carrying the protocol launch
    (whether a person can see and click it is the tester checklist's)."""
    from winrt.windows.ui.notifications import ToastNotificationManager

    marker = f"history check {os.getpid()} {time.time_ns()}"
    result, line = _run_helper(scratch, marker)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
    assert line.endswith("notify: shown")
    history = ToastNotificationManager.history
    try:
        found = []
        deadline = time.monotonic() + 5
        while not found and time.monotonic() < deadline:
            found = [toast.content.get_xml() for toast in history.get_history(notify_desktop.AUMID)
                     if marker in toast.content.get_xml()]
            time.sleep(0.2)
        assert found, "the toast is not in the notification history"
        root = fromstring(found[0])
        assert root.get("activationType") == "protocol" and root.get("launch") == UI
    finally:
        history.clear(notify_desktop.AUMID)


@windows
@pytest.mark.skipif(not _extra_installed(), reason="desktop extra not installed")
@pytest.mark.parametrize(("setting", "shown"), [("DISABLED_FOR_APPLICATION", False),
                                                ("DISABLED_BY_GROUP_POLICY", False),
                                                ("unreadable", True)])
def test_windows_switched_off_notifications_are_logged(monkeypatch, setting, shown):
    """Notifications switched off for self-learn (or by policy): nothing is
    shown and the outcome says why. A setting that cannot be read is taken
    as on, as desktop-notifier does (its issue #95). The real WinRT module is
    loaded; only the notifier is a stand-in, because writing the Settings
    registry key on the runner did not change what WinRT reports."""
    import winrt.windows.ui.notifications as toasts

    calls = []

    class Notifier:
        @property
        def setting(self):
            if setting == "unreadable":
                raise OSError(-2147023728, "Element not found")
            return toasts.NotificationSetting[setting]

        def show(self, toast):
            calls.append(toast)

    class Manager:
        @staticmethod
        def create_toast_notifier(application_id):
            assert application_id == notify_desktop.AUMID
            return Notifier()

    monkeypatch.setattr(toasts, "ToastNotificationManager", Manager)
    outcome = notify_desktop._show(notify_desktop.toast_xml("t", "b", UI))
    if shown:
        assert (outcome, len(calls)) == ("shown", 1)
    else:
        assert (outcome, calls) == (f"skipped: notifications are off for this session ({setting})", [])
