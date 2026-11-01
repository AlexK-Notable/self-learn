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
