"""E1 (2026-10-10): `replace` -- a new lesson takes over from one or more
named lessons, in one motion, with history (D-AUTHOR §2.2-2.11; build plan
E1 and SP-E).

The user, 2026-10-06 (`DECISIONS-FOLLOWUP-2026-10-06.md` §4): "obviously we
need a clean way to rewrite/edit/update already written lessons in a version
controlled way, as we've already discussed. ... we're going to make the
steward/overseer capable of editing these lessons however they want."

What is pinned here:

* the swap: the old line leaves and the new one comes in one locked step,
  in the same file or across files, on a git host and a plain host;
* a merge (`also`), across buckets too (SP-E (a): the live
  testing-methodology merge spans `skills/testing-methodology` and `user/`),
  with its crash ordering: the new line is placed BEFORE any `also` line is
  retired, so a refused middle step leaves duplicate guidance, never none,
  and a re-run finishes it (idempotence by a state read);
* a pending first lesson, `text_from` (the undo), the hook refusal, the S-76
  placement rule, `new-skill` into an existing self-learn skill only;
* the secret scan's two halves (S-71 kinds `bad-line` / `secret-record`);
* S-81: a steward `replace` that would change a lesson the overseer holds --
  as the line's id or as an `also` id -- is refused with nothing written;
* the always-loaded test reads `replace` lines (D-AUTHOR §2.9);
* the batch grammar, preview, receipt and CLI.

Every scenario runs on pytest sandbox ledgers and hosts (`support.make_env`),
with HOME pointed at the sandbox; ids and texts are synthetic. No model call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import always_loaded, batch, cases, cli, ledger_ops, verbs
from self_learn.compilers import BEGIN_MARKER
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_env
from test_steward import _dump_yaml
from test_steward_refusals import _case
from test_tracked_target_guard import _plain_repo_host

OLD_TRIGGER = "About to report a long agentic loop as converged."
OLD_INSTRUCTION = "Check the yield per round first; a flat yield is a steady state."
NEW_TRIGGER = "About to run another round of the same review."
NEW_INSTRUCTION = "Stop when the yield per round is flat: that is a steady state, not convergence."
MARKETPLACE = {"name": "sandbox-skills", "plugins": []}


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    # A user-scope lesson compiles into ~/.claude/CLAUDE.md: never the real one.
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


# ------------------------------------------------------------------ helpers


def _seed(home: Path, rid: str, *, scope: str = "skill:s", trigger: str = OLD_TRIGGER,
          instruction: str = OLD_INSTRUCTION, project_path: Path | None = None,
          evidence: list[dict] | None = None) -> str:
    record = make_behavior(scope=scope, record_id=rid, trigger=trigger, instruction=instruction)
    for entry in evidence or []:
        record.append_evidence(entry)
    create_record(home, record, project_path=project_path)
    commit_all(home, f"seed {rid}")
    return rid


def _place(home: Path, rid: str, dest: str) -> None:
    verbs.route(home, rid, dest=dest, no_push=True)


def _rec(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _subjects(repo: Path, n: int = 10) -> list[str]:
    return git(repo, "log", f"-{n}", "--format=%s").stdout.splitlines()


def _sheet(tmp_path: Path, items: list[dict], *, case: str | None = None,
           name: str = "sheet") -> batch.Sheet:
    data: dict = {"version": 1, "items": items}
    if case is not None:
        data["case"] = case
    path = tmp_path / f"{name}.yaml"
    _dump_yaml(path, data)
    return batch.load_sheet(path)


def _tree(path: Path) -> dict[str, bytes]:
    """Every file under *path* (no .git), for a nothing-written assertion."""
    return {
        str(p.relative_to(path)): p.read_bytes()
        for p in sorted(path.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(path).parts
    }


class Env:
    """`make_env`'s sandbox: one git host repo that is both the skills root
    (skill `s`) and a registered project, and a ledger home."""

    def __init__(self, tmp_path: Path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_md = sandbox.skill_md
        self.claude_md = self.host / "CLAUDE.md"
        self.tmp = tmp_path


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def agents_may_replace(monkeypatch):
    """E1 fold 1: `batch.REPLACE_REFUSED_ACTORS` refuses `replace` to the
    steward and the overseer until E3b. A test of what an agent's replace
    does once E3b empties the set runs with it empty here."""
    monkeypatch.setattr(batch, "REPLACE_REFUSED_ACTORS", frozenset())


# ---------------------------------------------------- the swap, one file


def test_a_rewrite_in_the_same_file_swaps_the_line_in_one_commit(env):
    """D-AUTHOR §2.5, same file: the old line goes and the new one comes in
    the route's own commit; the old lesson stays, as replaced."""
    old = _seed(env.home, "lrn-e1000001", evidence=[{"session": "s-1", "quote": "flat yield"}])
    _place(env.home, old, "skill-md")
    assert f"*({old})*" in env.skill_md.read_text(encoding="utf-8")  # control
    old_bytes = find_record_path(env.home, old).read_bytes()
    host_head = _head(env.host)

    result = verbs.replace_lesson(
        env.home, old, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
        because="shorter, and the trigger names the moment", no_push=True,
    )

    new = result.new_record_id
    assert new and new != old
    text = env.skill_md.read_text(encoding="utf-8")
    assert f"*({old})*" not in text and f"*({new})*" in text
    assert result.compiled_line is not None and result.compiled_line in text
    # one ledger commit made the swap, under the replace subject
    assert _subjects(env.home, 3)[0] == f"self-learn: replace {old} → {new} (skill-md)"
    assert _head(env.host) != host_head  # git host: one host commit
    made, gone = _rec(env.home, new), _rec(env.home, old)
    assert (made.status, made.source, made.supersedes) == ("routed", "rewrite", old)
    assert (made.routing or {}).get("destination") == "skill-md"
    assert {"session": "s-1", "quote": "flat yield"} in [dict(e) for e in made.evidence]
    assert (gone.status, gone.superseded_by) == ("superseded", new)
    # the old lesson's words stay in the ledger, byte for byte (only its
    # lifecycle fields changed)
    assert OLD_INSTRUCTION.encode() in find_record_path(env.home, old).read_bytes()
    assert old_bytes.split(b"\n---\n", 1)[1] == find_record_path(env.home, old).read_bytes().split(b"\n---\n", 1)[1]
    # `because` rides the replace commit's body (a telemetry flush may ride on top)
    sha = git(env.home, "log", "--format=%H", "--grep", f"^self-learn: replace {old}").stdout.split()[0]
    assert "shorter, and the trigger names the moment" in git(
        env.home, "log", "-1", "--format=%b", sha).stdout


def test_the_grounding_fields_carry_over_and_the_history_does_not(env):
    """D-AUTHOR §2.11: evidence (a union), verified/verified_how,
    incident_cost, generality, env and an open follow-up carry; history,
    notes and the resolution note stay with the old lesson."""
    old = _seed(env.home, "lrn-e1000002")
    path = find_record_path(env.home, old)
    record = Record.from_path(path)
    record.set_verified(True, "strings on 2.1.283 still finds the message")
    record.set_incident_cost("three wasted review rounds")
    record.set_generality("general-practice")
    record.set_env({"claude-code": "2.1.283"})
    record.write(path)
    commit_all(env.home, "ground it")
    verbs.route(env.home, old, dest="skill-md", no_push=True,
                follow_up={"action": "turn it into a hook once warnings exist"})
    verbs.note(env.home, old, append="a maintainer's note", no_push=True)

    new = verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER,
                               instruction=NEW_INSTRUCTION, because="b", no_push=True).new_record_id
    made = _rec(env.home, new)
    assert made.verified is True
    assert made.verified_how == "strings on 2.1.283 still finds the message"
    assert made.incident_cost == "three wasted review rounds"
    assert made.generality == "general-practice"
    assert made.env == {"claude-code": "2.1.283"}
    assert made.follow_up == {"action": "turn it into a hook once warnings exist"}
    assert made.notes == () and made.history == ()
    assert _rec(env.home, old).notes  # control: the note stayed where it was


