"""S-161 task selection: real files/FTS, fake embeddings, no writes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from self_learn import cli, select
from self_learn.index.related import COSINE_THRESHOLDS
from self_learn.index.store import LessonIndex, index_path
from self_learn.records import Record
from support import init_repo
from test_index import TopicProvider


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "ledger"
    init_repo(h)
    (h / "user").mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    return h


def put(home, number=1, *, scope="user", project=None, status="routed", gates=None,
        text="Docker container restart requires checking Docker container health", knowledge=False):
    rid = f"lrn-{number:08x}"
    kwargs = {"fact": text} if knowledge else {"trigger": text, "instruction": "Check the container health before restarting Docker."}
    r = Record.create(type="knowledge" if knowledge else "behavior", scope=scope,
                      source="teach", kind=None if knowledge else "anti-pattern", record_id=rid, **kwargs)
    r.set_status(status)
    if status == "routed":
        r.set_routing({"routed_at": "2026-11-22T00:00:00Z", "by": "human",
                       "destination": "claude-md", "rules_paths": gates,
                       **({"variant": "rules", "rules_topic": "containers"} if gates else {})})
    bucket = home / "user" if scope == "user" else home / "skills" / scope.removeprefix("skill:") if scope.startswith("skill:") else home / "projects" / f"project-{number}"
    folder = bucket / ("pending" if status in ("pending", "deferred") else "resolved")
    folder.mkdir(parents=True, exist_ok=True)
    if project is not None:
        (bucket / "meta.yaml").write_text(f"path: {json.dumps(str(project))}\n")
    path = folder / f"{rid}.md"
    r.write(path)
    return path


def ids(result):
    return [x["id"] for x in result["lessons"]]


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_current_text_rendered_floor_and_no_index_needed(home):
    path = put(home)
    fact = put(home, 2, knowledge=True)
    result = select.select_lessons(home, "Docker container health", provider=None)
    assert set(ids(result)) == {path.stem, fact.stem}
    assert result["mode"] == "lexical-only"
    for hit in result["lessons"]:
        assert hit["score"]["value"] >= result["thresholds"]["lexical"]
        assert hit["score"]["basis"] == "lexical"
        assert hit["scope"] == "user" and hit["routing"]["destination"] == "claude-md"
        assert "lexical" in hit["why"] and "user scope" in hit["why"]
    assert "**When" in next(h["text"] for h in result["lessons"] if h["type"] == "behavior")
    assert "Docker container restart" in next(h["text"] for h in result["lessons"] if h["type"] == "knowledge")
    assert ids(select.select_lessons(home, "medieval watercolor astronomy", provider=None)) == []
    assert not index_path(home).exists()


def test_scope_lifecycle_exclusions_before_limit(home, tmp_path):
    project, other = tmp_path / "app", tmp_path / "other"
    project.mkdir(); other.mkdir()
    put(home, 1)
    put(home, 2, scope="project", project=project)
    put(home, 3, scope="project", project=other)
    put(home, 4, scope="skill:containers")
    for n, state in enumerate(("pending", "deferred", "rejected", "superseded"), 5):
        path = put(home, n)
        historical = Record.from_path(path)
        historical.set_status(state)
        historical.write(path)
    assert ids(select.select_lessons(home, "Docker", provider=None)) == ["lrn-00000001"]
    result = select.select_lessons(home, "Docker", project=project, skills=["containers"], provider=None)
    assert set(ids(result)) == {"lrn-00000001", "lrn-00000002", "lrn-00000004"}
    assert "project scope" in result["lessons"][1]["why"]
    assert len(select.select_lessons(home, "Docker", project=project, skills=["containers"], limit=1, provider=None)["lessons"]) == 1
    assert ids(select.select_lessons(home, "Docker", project=project, exclude=["lrn-00000001"], limit=1, provider=None)) == ["lrn-00000002"]
    assert ids(select.select_lessons(home, "Docker", limit=0, provider=None)) == []


def test_path_gates_exact_recursive_absolute_glob_and_no_paths(home, tmp_path):
    project = tmp_path / "app"
    (project / "src" / "nested").mkdir(parents=True)
    (project / "src" / "main.py").touch()
    put(home, gates=["src/**/*.py"])
    assert not ids(select.select_lessons(home, "Docker", project=project, provider=None))
    for path in ("src/new.py", "src/nested/new.py", str(project / "src" / "main.py"), "src/**/*.py"):
        result = select.select_lessons(home, "Docker", project=project, paths=[path], provider=None)
        assert ids(result) == ["lrn-00000001"]
        assert "path gate" in result["lessons"][0]["why"]
        assert result["lessons"][0]["matched_paths"]
    for path in ("docs/main.py", "src/main.js", "missing/**/*.py"):
        assert not ids(select.select_lessons(home, "Docker", project=project, paths=[path], provider=None))
    with pytest.raises(ValueError):
        select.select_lessons(home, "Docker", project=project, paths=["../outside.py"], provider=None)


def test_hybrid_semantic_floor_and_unknown_model(home, monkeypatch):
    put(home, text="docker", knowledge=True)
    put(home, 2, text="lights", knowledge=True)
    fake = TopicProvider()
    ix = LessonIndex.open(home)
    ix.build(fake); ix.close()
    monkeypatch.setitem(COSINE_THRESHOLDS, fake.model_id, 0.75)
    result = select.select_lessons(home, "dockerized", provider=fake)
    assert ids(result) == ["lrn-00000001"]
    assert result["mode"] == "hybrid"
    assert result["lessons"][0]["score"]["basis"] == "cosine"
    assert "semantic" in result["lessons"][0]["why"]
    assert not ids(select.select_lessons(home, "watercolor astronomy", provider=fake))
    fake.calls.clear()
    monkeypatch.delitem(COSINE_THRESHOLDS, fake.model_id)
    result = select.select_lessons(home, "docker", provider=fake)
    assert result["mode"] == "lexical-only" and fake.calls == []
    assert "no measured" in result["note"]


def test_stale_vectors_and_lifecycle_never_recalled(home, monkeypatch):
    a, b = put(home), put(home, 2)
    fake = TopicProvider()
    monkeypatch.setitem(COSINE_THRESHOLDS, fake.model_id, .75)
    ix = LessonIndex.open(home); ix.build(fake); ix.close()
    r = Record.from_path(a); r.set_status("superseded"); r.write(a)
    r = Record.from_path(b); r.set_status("pending"); r.set_body("## Trigger\n\nwatercolor astronomy\n\n## Instruction\n\nPaint a star.\n"); r.set_status("routed"); r.write(b)
    result = select.select_lessons(home, "Docker", provider=fake)
    assert not ids(result)
    assert result["mode"] == "lexical-only"
    assert ids(select.select_lessons(home, "watercolor astronomy", provider=fake)) == [b.stem]


def test_provider_failure_and_partial_coverage_are_explicit(home, monkeypatch):
    put(home)
    fake = TopicProvider()
    monkeypatch.setitem(COSINE_THRESHOLDS, fake.model_id, .75)
    ix = LessonIndex.open(home); ix.build(fake); ix.close()
    put(home, 2)
    result = select.select_lessons(home, "Docker", provider=fake)
    assert len(result["lessons"]) == 2 and "partial" in result["note"]
    def broken(_texts):
        raise RuntimeError("never expose provider details")
    monkeypatch.setattr(fake, "embed", broken)
    result = select.select_lessons(home, "Docker", provider=fake)
    assert len(result["lessons"]) == 2 and result["mode"] == "lexical-only"
    assert "RuntimeError" in result["note"] and "never expose" not in result["note"]


def test_cli_read_only_even_when_autokick_enabled(home, tmp_path, monkeypatch, capsys):
    put(home)
    ix = LessonIndex.open(home); ix.build(None); ix.close()
    before = snapshot(tmp_path)
    def forbidden(*a, **kw):
        pytest.fail("select reached a mutating CLI path")
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "1")
    monkeypatch.setattr(cli.miner, "maybe_kick", forbidden)
    monkeypatch.setattr(cli.sentinel, "heartbeat", forbidden)
    monkeypatch.setattr(cli, "_mutating_epilogue", forbidden)
    monkeypatch.setattr(LessonIndex, "open_existing", forbidden)
    for _ in range(3):
        assert cli.main(["select", "--query", "Docker", "--no-embed", "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert ids(result) == ["lrn-00000001"]
    assert snapshot(tmp_path) == before
    assert cli.main(["select", "--query", "Docker", "--no-embed"]) == 0
    assert "**When" in capsys.readouterr().out


@pytest.mark.parametrize("args,code", [(["--query", " "], 2), (["--query", "x", "--limit", "-1"], 2), (["--query", "x", "--unknown"], 64)])
def test_invalid_cli_args(home, args, code):
    assert cli.main(["select", *args]) == code


def test_missing_home_not_empty_and_malformed_record_reported(home, tmp_path, monkeypatch, capsys):
    put(home)
    (home / "user" / "resolved" / "lrn-99999999.md").write_text("broken")
    assert cli.main(["select", "--query", "Docker", "--no-embed", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert ids(data) and data["unreadable"] == ["user/resolved/lrn-99999999.md"]
    missing = tmp_path / "missing"
    monkeypatch.setenv("SELF_LEARN_HOME", str(missing))
    assert cli.main(["select", "--query", "Docker", "--json"]) == 5
    assert "NOT an empty ledger" in capsys.readouterr().err
    assert not missing.exists()


def test_glob_scan_prunes_symlinks_and_refuses_budget(home, tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src/main.py").touch()
    (project / "cycle").symlink_to(project, target_is_directory=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.py").touch()
    (project / "external").symlink_to(outside, target_is_directory=True)
    assert select.task_paths(["**/*.py"], project) == ["src/main.py"]
    monkeypatch.setattr(select, "PATH_SCAN_LIMIT", 1)
    with pytest.raises(ValueError, match="budget exhausted"):
        select.task_paths(["**/*.py"], project)
    put(home, gates=["src/**/*.py"])
    assert select.select_lessons(home, "Docker", project=project, paths=["**/*.py"], limit=0)["lessons"] == []


def test_semantic_selection_does_not_change_cache_or_ledger(home, tmp_path, monkeypatch):
    put(home)
    fake = TopicProvider()
    monkeypatch.setitem(COSINE_THRESHOLDS, fake.model_id, .75)
    ix = LessonIndex.open(home); ix.build(fake); ix.close()
    before = snapshot(tmp_path)
    assert select.select_lessons(home, "Docker", provider=fake)["mode"] == "hybrid"
    assert snapshot(tmp_path) == before


def test_narrow_glob_scans_only_its_literal_prefix(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/ok.py").touch()
    (tmp_path / "src/unrelated").mkdir()
    for n in range(5):
        (tmp_path / "src/unrelated" / str(n)).touch()
    monkeypatch.setattr(select, "PATH_SCAN_LIMIT", 2)
    assert select.task_paths(["src/*.py"], tmp_path) == ["src/ok.py"]


def test_project_git_subdirectory_and_registered_worktree(home, tmp_path):
    from support import commit_all, git
    project = tmp_path / "project"
    init_repo(project)
    (project / "file").touch()
    (project / "subdir").mkdir()
    commit_all(project)
    (home / "hosts.yaml").write_text(f"projects:\n  - path: {project}\n")
    put(home, scope="project", project=project)
    wt = tmp_path / "worktree"
    git(project, "worktree", "add", "-b", "fixture", str(wt))
    for location in (project / "subdir", wt):
        assert ids(select.select_lessons(home, "Docker", project=location, provider=None)) == ["lrn-00000001"]


def test_live_status_with_supersession_pointer_excluded(home):
    path = put(home)
    r = Record.from_path(path)
    r.set_superseded_by("lrn-12345678")
    r.write(path)
    assert select.select_lessons(home, "Docker", provider=None)["lessons"] == []


def test_invalid_globs_are_usage_errors_or_reported_records(home, capsys):
    put(home)
    assert cli.main(["select", "--query", "Docker", "--path", "[z-a]", "--no-embed", "--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and "not translatable" in output.err
    path = put(home, 2, gates=["[z-a]"])
    result = select.select_lessons(home, "Docker", paths=["src/main.py"], provider=None)
    assert ids(result) == ["lrn-00000001"]
    assert result["unreadable"] == [str(path.relative_to(home))]


@pytest.mark.parametrize("knowledge", [False, True])
def test_reference_routing_preserves_full_sections_in_json_and_human(tmp_path, monkeypatch, capsys, knowledge):
    from support import make_env
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    first = "Recovery has two steps."
    later = "Restore the snapshot.\nReplay the event log."
    body = ["--type", "knowledge", "--fact", first + "\n" + later] if knowledge else [
        "--trigger", "Before recovery\nAfter a failed migration", "--instruction", first + "\n" + later]
    assert cli.main(["teach", "--skill", "s", *body, "--context", "Only for a stopped database.",
                     "--route", "--dest", "reference", "--note", "Synthetic reference approval",
                     "--json", "--no-push"]) == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["status"] == "routed"
    for as_json in (True, False):
        argv = ["select", "--query", "snapshot event log", "--skill", "s", "--no-embed"]
        assert cli.main(argv + (["--json"] if as_json else [])) == 0
        output = capsys.readouterr().out
        text = json.loads(output)["lessons"][0]["text"] if as_json else output
        assert captured["id"] in text and first in text
        assert "Restore the snapshot." in text and "Replay the event log." in text
        assert "Only for a stopped database." in text
        if not knowledge:
            assert "After a failed migration" in text


def test_selection_closes_its_ram_database(home, monkeypatch):
    put(home)
    opened = []
    connect = select.sqlite3.connect
    def tracked(*args, **kwargs):
        conn = connect(*args, **kwargs)
        opened.append(conn)
        return conn
    monkeypatch.setattr(select.sqlite3, "connect", tracked)
    assert ids(select.select_lessons(home, "Docker", provider=None))
    assert len(opened) == 1
    with pytest.raises(select.sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
