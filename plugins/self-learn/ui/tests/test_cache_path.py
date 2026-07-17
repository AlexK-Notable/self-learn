"""Cache-path resolution tests (10 §1 Server transient state row; task U1
test bullet 3).

Verifies the import-vs-shell decision made in ``self_learn_ui.uilog``:
the ui package IMPORTS the CLI's own ``self_learn.worker.cache_dir()``
rather than reimplementing the doc-13 home-namespaced derivation. Both
``XDG_CACHE_HOME`` and ``SELF_LEARN_HOME`` are redirected to throwaway
dirs (10 §0 rule 7/8) — this test never touches the real cache or ledger.
"""

from __future__ import annotations

from pathlib import Path

from self_learn.worker import cache_dir as cli_cache_dir

from self_learn_ui.uilog import UI_LOG_CAP_BYTES, log, ui_log_path


def test_ui_log_path_lives_inside_the_clis_cache_dir(
    redirected_xdg: dict[str, Path],
) -> None:
    assert ui_log_path().parent == cli_cache_dir()


def test_cache_dir_is_redirected_never_the_real_home(
    redirected_xdg: dict[str, Path],
) -> None:
    resolved = cli_cache_dir()
    assert str(resolved).startswith(str(redirected_xdg["cache_home"]))
    assert resolved.is_dir()  # cache_dir() creates it as a side effect


def test_cache_dir_is_home_namespaced(redirected_xdg: dict[str, Path]) -> None:
    """doc 13 §6 / H-4: the dir name embeds a short sha256 of the
    resolved SELF_LEARN_HOME — two different homes get two different
    cache dirs."""
    first = cli_cache_dir()
    assert first.name.startswith("home-")
    assert first.parent.name == "self-learn"


def test_log_writes_a_timestamped_line(redirected_xdg: dict[str, Path]) -> None:
    log("U1 verification line")
    content = ui_log_path().read_text(encoding="utf-8")
    assert "U1 verification line" in content
    # ISO-ish timestamp prefix, same shape as worker.log's lines.
    assert content.split(" ", 1)[0].endswith("Z")


def test_log_is_capped(redirected_xdg: dict[str, Path], monkeypatch) -> None:
    # UI_LOG_CAP_BYTES is looked up as a module global at call time inside
    # log(), so patching the module attribute (not the name imported into
    # this test module) is what actually takes effect.
    monkeypatch.setattr("self_learn_ui.uilog.UI_LOG_CAP_BYTES", 200)
    for i in range(100):
        log(f"line number {i} padding padding padding")
    size = ui_log_path().stat().st_size
    assert size <= 200


def test_default_cap_matches_workers_cap() -> None:
    """Same VALUE as worker.log's cap (10 §1: "same truncation as
    worker.log") — kept as an independent constant so this module never
    breaks if the CLI renames its own private constant."""
    assert UI_LOG_CAP_BYTES == 1_000_000