# --------------------------------------------- the swap, across two files


def test_a_correction_that_moves_takes_the_line_out_of_one_file_into_another(env):
    """D-AUTHOR §2.5, different file: the skill loses its line and the
    project CLAUDE.md gains the new one, in the same motion."""
    old = _seed(env.home, "lrn-e1000003")
    _place(env.home, old, "skill-md")
    new = verbs.replace_lesson(
        env.home, old, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
        to=str(env.host), dest="claude-md", because="it is about this project", no_push=True,
    ).new_record_id
    assert f"*({old})*" not in env.skill_md.read_text(encoding="utf-8")
    assert f"*({new})*" in env.claude_md.read_text(encoding="utf-8")
    assert _rec(env.home, new).scope == "project"


def test_a_plain_host_gets_the_swap_and_no_commit(env, tmp_path):
    """Plain mode: the compile record lives in the ledger; the host gets no
    commit, and the file is one git ignores (S-80)."""
    host = _plain_repo_host(env.home, tmp_path, "plain-one", track_claude_md=False)
    old = _seed(env.home, "lrn-e1000004", scope="project", project_path=host)
    _place(env.home, old, "claude-md")
    host_head = _head(host)
    new = verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER,
                               instruction=NEW_INSTRUCTION, because="b", no_push=True).new_record_id
    text = (host / "CLAUDE.md").read_text(encoding="utf-8")
    assert f"*({old})*" not in text and f"*({new})*" in text
    assert _head(host) == host_head
    assert git(host, "status", "--porcelain").stdout == ""  # ignored, not untracked


# ------------------------------------------------------ a pending lesson


def test_a_pending_first_lesson_gives_a_pending_replacement_in_one_commit(env):
    """D-AUTHOR §2.2 step 4: no destination -- the new lesson is captured to
    pending/ and the old one superseded, in one ledger commit."""
    old = _seed(env.home, "lrn-e1000005")
    head = _head(env.home)
    result = verbs.replace_lesson(env.home, old, fact="The yield per round decides it.",
                                  because="it is a fact, not a rule", no_push=True)
    new = result.new_record_id
    assert find_record_path(env.home, new).parent.name == "pending"
    made = _rec(env.home, new)
    assert (made.status, made.type, made.supersedes, made.source) == (
        "pending", "knowledge", old, "rewrite")
    gone = _rec(env.home, old)
    assert (gone.status, gone.superseded_by) == ("superseded", new)
    assert find_record_path(env.home, old).parent.name == "resolved"
    assert git(env.home, "rev-list", "--count", f"{head}..HEAD").stdout.strip() == "1"
    assert _subjects(env.home, 1)[0] == f"self-learn: replace {old} → {new} (pending)"
    assert result.compiled_line is None


def test_a_pending_replacement_may_not_retire_a_placed_lesson(env):
    """A design call D-AUTHOR leaves open: a pending first lesson with no
    dest would leave a placed `also` lesson's line with no successor loaded.
    Refused by name; nothing written."""
    old = _seed(env.home, "lrn-e1000006")
    placed = _seed(env.home, "lrn-e1000007")
    _place(env.home, placed, "skill-md")
    head = _head(env.home)
    with pytest.raises(verbs.SheetLineError) as exc:
        verbs.replace_lesson(env.home, old, also=[placed], trigger=NEW_TRIGGER,
                             instruction=NEW_INSTRUCTION, because="b", no_push=True)
    assert "would land pending while lrn-e1000007 is placed" in str(exc.value)
    assert _head(env.home) == head
    # with a dest it goes through
    verbs.replace_lesson(env.home, old, also=[placed], trigger=NEW_TRIGGER,
                         instruction=NEW_INSTRUCTION, dest="skill-md", because="b", no_push=True)
    assert _rec(env.home, placed).status == "superseded"


# ------------------------------------------------------------------ merge


def _three(env) -> tuple[str, str, str]:
    a = _seed(env.home, "lrn-e100000a", trigger="About to trust a check that never failed.")
    b = _seed(env.home, "lrn-e100000b", trigger="About to accept a green gate without a control.")
    c = _seed(env.home, "lrn-e100000c", trigger="About to read rc=0 after a pipe.")
    for rid in (a, b, c):
        _place(env.home, rid, "skill-md")
    return a, b, c


def test_a_merge_of_three_with_a_refused_middle_step_then_a_retry(env, tmp_path, monkeypatch):
    """D-AUTHOR §2.3 (M2): the first lesson goes in the route's commit, each
    `also` by `supersede` after it. A refused middle step leaves the merged
    line AND the not-yet-retired old line loaded (never neither), the item
    reports the refusal with its kind, and a re-run of the same sheet
    finishes the merge through the idempotence read."""
    a, b, c = _three(env)
    real = verbs.supersede
    calls: list[str] = []

    def flaky(home, old_id, new_id, **kw):
        calls.append(old_id)
        if old_id == b and calls.count(b) == 1:
            raise verbs.DestinationUnavailable(f"simulated refusal of {b}")
        return real(home, old_id, new_id, **kw)

    monkeypatch.setattr(verbs, "supersede", flaky)
    items = [{"id": a, "verb": "replace", "also": [b, c], "trigger": NEW_TRIGGER,
              "instruction": NEW_INSTRUCTION, "because": "one principle, three lessons"}]
    first = batch.run(env.home, _sheet(tmp_path, items), no_push=True)
    (item,) = first.items
    assert (item.state, item.kind) == ("refused", "destination-unavailable"), item.detail
    new = _rec(env.home, a).superseded_by
    assert isinstance(new, str) and new.startswith("lrn-")
    text = env.skill_md.read_text(encoding="utf-8")
    # the crash ordering: the new line is placed before any `also` is retired
    assert f"*({new})*" in text and f"*({b})*" in text and f"*({c})*" in text
    assert f"*({a})*" not in text
    assert _rec(env.home, b).status == "routed" and _rec(env.home, c).status == "routed"

    second = batch.run(env.home, _sheet(tmp_path, items), no_push=True)
    (item2,) = second.items
    assert item2.state == "applied", item2.detail
    text = env.skill_md.read_text(encoding="utf-8")
    assert f"*({new})*" in text
    assert not any(f"*({rid})*" in text for rid in (a, b, c))
    for rid in (b, c):
        assert (_rec(env.home, rid).status, _rec(env.home, rid).superseded_by) == ("superseded", new)
    # the merge reused the lesson the first run made: one successor only
    assert sorted(p.stem for p in (env.home / "skills" / "s" / "resolved").glob("*.md")
                  if _rec(env.home, p.stem).supersedes == a) == [new]

    third = batch.run(env.home, _sheet(tmp_path, items), no_push=True)
    head = _head(env.home)
    assert [i.state for i in third.items] == ["already-applied"]
    assert batch.classify(env.home, batch.load_sheet(tmp_path / "sheet.yaml")[0]) is True
    assert _head(env.home) == head


