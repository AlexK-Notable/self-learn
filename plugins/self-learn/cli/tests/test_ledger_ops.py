"""T3 ledger ops: create / resolve (git mv) / defer / supersede / proposals /
queue + eligibility. All on sandbox git repos under tmpdirs (02 §2–§3,
08 §1 pins: Proposal lifecycle, Dedupe key, `--json` stubs; §7.1 step 2)."""

import os
from datetime import datetime, timezone

import pytest

from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import (
    LedgerOpsError,
    LIVE_STATUSES,
    ProposalError,
    bucket_dir_for_scope,
    create_record,
    defer_record,
    find_record_path,
    is_unanalyzed,
    proposal_info,
    queue,
    read_proposal,
    require_status,
    resolve_record,
    stamp_proposal,
    supersede_cycle_check,
    supersede_record,
    unparseable_pending,
    validate_merge_proposal,
    validate_proposal,
    write_proposal,
)
from self_learn.normalize import sha_anchor
from self_learn.records import Record

from support import (
    force_past_deferred,
    commit_all,
    git,
    hook_proposal_fields,
    init_repo,
    make_behavior,
    make_env,
    make_home,
    make_knowledge,
    merge_proposal_text,
    proposal_dict,
)


def _bucket(home, name="s"):
    (b,) = [b for b in discover_buckets(home) if b.name == name]
    return b


# ------------------------------------------------------------ create_record


def test_create_record_skill_scope_resolves_skill_bucket(tmp_path):
    # doc 13 §3: skill buckets live under <home>/skills/<name>, gated on
    # the skill existing in the registered skills-root HOST.
    home = make_home(tmp_path, skills=("home-assistant",))
    rec = make_behavior(scope="skill:home-assistant")
    path = create_record(home, rec)
    assert path == (
        home / "skills" / "home-assistant" / "pending" / f"{rec.id}.md"
    )
    assert path.is_file()
    assert Record.from_path(path).status == "pending"


def test_create_record_user_scope_lands_in_user_bucket(tmp_path):
    home = make_home(tmp_path)
    rec = make_knowledge(scope="user")
    path = create_record(home, rec)
    assert path == home / "user" / "pending" / f"{rec.id}.md"
    assert path.is_file()


def test_create_record_project_scope_needs_and_uses_project_path(tmp_path):
    # doc 13 §3: project buckets are per-project — the path is REQUIRED
    # and recorded in meta.yaml beside the bucket (the slug alone is lossy).
    from self_learn.hosts import slug_for
    from self_learn.ledger_ops import bucket_project_path

    home = make_home(tmp_path)
    with pytest.raises(LedgerOpsError, match="project_path"):
        create_record(home, make_knowledge(scope="project"))
    proj = tmp_path / "proj-repo"
    init_repo(proj)
    rec = make_knowledge(scope="project")
    path = create_record(home, rec, project_path=proj)
    bucket_dir = home / "projects" / slug_for(proj)
    assert path == bucket_dir / "pending" / f"{rec.id}.md"
    assert path.is_file()
    assert bucket_project_path(bucket_dir) == proj.resolve()


def test_create_record_unknown_skill_raises(tmp_path):
    home = make_home(tmp_path, skills=("s",))
    rec = make_behavior(scope="skill:nope")
    with pytest.raises(LedgerOpsError, match="nope"):
        create_record(home, rec)


def test_create_record_ambiguous_skill_raises(tmp_path):
    # Ambiguity is now judged against the registered skills-root HOST:
    # two plugins there carrying the same skill name refuse the capture.
    env = make_env(tmp_path, skills=("s",))
    (env.host / "plugins" / "other-plugin" / "skills" / "s").mkdir(parents=True)
    with pytest.raises(LedgerOpsError, match="ambiguous"):
        create_record(env.ledger, make_behavior(scope="skill:s"))


def test_create_record_duplicate_id_raises(tmp_path):
    home = make_home(tmp_path)
    rec = make_behavior(record_id="lrn-aa000001")
    create_record(home, rec)
    with pytest.raises(LedgerOpsError, match="exists"):
        create_record(home, make_behavior(record_id="lrn-aa000001"))


