"""R1b synthetic tools and look-alike acceptance; no model/network calls."""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from self_learn import provenance
from self_learn.index import textquery
from self_learn.index.store import LessonIndex
from self_learn.mining import tools
from self_learn.records import Record


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "ledger"
    path.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    return path


def entry(role, content, **kwargs):
    return {"type": role, "message": {"content": content}, **kwargs}


def transcript(path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


def put(home, rid="lrn-00000001", *, trigger="docker restart container", instruction="inspect docker logs",
        scope="user", bucket="user", status="pending", successor=None, quote="original observation",
        fact=None, context=None):
    record = Record.create(type="knowledge" if fact else "behavior", scope=scope,
                           source="teach", kind=None if fact else "anti-pattern", trigger=trigger,
                           instruction=instruction, fact=fact, context=context, record_id=rid,
                           evidence=[{"quote": quote}])
    record.set_status(status)
    if status in ("routed", "superseded"):
        record.set_routing({"routed_at": "2026-01-01T00:00:00Z", "by": "user", "destination": "CLAUDE.md"})
    if successor:
        record.set_superseded_by(successor)
    folder = home / bucket / ("pending" if status == "pending" else "resolved")
    folder.mkdir(parents=True, exist_ok=True)
    record.write(folder / f"{rid}.md")
    return record


class Provider:
    model_id = "test-model"
    dim = 2

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        return [[1.0, 0.0] if "docker" in t else [0.0, 1.0] for t in texts]

    def embed_query(self, texts):
        raise AssertionError("must use document form")


def built(home, provider=None):
    index = LessonIndex.open(home)
    index.build(provider)
    return index


def invoke(toolset, name, **args):
    tool = next(t for t in toolset.tools if t.name == name)
    return asyncio.run(tool.handler(args))


def kit(tmp_path, home, entries, subagents=None, end=None, sent=None, provider=None):
    path = transcript(tmp_path / "main.jsonl", entries)
    return tools.build_toolset(path, subagents or {}, len(entries) if end is None else end,
                               home, sent=sent, provider=provider)


def token():
    return "ghp_" + "Ab12" * 10


def test_t1_definitions_pin():
    canonical = json.dumps(tools.TOOL_DEFINITIONS, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == "195ffd5a40749860b3213f3476c999b619ad7eed700d401bdbe6fb564463fd01"


def test_method_pin_and_required_parts():
    path = Path(__file__).resolve().parents[2] / "skills/self-learn/references/miner-method.md"
    method = path.read_text()
    assert hashlib.sha256(method.encode()).hexdigest() == "d855e01eda3925479fcd73c0715884327451e94978132468bf5d795f6b0f4f98"
    assert method.startswith("<!-- method-version: 1 -->")
    for text in ("within this session", "verification.how", "incident_cost.text", "## Context",
                 "AGENT-WRITTEN", "bad-brief", "left-brief", "unchecked-report", "FLAG",
                 "suspected-compliance", "suspected-violation", "cannot-tell", "each one line"):
        assert text in method
    assert "Confidence" not in method


def test_t2_stretch_pages_physical_lines_and_judged_end(tmp_path, home):
    entries = [entry("user", "first"), None] + [entry("assistant", f"message-{n}: " + "ordinary prose " * 400 + " tail") for n in range(15)]
    entries += [entry("user", "second"), entry("assistant", "after judged end")]
    ts = kit(tmp_path, home, entries, end=18)
    path = tmp_path / "main.jsonl"
    path.write_text(path.read_text().replace("\nnull\n", "\n{malformed JSON\n"))
    first = invoke(ts, "open_stretch", after_turn=1)
    assert not first.is_error and "L3 AGENT: message-0:" in first.text and "tail" in first.text
    assert "page 1 of 3" in first.text
    pages = [first] + [invoke(ts, "open_stretch", after_turn=1, page=p) for p in (2, 3)]
    assert all(len(p.text) <= 24000 and not p.is_error for p in pages)
    assert "end of stretch (T2 at L18)" in pages[-1].text
    assert "L17 AGENT: message-14" in pages[-1].text
    last = invoke(ts, "open_stretch", after_turn=2)
    assert last.text == "end of stretch (end of judged range)"
    assert invoke(ts, "open_stretch", after_turn=3).is_error
    assert invoke(ts, "open_stretch", after_turn=1, page=4).is_error


@pytest.mark.parametrize("name,args", [
    ("open_stretch", {"after_turn": -1}), ("open_stretch", {"after_turn": True}),
    ("open_stretch", {"after_turn": 0, "page": 0}), ("open_stretch", {"after_turn": 0, "extra": 1}),
    ("find_similar_lessons", {"draft": "short"}), ("find_similar_lessons", {"draft": "x" * 2001}),
    ("search_subagent", {"subagent": "../escape", "query": "ok"}),
    ("search_subagent", {"subagent": "a", "query": "x"}),
])
def test_invalid_arguments(tmp_path, home, name, args):
    ts = kit(tmp_path, home, [])
    result = invoke(ts, name, **args)
    assert result.is_error and result.text == f"invalid arguments for {name}"


def test_tools_results_edges_redaction_and_launch_link(tmp_path, home):
    prompt = "inspect the synthetic failure"
    sub = transcript(tmp_path / "agent-a.jsonl", [entry("user", prompt), entry("assistant", "report start\nreport end")])
    es = [entry("assistant", "preamble"), entry("user", "start"),
          entry("assistant", [{"type": "tool_use", "name": "Bash", "id": "b", "input": {"command": "echo " + token()}},
                              {"type": "tool_use", "name": "Edit", "id": "e", "input": {"file_path": "synthetic.py"}},
                              {"type": "tool_use", "name": "Agent", "id": "a", "input": {"prompt": prompt + " transformed"}}]),
          entry("user", [{"type": "tool_result", "tool_use_id": "b", "content": "first\nmiddle hidden\nlast", "is_error": True}]),
          entry("user", [{"type": "tool_result", "tool_use_id": "a", "content": "finished"}], toolUseResult={"agentId": "a"}),
          entry("user", "relay data", isMeta=True)]
    ts = kit(tmp_path, home, es, {"a": sub})
    assert "L1 AGENT: preamble" in invoke(ts, "open_stretch", after_turn=0).text
    reply = invoke(ts, "open_stretch", after_turn=1)
    assert not reply.is_error and "L3 TOOL Bash: echo [redacted:" in reply.text
    assert token() not in reply.text
    assert "FAILED (L4 TOOL_RESULT): first ⋯ last" in reply.text
    assert "middle hidden" not in reply.text
    assert "TOOL Edit: synthetic.py → pending" in reply.text
    assert "L3 SUBAGENT a: brief inspect" in reply.text and "report start" in reply.text
    assert "L6 RELAY: relay data" in reply.text
    # No id field: exact prompt fallback must still link.
    es[4].pop("toolUseResult")
    es[2]["message"]["content"][2]["input"]["prompt"] = prompt
    ts = kit(tmp_path, home, es, {"a": sub})
    assert "L3 SUBAGENT a:" in invoke(ts, "open_stretch", after_turn=1).text


def test_t3_lookup_no_mask_and_metadata(tmp_path, home):
    put(home, quote="first quote " + token())
    with_index = built(home)
    with_index.close()
    ts = kit(tmp_path, home, [])
    result = invoke(ts, "find_similar_lessons", draft="docker restart container logs")
    assert not result.is_error and result.text.startswith("search: word match only (")
    assert "lrn-00000001 [pending] (user/user) placed: not placed" in result.text
    assert "Trigger: docker restart container" in result.text
    assert "Instruction: inspect docker logs" in result.text and "first quote [redacted:" in result.text
    assert token() not in result.text


def test_t4_subagent_search_bounds_fts_cache_and_redaction(tmp_path, home, monkeypatch):
    sub = transcript(tmp_path / "agent-a.jsonl", [entry("user", "brief " + "ordinary brief words " * 150)] +
                     [entry("assistant", "before needle phrase " + token() + " after") for _ in range(30)] +
                     [entry("assistant", "report " + "ordinary report words " * 150)])
    ts = kit(tmp_path, home, [], {"a": sub})
    unknown = invoke(ts, "search_subagent", subagent="b", query="needle")
    assert unknown.is_error and unknown.text == "unknown subagent; valid ids: a"
    quoted = invoke(ts, "search_subagent", subagent="a", query='"NEEDLE PHRASE"')
    assert not quoted.is_error and "BRIEF: L1" in quoted.text and "REPORT: L32" in quoted.text
    assert len(quoted.text) <= 12000 and quoted.text.count(" / AGENT: …") == 20
    assert "[redacted:" in quoted.text and token() not in quoted.text
    assert len(quoted.text.splitlines()[0].split(" / YOU: ", 1)[1]) == 1500
    assert len(quoted.text.splitlines()[1].split(" / AGENT: ", 1)[1]) == 1500
    monkeypatch.setattr(tools, "read_entries", lambda *a: pytest.fail("subagent log read twice"))
    words = invoke(ts, "search_subagent", subagent="a", query="needles absentword")
    assert not words.is_error and words.text.count(" / AGENT: …") == 20


def test_t5_index_connection_owned_by_worker_thread(tmp_path, home):
    put(home)
    index = built(home)
    index.close()
    ts = kit(tmp_path, home, [])
    answers = []
    thread = threading.Thread(target=lambda: answers.append(invoke(ts, "find_similar_lessons", draft="docker restart container logs")))
    thread.start()
    thread.join(timeout=5)
    assert len(answers) == 1 and not answers[0].is_error
    assert "lrn-00000001" in answers[0].text


def test_t6_textquery_exclusion_hybrid_and_document_form(home):
    put(home)
    put(home, "lrn-00000002", trigger="keyboard switches", instruction="replace keyboard switch")
    provider = Provider()
    index = built(home, provider)
    try:
        provider.calls.clear()
        result = textquery.nearest_text(index, "docker restart container", provider=provider)
        assert result.mode == "hybrid" and result.hits[0].id == "lrn-00000001"
        assert result.hits[0].cosine == 1.0 and len(provider.calls) == 1
        assert provider.calls[0] == ["docker restart container"]
        excluded = textquery.nearest_text(index, "docker restart container", exclude_ids=frozenset({"lrn-00000001"}), provider=provider)
        assert [hit.id for hit in excluded.hits] == ["lrn-00000002"]
    finally:
        index.close()


@pytest.mark.parametrize("failure,reason", [("timeout", "embedding timed out"), ("error", "embedding failed"),
                                             ("dimension", "embedding failed"), ("model", "embedding model differs"),
                                             ("none", "no embedding provider given")])
def test_t6_degradation(home, monkeypatch, failure, reason):
    put(home)
    provider = Provider()
    index = built(home, provider)
    try:
        if failure == "timeout":
            monkeypatch.setattr(textquery, "EMBED_TIMEOUT", 0.01)
            monkeypatch.setattr(provider, "embed", lambda texts: (time.sleep(0.1) or [[1.0, 0.0]]))
        elif failure == "error":
            monkeypatch.setattr(provider, "embed", lambda texts: (_ for _ in ()).throw(ValueError(token())))
        elif failure == "dimension":
            monkeypatch.setattr(provider, "embed", lambda texts: [[1.0]])
        elif failure == "model":
            provider.model_id = "other"
        elif failure == "none":
            provider = None
        result = textquery.nearest_text(index, "docker restart container", provider=provider)
        assert result.hits[0].id == "lrn-00000001"
        assert result.mode == "lexical-only" and reason in result.note and token() not in result.note
    finally:
        index.close()


def test_t7_supersession_chain_cycles_and_retirement(tmp_path, home):
    put(home, status="superseded", successor="lrn-00000002")
    put(home, "lrn-00000002", status="superseded", successor="lrn-00000003")
    put(home, "lrn-00000003", trigger="unrelated replacement wording", instruction="take the replacement action", status="routed")
    put(home, "lrn-00000004", status="superseded", successor="lrn-00000005")
    put(home, "lrn-00000005", status="superseded", successor="lrn-00000004")
    put(home, "lrn-00000006", status="superseded", successor="lrn-00000009")
    index = built(home)
    index.close()
    result = invoke(kit(tmp_path, home, []), "find_similar_lessons", draft="docker restart container logs")
    assert not result.is_error and "lrn-00000003 [routed]" in result.text
    assert "placed: CLAUDE.md" in result.text
    assert result.text.count("lrn-") == 1
    assert "superseded" not in result.text


def test_t8_parallel_handlers_do_not_stall_event_loop(tmp_path, home, monkeypatch):
    started, release = threading.Event(), threading.Event()
    def slow(self, draft):
        started.set()
        assert release.wait(2), "event loop stalled behind synchronous handler"
        return "search: word match only (synthetic sleep)"
    monkeypatch.setattr(tools.SessionTools, "find_similar_lessons", slow)
    ts = kit(tmp_path, home, [entry("assistant", "parallel answer")])
    async def run():
        slow_task = asyncio.create_task(ts.tools[1].handler({"draft": "docker restart container"}))
        while not started.is_set():
            await asyncio.sleep(0.001)
        try:
            fast = await ts.tools[0].handler({"after_turn": 0})
            assert "parallel answer" in fast.text
        finally:
            release.set()
        assert not (await slow_task).is_error
    asyncio.run(run())


def test_t9_agent_written_labels_tagged_and_sent(tmp_path, home):
    body = "A synthetic dispatched brief long enough to exercise sent matching without the short-text rule."
    sent = provenance.SentIndex([provenance.Send(10.0, "sender", body, provenance.fold(body))])
    es = [entry("user", "person"), entry("user", "<agent-message>delegated brief</agent-message>"),
          entry("user", body, timestamp="1970-01-01T00:00:11Z", sessionId="receiver"), entry("assistant", "done")]
    sub = transcript(tmp_path / "agent-a.jsonl", es[1:])
    ts = kit(tmp_path, home, es, {"a": sub}, sent=sent)
    stretch = invoke(ts, "open_stretch", after_turn=1)
    assert "L2 AGENT-WRITTEN: <agent-message>" in stretch.text
    assert "L3 AGENT-WRITTEN: A synthetic" in stretch.text
    assert "YOU:" not in stretch.text and "end of judged range" in stretch.text
    search = invoke(ts, "search_subagent", subagent="a", query="brief")
    assert "BRIEF: L1 SUBAGENT a / AGENT-WRITTEN:" in search.text
    assert "L2 SUBAGENT a / AGENT-WRITTEN:" in search.text
    assert " / YOU:" not in search.text


def test_lookup_empty_index_and_five_bounded_hits(tmp_path, home):
    ts = kit(tmp_path, home, [])
    assert invoke(ts, "find_similar_lessons", draft="docker restart container").text == "search: word match only (index not built)"
    for n in range(1, 8):
        put(home, f"lrn-{n:08x}", trigger="docker " * 500, instruction="logs " * 500)
    index = built(home)
    index.close()
    result = invoke(ts, "find_similar_lessons", draft="docker restart container")
    assert not result.is_error and result.text.count("[pending]") == 5
    assert len(result.text) <= 10000
    assert all(len(part) <= 1800 for part in result.text.split("\n\n")[1:])


def test_work_documents_exclude_person_and_relay(tmp_path):
    es = [entry("user", "person secret"), entry("user", "relay secret", isMeta=True),
          entry("user", "<agent-message>brief secret</agent-message>"),
          entry("assistant", [{"type": "tool_use", "name": "Bash", "input": {"command": "docker restart " + token()}},
                               {"type": "text", "text": "working text"}]),
          entry("user", [{"type": "tool_result", "content": "first\ninterior\nlast"}])]
    stretches = tools.stretches(es)
    assert len(stretches) == 2 and stretches[1].after_turn == 1
    text = stretches[1].text
    assert "Bash\ndocker restart [redacted:" in text and "working text" in text and "first ⋯ last" in text
    assert not any(word in text for word in ("person", "relay", "brief", "interior", token()))


def test_lookup_knowledge_and_provider_redaction(tmp_path, home):
    put(home, fact="docker fact", context="container context", status="routed")
    provider = Provider()
    index = built(home, provider)
    try:
        provider.calls.clear()
        result = textquery.nearest_text(index, "docker context " + token(), provider=provider)
        assert result.mode == "hybrid" and result.hits
        assert "[redacted:" in provider.calls[0][0] and token() not in provider.calls[0][0]
    finally:
        index.close()
    response = invoke(kit(tmp_path, home, [], provider=provider), "find_similar_lessons", draft="docker container context")
    assert response.text.startswith("search: hybrid")
    assert "Fact: docker fact" in response.text and "Context: container context" in response.text


def test_stretch_adversarial_fields_stay_bounded(tmp_path, home):
    es = [entry("assistant", [{"type": "tool_use", "name": "long name " * 10000, "id": "a", "input": {"text": "ordinary words " * 2000}}])]
    reply = invoke(kit(tmp_path, home, es), "open_stretch", after_turn=0)
    assert not reply.is_error and reply.text.startswith("L1 TOOL long name")
    assert len(reply.text) <= 24000 and reply.text.endswith("end of stretch (end of judged range)")


def test_main_read_never_crosses_judged_end(tmp_path, home):
    es = [entry("user", "start"), entry("assistant", [{"type": "tool_use", "name": "Bash", "id": "a", "input": {"command": "echo safe"}}]),
          entry("user", [{"type": "tool_result", "tool_use_id": "a", "content": "future output"}])]
    reply = invoke(kit(tmp_path, home, es, end=2), "open_stretch", after_turn=1)
    assert "TOOL Bash: echo safe → pending" in reply.text
    assert "future output" not in reply.text and "L3" not in reply.text


def test_errors_redacted_one_line(tmp_path, home, monkeypatch):
    def failure(self, draft):
        raise ValueError("synthetic " + token() + "\nsecond line")
    monkeypatch.setattr(tools.SessionTools, "find_similar_lessons", failure)
    reply = invoke(kit(tmp_path, home, []), "find_similar_lessons", draft="docker restart container")
    assert reply.is_error and reply.text.startswith("synthetic [redacted:")
    assert token() not in reply.text and "\n" not in reply.text
