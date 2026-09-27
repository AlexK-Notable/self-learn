"""U2 · the lesson index and related-lesson search (``self_learn.index``;
02-schema.md §3a.7).

Fake providers only: no test reaches Google. The Gemini client is driven
through an injected ``transport``; its real network seam refuses under
pytest, and a test below proves that refusal. Key values are assembled at
run time so no literal here is secret-shaped.
"""

from __future__ import annotations

import json
import math
import random
import urllib.error
from pathlib import Path

import pytest

from self_learn import cli
from self_learn.index import gemini, registry
from self_learn.index.fake import FakeEmbeddingProvider
from self_learn.index.related import BUCKET_SIMILAR, SESSION, group_for_steward, related
from self_learn.index.store import HYBRID, LEXICAL_ONLY, LessonIndex, index_path
from self_learn.records import Record

S1 = "11111111-aaaa-bbbb-cccc-000000000001"
S2 = "22222222-aaaa-bbbb-cccc-000000000002"
S3 = "33333333-aaaa-bbbb-cccc-000000000003"


# ------------------------------------------------------------ builders


def _fake_key() -> str:
    return "-".join(["not", "a", "real", "key"])


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    for var in gemini.KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv(registry.PROVIDER_ENV, raising=False)


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    h = tmp_path / "ledger"
    for sub in ("skills", "projects", "user"):
        (h / sub).mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return h


def _bucket_dir(home: Path, bucket: str) -> Path:
    scope, _, name = bucket.partition(":")
    if scope == "skill":
        return home / "skills" / name
    if scope == "project":
        return home / "projects" / name
    return home / "user"


def put(home: Path, rid: str, *, bucket: str = "user", trigger: str = "About to do a thing.",
        instruction: str = "Do it carefully.", evidence: list | None = None,
        status_dir: str = "pending") -> Path:
    scope = {"skill": f"skill:{bucket.partition(':')[2]}", "project": "project"}.get(
        bucket.partition(":")[0], "user")
    record = Record.create(
        type="behavior", scope=scope, source="teach", kind="anti-pattern",
        trigger=trigger, instruction=instruction, evidence=evidence or [], record_id=rid,
    )
    folder = _bucket_dir(home, bucket) / status_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{rid}.md"
    record.write(path)
    return path


def sess(session: str, line: int = 5) -> dict:
    return {"session": session, "origin": f"transcript:{session}#L{line}", "quote": "q"}


VOCAB = ("docker", "lights", "keyboard", "backup", "shell")


class TopicProvider:
    """Vectors from topic-word counts: texts about the same topic have
    cosine near 1, different topics near 0."""

    def __init__(self, tag: str = "v1") -> None:
        self.dim = len(VOCAB) + 1
        self.model_id = f"topic-{tag}"
        self.calls: list[str] = []

    def embed(self, texts):
        self.calls.extend(texts)
        out = []
        for t in texts:
            low = t.lower()
            v = [float(low.count(w)) for w in VOCAB] + [0.05]
            n = math.sqrt(sum(x * x for x in v))
            out.append([x / n for x in v])
        return out


def built(home: Path, provider=None) -> LessonIndex:
    ix = LessonIndex.open(home)
    ix.build(provider)
    return ix


# ------------------------------------------------------ incremental build


def test_incremental_rebuild_embeds_only_what_changed_and_drops_the_deleted(home):
    put(home, "lrn-00000001", trigger="About to restart docker.")
    put(home, "lrn-00000002", trigger="About to dim the lights.")
    gone = put(home, "lrn-00000003", trigger="About to flash the keyboard.")
    fake = FakeEmbeddingProvider()
    ix = LessonIndex.open(home)

    first = ix.build(fake)
    assert sorted(first.embedded) == ["lrn-00000001", "lrn-00000002", "lrn-00000003"]
    assert first.mode == HYBRID

    second = ix.build(fake)
    assert second.embedded == [] and second.added == [] and second.changed == []
    assert len(fake.calls) == 3

    put(home, "lrn-00000002", trigger="About to dim the lights.", instruction="Use the scene.")
    gone.unlink()
    third = ix.build(fake)
    assert third.changed == ["lrn-00000002"]
    assert third.embedded == ["lrn-00000002"]
    assert third.removed == ["lrn-00000003"]
    assert sorted(ix.docs()) == ["lrn-00000001", "lrn-00000002"]
    assert ix.conn.execute("SELECT COUNT(*) FROM lesson_vectors WHERE id = 'lrn-00000003'").fetchone()[0] == 0
    assert ix.conn.execute("SELECT COUNT(*) FROM lessons_fts WHERE id = 'lrn-00000003'").fetchone()[0] == 0
    assert ix.mode() == (HYBRID, "")


