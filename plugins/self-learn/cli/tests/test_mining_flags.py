"""Situation flags use routed rules, work text, scope and separate score bars."""
from __future__ import annotations

from pathlib import Path

from self_learn import hosts
from self_learn.mining import flags, tools
from test_mining_tools import Provider, built, entry, home, put, token


def work(text="docker restart container", count=1):
    return [tools.Stretch(n, n * 10 + 2, n * 10 + 9, text) for n in range(count)]


def test_f1_trigger_work_flag_and_status(home):
    put(home, status="routed")
    put(home, "lrn-00000002", status="pending")
    put(home, "lrn-00000003", status="superseded", successor="lrn-00000001")
    index = built(home)
    try:
        result = flags.flag_rules(index, work(), cwd=Path("/synthetic"), provider=None)
        assert result.mode == "lexical-only" and result.note
        assert [(f.record, f.after_turn, f.start_line, f.end_line) for f in result.flags] == [("lrn-00000001", 0, 2, 9)]
        assert result.flags[0].lexical >= 0.30 and result.flags[0].rule == "docker restart container"
        unrelated = flags.flag_rules(index, work("guitar acoustic strings"), cwd=Path("/synthetic"), provider=None)
        assert unrelated.flags == ()
    finally:
        index.close()


def test_f2_project_scope_component_containment_and_unknown(home, tmp_path, monkeypatch):
    project = tmp_path / "project"
    slug = hosts.slug_for(project)
    put(home, scope="project", bucket=f"projects/{slug}", status="routed")
    monkeypatch.setattr(hosts, "load_hosts", lambda home: hosts.Hosts(projects=[project]))
    index = built(home)
    try:
        assert flags.flag_rules(index, work(), cwd=project / "child", provider=None).flags
        assert not flags.flag_rules(index, work(), cwd=tmp_path / "project-other", provider=None).flags
        monkeypatch.setattr(hosts, "load_hosts", lambda home: hosts.Hosts())
        assert flags.flag_rules(index, work(), cwd=tmp_path / "project-other", provider=None).flags
    finally:
        index.close()


def test_f2_skill_scope_tool_and_path(home):
    put(home, scope="skill:inspect", bucket="skills/inspect", status="routed")
    index = built(home)
    try:
        call = entry("assistant", [{"type": "tool_use", "name": "Skill", "input": {"skill": "inspect"}}])
        for e in (call, entry("assistant", "read skills/inspect/SKILL.md")):
            assert flags.flag_rules(index, work(), cwd=Path("/synthetic"), entries=[e], provider=None).flags
        assert not flags.flag_rules(index, work(), cwd=Path("/synthetic"), entries=[], provider=None).flags
        assert not flags.flag_rules(index, work(), cwd=Path("/synthetic"), entries=[entry("assistant", "skills/inspect-other/a")], provider=None).flags
    finally:
        index.close()


def test_f3_caps_and_best_first(home):
    put(home, status="routed")
    index = built(home)
    try:
        single = flags.flag_rules(index, work(count=4), cwd=Path("/synthetic"), provider=None)
        assert len(single.flags) == 2 and {f.after_turn for f in single.flags} == {0, 1}
        for n in range(2, 7):
            put(home, f"lrn-{n:08x}", status="routed")
        index.build(None)
        result = flags.flag_rules(index, work(count=4), cwd=Path("/synthetic"), provider=None)
        assert len(result.flags) == 8
        assert len({f.record for f in result.flags}) == 6
        assert all(sum(f.record == rid for f in result.flags) <= 2 for rid in {f.record for f in result.flags})
        assert [f.score for f in result.flags] == sorted((f.score for f in result.flags), reverse=True)
        assert {f.after_turn for f in result.flags} == {0, 1}
    finally:
        index.close()


def test_hybrid_batch_and_cosine_bar(home):
    put(home, status="routed")
    provider = Provider()
    index = built(home, provider)
    try:
        provider.calls.clear()
        # Same vector through a synthetic provider, no lexical overlap.
        provider.embed = lambda texts: (provider.calls.append(texts) or [[1.0, 0.0] for _ in texts])
        result = flags.flag_rules(index, work("unrelated words", 3), cwd=Path("/synthetic"), provider=provider)
        assert result.mode == "hybrid" and len(result.flags) == 2
        assert len(provider.calls) == 1 and len(provider.calls[0]) == 3
        assert result.flags[0].cosine == 1.0 and result.flags[0].lexical == 0
        provider.embed = lambda texts: [[0.0, 1.0] for _ in texts]
        assert not flags.flag_rules(index, work("unrelated words"), cwd=Path("/synthetic"), provider=provider).flags
    finally:
        index.close()


