"""Environment parsing (09 §4.4 / 10 §1's "Env vars (complete)" row).

The complete list, verbatim: ``SELF_LEARN_HOME`` (existing, 08) ·
``SELF_LEARN_UI_PORT`` (default ``7357``) · ``SELF_LEARN_UI_BROWSER``
(launcher-only — consumed by ``self-learn-ui-open``, never read by the
server itself; kept here anyway so this module stays the single source of
the *complete* var list, per 10 §1) · ``SELF_LEARN_PANE_MODEL`` (default
``claude-sonnet-5``) · ``SELF_LEARN_PANE_BUDGET_USD`` (default ``1.00``) ·
``SELF_LEARN_PANE_MAX_TURNS`` (default ``15``) · ``SELF_LEARN_PANE_ENGINE``
(``sdk`` | ``cli``, default ``sdk``; ``cli`` is the specced-not-built
alternative, 09 §4.1 — selecting it is a hard exit with the pinned
message, never a silent fallback) · ``SELF_LEARN_UI_IDLE_EXIT_SECONDS``
(Y-14, 09 §4.4: idle self-exit window in seconds; default 600 under
the systemd unit, unarmed in a foreground ``serve`` unless set
explicitly — the arming rule lives in
:func:`self_learn_ui.idle.resolve_idle_window`, this module only
parses; any value ≤ 0 disables, negatives never error).

Nothing else in v1; no config file (09 §4.4).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Pinned verbatim (09 §4.1 / §4.4) — the ``cli`` engine is specced, not
#: built; selecting it must fail loudly with exactly this text.
ENGINE_NOT_BUILT_MESSAGE = "engine not built — see 09 §4.1"

DEFAULT_UI_PORT = 7357
DEFAULT_PANE_MODEL = "claude-sonnet-5"
DEFAULT_PANE_BUDGET_USD = 1.00
DEFAULT_PANE_MAX_TURNS = 15
DEFAULT_PANE_ENGINE = "sdk"
#: Y-14 (09 §4.4): the default idle window — applied by
#: :func:`self_learn_ui.idle.resolve_idle_window` ONLY under the
#: systemd unit; ``EnvConfig.ui_idle_exit_seconds`` stays ``None``
#: when the var is unset so the arming rule can tell "default" from
#: "explicitly 600".
DEFAULT_UI_IDLE_EXIT_SECONDS = 600

_VALID_ENGINES = ("sdk", "cli")


class EnvError(ValueError):
    """A configured env var could not be parsed into its expected type."""


class EngineNotBuiltError(RuntimeError):
    """``SELF_LEARN_PANE_ENGINE=cli`` was selected (09 §4.1's pinned exit).

    Callers (the ``serve`` subcommand) catch this, print
    :data:`ENGINE_NOT_BUILT_MESSAGE` to stderr, and exit non-zero — this
    exception never propagates as a traceback in normal operation.
    """


@dataclass(frozen=True)
class EnvConfig:
    """Resolved configuration for one server process (09 §4.4)."""

    self_learn_home: Path
    ui_port: int
    ui_browser: str | None
    pane_model: str
    pane_budget_usd: float
    pane_max_turns: int
    pane_engine: str
    #: ``None`` = unset (arming rule decides); an int = explicit
    #: (≤ 0 disables — pinned at the Y-14 spec gate, never an error).
    ui_idle_exit_seconds: int | None = None


def _parse_int(raw: str, name: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise EnvError(f"{name}={raw!r} is not a valid integer") from exc


def _parse_float(raw: str, name: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise EnvError(f"{name}={raw!r} is not a valid number") from exc


def load_env(environ: dict[str, str] | None = None) -> EnvConfig:
    """Parse the complete env var list into an :class:`EnvConfig`.

    ``environ`` defaults to ``os.environ`` — tests pass an explicit
    mapping so real process env never leaks into a test (10 §0 rule 7/8:
    tests never touch the real ledger, cache, or runtime dir).

    Raises :class:`EngineNotBuiltError` when ``SELF_LEARN_PANE_ENGINE`` is
    ``cli`` (09 §4.1's pinned exit) and :class:`EnvError` on a
    malformed numeric value.
    """
    env = os.environ if environ is None else environ

    home_raw = env.get("SELF_LEARN_HOME") or "~/.self-learn"
    self_learn_home = Path(home_raw).expanduser()

    ui_port_raw = env.get("SELF_LEARN_UI_PORT")
    ui_port = _parse_int(ui_port_raw, "SELF_LEARN_UI_PORT") if ui_port_raw else DEFAULT_UI_PORT

    ui_browser = env.get("SELF_LEARN_UI_BROWSER") or None

    pane_model = env.get("SELF_LEARN_PANE_MODEL") or DEFAULT_PANE_MODEL

    budget_raw = env.get("SELF_LEARN_PANE_BUDGET_USD")
    pane_budget_usd = (
        _parse_float(budget_raw, "SELF_LEARN_PANE_BUDGET_USD")
        if budget_raw
        else DEFAULT_PANE_BUDGET_USD
    )

    turns_raw = env.get("SELF_LEARN_PANE_MAX_TURNS")
    pane_max_turns = (
        _parse_int(turns_raw, "SELF_LEARN_PANE_MAX_TURNS") if turns_raw else DEFAULT_PANE_MAX_TURNS
    )

    idle_raw = env.get("SELF_LEARN_UI_IDLE_EXIT_SECONDS")
    ui_idle_exit_seconds = (
        _parse_int(idle_raw, "SELF_LEARN_UI_IDLE_EXIT_SECONDS") if idle_raw else None
    )

    pane_engine = (env.get("SELF_LEARN_PANE_ENGINE") or DEFAULT_PANE_ENGINE).strip()
    if pane_engine not in _VALID_ENGINES:
        raise EnvError(
            f"SELF_LEARN_PANE_ENGINE={pane_engine!r} must be one of {_VALID_ENGINES}"
        )
    if pane_engine == "cli":
        raise EngineNotBuiltError(ENGINE_NOT_BUILT_MESSAGE)

    return EnvConfig(
        self_learn_home=self_learn_home,
        ui_port=ui_port,
        ui_browser=ui_browser,
        pane_model=pane_model,
        pane_budget_usd=pane_budget_usd,
        pane_max_turns=pane_max_turns,
        pane_engine=pane_engine,
        ui_idle_exit_seconds=ui_idle_exit_seconds,
    )
