"""charts.py -- server-side inline-SVG charts (humane lane 2, S-NEXT-humane-l2).

Three charts, all of COUNTS the CLI already computed (``report --json``'s
``series`` block and ``status --json``'s ``supply_mix``):

* :func:`waiting_chart` -- "Is it keeping up?": lessons waiting for a
  decision at each day's end. A day whose count is ``None`` (unknown) is a
  GAP in the line, never a zero.
* :func:`decided_chart` -- "What got decided, night by night": stacked
  columns per night, one segment per outcome group
  (``self_learn.series.OUTCOME_GROUPS``).
* :func:`supply_chart` -- "Where do lessons come from?": ranked horizontal
  bars, one hue.

Rules every chart here keeps (the ``dataviz`` skill's, and 09's honesty
rule: counted, never modelled):

* every mark draws a number the CLI counted; nothing is projected, scored
  or targeted. The sentences above a chart quote counts or sums of counts;
* every chart ships a "Show as a table" fold holding every value, so no
  value is hover-only and colour is never the only carrier;
* three SVGs are drawn per chart: narrow (320 units, fewer ticks, words
  above the bars; a phone), wide (560; a half-width card) and xwide (960; a
  full-width card). CSS container queries (``style.css``, the lane-2 block)
  pick one by the width of the chart's own box, so text stays readable
  from a 390 px phone to a wide desktop. The unused ones are
  ``display: none``, so a screen reader reads one chart, not three;
* CSP (09 §3 W-9): presentation attributes and classes only; no ``style=``
  attribute, no ``<style>`` block, no script. Colours are CSS custom
  properties (``--chart-*``) defined for light and dark in ``style.css``;
* the SVG has ``role="img"`` and a spoken summary; its marks carry a
  ``<title>`` for the native tooltip. Marks are not tab stops (28 of them
  per chart would swamp the keyboard map); the table is the keyboard and
  screen-reader route to every value.

Everything returned for a template is :class:`markupsafe.Markup` built from
escaped pieces; a CLI string never reaches the page unescaped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from typing import Any, Iterable, Sequence

from markupsafe import Markup

from self_learn import series as _series

__all__ = [
    "DECIDED_DAYS",
    "GROUP_ORDER",
    "GROUP_WORDS",
    "SUPPLY_WORDS",
    "TEMPLATE_GLOBALS",
    "decided_chart",
    "decided_legend",
    "decided_sentence",
    "supply_chart",
    "supply_sentence",
    "waiting_chart",
    "waiting_sentence",
]

#: The outcome groups, in stacking order (bottom first) -- the CLI's own
#: order, so a group added there appears here without an edit.
GROUP_ORDER: tuple[str, ...] = tuple(_series.OUTCOME_GROUPS)

#: What a person reads for each outcome group (contract.md §4). Checked
#: against ``OUTCOME_GROUPS`` at import: a group with no words fails loudly
#: here, in the suite, and not as a blank legend entry in the browser.
GROUP_WORDS: dict[str, str] = {
    "use": "Put to use",
    "no": "Turned down",
    "later": "Left for later",
    "kept": "Looked at, kept as is",
}
#: The same words in the middle of a sentence.
_GROUP_SENTENCE: dict[str, str] = {
    "use": "put to use",
    "no": "turned down",
    "later": "left for later",
    "kept": "looked at and kept as is",
}
_missing = [g for g in GROUP_ORDER if g not in GROUP_WORDS or g not in _GROUP_SENTENCE]
if _missing:  # pragma: no cover -- import-time guard
    raise RuntimeError(f"charts.GROUP_WORDS has no words for outcome group(s) {_missing}")

#: ``status --json`` ``supply_mix`` keys, in words. An unknown key shows raw.
SUPPLY_WORDS: dict[str, str] = {
    "session": "Found in your sessions overnight",
    "teach": "Taught during a session",
    "backlog": "Imported from older notes",
    "rewrite": "Rewrites of earlier lessons",
    "auto-memory": "Picked up from Claude's memory notes",
}
_SUPPLY_SENTENCE: dict[str, str] = {
    "session": "your sessions, read overnight",
    "teach": "being taught during a session",
    "backlog": "older notes that were imported",
    "rewrite": "rewrites of earlier lessons",
    "auto-memory": "Claude's memory notes",
}

#: How many nights the decided chart draws (the series carries 28).
DECIDED_DAYS = 21

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: Space between stacked segments, the radius of a column's data end and
#: the smallest a non-zero segment may be drawn (so a count of 1 on a tall
#: axis is still a visible mark; the table and tooltip carry the number).
_GAP = 2.0
_RADIUS = 4.0
_MIN_SEG = 2.0


# ------------------------------------------------------------------ helpers


def _esc(value: Any) -> str:
    return escape(str(value), quote=True)


def _f(x: float) -> str:
    return f"{x:.1f}"


def _int(value: Any) -> int | None:
    """A count, or ``None`` when it is not one. ``bool`` is not a count."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return int(value)


