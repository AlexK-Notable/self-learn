"""The context packet (attention round 2026-10-31c, design r2 §3.2; §5.1
test 9). Person's-shell tests: the module fixture deletes every agent
marker."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import attention, attention_packet, cli, settings
from support import make_home

TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _synthetic(look_at: list[str], evidence: list[dict]) -> dict:
    item = attention._new_item(  # noqa: SLF001
        "ask.system-change", "q-packet-bounds", title="Bind it?", since=_now(), by="overseer",
        question="Bind oo7-daemon to the session bus?", why="It changes your desktop.",
        look_at=look_at, evidence=evidence,
        options=[{"id": "opt-yes", "label": "Yes", "effect": "approve", "confirm": False,
                  "note": None, "recommended": True, "via": "answer"},
                 {"id": "opt-no", "label": "No", "effect": "decline", "confirm": False,
                  "note": None, "recommended": False, "via": "answer"}],
    )
    return item


def test_packet_bounds_redaction_and_look_at_limits(tmp_path, monkeypatch):
    """Mutations: remove the entry cap -> red; an empty deny list -> red; no
    depth check -> red."""
    home = make_home(tmp_path)
    fake_home = tmp_path / "home"
    (fake_home / ".ssh").mkdir(parents=True)
    (fake_home / ".ssh" / "x").write_text("private", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    secret_file = tmp_path / "files" / "notes.txt"
    secret_file.parent.mkdir(parents=True)
    secret_file.write_text(f"the token is {TOKEN}\n", encoding="utf-8")
    mcp = tmp_path / "files" / ".mcp.json"
    mcp.write_text("{}", encoding="utf-8")
    kept_paths = [str(secret_file)]
    for n in range(5):
        extra = tmp_path / "files" / f"d{n}"
        extra.mkdir()
        kept_paths.append(str(extra))
    look_at = [
        kept_paths[0], str(fake_home / ".ssh" / "x"), str(fake_home), "/etc", str(mcp),
        *kept_paths[1:],
    ]
    evidence = [
        {"kind": "fact", "label": f"synthetic {n}", "value": n, "text": "x" * 3000}
        for n in range(200)
    ]
    item = _synthetic(look_at, evidence)
    monkeypatch.setattr(attention, "collect", lambda _home, **_k: [item])

    packet = attention_packet.build(home, item["id"])
    raw = json.dumps(packet, ensure_ascii=False).encode("utf-8")
    assert len(raw) <= attention_packet.MAX_BYTES
    assert packet["limits"]["bytes"] == len(raw)
    assert len(packet["evidence"]) <= attention_packet.MAX_EVIDENCE
    assert len(packet["more"]) >= 200 - attention_packet.MAX_EVIDENCE
    truncated = packet["limits"]["truncated"]
    assert any(t.startswith("evidence:") for t in truncated)
    # look_at: kept are the five allowed paths; each refusal is named.
    assert packet["look_at"] == kept_paths[:5]
    named = " | ".join(t for t in truncated if t.startswith("look_at:"))
    for dropped in (str(fake_home / ".ssh" / "x"), str(fake_home), "/etc", str(mcp), kept_paths[5]):
        assert f"look_at: {dropped}:" in named, dropped
    # Every text is under the cap.
    for entry in packet["evidence"]:
        for value in entry.values():
            if isinstance(value, str):
                assert len(value) <= attention_packet.MAX_TEXT_CHARS


def test_an_excerpt_holding_a_token_is_redacted(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    secret_file = tmp_path / "files" / "notes.txt"
    secret_file.parent.mkdir(parents=True)
    secret_file.write_text(f"the token is {TOKEN}\n", encoding="utf-8")
    item = _synthetic([str(secret_file)], [{"kind": "fact", "label": "seeded", "value": f"v {TOKEN}"}])
    monkeypatch.setattr(attention, "collect", lambda _home, **_k: [item])
    packet = attention_packet.build(home, item["id"])
    text = json.dumps(packet)
    assert TOKEN not in text
    files = [e for e in packet["evidence"] if e["kind"] == "file"]
    assert files and "[redacted:" in files[0]["excerpt"], "positive control: the file was read"


def test_deny_names_and_paths_are_one_list():
    assert attention_packet.denied_name("token.env")
    assert attention_packet.denied_name("ID_ED25519")
    assert attention_packet.denied_name(".mcp.json")
    assert not attention_packet.denied_name("notes.txt")
    assert "~/.ssh" in attention_packet.SECRET_DENY.paths


def test_the_packet_verb_exit_codes(tmp_path, monkeypatch, capsys):
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    runs = home / "cases" / "runs"
    runs.mkdir(parents=True)
    (runs / "abcd1234.json").write_text(json.dumps({
        "actor": "overseer", "run_id": "abcd1234", "status": "complete",
        "last_attempt_at": (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "week": "2026-10-25", "date": "2026-10-25",
    }), encoding="utf-8")
    report = home / "overseer" / "latest-report.md"
    report.parent.mkdir(parents=True)
    report.write_text("# report\n\n## Hooks\n- none\n\n## Catalogue health\n- fine\n", encoding="utf-8")
    item_id = attention.item_id("decided.overseer-run", "abcd1234")
    assert cli.main(["attention", "packet", item_id, "--json"]) == 0
    packet = json.loads(capsys.readouterr().out)
    assert packet["packet_version"] == 1 and packet["item"]["id"] == item_id
    assert packet["why_you"] and packet["decided"]["by"] == "overseer"
    assert [e["kind"] for e in packet["evidence"]] == ["report"]
    assert "## Hooks" in packet["evidence"][0]["excerpt"]
    assert packet["conversation"]["agent_available"] is True
    assert cli.main(["attention", "packet", "att-000000000000", "--json"]) == 2
    monkeypatch.setattr(attention_packet, "_evidence", lambda *a, **k: 1 / 0)
    assert cli.main(["attention", "packet", item_id, "--json"]) == 1
    assert "could not be built" in capsys.readouterr().err


def test_a_hook_activation_shows_the_hook_script_and_its_registration(tmp_path, monkeypatch):
    """Mutation: drop the hook entry from `_evidence` -> red."""
    from self_learn import ledger_ops, records
    from support import make_env

    env = make_env(tmp_path)
    script = env.host / "hooks" / "self-learn" / "lrn-0000aaaa-guard.sh"
    script.parent.mkdir(parents=True)
    script.write_text(f"#!/bin/sh\n# guard\nexport T={TOKEN}\nexit 2\n", encoding="utf-8")

    class _Fake:
        body = "# Never import-environment bare\n\nThe guard blocks it.\n"
        status = "resolved"
        routing = {"destination": "hook", "hook": {
            "script_path": "hooks/self-learn/lrn-0000aaaa-guard.sh", "event": "PreToolUse",
            "matcher": "Bash"}}

    monkeypatch.setattr(ledger_ops, "find_record_path", lambda home, rid: tmp_path / f"{rid}.md")
    monkeypatch.setattr(records.Record, "from_path", classmethod(lambda cls, path: _Fake()))
    runs = env.ledger / "cases" / "runs"
    runs.mkdir(parents=True)
    at = _now()
    (runs / "run-aaaaaaaaaaaa.json").write_text(json.dumps({
        "actor": "steward", "run_id": "run-aaaaaaaaaaaa", "completed_at": at, "decided": [],
        "attention_effects": [{"lesson": "lrn-0000aaaa", "verb": "route", "destination": "hook",
                               "always_loaded": False, "hook_activated": True, "at": at}],
    }), encoding="utf-8")
    item_id = attention.item_id("decided.hook-activated", f"lrn-0000aaaa@{at}")
    packet = attention_packet.build(env.ledger, item_id)
    hooks = [e for e in packet["evidence"] if e["kind"] == "hook"]
    assert len(hooks) == 1 and hooks[0]["record"] == "lrn-0000aaaa"
    assert "# guard" in hooks[0]["script_excerpt"] and TOKEN not in hooks[0]["script_excerpt"]
    assert '"matcher": "Bash"' in hooks[0]["registration"]


# ------------------------------------------------- fix round 1 (gate r1)


LESSON = "lrn-0000aaaa"


def _case_with_links(tmp_path: Path, monkeypatch) -> tuple[Path, str, str]:
    """A ledger holding a lesson, a statement the user typed, and a case
    (actor overseer) whose frontmatter names the lesson and whose section 4
    names the statement. Returns ``(ledger, case id, statement id)``."""
    from ruamel.yaml import YAML

    from self_learn import cases
    from self_learn.ledger_ops import create_record
    from support import commit_all, make_behavior, make_env
    from test_grants import _stmt

    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    create_record(env.ledger, make_behavior(scope="user", record_id=LESSON,
                                            instruction="Restart oo7-daemon by hand."))
    commit_all(env.ledger, "seed the lesson")
    stmt = _stmt(env.ledger, tmp_path)
    stage = tmp_path / "case-stage.yaml"
    with stage.open("w", encoding="utf-8") as fh:
        YAML().dump({
            "kind": "parked", "trigger": "weekly", "outcome": "parked",
            "parked_for": "overseer", "parked_reason": "authority-unclear",
            "records": [LESSON], "scope": "user",
            "question": "Should oo7-daemon be bound to the session bus?",
            "evidence": [{"ref": "transcript:conversation#L1", "quote": "the user's words"}],
            "decision": {"verb": "park", "because": "it changes the user's desktop",
                         "confidence": "settled"},
            "dependencies": {"statements": [stmt], "user_model": [], "conditions": [],
                             "capabilities": []},
        }, fh)
    case_id = cases.record(env.ledger, stage, actor="overseer")
    return env.ledger, case_id, stmt


def test_an_asks_packet_shows_the_lesson_and_statements_its_case_names(tmp_path, monkeypatch):
    """Gate r1 MAJOR 1. Mutation: drop the case expansion in `_evidence`
    (`linked` left empty) -> only the case entry, red."""
    ledger, case_id, stmt = _case_with_links(tmp_path, monkeypatch)
    item = attention._new_item(  # noqa: SLF001
        "ask.system-change", "q-oo7-binding", title="Bind it?", since=_now(), by="overseer",
        refs=["q-oo7-binding", case_id], question="Bind oo7-daemon to the session bus?",
    )
    monkeypatch.setattr(attention, "collect", lambda _home, **_k: [item])
    packet = attention_packet.build(ledger, item["id"])
    kinds = [(e["kind"], e.get("id")) for e in packet["evidence"]]
    assert kinds == [("case", case_id), ("lesson", LESSON), ("statement", stmt)]
    case = packet["evidence"][0]
    assert case["question"] == "Should oo7-daemon be bound to the session bus?"
    assert case["because"] == "it changes the user's desktop"
    assert "Restart oo7-daemon by hand." in packet["evidence"][1]["text"]
    assert packet["evidence"][2]["verbatim"] and packet["evidence"][2]["context"]
    # A ref named both by the item and by its case is shown once.
    item["refs"] = ["q-oo7-binding", case_id, LESSON, stmt]
    again = attention_packet.build(ledger, item["id"])
    assert [(e["kind"], e.get("id")) for e in again["evidence"]] == kinds


def test_a_run_digest_packet_shows_the_cases_behind_its_decisions(tmp_path, monkeypatch):
    """Gate r1 MAJOR 1 (run digests). Mutation: leave the manifest's `cases`
    keys out of the digest's refs -> no case entry, red."""
    ledger, case_id, stmt = _case_with_links(tmp_path, monkeypatch)
    runs = ledger / "cases" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "run-bbbbbbbbbbbb.json").write_text(json.dumps({
        "actor": "steward", "run_id": "run-bbbbbbbbbbbb", "completed_at": _now(),
        "decided": [LESSON], "cases": {case_id: {"phase": "applied"}},
    }), encoding="utf-8")
    item_id = attention.item_id("decided.steward-run", "run-bbbbbbbbbbbb")
    packet = attention_packet.build(ledger, item_id)
    kinds = [(e["kind"], e.get("id")) for e in packet["evidence"]]
    assert kinds == [("case", case_id), ("lesson", LESSON), ("statement", stmt)]


