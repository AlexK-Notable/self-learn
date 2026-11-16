"""Per-skill editorial permission and conservative adoption (S-157).

Registration never transfers authorship. All decisions are repeated with the
ledger lock held; adoption additionally holds the skills-root host lock.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from functools import partial
from pathlib import Path

from . import gitops, intents, scan, skill_registry, skill_writer
from .hosts import HostsError, host_mode, load_hosts, validate_host_path
from .primitives import chrono, fsops
from .selfcheck import claude_runtime_dir
from .skill_scaffold import _read_frontmatter


class RegistrationError(ValueError):
    """A named check refused registration before granting permission."""


def _note_by(note: str, by: str) -> None:
    if not isinstance(note, str) or not note.strip():
        raise RegistrationError("--note must explain why")
    hits = scan.scan(note)
    if hits:
        raise RegistrationError("--note secret scan refused: " + ", ".join(sorted({hit.rule for hit in hits})))
    if by not in ("human", "agent"):
        raise RegistrationError("registration attribution must be human or agent")


def _repository(path: Path) -> Path | None:
    # Handles worktrees (.git is a file), nested repositories and bare roots.
    for parent in (path, *path.parents):
        if (parent / ".git").exists() or ((parent / "HEAD").is_file() and (parent / "objects").is_dir()):
            return parent.resolve()
    return None


def _resolve(home: Path, argument: str) -> tuple[Path, Path]:
    hosts = load_hosts(home)
    if hosts.skills_root is None:
        raise RegistrationError("no skills root is registered")
    root = validate_host_path(home, hosts.skills_root, "skills-root").resolve()
    if "/" in argument or argument.startswith(".") or argument.startswith("~"):
        path = Path(argument).expanduser().absolute()
    else:
        choices = list(root.glob(f"plugins/*/skills/{argument}"))
        if len(choices) > 1:
            raise RegistrationError(f"ambiguous skill name: {argument}")
        path = choices[0] if choices else claude_runtime_dir() / "skills" / argument
    if not path.is_dir():
        raise RegistrationError(f"skill directory does not exist: {path}")
    return root, path


def _inspect(root: Path, path: Path) -> tuple[str, str, list[str]]:
    real = path.resolve(strict=True)
    name = path.name
    if not skill_writer._valid_name(name):
        raise RegistrationError("name-not-kebab: skill folder name must be kebab-case")
    md = real / "SKILL.md"
    if md.is_symlink():
        raise RegistrationError("SKILL.md is a symlink; registration requires local files")
    try:
        text = md.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RegistrationError(f"SKILL.md is not readable: {exc}") from exc
    front = _read_frontmatter(text)
    if front.mapping is None or front.finding:
        raise RegistrationError("SKILL.md: " + (front.finding.rule if front.finding else "frontmatter-unparseable"))
    if front.mapping.get("name") != name:
        raise RegistrationError(f"name-dir-mismatch: frontmatter name must match {name}")
    description = front.mapping.get("description")
    if not isinstance(description, str) or not description.strip():
        # A full rewrite can supply this editable field. The adoption package
        # needs a label now; preserve the actual SKILL.md until that rewrite.
        description = f"User-maintained skill {name}."
    if front.mapping.get("metadata") is not None and not isinstance(front.mapping["metadata"], dict):
        raise RegistrationError("metadata-not-mapping: metadata must be a mapping to preserve it when stamping")
    claude = claude_runtime_dir().resolve()
    agents = Path(os.environ.get("SELF_LEARN_AGENTS_DIR", str(Path.home() / ".agents"))).expanduser().resolve()
    codex = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    signals = [
        ((real / ".aws-skill-metadata").exists(), ".aws-skill-metadata"),
        (real.is_relative_to(agents), "under .agents/"),
        (real.is_relative_to(claude / "plugins"), "under Claude plugins/"),
        (real.is_relative_to(claude / "skills" / "synced"), "under Claude skills/synced/"),
        ("node_modules" in real.parts, "under node_modules/"),
        (real.is_relative_to(codex / "skills" / ".system"), "under Codex skills/.system/"),
        ("LOCAL ADDITIONS BELOW" in text, "LOCAL ADDITIONS BELOW upstream marker"),
        (isinstance(front.mapping.get("metadata"), dict) and "upstream" in front.mapping["metadata"], "metadata.upstream"),
    ]
    for present, signal in signals:
        if present:
            raise RegistrationError(f"outside-maintained skill: {signal}")
    lock = agents / ".skill-lock.json"
    if lock.exists():
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
                raise ValueError("expected a skills mapping")
        except (ValueError, OSError) as exc:
            raise RegistrationError(f"cannot check .skill-lock.json: {exc}") from exc
        if name in data["skills"] or real.name in data["skills"]:
            raise RegistrationError("outside-maintained skill: listed in .skill-lock.json")
    repo = _repository(real)
    if repo is not None and repo != root:
        raise RegistrationError(f"inside another git repository: {repo}")
    target = skill_writer.skill_dir(root, name)
    if real.is_relative_to(root) and real != target:
        raise RegistrationError(f"inside skills root but not in plugins/{name}/skills/{name}")
    if real != target and (repo is not None or path.is_symlink()):
        raise RegistrationError("adoption requires a loose real directory with no repository")
    # No linked descendants: copying or later writing them could escape the skill.
    if any(p.is_symlink() for p in real.rglob("*")):
        raise RegistrationError("skill contains symlinks; cannot safely adopt or edit")
    return name, description, ["readable-frontmatter", "matching-name", "no-installer-signals", "no-upstream-marker", "repository-location", "no-linked-files"]


def _put(registry: skill_registry.Registry, *, name: str, row: dict) -> None:
    registry.registrations[name] = row


def _withdraw(registry: skill_registry.Registry, *, name: str, note: str, by: str) -> None:
    if not registry.is_registered(name):
        raise RegistrationError(f"{name} is not registered")
    row = registry.registrations[name]
    row["status"] = "withdrawn"
    row["withdrawn"] = {"at": chrono.now_iso(), "by": by, "note": note.strip()}


def unregister(home: Path | str, name: str, *, note: str, by: str) -> dict:
    _note_by(note, by)
    sha = skill_registry.with_update(home, partial(_withdraw, name=name, note=note, by=by),
        subject=f"skill unregister {name}", body=f"By: {by}\nWhy: {note.strip()}")
    return {"name": name, "state": "unregistered", "ledger_commit": sha}


def register(home: Path | str, argument: str, *, note: str, by: str) -> dict:
    _note_by(note, by)
    home = Path(home)
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
        try:
            root, path = _resolve(home, argument)
        except HostsError as exc:
            raise RegistrationError(str(exc)) from exc
        with gitops.host_lock(root, host_mode(home, root, registration="skills-root")):
            try:
                return _register_locked(home, root, path, note=note, by=by)
            except skill_writer._Refused as exc:
                raise RegistrationError("; ".join(exc.problems)) from exc
            except skill_writer.SkillLinkError as exc:
                raise RegistrationError(str(exc)) from exc


def _register_locked(home: Path, root: Path, path: Path, *, note: str, by: str) -> dict:
    name, description, checks = _inspect(root, path)
    registry = skill_registry.load(home)
    if registry.veto_of(name):
        raise RegistrationError(f"{name} is vetoed")
    if registry.is_owned(name):
        raise RegistrationError(f"{name} is already owned by self-learn; nothing to register")
    if registry.is_registered(name):
        if registry.registrations[name]["registered"]["path"] != str(path.resolve()):
            raise RegistrationError(f"{name} is registered at a different path; unregister and register again")
        _repair_links(root, name, registry.registrations[name]["registered"])
        return {"name": name, "state": "already registered"}
    if name in registry.skills:
        raise RegistrationError(f"{name} has an ownership history; choose a different name")
    target = skill_writer.skill_dir(root, name)
    original = path.resolve()
    backup = None
    host_sha = None
    if original != target:
        backup, host_sha = _adopt(home, root, original, name, description, by)
    if original == target:
        skill_writer.link_skill(root, name)
    row = {"status": "live", "plugin": f"plugins/{name}", "registered": {
        "at": chrono.now_iso(), "by": by, "note": note.strip(),
        "path": str(target.resolve()), "original": str(original),
        "backup": str(backup) if backup else None, "checks": checks,
        "authored_sha256": skill_writer.authored_sha256_at(root, name),
    }}
    sha = skill_registry.with_update(home, partial(_put, name=name, row=row),
        subject=f"skill register {name}", body=f"By: {by}\nWhy: {note.strip()}")
    return {"name": name, "state": "registered", "adopted": backup is not None,
        "backup": str(backup) if backup else None, "path": str(target),
        "ledger_commit": sha, "host_commit": host_sha}


def _same_tree(folder: Path, backup: Path) -> bool:
    """A failed cross-device move may leave either copy incomplete."""
    if not folder.is_dir():
        return False
    paths = {p.relative_to(folder) for p in folder.rglob("*")}
    if paths != {p.relative_to(backup) for p in backup.rglob("*")}:
        return False
    return all((folder / p).is_dir() == (backup / p).is_dir()
        and ((folder / p).is_dir() or (folder / p).read_bytes() == (backup / p).read_bytes())
        for p in paths)


def _adopt(home: Path, root: Path, original: Path, name: str, description: str, by: str) -> tuple[Path, str | None]:
    try:
        skill_writer._skills_root(home)  # git mode and marketplace required
    except skill_writer._Refused as exc:
        raise RegistrationError("adoption needs a git-mode skills root with a marketplace: " + "; ".join(exc.problems)) from exc
    plugin = root / "plugins" / name
    target = skill_writer.skill_dir(root, name)
    market = root / ".claude-plugin" / "marketplace.json"
    runtime = skill_writer.link_path(name)
    if plugin.exists() or plugin.is_symlink():
        raise RegistrationError(f"adoption target already exists: {plugin}")
    if runtime != original and (runtime.exists() or runtime.is_symlink()):
        raise RegistrationError(f"runtime link already exists: {runtime}")
    if skill_writer._dirty_under(root, [market, plugin]):
        raise RegistrationError("uncommitted changes in adoption target or marketplace")
    before = market.read_text(encoding="utf-8")
    data, _ = skill_writer._read_marketplace(before)
    if skill_writer._entries_named(data, name):
        raise RegistrationError(f"marketplace already names {name}")
    after = skill_writer._marketplace_with(before, name, description)
    manifest, _ = skill_writer._manifest_text(None, name, description)
    # Cache backups are scoped to this ledger and retained after adoption.
    from .worker import cache_dir
    backup = cache_dir(home) / "skill-adoptions" / f"{name}-{chrono.now_iso().replace(':', '')}-{uuid.uuid4().hex[:8]}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(original, backup)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(original), str(target))
        (plugin / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        fsops.atomic_write(plugin / ".claude-plugin" / "plugin.json", manifest or "")
        fsops.atomic_write(market, after)
        sha = gitops.stage_and_commit(root, [plugin, market], f"self-learn: skill adopt {name}", f"By: {by}")
    except Exception as exc:
        failures = [f"adoption failed ({type(exc).__name__})"]
        # Leave an untouched original alone. Move a complete copy back without
        # deleting it first; only a partial move needs the retained backup.
        try:
            if original.exists() and _same_tree(original, backup):
                pass
            elif not original.exists() and target.exists() and _same_tree(target, backup):
                try:
                    os.rename(target, original)
                except OSError:
                    shutil.copytree(backup, original)
            elif target.exists() or not _same_tree(original, backup):
                if original.exists():
                    shutil.rmtree(original)
                shutil.copytree(backup, original)
        except Exception as restore_exc:
            failures.append(f"restore {original}: {type(restore_exc).__name__}")
        try:
            if plugin.exists():
                shutil.rmtree(plugin)
        except Exception as cleanup_exc:
            failures.append(f"remove {plugin}: {type(cleanup_exc).__name__}")
        try:
            fsops.atomic_write(market, before)
        except Exception as market_exc:
            failures.append(f"restore {market}: {type(market_exc).__name__}")
        try:
            gitops.unstage(root, [plugin, market])
        except Exception as index_exc:
            failures.append(f"clean git index: {type(index_exc).__name__}")
        raise RegistrationError("; ".join(failures) + f"; backup: {backup}") from exc
    try:
        skill_writer._place_link(original, target)
    except Exception as exc:
        # The host commit landed. Retry the link only; never undo that commit.
        try:
            skill_writer._place_link(original, target)
        except Exception as link_exc:
            raise RegistrationError(f"adoption committed; repair link {original} -> {target}; backup: {backup}") from link_exc
    return backup, sha


def _repair_links(root: Path, name: str, stamp: dict) -> None:
    original = Path(stamp["original"])
    target = skill_writer.skill_dir(root, name)
    if original == target:
        skill_writer.link_skill(root, name)
    else:
        skill_writer._place_link(original, target)
