"""U-pointer (the reachability emitter): per-destination, per-record
proof that a compiled canon file would actually be LOADED by a session —
distinct from ``_check_drift`` ("did the write land?") and from
``_check_reach`` ("does the `reference` pointer name the target?", wholly
owned, never touched here).

**The one-sentence contract:** a check that cannot see its target must
never print "reachable" (`lrn-ea833a5b`, `lrn-6d21607e`). Every predicate
below terminates in exactly one of three states — ``reachable`` /
``unreachable`` / ``unmeasurable`` — and ``unmeasurable`` is a first-class
value, never collapsed into either determined state (see this module's
own :class:`Verdict`, the per-record dataclass below — distinct from
``selfcheck.Verdict``, a separate PASS/FAIL/UNMEASURED enum; fold r2,
2026-09-04, gate r1 nit 1: two exported types share the name `Verdict`
in this package, and this cross-reference used to be ambiguous about
which one it meant).

**One predicate, two renderers (spec §4.3, NORMATIVE).** This module
exposes exactly one entry point, :func:`reachability_rows`. Both
``selfcheck._check_surface`` and ``report._surface_reach`` call it and
render the SAME verdict list two different ways; neither may re-derive,
re-probe, or recompute a field — including a `settings.json` read, which
this module performs exactly once per call, inside :func:`read_instrument`.

**Undocumented-but-necessary design note.** Two facts a renderer needs —
the instrument's per-facet usability (§5.5, §6 rule 2's nulling table) and
the count of resolved records that failed to even parse (§5.6's
``unparseable_records``) — are not per-:class:`Verdict` fields, and a
renderer reading ``settings.json`` or re-walking ``discover_buckets`` +
``Record.from_path`` itself to recover them would be exactly the "two
implementations of one predicate" divergence §4.3 forbids. Rather than
widen :func:`reachability_rows`'s NORMATIVE signature (fixed at
``-> list[Verdict]``), this module attaches them as extra, defaulted
attributes on the returned list (a :class:`VerdictList`, a ``list``
subclass) — computed once, during the single domain walk / instrument
read already inside this function. A caller that only needs the bare
list (any stub in ``T-ONE-PREDICATE``'s monkeypatch, or a caller passing
a plain ``list``) still type-checks and still works: every attribute read
off it goes through ``getattr(..., <default>)``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import domain
from .compilers import has_paths_key, read_paths_frontmatter
from .hosts import HostsError, load_hosts
from .ledger import Bucket, discover_buckets
from .ledger_ops import bucket_project_path, glob_reaches
from .records import Record, RecordError
from .verbs import (
    _project_rules_dir,
    _user_reachability_roots,
    _user_rules_dir,
    managed_target_for,
)

__all__ = ["Instrument", "Verdict", "VerdictList", "read_instrument", "reachability_rows"]

#: §5.6: the destinations this unit's domain covers. `reference` is
#: wholly owned by `_check_reach` + `report._reference_shelf` (§3, §9.1)
#: and is deliberately excluded — a second predicate over one destination
#: is the masking trap `selfcheck.py:288-296` names.
_DOMAIN_DESTINATIONS = ("skill-md", "claude-md", "new-skill", "hook")


@dataclass(frozen=True)
class Verdict:
    """One record's reachability verdict — §5.0, NORMATIVE."""

    record_id: str
    bucket: str
    scope: str
    destination: str
    variant: str | None
    target: str | None
    state: str
    reason: str
    detail: str


class VerdictList(list):
    """``list[Verdict]`` plus the non-per-record domain facts both
    renderers need (see the module docstring). Defaulted so a stub
    (``T-ONE-PREDICATE``) or a plain ``list`` return still behaves."""

    unparseable_records: int = 0
    instrument_state: str = "ok"
    claude_dir_usable: bool = True
    settings_usable: bool = True


