"""Stage, validate and settle skill work requests using applied writer receipts."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .. import scan, skill_registry, skill_requests, skill_writer
from .skills import _yaml_text

INPUT = "skill-requests.yaml"
OUTPUT = "skill-request-decisions.yaml"


def stage_requests(home: Path, stage: Path, write: Callable, notes: list[str] | None = None) -> list[dict]:
    notes = notes if notes is not None else []
    try:
        rows = skill_requests.requests(home, open_only=True)
    except (ValueError, OSError):
        notes.append("skill-requests.yaml: cannot read requests; staged an empty list; requests remain open")
        rows = []
    safe = []
    for row in rows:
        if scan.scan(_yaml_text(row)):
            # Keep only the operational fields; untrusted free text never reaches
            # the stage or the manifest, including followups and old answers.
            row = {key: row[key] for key in ("id", "kind", "name", "lessons")}
            row["note"] = "Request text withheld by the secret scan; inspect the local request before deciding."
            if scan.scan(_yaml_text(row)):
                notes.append("skill request: unsafe identifying fields withheld; request remains open")
                continue
        if row["kind"] == "change":
            try:
                registry = skill_registry.load(home)
                if registry.veto_of(row["name"]):
                    row = {**row, "target": "vetoed"}
                elif not registry.may_edit(row["name"]):
                    row = {**row, "target": "withdrawn"}
            except skill_registry.SkillRegistryError:
                row = {**row, "target": "unavailable"}
        safe.append(row)
    write(stage, stage / INPUT, _yaml_text({"requests": safe}))
    return safe


def read_decisions(stage: Path, rows: list[dict], notes: list[str] | None = None) -> list[dict]:
    notes = notes if notes is not None else []
    if not rows:
        return []
    try:
        data = YAML(typ="safe").load((stage / OUTPUT).read_text(encoding="utf-8"))
        decisions = data["decisions"]
        if not isinstance(decisions, list):
            raise ValueError("decisions must be a list")
    except (OSError, ValueError, KeyError, TypeError, YAMLError):
        notes.append(f"{OUTPUT}: missing or unreadable answers; requests remain open")
        decisions = []
    by_id = {row["id"]: row for row in rows}
    seen = set()
    out = []
    for answer in decisions:
        if not isinstance(answer, dict) or not isinstance(answer.get("id"), str) or answer["id"] not in by_id:
            notes.append("skill request: dropped answer with unknown or malformed id")
            continue
        row = by_id[answer["id"]]
        ident = row["id"]
        expected = "built" if row["kind"] == "build" else "changed"
        reason = answer.get("reason")
        problem = None
        if ident in seen:
            problem = "duplicate answer"
        elif answer.get("answer") not in (expected, "declined"):
            problem = f"answer must be {expected} or declined"
        elif not isinstance(reason, str) or not reason.strip():
            problem = "answer needs a nonempty reason"
        elif answer["answer"] != "declined" and (not isinstance(answer.get("case"), str) or not answer["case"].strip()):
            problem = "built/changed must name the case file that performs the write"
        elif scan.scan(_yaml_text(answer)):
            problem = "answer text withheld by the secret scan"
        if problem:
            notes.append(f"skill request {ident}: dropped answer — {problem}; request remains open")
            continue
        assert isinstance(reason, str)
        seen.add(ident)
        out.append({**row, "answer": answer["answer"], "reason": " ".join(reason.split()), "case": answer.get("case")})
    for ident in sorted(set(by_id) - seen):
        notes.append(f"skill request {ident}: no valid answer; request remains open")
    return out


def settle(home: Path, manifest: dict, *, complete: bool) -> list[str]:
    """A model's 'built' is not proof. Close only after the named writer step applied.

    Failed writes and drafts remain open and are explicitly reported; declines
    close only on a completed run. Repeating finalization is idempotent.
    """
    lines = []
    for answer in (manifest.get("skills") or {}).get("requests", []):
        result = answer["answer"]
        reason = answer["reason"]
        actual_name = None
        applied = result == "declined"
        if not applied:
            for recipe in (manifest.get("cases") or {}).values():
                step = recipe.get("skill") or {}
                if (str(recipe.get("case_name", "")).removesuffix(".yaml") == str(answer.get("case", "")).removesuffix(".yaml")
                    and (result == "built" or step.get("name") == answer["name"]) and step.get("action") == "write"
                    and step.get("state") == "applied"):
                    applied = (result != "built" or set(answer["lessons"]).issubset(
                        skill_writer.routed_lessons(home, step["name"])))
                    if applied:
                        actual_name = step["name"]
                        break
        if complete and applied:
            skill_requests.close_request(home, answer["id"], answer=result, reason=reason, run=manifest["run_id"], actual_name=actual_name)
        else:
            result = "open"
            reason = "The requested decision did not land; it will be considered next run. " + reason
        if actual_name and actual_name != answer["name"]:
            reason += f" Used skill {actual_name}."
        lines.append(f"[skill request] {answer['id']} {answer['kind']} {answer['name']}: {result} — {reason}")
    return lines
