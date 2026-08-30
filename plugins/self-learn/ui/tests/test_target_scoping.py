"""U-target §6.1 render-level group — `B1`, `B4`, `C1`, `S1`, `S1b`,
`S2`, `SIG1`.

These are TEMPLATE and SOURCE-SHAPE facts, not orderings: what the
server actually emits, and what the repository actually contains. A
browser would add nothing here, so they are driven through the real
`create_app` + `TestClient` and through the real files on disk. The
orderings — which row a keypress acts on, what the deferred fire does —
live in `test_js_dom_targeting.py`, where a real browser runs the real
`app.js`.

The structural guards (`S1`/`S1b`/`S2`) need ANCESTOR questions ("does
this `[data-key-action]` sit inside a `[data-row]`?", "does this arming
control sit outside every `.action-bar`?"), which a regex over the HTML
cannot answer. This package has no HTML parser dependency, so
`_MiniDom` below builds a small parent-linked tree with `html.parser`
from the stdlib. It is deliberately strict about the one thing that
could make a guard pass VACUOUSLY — a mis-nested tree that reports two
same-row duplicates as living in different rows — and every criterion
that depends on a particular document shape asserts that shape as a
PRECONDITION before it compares anything.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from starlette.testclient import TestClient

from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.keymap import KEYMAP
from self_learn_ui.runner import FakeRunner

from support import (
    make_behavior,
    make_env,
    merge_proposal_text,
    resolve_record_directly,
    seed_proposal,
    seed_record,
)

TOKEN = "u-target-scoping-token"

#: The package root — `C1` and `SIG1` search real files under it.
UI_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = UI_ROOT / "templates"


def make_client(sb, *, port: int = 7357) -> TestClient:
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
    c = TestClient(app, base_url=f"http://127.0.0.1:{port}")
    c.cookies.set("slu_token", TOKEN)
    return c


# --------------------------------------------------------------- mini DOM


#: HTML void elements — they never open a scope, so they must not be
#: pushed onto the nesting stack (an `<input>` would otherwise swallow
#: everything after it into itself and destroy every ancestor answer).
_VOID = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)

#: Tags the HTML parser auto-closes when a new block-level start tag
#: arrives. The templates close their own `<p>`/`<li>` today (asserted
#: by `test_minidom_matches_the_real_nesting` below), but a future edit
#: that leans on the implicit close must not silently corrupt the tree.
_AUTO_CLOSE = {"p": frozenset({"p", "div", "section", "ul", "ol", "li", "form", "h2"}),
               "li": frozenset({"li", "ul", "ol"}),
               "option": frozenset({"option", "select"})}


class _Node:
    __slots__ = ("tag", "attrs", "parent", "children")

    def __init__(self, tag: str, attrs: dict[str, str], parent: "_Node | None") -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node] = []

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        ident = self.attrs.get("id") or self.attrs.get("class") or ""
        return f"<{self.tag} {ident!r}>"


class _MiniDom(HTMLParser):
    """A parent-linked element tree. Recovery on a stray close tag pops
    to the matching open (the browser's own rule) rather than silently
    dropping it, so a template typo shows up as a wrong ancestor — which
    every guard below turns into a FAILURE, never a pass."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#document", {}, None)
        self._stack = [self.root]
        self.unmatched_close_tags: list[str] = []

    def handle_starttag(self, tag, attrs):
        implied = _AUTO_CLOSE.get(self._stack[-1].tag)
        if implied and tag in implied:
            self._stack.pop()
        node = _Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = _Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for idx in range(len(self._stack) - 1, 0, -1):
            if self._stack[idx].tag == tag:
                del self._stack[idx:]
                return
        self.unmatched_close_tags.append(tag)


def parse(html: str) -> _Node:
    p = _MiniDom()
    p.feed(html)
    p.close()
    assert not p.unmatched_close_tags, (
        "the document has close tags with no matching open "
        f"({p.unmatched_close_tags[:5]}) — every ancestor answer below "
        "would be unreliable"
    )
    return p.root


def walk(node: _Node):
    for child in node.children:
        yield child
        yield from walk(child)


def with_attr(root: _Node, name: str) -> list[_Node]:
    return [n for n in walk(root) if name in n.attrs]


def closest(node: _Node, predicate) -> _Node | None:
    cur = node.parent
    while cur is not None:
        if predicate(cur):
            return cur
        cur = cur.parent
    return None


def _is_row(n: _Node) -> bool:
    return "data-row" in n.attrs