@dataclass(frozen=True)
class Instrument:
    """§5.5: the operator's live configuration, read ONCE per
    :func:`reachability_rows` call and handed to every predicate — no
    predicate opens `settings.json` (or `known_marketplaces.json`) itself.

    Two facets, not one blanket flag (r1 M-A): `claude_dir_usable` and
    `settings_usable` are independent, so a broken `settings.json` never
    blanks a predicate that never reads it (§4.4a)."""

    state: str  # "ok" | "claude-dir-absent" | "settings-absent" | "settings-unparseable"
    claude_dir_usable: bool
    settings_usable: bool
    claude_dir: Path
    enabled_plugins: dict[str, bool]
    skill_overrides: dict[str, str]
    marketplaces: dict[str, str]  # marketplace name -> installLocation (§5.1A)
    hook_registrations: tuple[tuple[str, str, str], ...]  # (event, matcher, command)
    problem: str | None


def read_instrument(claude_dir: Path) -> Instrument:
    """§5.5: the four-state instrument reader. Never raises — an
    unreadable/absent file degrades a facet, it never crashes the caller
    (a check that crashes reports nothing)."""
    claude_dir = Path(claude_dir)
    if not claude_dir.is_dir():
        return Instrument(
            state="claude-dir-absent",
            claude_dir_usable=False,
            settings_usable=False,
            claude_dir=claude_dir,
            enabled_plugins={},
            skill_overrides={},
            marketplaces={},
            hook_registrations=(),
            problem=None,
        )

    enabled_plugins: dict[str, bool] = {}
    skill_overrides: dict[str, str] = {}
    hook_registrations: list[tuple[str, str, str]] = []
    state = "ok"
    problem: str | None = None
    settings_usable = True

    settings_path = claude_dir / "settings.json"
    if not settings_path.is_file():
        state = "settings-absent"
    else:
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            state = "settings-unparseable"
            settings_usable = False
            problem = f"unparseable {settings_path}: {exc}"
            data = None
        if isinstance(data, dict):
            ep = data.get("enabledPlugins")
            if isinstance(ep, dict):
                enabled_plugins = {
                    k: bool(v) for k, v in ep.items() if isinstance(k, str)
                }
            so = data.get("skillOverrides")
            if isinstance(so, dict):
                skill_overrides = {
                    k: v for k, v in so.items() if isinstance(k, str) and isinstance(v, str)
                }
            hooks_cfg = data.get("hooks")
            if isinstance(hooks_cfg, dict):
                for event, entries in hooks_cfg.items():
                    if not isinstance(event, str) or not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        matcher = entry.get("matcher")
                        matcher_str = matcher if isinstance(matcher, str) else ""
                        for hook in entry.get("hooks") or []:
                            cmd = hook.get("command") if isinstance(hook, dict) else None
                            if isinstance(cmd, str):
                                hook_registrations.append((event, matcher_str, cmd))

    # known_marketplaces.json (§5.1A) — the CLAUDE-DIR facet, not settings:
    # a read failure here leaves `marketplaces` empty and never sets
    # `settings-unparseable` (§5.5's rule — two different files, two
    # different remedies).
    marketplaces: dict[str, str] = {}
    mk_path = claude_dir / "plugins" / "known_marketplaces.json"
    if mk_path.is_file():
        try:
            mk_data = json.loads(mk_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            mk_data = None
        if isinstance(mk_data, dict):
            for name, entry in mk_data.items():
                if not isinstance(name, str) or not isinstance(entry, dict):
                    continue
                loc = entry.get("installLocation")
                if isinstance(loc, str):
                    marketplaces[name] = loc

    return Instrument(
        state=state,
        claude_dir_usable=True,
        settings_usable=settings_usable,
        claude_dir=claude_dir,
        enabled_plugins=enabled_plugins,
        skill_overrides=skill_overrides,
        marketplaces=marketplaces,
        hook_registrations=tuple(hook_registrations),
        problem=problem,
    )


# ------------------------------------------------------- RP-SKILL (§5.1)


def _resolve_plugin_root(instrument: Instrument, plugin: str, marketplace: str) -> Path | None:
    """§5.1A steps 1-3: the plugin's root dir, or `None` when undecidable
    at any step (missing installLocation, non-dir installLocation,
    unreadable/unparseable marketplace.json, no matching plugin entry, or
    a non-string `source`)."""
    install = instrument.marketplaces.get(marketplace)
    if install is None:
        return None
    install_path = Path(install)
    if not install_path.is_dir():
        return None
    mp_json = install_path / ".claude-plugin" / "marketplace.json"
    try:
        data = json.loads(mp_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        return None
    entry = next(
        (p for p in plugins if isinstance(p, dict) and p.get("name") == plugin), None
    )
    if entry is None:
        return None
    source = entry.get("source")
    if not isinstance(source, str):
        return None
    try:
        return (install_path / source).resolve()
    except OSError:
        return None


def _install_is_ancestor_or_equal(install: str | None, target: Path) -> bool:
    """§5.1A′'s second in-scope disjunct."""
    if install is None:
        return False
    try:
        install_resolved = Path(install).resolve()
    except OSError:
        return False
    return target == install_resolved or install_resolved in target.parents


def _rp_skill(claude_dir: Path, instrument: Instrument, target: Path | None) -> tuple[str, str, str]:
    """§5.1B: rows 1-10, first row that applies decides."""
    if target is None:
        return "unmeasurable", "target-unresolvable", (
            "the compiled skill target could not be resolved via hosts.yaml"
        )
    if not target.is_file():
        return "unmeasurable", "target-missing", (
            f"compiled SKILL.md {target} does not exist — run `self-learn recompile`"
        )
    if not instrument.claude_dir_usable:
        return "unmeasurable", "claude-dir-absent", (
            f"{claude_dir} does not exist — reachability not checked"
        )
    if not instrument.settings_usable:
        return "unmeasurable", "settings-unparseable", (
            instrument.problem or "settings.json unparseable"
        )

    name = target.parent.name
    decidable_true = False
    decidable_false = False
    undecidable_in_scope = False
    resolved_plugin_for_target: str | None = None

    for key, enabled in instrument.enabled_plugins.items():
        plugin, sep, marketplace = key.partition("@")
        if not sep:
            continue
        plugin_root = _resolve_plugin_root(instrument, plugin, marketplace)
        if plugin_root is None:
            # §5.1A′: undecidable — count for row 9 ONLY if in scope for
            # THIS target (plugin name matches, or the marketplace's
            # installLocation is target or an ancestor of it).
            if plugin == name or _install_is_ancestor_or_equal(
                instrument.marketplaces.get(marketplace), target
            ):
                undecidable_in_scope = True
            continue
        candidate = plugin_root / "skills" / name / "SKILL.md"
        try:
            candidate = candidate.resolve()
        except OSError:
            pass
        if candidate == target:
            if resolved_plugin_for_target is None:
                resolved_plugin_for_target = plugin
            if enabled:
                decidable_true = True
            else:
                decidable_false = True

    # row 5: skillOverrides — bare form (personal-symlink skills) or
    # `<plugin>:<skill>` (§5.1C) when §5.1A resolved a plugin for THIS
    # target. Checked before rows 6-10: an override wins over a working
    # discovery route.
    override_hit = instrument.skill_overrides.get(name) == "off"
    if not override_hit and resolved_plugin_for_target is not None:
        override_hit = (
            instrument.skill_overrides.get(f"{resolved_plugin_for_target}:{name}") == "off"
        )
    if override_hit:
        return "unreachable", "skill-override-off", f"skillOverrides marks {name!r} off"

    # row 6: the personal symlink — exists()/.resolve() follow symlinks,
    # so a DANGLING <claude_dir>/skills/<name> reads as absent (falls
    # through to row 10), never as reachable.
    personal = claude_dir / "skills" / name / "SKILL.md"
    if personal.exists():
        try:
            if personal.resolve() == target:
                return "reachable", "personal-skill-link", f"{personal} resolves to {target}"
        except OSError:
            pass

    # rows 7-9: iterate the whole enabledPlugins map, but row 9 counts
    # only in-scope entries (§5.1A′) — computed above.
    if decidable_true:
        return "reachable", "enabled-plugin", (
            f"an enabledPlugins entry resolves to {target} and is enabled"
        )
    if decidable_false:
        return "unreachable", "plugin-disabled", (
            f"an enabledPlugins entry resolves to {target} and is disabled"
        )
    if undecidable_in_scope:
        return "unmeasurable", "plugin-route-undecidable", (
            "an in-scope enabledPlugins entry could not be resolved to a plugin root"
        )
    return "unreachable", "not-indexed", (
        f"{target} is not named by any resolvable discovery route (no personal symlink, "
        "no enabledPlugins match)"
    )


# --------------------------------------------------------- RP-CMD (§5.2)


def _rp_cmd(
    claude_dir: Path,
    bucket: Bucket,
    record: Record,
    routing: dict,
    instrument: Instrument,
    target: Path | None,
    skills_root: Path | None,
) -> tuple[str, str, str]:
    """§5.2: rows 1-8. `variant == "local"` is checked ahead of the
    user-scope branch, mirroring `managed_target_for`'s own precedence
    (its local branch never inspects `record.scope`)."""
    if target is None:
        return "unmeasurable", "target-unresolvable", (
            "the compiled claude-md target could not be resolved via hosts.yaml"
        )

    variant = routing.get("variant")
    if variant != "local" and record.scope == "user":
        if not instrument.claude_dir_usable:
            return "unmeasurable", "claude-dir-absent", (
                f"{claude_dir} does not exist — reachability not checked"
            )
        if not target.is_file():
            return "unmeasurable", "target-missing", (
                f"{target} does not exist — run `self-learn recompile`"
            )
        # §11 Q5: with B1's threading, target IS <claude_dir>/CLAUDE.md by
        # construction — row 4 is true whenever rows 1-3 pass.
        return "reachable", "user-memory-file", (
            f"{target} is the user CLAUDE.md the loader reads at session start"
        )

    if variant == "local" or record.scope == "project":
        host_root = bucket_project_path(bucket.path)
    else:
        host_root = skills_root
    host_root = Path(host_root) if host_root is not None else None

    if host_root is None or not host_root.is_dir():
        return "unmeasurable", "host-missing", (
            f"the host directory for {record.scope!r} no longer exists on disk"
        )
    if not target.is_file():
        return "unmeasurable", "target-missing", (
            f"{target} does not exist — run `self-learn recompile`"
        )
    try:
        host_root_resolved = host_root.resolve()
    except OSError:
        host_root_resolved = host_root

    if target.parent == host_root_resolved and target.name == "CLAUDE.md":
        return "reachable", "project-root-memory-file", (
            f"{target} sits at the registered host root, where the loader scans at "
            "session start — this does NOT prove any session ever opens this project "
            "as its cwd (a static check cannot answer that)"
        )
    if target.name == "CLAUDE.local.md" and target.parent == host_root_resolved:
        return "reachable", "project-local-memory-file", (
            f"{target} sits at the registered host root — same session-start-scan "
            "caveat as project-root-memory-file, and CLAUDE.local.md is git-excluded "
            "by design, so it is LESS DURABLE than the thing it may point at"
        )
    return "unreachable", "not-on-a-loaded-path", (
        f"{target} is not at a path the loader scans for scope {record.scope!r}"
    )


# ------------------------------------------------------- RP-RULES (§5.3)


def _rp_rules(
    home: Path,
    claude_dir: Path,
    bucket: Bucket,
    record: Record,
    routing: dict,
    instrument: Instrument,
    target: Path | None,
    user_claude_md: Path,
) -> tuple[str, str, str]:
    if target is None:
        return "unmeasurable", "target-unresolvable", (
            "the rules target could not be resolved via hosts.yaml"
        )

    is_user = record.scope == "user"
    if is_user and not instrument.claude_dir_usable:
        return "unmeasurable", "claude-dir-absent", (
            f"{claude_dir} does not exist — reachability not checked"
        )
    if not target.is_file():
        return "unmeasurable", "target-missing", (
            f"{target} does not exist — run `self-learn recompile`"
        )

    if is_user:
        expected_dir = _user_rules_dir(user_claude_md).resolve()
        roots = _user_reachability_roots(home, user_claude_md)
    else:
        host = bucket_project_path(bucket.path)
        if host is None:
            return "unreachable", "rules-dir-off-loaded-path", (
                f"{target} has no registered project host to scan against"
            )
        expected_dir = _project_rules_dir(Path(host)).resolve()
        roots = (Path(host),)

    try:
        target_parent = target.parent.resolve()
    except OSError:
        target_parent = target.parent
    if target_parent != expected_dir:
        return "unreachable", "rules-dir-off-loaded-path", (
            f"{target} is not inside the scanned rules directory {expected_dir}"
        )

    # step 3: the ratified zero-match / legacy bypass, BEFORE any glob
    # probe (r1 M-D). A "budget" bypass is NOT exempt — U-glob §6.6's
    # asymmetry, kept verbatim.
    bypass_reason = routing.get("glob_bypass_reason")
    legacy_bypass = (
        routing.get("allow_empty_glob") is True and "glob_bypass_reason" not in routing
    )
    if bypass_reason == "zero-match" or legacy_bypass:
        bypass_name = bypass_reason if bypass_reason is not None else "legacy allow_empty_glob"
        return "reachable", "bypass-approved", (
            f"routed under the approved zero-match bypass ({bypass_name}) — the router's "
            "write-the-rule-first route (§5.3 step 3)"
        )

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return "unmeasurable", "frontmatter-unreadable", f"{target} not readable as UTF-8 ({exc})"

    ledger_paths = tuple(routing.get("rules_paths") or ())

    if not has_paths_key(text):
        return "reachable", "loads-unconditionally", (
            f"{target} carries no `paths:` frontmatter — U-glob §8.1A's evidence: this "
            "loads at load_reason session_start regardless of any glob"
        )

    paths = read_paths_frontmatter(text)
    drift_note = ""
    if paths and ledger_paths and tuple(paths) != ledger_paths:
        drift_note = (
            f" (frontmatter drift: file paths {list(paths)} differ from the ledger's "
            f"routing.rules_paths {list(ledger_paths)})"
        )

    if not paths:
        return "reachable", "loads-unconditionally", (
            f"{target} carries a `paths:` key with no usable value — U-glob §8.1A's "
            "evidence: this loads at load_reason session_start regardless of any glob"
        )

    verdicts = [glob_reaches(roots, p) for p in paths]
    roots_str = ", ".join(str(r) for r in roots)
    if all(v == "none" for v in verdicts):
        return "unreachable", "globs-match-nothing", (
            f"none of {list(paths)} match under {roots_str}{drift_note}"
        )
    if any(v == "match" for v in verdicts):
        return "reachable", "globs-match", f"{list(paths)} match under {roots_str}{drift_note}"
    return "unmeasurable", "glob-budget-exhausted", (
        f"could not determine within the reachability budget under {roots_str}{drift_note}"
    )


# -------------------------------------------------------- RP-HOOK (§5.4)


def _matcher_covers(matcher: str, tool: str) -> bool | None:
    """`None` = the matcher is not a valid regex (§5.4 row 8)."""
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return None


def _rp_hook(
    claude_dir: Path,
    record: Record,
    routing: dict,
    instrument: Instrument,
    skills_root: Path | None,
) -> tuple[str, str, str, Path | None]:
    meta = routing.get("hook") or {}
    rel = meta.get("script_path")
    if rel is None or skills_root is None:
        return "unmeasurable", "target-unresolvable", (
            "no routing.hook.script_path, or no skills root registered"
        ), None
    script = (skills_root / rel).resolve()
    if not script.is_file():
        return "unmeasurable", "target-missing", (
            f"hook script {script} does not exist — run `self-learn recompile`"
        ), script
    if not instrument.claude_dir_usable:
        return "unmeasurable", "claude-dir-absent", (
            f"{claude_dir} does not exist — reachability not checked"
        ), script
    if not instrument.settings_usable:
        return "unmeasurable", "settings-unparseable", (
            instrument.problem or "settings.json unparseable"
        ), script
    if instrument.state == "settings-absent":
        return "unreachable", "no-registrations", (
            f"{claude_dir / 'settings.json'} does not exist — no hooks are registered at all"
        ), script

    script_name = script.name
    matching_any = [
        (event, matcher)
        for (event, matcher, command) in instrument.hook_registrations
        if Path(command).name == script_name
    ]
    if not matching_any:
        return "unreachable", "not-registered", (
            f"no settings.json registration names {script_name}"
        ), script
    pretooluse = [(event, matcher) for event, matcher in matching_any if event == "PreToolUse"]
    if not pretooluse:
        events = ", ".join(sorted({e for e, _m in matching_any}))
        return "unreachable", "wrong-event", (
            f"{script_name} is registered only under {events}, never PreToolUse"
        ), script

    matcher = pretooluse[0][1]
    tools = meta.get("tools") or []
    results = [_matcher_covers(matcher, t) for t in tools]
    if any(r is None for r in results):
        return "unmeasurable", "matcher-unparseable", (
            f"matcher {matcher!r} is not a valid regex"
        ), script
    if not all(results):
        return "unreachable", "matcher-mismatch", (
            f"matcher {matcher!r} does not cover every guarded tool {tools}"
        ), script
    return "reachable", "registered", (
        f"{script_name} is registered under PreToolUse with matcher {matcher!r}"
    ), script


# ------------------------------------------------------------- dispatch


def _variant_for(destination: str, routing: dict) -> str | None:
    if destination == "claude-md":
        return routing.get("variant")
    return None


def _verdict_for(
    home: Path,
    claude_dir: Path,
    bucket: Bucket,
    record: Record,
    routing: dict,
    destination: str,
    instrument: Instrument,
    user_claude_md: Path,
    skills_root: Path | None,
) -> Verdict:
    variant = _variant_for(destination, routing)

    if destination in ("skill-md", "new-skill"):
        target = managed_target_for(home, bucket, record, user_claude_md=user_claude_md)
        state, reason, detail = _rp_skill(claude_dir, instrument, target)
    elif destination == "claude-md":
        target = managed_target_for(home, bucket, record, user_claude_md=user_claude_md)
        if variant == "rules":
            state, reason, detail = _rp_rules(
                home, claude_dir, bucket, record, routing, instrument, target, user_claude_md
            )
        else:
            state, reason, detail = _rp_cmd(
                claude_dir, bucket, record, routing, instrument, target, skills_root
            )
    else:  # "hook"
        state, reason, detail, target = _rp_hook(
            claude_dir, record, routing, instrument, skills_root
        )

    return Verdict(
        record_id=record.id,
        bucket=bucket.path.relative_to(home).as_posix(),
        scope=record.scope,
        destination=destination,
        variant=variant,
        target=str(target) if target is not None else None,
        state=state,
        reason=reason,
        detail=detail,
    )


def reachability_rows(
    home: Path,
    claude_dir: Path,
    *,
    user_claude_md: Path | None = None,
) -> list[Verdict]:
    """§4.3: the ONE entry point. `user_claude_md` defaults to
    `claude_dir / "CLAUDE.md"` — never `DEFAULT_USER_CLAUDE_MD`, never
    `Path.home()`, never a second `~` expansion — computed once, here,
    and threaded to every user-scope resolver this call makes.

    §5.6: the domain is every bucket `discover_buckets` returns
    (`skills/*`, `projects/*`, the single one-level `user/` bucket —
    NEVER a `<home>/*/*/resolved/` glob), filtered to
    `status == "routed"`, `superseded_by is None`,
    `destination in ("skill-md", "claude-md", "new-skill", "hook")`.
    `reference` is excluded (§3, §9.1) by construction — it is simply not
    in that destination set."""
    home = Path(home)
    claude_dir = Path(claude_dir)
    resolved_user_claude_md = (
        Path(user_claude_md) if user_claude_md is not None else (claude_dir / "CLAUDE.md")
    )

    instrument = read_instrument(claude_dir)
    try:
        skills_root = load_hosts(home).skills_root
    except HostsError:
        skills_root = None

    rows: list[Verdict] = []
    unparseable = 0

    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except (RecordError, UnicodeDecodeError):
                unparseable += 1
                continue
            if not domain.is_canon_live(record):
                continue
            routing = record.routing or {}
            destination = routing.get("destination")
            if destination not in _DOMAIN_DESTINATIONS:
                continue
            rows.append(
                _verdict_for(
                    home,
                    claude_dir,
                    bucket,
                    record,
                    routing,
                    destination,
                    instrument,
                    resolved_user_claude_md,
                    skills_root,
                )
            )

    result = VerdictList(rows)
    result.unparseable_records = unparseable
    result.instrument_state = instrument.state
    result.claude_dir_usable = instrument.claude_dir_usable
    result.settings_usable = instrument.settings_usable
    return result
