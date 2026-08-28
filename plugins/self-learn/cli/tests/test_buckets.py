"""Bucket discovery on the independent ledger-home layout (doc 13 §3):
``skills/<name>/``, ``projects/<slug>/``, ``user/``."""

from self_learn.ledger import discover_buckets


def _mk_skill_bucket(home, skill):
    d = home / "skills" / skill
    d.mkdir(parents=True)
    return d


def test_empty_home_has_no_buckets(tmp_path):
    assert discover_buckets(tmp_path) == []


def test_skill_buckets_found_under_skills_dir(tmp_path):
    a = _mk_skill_bucket(tmp_path, "home-assistant")
    b = _mk_skill_bucket(tmp_path, "dotfiles")
    buckets = discover_buckets(tmp_path)
    assert [x.path for x in buckets] == sorted([a, b])
    assert all(x.scope == "skill" for x in buckets)
    assert {x.name for x in buckets} == {"home-assistant", "dotfiles"}


def test_skill_bucket_named_after_its_dir(tmp_path):
    _mk_skill_bucket(tmp_path, "inner-skill")
    (bucket,) = discover_buckets(tmp_path)
    assert bucket.name == "inner-skill"


def test_project_and_user_buckets_are_separate_scopes(tmp_path):
    # doc 13 §3: the old "project+user" root bucket is dead — projects/<slug>
    # buckets carry scope "project", user/ carries scope "user".
    proj = tmp_path / "projects" / "-home-user-repos-x"
    proj.mkdir(parents=True)
    user = tmp_path / "user"
    user.mkdir()
    buckets = {b.scope: b for b in discover_buckets(tmp_path)}
    assert set(buckets) == {"project", "user"}
    assert buckets["project"].path == proj
    assert buckets["project"].name == "-home-user-repos-x"
    assert buckets["user"].path == user
    assert buckets["user"].name == "user"


def test_non_bucket_dirs_and_files_are_not_buckets(tmp_path):
    # telemetry/ is observation lines, hosts.yaml is the registry, and a
    # stray FILE under skills/ is not a bucket dir.
    (tmp_path / "telemetry").mkdir()
    (tmp_path / "hosts.yaml").write_text("skills_root: /nowhere\n")
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "not-a-dir.md").write_text("stray\n")
    assert discover_buckets(tmp_path) == []


def test_pending_files_lists_md_only_sorted(tmp_path):
    d = _mk_skill_bucket(tmp_path, "s")
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
    _mk_skill_bucket(tmp_path, "s")
    (bucket,) = discover_buckets(tmp_path)
    assert bucket.pending_files() == []
