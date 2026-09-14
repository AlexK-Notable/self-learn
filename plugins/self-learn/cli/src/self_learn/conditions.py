"""conditions.py — the conditions feed (U9; plan-steward §4.4; interface
§4; `02-schema.md` §3a.5).

A block of facts about the world *as of this run*, assembled by code and
handed to the steward's packet (:func:`steward_prompt.assemble`) and,
later, the overseer's own re-observation diff. Every item is
``Item(key, value, observed_at, source)``; :func:`feed` is the ONE
importable entry point (interface R-11) — the overseer's conditions diff
calls this exact name to re-observe the keys a case cited. Read-only:
this module never writes the ledger and takes no lock.

**Fail-closed visibility (build-u9.md).** Every source that cannot be
read yields its item(s) with ``value == "unavailable"`` and a ``source``
naming what was tried. A key is NEVER silently absent because its source
failed to read; :func:`feed` itself never raises.

**Ruling — no bare ``repo.head`` (build-u9.md, overriding `02-schema.md`
§3a.5 and interface-draft-steward-2026-09-13.md §4.2, both of which list
``ledger.head``, ``repo.head`` verbatim).** This module emits
``host.<path>.head`` once per REGISTERED host (:func:`hosts.load_hosts` —
the skills root plus every project) whose path is actually a git
repository (:func:`gitops.toplevel` returns non-``None`` for it). A host
that is not a git repo (a plain-mode host, by `hosts.py`'s own "a plain
host is never a git repo self-learn manages" contract, or any registered
path that never became one) gets no ``.head`` item at all — that is a
design absence, not a read failure, so it is never reported
``"unavailable"``. ``host.<path>.mode`` is always emitted for every
registered host, git or not. When ``hosts.yaml`` itself cannot be
parsed, the per-path keys cannot be formed at all (the paths are exactly
what failed to read) — this module falls back to the literal keys
``host.*.mode`` / ``host.*.head`` with value ``"unavailable"``, source
naming the parse failure, so "host." items are still present, never
silently absent.

**``declared.<key>`` derivation (this module's own reading — the
interface draft's §3.3 says user-model container E entries carry a
``cond:`` field; the shipped `user_model.py` (U2, already merged) has no
such field, grepped clean).** The seed document
(``misc/audit-2026-09-02/steward-design/user-model-seed-2026-09-12.md``)
resolves this: container E entries spell the feed key straight into
their own ``title`` — e.g. ``declared.host.self-learn.claude-md: local``,
``declared.config-outer-repo-has-no-remote``. This module reads each
entry's ``title``, splits it on the first ``": "`` into key/value (a
title with no ``": "`` is a boolean-shaped declaration, value
``"true"``), and strips one leading ``"declared."`` before re-adding it,
so a future entry whose author omits the prefix in `title` still lands
on the same key shape.

**``steward.*`` / ``overseer.*`` run records.**
``steward.last_run_at`` / ``.last_run_outcome`` / ``.cases_since_overseer``
read the newest ``<cache_dir>/steward/runs/<run_id>/run.json`` by file
mtime (U10 not yet built — no run_id naming convention exists to sort by
instead); its top-level keys are read as exactly those three suffixes.
Absent (no runs directory yet, the expected pre-U10 state) →
``"unavailable"`` for all three, never a missing key.

O-3 adds top-level ``last_run_at`` / ``last_examined_at`` to
``<ledger>/overseer/coverage.yaml``. The feed reads those two persisted
facts directly; it does not derive a run time from stratum timestamps.
Either missing field yields ``"unavailable"`` independently.

**``status.*`` — no `cli.py` extraction (this unit's own resolution of
the build brief's conditional "if those are inline in `cli.py`,
extract...").** The four values already live behind importable,
side-effect-free module functions this module calls directly:
:func:`worker.fast_status` (``total_pending``, ``unanalyzed_total``) and
:func:`intents.classify_status` (``.probe``, ``len(.stopped)``) — the
same "intents probe" `cli._cmd_status_fast` itself calls. Nothing in
`cli.py` was inline here to extract, so `cli.py` is untouched by this
unit and the brief's parity test (#7, "only if you extracted it") does
not apply — see this unit's report."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import gitops
from . import hosts as hosts_mod
from . import intents
from . import report as report_mod
from . import settings
from . import user_model
from .primitives import chrono

__all__ = ["Item", "feed"]


@dataclass(frozen=True)
class Item:
    key: str
    value: Any
    observed_at: str
    source: str


_REPORT_KEYS = (
    "buckets",
    "destinations",
    "routed_live",
    "open_followups",
    "recurrence_suspects",
    "deferred",
    "reference_shelf",
    "context_budget",
    "surface_reach",
)

_MODEL_SETTINGS = (
    "models.worker",
    "models.miner",
    "models.analyst",
    "models.steward",
    "models.overseer",
)

_STEWARD_RUN_KEYS = ("last_run_at", "last_run_outcome", "cases_since_overseer")
_OVERSEER_RUN_KEYS = ("last_run_at", "last_examined_at")


def _report_items(home: Path, observed_at: str) -> list[Item]:
    source = "report.gather(home)"
    try:
        facts = report_mod.gather(home)
    except Exception as exc:  # noqa: BLE001 — fail-closed, never propagate
        return [
            Item(f"report.{k}", "unavailable", observed_at, f"{source} failed: {exc}")
            for k in _REPORT_KEYS
        ]
    return [
        Item(f"report.{k}", facts.get(k, "unavailable"), observed_at, source)
        for k in _REPORT_KEYS
    ]


def _status_items(home: Path, observed_at: str) -> list[Item]:
    """N1: `worker.fast_status` and `intents.classify_status` are two
    independent producers feeding four keys between them; each gets its
    OWN try/except so one producer's failure never blanks the other's
    two keys, and a key's `source` names only the producer that actually
    made it."""
    from . import worker  # deferred: same-family reuse convention

    try:
        fast = worker.fast_status(home)
        fast_source = "worker.fast_status(home)"
        total_pending = fast.get("total_pending", "unavailable")
        unanalyzed_total = fast.get("unanalyzed_total", "unavailable")
    except Exception as exc:  # noqa: BLE001 — fail-closed
        fast_source = f"worker.fast_status(home) failed: {exc}"
        total_pending = "unavailable"
        unanalyzed_total = "unavailable"

    try:
        cls = intents.classify_status(home)
        cls_source = "intents.classify_status(home)"
        intents_probe = cls.probe
        intents_stopped_count = len(cls.stopped)
    except Exception as exc:  # noqa: BLE001 — fail-closed
        cls_source = f"intents.classify_status(home) failed: {exc}"
        intents_probe = "unavailable"
        intents_stopped_count = "unavailable"

    return [
        Item("status.total_pending", total_pending, observed_at, fast_source),
        Item("status.unanalyzed_total", unanalyzed_total, observed_at, fast_source),
        Item("status.intents_probe", intents_probe, observed_at, cls_source),
        Item(
            "status.intents_stopped_count",
            intents_stopped_count,
            observed_at,
            cls_source,
        ),
    ]


def _host_items(home: Path, observed_at: str) -> list[Item]:
    try:
        parsed = hosts_mod.load_hosts(home)
    except hosts_mod.HostsError as exc:
        source = f"hosts.load_hosts(home) failed: {exc}"
        return [
            Item("host.*.mode", "unavailable", observed_at, source),
            Item("host.*.head", "unavailable", observed_at, source),
        ]

    entries: list[tuple[str, str]] = []  # (resolved path str, mode)
    if parsed.skills_root is not None:
        entries.append((str(parsed.skills_root.resolve()), parsed.skills_root_mode))
    for p in parsed.projects:
        resolved = str(p.resolve())
        mode = parsed.project_modes.get(resolved, "git")
        entries.append((resolved, mode))

    items: list[Item] = []
    for path_str, mode in entries:
        items.append(
            Item(f"host.{path_str}.mode", mode, observed_at, "hosts.load_hosts(home)")
        )
        try:
            top = gitops.toplevel(Path(path_str))
        except Exception:  # noqa: BLE001 — treat as "cannot determine"
            top = None
        if top is None:
            continue  # not a git repo (or unresolvable) — design absence, not a failure
        try:
            head = gitops.head_sha(Path(path_str))
            items.append(
                Item(
                    f"host.{path_str}.head",
                    head,
                    observed_at,
                    f"gitops.head_sha({path_str})",
                )
            )
        except Exception as exc:  # noqa: BLE001
            items.append(
                Item(
                    f"host.{path_str}.head",
                    "unavailable",
                    observed_at,
                    f"gitops.head_sha({path_str}) failed: {exc}",
                )
            )
    return items


def _settings_items(home: Path, observed_at: str) -> list[Item]:
    names = list(_MODEL_SETTINGS) + [
        s.name for s in settings.REGISTRY if s.name.startswith("sdk.max_turns.")
    ]
    items: list[Item] = []
    for name in names:
        try:
            setting = settings.by_name(name)
            value, _source_label = settings.resolve_setting(home, setting)
            items.append(
                Item(name, value, observed_at, f"settings.resolve_setting({name})")
            )
        except Exception as exc:  # noqa: BLE001
            items.append(
                Item(
                    name,
                    "unavailable",
                    observed_at,
                    f"settings.resolve_setting({name}) failed: {exc}",
                )
            )
    return items


def _output_style_item(observed_at: str) -> Item:
    from .selfcheck import claude_runtime_dir  # deferred: same-family reuse

    key = "surface.output-style.active"
    claude_dir = claude_runtime_dir()
    settings_path = claude_dir / "settings.json"
    source = f"{settings_path}:outputStyle"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Item(key, "unavailable", observed_at, source)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Item(key, "unavailable", observed_at, f"{source} failed: {exc}")
    if not isinstance(data, dict):
        return Item(key, "unavailable", observed_at, f"{source}: not a JSON object")
    value = data.get("outputStyle")
    if value is None:
        return Item(key, "unavailable", observed_at, f"{source}: key absent")
    return Item(key, value, observed_at, source)


def _declared_items(home: Path, observed_at: str) -> list[Item]:
    source = "user_model.show(home)[containers][E]"
    try:
        containers = user_model.show(home)["containers"]
    except Exception as exc:  # noqa: BLE001
        return [Item("declared.*", "unavailable", observed_at, f"{source} failed: {exc}")]
    items: list[Item] = []
    for entry in containers.get("E", []):
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        key_part, sep, value_part = title.partition(": ")
        key_part = key_part.strip()
        if key_part.startswith("declared."):
            key_part = key_part[len("declared.") :]
        key = f"declared.{key_part}" if key_part else "declared.<unnamed>"
        value = value_part.strip() if sep else "true"
        items.append(Item(key, value, observed_at, source))
    return items


def _newest_by_mtime(paths: list[Path]) -> Path | None:
    best: tuple[float, Path] | None = None
    for p in paths:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, p)
    return best[1] if best is not None else None


def _steward_run_items(cache_dir: Path, observed_at: str) -> list[Item]:
    runs_dir = cache_dir / "steward" / "runs"
    fallback_source = f"{runs_dir}/<run_id>/run.json"
    if not runs_dir.is_dir():
        return [
            Item(f"steward.{k}", "unavailable", observed_at, fallback_source)
            for k in _STEWARD_RUN_KEYS
        ]
    candidates = [p for p in runs_dir.glob("*/run.json") if p.is_file()]
    newest = _newest_by_mtime(candidates)
    if newest is None:
        return [
            Item(f"steward.{k}", "unavailable", observed_at, fallback_source)
            for k in _STEWARD_RUN_KEYS
        ]
    try:
        data = json.loads(newest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        source = f"{newest} failed: {exc}"
        return [
            Item(f"steward.{k}", "unavailable", observed_at, source)
            for k in _STEWARD_RUN_KEYS
        ]
    if not isinstance(data, dict):
        source = f"{newest}: not a JSON object"
        return [
            Item(f"steward.{k}", "unavailable", observed_at, source)
            for k in _STEWARD_RUN_KEYS
        ]
    return [
        Item(f"steward.{k}", data.get(k, "unavailable"), observed_at, str(newest))
        for k in _STEWARD_RUN_KEYS
    ]


def _overseer_run_items(home: Path, observed_at: str) -> list[Item]:
    path = home / "overseer" / "coverage.yaml"
    source = str(path)
    if not path.is_file():
        return [
            Item("overseer.last_run_at", "unavailable", observed_at, source),
            Item("overseer.last_examined_at", "unavailable", observed_at, source),
        ]
    try:
        from ruamel.yaml import YAML, YAMLError

        yaml = YAML(typ="safe")
        data = yaml.load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        fail_source = f"{source} failed: {exc}"
        return [
            Item("overseer.last_run_at", "unavailable", observed_at, fail_source),
            Item("overseer.last_examined_at", "unavailable", observed_at, fail_source),
        ]
    if not isinstance(data, dict):
        data = {}
    return [
        Item("overseer.last_run_at", data.get("last_run_at") or "unavailable", observed_at, source),
        Item("overseer.last_examined_at", data.get("last_examined_at") or "unavailable", observed_at, source),
    ]


def _ledger_head_item(home: Path, observed_at: str) -> Item:
    try:
        sha = gitops.head_sha(home)
        return Item("ledger.head", sha, observed_at, "gitops.head_sha(home)")
    except Exception as exc:  # noqa: BLE001
        return Item(
            "ledger.head", "unavailable", observed_at, f"gitops.head_sha(home) failed: {exc}"
        )


def feed(home: Path | str, cache_dir: Path | str | None = None) -> list[Item]:
    """Interface §4 / R-11: THE importable conditions feed. Never raises
    (every source group is its own try/except, fail-closed to
    ``"unavailable"``, N2 -- this now includes the ``cache_dir`` fallback
    and the output-style read, not only the nine source-group helpers);
    never mutates the ledger; takes no lock. One ``observed_at``
    timestamp is computed once and shared by every item — the whole feed
    is one snapshot "as of this run" (plan §4.4)."""
    home = Path(home)
    if cache_dir is None:
        try:
            from . import worker  # deferred: same-family reuse convention

            cache_dir = worker.cache_dir(home)
        except Exception:  # noqa: BLE001 — fail-closed; feed() never raises
            # No readable cache dir: `_steward_run_items` below already
            # degrades a missing/unreadable runs directory to
            # "unavailable" for all three `steward.*` keys, so handing it
            # a path that provably does not exist reaches the same
            # fail-closed shape without a second code path.
            cache_dir = home / ".self-learn-cache-unavailable"
    else:
        cache_dir = Path(cache_dir)
    observed_at = chrono.now_iso()

    items: list[Item] = []
    items.extend(_report_items(home, observed_at))
    items.extend(_status_items(home, observed_at))
    items.extend(_host_items(home, observed_at))
    items.extend(_settings_items(home, observed_at))
    try:
        items.append(_output_style_item(observed_at))
    except Exception as exc:  # noqa: BLE001 — fail-closed; feed() never raises
        items.append(
            Item(
                "surface.output-style.active",
                "unavailable",
                observed_at,
                f"_output_style_item failed: {exc}",
            )
        )
    items.extend(_declared_items(home, observed_at))
    items.extend(_steward_run_items(cache_dir, observed_at))
    items.extend(_overseer_run_items(home, observed_at))
    items.append(_ledger_head_item(home, observed_at))
    return items