def _is_action_bar(n: _Node) -> bool:
    return "action-bar" in n.classes()


# ------------------------------------------------------------- fixtures


def _front_sandbox(tmp_path: Path):
    """Front with **2 holding rows** and **2 follow-up rows** — `S1`'s
    stated fixture.

    Holding rows are routed records carrying an unconfirmed
    `recurrence-suspect` telemetry event (only the real `self-learn
    report --json` CLI computes them, the same way
    `test_js_dom.py::_seed_holding_ledger` builds them). Follow-up rows
    are routed records whose routing block still carries `follow_up`
    (`ledger_ops.open_followups`). They are DISJOINT sets on purpose: a
    record that was both would inflate one count while leaving the
    other short."""
    sb = make_env(tmp_path, skills=("s",))
    bucket_dir = sb.ledger / "skills" / "s"
    holding_ids = ("lrn-c0100001", "lrn-c0100002")
    for rid in holding_ids:
        rec = make_behavior(scope="skill:s", record_id=rid, trigger=f"Holding {rid}.")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, bucket_dir, rec, status="routed")
    tel = sb.ledger / "telemetry"
    tel.mkdir(parents=True, exist_ok=True)
    tel.joinpath("2026-07.u-target.jsonl").write_text(
        "".join(
            '{"kind": "recurrence-suspect", "record": "%s", '
            '"nonce": "u-target-nonce-%s", "ts": "2026-07-20T00:00:00Z"}\n' % (rid, rid)
            for rid in holding_ids
        ),
        encoding="utf-8",
    )
    for rid in ("lrn-c0200001", "lrn-c0200002"):
        rec = make_behavior(scope="skill:s", record_id=rid, trigger=f"Followup {rid}.")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, bucket_dir, rec, status="routed")
        _attach_follow_up(bucket_dir / "resolved" / f"{rid}.md")
    return sb


def _attach_follow_up(path: Path) -> None:
    from self_learn.records import Record

    rec = Record.from_path(path)
    rec.set_follow_up("widen the guard once the upstream fix lands")
    rec.write(path)


def _bucket_sandbox(tmp_path: Path):
    """Bucket with **2 pending record rows** and a **bulk-collapse
    group**, no cluster — `S1`'s and `B1`'s stated fixture.

    The bulk row renders only for a group whose EVERY row is
    `already_canon` (`models.py:1436-1444`, which then sets `rows = ()`
    so the bulk row REPLACES that group's record rows). So the
    already-canon record carries a proposal with `destination:
    skill-md`, and the two plain rows carry no proposal at all, which
    lands them in `no-analysis` — a group `models.py` deliberately
    excludes from bulk collapse."""
    sb = make_env(tmp_path, skills=("s",))
    canon = make_behavior(scope="skill:s", record_id="lrn-c0300001", trigger="Canon one.")
    seed_record(sb.ledger, canon)
    seed_proposal(
        sb.ledger,
        canon.id,
        scope="skill:s",
        destination="skill-md",
        already_canon=True,
        already_canon_reason="SKILL.md already says this",
    )
    for rid in ("lrn-c0400001", "lrn-c0400002"):
        seed_record(
            sb.ledger,
            make_behavior(scope="skill:s", record_id=rid, trigger=f"Plain {rid}."),
        )
    return sb


CLUSTER_ID = "merge-deadbeef"
CLUSTER_MEMBERS = ("lrn-c0500001", "lrn-c0500002")
CLUSTER_PLAIN = ("lrn-c0600001", "lrn-c0600002")


def _cluster_sandbox(tmp_path: Path):
    """A bucket carrying a valid `merge-*.yaml` over 2 records, plus 2
    plain pending record rows — the document `S1b`/`S2` inspect and the
    CO-ARM fixture the browser module drives."""
    sb = make_env(tmp_path, skills=("s",))
    for rid in CLUSTER_MEMBERS + CLUSTER_PLAIN:
        seed_record(
            sb.ledger,
            make_behavior(scope="skill:s", record_id=rid, trigger=f"Cluster fixture {rid}."),
        )
    pdir = sb.ledger / "skills" / "s" / "proposals"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{CLUSTER_ID}.yaml").write_text(
        merge_proposal_text(CLUSTER_ID, list(CLUSTER_MEMBERS), CLUSTER_MEMBERS[0]),
        encoding="utf-8",
    )
    return sb


