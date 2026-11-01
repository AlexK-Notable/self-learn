"""The counted facts of one weekly overseer run, for the weekly report page
(humane UI lane 3, proposal §5).

The report page shows a few counts beside the overseer's own words: how many
past decisions it re-checked out of how many it could have, how many
decisions it made in the person's stead, and how many questions it asked.
They come from the run's own record (``cases/runs/<run id>.json``: the
``findings`` it kept, its ``population_count``, the ``decisions`` tally the
runner staged and dropped, its ``questions``), never from reading the
report's prose, and never estimated. The report names its run on its first
line (``# Overseer report — <date>   run <id>   actor …   model …``), which
is how a report is matched to its record.

Read-only: no git, no write, no model call. Every failure is ``None`` (or a
field left ``None``), never a raise, so a report always renders.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

__all__ = ["HEADING_RE", "parse_heading", "run_facts"]

#: The report's first line, as the overseer runner writes it.
HEADING_RE = re.compile(
    r"^#\s*Overseer report\s*[—-]\s*(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:\s+run\s+(?P<run>[0-9a-f]{6,16}))?"
    r"(?:\s+actor\s+(?P<actor>\S+))?"
    r"(?:\s+model\s+(?P<model>\S+))?\s*$"
)
_RUN_ID_RE = re.compile(r"^[0-9a-f]{6,16}$")


def parse_heading(text: str | None) -> dict[str, str | None] | None:
    """The fields of the report's first line, or ``None`` when the report
    does not start with the runner's heading."""
    first = (text or "").lstrip().split("\n", 1)[0].strip()
    match = HEADING_RE.match(first)
    if match is None:
        return None
    return {k: match.group(k) for k in ("date", "run", "actor", "model")}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def run_facts(home: Path | str, run_id: str | None) -> dict[str, Any] | None:
    """The counted facts of overseer run *run_id*, or ``None`` when there is
    no such record (an older report, a run recorded elsewhere).

    Fields (each ``None`` when the record lacks it):

    - ``run_id``, ``actor``, ``model``, ``date``;
    - ``started_at``; ``finished_at``: the time of the run's last progress,
      for a run whose status is ``complete`` or ``closed``;
    - ``examined``: findings of kind ``examined`` (past decisions it
      re-checked); ``population``: the decisions it could have re-checked;
    - ``decided``: the decisions in the person's stead that reached the
      ledger (``decisions.staged`` less ``decisions.dropped``);
      ``decisions_written``: ``decisions.staged``; ``decisions_dropped``;
    - ``questions``: the questions it asked the person.
    """
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        return None
    path = Path(home) / "cases" / "runs" / f"{run_id}.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(manifest, dict) or manifest.get("actor") != "overseer":
        return None
    findings = manifest.get("findings")
    examined = (
        sum(1 for f in findings if isinstance(f, dict) and f.get("kind") == "examined")
        if isinstance(findings, list) else None
    )
    raw_decisions = manifest.get("decisions")
    decisions: dict[str, Any] = raw_decisions if isinstance(raw_decisions, dict) else {}
    staged = _int(decisions.get("staged"))
    dropped = _int(decisions.get("dropped"))
    questions = manifest.get("questions")
    asked = questions.get("questions") if isinstance(questions, dict) else None
    status = manifest.get("status")
    finished = manifest.get("progress_at") if status in ("complete", "closed") else None
    return {
        "run_id": run_id,
        "actor": manifest.get("actor"),
        "model": manifest.get("model") if isinstance(manifest.get("model"), str) else None,
        "date": manifest.get("date") or manifest.get("week"),
        "started_at": manifest.get("started") if isinstance(manifest.get("started"), str) else None,
        "finished_at": finished if isinstance(finished, str) else None,
        "examined": examined,
        "population": _int(manifest.get("population_count")),
        "decided": (staged - (dropped or 0)) if staged is not None else None,
        "decisions_written": staged,
        "decisions_dropped": dropped,
        "questions": len(asked) if isinstance(asked, list) else None,
    }
