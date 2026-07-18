"""The pane doctrine compiler (10 §1's "Doctrine compile" row; 09 §4.2).

``<cache>/pane-doctrine.md`` = concat of ``references/routing-doctrine.md``
+ ``references/pane-surface-model.md`` + ``references/pane-charter.md``
(all tracked in the plugin; the surface model added 2026-07-17 — 09 §11
Y-13/§4.2: what the buckets/scopes/verbs/screens are, so "talk to me
about my buckets and routing" works without the agent rediscovering the
system each session). Recompiled
when any source's mtime is newer than the compiled file's; byte-stable
between recompiles (plain concatenation — no timestamps, no randomness);
read into the SDK's ``system_prompt`` option at session start (09 §4.2:
"byte-stable across sessions by construction" is what makes whatever
prompt caching the auth path offers actually land).

This module also owns :func:`plugin_references_dir` — the skill's
``references/`` dir resolved relative to the **ui package's own installed
location**, per 09 §11 Y-2 root 3 ("never via SELF_LEARN_HOME"). It is a
deliberately independent computation from
``self_learn.worker.package_skill_refs()`` (the cli package's equivalent):
even though both land on the same directory in this monorepo layout, the
ui package's contract is "resolve relative to MY OWN location" — importing
the cli package's private path arithmetic for this would make the ui
package's root-3 guarantee depend on where the CLI package happens to sit,
which is exactly the kind of silent coupling Y-2 warns against for read
scope. (Contrast with :mod:`self_learn_ui.uilog`, which DOES import the
cli package's ``cache_dir()`` — that one is a single shared *value*
derivation the two packages must agree on bit-for-bit; this one is a
per-package *identity* guarantee that must NOT depend on the other
package's location.)
"""

from __future__ import annotations

from pathlib import Path

from self_learn.worker import cache_dir

__all__ = [
    "COMPILED_DOCTRINE_NAME",
    "compile_doctrine",
    "compiled_doctrine_path",
    "pane_charter_path",
    "pane_surface_model_path",
    "plugin_references_dir",
    "read_doctrine",
    "routing_doctrine_path",
]

COMPILED_DOCTRINE_NAME = "pane-doctrine.md"


def plugin_references_dir() -> Path:
    """The skill's ``references/`` dir, resolved relative to THIS file's
    own installed location (09 §11 Y-2 root 3). ``doctrine.py`` lives at
    ``plugins/self-learn/ui/src/self_learn_ui/doctrine.py`` — four
    ``parents[]`` hops up is ``plugins/self-learn``."""
    return Path(__file__).resolve().parents[3] / "skills" / "self-learn" / "references"


def routing_doctrine_path() -> Path:
    return plugin_references_dir() / "routing-doctrine.md"


def pane_charter_path() -> Path:
    return plugin_references_dir() / "pane-charter.md"


def pane_surface_model_path() -> Path:
    return plugin_references_dir() / "pane-surface-model.md"


def compiled_doctrine_path() -> Path:
    """The compiled artifact's resolved path — inside the CLI's own
    home-namespaced cache dir (imported, never reimplemented — same
    single-computation rule ``uilog.py`` follows)."""
    return cache_dir() / COMPILED_DOCTRINE_NAME


def compile_doctrine(
    *,
    routing_path: Path | None = None,
    charter_path: Path | None = None,
    compiled_path: Path | None = None,
    surface_model_path: Path | None = None,
) -> Path:
    """Recompile ``compiled_path`` from ``routing_path`` +
    ``surface_model_path`` + ``charter_path`` iff any source's mtime is
    newer than the compiled file's (or the compiled file doesn't exist
    yet). Returns the compiled path either way — callers that only want
    the text should use :func:`read_doctrine`.

    All paths default to the real, tracked locations; tests pass
    explicit ``tmp_path``-rooted paths instead of touching the real skill
    references dir or the real cache (10 §0 rule 7/8).
    """
    routing_path = routing_path if routing_path is not None else routing_doctrine_path()
    charter_path = charter_path if charter_path is not None else pane_charter_path()
    compiled_path = compiled_path if compiled_path is not None else compiled_doctrine_path()
    surface_model_path = (
        surface_model_path if surface_model_path is not None else pane_surface_model_path()
    )

    sources = [routing_path, surface_model_path, charter_path]
    newest_source = max(path.stat().st_mtime for path in sources)

    needs_compile = True
    if compiled_path.is_file():
        needs_compile = compiled_path.stat().st_mtime < newest_source

    if needs_compile:
        # Plain concatenation — no timestamps, no compile metadata — is what
        # makes two recompiles of unchanged sources byte-identical (the
        # byte-stability pin: 09 §4.2, "byte-stable across sessions by
        # construction"). Order pinned: doctrine, surface model, charter —
        # the charter (the hard rules) reads last, closest to the task.
        parts = []
        for path in sources:
            text = path.read_text(encoding="utf-8")
            if not text.endswith("\n"):
                text += "\n"
            parts.append(text)
        compiled_text = "\n".join(parts)
        compiled_path.parent.mkdir(parents=True, exist_ok=True)
        compiled_path.write_text(compiled_text, encoding="utf-8")

    return compiled_path


def read_doctrine(
    *,
    routing_path: Path | None = None,
    charter_path: Path | None = None,
    compiled_path: Path | None = None,
    surface_model_path: Path | None = None,
) -> str:
    """Compile-if-needed, then return the compiled doctrine text — the
    string passed as the SDK's ``system_prompt`` option (09 §4.2)."""
    path = compile_doctrine(
        routing_path=routing_path,
        charter_path=charter_path,
        compiled_path=compiled_path,
        surface_model_path=surface_model_path,
    )
    return path.read_text(encoding="utf-8")