def test_every_status_is_indexed_and_evidence_quotes_are_in_the_text(home):
    put(home, "lrn-0000000a", evidence=[{"session": S1, "quote": "the zebra quote"}])
    put(home, "lrn-0000000b", status_dir="resolved")
    ix = built(home)
    docs = ix.docs()
    assert sorted(docs) == ["lrn-0000000a", "lrn-0000000b"]
    assert "zebra" in docs["lrn-0000000a"].text


def test_a_model_change_re_embeds_everything_and_never_mixes_models(home):
    put(home, "lrn-00000001")
    put(home, "lrn-00000002", trigger="Something else entirely.")
    old, new = FakeEmbeddingProvider(seed=0), FakeEmbeddingProvider(seed=1)
    ix = built(home, old)
    report = ix.build(new)
    assert sorted(report.embedded) == ["lrn-00000001", "lrn-00000002"]
    assert ix.model_id() == new.model_id
    assert ix.vectors.stored_model_ids() == {new.model_id}
    assert ix.mode() == (HYBRID, "")


# ------------------------------------------------------------ degradation


def test_no_key_means_lexical_only_and_says_why(home):
    put(home, "lrn-00000001")
    ix = LessonIndex.open(home)
    report = ix.build()  # provider chosen from the environment: no key
    assert report.mode == LEXICAL_ONLY
    assert "no Gemini API key" in report.mode_reason
    status = ix.status()
    assert status["mode"] == LEXICAL_ONLY
    assert "no Gemini API key" in status["mode_reason"]
    assert status["key_present"] is False


def test_a_failing_api_means_lexical_only_not_an_error(home):
    put(home, "lrn-00000001")

    def refuse(action, body, timeout):
        raise urllib.error.HTTPError("https://example.invalid", 403, "forbidden", {}, None)  # type: ignore[arg-type]

    provider = gemini.GeminiEmbedder(api_key=_fake_key(), rpm=0, transport=refuse, dim=4)
    ix = LessonIndex.open(home)
    report = ix.build(provider)
    assert report.mode == LEXICAL_ONLY
    assert "embedding failed" in report.embed_error
    assert "embedding failed" in ix.status()["mode_reason"]


def test_the_self_learn_key_variable_is_read_first(monkeypatch):
    own, general = _fake_key() + "-own", _fake_key() + "-general"
    monkeypatch.setenv("GEMINI_API_KEY", general)
    monkeypatch.setenv("SELF_LEARN_GEMINI_API_KEY", own)
    assert gemini.GeminiEmbedder(rpm=0)._key == own
    monkeypatch.setenv("SELF_LEARN_GEMINI_API_KEY", "")
    assert gemini.GeminiEmbedder(rpm=0)._key == general
    monkeypatch.delenv("GEMINI_API_KEY")
    assert registry.load_provider()[0] is None


def test_the_gemini_client_refuses_a_real_call_under_pytest():
    client = gemini.GeminiEmbedder(api_key=_fake_key(), rpm=0)
    with pytest.raises(gemini.GeminiEmbedError, match="pytest"):
        client.embed(["hello"])
    assert client.stats["requests"] == 1 and client.stats["retries"] == 0


def test_a_faked_transport_batches_at_the_api_cap_and_keeps_order():
    requests: list[int] = []

    def transport(action, body, timeout):
        reqs = body["requests"]
        requests.append(len(reqs))
        return {"embeddings": [
            {"values": [float(len(r["content"]["parts"][0]["text"])), 1.0, 0.0, 0.0]} for r in reqs
        ]}

    client = gemini.GeminiEmbedder(api_key=_fake_key(), rpm=0, transport=transport, dim=4)
    texts = ["x" * (i + 1) for i in range(150)]
    vecs = client.embed(texts)
    assert sorted(requests) == [50, 100]
    lengths = [len(gemini.format_document_text(t)) for t in texts]
    assert [round(v[0] / v[1]) for v in vecs] == lengths


# ------------------------------------------------------------ relatedness


def test_related_by_a_shared_session_across_buckets(home):
    put(home, "lrn-00000001", bucket="skill:ha", evidence=[sess(S1)])
    put(home, "lrn-00000002", bucket="project:p", trigger="Unrelated words.", evidence=[sess(S1, 9)])
    put(home, "lrn-00000003", bucket="project:p", evidence=[sess(S2)])
    ix = built(home)
    r = related(ix, "lrn-00000001", "lrn-00000002")
    assert r.related and r.reasons == (SESSION,) and r.shared_sessions == (S1,)
    assert not r.same_bucket
    assert not related(ix, "lrn-00000001", "lrn-00000003").related