def test_the_merge_carries_every_lesson_s_evidence(env):
    a = _seed(env.home, "lrn-e1000011", evidence=[{"session": "s-a", "quote": "qa"}])
    b = _seed(env.home, "lrn-e1000012", evidence=[{"session": "s-b", "quote": "qb"}])
    for rid in (a, b):
        _place(env.home, rid, "skill-md")
    new = verbs.replace_lesson(env.home, a, also=[b], trigger=NEW_TRIGGER,
                               instruction=NEW_INSTRUCTION, because="b", no_push=True).new_record_id
    evidence = [dict(e) for e in _rec(env.home, new).evidence]
    assert {"session": "s-a", "quote": "qa"} in evidence and {"session": "s-b", "quote": "qb"} in evidence
    assert _rec(env.home, new).sightings == 2


def test_two_different_open_follow_ups_refuse_the_merge_by_name(env):
    a, b = _seed(env.home, "lrn-e1000013"), _seed(env.home, "lrn-e1000014")
    verbs.route(env.home, a, dest="skill-md", no_push=True, follow_up={"action": "one plan"})
    verbs.route(env.home, b, dest="skill-md", no_push=True, follow_up={"action": "another plan"})
    head = _head(env.home)
    with pytest.raises(verbs.SheetLineError) as exc:
        verbs.replace_lesson(env.home, a, also=[b], trigger=NEW_TRIGGER,
                             instruction=NEW_INSTRUCTION, because="b", no_push=True)
    assert "different open follow-ups (lrn-e1000013, lrn-e1000014)" in str(exc.value)
    assert _head(env.home) == head


# --------------------------------------------- (a) a merge across buckets


def _testing_methodology(env) -> tuple[str, str, Path]:
    """SP-E (a)'s live shape: a `user/` lesson routed `new-skill:
    testing-methodology` (the skill self-learn scaffolded) and a lesson in
    the skill's own bucket routed `skill-md`, both compiled into the one
    SKILL.md."""
    marketplace = env.host / ".claude-plugin" / "marketplace.json"
    marketplace.parent.mkdir()
    marketplace.write_text(json.dumps(MARKETPLACE) + "\n", encoding="utf-8")
    commit_all(env.host, "marketplace")
    user_lesson = _seed(env.home, "lrn-e1000021", scope="user",
                        trigger="About to call a check that cannot fail a pass.")
    _place(env.home, user_lesson, "new-skill:testing-methodology")
    skill_md = env.host / "plugins" / "testing-methodology" / "skills" / "testing-methodology" / "SKILL.md"
    skill_lesson = _seed(env.home, "lrn-e1000022", scope="skill:testing-methodology",
                         trigger="About to trust a gate with no positive control.")
    _place(env.home, skill_lesson, "skill-md")
    text = skill_md.read_text(encoding="utf-8")
    assert f"*({user_lesson})*" in text and f"*({skill_lesson})*" in text  # control
    return user_lesson, skill_lesson, skill_md


def test_also_works_across_buckets_the_testing_methodology_merge(env, tmp_path):
    """SP-E (a): `replace` of a `skills/testing-methodology` lesson with
    `also:` naming a `user/` lesson routed `new-skill: testing-methodology`
    removes both old lines from that skill's SKILL.md, adds the new one, and
    the user-bucket lesson reads `superseded_by: <new id>`."""
    user_lesson, skill_lesson, skill_md = _testing_methodology(env)
    result = batch.run(env.home, _sheet(tmp_path, [{
        "id": skill_lesson, "verb": "replace", "also": [user_lesson],
        "trigger": "About to trust a check.", "because": "one principle",
        "instruction": "A check that cannot fail proves nothing; add a positive control.",
    }]), no_push=True)
    (item,) = result.items
    assert item.state == "applied", item.detail
    new = _rec(env.home, skill_lesson).superseded_by
    text = skill_md.read_text(encoding="utf-8")
    assert f"*({new})*" in text
    assert f"*({skill_lesson})*" not in text and f"*({user_lesson})*" not in text
    assert _rec(env.home, user_lesson).superseded_by == new
    assert find_record_path(env.home, user_lesson).parts[-3] == "user"
    assert find_record_path(env.home, new).parts[-3:-1] == ("testing-methodology", "resolved")


# ----------------------------------------------------- new-skill admission


def test_a_replace_into_an_existing_self_learn_skill_needs_no_one_motion_opt_in(env):
    """D-AUTHOR §2.2: `replace` runs every gate of the direct route but the
    one-motion gate, and admits `new-skill:<name>` only into a skill
    self-learn made (its managed section). The config opt-in is off."""
    user_lesson, _skill_lesson, skill_md = _testing_methodology(env)
    assert verbs.one_motion_allowed(env.home, "new-skill") is False  # control: gate is on
    new = verbs.replace_lesson(env.home, user_lesson, trigger=NEW_TRIGGER,
                               instruction=NEW_INSTRUCTION, because="b", no_push=True).new_record_id
    assert (_rec(env.home, new).routing or {}).get("new_skill") == "testing-methodology"
    assert f"*({new})*" in skill_md.read_text(encoding="utf-8")


def test_a_replace_into_a_skill_that_does_not_exist_is_refused_by_name(env):
    marketplace = env.host / ".claude-plugin" / "marketplace.json"
    marketplace.parent.mkdir()
    marketplace.write_text(json.dumps(MARKETPLACE) + "\n", encoding="utf-8")
    commit_all(env.host, "marketplace")
    old = _seed(env.home, "lrn-e1000023")
    _place(env.home, old, "skill-md")
    host_tree, head = _tree(env.host), _head(env.home)
    with pytest.raises(verbs.DestinationUnavailable) as exc:
        verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
                             dest="new-skill:brand-new", because="b", no_push=True)
    assert "new-skill:brand-new does not exist" in str(exc.value)
    assert "never scaffolds" in str(exc.value)
    assert _tree(env.host) == host_tree and _head(env.home) == head
    assert not (env.host / "plugins" / "brand-new").exists()


# ------------------------------------------------------ refused by name


def _hook_routed(env, rid: str) -> str:
    _seed(env.home, rid)
    path = find_record_path(env.home, rid)
    record = Record.from_path(path)
    record.set_routing({"routed_at": "2026-10-01T00:00:00Z", "destination": "hook", "by": "human"})
    record.set_status("routed")
    resolved = path.parent.parent / "resolved" / path.name
    resolved.parent.mkdir(exist_ok=True)
    record.write(resolved)
    path.unlink()
    commit_all(env.home, f"hook-routed {rid}")
    return rid


def test_a_hook_lesson_is_refused(env):
    hooked = _hook_routed(env, "lrn-e1000031")
    old = _seed(env.home, "lrn-e1000032")
    head = _head(env.home)
    with pytest.raises(verbs.SheetLineError) as exc:
        verbs.replace_lesson(env.home, hooked, trigger=NEW_TRIGGER,
                             instruction=NEW_INSTRUCTION, dest="skill-md", because="b", no_push=True)
    assert "corrected through its hook route, not its text" in str(exc.value)
    # as an `also` lesson too
    with pytest.raises(verbs.SheetLineError):
        verbs.replace_lesson(env.home, old, also=[hooked], trigger=NEW_TRIGGER,
                             instruction=NEW_INSTRUCTION, dest="skill-md", because="b", no_push=True)
    assert _head(env.home) == head
    assert _rec(env.home, old).status == "pending"
    with pytest.raises(verbs.SheetLineError) as exc:
        verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
                             dest="hook", because="b", no_push=True)
    assert "never from lesson text" in str(exc.value)


