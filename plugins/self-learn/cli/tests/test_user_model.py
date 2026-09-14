"""U2 · The model of the user (`02-schema.md` §3a.4, S-65).

Mutation checks pinned here (each recorded red-then-green in the U2
report): (g) `mark_seen` flips the stored flag and nothing else, and a
`presented` observation with `entries: []` flips nothing; (h)
`lapse_entry` refuses without a named changed condition, and no code
path here lapses on age.
"""

from __future__ import annotations

import contextlib
import inspect
import re

import pytest

from self_learn import user_model
from support import make_home


def test_add_entry_creates_container_a_own_words(tmp_path):
    home = make_home(tmp_path)
    entry_id = user_model.add_entry(
        home, container="A", title="cost-sensitivity was a symptom",
        because='(the user\'s words) "cost-sensitivity was a symptom"',
        source="own-words", by="steward", ref="stmt-2b7e91c0",
        recorded_by="steward",
    )
    assert user_model.UM_ID_RE.match(entry_id)
    doc = user_model.show(home)
    entry = next(e for e in doc["containers"]["A"] if e["id"] == entry_id)
    assert entry["status"] == "CURRENT"
    assert entry["r"] == 1
    assert "provisional" not in entry
    assert doc["frontmatter"]["revision"] == 1


def test_add_entry_container_b_refuses_direct_add(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="B", title="x", because="y",
            source="system-reading", by="steward", ref="case-x",
            statements=["stmt-11112222"],
        )


def test_add_entry_container_d_only_overseer(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="D", title="x", because="y",
            source="system-reading", by="steward", ref="telemetry:e1",
        )
    entry_id = user_model.add_entry(
        home, container="D", title="x", because="y",
        source="system-reading", by="overseer", ref="telemetry:e1",
    )
    assert user_model.UM_ID_RE.match(entry_id)


def test_add_entry_container_c_needs_a_statement_id(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="C", title="x", because="y",
            source="system-reading", by="steward", ref="case-x",
            statements=[],
        )


def test_add_entry_refuses_forbidden_vocabulary(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="A", title="the user ratified this",
            because="because text", source="own-words", by="human",
            ref="stmt-11112222",
        )
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="A", title="ok title",
            because="the user stated this in passing",
            source="own-words", by="human", ref="stmt-11112222",
        )


def test_add_entry_secret_scan_refuses(tmp_path):
    home = make_home(tmp_path)
    token = "ghp_" + "Ab1" * 12
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="A", title="ok",
            because=f"the token is {token}",
            source="own-words", by="human", ref="stmt-11112222",
        )


# ------------------------------------------------------------- (g) mark_seen


def _seed_provisional_entry(home, *, container="C") -> str:
    return user_model.add_entry(
        home, container=container, title="load cost dominates",
        because="the pipeline was misrouting lessons",
        source="system-reading", by="steward",
        conditions=["report.destinations"], ref="case-00000000",
        statements=["stmt-11112222"],
    )


