"""report_view.py — how the weekly report page draws the overseer's report
(humane UI lane 3, proposal §5).

The report file is the overseer's and is never changed: ``overseer/
conversation.py`` reads its "## Questions for you" section, and the runner
writes it. This module changes only how it is drawn:

- the first line ("# Overseer report — 2026-11-01   run 92d6fec6   actor
  overseer   model …") becomes a title in words ("Weekly report · Sunday 1
  November"), and the run id, actor and model move to an "About this run"
  fold;
- the "Questions for you" section is lifted to the top: "Nothing needs you
  this week." when it says none, otherwise its questions with a link to the
  inbox. It is never folded and never dropped;
- a few counts from the run's own record (:func:`self_learn.weekly_facts.run_facts`:
  re-checked, decided in the person's stead, questions), never from the prose;
- inside a bullet, machine text reads as a short placeholder (its original
  in a tooltip, and the whole bullet as written in one fold at its end): a run of three
  or more ids ("the 35 cases"), an absolute path, a full-length hash, a JSON
  object. Text inside ``code`` is left as written (it is a command to copy),
  and nothing inside a paragraph is folded (a ``<details>`` would break it);
- "Refused / could not do" folds by default, with its count.

Every render goes through :func:`self_learn_ui.rendering.render_markdown`
(``html=False``); the folds are added to its escaped output, so text from
the report never becomes markup.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markupsafe

from .rendering import render_markdown

__all__ = ["build", "fold_machine_text", "split_sections"]

_ID = r"(?:case|lrn|stmt|um|op|sc|grant|obs|q)-[0-9a-z][0-9a-z-]*(?:@r\d+)?"
#: Three or more ids in a row, separated by commas (an "and" allowed).
_ID_RUN_RE = re.compile(rf"\b{_ID}(?:,\s*(?:and\s+)?{_ID}){{2,}}")
_ID_ONE_RE = re.compile(rf"\b{_ID}")
#: An absolute path (shown with ``~`` for the home directory).
_PATH_RE = re.compile(r"(?<![\w/~.&;])/(?:home|root|etc|usr|var|tmp|opt)(?:/[^\s<,;()'\"&]+)+")
#: A full SHA-1 or SHA-256 (short commit ids stay: a person can quote them).
_HASH_RE = re.compile(r"\b(?:[0-9a-f]{64}|[0-9a-f]{40})\b")
_TAG_RE = re.compile(r"(<[^>]+>)")
_NOUNS = {"case": "cases", "lrn": "lessons", "stmt": "of your statements", "sc": "skill ideas"}
_QUESTIONS = "Questions for you"
#: Humane UI lane 5: the overseer's own optional summary, drawn in the
#: "In short" box (``summary_view``), never again in the body.
_IN_SHORT = "In short"


def _home_prefix() -> str:
    return str(Path.home())


def _display_path(path: str) -> str:
    home = _home_prefix()
    if home and home != "/" and (path == home or path.startswith(home + "/")):
        return "~" + path[len(home):]
    return path


def _json_spans(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` of each balanced ``{&quot;…}`` in escaped text."""
    spans: list[tuple[int, int]] = []
    start = text.find("{&quot;")
    while start != -1:
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    spans.append((start, i + 1))
                    break
            i += 1
        else:
            break
        start = text.find("{&quot;", spans[-1][1])
    return spans


_KIND_WORDS = {"ids": "ids", "path": "paths", "hash": "hashes", "json": "settings entries"}


def _token(words: str, original: str, kind: str, seen: set[str]) -> str:
    """A short placeholder for machine text, the original in its tooltip;
    *seen* collects the kinds a bullet replaced, for its fold's summary."""
    seen.add(kind)
    return (f'<span class="rv-token" data-fold="{kind}" title="{original}">'
            f"{words}</span>")


def _fold_text(text: str, seen: set[str]) -> str:
    """One escaped text node with its machine text replaced by placeholders."""
    chunks: list[tuple[bool, str]] = []
    cursor = 0
    for start, end in _json_spans(text):
        chunks.append((False, text[cursor:start]))
        chunks.append((True, _token("a settings entry", text[start:end], "json", seen)))
        cursor = end
    chunks.append((False, text[cursor:]))
    pieces: list[str] = []
    for done, piece in chunks:
        if done:
            pieces.append(piece)
            continue

        def ids(match: re.Match[str]) -> str:
            found = _ID_ONE_RE.findall(match.group(0))
            prefixes = {i.split("-", 1)[0] for i in found}
            noun = _NOUNS.get(prefixes.pop(), "ids") if len(prefixes) == 1 else "ids"
            return _token(f"the {len(found)} {noun}", match.group(0), "ids", seen)

        piece = _ID_RUN_RE.sub(ids, piece)
        piece = _PATH_RE.sub(lambda m: _token(
            "a path", str(markupsafe.escape(_display_path(m.group(0)))), "path", seen), piece)
        piece = _HASH_RE.sub(lambda m: _token("a hash", m.group(0), "hash", seen), piece)
        pieces.append(piece)
    return "".join(pieces)