def test_related_by_the_legacy_origin_alone(home):
    put(home, "lrn-00000001", bucket="skill:a",
        evidence=[{"origin": f"transcript:{S3}#L2", "quote": "q"}])
    put(home, "lrn-00000002", bucket="skill:b", trigger="Other.",
        evidence=[{"origin": f"transcript:{S3}#L80", "quote": "q"}])
    ix = built(home)
    assert related(ix, "lrn-00000001", "lrn-00000002").reasons == (SESSION,)


def test_related_by_one_moment_copied_into_a_forked_session(home):
    def ref(session: str, uuid: str) -> dict:
        return {"ref": {"session": session, "project_dir": "-w", "line": 3, "uuid": uuid,
                        "entry_ts": None, "cwd": None, "role": "user"}, "quote": "q"}

    put(home, "lrn-00000001", bucket="skill:a", evidence=[ref(S1, "u-same")])
    put(home, "lrn-00000002", bucket="skill:b", trigger="Other.", evidence=[ref(S2, "u-same")])
    put(home, "lrn-00000003", bucket="skill:b", trigger="Other.", evidence=[ref(S3, "u-else")])
    ix = built(home)
    r = related(ix, "lrn-00000001", "lrn-00000002")
    assert r.related and r.shared_uuids == ("u-same",) and r.shared_sessions == ()
    assert not related(ix, "lrn-00000001", "lrn-00000003").related


def test_related_by_bucket_and_meaning_with_embeddings(home):
    put(home, "lrn-00000001", trigger="About to restart docker.", instruction="Check docker logs.")
    put(home, "lrn-00000002", trigger="A docker container dies.", instruction="Read docker events.")
    put(home, "lrn-00000003", trigger="About to dim the lights.", instruction="Use lights scenes.")
    ix = built(home, TopicProvider())
    r = related(ix, "lrn-00000001", "lrn-00000002", cosine_threshold=0.8)
    assert r.related and r.reasons == (BUCKET_SIMILAR,) and r.basis == "cosine"
    far = related(ix, "lrn-00000001", "lrn-00000003", cosine_threshold=0.8)
    assert far.same_bucket and far.similarity is not None and not far.related


def _filler(home: Path, n: int = 12) -> None:
    """Unrelated records in other buckets: BM25 weighs a word by how rare
    it is, and in a three-record corpus every shared word is common (FTS5
    clamps its weight to ~0). The live ledger holds hundreds."""
    words = ("apple", "violin", "harbor", "quartz", "meadow", "falcon", "copper",
             "lantern", "glacier", "orchid", "saddle", "tundra")
    for i in range(n):
        put(home, f"lrn-f000{i:04d}", bucket=f"skill:filler{i}",
            trigger=f"{words[i % len(words)]} notes.", instruction=f"{words[(i + 5) % len(words)]} steps.")


def test_related_by_bucket_and_words_when_lexical_only(home):
    _filler(home)
    put(home, "lrn-00000001", trigger="About to restart the docker daemon on the build host.",
        instruction="Check the docker daemon journal first.")
    put(home, "lrn-00000002", trigger="The docker daemon on the build host will not restart.",
        instruction="Read the docker daemon journal.")
    put(home, "lrn-00000003", trigger="Dimming bedroom lamps at night.",
        instruction="Prefer a scene over brightness steps.")
    ix = built(home)
    assert ix.mode()[0] == LEXICAL_ONLY
    near = related(ix, "lrn-00000001", "lrn-00000002")
    assert near.related and near.basis == "lexical" and near.reasons == (BUCKET_SIMILAR,)
    assert not related(ix, "lrn-00000001", "lrn-00000003").related


def test_the_same_name_in_two_scopes_is_not_one_bucket(home):
    text = dict(trigger="About to restart docker.", instruction="Check docker logs.")
    put(home, "lrn-00000001", bucket="skill:shared", **text)
    put(home, "lrn-00000002", bucket="project:shared", **text)
    put(home, "lrn-00000003", bucket="skill:shared", **text)
    ix = built(home, TopicProvider())
    # positive control: the same text inside one bucket IS related
    assert related(ix, "lrn-00000001", "lrn-00000003", cosine_threshold=0.8).related
    cross = related(ix, "lrn-00000001", "lrn-00000002", cosine_threshold=0.8)
    assert not cross.same_bucket and not cross.related


def test_a_model_with_no_measured_threshold_falls_back_to_lexical(home):
    put(home, "lrn-00000001", trigger="About to restart docker.")
    put(home, "lrn-00000002", trigger="About to dim the lights.")
    ix = built(home, TopicProvider())
    assert ix.mode()[0] == HYBRID
    assert related(ix, "lrn-00000001", "lrn-00000002").basis == "lexical"
    assert related(ix, "lrn-00000001", "lrn-00000002", cosine_threshold=0.8).basis == "cosine"


# --------------------------------------------------------------- grouping


