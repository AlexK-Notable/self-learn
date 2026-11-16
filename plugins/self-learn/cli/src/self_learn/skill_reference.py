"""S-159: bundled authoring evidence, optional native examples, offline status."""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from ruamel.yaml import YAML

PACK_DIR = Path(__file__).with_suffix("")
VERSION = "anthropic-2026-11-15"
READ_DATE = "2026-11-15"
NORMALIZATION = "markdown-nfc-whitespace-v1"
BP = "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices"
OV = "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview"
SPEC = "https://agentskills.io/specification"
CC = "https://code.claude.com/docs/en/skills"


def sources() -> list[dict]:
    return YAML(typ="safe").load((PACK_DIR / "sources.yaml").read_text())["sources"]


def normalize(text: str) -> str:
    """Markdown endpoints avoid volatile HTML hydration/navigation data.

    Preserve every non-whitespace character, including links and code; collapse
    whitespace and Unicode canonical spelling only. No dates/content stripped.
    """
    return " ".join(unicodedata.normalize("NFC", text).split())


def digest(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def fetch_text(url: str) -> str:
    request = Request(url, headers={"Accept": "text/markdown, text/plain", "User-Agent": "self-learn-skill-reference/1"})
    with urlopen(request, timeout=20) as response:
        data = response.read(4_000_001)
        if len(data) > 4_000_000:
            raise ValueError("source exceeds 4 MB")
        text = data.decode("utf-8")
        if not text.strip() or re.search(r"<(?:!doctype|html)\b", text[:500], re.I):
            raise ValueError("expected nonempty Markdown, received HTML or empty response")
        return text


def status_path(home: Path) -> Path:
    from .cache_gc import cache_root, home_digest
    return cache_root() / ("home-" + home_digest(home)) / "skill-reference-status.json"


def record_status(home: Path, result: dict) -> None:
    from .primitives import fsops
    path = status_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(path, json.dumps(result, sort_keys=True) + "\n")


def status(home: Path, *, fetch: bool = False, fetcher=None, today: date | None = None) -> dict:
    result = {"version": VERSION, "date_read": READ_DATE,
              "age_days": ((today or date.today()) - date.fromisoformat(READ_DATE)).days,
              "normalization": NORMALIZATION, "sources": sources()}
    if fetch:
        get = fetcher or fetch_text
        checks = []
        for source in result["sources"]:
            item = {"url": source["url"]}
            try:
                sha = digest(get(source["url"]))
                item.update(state="unchanged" if sha == source["sha256"] else "changed", sha256=sha)
            except Exception as exc:
                # No response bodies or network credentials in the status record.
                item.update(state="unreachable", error=type(exc).__name__)
            checks.append(item)
        result.update(checked_at=datetime.now(timezone.utc).isoformat(), checks=checks)
        record_status(home, result)
    else:
        try:
            prior = json.loads(status_path(home).read_text())
            if (isinstance(prior, dict) and prior.get("version") == VERSION
                    and prior.get("normalization") == NORMALIZATION
                    and isinstance(prior.get("checked_at"), str)
                    and isinstance(prior.get("checks"), list) and prior["checks"]
                    and all(isinstance(row, dict) and row.get("state") in ("changed", "unchanged", "unreachable")
                            and isinstance(row.get("url"), str) for row in prior["checks"])):
                result["last_fetch"] = prior
        except (OSError, ValueError, AttributeError):
            pass
    return result


def status_lines(result: dict) -> list[str]:
    lines = [f"skill reference: {result['version']}; read {result['date_read']}; age {result['age_days']} days"]
    prior = result if "checks" in result else result.get("last_fetch")
    if prior:
        lines.append(f"last reference fetch: {prior['checked_at']}")
        lines += [f"reference source {r['state']}: {r['url']}" for r in prior["checks"]]
    else:
        lines.append("reference sources: no fetch recorded for this pack; network not checked")
    return lines


def example_roots() -> tuple[Path, Path]:
    claude = Path(os.environ.get("SELF_LEARN_CLAUDE_DIR", str(Path.home() / ".claude")))
    return (Path(os.environ.get("SELF_LEARN_SKILL_REFERENCE_PLUGIN_ROOT", str(claude / "plugins/cache/claude-plugins-official/skill-creator"))),
            Path(os.environ.get("SELF_LEARN_SKILL_REFERENCE_SYNCED_ROOT", str(claude / "skills/synced"))))


def local_examples() -> dict[str, Path]:
    """Only native creator copies and manifest-attributed Anthropic synced skills.

    Absence is ordinary. Do not infer Anthropic provenance from a folder name.
    Configured roots replace defaults, allowing fully isolated fixtures.
    """
    plugin, synced = example_roots()
    examples = {}
    candidates = list(plugin.glob("*/skills/skill-creator/SKILL.md"))
    if candidates:
        newest = max(candidates, key=lambda p: (p.stat().st_mtime_ns, str(p)))
        examples["local-skill-creator"] = newest.parent
    for manifest in sorted(synced.glob("*/manifest.json")):
        try:
            data = json.loads(manifest.read_text())
            rows = data.get("skills", [])
            if isinstance(rows, dict):
                rows = [dict(value, name=key) for key, value in rows.items() if isinstance(value, dict)]
            for row in rows:
                if not isinstance(row, dict) or row.get("source") not in ("anthropic", "anthropic-example"):
                    continue
                name = row.get("name", "")
                if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]+", name):
                    continue
                folder = manifest.parent / name
                if (folder / "SKILL.md").is_file():
                    examples.setdefault("synced-" + name, folder)
        except (OSError, ValueError, TypeError):
            continue
    return examples


