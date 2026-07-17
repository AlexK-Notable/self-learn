"""Capped logging to ``<cache>/ui.log`` (10 §1's "Server transient state" row).

``<cache>`` is the doc-13 home-namespaced cache dir
(``${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(resolved
SELF_LEARN_HOME)[:8]>/``). **Decision (resolved at U1, per the task
brief): IMPORT, never shell or reimplement.** The CLI package
(``plugins/self-learn/cli``) already owns this derivation as
``self_learn.worker.cache_dir()`` (verified: it resolves
``SELF_LEARN_HOME`` via ``self_learn.ledger.resolve_home()``, namespaces
by the home's sha256, and creates the dir). The ui package declares
``self-learn-cli`` as an editable path dependency in ``pyproject.toml``
(``[tool.uv.sources]``) specifically for this import — the same
one-computation rule 10 §1 cites (P2-4): a second reimplementation would
drift the moment the CLI's cache layout changes (it already has once,
per the doc-13 migration shim in ``worker.py``).

Truncation mirrors ``worker.log``'s cap exactly (same constant, same
"keep the newest bytes" algorithm) so operators reading either log get
consistent behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from self_learn.worker import cache_dir

#: Same cap as worker.log (worker.py's LOG_CAP_BYTES) — kept as its own
#: constant rather than imported so this module never breaks if the CLI
#: renames/removes its private cap constant; the VALUE is what's shared.
UI_LOG_CAP_BYTES = 1_000_000

UI_LOG_NAME = "ui.log"


def ui_log_path() -> Path:
    """The resolved path of the ui log, inside the CLI's own cache dir."""
    return cache_dir() / UI_LOG_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate_oldest(path: Path, cap: int) -> None:
    try:
        if path.stat().st_size <= cap:
            return
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        keep: list[str] = []
        size = 0
        for line in reversed(lines):
            size += len(line.encode("utf-8"))
            if size > cap:
                break
            keep.append(line)
        path.write_text("".join(reversed(keep)), encoding="utf-8")
    except OSError:
        pass


def log(message: str) -> None:
    """Append one timestamped line to ``<cache>/ui.log`` (capped ~1 MB).

    A log write failure is never fatal to the caller (same posture as
    ``self_learn.worker.log``) — logging must not be able to take the
    server down.
    """
    path = ui_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{_now_iso()} {message}\n")
    except OSError:
        return
    _truncate_oldest(path, UI_LOG_CAP_BYTES)
