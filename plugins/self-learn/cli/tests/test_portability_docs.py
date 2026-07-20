"""C1 §1 / §3 — portability defect repair: doc/manifest content
(docs/specs/self-learn/drafts/c1-portability-defects-spec.md rev 7).

Obligations O-6 through O-9 and O-11. O-1..O-5/O-10/O-12/O-13/O-16 (the
`init` verb's own behavior) live in test_init.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from self_learn import sentinel

REPO_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_DIR = REPO_ROOT / "plugins" / "self-learn"
SYSTEMD_DIR = REPO_ROOT / "systemd"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------- O-6 / P-C1.17/18


def test_o6_systemd_units_have_no_claude_skills_reference():
    units = sorted(SYSTEMD_DIR.glob("*.service")) + sorted(SYSTEMD_DIR.glob("*.timer"))
    assert units, "no systemd units found — path drifted"
    for path in units:
        assert "claude-skills" not in _read(path), path


def test_o6_readme_install_blocks_have_no_repos_claude_skills():
    """    NIT 7 (code gate): the spec scopes this to install/registration
    blocks; this asserts WHOLE-FILE, which is strictly stricter. It
    passes today only because README.md:82's Spec-D-deferred literal
    is spelled `repos-claude-skills` (hyphens). A Spec D author who
    rewrites it with slashes will trip this — by design.

    P-C1.17: the pattern must match each surface's own spelling — this
    is the `repos/claude-skills` shape the two READMEs use (never
    `plugin.json`'s different `github.com/AlexK-Notable/claude-skills`
    spelling, which O-8 covers on its own surface — P-C1.18: no
    repo-wide sweep, no global allowlist)."""
    for path in (REPO_ROOT / "README.md", PLUGIN_DIR / "README.md"):
        assert "repos/claude-skills" not in _read(path), path


# ------------------------------------------------------------------- O-7


def test_o7_plugin_readme_cache_path_matches_sentinel_function(monkeypatch):
    """Asserted against `sentinel.sentinel_path()` itself, never a
    literal (rev 1 named a function that does not exist — `cache_path`)."""
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    expected = sentinel.sentinel_path()
    doc_relative = str(expected).replace(str(Path.home()), "~", 1)
    text = _read(PLUGIN_DIR / "README.md")
    assert doc_relative in text
    # the retired claude-skills-namespaced path must be gone
    assert "claude-skills/self-learn/autosync-pause" not in text


# ------------------------------------------------------------------- O-8


def test_o8_plugin_json_names_self_learn_repo():
    data = json.loads(_read(PLUGIN_DIR / ".claude-plugin" / "plugin.json"))
    assert data["homepage"] == "https://github.com/AlexK-Notable/self-learn"
    assert data["repository"]["url"] == "https://github.com/AlexK-Notable/self-learn.git"
    # P-C1.3: the author block is untouched — out of scope, never a target
    assert data["author"]["name"] == "Alex Kechichian"
    assert data["author"]["email"] == "alexkechichian1@gmail.com"


# ------------------------------------------------------------------- O-9


def test_o9_no_manual_ln_sf_of_a_unit_install_sh_already_links():
    surfaces = [
        SYSTEMD_DIR / "self-learn-miner.service",
        SYSTEMD_DIR / "self-learn-ui.service",
        PLUGIN_DIR / "README.md",
    ]
    for path in surfaces:
        text = _read(path)
        assert "ln -sf" not in text, f"{path} still instructs a manual ln -sf"
        # replaced by a pointer to the enable step install.sh leaves manual
        assert "systemctl --user enable" in text, path


# ------------------------------------------------------------------ O-11


def test_o11_readme_states_git_repo_prerequisite_and_names_init():
    text = _read(REPO_ROOT / "README.md")
    assert "self-learn init" in text
    assert "git repo" in text


def test_o11_readme_clone_block_discloses_private_repo():
    text = _read(REPO_ROOT / "README.md")
    marker = "git clone git@github.com:AlexK-Notable/self-learn.git"
    idx = text.index(marker)
    window = text[max(0, idx - 200) : idx]
    assert "private" in window.lower()


def test_o11_no_bogus_cross_reference_remains_anywhere_in_sentinel_py():
    """File-wide, not line-targeted (§1.2a / P-C1.19) — rev 3-4 named only
    `:55` and missed the docstring copy at `:3`."""
    text = _read(
        REPO_ROOT / "plugins" / "self-learn" / "cli" / "src" / "self_learn" / "sentinel.py"
    )
    assert "§4.4" not in text
    assert "doc 13 §6" in text  # the corrected authority is actually cited


def test_home_state_error_messages_name_init():
    """`ledger.py`'s `missing` / `not-a-repo` refusals gain a mention of
    `self-learn init` (C1 §2.2 P-C1.7)."""
    from self_learn.ledger import home_state_message

    missing = home_state_message("missing", "/nonexistent/wherever")
    not_a_repo = home_state_message("not-a-repo", "/nonexistent/wherever")
    assert "self-learn init" in missing
    assert "self-learn init" in not_a_repo