def _compose_cluster_page(client: TestClient) -> str:
    """`S1b` FIXTURE PROVENANCE (gate r3 MINOR-1). `cluster_expanded.html`
    renders from exactly ONE route — `GET
    /cluster/{scope}/{name}/{cluster_id}` — so a plain Bucket `GET`
    contains NO cluster at all, and a criterion that inspected the plain
    page would compare an empty set to an empty expectation and pass
    while looking at a cluster-free document. This splices the cluster
    response into the bucket page at its own `#cluster-target-<id>`
    slot, exactly as htmx's `hx-swap="innerHTML"` does in the browser."""
    page = client.get("/bucket/skill/s").text
    fragment = client.get(f"/cluster/skill/s/{CLUSTER_ID}").text
    slot = f'<div id="cluster-target-{CLUSTER_ID}"></div>'
    assert slot in page, "the cluster row's swap slot is not on the bucket page"
    return page.replace(slot, f'<div id="cluster-target-{CLUSTER_ID}">{fragment}</div>')


def _assert_cluster_precondition(root: _Node) -> list[_Node]:
    """`S1b`/`S2`'s FAIL-LOUD precondition. Without it both criteria
    compare empty to empty on a document containing no cluster — the
    vacuous-pass shape this whole unit exists to stop."""
    expanded = [n for n in walk(root) if "cluster-expanded" in n.classes()]
    assert expanded, (
        "no .cluster-expanded element in the composed document — the "
        "fixture did not splice the cluster in, and everything below "
        "would compare an empty set to an empty expectation"
    )
    routes = [
        n
        for n in walk(expanded[0])
        if n.attrs.get("data-key-action") == "route"
    ]
    assert len(routes) >= 2, (
        f"the expanded cluster carries {len(routes)} route buttons, need >=2 "
        "— a one-member cluster cannot exhibit the same-row multiplicity "
        "this criterion is about"
    )
    return expanded


# ------------------------------------------------------------ the guards


def test_minidom_matches_the_real_nesting(tmp_path: Path) -> None:
    """Guard-of-the-guard for `_MiniDom`. Every structural criterion
    below rests on ancestor answers; a parser that mis-nested would
    report two same-row duplicates as living in DIFFERENT rows and turn
    `S1`/`S1b` into passes that inspect nothing. Positive control: the
    parser finds the SAME number of `[data-row]` elements a regex-free
    attribute count does, and every action bar on a bucket page resolves
    to the record row whose id it names."""
    sb = _bucket_sandbox(tmp_path)
    html = make_client(sb).get("/bucket/skill/s").text
    root = parse(html)
    rows = with_attr(root, "data-row")
    assert len(rows) == html.count("data-row>") + html.count('data-row ')
    bars = [n for n in walk(root) if _is_action_bar(n)]
    assert bars, "no .action-bar on the bucket page — fixture is wrong"
    for bar in bars:
        rid = (bar.attrs.get("id") or "").removeprefix("action-bar-")
        if not rid.startswith("lrn-"):
            continue
        row = closest(bar, _is_row)
        assert row is not None, f"{bar.attrs.get('id')} has no [data-row] ancestor"
        assert "record-row" in row.classes()


class TestC1DataKeyContextDeleted:
    def test_c1_data_key_context_has_zero_occurrences(self) -> None:
        """`C1` — `data-key-context` was declared at `action_bar.html:10`
        and `pane.html:16` and read by NOTHING. It is DELETED, not wired:
        `KEYMAP` binds `g` -> `graduate` with `context="detail"`, but
        `action_bar.html`'s holding branch renders
        `data-key-context="holding"` on a bar carrying
        `data-key-action="graduate"` — a filter requiring the two to
        match would make `g` DEAD on Front's holding rows, a regression
        delivered by the very mechanism meant to fix targeting."""
        hits = _grep_ui_tree("data-key-context")
        assert hits == [], f"data-key-context is back at: {hits}"
        # Positive control in the same test: the identical search for an
        # attribute that IS consumed comes back non-empty, so a zero
        # above cannot be "the search saw nothing at all".
        control = _grep_ui_tree("data-noop-hint")
        assert control, "the search itself is blind — it found no data-noop-hint either"


