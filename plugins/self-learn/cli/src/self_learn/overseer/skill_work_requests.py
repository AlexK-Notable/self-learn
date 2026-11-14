"""Stage, validate and settle skill work requests using applied writer receipts."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .. import skill_requests, skill_writer
from .skills import _yaml_text

INPUT = "skill-requests.yaml"
OUTPUT = "skill-request-decisions.yaml"


def stage_requests(home: Path, stage: Path, write: Callable) -> list[dict]:
    rows = skill_requests.requests(home, open_only=True)
    write(stage, stage / INPUT, _yaml_text({"requests": rows}))
    return rows


def read_decisions(stage: Path, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    path = stage / OUTPUT
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
        decisions = data["decisions"]
        if not isinstance(decisions, list):
            raise ValueError("decisions must be a list")
        by_id = {row["id"]: row for row in rows}
        seen = set()
        out = []
        for answer in decisions:
            if not isinstance(answer, dict) or answer.get("id") not in by_id or answer["id"] in seen:
                raise ValueError("unknown or repeated request id")
            row = by_id[answer["id"]]
            expected = "built" if row["kind"] == "build" else "changed"
            if answer.get("answer") not in (expected, "declined"):
                raise ValueError(f"{row['id']}: answer must be {expected} or declined")
            reason = answer.get("reason")
            if not isinstance(reason, str) or not reason.strip() or "\n" in reason:
                raise ValueError("each answer needs a one-sentence reason")
            if answer["answer"] != "declined" and not isinstance(answer.get("case"), str):
                raise ValueError("built/changed must name the case file that performs the write")
            seen.add(row["id"])
            out.append({**row, "answer": answer["answer"], "reason": reason.strip(), "case": answer.get("case")})
        if seen != set(by_id):
            raise ValueError("every open request must be decided: missing " + ", ".join(sorted(set(by_id) - seen)))
        return out
    except (OSError, ValueError, KeyError, TypeError, YAMLError) as exc:
        raise ValueError(f"{OUTPUT}: {exc}; requests remain open: " + ", ".join(row["id"] for row in rows)) from exc


def settle(home: Path, manifest: dict, *, complete: bool) -> list[str]:
    """A model's 'built' is not proof. Close only after the named writer step applied.

    Failed writes and drafts remain open and are explicitly reported; declines
    close only on a completed run. Repeating finalization is idempotent.
    """
    lines = []
    for answer in (manifest.get("skills") or {}).get("requests", []):
        result = answer["answer"]
        reason = answer["reason"]
        applied = result == "declined"
        if not applied:
            for recipe in (manifest.get("cases") or {}).values():
                step = recipe.get("skill") or {}
                if (recipe.get("case_name") == answer.get("case")
                    and step.get("name") == answer["name"] and step.get("action") == "write"
                    and bool(step.get("updating")) == (result == "changed")
                    and step.get("state") == "applied"):
                    applied = (result != "built" or set(answer["lessons"]).issubset(
                        skill_writer.routed_lessons(home, answer["name"])))
                    break
        if complete and applied:
            skill_requests.close_request(home, answer["id"], answer=result, reason=reason, run=manifest["run_id"])
        else:
            result = "open"
            reason = "The requested decision did not land; it will be considered next run. " + reason
        lines.append(f"[skill request] {answer['id']} {answer['kind']} {answer['name']}: {result} — {reason}")
    return lines