@pytest.mark.parametrize(
    "kwargs,needle",
    [
        ({}, "needs the new text"),
        ({"trigger": NEW_TRIGGER}, "needs both trigger and instruction"),
        ({"trigger": NEW_TRIGGER, "instruction": "x", "fact": "y"}, "never both"),
        ({"fact": "y", "text_from": "lrn-e1000041"}, "cannot be mixed"),
        ({"fact": "y", "type": "behavior"}, "not behavior"),
    ],
)
def test_the_text_keys_are_checked_before_anything(env, kwargs, needle):
    old = _seed(env.home, "lrn-e1000041")
    head = _head(env.home)
    with pytest.raises(verbs.VerbError) as exc:
        verbs.replace_lesson(env.home, old, because="b", no_push=True, **kwargs)
    assert needle in str(exc.value)
    assert _head(env.home) == head


def test_a_multi_line_loaded_section_is_refused_and_context_takes_the_rest(env):
    """S-79 / D-AUTHOR §2.12: a loaded section is one line; the rest goes to
    `## Context`, which is kept and never loaded."""
    old = _seed(env.home, "lrn-e1000042")
    _place(env.home, old, "skill-md")
    with pytest.raises(verbs.SheetLineError):
        verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER,
                             instruction=NEW_INSTRUCTION + "\nand a second line", because="b",
                             no_push=True)
    new = verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
                               context="and a second line\nand a third", because="b",
                               no_push=True).new_record_id
    assert "and a third" in _rec(env.home, new).body  # the record keeps it
    text = env.skill_md.read_text(encoding="utf-8")
    assert f"*({new})*" in text and "and a second line" not in text  # never loaded


def test_a_lesson_already_replaced_by_another_text_is_refused(env):
    old = _seed(env.home, "lrn-e1000043")
    _place(env.home, old, "skill-md")
    first = verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER,
                                 instruction=NEW_INSTRUCTION, because="b", no_push=True)
    with pytest.raises(verbs.VerbError) as exc:
        verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER,
                             instruction="A different instruction.", because="b", no_push=True)
    assert f"already superseded by {first.new_record_id}" in str(exc.value)
    assert batch.refusal_kind(exc.value, rc=1, state="refused") == "status"
    # the same text again: nothing left to do, refused cleanly
    with pytest.raises(verbs.VerbError) as exc:
        verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER,
                             instruction=NEW_INSTRUCTION, because="b", no_push=True)
    assert "nothing to do" in str(exc.value)


# ---------------------------------------------------------- undo: text_from


def test_text_from_restores_the_original_text_byte_for_byte(env):
    """D-AUTHOR §2.7: the undo of a bad rewrite is a further `replace` that
    copies the original's sections exactly from `resolved/`. The Context
    here starts with a blank line and an indent, bytes a re-render from the
    stripped sections would not keep, so only a byte copy passes."""
    original = _seed(env.home, "lrn-e1000051")
    path = find_record_path(env.home, original)
    record = Record.from_path(path)
    record.set_body(record.body + "\n## Context\n\n   why the long form mattered\n   with odd  spacing\n")
    record.write(path)
    commit_all(env.home, "context")
    _place(env.home, original, "skill-md")
    bad = verbs.replace_lesson(env.home, original, trigger=NEW_TRIGGER,
                               instruction=NEW_INSTRUCTION, because="shorten", no_push=True).new_record_id
    undo = verbs.replace_lesson(env.home, bad, text_from=original,
                                because="the rewrite lost the why", no_push=True).new_record_id
    restored, orig = _rec(env.home, undo), _rec(env.home, original)
    assert restored.body == orig.body
    assert (restored.supersedes, _rec(env.home, bad).superseded_by) == (bad, undo)
    assert f"*({undo})*" in env.skill_md.read_text(encoding="utf-8")


# --------------------------------------------------- S-76: a person's case


def _human_case(home: Path, tmp_path: Path, rid: str) -> str:
    stage = tmp_path / f"human-{rid}.yaml"
    case = _case([rid], "route", "route")
    case["trigger"] = "human"
    _dump_yaml(stage, case)
    return cases.record(home, stage, actor="human")


@pytest.mark.usefixtures("agents_may_replace")
def test_a_lesson_a_person_s_case_covers_keeps_its_placement(env, tmp_path):
    """D-AUTHOR §2.10 (S-76): when an open case a person recorded covers the
    first lesson, an agent's replacement keeps that lesson's placement
    (words only); moving it is asked of the user. The rule binds the
    runner's actor, never a line's own `by`. A person may move their own."""
    old = _seed(env.home, "lrn-e1000061")
    _place(env.home, old, "skill-md")
    case_id = _human_case(env.home, tmp_path, old)
    moving = {"id": old, "verb": "replace", "trigger": NEW_TRIGGER, "by": "human",
              "instruction": NEW_INSTRUCTION, "to": str(env.host), "dest": "claude-md",
              "because": "it is about this project"}
    head = _head(env.home)
    preview = batch.dry_run(env.home, _sheet(tmp_path, [moving], name="move"), actor="overseer")
    assert (preview.items[0].state, preview.items[0].kind) == ("would-refuse", "needs-person")
    result = batch.run(env.home, _sheet(tmp_path, [moving], name="move"), no_push=True,
                       actor="overseer")
    (item,) = result.items
    assert (item.state, item.kind) == ("refused", "needs-person"), item.detail
    assert case_id in (item.detail or "") and "keeps its placement" in (item.detail or "")
    assert not any(s.startswith("self-learn: replace") for s in _subjects(env.home, 5))
    assert git(env.home, "rev-list", "--count", f"{head}..HEAD", "--", "skills").stdout.strip() == "0"

    words_only = {key: value for key, value in moving.items() if key not in ("to", "dest")}
    applied = batch.run(env.home, _sheet(tmp_path, [words_only], name="words"), no_push=True,
                        actor="overseer")
    assert applied.items[0].state == "applied", applied.items[0].detail
    new = _rec(env.home, old).superseded_by
    assert (_rec(env.home, new).routing or {}).get("destination") == "skill-md"


def test_a_person_may_move_a_lesson_their_own_case_covers(env, tmp_path):
    old = _seed(env.home, "lrn-e1000062")
    _place(env.home, old, "skill-md")
    _human_case(env.home, tmp_path, old)
    new = verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
                               to=str(env.host), dest="claude-md", because="b",
                               no_push=True).new_record_id
    assert f"*({new})*" in env.claude_md.read_text(encoding="utf-8")


# ------------------------------------------------------------- secret scan


def _token() -> str:
    return "ghp_" + "Zx9" * 12