def test_bucket_dir_for_scope_rejects_garbage(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(LedgerOpsError):
        bucket_dir_for_scope(home, "banana")


# ---------------------------------------------------------- resolve_record


def test_resolve_routed_moves_via_git_with_rename_detection(tmp_path):
    home = make_home(tmp_path)
    rec = make_behavior(record_id="lrn-aa000001")
    pending_path = create_record(home, rec)
    commit_all(home, "capture")

    touched = resolve_record(
        home, "lrn-aa000001", "routed", destination="skill-md", note="good rule"
    )

    resolved_path = pending_path.parent.parent / "resolved" / "lrn-aa000001.md"
    assert not pending_path.exists()
    assert resolved_path.is_file()

    moved = Record.from_path(resolved_path)
    assert moved.status == "routed"
    assert moved.routing == {
        "routed_at": moved.routing["routed_at"],
        "destination": "skill-md",
        "by": "human",
    }
    assert moved.resolution_note == "good rule"

    # Stage exactly the touched paths and commit; deletions among them are
    # pre-staged by git mv/rm (module contract), so T7 adds the survivors.
    # The mv must be rename-detected so `git log --follow` spans it.
    git(home, "add", "--", *[str(p) for p in touched if p.exists()])
    git(home, "commit", "-q", "-m", "self-learn: route lrn-aa000001 → skill-md")

    follow = git(
        home, "log", "--follow", "--format=%s", "--", str(resolved_path)
    ).stdout.strip().split("\n")
    assert len(follow) == 2  # move commit AND the original capture commit
    name_status = git(
        home, "diff", "HEAD~1", "HEAD", "-M", "--name-status"
    ).stdout
    assert name_status.startswith("R")
    assert "pending/lrn-aa000001.md" in name_status
    assert "resolved/lrn-aa000001.md" in name_status


def test_resolve_untracked_record_falls_back_to_fs_move(tmp_path):
    home = make_home(tmp_path)
    rec = make_behavior(record_id="lrn-aa000002")
    pending_path = create_record(home, rec)  # never committed

    touched = resolve_record(home, "lrn-aa000002", "rejected")
    resolved_path = pending_path.parent.parent / "resolved" / "lrn-aa000002.md"
    assert not pending_path.exists()
    assert resolved_path.is_file()
    assert Record.from_path(resolved_path).status == "rejected"
    assert pending_path in touched and resolved_path in touched


def test_resolve_removes_proposal_siblings_and_partial_merge_clusters(tmp_path):
    home = make_home(tmp_path)
    a = make_behavior(record_id="lrn-aa000001")
    b = make_behavior(record_id="lrn-bb000002")
    c = make_behavior(record_id="lrn-cc000003")
    path_a = create_record(home, a)
    create_record(home, b)
    create_record(home, c)

    pdir = path_a.parent.parent / "proposals"
    pdir.mkdir()
    yaml_a = pdir / "lrn-aa000001.yaml"
    diff_a = pdir / "lrn-aa000001.diff"
    merge_ab = pdir / "merge-9f3d2c1a.yaml"
    merge_bc = pdir / "merge-0e1d2c3b.yaml"
    write_proposal(home, "lrn-aa000001", proposal_dict())
    diff_a.write_text("--- preview\n")
    merge_ab.write_text(
        merge_proposal_text("merge-9f3d2c1a", ["lrn-aa000001", "lrn-bb000002"], "lrn-aa000001")
    )
    merge_bc.write_text(
        merge_proposal_text("merge-0e1d2c3b", ["lrn-bb000002", "lrn-cc000003"], "lrn-bb000002")
    )
    # yaml_a + merge_ab tracked; diff_a left untracked (mid-review case —
    # --ignore-unmatch + fs remove must still clear it)
    git(home, "add", "--", str(yaml_a), str(merge_ab))
    commit_all(home, "capture + proposals")

    touched = resolve_record(home, "lrn-aa000001", "routed", destination="hook")

    assert not yaml_a.exists()
    assert not diff_a.exists()
    assert not merge_ab.exists()  # names the resolved id → partial cluster invalid
    assert merge_bc.exists()  # does not name it → survives
    for p in (yaml_a, diff_a, merge_ab):
        assert p in touched


def test_resolve_touched_path_list_is_exact(tmp_path):
    home = make_home(tmp_path)
    rec = make_behavior(record_id="lrn-aa000001")
    pending_path = create_record(home, rec)
    pdir = pending_path.parent.parent / "proposals"
    write_proposal(home, "lrn-aa000001", proposal_dict())
    commit_all(home, "capture")

    touched = resolve_record(home, "lrn-aa000001", "routed", destination="skill-md")
    resolved_path = pending_path.parent.parent / "resolved" / "lrn-aa000001.md"
    assert sorted(touched) == sorted(
        [pending_path, resolved_path, pdir / "lrn-aa000001.yaml"]
    )


def test_resolve_routed_requires_destination(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    with pytest.raises(LedgerOpsError, match="destination"):
        resolve_record(home, "lrn-aa000001", "routed")


def test_resolve_superseded_requires_superseded_by(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    with pytest.raises(LedgerOpsError, match="superseded_by"):
        resolve_record(home, "lrn-aa000001", "superseded")


def test_resolve_rejects_non_terminal_status(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    with pytest.raises(LedgerOpsError):
        resolve_record(home, "lrn-aa000001", "deferred")


def test_resolve_missing_record_raises(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(LedgerOpsError, match="not found"):
        resolve_record(home, "lrn-99999999", "rejected")


# ---------------------------------------------------- supersede / graduate


def test_supersede_pending_record_moves_and_links(tmp_path):
    home = make_home(tmp_path)
    old = make_behavior(record_id="lrn-aa000001")
    pending_path = create_record(home, old)
    commit_all(home)

    supersede_record(home, "lrn-aa000001", "lrn-bb000002")
    resolved_path = pending_path.parent.parent / "resolved" / "lrn-aa000001.md"
    moved = Record.from_path(resolved_path)
    assert moved.status == "superseded"
    assert moved.superseded_by == "lrn-bb000002"


def test_graduation_marks_superseded_by_canon(tmp_path):
    home = make_home(tmp_path)
    pending_path = create_record(
        home, make_knowledge(scope="user", record_id="lrn-aa000001")
    )
    supersede_record(home, "lrn-aa000001", "canon")
    moved = Record.from_path(pending_path.parent.parent / "resolved" / "lrn-aa000001.md")
    assert moved.status == "superseded"
    assert moved.superseded_by == "canon"


def test_supersede_already_resolved_record_updates_in_place(tmp_path):
    # Corrective supersession targets an already-routed record in resolved/.
    home = make_home(tmp_path)
    pending_path = create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    resolve_record(home, "lrn-aa000001", "routed", destination="skill-md")
    resolved_path = pending_path.parent.parent / "resolved" / "lrn-aa000001.md"

    touched = supersede_record(home, "lrn-aa000001", "lrn-bb000002")
    assert resolved_path.is_file()
    updated = Record.from_path(resolved_path)
    assert updated.status == "superseded"
    assert updated.superseded_by == "lrn-bb000002"
    assert touched == [resolved_path]


# ------------------------------------------------- FW-51: require_status
#
# (2026-08-26 verb assessment): `resolve_record` used to look a record up
# via `find_record_path` with NO status precondition at all — every
# resolution verb inherited that hole. These pin the root-cause fix
# DIRECTLY at the `resolve_record`/`require_status` layer, independent of
# the verb-level guards `test_verbs.py` pins (which add the correct exit
# code + pre-lock timing on top of this).


def test_resolve_record_no_longer_lies_not_found_for_a_resolved_record(tmp_path):
    # FW-51: `route`/`reject`/`defer` used to search pending/ ONLY, so a
    # record sitting in resolved/ (any terminal status) came back "not
    # found" (a lie -- the record exists, its STATUS makes the verb
    # illegal). resolve_record now finds it and refuses on status.
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    resolve_record(home, "lrn-aa000001", "rejected")  # -> resolved/, status rejected

    with pytest.raises(LedgerOpsError) as excinfo:
        resolve_record(home, "lrn-aa000001", "routed", destination="skill-md")
    message = str(excinfo.value)
    assert "not found" not in message
    assert "lrn-aa000001" in message
    assert "'rejected'" in message


def test_resolve_record_refuses_graduate_after_reject(tmp_path):
    # The measured FW-51 headline defect: `reject A` then `graduate A`
    # used to rc 0 and silently invert the human's denial into "the
    # lesson won" (superseded_by: canon). `graduate` is
    # `resolve_record(..., "superseded", superseded_by="canon")` at this
    # layer.
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    resolve_record(home, "lrn-aa000001", "rejected")

    with pytest.raises(LedgerOpsError, match="rejected"):
        resolve_record(home, "lrn-aa000001", "superseded", superseded_by="canon")

    # nothing written on refusal: still rejected, not superseded
    resolved_path = home / "skills" / "s" / "resolved" / "lrn-aa000001.md"
    assert Record.from_path(resolved_path).status == "rejected"


@pytest.mark.parametrize("source_status", ["pending", "deferred", "routed"])
def test_resolve_record_accepts_every_live_source_for_superseded(tmp_path, source_status):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    if source_status == "deferred":
        defer_record(home, "lrn-aa000001", "2099-01-01")
    elif source_status == "routed":
        resolve_record(home, "lrn-aa000001", "routed", destination="skill-md")

    resolve_record(home, "lrn-aa000001", "superseded", superseded_by="canon")
    resolved_path = home / "skills" / "s" / "resolved" / "lrn-aa000001.md"
    assert Record.from_path(resolved_path).status == "superseded"


@pytest.mark.parametrize("new_status", ["routed", "rejected"])
def test_resolve_record_refuses_terminal_source_for_route_and_reject(tmp_path, new_status):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    resolve_record(home, "lrn-aa000001", "rejected")  # terminalize it first

    with pytest.raises(LedgerOpsError, match="rejected"):
        if new_status == "routed":
            resolve_record(home, "lrn-aa000001", new_status, destination="skill-md")
        else:
            resolve_record(home, "lrn-aa000001", new_status)


def test_supersede_record_refuses_terminal_old(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    resolve_record(home, "lrn-aa000001", "rejected")

    with pytest.raises(LedgerOpsError, match="rejected"):
        supersede_record(home, "lrn-aa000001", "lrn-bb000002")


def test_supersede_record_refuses_already_graduated_old(tmp_path):
    # supersede on a canon-graduated record: FW-51's second measured case.
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    supersede_record(home, "lrn-aa000001", "canon")  # graduate-equivalent

    with pytest.raises(LedgerOpsError, match="superseded"):
        supersede_record(home, "lrn-aa000001", "lrn-bb000002")


def test_supersede_record_direct_cycle_refused(tmp_path):
    # FW-51's two-record cycle: `supersede C D` then `supersede D C` --
    # neither record ends up live. The second call must refuse.
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-cccccccc"))
    create_record(home, make_behavior(record_id="lrn-dddddddd"))
    commit_all(home)

    supersede_record(home, "lrn-cccccccc", "lrn-dddddddd")  # C -> D

    with pytest.raises(LedgerOpsError):
        supersede_record(home, "lrn-dddddddd", "lrn-cccccccc")  # D -> C: cycle

    # neither record was touched by the refused call
    c = Record.from_path(home / "skills" / "s" / "resolved" / "lrn-cccccccc.md")
    assert c.status == "superseded" and c.superseded_by == "lrn-dddddddd"
    d = Record.from_path(home / "skills" / "s" / "pending" / "lrn-dddddddd.md")
    assert d.status == "pending" and d.superseded_by is None


def test_supersede_record_refuses_direct_self_cycle(tmp_path):
    """Root-cause extra (code gate r1): `supersede_record(home, X, X)`
    used to be silently ACCEPTED — `supersede_cycle_check`'s walk starts
    at `superseded_by`'s OWN `superseded_by` field, which for a live
    record is always None, so the walk finds nothing to hop to and
    returns clean without ever noticing `old_id == superseded_by`. The
    result was real corruption: `lrn-aa000001` pointing at itself
    (`superseded_by: lrn-aa000001`). The standalone `supersede` VERB
    already had its own `old_id == new_id` guard — this pins the SAME
    refusal one layer down, in `supersede_record` itself, which `route
    --supersedes` and any other direct caller also goes through."""
    home = make_home(tmp_path)
    pending_path = create_record(home, make_behavior(record_id="lrn-aa000001"))

    with pytest.raises(LedgerOpsError, match="itself"):
        supersede_record(home, "lrn-aa000001", "lrn-aa000001")

    # nothing written: still pending, no self-reference
    rec = Record.from_path(pending_path)
    assert rec.status == "pending"
    assert rec.superseded_by is None


# ----------------------------------------------------------- defer_record


def test_defer_sets_metadata_in_place_and_increments_count(tmp_path):
    home = make_home(tmp_path)
    pending_path = create_record(home, make_behavior(record_id="lrn-aa000001"))

    touched = defer_record(home, "lrn-aa000001", "2099-01-01")
    assert touched == [pending_path]
    rec = Record.from_path(pending_path)
    assert rec.status == "deferred"
    assert str(rec.deferred_until) == "2099-01-01"
    assert rec.deferred_count == 1

    defer_record(home, "lrn-aa000001", "2099-06-01")
    rec = Record.from_path(pending_path)
    assert rec.deferred_count == 2
    assert str(rec.deferred_until) == "2099-06-01"
    assert pending_path.parent.name == "pending"  # never moved


def test_defer_default_is_plus_30_days(tmp_path):
    home = make_home(tmp_path)
    path = create_record(home, make_behavior(record_id="lrn-aa000001"))
    defer_record(home, "lrn-aa000001")
    rec = Record.from_path(path)
    until = datetime.strptime(str(rec.deferred_until), "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    delta_days = (until - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 28.5 < delta_days < 30.5


# -------------------------------------------------- queue membership (ONE fn)


def test_queue_hides_future_deferred_shows_past_deferred(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))  # plain pending
    create_record(home, make_behavior(record_id="lrn-bb000002"))
    create_record(home, make_behavior(record_id="lrn-cc000003"))
    defer_record(home, "lrn-bb000002", "2099-01-01")  # future → hidden
    # U-verbs STATE1: `defer_record` itself now refuses a past `--until`
    # (the human-typo guard) — simulate a deferral that has already
    # ELAPSED instead, which is the real-world way `deferred_until` ends
    # up in the past.
    force_past_deferred(home, "lrn-cc000003", "2020-01-01")  # past → visible again

    bucket = _bucket(home)
    ids = [e.record.id for e in queue(bucket)]
    assert ids == ["lrn-aa000001", "lrn-cc000003"]

    superset = [e.record.id for e in queue(bucket, include_deferred=True)]
    assert superset == ["lrn-aa000001", "lrn-bb000002", "lrn-cc000003"]


def test_queue_skips_unparseable_files_and_reports_them(tmp_path):
    home = make_home(tmp_path)
    path = create_record(home, make_behavior(record_id="lrn-aa000001"))
    junk = path.parent / "lrn-ffffffff.md"
    junk.write_text("not a record\n")
    bucket = _bucket(home)
    assert [e.record.id for e in queue(bucket)] == ["lrn-aa000001"]
    assert unparseable_pending(bucket) == [junk]


# ---- 09 §5 FW-18: the widened skip set (I/O, decode, YAML — not just
# RecordError). Each test seeds ONE failure class into pending/ and pins
# that BOTH the queue excludes it AND unparseable_pending captures it
# WITHOUT RAISING. Kill check: narrow the catch back to `except
# RecordError:` and the decode/YAML/OSError cases propagate out of
# _load_pending (queue and unparseable_pending both crash), reddening the
# matching test. The junk-file test above still passes under the narrow
# catch, so it alone would NOT protect the widening.


def _valid_and_bucket(tmp_path):
    home = make_home(tmp_path)
    path = create_record(home, make_behavior(record_id="lrn-aa000001"))
    return home, path.parent, _bucket(home)


def test_load_pending_skips_yaml_parse_error(tmp_path):
    """A record whose frontmatter block is present but not parseable YAML
    (ruamel raises YAMLError, not a RecordError)."""
    _home, pending_dir, bucket = _valid_and_bucket(tmp_path)
    bad = pending_dir / "lrn-badya111.md"
    bad.write_text("---\nfoo: [unclosed\n---\nbody text\n", encoding="utf-8")
    assert [e.record.id for e in queue(bucket)] == ["lrn-aa000001"]
    assert unparseable_pending(bucket) == [bad]


def test_load_pending_skips_undecodable_bytes(tmp_path):
    """A record file that is not valid UTF-8 (read_text raises
    UnicodeDecodeError, a ValueError — never caught by `except OSError`)."""
    _home, pending_dir, bucket = _valid_and_bucket(tmp_path)
    bad = pending_dir / "lrn-badby222.md"
    bad.write_bytes(b"---\nid: \xff\xfe not utf-8\n---\nbody\n")
    assert [e.record.id for e in queue(bucket)] == ["lrn-aa000001"]
    assert unparseable_pending(bucket) == [bad]


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="chmod 000 does not deny read to root",
)
def test_load_pending_skips_unreadable_file_oserror(tmp_path):
    """A record file present at glob time but unreadable (chmod 000 →
    PermissionError, an OSError) — the 'vanished/permissions' class."""
    _home, pending_dir, bucket = _valid_and_bucket(tmp_path)
    bad = pending_dir / "lrn-badio333.md"
    bad.write_text("---\nid: lrn-badio333\n---\nbody\n", encoding="utf-8")
    bad.chmod(0o000)
    try:
        assert [e.record.id for e in queue(bucket)] == ["lrn-aa000001"]
        assert unparseable_pending(bucket) == [bad]
    finally:
        bad.chmod(0o644)  # let tmp_path teardown remove it


def test_resolved_records_never_in_queue(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    resolve_record(home, "lrn-aa000001", "rejected")
    assert queue(_bucket(home)) == []


# ------------------------------------- eligibility / unanalyzed (ONE fn)


def _seed_eligibility_matrix(home):
    """no proposal / unparseable / schema-invalid / stale sha / fresh."""
    ids = {
        "none": "lrn-aa000001",
        "unparseable": "lrn-bb000002",
        "invalid": "lrn-cc000003",
        "stale": "lrn-dd000004",
        "fresh": "lrn-ee000005",
    }
    for rid in ids.values():
        create_record(home, make_behavior(record_id=rid))
    bucket = _bucket(home)
    pdir = bucket.path / "proposals"
    pdir.mkdir(exist_ok=True)
    (pdir / f"{ids['unparseable']}.yaml").write_text("{ [unclosed\n")
    (pdir / f"{ids['invalid']}.yaml").write_text("rationale: missing destination\n")
    write_proposal(home, ids["stale"], proposal_dict(record_sha="sha256:000000000000"))
    write_proposal(home, ids["fresh"], proposal_dict())
    stamp_proposal(home, ids["fresh"])
    return bucket, ids


def test_eligibility_matrix(tmp_path):
    home = make_home(tmp_path)
    bucket, ids = _seed_eligibility_matrix(home)
    by_id = {e.record.id: e for e in queue(bucket)}
    assert is_unanalyzed(by_id[ids["none"]]) is True
    assert is_unanalyzed(by_id[ids["unparseable"]]) is True
    assert is_unanalyzed(by_id[ids["invalid"]]) is True
    assert is_unanalyzed(by_id[ids["stale"]]) is True
    assert is_unanalyzed(by_id[ids["fresh"]]) is False


def test_future_deferred_record_is_not_unanalyzed(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    defer_record(home, "lrn-aa000001", "2099-01-01")
    bucket = _bucket(home)
    (entry,) = queue(bucket, include_deferred=True)
    assert is_unanalyzed(entry) is False  # deferred → ineligible even w/o proposal


def test_stale_becomes_fresh_after_record_edit_plus_restamp(tmp_path):
    home = make_home(tmp_path)
    path = create_record(home, make_behavior(record_id="lrn-aa000001"))
    write_proposal(home, "lrn-aa000001", proposal_dict())
    stamp_proposal(home, "lrn-aa000001")
    bucket = _bucket(home)
    (entry,) = queue(bucket)
    assert is_unanalyzed(entry) is False

    # Edit the pending record body (legal pre-routing) → hash mismatch.
    rec = Record.from_path(path)
    rec.set_body("\n## Trigger\nA different trigger.\n\n## Instruction\nDo the thing.\n")
    rec.write(path)
    (entry,) = queue(bucket)
    assert is_unanalyzed(entry) is True

    stamp_proposal(home, "lrn-aa000001")
    (entry,) = queue(bucket)
    assert is_unanalyzed(entry) is False


# ------------------------------------------------------- proposal I/O


def test_write_and_read_proposal_roundtrip(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    p = write_proposal(
        home,
        "lrn-aa000001",
        # 02 §1 hook extension (M3): destination hook carries the
        # structured compile input + replay examples.
        proposal_dict(destination="hook", **hook_proposal_fields()),
    )
    data = read_proposal(p)
    assert data["destination"] == "hook"
    validate_proposal(data)


def test_write_proposal_rejects_bad_destination(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    with pytest.raises(ProposalError, match="destination"):
        write_proposal(home, "lrn-aa000001", proposal_dict(destination="emailer"))


def test_validate_proposal_requires_core_fields():
    with pytest.raises(ProposalError):
        validate_proposal({"destination": "skill-md"})
    with pytest.raises(ProposalError, match="already_canon"):
        validate_proposal(proposal_dict(already_canon="yes"))
    with pytest.raises(ProposalError, match="record_sha"):
        validate_proposal(proposal_dict(record_sha="not-a-sha"))
    validate_proposal(proposal_dict())  # baseline sane


def test_validate_proposal_card_shape():
    # Optional: pre-contract proposals (no card) stay valid.
    validate_proposal(proposal_dict())
    # Valid card: mapping of non-empty str → non-empty str; keys are NOT
    # enforced against the registry here (02 §1 M1 posture), so an
    # unknown-but-well-formed key passes.
    validate_proposal(
        proposal_dict(
            card={
                "headline": "The bedroom never turned red at night.",
                "impact": "Next time Claude checks the AL mode switch first.",
                "discuss": "Nothing contentious.",
                "future-section": "unknown keys are the registry's business",
            }
        )
    )
    with pytest.raises(ProposalError, match="card must be a non-empty mapping"):
        validate_proposal(proposal_dict(card="just a string"))
    with pytest.raises(ProposalError, match="card must be a non-empty mapping"):
        validate_proposal(proposal_dict(card={}))
    with pytest.raises(ProposalError, match="non-empty text"):
        validate_proposal(proposal_dict(card={"headline": "   "}))
    with pytest.raises(ProposalError, match="non-empty text"):
        validate_proposal(proposal_dict(card={"impact": None}))
    with pytest.raises(ProposalError, match="keys must be non-empty"):
        validate_proposal(proposal_dict(card={"": "text"}))


def test_validate_merge_proposal():
    from ruamel.yaml import YAML

    data = YAML(typ="rt").load(
        merge_proposal_text("merge-9f3d2c1a", ["lrn-aa000001", "lrn-bb000002"], "lrn-aa000001")
    )
    validate_merge_proposal(data)
    bad = dict(data)
    bad["suggested_survivor"] = "lrn-99999999"
    with pytest.raises(ProposalError, match="survivor"):
        validate_merge_proposal(bad)
    with pytest.raises(ProposalError, match="cluster_id"):
        validate_merge_proposal({**dict(data), "cluster_id": "cluster-1"})


def test_stamp_proposal_overwrites_model_emitted_sha(tmp_path):
    home = make_home(tmp_path)
    path = create_record(home, make_behavior(record_id="lrn-aa000001"))
    write_proposal(
        home, "lrn-aa000001", proposal_dict(record_sha="sha256:deadbeef1234")
    )
    ppath = stamp_proposal(home, "lrn-aa000001")
    data = read_proposal(ppath)
    assert data["record_sha"] == sha_anchor(Record.from_path(path).body)
    assert data["record_sha"] != "sha256:deadbeef1234"


def test_stamp_proposal_unparseable_yaml_raises(tmp_path):
    home = make_home(tmp_path)
    path = create_record(home, make_behavior(record_id="lrn-aa000001"))
    pdir = path.parent.parent / "proposals"
    pdir.mkdir(exist_ok=True)
    (pdir / "lrn-aa000001.yaml").write_text("{ [unclosed\n")
    with pytest.raises(ProposalError):
        stamp_proposal(home, "lrn-aa000001")


# ------------------------------------------------------ proposal_info


def test_proposal_info_shapes(tmp_path):
    home = make_home(tmp_path)
    bucket, ids = _seed_eligibility_matrix(home)
    by_id = {e.record.id: e for e in queue(bucket)}

    none = proposal_info(by_id[ids["none"]])
    assert none == {
        "has_proposal": False,
        "proposal_fresh": False,
        "destination": None,
        "already_canon": False,
    }
    invalid = proposal_info(by_id[ids["invalid"]])
    assert invalid["has_proposal"] is True
    assert invalid["proposal_fresh"] is False
    assert invalid["destination"] is None
    fresh = proposal_info(by_id[ids["fresh"]])
    assert fresh["proposal_fresh"] is True
    assert fresh["destination"] == "skill-md"


# --------------------------------------------------- require_status (unit)


def test_require_status_finds_a_resolved_record_not_just_pending(tmp_path):
    # The FW-51 fix's core mechanism: find_record_path's DEFAULT statuses
    # (pending, resolved) — an existing record is never "not found"
    # merely because its status makes the caller's verb illegal.
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    resolve_record(home, "lrn-aa000001", "rejected")

    path, record = require_status(
        home, "lrn-aa000001", frozenset({"rejected"}), verb="probe"
    )
    # not raised — but the record IS found and its real status readable,
    # proving the lookup itself never lied "not found"
    assert path == find_record_path(home, "lrn-aa000001")
    assert record.status == "rejected"


def test_require_status_returns_path_and_record_when_allowed(tmp_path):
    home = make_home(tmp_path)
    pending_path = create_record(home, make_behavior(record_id="lrn-aa000001"))

    path, record = require_status(home, "lrn-aa000001", LIVE_STATUSES, verb="probe")
    assert path == pending_path
    assert record.status == "pending"


def test_require_status_refuses_naming_record_status_and_verb(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    commit_all(home)
    resolve_record(home, "lrn-aa000001", "rejected")

    with pytest.raises(LedgerOpsError) as excinfo:
        require_status(home, "lrn-aa000001", LIVE_STATUSES, verb="reject")
    message = str(excinfo.value)
    assert "lrn-aa000001" in message
    assert "'rejected'" in message
    assert "reject" in message


def test_require_status_still_raises_not_found_for_a_genuinely_missing_id(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(LedgerOpsError, match="not found"):
        require_status(home, "lrn-99999999", LIVE_STATUSES, verb="probe")


# ---------------------------------------------- supersede_cycle_check (unit)


def test_supersede_cycle_check_passes_when_new_has_no_chain(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    create_record(home, make_behavior(record_id="lrn-bb000002"))
    supersede_cycle_check(home, "lrn-aa000001", "lrn-bb000002")  # no raise


def test_supersede_cycle_check_tolerates_a_dangling_new_id(tmp_path):
    # supersede_record has never validated `superseded_by` names a real
    # record (metadata-only) -- the cycle walk must not invent a refusal
    # for an id that simply does not exist.
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    supersede_cycle_check(home, "lrn-aa000001", "lrn-99999999")  # no raise


def test_supersede_cycle_check_refuses_direct_cycle(tmp_path):
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-cccccccc"))
    create_record(home, make_behavior(record_id="lrn-dddddddd"))
    commit_all(home)
    supersede_record(home, "lrn-cccccccc", "lrn-dddddddd")  # C.superseded_by = D

    with pytest.raises(LedgerOpsError, match="cycle"):
        supersede_cycle_check(home, "lrn-dddddddd", "lrn-cccccccc")


def test_supersede_cycle_check_refuses_a_longer_chain(tmp_path):
    """The genuinely graph-shaped case (u-verbguards §5's "longer chain"
    obligation), isolated from the liveness check: A is LIVE (status
    routed) yet ALSO carries a hand-set `superseded_by` chain A -> B -> C
    reaching back to `old_id` -- a combination the CLI itself can never
    produce (resolve_record only ever sets `superseded_by` together with
    a terminal status), but nothing in the schema forbids it (02 §2:
    `superseded_by` is mutable "in every status"). This proves the walk
    is a real, independent graph traversal, not just a restatement of
    the NEW-status liveness check: if `supersede_cycle_check`'s call
    were deleted from `supersede_record`, THIS record's own status
    (`routed`) would sail straight through `require_status`, and only
    the walk below stands between `supersede(C, A)` and a cycle."""
    home = make_home(tmp_path)
    bucket_dir = home / "skills" / "s"
    a_path = create_record(home, make_behavior(record_id="lrn-aaaaaaaa"))
    create_record(home, make_behavior(record_id="lrn-bbbbbbbb"))
    create_record(home, make_behavior(record_id="lrn-cccccccc"))
    commit_all(home)
    resolve_record(home, "lrn-aaaaaaaa", "routed", destination="skill-md")
    a_resolved = bucket_dir / "resolved" / "lrn-aaaaaaaa.md"
    b_pending = bucket_dir / "pending" / "lrn-bbbbbbbb.md"

    # Hand-set the chain A -> B -> C, bypassing resolve_record entirely —
    # A stays `status: routed` (LIVE) the whole time.
    a = Record.from_path(a_resolved)
    a.set_superseded_by("lrn-bbbbbbbb")
    a.write(a_resolved)
    b = Record.from_path(b_pending)
    b.set_superseded_by("lrn-cccccccc")
    b.write(b_pending)

    with pytest.raises(LedgerOpsError, match="cycle"):
        supersede_cycle_check(home, "lrn-cccccccc", "lrn-aaaaaaaa")

    # a genuinely live A (routed, no corrupted chain) is unaffected
    assert Record.from_path(a_resolved).status == "routed"
