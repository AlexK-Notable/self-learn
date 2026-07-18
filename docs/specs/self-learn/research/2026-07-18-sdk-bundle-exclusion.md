# Research note — claude_agent_sdk bundle exclusion (packaging pivot input)

2026-07-18, overnight autonomous run. Closes the open question from the
2026-07-17 binarization spike: *can the PyInstaller UI binary exclude
the SDK's vendored node bundle?*

**Answer: YES — verified in source AND empirically.**

- Source (installed SDK 0.2.121,
  `_internal/transport/subprocess_cli.py`): `_find_cli()` checks the
  package-relative `_bundled/` CLI first (`bundled_path.exists()`),
  then falls back to `shutil.which("claude")`. The bundle is an
  existence check, not a hard dependency.
- Empirical: a `tar`-copied `claude_agent_sdk` with `_bundled/`
  excluded (900 KB vs 252 MB) put first on `sys.path` resolves
  `_find_bundled_cli() → None` and `_find_cli() →
  /home/komi/.local/bin/claude` — the PATH fallback fires exactly as
  the source promises.

Consequences for the packaging phase:

1. The UI onefile/onedir build excludes
   `claude_agent_sdk/_bundled/**` — expected size drop ~305 MB →
   ~50 MB.
2. Hard runtime requirement, to be documented and checked at startup:
   `claude` on PATH. This is not a new burden — the product wraps
   Claude Code sessions; a machine without the CLI has no use for
   self-learn at all. A friendly preflight ("claude not found on
   PATH — install Claude Code first") beats the SDK's own late error.
3. Version-skew caveat: the bundled CLI is version-pinned by the SDK
   release; the PATH CLI is whatever the user runs. The pane engine
   already survives normal CLI drift (it speaks the SDK protocol),
   but packaging docs should note the SDK's tested-against version.