@pytest.mark.usefixtures("agents_may_replace")
def test_a_secret_in_the_line_is_the_line_s_and_in_the_record_is_refused(env, tmp_path):
    """D-AUTHOR §2.6 / S-71: the line's own text is scanned first -- a hit is
    `bad-line` (the steward's repair turn); a hit in a record the call
    rewrites is `secret-record` (refused, never parked)."""
    old = _seed(env.home, "lrn-e1000071")
    _place(env.home, old, "skill-md")
    line = batch.run(env.home, _sheet(tmp_path, [{
        "id": old, "verb": "replace", "trigger": NEW_TRIGGER, "because": "b",
        "instruction": f"Use the token {_token()} for the push.",
    }], name="line"), no_push=True, actor="steward")
    assert (line.items[0].state, line.items[0].kind) == ("refused", "bad-line")
    assert _token() not in (line.items[0].detail or "")

    assert _rec(env.home, old).status == "routed"
    assert not any(s.startswith("self-learn: replace") for s in _subjects(env.home, 5))

    # a secret already in a record the call would rewrite (here, carried
    # evidence a hand edit put there): the record's, refused outright
    dirty = _seed(env.home, "lrn-e1000072", evidence=[{"session": "s", "quote": f"tok {_token()}"}])
    record = batch.run(env.home, _sheet(tmp_path, [{
        "id": dirty, "verb": "replace", "trigger": NEW_TRIGGER,
        "instruction": NEW_INSTRUCTION, "because": "b",
    }], name="record"), no_push=True, actor="steward")
    assert (record.items[0].state, record.items[0].kind) == ("refused", "secret-record")
    assert _rec(env.home, dirty).status == "pending"
    assert not any(s.startswith("self-learn: replace") for s in _subjects(env.home, 5))


# ------------------------------------------------------ S-81: the hold


def _hold(home: Path, tmp_path: Path, rid: str) -> str:
    """An open parked case for the overseer names *rid*: the overseer holds
    it (S-81 (1)), whoever parked it."""
    stage = tmp_path / f"parked-{rid}.yaml"
    case = _case([rid], "parked", "defer")
    case.update(kind="parked", parked_for="overseer", parked_reason="authority-unclear")
    case["decision"]["confidence"] = "provisional"
    _dump_yaml(stage, case)
    return cases.record(home, stage, actor="steward")


@pytest.mark.usefixtures("agents_may_replace")
@pytest.mark.parametrize("held_as", ["main", "also"])
def test_a_steward_replace_touching_a_held_lesson_is_refused_with_nothing_written(
    env, tmp_path, held_as
):
    """Brief (c), S-81 (2): every record `replace` changes passes the two
    gates before anything is written, so a steward line whose main id OR
    whose `also` id the overseer holds is refused, `bad-line`, with the
    ledger HEAD and every host file unchanged. The same line by a person or
    the overseer applies (the control)."""
    a = _seed(env.home, "lrn-e1000081")
    b = _seed(env.home, "lrn-e1000082")
    for rid in (a, b):
        _place(env.home, rid, "skill-md")
    _hold(env.home, tmp_path, a if held_as == "main" else b)
    items = [{"id": a, "verb": "replace", "also": [b], "trigger": NEW_TRIGGER,
              "instruction": NEW_INSTRUCTION, "because": "merge"}]
    sheet = _sheet(tmp_path, items)
    head, host_tree, host_head = _head(env.home), _tree(env.host), _head(env.host)

    preview = batch.dry_run(env.home, sheet, actor="steward")
    assert (preview.items[0].state, preview.items[0].kind) == ("would-refuse", "bad-line")
    result = batch.run(env.home, sheet, no_push=True, actor="steward")
    (item,) = result.items
    assert (item.state, item.kind) == ("refused", "bad-line"), item.detail
    held = a if held_as == "main" else b
    assert f"the overseer holds {held}" in (item.detail or "")
    # nothing written: no replace commit (a telemetry flush may ride on top)
    assert not any(s.startswith("self-learn: replace") for s in _subjects(env.home, 5))
    assert git(env.home, "rev-list", "--count", f"{head}..HEAD", "--", "skills").stdout.strip() == "0"
    assert _tree(env.host) == host_tree and _head(env.host) == host_head
    assert (_rec(env.home, a).status, _rec(env.home, b).status) == ("routed", "routed")

    # the verb itself, under the steward's scope, refuses the same way
    with ledger_ops.acting_as("steward", env.home):
        with pytest.raises(verbs.VerbError):
            verbs.replace_lesson(env.home, a, also=[b], trigger=NEW_TRIGGER,
                                 instruction=NEW_INSTRUCTION, because="m", no_push=True)
    assert _tree(env.host) == host_tree

    # control: the overseer (and a person) are never refused by the hold
    applied = batch.run(env.home, sheet, no_push=True, actor="overseer")
    assert applied.items[0].state == "applied", applied.items[0].detail
    assert _rec(env.home, b).superseded_by == _rec(env.home, a).superseded_by


def test_a_person_s_replace_of_a_held_lesson_applies(env, tmp_path):
    a = _seed(env.home, "lrn-e1000083")
    _place(env.home, a, "skill-md")
    _hold(env.home, tmp_path, a)
    new = verbs.replace_lesson(env.home, a, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
                               because="b", no_push=True).new_record_id
    assert _rec(env.home, a).superseded_by == new


# ------------------------------------------------------ the batch grammar


def test_the_sheet_grammar_admits_replace_and_checks_its_shape(tmp_path):
    assert "replace" in batch.PERMITTED_VERBS
    assert batch.REQUIRED_KEYS["replace"] == frozenset({"because"})
    with pytest.raises(batch.BatchError) as exc:
        _sheet(tmp_path, [{"id": "lrn-e1000091", "verb": "replace", "fact": "x"}])
    assert "missing required key(s): ['because']" in str(exc.value)
    with pytest.raises(batch.BatchError) as exc:
        _sheet(tmp_path, [{"id": "lrn-e1000091", "verb": "replace", "fact": "x",
                           "because": "b", "also": "lrn-e1000092"}])
    assert "`also` must be a list" in str(exc.value)
    with pytest.raises(batch.BatchError):
        _sheet(tmp_path, [{"id": "lrn-e1000091", "verb": "replace", "fact": "x",
                           "because": "b", "covered_by": "claude-md:user"}])


@pytest.mark.usefixtures("agents_may_replace")
def test_the_preview_names_what_the_run_would_do_and_writes_nothing(env, tmp_path):
    old = _seed(env.home, "lrn-e1000093")
    _place(env.home, old, "skill-md")
    sheet = _sheet(tmp_path, [{"id": old, "verb": "replace", "trigger": NEW_TRIGGER,
                               "instruction": NEW_INSTRUCTION, "because": "b"}])
    ledger, host = _tree(env.home), _tree(env.host)
    preview = batch.dry_run(env.home, sheet, actor="steward")
    assert preview.items[0].state == "would-apply", preview.items[0].detail
    assert _tree(env.home) == ledger and _tree(env.host) == host
    refused = batch.dry_run(env.home, _sheet(tmp_path, [{
        "id": old, "verb": "replace", "trigger": NEW_TRIGGER, "because": "b",
        "instruction": NEW_INSTRUCTION, "dest": "new-skill:nope"}], name="nope"), actor="steward")
    assert (refused.items[0].state, refused.items[0].kind) == (
        "would-refuse", "destination-unavailable")