def _fold_summary(kinds: set[str]) -> str:
    words = [_KIND_WORDS[k] for k in ("ids", "path", "hash", "json") if k in kinds]
    joined = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
    return f"Show the {joined} in full"


def fold_machine_text(html: str) -> str:
    """*html* (markdown-it's escaped output) with the machine text inside
    list items folded: each run of three or more ids, absolute path, full
    hash or JSON object reads as a short placeholder ("the 35 cases", "a
    path"), and the bullet ends with one fold holding its original text.
    Text in ``code`` or ``pre`` and text in a paragraph are left alone."""
    parts = _TAG_RE.split(html)
    out: list[str] = []
    in_code = in_p = 0
    # One entry per open <li>: its original HTML and the kinds it replaced.
    stack: list[tuple[list[str], set[str]]] = []
    for part in parts:
        if part.startswith("<"):
            name = re.match(r"</?([a-zA-Z0-9]+)", part)
            tag = name.group(1).lower() if name else ""
            closing = part.startswith("</")
            step = -1 if closing else 1
            if tag in ("code", "pre"):
                in_code = max(0, in_code + step)
            elif tag == "p":
                in_p = max(0, in_p + step)
            if tag == "li" and closing and stack:
                original, kinds = stack.pop()
                if kinds:
                    out.append(f'<details class="rv-fold"><summary>{_fold_summary(kinds)}'
                               f'</summary><div class="rv-fold-body">{"".join(original)}</div></details>')
                for entry in stack:
                    entry[0].append("".join(original) + part)
                out.append(part)
                continue
            for entry in stack:
                entry[0].append(part)
            if tag == "li" and not closing:
                stack.append(([], set()))
            out.append(part)
            continue
        for entry in stack:
            entry[0].append(part)
        if stack and not in_code and not in_p:
            out.append(_fold_text(part, stack[-1][1]))
        else:
            out.append(part)
    return "".join(out)


def split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """``(preamble, [(heading, body), …])`` by the report's ``## `` headings."""
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    return "\n".join(preamble), [(h, "\n".join(b).strip()) for h, b in sections]


def _top_bullets(body: str) -> int:
    return sum(1 for line in body.splitlines() if re.match(r"^[-*+]\s", line))


def _says_none(body: str) -> bool:
    words = re.sub(r"[-*+\s.]+", " ", body).strip().lower()
    return words in ("", "none", "no questions", "none this week")


def _day_words(date: str | None) -> str | None:
    try:
        parsed = datetime.strptime(str(date)[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return f"{parsed.strftime('%A')} {parsed.day} {parsed.strftime('%B')}"


def _finished_words(at: str | None, date: str | None) -> str | None:
    if not at:
        return None
    try:
        parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone()
    clock = local.strftime("%H:%M")
    if date and local.strftime("%Y-%m-%d") != str(date)[:10]:
        return f"finished {local.strftime('%a')} {local.day} {local.strftime('%b')} at {clock}"
    return f"finished at {clock}"


def build(text: str, home: Path | str) -> dict[str, Any]:
    """The page's view of report *text*. Never raises on odd text: an
    unknown first line is drawn as written."""
    from self_learn import weekly_facts

    heading = weekly_facts.parse_heading(text)
    preamble, sections = split_sections(text)
    if heading is not None:
        # The first line is the title, drawn in words above.
        preamble = "\n".join(preamble.lstrip().split("\n")[1:])
    facts = weekly_facts.run_facts(home, (heading or {}).get("run"))
    date = (heading or {}).get("date") or (facts or {}).get("date")
    questions: dict[str, Any] | None = None
    drawn: list[dict[str, Any]] = []
    for title, body in sections:
        if title == _IN_SHORT:
            continue
        if title == _QUESTIONS:
            questions = ({"none": True, "html": None} if _says_none(body) else
                         {"none": False, "html": markupsafe.Markup(render_markdown(body))})
            continue
        html = fold_machine_text(render_markdown(body))
        folded = title.lower().startswith("refused")
        drawn.append({"title": title, "html": markupsafe.Markup(html), "folded": folded,
                      "count": _top_bullets(body)})
    day = _day_words(date)
    return {
        "title": f"Weekly report · {day}" if day else "Weekly report",
        "finished": _finished_words((facts or {}).get("finished_at"), date),
        "heading": heading,
        "facts": facts,
        "questions": questions,
        "preamble": markupsafe.Markup(fold_machine_text(render_markdown(preamble)))
        if preamble.strip() else None,
        "sections": drawn,
    }