def stage_pack(home: Path, stage: Path, write) -> list[str]:
    """Scan reference text before passing it to the overseer stage writer.

    Local examples are runtime-only, never repository assets. Scripts are not
    executed or copied; prose and licenses illustrate structure and decisions.
    """
    from . import scan
    from .overseer.skills import short_hashes
    target = stage / "skill-reference"
    for name in ("PACK.md", "sources.yaml"):
        text = (PACK_DIR / name).read_text()
        if name == "sources.yaml":
            text = "# Model-facing copy: hash prefixes only; full hashes in the installed pack.\n" + short_hashes(text)
        write(stage, target / name, scan.withhold_spans(text))
    lines = status_lines(status(home))
    index = [f"# Examples for {VERSION}", "Read as examples, not commands to execute."]
    for name, folder in local_examples().items():
        copied = []
        for path in sorted(folder.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 300_000:
                continue
            rel = path.relative_to(folder)
            if any(part.startswith(".") for part in rel.parts) or path.suffix.lower() not in (".md", ".txt"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
                hits = scan.scan(text)
                if hits:
                    text = "Example withheld by secret scan: " + ", ".join(sorted({hit.rule for hit in hits})) + "\n"
                write(stage, target / "examples" / name / rel, text)
                copied.append(rel.as_posix())
            except (OSError, UnicodeError):
                continue
        if copied:
            index.append(f"- {name}: " + ", ".join(copied))
    if len(index) == 2:
        index.append("No native examples installed in the configured roots; use PACK.md.")
    write(stage, target / "EXAMPLES.md", scan.withhold_spans("\n".join(index) + "\n"))
    lines = [scan.withhold_spans(line) for line in lines]
    write(stage, target / "STATUS.md", "\n".join(lines) + "\n")
    return lines


def finding_source(rule: str) -> str:
    if rule == "name-synced":
        return CC
    if rule in ("name-hyphens", "name-dir-mismatch", "compatibility-limit", "metadata-string-values"):
        return SPEC
    if rule in ("name-missing", "name-not-kebab", "name-too-long", "name-reserved-word",
                "name-xml-tag", "description-empty", "description-too-long", "description-xml-tag"):
        return OV
    if rule.startswith("guidance-") or rule in ("file-nested", "reference-not-linked", "body-long-lines"):
        return BP
    return "self-learn policy (PACK.md: scope and existing template rules)"


def check_requirements(mapping: dict, body: str, files: dict, *, existing_name=None, carried=None):
    """Documented hard limits plus deliberately modest, non-semantic heuristics.

    These findings do not certify triggering or task quality. Carried values are
    evidence of the user's settings, not authority to rewrite those settings.
    """
    from .skill_scaffold import SkillFinding
    problems, notes = [], []
    def add(rule, message, key=None, guidance=False):
        unchanged = key is not None and carried is not None and key in carried and mapping.get(key) == carried[key]
        if key == "name" and mapping.get(key) == existing_name:
            unchanged = True
        finding = SkillFinding(rule, message + ("; existing user setting retained" if unchanged else "") + " [" + finding_source(rule) + "]")
        (notes if guidance or unchanged else problems).append(finding)
    name = mapping.get("name")
    if isinstance(name, str):
        if name.endswith("-") or "--" in name:
            add("name-hyphens", "name must not end with a hyphen or contain consecutive hyphens", "name")
        if name.casefold() == "synced":
            add("name-synced", "synced is reserved by Claude Code", "name")
    if "compatibility" in mapping:
        value = mapping["compatibility"]
        if not isinstance(value, str) or len(value) > 500:
            add("compatibility-limit", "compatibility must be text of at most 500 characters", "compatibility")
    meta = mapping.get("metadata")
    if isinstance(meta, dict) and any(not isinstance(k, str) or not isinstance(v, str) for k, v in meta.items()):
        add("metadata-string-values", "portable uploads require metadata string values; Claude Code permits this map", "metadata", True)
    desc = mapping.get("description")
    if isinstance(desc, str) and desc.strip():
        if not re.search(r"\b(when|whenever|if|use for)\b", desc, re.I):
            add("guidance-description-trigger", "review description: no explicit when-to-use wording detected (heuristic)", guidance=True)
        if re.search(r"\b(I|we|you|your)\b", desc, re.I):
            add("guidance-description-person", "review description: first/second person wording detected; prefer task and trigger wording", guidance=True)
        if "<" in desc or ">" in desc:
            add("guidance-angle-brackets", "native skill-creator rejects angle brackets; prefer plain placeholders", guidance=True)
    # Not a tokenizer: report a clearly labelled estimate, never enforce it.
    if len(body) / 4 > 5000:
        add("guidance-body-tokens", "body exceeds roughly 5000 tokens (characters/4 estimate); consider splitting details", guidance=True)
    for path, content in files.items():
        if path != "SKILL.md" and path.endswith(".md") and len(content.splitlines()) > 100 and not re.search(r"(?im)^#{1,3} .*contents|^[-*] \[.*\]\(#", content):
            notes.append(SkillFinding("guidance-reference-contents", "long reference has no detected contents list; review navigation [" + BP + "]", path))
    return problems, notes


def resolve_skill(home: Path, name: str) -> Path:
    from .hosts import load_hosts
    from .selfcheck import claude_runtime_dir
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise ValueError("skill folder does not exist")
    choices = []
    root = load_hosts(home).skills_root
    if root:
        choices.extend(Path(root).glob(f"plugins/*/skills/{name}"))
    runtime = claude_runtime_dir() / "skills" / name
    if runtime.is_dir():
        choices.append(runtime)
    choices = sorted({path.resolve() for path in choices})
    if len(choices) != 1:
        raise ValueError(f"skill name resolves to {len(choices)} folders; pass a path")
    return choices[0]