@pytest.mark.usefixtures("agents_may_replace")
def test_an_agent_replace_onto_a_reference_shelf_is_refused(env, tmp_path):
    """S-77: no agent puts a lesson on a shelf -- not by `replace` either."""
    old = _seed(env.home, "lrn-e1000094")
    _place(env.home, old, "skill-md")
    items = [{"id": old, "verb": "replace", "trigger": NEW_TRIGGER, "because": "b",
              "instruction": NEW_INSTRUCTION, "dest": "reference"}]
    result = batch.run(env.home, _sheet(tmp_path, items), no_push=True, actor="steward")
    assert (result.items[0].state, result.items[0].kind) == ("refused", "bad-line")
    assert "reference shelf is refused for the steward" in (result.items[0].detail or "")
    assert _rec(env.home, old).status == "routed"


def test_the_receipt_names_the_lesson_made_and_its_compiled_line(env, tmp_path):
    """D-AUTHOR §2.4: the batch receipt carries the minted id and the line
    as the compiler rendered it, so the case shows before (evidence) and
    after (receipt) without a model retyping either -- and a re-run of the
    same sheet keeps naming it."""
    old = _seed(env.home, "lrn-e1000095")
    _place(env.home, old, "skill-md")
    stage = tmp_path / "case.yaml"
    case = _case([old], "replaced", "replace")
    case["decision"]["rewrite"] = {"ideas": [{"idea": "flat yield", "now": "loaded"}]}
    _dump_yaml(stage, case)
    case_id = cases.record(env.home, stage, actor="human")
    sheet = _sheet(tmp_path, [{"id": old, "verb": "replace", "trigger": NEW_TRIGGER,
                               "instruction": NEW_INSTRUCTION, "because": "b"}], case=case_id)
    result = batch.run(env.home, sheet, no_push=True)
    batch.write_receipt(env.home, result, "sheet.yaml", no_push=True)
    new = _rec(env.home, old).superseded_by
    line = next(ln for ln in env.skill_md.read_text(encoding="utf-8").splitlines() if f"({new})" in ln)
    application = cases.show(env.home, case_id, evidence_only=False).sections["Application"]
    assert f"made {new}; line: {line}" in application

    again = batch.run(env.home, _sheet(tmp_path, [{"id": old, "verb": "replace",
                                                    "trigger": NEW_TRIGGER,
                                                    "instruction": NEW_INSTRUCTION,
                                                    "because": "b"}], case=case_id), no_push=True)
    assert again.items[0].state == "already-applied"
    batch.write_receipt(env.home, again, "sheet.yaml", no_push=True)
    application = cases.show(env.home, case_id, evidence_only=False).sections["Application"]
    assert f"already-applied (exit 0); made {new}; line: {line}" in application


# ------------------------------------------------- the always-loaded test


def test_the_always_loaded_test_reads_replace_lines(env, tmp_path):
    """D-AUTHOR §2.9: a `replace` into an always-loaded line meets S-72's
    combined test, with an explicit dest and with an inherited one; a
    skill-md placement does not (control)."""
    project = _seed(env.home, "lrn-e10000a1", scope="project", project_path=env.host)
    _place(env.home, project, "claude-md")
    skill = _seed(env.home, "lrn-e10000a2")
    _place(env.home, skill, "skill-md")
    case = _case([project], "replaced", "replace")
    placement = always_loaded.placement_resolver(env.home)
    explicit = [{"id": skill, "verb": "replace", "dest": "claude-md", "because": "b"}]
    inherited = [{"id": project, "verb": "replace", "because": "b"}]
    stays = [{"id": skill, "verb": "replace", "because": "b"}]
    assert "always-loaded line" in (always_loaded.route_problem(case, explicit, placement=placement) or "")
    assert "always-loaded line" in (always_loaded.route_problem(case, inherited, placement=placement) or "")
    assert always_loaded.route_problem(case, stays, placement=placement) is None
    assert placement(project) == ("claude-md", None) and placement(skill) == ("skill-md", None)
    # a caller that cannot see the placement does not pass the line
    assert always_loaded.route_problem(case, stays) is not None
    ref = case["evidence"][0]["ref"]
    case["decision"]["always_loaded"] = {
        key: {"because": "every session", "refs": [ref]} for key in always_loaded.TEST_KEYS
    }
    assert always_loaded.route_problem(case, inherited, placement=placement) is None


# ------------------------------------------------- revise may add Context


def test_revise_may_add_a_context_section_a_lesson_does_not_have(env):
    """D-AUTHOR §2.12 / S-79's deferred gap: `revise` can add `## Context`
    (never loaded), so a multi-line section has somewhere to go."""
    rid = _seed(env.home, "lrn-e10000b1")
    assert "## Context" not in _rec(env.home, rid).body  # control
    verbs.revise(env.home, rid, section="Context", text="the long story", because="b", no_push=True)
    body = _rec(env.home, rid).body
    assert body.rstrip().endswith("## Context\nthe long story")
    assert OLD_INSTRUCTION in body
    with pytest.raises(verbs.SheetLineError):  # any other missing section still refuses
        verbs.revise(env.home, rid, section="Rationale", text="x", because="b", no_push=True)


# ----------------------------------------------------------------- the CLI


def test_the_cli_verb(env, monkeypatch, capsys):
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
    old = _seed(env.home, "lrn-e10000c1")
    _place(env.home, old, "skill-md")
    code = cli.main(["replace", old, "--trigger", NEW_TRIGGER, "--instruction",
                     NEW_INSTRUCTION, "--because", "shorter", "--no-push", "--json"])
    assert code == 0, capsys.readouterr().err
    envelope = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    new = envelope["new_record_id"]
    assert envelope["action"] == "replace" and envelope["record_id"] == old
    assert f"({new})" in envelope["compiled_line"]
    assert _rec(env.home, old).superseded_by == new
    assert BEGIN_MARKER in env.skill_md.read_text(encoding="utf-8")
    code = cli.main(["replace", old, "--trigger", NEW_TRIGGER, "--because", "x", "--no-push"])
    assert code == 64
    assert "needs both trigger and instruction" in capsys.readouterr().err


def test_the_ledger_metrics_read_a_replace_commit_as_a_resolution(env):
    """`report._resolution_dates` reads resolution commits by subject; the
    replace subject is one (E1)."""
    from self_learn import report

    old = _seed(env.home, "lrn-e10000d1")
    _place(env.home, old, "skill-md")
    new = verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
                               because="b", no_push=True).new_record_id
    dates = report._resolution_dates(env.home)
    assert old in dates  # control: its route commit already counted
    assert new in dates
    # Fold item 5, N5: and it is the REPLACE commit that resolves both --
    # a route subject also names both ids, so the dates alone cannot tell.
    subject = _subjects(env.home, 1)[0]
    assert subject == f"self-learn: replace {old} → {new} (skill-md)"
    assert report._RESOLUTION_SUBJECT_RE.match(subject)


# =========================================================== E1 fold 1
#
# 2026-10-11, the blind gate's D1/R1-R4/N1/N3/N5. Until E3b writes the
# agents' instructions for `replace`, `batch` refuses it to the steward and
# the overseer by name and their contracts do not show it
# (`batch.REPLACE_REFUSED_ACTORS`). The recovery readers and the post-run
# recompile already know it, so E3b only empties that set; those tests run
# with it empty (`agents_may_replace`).


def _merge_sheet(tmp_path: Path, a: str, b: str, *, name: str = "merge") -> batch.Sheet:
    return _sheet(tmp_path, [{"id": a, "verb": "replace", "also": [b], "trigger": NEW_TRIGGER,
                              "instruction": NEW_INSTRUCTION, "because": "merge"}],
                  case="case-0000beef", name=name)