class TestSIG1NoPrefixedHtmxAttributes:
    def test_sig1_templates_never_use_the_data_hx_form(self) -> None:
        """`SIG1` — `targetSignature()` reads the PLAIN `hx-post`/
        `hx-vals`/`hx-include` attributes. htmx also honours a
        `data-hx-*` prefixed form; if a template ever switched, the
        signature would silently weaken (every leg reading `null`), and
        the deferred-fire guard would go quietly inert on the surfaces
        it was built for. This fails first."""
        hits = [
            f"{p.relative_to(UI_ROOT)}"
            for p in sorted(TEMPLATES.rglob("*.html"))
            if "data-hx-" in p.read_text(encoding="utf-8")
        ]
        assert hits == [], f"templates using htmx's prefixed form: {hits}"
        control = [
            p for p in TEMPLATES.rglob("*.html") if "hx-post" in p.read_text(encoding="utf-8")
        ]
        assert control, "the search itself is blind — it found no hx-post either"


def _grep_ui_tree(needle: str) -> list[str]:
    out = []
    for pattern in ("templates/**/*.html", "src/**/*.py", "static/*.js", "static/*.css"):
        for path in sorted(UI_ROOT.glob(pattern)):
            if needle in path.read_text(encoding="utf-8"):
                out.append(str(path.relative_to(UI_ROOT)))
    return out


class TestBulkCollapseRowShape:
    def test_b1_bulk_button_is_gated_not_key_bound(self, tmp_path: Path) -> None:
        """`B1` — against the REAL rendered HTML of a bucket page whose
        `skill-md` group is bulk-collapsed. The button that posts
        straight to `graduate-bulk` with a hidden multi-record `ids`
        field must carry NO `data-key-action`, and must carry the gated
        `[data-noop-hint][data-noop-action="graduate"]` pair instead."""
        sb = _bucket_sandbox(tmp_path)
        html = make_client(sb).get("/bucket/skill/s").text
        root = parse(html)
        bulk_rows = [n for n in walk(root) if "bulk-collapse-row" in n.classes()]
        assert len(bulk_rows) == 1, (
            f"expected exactly one bulk-collapse row, got {len(bulk_rows)} — "
            "the fixture is not exercising the shape this criterion is about"
        )
        buttons = [n for n in walk(bulk_rows[0]) if n.tag == "button"]
        assert len(buttons) == 1, f"bulk row has {len(buttons)} buttons"
        button = buttons[0]
        assert "data-key-action" not in button.attrs, (
            "the bulk-collapse button is keyboard-dispatchable again — one "
            "press of `g` posts graduate-bulk with a multi-record ids field, "
            "un-armed"
        )
        assert button.attrs.get("data-noop-action") == "graduate"
        assert button.attrs.get("data-noop-hint", "").strip(), (
            "the gated pair needs its hint text — without it `g` on the "
            "selected bulk row refuses SILENTLY"
        )
        # The precondition that makes this criterion non-vacuous: the
        # button really is the multi-record write.
        form = closest(button, lambda n: n.tag == "form")
        assert form is not None and form.attrs.get("hx-post", "").endswith("/graduate-bulk")
        ids = [n for n in walk(form) if n.attrs.get("name") == "ids"]
        assert len(ids) == 1 and ids[0].attrs.get("value")

    def test_b4a_bulk_button_carries_no_key_action_attribute(self, tmp_path: Path) -> None:
        """`B4` half (a) — stated as its own mechanically checkable
        assertion (gate r1 MINOR-3: r1's "or any other name bound to the
        bulk button" could only fail if someone added what nobody
        proposed). The attribute is absent, whatever its value would
        have been."""
        sb = _bucket_sandbox(tmp_path)
        html = make_client(sb).get("/bucket/skill/s").text
        root = parse(html)
        bulk_rows = [n for n in walk(root) if "bulk-collapse-row" in n.classes()]
        assert len(bulk_rows) == 1
        assert [n for n in walk(bulk_rows[0]) if "data-key-action" in n.attrs] == []

    def test_b4b_keymap_action_list_is_pinned(self) -> None:
        """`B4` half (b) — the whole `KEYMAP` action list, pinned
        literally, so ANY entry added or renamed reddens: including one
        named for the bulk write. No new keymap entry is added by this
        unit; "give bulk graduate its own key after it has an arm step"
        is deferred as `[B-1]`.

        *Honesty note carried from the spec: `B4` is a cheap guard, not a
        load-bearing pin.*"""
        assert [e.action for e in KEYMAP] == [
            "move_down",
            "move_up",
            "drill_in",
            "up",
            "route",
            "reject",
            "defer",
            "graduate",
            "iterate",
            "cycle_destination",
            "note",
            "toggle_brief",
            "tolerate",
            "confirm_recurrence",
            "dismiss_suspect",
            "confirm_held",
            "retry",
            "close_pane",
            "bucket_pane",
            "arm_proposal",
            "success_next",
            "success_bucket",
            "success_view",
            "help",
        ]