def test_a_tampered_cases_packet_shows_the_file_as_edited(tmp_path, monkeypatch):
    """Gate r1 MAJOR 2. Mutation: drop the `_edited_case` fallback (the
    case goes through `cases.show` alone) -> no case entry, red."""
    from self_learn import cases

    ledger, case_id, stmt = _case_with_links(tmp_path, monkeypatch)
    path = next((ledger / "cases").glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    edited = text.replace("it changes the user's desktop",
                          f"I decided this myself; the token is {TOKEN}")
    assert edited != text  # positive control: the edit landed
    path.write_text(edited, encoding="utf-8")
    with pytest.raises(cases.CaseError):
        cases.show(ledger, case_id, evidence_only=False)  # control: show refuses it
    item = attention._new_item(  # noqa: SLF001
        "conflict.case-tampered", case_id, title="A parked case file was edited",
        since=_now(), refs=[case_id, LESSON],
    )
    monkeypatch.setattr(attention, "collect", lambda _home, **_k: [item])
    packet = attention_packet.build(ledger, item["id"])
    kinds = [(e["kind"], e.get("id")) for e in packet["evidence"]]
    assert kinds[:4] == [("case", case_id), ("fact", None), ("lesson", LESSON), ("statement", stmt)]
    case = packet["evidence"][0]
    assert "I decided this myself" in case["excerpt"] and case["because"].startswith("I decided")
    assert TOKEN not in json.dumps(packet) and "[redacted:" in case["excerpt"]
    fact = packet["evidence"][1]
    assert "no longer match the hash" in fact["value"]
    assert "inbox item" not in fact["value"]  # on its own page it names no other item
    # Gate r2 MINOR 2: the pointer promises what `ledger_history` returns
    # (commit subjects and trailers), never the decided text or a diff.
    pointer = next(p for p in packet["pointers"]
                   if p.get("tool") == "ledger_history" and p.get("path") == str(path))
    assert "subjects and trailers only, not the text" in pointer["label"]
    assert "the version committed when it was decided" not in pointer["label"]


def test_an_ask_citing_a_tampered_case_keeps_the_case_and_its_lesson(tmp_path, monkeypatch):
    """Gate r2 MINOR 1. An overseer ask reaches its lesson only through its
    case; when the case file was edited by hand the ask's page still shows
    the case as edited, a fact pointing at the case's own inbox item, and
    the lesson and statement the case names. Mutation: restore the
    `conflict.case-tampered`-only condition on the `_edited_case` fallback
    -> no case, no lesson, red."""
    ledger, case_id, stmt = _case_with_links(tmp_path, monkeypatch)
    path = next((ledger / "cases").glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    edited = text.replace("it changes the user's desktop", "I changed my mind about this")
    assert edited != text  # positive control: the edit landed
    path.write_text(edited, encoding="utf-8")
    ask = attention._new_item(  # noqa: SLF001
        "ask.system-change", "q-tampered-ask", title="May I add the drop-in?",
        since=_now(), refs=["q-tampered-ask", case_id],
    )
    conflict = attention._new_item(  # noqa: SLF001
        "conflict.case-tampered", case_id, title="A parked case file was edited",
        since=_now(), refs=[case_id, LESSON],
    )
    monkeypatch.setattr(attention, "collect", lambda _home, **_k: [ask, conflict])
    packet = attention_packet.build(ledger, ask["id"])
    kinds = [(e["kind"], e.get("id")) for e in packet["evidence"]]
    assert kinds[:4] == [("case", case_id), ("fact", None), ("lesson", LESSON), ("statement", stmt)]
    assert "I changed my mind" in packet["evidence"][0]["excerpt"]
    fact = packet["evidence"][1]["value"]
    assert "may not be what was decided" in fact and conflict["id"] in fact


_DROP_IN = "".join(f"# line {n} of the drop-in, a plain sentence\n" for n in range(250))


def test_the_plan_is_secret_scanned_and_bounded(tmp_path, monkeypatch):
    """Gate r1 MINOR 3. Mutations: copy the plan verbatim again -> the token
    shows, red; leave plan texts out of `_fit` -> over 64 KiB, red."""
    home = make_home(tmp_path)
    plan = {
        "summary": "add the drop-in", "checks": [{"say": "look", "command": f"cat x # {TOKEN}"}],
        "steps": [{"say": f"export T={TOKEN}", "command": "systemctl --user daemon-reload",
                   "sudo": False}],
        "files": [{"path": f"/tmp/f{n}.conf", "content": f"{TOKEN}\n" + _DROP_IN}
                  for n in range(30)],
    }
    item = _synthetic([], [])
    item["_plan"] = plan
    monkeypatch.setattr(attention, "collect", lambda _home, **_k: [item])
    packet = attention_packet.build(home, item["id"])
    raw = json.dumps(packet, ensure_ascii=False)
    assert TOKEN not in raw
    assert "[redacted:" in packet["plan"]["steps"][0]["say"]
    assert "[redacted:" in packet["plan"]["checks"][0]["command"]
    assert len(raw.encode("utf-8")) <= attention_packet.MAX_BYTES
    assert len(packet["plan"]["files"]) == 30
    assert all(len(f["content"]) <= attention_packet.MAX_TEXT_CHARS for f in packet["plan"]["files"])
    assert "plan.files[0].content" in packet["limits"]["truncated"]
