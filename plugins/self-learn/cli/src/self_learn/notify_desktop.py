"""The Windows desktop notification helper (parity plan 1.11 and row 7N).

On Linux the one popup self-learn still shows (a login hold, attention
round answer 1) goes through the Bash companion script
``scripts/self-learn-notify`` and ``notify-send``. Windows has neither, so
on Windows ``overseer.notify.send`` runs this module instead, through
``pythonw.exe`` (a GUI-subsystem program, so no console window opens)::

    pythonw.exe -I -m self_learn.notify_desktop --title T --body B [--open URL]

It shows one Windows toast and exits. It never prints, never raises out of
:func:`main`, and logs exactly one line per run to ``notify.log`` in the
per-home cache folder (``names.home_cache()``). When the optional
``desktop`` extra (the PyWinRT packages) is not installed, or Windows has no
notification service for this session (a server, a CI runner, a session
without a desktop), it logs that one line and exits 0.

The click needs no running process. The toast's body uses protocol
activation (``activationType="protocol"``, ``launch=<URL>``), so Windows
itself opens the URL in the default browser when the toast is clicked, also
after this helper has exited. desktop-notifier, the library the plan named,
cannot do that: its toast element is fixed to ``launch="default"`` with
in-process event handlers, and its README says "a running event loop is
required to respond to user interactions with a notification". The extra
therefore installs the PyWinRT packages desktop-notifier itself builds on
and this module writes the toast XML directly.

Bound: a watchdog ends the process with exit 0 after
:data:`DEADLINE_SECONDS` whatever WinRT is doing, and the sender waits at
most :data:`CALLER_TIMEOUT_SECONDS` before the process facade kills it.

Arguments: each of ``--title``, ``--body`` and ``--open`` is given at most
once, as its own argument, and the argument after it is its value verbatim,
so a title or body that starts with ``--`` is data, never an option. Text is
cut to a fixed length and stripped of characters XML 1.0 cannot carry.
``--open`` is refused (exit 2, nothing shown) unless it is an http or https
URL on the UI's own loopback address ``127.0.0.1``.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

#: The application identity the toasts carry. Registered per user under
#: ``HKCU\\Software\\Classes\\AppUserModelId\\<AUMID>`` with a display name,
#: the way desktop-notifier registers an unpackaged app.
AUMID = "self-learn.notify"
DISPLAY_NAME = "self-learn"
AUMID_KEY = "Software\\Classes\\AppUserModelId\\" + AUMID

#: The helper ends itself after this many seconds, shown or not.
DEADLINE_SECONDS = 6.0
#: The sender's bound on the helper (``procs.run_bounded`` kills it after).
CALLER_TIMEOUT_SECONDS = 10.0

TITLE_LIMIT = 120
BODY_LIMIT = 1000
URL_LIMIT = 2048

LOG_NAME = "notify.log"
MODULE = "self_learn.notify_desktop"
OPEN_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 7357

EXIT_OK = 0
EXIT_REFUSED = 2

_FLAGS = ("--title", "--body", "--open")


class Refused(ValueError):
    """The arguments are not a well-formed request; nothing is shown."""


def parse_args(argv: Sequence[str]) -> dict[str, str]:
    """``{"title": ..., "body": ..., "open": ...}`` from *argv*.

    Each flag is its own argument and is followed by its value verbatim;
    no ``--flag=value`` form, no abbreviations, no repeats. ``--title`` and
    ``--body`` are required, ``--open`` is optional."""
    found: dict[str, str] = {}
    index = 0
    while index < len(argv):
        flag = argv[index]
        if flag not in _FLAGS:
            raise Refused(f"unknown argument at position {index}")
        name = flag[2:]
        if name in found:
            raise Refused(f"{flag} given twice")
        if index + 1 >= len(argv):
            raise Refused(f"{flag} needs a value")
        found[name] = argv[index + 1]
        index += 2
    for required in ("title", "body"):
        if required not in found:
            raise Refused(f"--{required} is required")
    return found


def _xml_char(char: str) -> bool:
    code = ord(char)
    return (
        code in (0x9, 0xA, 0xD)
        or 0x20 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
    )


def clean_text(text: str, limit: int) -> str:
    """*text* cut to *limit* characters, without lone surrogates or
    characters XML 1.0 cannot carry (NUL and most control characters), so
    it survives a Windows command line and the toast's XML parser (which
    would turn a carriage return into a line feed anyway)."""
    text = text.encode("utf-8", "replace").decode("utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    kept = "".join(char for char in text if _xml_char(char))
    if len(kept) > limit:
        kept = kept[: limit - 1] + "…"
    return kept


def check_open(url: str) -> str:
    """*url* when it is an http or https URL on ``127.0.0.1`` (the address
    the UI binds), else :class:`Refused`."""
    if len(url) > URL_LIMIT:
        raise Refused("--open is too long")
    if any(not char.isprintable() or char.isspace() for char in url):
        raise Refused("--open carries whitespace or control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise Refused("--open is not a valid URL") from exc
    if parts.scheme not in ("http", "https"):
        raise Refused("--open is not an http or https URL")
    if parts.username is not None or parts.password is not None:
        raise Refused("--open carries user information")
    if parts.netloc.rsplit(":", 1)[0] != OPEN_HOST:
        raise Refused("--open is not the UI's loopback address")
    if port is not None and not 1 <= port <= 65535:
        raise Refused("--open has an invalid port")
    return url


def ui_url(page: str, env: dict[str, str] | None = None) -> str:
    """The UI's URL for *page*: ``http://127.0.0.1:<port><page>``, the port
    from ``SELF_LEARN_UI_PORT`` (the UI's own setting) or 7357. The bearer
    token is never part of it: a toast's launch string is kept in the
    notification database and a token there would outlive its session."""
    env = dict(os.environ) if env is None else env
    raw = env.get("SELF_LEARN_UI_PORT", "")
    port = DEFAULT_UI_PORT
    if raw.isdigit() and 1 <= int(raw) <= 65535:
        port = int(raw)
    return f"http://{OPEN_HOST}:{port}{page}"


def toast_xml(title: str, body: str, url: str | None) -> str:
    """The toast document. With *url*, a click on the body opens it through
    protocol activation; Windows does that itself, no process needs to be
    running. ``duration="long"`` keeps the popup about 25 seconds."""
    attributes = {"duration": "long"}
    if url is not None:
        attributes.update({"activationType": "protocol", "launch": url})
    toast = Element("toast", attributes)
    visual = SubElement(toast, "visual")
    binding = SubElement(visual, "binding", {"template": "ToastGeneric"})
    SubElement(binding, "text").text = title
    SubElement(binding, "text").text = body
    if url is not None:
        actions = SubElement(toast, "actions")
        SubElement(actions, "action", {"content": "Open", "activationType": "protocol",
                                       "arguments": url})
    return tostring(toast, encoding="unicode")


def pythonw_beside(executable: str | None = None) -> Path | None:
    """``pythonw.exe`` in the folder of *executable* (default: this
    interpreter), or ``None`` when there is none. It is named by absolute
    path, so neither PATH nor the current folder decides which program runs."""
    base = Path(executable or sys.executable)
    candidate = base if base.name.lower() == "pythonw.exe" else base.with_name("pythonw.exe")
    return candidate if candidate.is_file() else None


def helper_argv(launcher: Path | str, *, title: str, body: str, url: str | None) -> list[str]:
    """The argument list the sender passes to the process facade, as a list,
    never through a shell. ``-I`` keeps the current folder and ``PYTHON*``
    variables out of the helper's imports."""
    argv = [str(launcher), "-I", "-m", MODULE,
            "--title", clean_text(title, TITLE_LIMIT),
            "--body", clean_text(body, BODY_LIMIT)]
    if url is not None:
        argv += ["--open", url]
    return argv


def log_path() -> Path:
    from .primitives import names

    return names.home_cache() / LOG_NAME


def _log(message: str) -> None:
    """One line in ``notify.log``; a log that cannot be written costs only
    the line (``worker._log_to`` is silent on ``OSError``)."""
    try:
        from . import worker

        worker._log_to(log_path(), "notify: " + message.replace("\n", " "))
    except Exception:
        return


def _register_identity() -> None:
    """Give :data:`AUMID` a display name for the current user, the same
    per-user key desktop-notifier writes for an unpackaged app."""
    if sys.platform != "win32":
        return
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, AUMID_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, DISPLAY_NAME)


