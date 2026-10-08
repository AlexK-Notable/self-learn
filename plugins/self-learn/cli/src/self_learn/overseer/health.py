"""O-7 catalogue-health facts for the overseer's phase-B packet.

Every exported fact builder is a projection or comparison over values read by
existing modules.  This module never calls a model and never writes the
ledger.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ruamel.yaml import YAML

from .. import conditions, gitops, report, settings, telemetry
from ..always_loaded import is_always_loaded
from ..ledger import discover_buckets
from ..records import Record, RecordError, is_replacement


#: How far back a fire counts when the row asks which always-loaded lines have
#: gone quiet. One constant for the lookback and the label, so the number and
#: the words that describe it cannot drift apart.
_FIRE_WINDOW_DAYS = 30

_SILENCE_CAUTION = (
    "Silence is not retirement evidence: fire telemetry is incomplete and "
    "a zero may mean the lesson was not encountered or not observed."
)


def context_budget_crowding(gathered: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "context-budget-crowding",
        "value": (gathered.get("context_budget") or {}).get("crowding", "unavailable"),
    }


def reference_read_verdict(gathered: dict[str, Any]) -> dict[str, Any]:
    context = gathered.get("context_budget") or {}
    return {
        "kind": "reference-read-verdict",
        "value": (context.get("conditional") or {}).get("reference", "unavailable"),
    }


def surface_reach(gathered: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "surface-reach", "value": gathered.get("surface_reach", "unavailable")}


def recurrence_suspects(gathered: dict[str, Any]) -> dict[str, Any]:
    rows = gathered.get("recurrence_suspects")
    return {
        "kind": "recurrence-suspects",
        "value": list(rows) if isinstance(rows, list) else [],
    }


def never_fired_always_loaded(
    always_loaded: Iterable[str],
    fired: set[str],
    *,
    window_days: int = _FIRE_WINDOW_DAYS,
) -> dict[str, Any]:
    """Always-loaded lines with no recorded fire in the last *window_days*.

    The function keeps its old name for its callers; the row it builds says
    what it measures: a lookback window, not "never"."""
    return {
        "kind": "no-fire-always-loaded",
        "label": (
            f"Always-loaded CLAUDE.md lines with no recorded fire in the last {window_days} days "
            "(a replaced lesson's fires count)"
        ),
        "window_days": window_days,
        "value": sorted({record_id for record_id in always_loaded if record_id not in fired}),
        "caution": _SILENCE_CAUTION,
    }


def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    rows: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            rows.update(_flatten(value, path))
        else:
            rows[path] = value
    return rows


def _condition_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "key"):
        return asdict(item)
    return dict(item)


def conditions_diff(
    *,
    previous_hosts: Any,
    current_hosts: Any,
    previous_config: Any,
    current_config: Any,
    current: Iterable[Any],
    baseline: str | None,
) -> dict[str, Any]:
    """Compare the committed inputs and attach relevant current effective facts.

    A process environment from a prior run cannot be reconstructed from Git;
    that limit stays explicit instead of being reported as an unchanged model.
    """
    old = _flatten(previous_config)
    new = _flatten(current_config)
    model_names = sorted(setting.name for setting in settings.REGISTRY if setting.name.startswith("models."))
    capability_names = sorted(setting.name for setting in settings.REGISTRY if setting.kind == "bool")
    relevant = set(model_names) | set(capability_names)
    effective = []
    for raw in current:
        item = _condition_dict(raw)
        key = str(item.get("key", ""))
        if key.startswith("host.") or key in relevant:
            effective.append(item)
    return {
        "kind": "conditions-diff",
        "baseline": baseline or "unavailable-first-run",
        "hosts_changed": None if baseline is None else previous_hosts != current_hosts,
        "models_changed": [name for name in model_names if old.get(name) != new.get(name)],
        "capability_flags_changed": [
            name for name in capability_names if old.get(name) != new.get(name)
        ],
        "current": effective,
        "ambient_previous_values": "unavailable; prior process environment is not committed",
    }


def _yaml_text(text: str) -> Any:
    try:
        loaded = YAML(typ="safe").load(text)
    except Exception:  # noqa: BLE001 - health facts degrade, never break a run
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _current_yaml(path: Path) -> Any:
    try:
        return _yaml_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def _last_overseer_commit(home: Path) -> str | None:
    try:
        proc = gitops._git(home, "log", "-1", "--format=%H", "--", "overseer/latest-report.md")
    except gitops.GitOpsError:
        return None
    value = proc.stdout.strip() if proc.returncode == 0 else ""
    return value or None


def _historical_yaml(home: Path, commit: str | None, name: str) -> Any:
    if commit is None:
        return {}
    try:
        proc = gitops._git(home, "show", f"{commit}:{name}")
    except gitops.GitOpsError:
        return {}
    return _yaml_text(proc.stdout) if proc.returncode == 0 else {}


def _always_loaded_ids(home: Path) -> list[str]:
    """Ids of routed user-scope lessons whose destination is an always-loaded
    line, by the same test the steward's gate uses
    (:func:`self_learn.always_loaded.is_always_loaded`). A lesson routed to a reference
    shelf, a path-scoped rule, a skill or a hook loads some other way and is
    not counted."""
    ids: list[str] = []
    for bucket in discover_buckets(home):
        if bucket.scope != "user":
            continue
        directory = bucket.path / "resolved"
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except (RecordError, OSError, UnicodeDecodeError):
                continue
            if record.status != "routed":
                continue
            routing = record.routing or {}
            if is_always_loaded(routing.get("destination"), routing.get("variant")):
                ids.append(record.id)
    return ids


def _replacement_successors(home: Path) -> dict[str, str]:
    """``{old record id: its replacement's id}`` for every record in any
    bucket's ``resolved/`` whose ``superseded_by`` names a record id.

    That is what ``supersede`` and ``teach --supersedes`` both leave on the OLD
    record. A retirement (``covered_by:<kind>:<name>``, or the legacy
    ``canon``) names a surface, not a lesson, and is left out
    (:func:`self_learn.records.is_replacement` is the one test for the
    difference). A file that does not read back is skipped, as in
    :func:`_always_loaded_ids`."""
    successors: dict[str, str] = {}
    for bucket in discover_buckets(home):
        directory = bucket.path / "resolved"
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except (RecordError, OSError, UnicodeDecodeError):
                continue
            successor = record.superseded_by
            if is_replacement(successor):
                successors[record.id] = str(successor)
    return successors


def credit_replacement_chains(home: Path, fired: set[str]) -> set[str]:
    """*fired* plus every lesson downstream of a fired one in a replacement
    chain (the "fire credit" rule).

    A lesson that ``supersede`` or ``teach --supersedes`` replaced starts at zero
    fires under its new id. Without this, a rewrite that shortens a line looks
    dead the next week and invites a wrong retirement. A fire on the old id
    counts toward each lesson after it in the chain, so the live one at the end
    is credited. The walk goes forward through the old record's
    ``superseded_by`` only, never backward through ``supersedes``.

    The walk is bounded: it stops at the end of a chain, at an id with no
    record (a dangling ``superseded_by``), and on revisiting an id (a cycle or
    a self-reference). The caller applies its own time window to *fired*
    BEFORE calling, so a fire outside the window credits nothing."""
    successors = _replacement_successors(home)
    credited = set(fired)
    for record_id in fired:
        seen = {record_id}
        current = record_id
        while True:
            following = successors.get(current)
            if following is None or following in seen:
                break
            credited.add(following)
            seen.add(following)
            current = following
    return credited


def _current_condition_items(home: Path) -> list[Any]:
    items: list[Any] = list(conditions.feed(home))
    observed_at = items[0].observed_at if items else datetime.now(timezone.utc).isoformat()
    existing = {item.key for item in items}
    for setting in settings.REGISTRY:
        if not (setting.name.startswith("models.") or setting.kind == "bool"):
            continue
        if setting.name in existing:
            continue
        try:
            value, _source = settings.resolve_setting(home, setting)
            source = f"settings.resolve_setting({setting.name})"
        except Exception as exc:  # noqa: BLE001 - fact row remains visible
            value = "unavailable"
            source = f"settings.resolve_setting({setting.name}) failed: {exc}"
        items.append(conditions.Item(setting.name, value, observed_at, source))
    return items


def gather(home: Path | str) -> list[dict[str, Any]]:
    """Read and render the bounded catalogue-health packet."""
    resolved = Path(home)
    gathered = report.gather(resolved)
    since = (datetime.now(timezone.utc) - timedelta(days=_FIRE_WINDOW_DAYS)).isoformat()
    fired = {
        str(event["record"])
        for event in telemetry.read_events(resolved)
        if event.get("kind") == "fire"
        and isinstance(event.get("record"), str)
        and str(event.get("ts", "")) >= str(since)
    }
    # A lesson replaced inside the window keeps its fires.
    fired = credit_replacement_chains(resolved, fired)
    current = _current_condition_items(resolved)
    baseline = _last_overseer_commit(resolved)
    condition_row = conditions_diff(
        previous_hosts=_historical_yaml(resolved, baseline, "hosts.yaml"),
        current_hosts=_current_yaml(resolved / "hosts.yaml"),
        previous_config=_historical_yaml(resolved, baseline, "config.yaml"),
        current_config=_current_yaml(resolved / "config.yaml"),
        current=current,
        baseline=baseline,
    )
    return [
        context_budget_crowding(gathered),
        reference_read_verdict(gathered),
        surface_reach(gathered),
        recurrence_suspects(gathered),
        never_fired_always_loaded(_always_loaded_ids(resolved), fired),
        condition_row,
        {
            "kind": "consolidation-policy",
            "value": (
                "File a kind: maintenance case. Its first sheet notes every source: "
                "consolidation proposed, successor case <id>. Only a later run's successor "
                "case may reroute and retire the sources."
            ),
        },
    ]