@pytest.mark.parametrize("actor", ["steward", "overseer"])
def test_an_agent_replace_is_refused_by_name_until_e3b_with_nothing_written(
    env, tmp_path, actor
):
    """Fold item 1 (gate R1): the line is refused by name, `bad-line`, in
    the preview and the run alike, before the verb reads anything; the
    ledger and the host are untouched. The same sheet run by a person
    applies (the control)."""
    a, b = _seed(env.home, "lrn-e1f00001"), _seed(env.home, "lrn-e1f00002")
    for rid in (a, b):
        _place(env.home, rid, "skill-md")
    sheet = _merge_sheet(tmp_path, a, b)
    head, host_tree = _head(env.home), _tree(env.host)

    (pitem,) = batch.dry_run(env.home, sheet, actor=actor).items
    assert (pitem.state, pitem.kind) == ("would-refuse", "bad-line"), pitem.detail
    (item,) = batch.run(env.home, sheet, no_push=True, actor=actor).items
    assert (item.state, item.kind) == ("refused", "bad-line"), item.detail
    for detail in (pitem.detail, item.detail):
        assert f"`replace` is refused for the {actor}" in (detail or "")
        assert "not built yet (E3b)" in (detail or "")
    assert not any(s.startswith("self-learn: replace") for s in _subjects(env.home, 5))
    assert git(env.home, "rev-list", "--count", f"{head}..HEAD", "--", "skills").stdout.strip() == "0"
    assert _tree(env.host) == host_tree
    assert (_rec(env.home, a).status, _rec(env.home, b).status) == ("routed", "routed")

    (applied,) = batch.run(env.home, sheet, no_push=True, actor="human").items
    assert applied.state == "applied", applied.detail
    assert _rec(env.home, b).status == "superseded"


def test_the_agents_contracts_do_not_offer_replace_until_e3b(monkeypatch):
    """Fold item 1: the steward's sheet-verb list and the overseer's
    closed sets leave `replace` out while the batch refuses it to them, and
    list it again the moment E3b empties the set (the control)."""
    from self_learn import steward_prompt
    from self_learn.overseer import formats

    def offered() -> tuple[bool, bool, bool, bool]:
        lines = steward_prompt._sheet_verb_lines()
        closed = formats.closed_sets()["sheet"]["verbs"]
        return (
            any(line.split()[0] == "replace" for line in lines),
            "replace" in closed,
            any(line.split()[0] == "revise" for line in lines),
            "revise" in closed,
        )

    assert offered() == (False, False, True, True)  # revise: the positive control
    assert "replace" in batch.PERMITTED_KEYS  # a person's sheet keeps it
    monkeypatch.setattr(batch, "REPLACE_REFUSED_ACTORS", frozenset())
    assert offered() == (True, True, True, True)


def _half_applied_merge(env, monkeypatch, a: str, b: str):
    """The steward's line `replace a also: [b]`: the primary commit lands
    (with the execution trailers), then the `also` supersede is refused --
    the shape that halts a host-outcome verb after its ledger commit."""
    from self_learn import execution_evidence, gitops

    for rid in (a, b):
        _place(env.home, rid, "skill-md")
    start = gitops.head_sha(env.home)
    real = verbs.supersede

    def refused(*_a, **_k):
        raise verbs.DestinationUnavailable("simulated refusal of the also leg")

    monkeypatch.setattr(verbs, "supersede", refused)
    ref = execution_evidence.ExecutionRef(
        run_id="run-fold1", case_id="case-0000beef", sheet_sha="0123abcd",
        sheet_digest="0" * 64, item=1, record_id=a, verb="replace", actor="steward",
    )
    with pytest.raises(verbs.DestinationUnavailable):
        verbs.replace_lesson(env.home, a, also=[b], trigger=NEW_TRIGGER,
                             instruction=NEW_INSTRUCTION, because="merge", no_push=True,
                             execution=ref, actor="steward")
    monkeypatch.setattr(verbs, "supersede", real)
    assert _rec(env.home, a).status == "superseded"  # control: the primary landed
    assert _rec(env.home, b).status == "routed"
    return start


@pytest.mark.usefixtures("agents_may_replace")
def test_the_steward_retry_finishes_a_half_applied_merge(env, tmp_path, monkeypatch):
    """Fold item 2 (gate D1, probe P8): the recovery reader proves the
    primary commit, but the line is established only when the state read
    `batch.classify` makes says applied. Half-applied, it is NOT recovered,
    so the retry re-dispatches it and the verb finishes the merge: B is
    superseded by the new lesson and its line leaves SKILL.md. Once
    finished, the same reader recovers it as applied (the control)."""
    from self_learn import execution_evidence, steward

    a, b = _seed(env.home, "lrn-e1f00011"), _seed(env.home, "lrn-e1f00012")
    start = _half_applied_merge(env, monkeypatch, a, b)
    sheet = _merge_sheet(tmp_path, a, b)
    monkeypatch.setattr(steward, "_committed_receipts", lambda *a_, **k: {})
    monkeypatch.setattr(execution_evidence, "validate_manifest_ref", lambda *a_, **k: None)
    manifest = {"run_id": "run-fold1", "start_head": start}
    recipe = {"sheet_sha": "0123abcd", "sheet_digest": "0" * 64}
    assert batch.classify(env.home, sheet[0]) is False

    assert steward._recovered_items(env.home, manifest, "case-0000beef", recipe, sheet) == {}

    (item,) = batch.run(env.home, sheet, no_push=True, actor="steward").items
    assert item.state == "applied", item.detail
    new = _rec(env.home, a).superseded_by
    assert batch.classify(env.home, sheet[0]) is True
    assert (_rec(env.home, b).status, _rec(env.home, b).superseded_by) == ("superseded", new)
    text = env.skill_md.read_text(encoding="utf-8")
    assert f"*({b})*" not in text and f"*({new})*" in text

    done = steward._recovered_items(env.home, manifest, "case-0000beef", recipe, sheet)
    assert (done[1].state, done[1].rc) == ("applied", 0), done[1].detail


@pytest.mark.usefixtures("agents_may_replace")
def test_the_overseer_resume_of_a_half_applied_merge_re_dispatches_it(env, tmp_path, monkeypatch):
    """Fold item 2 (gate D1): before, `_candidate_establishes` had no
    `replace` branch and every resume raised `OverseerError`, walking the
    attempt cap to a question. Now a half-applied merge is left out of the
    completed items (re-dispatched, as the steward's is), and a finished one
    is recovered as applied."""
    from self_learn.overseer import run as orun

    a, b = _seed(env.home, "lrn-e1f00021"), _seed(env.home, "lrn-e1f00022")
    start = _half_applied_merge(env, monkeypatch, a, b)
    sheet_text = (f"version: 1\ncase: case-0000beef\nitems:\n  - id: {a}\n    verb: replace\n"
                  f"    also: [{b}]\n    trigger: \"{NEW_TRIGGER}\"\n"
                  f"    instruction: \"{NEW_INSTRUCTION}\"\n    because: merge\n")
    recipe = {"sheet_sha": "0123abcd", "sheet_digest": "0" * 64, "sheet": sheet_text,
              "items": [{"n": 1, "id": a, "verb": "replace"}]}
    proof = git(env.home, "log", "-1", "--format=%H", f"--grep=^self-learn: replace {a}").stdout.strip()
    assert proof  # control: the proof commit exists
    monkeypatch.setattr(orun, "_manifest_introduction", lambda *a_, **k: start)
    from self_learn import execution_evidence
    monkeypatch.setattr(execution_evidence, "find_mutation_commit", lambda *a_, **k: proof)

    assert orun._mutation_proven_completed(
        env.home, {"run_id": "run-fold1"}, "case-0000beef", recipe, {}) == {}

    path = tmp_path / "resume.yaml"
    path.write_text(sheet_text, encoding="utf-8")
    (item,) = batch.run(env.home, batch.load_sheet(path), no_push=True, actor="overseer").items
    assert item.state == "applied", item.detail
    out = orun._mutation_proven_completed(
        env.home, {"run_id": "run-fold1"}, "case-0000beef", recipe, {})
    assert (out[1].state, out[1].rc) == ("applied", 0)