def test_flag_embedding_failure_lexical_fallback(home):
    put(home, status="routed")
    provider = Provider()
    index = built(home, provider)
    try:
        provider.embed = lambda texts: (_ for _ in ()).throw(ValueError("synthetic failure"))
        result = flags.flag_rules(index, work(), cwd=Path("/synthetic"), provider=provider)
        assert result.flags and result.flags[0].cosine is None
        assert result.mode == "lexical-only" and result.note == "embedding failed: ValueError"
    finally:
        index.close()


def test_knowledge_fact_context_and_redaction(home):
    put(home, status="routed", fact="docker container", context="restart " + token())
    index = built(home)
    try:
        result = flags.flag_rules(index, work(), cwd=Path("/synthetic"), provider=None)
        assert result.flags and "[redacted:" in result.flags[0].rule
        assert "docker container\nrestart" in result.flags[0].rule
        assert token() not in result.flags[0].rule
    finally:
        index.close()


def test_lexical_bar_normalizes_against_query(home, monkeypatch):
    put(home, status="routed")
    index = built(home)
    try:
        # Positive control: this query has a real matching stretch.
        assert flags.flag_rules(index, work(), cwd=Path("/synthetic"), provider=None).flags
        monkeypatch.setattr(flags.fts5, "search", lambda conn, text: [("query", -10.0), ("0", -2.9)])
        assert not flags.flag_rules(index, work(), cwd=Path("/synthetic"), provider=None).flags
        monkeypatch.setattr(flags.fts5, "search", lambda conn, text: [("query", -10.0), ("0", -3.0)])
        result = flags.flag_rules(index, work(), cwd=Path("/synthetic"), provider=None)
        assert result.flags[0].lexical == 0.30
    finally:
        index.close()


def test_flag_no_provider_and_model_mismatch(home):
    put(home, status="routed")
    provider = Provider()
    index = built(home, provider)
    try:
        result = flags.flag_rules(index, work(), cwd=Path("/synthetic"), provider=None)
        assert result.flags and result.mode == "lexical-only" and result.note == "no embedding provider given"
        provider.model_id = "wrong-model"
        result = flags.flag_rules(index, work(), cwd=Path("/synthetic"), provider=provider)
        assert result.flags and result.mode == "lexical-only" and result.note == "embedding model differs from the index"
    finally:
        index.close()


def test_flag_embedding_uses_the_short_interactive_call(home, monkeypatch):
    # Orchestrator fold (gate r1b round 2, finding 2): a timed-out flag embedding
    # must not keep retrying under the bulk policy.
    put(home, status="routed")
    provider = Provider()
    index = built(home, provider)
    seen = []

    def fake(prov, texts, *, interactive=False):
        seen.append(interactive)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(flags, "embed_documents", fake)
    try:
        result = flags.flag_rules(index, work("unrelated words"), cwd=Path("/synthetic"), provider=provider)
        assert result.mode == "hybrid" and seen == [True]
    finally:
        index.close()


def test_empty_work_stretches_do_not_poison_embeddings_or_move_flags(home):
    from self_learn.index.gemini import GeminiEmbedder

    put(home, status="routed")
    provider = Provider()
    index = built(home, provider)
    calls = []

    def strict(texts):
        # Same local preflight that rejected all six real preview batches.
        GeminiEmbedder._require_nonempty(texts)
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    provider.embed = strict
    try:
        positive = flags.flag_rules(index, work("unrelated work"), cwd=Path("/synthetic"), provider=provider)
        assert positive.mode == "hybrid" and positive.flags[0].cosine == 1.0
        calls.clear()
        stretches = [tools.Stretch(0, 1, 1, ""), tools.Stretch(1, 3, 5, "unrelated work"),
                     tools.Stretch(2, 7, 7, " \n\t"), tools.Stretch(3, 9, 12, "other work")]
        result = flags.flag_rules(index, stretches, cwd=Path("/synthetic"), provider=provider)
        assert result.mode == "hybrid" and result.note == ""
        assert calls == [["unrelated work", "other work"]]
        assert {(f.after_turn, f.start_line, f.end_line) for f in result.flags} == {(1, 3, 5), (3, 9, 12)}
        calls.clear()
        empty = flags.flag_rules(index, [stretches[0], stretches[2]], cwd=Path("/synthetic"), provider=provider)
        assert empty.mode == "hybrid" and empty.flags == () and calls == []
    finally:
        index.close()