def _day(iso: Any) -> str:
    """``"2026-10-05"`` -> ``"5 Oct"``; anything else comes back as written."""
    text = str(iso)
    try:
        y, m, d = text.split("-")
        return f"{int(d)} {_MONTHS[int(m) - 1]}"
    except (ValueError, IndexError):
        return text


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _series_rows(series: Any) -> list[dict]:
    """The ``rows`` list of a ``series`` block, tolerant of a bare list, of
    ``None`` and of rows that are not objects (a malformed CLI answer draws
    an empty chart with its words, never a 500)."""
    rows = series.get("rows") if isinstance(series, dict) else series
    if not isinstance(rows, (list, tuple)):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _series_error(series: Any) -> str | None:
    err = series.get("error") if isinstance(series, dict) else None
    return str(err) if err else None


def _scale(vmax: int) -> tuple[int, int]:
    """``(top of the axis, tick step)`` for whole counts: at most four
    intervals, a round step, never a top below the data."""
    if vmax <= 0:
        return 4, 1
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if math.ceil(vmax / step) <= 4:
            return math.ceil(vmax / step) * step, step
    step = 10 ** math.ceil(math.log10(vmax / 4))
    return math.ceil(vmax / step) * step, step


@dataclass(frozen=True)
class _Frame:
    """One variant's geometry, in SVG user units."""

    name: str
    width: int
    plot_h: int
    left: int
    right: int
    top: int
    bottom: int

    @property
    def height(self) -> int:
        return self.top + self.plot_h + self.bottom

    @property
    def plot_w(self) -> int:
        return self.width - self.left - self.right

    @property
    def base(self) -> float:
        return float(self.top + self.plot_h)


#: Three drawings per chart, picked by the chart's own width (style.css):
#: narrow below 460 px (a phone), wide to 820 px (a half-width card), xwide
#: above (a full-width card on a desktop). Each is drawn so its text lands
#: between about 11 and 15 px at the widths it is shown.
_NARROW = _Frame("narrow", width=320, plot_h=150, left=26, right=44, top=12, bottom=30)
_WIDE = _Frame("wide", width=560, plot_h=150, left=34, right=48, top=12, bottom=30)
_XWIDE = _Frame("xwide", width=960, plot_h=170, left=38, right=56, top=12, bottom=30)
_FRAMES = (_NARROW, _WIDE, _XWIDE)


def _open(frame: _Frame, label: str, height: int | None = None) -> str:
    return (
        f'<svg class="chart-svg" viewBox="0 0 {frame.width} {height or frame.height}" '
        f'role="img" aria-label="{_esc(label)}">'
    )


def _axis(frame: _Frame, ymax: int, step: int) -> list[str]:
    """Hairline grid, a solid baseline, and a whole-number tick label per
    gridline: one axis, recessive."""
    out: list[str] = []
    for t in range(0, ymax + 1, step):
        y = frame.base - frame.plot_h * t / ymax
        cls = "cv-base" if t == 0 else "cv-grid"
        out.append(
            f'<line class="{cls}" x1="{frame.left}" x2="{frame.left + frame.plot_w}" '
            f'y1="{_f(y)}" y2="{_f(y)}"/>'
        )
        out.append(
            f'<text class="cv-t" x="{frame.left - 6}" y="{_f(y + 4)}" text-anchor="end">{t}</text>'
        )
    return out