def test_a_same_session_cluster_over_ten_is_split_within_the_cap(home):
    ids = [f"lrn-000001{n:02d}" for n in range(12)]
    for n, rid in enumerate(ids):
        put(home, rid, bucket=f"skill:s{n}", trigger=f"Distinct subject {n}.", evidence=[sess(S1, n + 1)])
    g = group_for_steward(ids, index=built(home))
    assert [len(x.members) for x in g.groups] == [10, 2]
    assert all(x.unrelated == () for x in g.groups)
    assert sorted(m for x in g.groups for m in x.members) == ids


def test_unrelated_lessons_are_capped_at_five_per_group(home):
    ids = [f"lrn-000002{n:02d}" for n in range(25)]
    for n, rid in enumerate(ids):
        put(home, rid, bucket=f"skill:s{n}", trigger=f"Subject {n}.", evidence=[sess(f"{n:08d}-x")])
    g = group_for_steward(ids, index=built(home))
    assert [len(x.members) for x in g.groups] == [5, 5, 5, 5, 5]
    assert all(len(x.unrelated) == 5 for x in g.groups)


def test_related_blocks_fill_groups_before_unrelated_ones(home):
    block = ["lrn-00000301", "lrn-00000302", "lrn-00000303"]
    singles = [f"lrn-000004{n:02d}" for n in range(8)]
    for n, rid in enumerate(block):
        put(home, rid, bucket=f"skill:b{n}", evidence=[sess(S2, n + 1)])
    for n, rid in enumerate(singles):
        put(home, rid, bucket=f"skill:u{n}", evidence=[sess(f"{n:08d}-y")])
    g = group_for_steward(block + singles, index=built(home))
    assert [len(x.members) for x in g.groups] == [8, 3]
    assert g.groups[0].members[:3] == tuple(block)
    assert [len(x.unrelated) for x in g.groups] == [5, 3]
    assert all(len(x.members) <= 10 and len(x.unrelated) <= 5 for x in g.groups)


def test_grouping_is_deterministic(home):
    ids = [f"lrn-000005{n:02d}" for n in range(14)]
    for n, rid in enumerate(ids):
        session = S1 if n % 3 == 0 else f"{n:08d}-z"
        put(home, rid, bucket=f"skill:d{n}", trigger=f"Topic {n}.", evidence=[sess(session, n + 1)])
    ix = built(home)
    first = group_for_steward(ids, index=ix).to_json()
    shuffled = ids + ids[:4]
    random.Random(7).shuffle(shuffled)
    assert group_for_steward(shuffled, index=ix).to_json() == first


# -------------------------------------------------------------------- CLI


def _run(capsys, *argv: str) -> tuple[int, dict]:
    rc = cli.main(list(argv))
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_cli_json_shapes(home, capsys):
    put(home, "lrn-00000001", evidence=[sess(S1)])
    put(home, "lrn-00000002", bucket="skill:x", trigger="Something else.", evidence=[sess(S1, 8)])

    rc, before = _run(capsys, "index", "status", "--json")
    assert rc == 0 and before["built"] is False
    assert not index_path(home).parent.exists()  # a status read creates nothing

    rc, build = _run(capsys, "index", "build", "--json", "--no-embed")
    assert rc == 0
    assert {"added", "changed", "removed", "embedded", "unreadable", "model", "embed_error",
            "mode", "mode_reason"} <= set(build)
    assert build["added"] == 2 and build["mode"] == LEXICAL_ONLY

    rc, status = _run(capsys, "index", "status", "--json")
    assert rc == 0
    assert status["built"] is True and status["records"] == 2
    assert status["mode"] == LEXICAL_ONLY and status["mode_reason"]
    assert status["model"] is None and status["last_build_at"]
    assert status["vectors"] == {"current": 0, "missing": 2}
    assert status["stale"] == {"not_indexed": 0, "changed": 0, "gone": 0}
    assert status["by_status"] == {"pending": 2} and status["buckets"] == 2

    put(home, "lrn-00000003", trigger="New one.")
    rc, status = _run(capsys, "index", "status", "--json")
    assert status["stale"]["not_indexed"] == 1

    rc, rel = _run(capsys, "index", "related", "lrn-00000001", "--json")
    assert rc == 0 and rel["id"] == "lrn-00000001" and rel["basis"] == "lexical"
    assert [r["b"] for r in rel["related"]] == ["lrn-00000002"]
    assert rel["related"][0]["reasons"] == [SESSION]
    assert rel["nearest"]["mode"] == LEXICAL_ONLY

    rc, groups = _run(capsys, "index", "groups", "--json")
    assert rc == 0 and groups["queued"] == 3 and groups["basis"] == "lexical"
    assert groups["groups"] == [{
        "members": ["lrn-00000001", "lrn-00000002", "lrn-00000003"],
        "unrelated": ["lrn-00000003"],
        "links": [rel["related"][0]],
    }]
