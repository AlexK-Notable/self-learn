"""Base template skeleton tests (10 §3 task U1 bullet 4)."""

from __future__ import annotations

from pathlib import Path

BASE_HTML = (
    Path(__file__).resolve().parents[1] / "templates" / "base.html"
).read_text(encoding="utf-8")

# Documentation comments in the file legitimately mention the banned
# patterns by name (explaining the rule) — strip HTML comments before
# scanning for actual occurrences of those patterns in markup.
import re as _re  # noqa: E402

BASE_HTML_NO_COMMENTS = _re.sub(r"<!--.*?-->", "", BASE_HTML, flags=_re.S)


def test_base_template_exists_with_expected_blocks() -> None:
    for block in (
        "{% block header %}",
        "{% block status_strip %}",
        "{% block content %}",
        "{% block keymap_footer %}",
        "{% block keymap_json %}",
    ):
        assert block in BASE_HTML, f"missing {block}"


def test_no_template_turns_autoescape_off_and_the_environment_has_it_on() -> None:
    """app.py's rule: explicit `autoescape=True`, constructed once, and
    never an `{% autoescape false %}` block anywhere in the template tree
    ("enforced by convention + tests/test_templates.py"). The old test only
    looked for a comment in base.html, so it stayed green if app.py dropped
    `autoescape=True` or a partial gained an `{% autoescape false %}` block
    (test audit L9-65, mutation run M-20)."""
    from self_learn_ui.app import _build_templates

    assert _build_templates().env.autoescape is True

    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    sources = {
        path: path.read_text(encoding="utf-8") for path in sorted(templates_dir.rglob("*.html"))
    }
    # Positive control: the sweep really reached the tree, base.html included.
    assert templates_dir / "base.html" in sources
    assert len(sources) > 1
    offenders = []
    for path, text in sources.items():
        # Jinja comments and HTML comments may name the banned tag in prose.
        text = _re.sub(r"\{#.*?#\}", "", text, flags=_re.S)
        text = _re.sub(r"<!--.*?-->", "", text, flags=_re.S)
        if _re.search(r"\{%[-+]?\s*autoescape\b(?!\s+true\b)", text):
            offenders.append(path.name)
    assert offenders == []


def test_base_template_has_no_inline_style_attributes() -> None:
    assert 'style="' not in BASE_HTML_NO_COMMENTS


def test_base_template_has_no_inline_style_blocks() -> None:
    assert "<style>" not in BASE_HTML_NO_COMMENTS


def test_base_template_has_no_inline_script_blocks() -> None:
    """Only vendored <script src=...> tags and the JSON data blob are
    allowed — no executable inline <script> body anywhere (CSP:
    script-src 'self'). Wired at U3 (10 §3 task U3: "app.js EventSource
    client + keydown handler")."""
    assert 'src="/static/app.js"' in BASE_HTML  # wired at U3
    assert "static/htmx-2.0.9.min.js" in BASE_HTML
    assert 'type="application/json"' in BASE_HTML
    # No inline, non-JSON <script>...</script> body: every <script> tag
    # in this file is either self-closing-via-src or the JSON data blob.
    import re as _re2

    for match in _re2.finditer(r"<script\b([^>]*)>(.*?)</script>", BASE_HTML_NO_COMMENTS, _re2.S):
        attrs, body = match.group(1), match.group(2)
        if "src=" in attrs:
            assert body.strip() == "", "a src= script tag must have no inline body"
        else:
            assert 'type="application/json"' in attrs


def test_terminal_command_text_only_in_the_y11_exempt_surfaces() -> None:
    """09 §11 Y-11 (amended 2026-07-17), the auditable predicate: any
    surface text asking the user to run a terminal command is a defect
    unless recorded exempt. Template-source half: the only `self-learn …`
    command literal in templates is the ARMED host-add bar's own command
    display (the sanctioned consequence rendering). The amendment's
    other exempt entries don't appear as template literals at all —
    `teach --supersedes` (action_bar.html) carries no `self-learn`
    prefix, stderr strips render runtime values, and the 403 recovery
    line is generated in middleware, not a template."""
    import re as _re3

    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    command_literal = _re3.compile(r"self-learn\s+[a-z]")
    offenders = []
    for path in sorted(templates_dir.rglob("*.html")):
        if path.name == "host_add_bar.html":
            continue  # the sanctioned armed command display
        if command_literal.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert offenders == [], f"unsanctioned terminal-command text in: {offenders}"