def _col_path(x: float, y_top: float, w: float, h: float, r: float) -> str:
    """A column from ``y_top`` down ``h``: data end (top) rounded, base square."""
    r = min(r, w / 2, h)
    if r < 0.75:
        return f"M{_f(x)},{_f(y_top + h)} V{_f(y_top)} H{_f(x + w)} V{_f(y_top + h)} Z"
    return (
        f"M{_f(x)},{_f(y_top + h)} V{_f(y_top + r)} Q{_f(x)},{_f(y_top)} {_f(x + r)},{_f(y_top)} "
        f"H{_f(x + w - r)} Q{_f(x + w)},{_f(y_top)} {_f(x + w)},{_f(y_top + r)} V{_f(y_top + h)} Z"
    )


def _figure(kind: str, narrow: str, wide: str, xwide: str, table: str) -> Markup:
    return Markup(
        f'<figure class="chart-fig" data-chart="{_esc(kind)}">'
        f'<div class="chart-v chart-v-narrow">{narrow}</div>'
        f'<div class="chart-v chart-v-wide">{wide}</div>'
        f'<div class="chart-v chart-v-xwide">{xwide}</div>'
        f'<details class="chart-table"><summary>Show as a table</summary>'
        f'<div class="chart-table-scroll">{table}</div></details>'
        f"</figure>"
    )


def _empty(kind: str, words: str) -> Markup:
    return Markup(f'<p class="chart-empty" data-chart="{_esc(kind)}">{_esc(words)}</p>')


def _table(head: Sequence[str], body: Iterable[Sequence[str]], caption: str) -> str:
    th = "".join(
        ('<th scope="col" class="num">' if i else '<th scope="col">') + _esc(h) + "</th>"
        for i, h in enumerate(head)
    )
    trs = []
    for row in body:
        cells = "".join(
            (f'<th scope="row">{_esc(c)}</th>' if i == 0 else f'<td class="num">{_esc(c)}</td>')
            for i, c in enumerate(row)
        )
        trs.append(f"<tr>{cells}</tr>")
    return (
        f'<table class="chart-data"><caption>{_esc(caption)}</caption>'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"
    )


# ----------------------------------------------------- 1. Is it keeping up?


def _pending(rows: list[dict]) -> list[int | None]:
    return [_int(r.get("pending")) for r in rows]


def waiting_sentence(series: Any) -> str:
    """The one-sentence answer above the chart, from counts only."""
    rows = _series_rows(series)
    vals = _pending(rows)
    known = [i for i, v in enumerate(vals) if v is not None]
    if not known:
        err = _series_error(series)
        if err:
            return f"The ledger's history could not be read, so there is nothing to draw. ({err})"
        return "There is no history to draw yet."
    first, last = known[0], known[-1]
    a, b = vals[first], vals[last]
    assert a is not None and b is not None
    d1 = _day(rows[first].get("date"))
    if first == last:
        return f"At the end of {d1}, {_plural(b, 'lesson')} {'was' if b == 1 else 'were'} waiting for a decision."
    when = "Now" if last == len(rows) - 1 else f"On {_day(rows[last].get('date'))}"
    was = "was" if a == 1 else "were"
    if a == b:
        tail = f"{when} there {'is' if b == 1 else 'are'} still {b}."
    else:
        tail = f"{when} there {'is' if b == 1 else 'are'} {b}."
    return f"On {d1}, {_plural(a, 'lesson')} {was} waiting for a decision. {tail}"