# --------------------------------------------------------- S1 / S1b / S2


def _duplicate_report(root: _Node) -> dict[str, list[_Node]]:
    """Every `data-key-action` VALUE present in the document — not only
    the KEYMAP-bound ones (gate r1 MAJOR-4: scoping this to bound
    actions made it blind to `followup_done` and `link_contradicts`,
    the very latent class §3.2 says must be closed)."""
    buckets: dict[str, list[_Node]] = {}
    for node in walk(root):
        action = node.attrs.get("data-key-action")
        if action:
            buckets.setdefault(action, []).append(node)
    return buckets


def _s1_violations(root: _Node) -> list[str]:
    """`S1`'s rule: for every action value, EITHER it occurs exactly once
    in the document, OR every occurrence has a `[data-row]` ancestor and
    no two occurrences share the same `[data-row]` ancestor."""
    bad: list[str] = []
    for action, nodes in sorted(_duplicate_report(root).items()):
        if len(nodes) == 1:
            continue
        rows = [closest(n, _is_row) for n in nodes]
        if any(r is None for r in rows):
            bad.append(f"{action}: {len(nodes)} occurrences, some outside any [data-row]")
            continue
        if len({id(r) for r in rows}) != len(rows):
            bad.append(f"{action}: two occurrences share one [data-row]")
    return bad


class TestS1NoSameRowDuplicates:
    """`S1` — the structural guard. The DISPATCH fix closes the latent
    class by construction (`resolveScoped` is action-agnostic, so a key
    bound to `followup_done` tomorrow is scoped the day it is bound);
    this is what stops a TEMPLATE from re-opening it.

    **Stated coverage, honestly:** this guard does NOT catch the
    bulk-collapse shape — the bulk row and the record rows are distinct
    `[data-row]`s — which is why `B1`/`B2`/`B3` exist as separate
    criteria. A guard whose coverage is overstated is worse than no
    guard."""

    def test_s1_front(self, tmp_path: Path) -> None:
        sb = _front_sandbox(tmp_path)
        html = make_client(sb).get("/").text
        root = parse(html)
        # Precondition: the page really carries the duplicated shapes.
        holding = [n for n in walk(root) if "holding-row" in n.classes()]
        followups = [n for n in walk(root) if "followup-row" in n.classes()]
        assert len(holding) >= 2, f"need >=2 holding rows, got {len(holding)}"
        assert len(followups) >= 2, f"need >=2 follow-up rows, got {len(followups)}"
        actions = _duplicate_report(root)
        assert "followup_done" in actions, (
            "the follow-up rows rendered no `followup_done` target — this "
            "criterion would then never inspect the latent class it exists for"
        )
        assert _s1_violations(root) == []

    def test_s1_bucket(self, tmp_path: Path) -> None:
        sb = _bucket_sandbox(tmp_path)
        html = make_client(sb).get("/bucket/skill/s").text
        root = parse(html)
        rows = [n for n in walk(root) if "record-row" in n.classes()]
        assert len(rows) >= 2, f"need >=2 record rows, got {len(rows)}"
        assert [n for n in walk(root) if "bulk-collapse-row" in n.classes()], (
            "no bulk-collapse group on this page"
        )
        assert [n for n in walk(root) if "cluster-expanded" in n.classes()] == [], (
            "a cluster is expanded on S1's fixture — that shape belongs to S1b"
        )
        assert _s1_violations(root) == []

    def test_s1_detail(self, tmp_path: Path) -> None:
        sb = _bucket_sandbox(tmp_path)
        html = make_client(sb).get("/record/lrn-c0400001").text
        root = parse(html)
        assert with_attr(root, "data-row") == [], (
            "a Detail page grew a [data-row] — S1's clause (b) would then "
            "be doing work here, and this fixture is meant to prove the "
            "unique-by-construction surface stays unique"
        )
        assert _duplicate_report(root), "no data-key-action on the Detail page at all"
        assert _s1_violations(root) == []


