"""Bucket discovery (08-build-plan §1 Bucket-discovery pin, 02-schema §3)."""

from self_learn.ledger import discover_buckets


def _mk_skill_bucket(home, plugin, skill):
    d = home / "plugins" / plugin / "skills" / skill / ".self-learn"
    d.mkdir(parents=True)
    return d


def test_empty_home_has_no_buckets(tmp_path):
    assert discover_buckets(tmp_path) == []


def test_skill_buckets_found_via_glob(tmp_path):
    a = _mk_skill_bucket(tmp_path, "home-assistant", "home-assistant")
    b = _mk_skill_bucket(tmp_path, "chezmoi", "chezmoi")
    buckets = discover_buckets(tmp_path)
    assert [x.path for x in buckets] == sorted([a, b])
    assert all(x.scope == "skill" for x in buckets)
    assert {x.name for x in buckets} == {"home-assistant", "chezmoi"}


def test_skill_bucket_named_after_skill_dir_not_plugin(tmp_path):
    _mk_skill_bucket(tmp_path, "some-plugin", "inner-skill")
    (bucket,) = discover_buckets(tmp_path)
    assert bucket.name == "inner-skill"


def test_root_bucket_is_project_user_scope(tmp_path):
    root = tmp_path / ".self-learn"
    root.mkdir()
    (bucket,) = discover_buckets(tmp_path)
    assert bucket.path == root
    assert bucket.scope == "project+user"
    assert bucket.name == "project"


def test_plugin_dir_without_self_learn_is_not_a_bucket(tmp_path):
    (tmp_path / "plugins" / "p" / "skills" / "s").mkdir(parents=True)
    assert discover_buckets(tmp_path) == []


def test_pending_files_lists_md_only_sorted(tmp_path):
    d = _mk_skill_bucket(tmp_path, "p", "s")
    pending = d / "pending"
    pending.mkdir()
    (pending / "lrn-deadbeef.md").write_text("stub record\n")
    (pending / "lrn-cafef00d.md").write_text("stub record\n")
    (pending / "not-a-record.txt").write_text("ignored\n")
    (bucket,) = discover_buckets(tmp_path)
    assert [p.name for p in bucket.pending_files()] == [
        "lrn-cafef00d.md",
        "lrn-deadbeef.md",
    ]


def test_pending_files_empty_without_pending_dir(tmp_path):
    _mk_skill_bucket(tmp_path, "p", "s")
    (bucket,) = discover_buckets(tmp_path)
    assert bucket.pending_files() == []