def _waiting_svg(rows: list[dict], frame: _Frame, label: str) -> str:
    n = len(rows)
    vals = _pending(rows)
    known = [v for v in vals if v is not None]
    ymax, step = _scale(max(known) if known else 0)
    pw = frame.plot_w
    slot = pw / (n - 1) if n > 1 else float(pw)

    def X(i: int) -> float:
        return frame.left + (slot * i if n > 1 else pw / 2)

    def Y(v: int) -> float:
        return frame.base - frame.plot_h * v / ymax

    out = [_open(frame, label)]
    out += _axis(frame, ymax, step)
    # Runs of known days: an unknown day breaks the line (a gap), it is
    # never joined across and never drawn as zero.
    runs: list[list[int]] = []
    for i, v in enumerate(vals):
        if v is None:
            continue
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    for run in runs:
        pts = [(X(i), Y(vals[i])) for i in run]  # type: ignore[arg-type]
        if len(pts) == 1:
            out.append(f'<circle class="cv-dot" cx="{_f(pts[0][0])}" cy="{_f(pts[0][1])}" r="3"/>')
            continue
        line = " L".join(f"{_f(x)},{_f(y)}" for x, y in pts)
        out.append(
            f'<path class="cv-area" d="M{_f(pts[0][0])},{_f(frame.base)} L{line} '
            f'L{_f(pts[-1][0])},{_f(frame.base)} Z"/>'
        )
        out.append(f'<path class="cv-line" d="M{line}"/>')
    # Hover targets and native tooltips, one per day. Unknown days say so.
    half = slot / 2
    for i, row in enumerate(rows):
        v = vals[i]
        text = (
            f"{_day(row.get('date'))}: not known"
            if v is None
            else f"{_day(row.get('date'))}: {v} waiting for a decision"
        )
        x0 = max(X(i) - half, float(frame.left))
        x1 = min(X(i) + half, float(frame.left + pw))
        out.append(
            f'<g><title>{_esc(text)}</title><rect x="{_f(x0)}" y="{frame.top}" '
            f'width="{_f(max(x1 - x0, 1.0))}" height="{frame.plot_h}" fill="transparent"/></g>'
        )
    # Weekly date labels counted back from the last day, so the newest is
    # always labelled and the spacing is even.
    for i, row in enumerate(rows):
        if (n - 1 - i) % 7 == 0:
            out.append(
                f'<text class="cv-t" x="{_f(X(i))}" y="{frame.height - 8}" '
                f'text-anchor="middle">{_esc(_day(row.get("date")))}</text>'
            )
    # The end of the line, labelled "N now", only when the last day is known.
    if n and vals[-1] is not None:
        x, y = X(n - 1), Y(vals[-1])
        out.append(f'<circle class="cv-end" cx="{_f(x)}" cy="{_f(y)}" r="4"/>')
        out.append(
            f'<text class="cv-lbl" x="{_f(x + 9)}" y="{_f(y + 4)}">{vals[-1]} now</text>'
        )
    out.append("</svg>")
    return "".join(out)


def waiting_chart(series: Any) -> Markup:
    """The "Is it keeping up?" figure: an area line of lessons waiting at
    each day's end. Unknown days are a gap."""
    rows = _series_rows(series)
    if not rows or all(v is None for v in _pending(rows)):
        return _empty("waiting", waiting_sentence(series))
    label = "Lessons waiting for a decision at the end of each day. " + waiting_sentence(series)
    svgs = [_waiting_svg(rows, f, label) for f in _FRAMES]
    body = (
        (_day(r.get("date")), "not known" if p is None else str(p), "not known" if d is None else str(d))
        for r, p, d in zip(rows, _pending(rows), [_int(r.get("deferred")) for r in rows])
    )
    table = _table(
        ("Day", "Waiting for a decision", "Put off until later"),
        body,
        "Lessons waiting for a decision at the end of each day",
    )
    return _figure("waiting", svgs[0], svgs[1], svgs[2], table)


# ----------------------------------------------- 2. What got decided


def _decided(row: dict) -> dict[str, int]:
    d = row.get("decided")
    d = d if isinstance(d, dict) else {}
    return {g: max(_int(d.get(g)) or 0, 0) for g in GROUP_ORDER}


def _decided_rows(series: Any) -> list[dict]:
    return _series_rows(series)[-DECIDED_DAYS:]


def decided_legend() -> Markup:
    """The legend for the stacked chart: swatch plus words, in stack order."""
    items = "".join(
        f'<li><span class="chart-key chart-key-{g}" aria-hidden="true"></span>{_esc(GROUP_WORDS[g])}</li>'
        for g in GROUP_ORDER
    )
    return Markup(f'<ul class="chart-legend" aria-label="Colours">{items}</ul>')