class TestS1bClusterIsTheOneSanctionedSameRowSet:
    def test_s1b_only_cluster_route_buttons_share_a_row(self, tmp_path: Path) -> None:
        """`S1b` — on the composed cluster document, the ONLY
        same-`[data-row]` duplicate sets are the `route` buttons inside a
        `.cluster-expanded` element. This is the one sanctioned same-row
        multiplicity in the codebase: it is dispatch-covered by `T6`'s
        refusal, and removing it means making members individually
        selectable, which is `[B-2]`.

        Split from `S1` rather than folded into it because `S1`'s clause
        (b) is FALSE on the intended tree the moment a cluster is
        expanded — a single-fixture `S1` covering both shapes would be a
        criterion that cannot pass."""
        sb = _cluster_sandbox(tmp_path)
        html = _compose_cluster_page(make_client(sb))
        root = parse(html)
        _assert_cluster_precondition(root)

        offenders: list[str] = []
        for action, nodes in sorted(_duplicate_report(root).items()):
            if len(nodes) == 1:
                continue
            rows = [closest(n, _is_row) for n in nodes]
            if any(r is None for r in rows):
                offenders.append(f"{action}: an occurrence outside any [data-row]")
                continue
            seen: dict[int, _Node] = {}
            for node, row in zip(nodes, rows):
                if id(row) in seen:
                    inside_cluster = closest(
                        node, lambda n: "cluster-expanded" in n.classes()
                    ) is not None
                    if not (action == "route" and inside_cluster):
                        offenders.append(
                            f"{action}: an unsanctioned same-[data-row] duplicate"
                        )
                seen[id(row)] = node
        assert offenders == [], offenders


class TestS2ArmingControlInventory:
    def test_s2_only_cluster_members_arm_from_outside_a_bar(self, tmp_path: Path) -> None:
        """`S2` — the arming-control INVENTORY, and a detector rather
        than a fix.

        `style.css:433` (`body:has(.action-bar[data-armed="true"])
        .action-bar[data-armed="false"] button { visibility: hidden }`)
        is the only thing stopping a MOUSE from stacking a second armed
        bar, and it works by `.action-bar` ANCESTRY. So any control that
        arms from OUTSIDE a `.action-bar` silently escapes it and
        re-opens the co-arm door `A1`/`A2`/`A5` exist to govern. Exactly
        one does today: the cluster member's "Route as survivor" button.

        **The predicate is `/arm$`, not `/action/arm$`** (gate r2
        MINOR-4). Four distinct arming routes exist —
        `/record/{id}/action/arm`, `/record/{id}/action/commit-drift/arm`,
        `/proposal/arm`, `/bucket/{scope}/{name}/host-add/arm` — and the
        narrower suffix would have been GREEN while blind to three of
        them.

        **Stated coverage, honestly:** this sees only controls whose own
        `hx-post` ends in `/arm`. It does NOT see a control that arms
        indirectly (a plain `<button>` wired by future JS, a link, a form
        whose action is computed at runtime), and it does not see the
        bulk-collapse WRITE (`/graduate-bulk`), which is outside a
        `.action-bar` too and is tracked separately as `[B-1]`. Closing
        the door itself is `[B-7]`."""
        sb = _cluster_sandbox(tmp_path)
        html = _compose_cluster_page(make_client(sb))
        root = parse(html)
        expanded = _assert_cluster_precondition(root)

        arming: list[_Node] = []
        for node in walk(root):
            post = node.attrs.get("hx-post")
            if post and post.endswith("/arm"):
                arming.append(node)
            elif node.tag in ("button", "input") and node.attrs.get("type") == "submit":
                form = closest(node, lambda n: n.tag == "form")
                if form is not None and (form.attrs.get("hx-post") or "").endswith("/arm"):
                    arming.append(node)
        assert arming, "no arming control found at all — the predicate is blind"

        outside = [n for n in arming if closest(n, _is_action_bar) is None]
        cluster_buttons = [
            n
            for n in walk(expanded[0])
            if n.attrs.get("data-key-action") == "route"
        ]
        assert {id(n) for n in outside} == {id(n) for n in cluster_buttons}, (
            "the set of arming controls with no .action-bar ancestor is no "
            "longer exactly the cluster-member 'Route as survivor' buttons — "
            "a new one silently escapes style.css:433's modal rule and "
            "re-opens the co-arm door (§2.7 c). The bulk-collapse button is "
            "a KNOWN, separately-tracked exception: it is not an arming "
            "control but an un-armed multi-record WRITE outside a bar "
            "([B-1]).\n"
            f"  outside a bar: {outside}\n"
            f"  expected:      {cluster_buttons}"
        )