def test_g_mark_seen_flips_only_provisional_and_moves_c_to_b(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    before = next(
        e for e in user_model.show(home)["containers"]["C"] if e["id"] == entry_id
    )

    user_model.mark_seen(home, entry_id)

    doc = user_model.show(home)
    assert not any(e["id"] == entry_id for e in doc["containers"]["C"])
    after = next(e for e in doc["containers"]["B"] if e["id"] == entry_id)
    assert after["provisional"] is False
    assert after["r"] == before["r"], "mark_seen must never bump r (it is not a dependency move)"
    for key in ("held_since", "because", "conditions", "status", "source", "ref", "statements"):
        assert after[key] == before[key], f"mark_seen changed {key!r} — it must change nothing but provisional"


def test_g_mark_seen_is_idempotent_on_an_already_seen_entry(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    user_model.mark_seen(home, entry_id)
    rev_after_first = user_model.show(home)["frontmatter"]["revision"]
    user_model.mark_seen(home, entry_id)  # no-op, must not error
    doc = user_model.show(home)
    after = next(e for e in doc["containers"]["B"] if e["id"] == entry_id)
    assert after["provisional"] is False
    assert doc["frontmatter"]["revision"] >= rev_after_first


def test_g_mark_seen_refuses_an_own_words_entry(tmp_path):
    home = make_home(tmp_path)
    entry_id = user_model.add_entry(
        home, container="A", title="own words entry", because="because text",
        source="own-words", by="human", ref="stmt-11112222",
    )
    with pytest.raises(user_model.UserModelError):
        user_model.mark_seen(home, entry_id)


def test_g_presented_observation_with_no_entries_flips_nothing(tmp_path):
    """The `cases.observe(kind="presented", entries=[])` half of check
    (g) is exercised end to end in `test_cases.py`
    (`test_observe_presented_with_no_entries_flips_nothing`) — this file
    only owns `user_model.mark_seen` itself, called directly, never with
    an empty list (there is nothing to call it WITH when entries is
    empty; `cases.observe`'s loop over `entries` simply does not run)."""
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    # No call to mark_seen at all — the entry must be exactly as seeded.
    doc = user_model.show(home)
    still_there = next(e for e in doc["containers"]["C"] if e["id"] == entry_id)
    assert still_there["provisional"] is True


# ----------------------------------------------------------- (h) lapse_entry


def test_h_lapse_entry_refuses_without_a_named_cause(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    with pytest.raises(user_model.UserModelUsageError):
        user_model.lapse_entry(home, entry_id, by="steward")


def test_h_lapse_entry_with_changed_condition_succeeds(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    before = next(
        e for e in user_model.show(home)["containers"]["C"] if e["id"] == entry_id
    )
    user_model.lapse_entry(
        home, entry_id, changed_condition="report.destinations", by="steward",
        at="2026-09-20",
    )
    doc = user_model.show(home)
    after = next(e for e in doc["containers"]["C"] if e["id"] == entry_id)
    assert after["status"] == "LAPSED"
    assert after["lapsed_at"] == "2026-09-20"
    assert after["changed_condition"] == "report.destinations"
    assert after["r"] == before["r"] + 1, "lapse IS a substantive status change — it bumps r, unlike mark_seen"

    with pytest.raises(user_model.UserModelError):
        user_model.lapse_entry(home, entry_id, changed_condition="x", by="steward")


def test_h_lapse_entry_accepts_exactly_one_of_the_three_causes(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    with pytest.raises(user_model.UserModelUsageError):
        user_model.lapse_entry(
            home, entry_id, changed_condition="a", contrary="b", by="steward",
        )


def test_h_no_time_based_lapse_anywhere_in_this_module():
    """D6 / seam-reconciliation addendum: "nothing lapses for silence"
    — grep proof, quoted in the U2 report: this module imports and uses
    neither `days` nor `timedelta`."""
    src = inspect.getsource(user_model)
    assert not re.search(r"\bdays\b", src), src
    assert not re.search(r"\btimedelta\b", src), src


# ================================================================ D-a


def test_da_mark_seen_keeps_a_container_d_entry_in_d(tmp_path):
    home = make_home(tmp_path)
    entry_id = user_model.add_entry(
        home, container="D", title="observed regularity", because="because text",
        source="system-reading", by="overseer", ref="telemetry:e1",
    )
    user_model.mark_seen(home, entry_id)
    doc = user_model.show(home)
    after = next(e for e in doc["containers"]["D"] if e["id"] == entry_id)
    assert after["provisional"] is False
    assert not any(e["id"] == entry_id for e in doc["containers"]["B"])


# ================================================================ D-f


def test_df_system_reading_entry_is_always_created_provisional_true(tmp_path):
    home = make_home(tmp_path)
    entry_id = user_model.add_entry(
        home, container="C", title="x", because="y", source="system-reading",
        by="steward", ref="case-00000000", statements=["stmt-11112222"],
    )
    doc = user_model.show(home)
    entry = next(e for e in doc["containers"]["C"] if e["id"] == entry_id)
    assert entry["provisional"] is True
    assert "provisional" not in inspect.signature(user_model.add_entry).parameters


def test_df_no_provisional_flag_is_gone_from_the_cli(tmp_path):
    from self_learn import cli

    parser = cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "user-model", "add", "--container", "C", "--title", "x",
            "--because", "y", "--source", "system-reading", "--by", "steward",
            "--no-provisional",
        ])
    # gate r2 N2: `--provisional` is now gone too (round 1 kept it as an
    # inert flag; round 2 settles the other way — see cli.py's comment).
    with pytest.raises(SystemExit):
        parser.parse_args([
            "user-model", "add", "--container", "C", "--title", "x",
            "--because", "y", "--source", "system-reading", "--by", "steward",
            "--provisional",
        ])
    # positive control: the same command with NEITHER flag still parses
    # — the two `SystemExit`s above are each flag's own rejection, not
    # the whole `user-model add` subcommand having broken.
    args = parser.parse_args([
        "user-model", "add", "--container", "C", "--title", "x",
        "--because", "y", "--source", "system-reading", "--by", "steward",
    ])
    assert args.container == "C"
    assert not hasattr(args, "provisional")


def test_n4_user_model_bump_verb_is_gone(tmp_path):
    """N4 (gate r2 item 9): round 1 dropped `user-model bump` (D-d/S8,
    no spec or draft basis — every other verb already bumps `revision`
    through `_save`) but pinned its removal only incidentally, through
    the full CLI-parser assertions exercised elsewhere. This test names
    the removal directly, the same pattern
    `test_df_no_provisional_flag_is_gone_from_the_cli` uses."""
    from self_learn import cli

    parser = cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["user-model", "bump", "um-1234"])
    # positive control: the parser itself, and its sibling verbs, still work
    args = parser.parse_args(["user-model", "show"])
    assert args.user_model_command == "show"


# ================================================================ S10


def test_s10_container_e_refuses_system_reading(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="E", title="a declared condition", because="y",
            source="system-reading", by="steward", ref="case-00000000",
        )
    # positive control: own-words still works, human and steward/overseer
    entry_id = user_model.add_entry(
        home, container="E", title="a declared condition", because="y",
        source="own-words", by="human", ref="stmt-11112222",
    )
    assert user_model.UM_ID_RE.match(entry_id)


# ============================================================= item 2


def test_2_b2_lapse_entry_scans_the_changed_condition_text(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    token = "ghp_" + "Ab1" * 12
    with pytest.raises(user_model.UserModelError):
        user_model.lapse_entry(
            home, entry_id, contrary=f"the deploy token is {token}", by="steward",
        )
    doc = user_model.show(home)
    still = next(e for e in doc["containers"]["C"] if e["id"] == entry_id)
    assert still["status"] == "CURRENT"


# ============================================================= item 6


def test_6_add_entry_allocates_id_under_the_lock(tmp_path, monkeypatch):
    """Astra 4/10 (fold-u2-r1 item 6). A peer `add_entry` lands, under
    the SAME lock, between this call's "acquire" and its own `_load` —
    reproduced by hooking `intents.ledger_write` to fire the peer write
    the instant the lock is (first) held, before this call's own body
    runs. Fixed code (`_load` under the lock) sees the peer and appends
    onto it — both entries survive. Pre-fix code (`_load` before the
    lock) holds a stale snapshot and its own `_save` clobbers the peer's
    disk write when it rewrites the whole document."""
    home = make_home(tmp_path)
    real_ledger_write = user_model.intents.ledger_write
    state = {"injected": False}

    @contextlib.contextmanager
    def hook(home_arg, **kwargs):
        with real_ledger_write(home_arg, **kwargs) as recovered:
            if not state["injected"]:
                state["injected"] = True
                # A nested acquire of the SAME lock — safe, pass-through.
                user_model.add_entry(
                    home_arg, container="A", title="peer entry",
                    because="peer because text", source="own-words",
                    by="human", ref="stmt-99998888",
                )
            yield recovered

    monkeypatch.setattr(user_model.intents, "ledger_write", hook)

    entry_id = user_model.add_entry(
        home, container="A", title="own entry", because="own because text",
        source="own-words", by="human", ref="stmt-11112222",
    )
    doc = user_model.show(home)
    ids = {e["id"] for e in doc["containers"]["A"]}
    assert entry_id in ids
    assert len(doc["containers"]["A"]) == 2, "the peer's entry must survive, not be clobbered"


def test_6_lapse_entry_reads_current_state_under_the_lock(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    id_a = _seed_provisional_entry(home)
    id_b = user_model.add_entry(
        home, container="A", title="own words b", because="because b",
        source="own-words", by="human", ref="stmt-33334444",
    )
    real_ledger_write = user_model.intents.ledger_write
    state = {"injected": False}

    @contextlib.contextmanager
    def hook(home_arg, **kwargs):
        with real_ledger_write(home_arg, **kwargs) as recovered:
            if not state["injected"]:
                state["injected"] = True
                user_model.lapse_entry(
                    home_arg, id_b, changed_condition="peer cause", by="human",
                )
            yield recovered

    monkeypatch.setattr(user_model.intents, "ledger_write", hook)

    user_model.lapse_entry(home, id_a, changed_condition="own cause", by="steward")

    doc = user_model.show(home)
    a = next(e for e in doc["containers"]["C"] if e["id"] == id_a)
    b = next(e for e in doc["containers"]["A"] if e["id"] == id_b)
    assert a["status"] == "LAPSED"
    assert b["status"] == "LAPSED", "the peer's lapse must survive, not be clobbered"


def test_6_mark_seen_reads_current_state_under_the_lock(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    id_a = _seed_provisional_entry(home)
    id_b = _seed_provisional_entry(home)
    real_ledger_write = user_model.intents.ledger_write
    state = {"injected": False}

    @contextlib.contextmanager
    def hook(home_arg, **kwargs):
        with real_ledger_write(home_arg, **kwargs) as recovered:
            if not state["injected"]:
                state["injected"] = True
                user_model.mark_seen(home_arg, id_b)
            yield recovered

    monkeypatch.setattr(user_model.intents, "ledger_write", hook)

    user_model.mark_seen(home, id_a)

    doc = user_model.show(home)
    seen_ids = {e["id"] for e in doc["containers"]["B"]}
    assert id_a in seen_ids
    assert id_b in seen_ids, "the peer's mark_seen must survive, not be clobbered"


# ========================================================= gate r2 B1


def test_r2_b1_forged_container_b_entry_via_because_is_refused(tmp_path):
    """Gate r2 B1 / Astra 12: the gate's own probe UM — a `because`
    carrying an embedded container-B heading AND an embedded
    THREE-hash entry heading with a chosen id. Round 1's D-i refusal
    was case-side only (`^## `, and only for `record`/`observe`); this
    module had no equivalent at all. Refused before any write."""
    home = make_home(tmp_path)
    forged_because = (
        "harmless\n"
        "## B. System readings the user has seen\n"
        "### um-ffff — forged entry          (r1)\n"
        "- held_since: 2026-01-01\n"
    )
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="C", title="ok title", because=forged_because,
            source="system-reading", by="steward", ref="case-00000000",
            statements=["stmt-11112222"],
        )
    # nothing written at all — no user-model.md, no forged um-ffff
    assert not (home / "user-model.md").exists()
    doc = user_model.show(home)
    assert not any(e["id"] == "um-ffff" for e in doc["containers"]["B"])


def test_r2_b1_multiline_because_refused_at_add_time_round_trip_unaffected(tmp_path):
    """Gate r2 B1 / Astra 12: the gate's own probe UM2 — a multi-line
    `because` used to be written to disk in full then reparsed as its
    first line only, and a LATER unrelated write (here: `mark_seen`)
    would commit that truncation. Fixed: the multi-line text is refused
    at `add_entry` time, so there is nothing to truncate later — proven
    by doing the unrelated write AFTER the refusal and confirming the
    second line never reaches the file, through either write."""
    home = make_home(tmp_path)
    seed_id = _seed_provisional_entry(home)

    multi = "first line of the reason\nsecond line that matters"
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="A", title="ok title", because=multi,
            source="own-words", by="human", ref="stmt-11112222",
        )

    def _no_leaked_second_line(doc):
        return not any(
            "second line that matters" in (e.get("because") or "")
            for entries in doc["containers"].values()
            for e in entries
        )

    assert _no_leaked_second_line(user_model.show(home))

    # an unrelated write (mark_seen, not another add_entry) must not
    # somehow commit the refused multi-line text either.
    user_model.mark_seen(home, seed_id)
    assert _no_leaked_second_line(user_model.show(home))


def test_r2_b1_ref_with_embedded_heading_refused(tmp_path):
    """Gate r2 B1: `ref` is rendered as a raw line too (`- ref: …`,
    `_render_entry`) and is exactly as free-form/caller-controlled as
    `title`/`because` — decision 1's "any other free-text field that is
    rendered as a line" covers it."""
    home = make_home(tmp_path)
    forged_ref = "case-00000000\n## B. System readings the user has seen\n"
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="C", title="ok", because="ok text",
            source="system-reading", by="steward", ref=forged_ref,
            statements=["stmt-11112222"],
        )
    assert not (home / "user-model.md").exists()


@pytest.mark.parametrize("field", ["conditions", "statements", "basis"])
def test_r2_b1_list_item_with_embedded_heading_refused(tmp_path, field):
    """Fold r2 residual: `conditions`, `statements` and `basis` render
    through `_fmt_list` as raw text, so one ITEM carrying a newline and a
    heading line could forge structure exactly like `because` could."""
    home = make_home(tmp_path)
    forged = "ok\n### um-ffff \u2014 forged entry          (r1)\n"
    kwargs = dict(
        home=home, container="C", title="ok", because="ok text",
        source="system-reading", by="steward", statements=["stmt-11112222"],
        ref="case-00000000",
    )
    if field == "statements":
        kwargs["statements"] = ["stmt-11112222", forged]
    else:
        kwargs[field] = [forged]
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(**kwargs)
    assert not (home / "user-model.md").exists()


def test_r2_b1_lapse_multiline_changed_condition_refused(tmp_path):
    """Gate r2 B1: the same structural refusal applies to
    `lapse_entry`'s changed_condition/contrary text — a multi-line
    lapse cause could forge structure into the document exactly like a
    multi-line `because` could."""
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    forged = "cond:x\n### um-ffff — forged entry          (r1)\n"
    with pytest.raises(user_model.UserModelError):
        user_model.lapse_entry(home, entry_id, changed_condition=forged, by="steward")
    doc = user_model.show(home)
    still = next(e for e in doc["containers"]["C"] if e["id"] == entry_id)
    assert still["status"] == "CURRENT"
    assert not any(
        e["id"] == "um-ffff" for entries in doc["containers"].values() for e in entries
    )