def _oxford(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def decided_sentence(series: Any) -> str:
    rows = _decided_rows(series)
    if not rows:
        return "There is no history to draw yet."
    totals = {g: sum(_decided(r)[g] for r in rows) for g in GROUP_ORDER}
    total = sum(totals.values())
    span = "three weeks" if len(rows) == DECIDED_DAYS else _plural(len(rows), "day")
    if not total:
        return f"Nothing was decided in the last {span}."
    parts = [f"{totals[g]} {_GROUP_SENTENCE[g]}" for g in GROUP_ORDER if totals[g]]
    return f"{_plural(total, 'decision')} in the last {span}: {_oxford(parts)}."


def _decided_svg(rows: list[dict], frame: _Frame, label: str, every: int) -> str:
    n = len(rows)
    per = [_decided(r) for r in rows]
    totals = [sum(p.values()) for p in per]
    ymax, step = _scale(max(totals) if totals else 0)
    slot = frame.plot_w / n
    bw = min(28.0 if frame.name == "xwide" else 18.0, slot - 4)
    out = [_open(frame, label)]
    out += _axis(frame, ymax, step)
    for i, (row, counts) in enumerate(zip(rows, per)):
        x = frame.left + slot * i + (slot - bw) / 2
        present = [g for g in GROUP_ORDER if counts[g]]
        if present:
            tip = ", ".join(f"{counts[g]} {_GROUP_SENTENCE[g]}" for g in present)
        else:
            tip = "nothing decided"
        out.append(f"<g><title>{_esc(_day(row.get('date')))}: {_esc(tip)}</title>")
        nominal = frame.base
        for j, g in enumerate(present):
            full = frame.plot_h * counts[g] / ymax
            nominal_top = nominal - full
            draw_bottom = nominal - (_GAP if j else 0.0)
            draw_h = max(draw_bottom - nominal_top, _MIN_SEG)
            is_top = j == len(present) - 1
            out.append(
                f'<path class="cv-{g}" d="{_col_path(x, draw_bottom - draw_h, bw, draw_h, _RADIUS if is_top else 0.0)}"/>'
            )
            nominal = nominal_top
        out.append(
            f'<rect x="{_f(frame.left + slot * i)}" y="{frame.top}" width="{_f(slot)}" '
            f'height="{frame.plot_h}" fill="transparent"/></g>'
        )
        if (n - 1 - i) % every == 0:
            out.append(
                f'<text class="cv-t" x="{_f(x + bw / 2)}" y="{frame.height - 8}" '
                f'text-anchor="middle">{_esc(_day(row.get("date")))}</text>'
            )
    out.append("</svg>")
    return "".join(out)


def decided_chart(series: Any) -> Markup:
    """The "What got decided, night by night" figure: stacked columns,
    last three weeks. A night with no decisions is an empty slot."""
    rows = _decided_rows(series)
    if not rows:
        return _empty("decided", decided_sentence(series))
    label = (
        "Decisions each night by outcome, last three weeks. "
        + decided_sentence(series)
        + " The table below the chart lists every night."
    )
    narrow = _decided_svg(rows, _NARROW, label, every=5)
    wide = _decided_svg(rows, _WIDE, label, every=3)
    xwide = _decided_svg(rows, _XWIDE, label, every=2)
    table = _table(
        ("Night", *(GROUP_WORDS[g] for g in GROUP_ORDER)),
        ((_day(r.get("date")), *(str(_decided(r)[g]) for g in GROUP_ORDER)) for r in rows),
        "Decisions each night, by outcome",
    )
    return _figure("decided", narrow, wide, xwide, table)


# --------------------------------------------- 3. Where lessons come from


def _supply_rows(supply_mix: Any) -> list[tuple[str, int]]:
    """``(words, count)`` ranked high to low; ties keep the CLI's order."""
    if not isinstance(supply_mix, dict):
        return []
    rows = []
    for key, value in supply_mix.items():
        n = _int(value)
        if n is None:
            continue
        rows.append((SUPPLY_WORDS.get(str(key), str(key)), max(n, 0), str(key)))
    rows.sort(key=lambda r: -r[1])
    return [(w, n) for w, n, _k in rows]


def supply_sentence(supply_mix: Any) -> str:
    if not isinstance(supply_mix, dict):
        return "There is no count of where lessons come from yet."
    pairs = []
    for key, value in supply_mix.items():
        n = _int(value)
        if n is not None:
            pairs.append((str(key), max(n, 0)))
    total = sum(n for _k, n in pairs)
    if not total:
        return "No lessons have been counted yet."
    key, top = max(pairs, key=lambda p: p[1])
    source = _SUPPLY_SENTENCE.get(key, SUPPLY_WORDS.get(key, key))
    return f"Of {total} lessons so far, {top} came from {source}."


def _supply_svg(rows: list[tuple[str, int]], frame: _Frame, label: str) -> str:
    vmax = max((n for _w, n in rows), default=0) or 1
    wide = frame.name != "narrow"  # wide drawings put the words left of the bar
    row_h = 30 if wide else 44
    height = 8 + row_h * len(rows)
    label_w = (260 if frame.name == "xwide" else 232) if wide else 0
    out = [_open(frame, label, height)]
    bar_left = label_w + 4 if wide else 4
    bar_room = frame.width - bar_left - 44
    for i, (words, n) in enumerate(rows):
        y = 4 + i * row_h
        w = bar_room * n / vmax
        if wide:
            out.append(
                f'<text class="cv-lbl" x="{label_w}" y="{y + 19}" text-anchor="end">{_esc(words)}</text>'
            )
            by = y + 5
        else:
            out.append(f'<text class="cv-lbl" x="{bar_left}" y="{y + 12}">{_esc(words)}</text>')
            by = y + 19
        bh = 20
        out.append(f"<g><title>{_esc(words)}: {n}</title>")
        if w >= 1:
            out.append(f'<path class="cv-use" d="{_bar_path(bar_left, by, w, bh)}"/>')
        out.append("</g>")
        out.append(
            f'<text class="cv-lbl" x="{_f(bar_left + w + 6)}" y="{by + 15}">{n}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def _bar_path(x: float, y: float, w: float, h: float, r: float = _RADIUS) -> str:
    """A horizontal bar growing right from ``x``: data end rounded, base square."""
    r = min(r, w, h / 2)
    if r < 0.75:
        return f"M{_f(x)},{_f(y)} H{_f(x + w)} V{_f(y + h)} H{_f(x)} Z"
    return (
        f"M{_f(x)},{_f(y)} H{_f(x + w - r)} Q{_f(x + w)},{_f(y)} {_f(x + w)},{_f(y + r)} "
        f"V{_f(y + h - r)} Q{_f(x + w)},{_f(y + h)} {_f(x + w - r)},{_f(y + h)} H{_f(x)} Z"
    )


def supply_chart(supply_mix: Any) -> Markup:
    """The "Where do lessons come from?" figure: ranked bars, one hue (the
    heading names the one series, so no legend)."""
    rows = _supply_rows(supply_mix)
    if not rows:
        return _empty("supply", supply_sentence(supply_mix))
    label = "Where lessons come from, all time. " + supply_sentence(supply_mix)
    narrow = _supply_svg(rows, _NARROW, label)
    wide = _supply_svg(rows, _WIDE, label)
    xwide = _supply_svg(rows, _XWIDE, label)
    table = _table(("Source", "Lessons"), ((w, str(n)) for w, n in rows), "Where lessons come from, all time")
    return _figure("supply", narrow, wide, xwide, table)


#: Registered on the Jinja environment by ``app._build_templates`` so a
#: template (``partials/home_charts.html``, ``report.html``) calls them by
#: name. They return Markup, so autoescape leaves the SVG alone and every
#: dynamic piece inside has already been escaped here.
TEMPLATE_GLOBALS: dict[str, Any] = {
    "chart_waiting": waiting_chart,
    "chart_waiting_sentence": waiting_sentence,
    "chart_decided": decided_chart,
    "chart_decided_sentence": decided_sentence,
    "chart_decided_legend": decided_legend,
    "chart_supply": supply_chart,
    "chart_supply_sentence": supply_sentence,
}
