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

__all__ = ["HEADING_RE", "QUESTION_ID_RE", "parse_heading", "question_states", "run_facts"]

#: The report's first line, as the overseer runner writes it.
HEADING_RE = re.compile(
    r"^#\s*Overseer report\s*[—-]\s*(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:\s+run\s+(?P<run>[0-9a-f]{6,16}))?"
    r"(?:\s+actor\s+(?P<actor>\S+))?"
    r"(?:\s+model\s+(?P<model>\S+))?\s*$"
)
_RUN_ID_RE = re.compile(r"^[0-9a-f]{6,16}$")
#: A question's id as a report's "Questions for you" bullet opens with it:
#: an ask (``q-…``) or a reading's revision (``um-…@r1``).
QUESTION_ID_RE = re.compile(r"^(?:q-[a-z0-9-]+|um-[0-9a-z]+@r\d+)$")


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
    - ``questions``: the questions it asked the person;
    - ``agreed``, ``disagreed``, ``no_verdict``: of the decisions it
      re-checked, how many it said still hold, how many it said do not, and
      how many it gave no verdict on; ``findings_dropped``: its own findings
      of the week that the runner dropped. From the record's ``review``
      block (humane UI lane 5, 02 §3a.13a); every one ``None`` for a run
      recorded before that block existed.
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
    raw_review = manifest.get("review")
    review: dict[str, Any] = raw_review if isinstance(raw_review, dict) else {}
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
        "agreed": _int(review.get("agreed")),
        "disagreed": _int(review.get("disagreed")),
        "no_verdict": _int(review.get("no_verdict")),
        "findings_dropped": _int(review.get("findings_dropped")),
    }


def question_states(home: Path | str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Where each question a report asked stands now (gate r1 MINOR 6), so an
    old report never invites answering a question settled weeks ago:

    - ``open``: still in the overseer's index and not answered
      (``overseer.conversation``'s own rule);
    - ``answered``: the person's latest words recorded as answering it
      (a statement whose ``answers.ref`` is the id), with ``answer`` (their
      words, verbatim) and ``at``; or their option click (a choice row), with
      ``answer`` the option's label when the row has one;
    - ``closed``: neither -- no longer asked, and no answer on record.

    Read-only; a store that cannot be read leaves a question ``closed``
    rather than inventing an answer, except that the index is read first,
    so a question still open is never shown as settled."""
    home = Path(home)
    wanted = [i for i in ids if isinstance(i, str) and QUESTION_ID_RE.match(i)]
    out: dict[str, dict[str, Any]] = {i: {"state": "closed", "answer": None, "at": None}
                                      for i in wanted}
    if not wanted:
        return out
    try:
        from .overseer import conversation

        rows = conversation._load_questions(home)  # noqa: SLF001
        open_rows, _answered = conversation._unanswered(  # noqa: SLF001
            home, [r for r in rows if r.get("id") in out])
        still_open = {str(r.get("id")) for r in open_rows}
    except Exception:  # noqa: BLE001 -- an unreadable index opens nothing
        still_open = set()
    try:
        from . import statements

        said = statements.list_statements(home)
    except Exception:  # noqa: BLE001
        said = []
    for row in said:
        answers = row.get("answers")
        ref = answers.get("ref") if isinstance(answers, dict) else None
        if ref in out and isinstance(row.get("verbatim"), str):
            at = row.get("at") if isinstance(row.get("at"), str) else None
            if out[ref]["at"] is None or (at or "") >= str(out[ref]["at"]):
                out[ref].update(state="answered", answer=row["verbatim"], at=at)
    try:
        from .overseer import conversation

        chose = conversation.choice_rows(home)
    except Exception:  # noqa: BLE001
        chose = []
    for row in chose:
        answers = row.get("answers")
        ref = answers.get("ref") if isinstance(answers, dict) else None
        q_id = ref if ref in out else row.get("subject") if row.get("subject") in out else None
        if q_id is None or out[q_id]["state"] == "answered":
            continue
        label = row.get("label") if isinstance(row.get("label"), str) else None
        out[q_id].update(state="answered", answer=label,
                         at=row.get("at") if isinstance(row.get("at"), str) else None)
    for q_id in still_open:
        out[q_id].update(state="open")
    return out