def _show(document: str) -> str:
    """Show *document* as a toast; returns the outcome for the log line."""
    if sys.platform != "win32":
        return "skipped: not Windows"
    try:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import (
            NotificationSetting,
            ToastNotification,
            ToastNotificationManager,
        )
    except ImportError:
        return "skipped: the desktop extra is not installed"
    try:
        _register_identity()
        notifier = ToastNotificationManager.create_toast_notifier(AUMID)
        try:
            setting = notifier.setting
        except OSError:
            # desktop-notifier issue #95: some sessions cannot read the
            # setting yet show toasts; it treats this as allowed, so do we.
            setting = NotificationSetting.ENABLED
        if setting != NotificationSetting.ENABLED:
            return f"skipped: notifications are off for this session ({setting.name})"
        xml = XmlDocument()
        xml.load_xml(document)
        notifier.show(ToastNotification(xml))
    except Exception as exc:
        return f"skipped: no notification service ({type(exc).__name__}: {exc})"
    return "shown"


def _expire() -> None:
    _log(f"timed out after {DEADLINE_SECONDS:g} s")
    os._exit(EXIT_OK)


def main(argv: Sequence[str] | None = None, *,
         expire: Callable[[], None] | None = None) -> int:
    """Show one toast and return an exit status; never raises, never prints."""
    watchdog = threading.Timer(DEADLINE_SECONDS, expire or _expire)
    watchdog.daemon = True
    watchdog.start()
    try:
        try:
            request = parse_args(list(sys.argv[1:] if argv is None else argv))
            url = check_open(request["open"]) if "open" in request else None
        except Refused as exc:
            _log(f"refused: {exc}")
            return EXIT_REFUSED
        title = clean_text(request["title"], TITLE_LIMIT)
        body = clean_text(request["body"], BODY_LIMIT)
        _log(_show(toast_xml(title, body, url)))
        return EXIT_OK
    except BaseException as exc:  # never into the caller, never a traceback
        _log(f"failed: {type(exc).__name__}")
        return EXIT_OK
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    sys.exit(main())