def test_the_post_run_recompile_writes_a_replace_whose_host_write_failed(env, monkeypatch):
    """Fold item 2: a replace whose ledger commit landed and whose host
    write failed is recompiled by the runners' post-run pass -- keyed to the
    NEW lesson (the item's own id is the retired one) and to the target the
    old line sat in, so a moved line both arrives and leaves."""
    from self_learn import batch as batch_mod

    old = _seed(env.home, "lrn-e1f00031")
    _place(env.home, old, "skill-md")
    assert f"*({old})*" in env.skill_md.read_text(encoding="utf-8")  # control

    def boom(*_a, **_k):
        raise RuntimeError("simulated host-phase failure")

    monkeypatch.setattr(verbs, "_host_phase", boom)
    with pytest.raises(RuntimeError):
        verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
                             to=str(env.host), dest="claude-md", because="moves", no_push=True)
    monkeypatch.undo()
    new = _rec(env.home, old).superseded_by
    assert new and f"*({old})*" in env.skill_md.read_text(encoding="utf-8")  # the host write failed
    assert f"*({new})*" not in env.claude_md.read_text(encoding="utf-8")

    owed = [batch_mod.ItemResult(n=1, id=old, verb="replace", rc=1, state="unresolved-host")]
    ids = verbs.host_result_ids(owed, env.home)
    assert ids[:2] == [new, old]
    verbs.post_run_recompile(env.home, ids, verbs.host_result_origins(env.home, owed))
    assert f"*({new})*" in env.claude_md.read_text(encoding="utf-8")
    assert f"*({old})*" not in env.skill_md.read_text(encoding="utf-8")


@pytest.mark.usefixtures("agents_may_replace")
def test_an_agent_replace_may_not_retire_an_also_lesson_a_person_s_case_covers(env, tmp_path):
    """Fold item 3 (gate R2, probe P5): S-76 binds every lesson the replace
    moves, not only the first. B is placed in CLAUDE.md under an open case a
    person recorded; an agent merging B into A (in SKILL.md) is refused as
    needs-person, before anything is written. A person's own merge applies."""
    a = _seed(env.home, "lrn-e1f00041")
    _place(env.home, a, "skill-md")
    b = _seed(env.home, "lrn-e1f00042", scope="project", project_path=env.host)
    _place(env.home, b, "claude-md")
    case_id = _human_case(env.home, tmp_path, b)
    sheet = _merge_sheet(tmp_path, a, b)
    head, host_tree = _head(env.home), _tree(env.host)

    (pitem,) = batch.dry_run(env.home, sheet, actor="overseer").items
    assert (pitem.state, pitem.kind) == ("would-refuse", "needs-person"), pitem.detail
    (item,) = batch.run(env.home, sheet, no_push=True, actor="overseer").items
    assert (item.state, item.kind) == ("refused", "needs-person"), item.detail
    assert f"{b} is covered by {case_id}" in (item.detail or "")
    assert git(env.home, "rev-list", "--count", f"{head}..HEAD", "--", "skills", "projects").stdout.strip() == "0"
    assert _tree(env.host) == host_tree
    assert _rec(env.home, b).status == "routed"

    (applied,) = batch.run(env.home, sheet, no_push=True, actor="human").items
    assert applied.state == "applied", applied.detail
    assert f"*({b})*" not in env.claude_md.read_text(encoding="utf-8")


def test_the_preview_refuses_a_replace_whose_old_line_sits_on_a_tracked_plain_shelf(tmp_path):
    """Fold item 4 (gate R3): the first lesson's retirement pre-flight runs
    in the preview with the composed record, unrouted, as `after_route` (no
    simulated routed copy, no second `_DRY_RUN_EXEMPT` entry). Moving a
    lesson off a shelf its plain host keeps in git would rewrite that
    tracked shelf: refused, needs-person, in the preview and the run alike,
    by that pre-flight alone (the new line's own target, the host's
    untracked CLAUDE.md, is fine); nothing changes. (A same-shelf rewrite
    there is refused earlier, by the new line's own target check.)"""
    from support import make_env as _make_env
    from test_tracked_target_guard import _lesson

    home = _make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path, track_claude_md=False)
    rid = _lesson(home, host, "lrn-e1f00051")
    verbs.route(home, rid, dest="reference", no_push=True)
    git(host, "add", "-f", "--", "references/LEARNINGS.md")
    git(host, "commit", "-q", "-m", "keep the shelf in history")
    shelf = (host / "references" / "LEARNINGS.md").read_bytes()
    assert rid.encode() in shelf  # control
    sheet = _sheet(tmp_path, [{"id": rid, "verb": "replace", "trigger": NEW_TRIGGER,
                               "instruction": NEW_INSTRUCTION, "because": "shorter",
                               "dest": "claude-md"}])

    (pitem,) = batch.dry_run(home, sheet, actor="human").items
    assert (pitem.state, pitem.kind) == ("would-refuse", "needs-person"), pitem.detail
    assert "LEARNINGS.md is tracked by git" in (pitem.detail or "")
    (item,) = batch.run(home, sheet, no_push=True, actor="human").items
    assert (item.state, item.kind) == ("refused", "needs-person"), item.detail
    assert _rec(home, rid).status == "routed"
    assert (host / "references" / "LEARNINGS.md").read_bytes() == shelf


def test_a_replace_on_the_default_shelf_stores_the_shelf_as_a_route_does(env):
    """Fold item 5, N1: a lesson on its bucket's default reference shelf
    stores `reference_file: None`; a replace inheriting that placement
    stores the same, not the file name spelled out."""
    old = _seed(env.home, "lrn-e1f00061")
    _place(env.home, old, "reference")
    assert (_rec(env.home, old).routing or {}).get("reference_file") is None  # control
    new = verbs.replace_lesson(env.home, old, trigger=NEW_TRIGGER, instruction=NEW_INSTRUCTION,
                               because="shorter", no_push=True).new_record_id
    routing = _rec(env.home, new).routing or {}
    assert (routing.get("destination"), routing.get("reference_file")) == ("reference", None)


def test_a_pending_replacement_carries_because_as_its_resolution_note(env):
    """Fold item 5, N3: on the pending path too, `because` (with `note`
    after it) is the new lesson's resolution_note, as on the routed path."""
    old = _seed(env.home, "lrn-e1f00071")
    new = verbs.replace_lesson(env.home, old, fact="The yield per round decides it.",
                               because="it is a fact", note="from the review", no_push=True
                               ).new_record_id
    assert _rec(env.home, new).resolution_note == "it is a fact\n\nfrom the review"
