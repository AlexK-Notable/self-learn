"""Follow-ups 2 gate r1 F3: the ask agent starts from a packet that already
holds a hand-edited case's decided text (answer 10: "an agent that already
has the relevant information in its own context"), so it need not think to
call its `case` tool. The turn runs on `invocation.FakeBackend`; no model
call is made.
"""

from __future__ import annotations

import io
import json

from self_learn import ask, attention
from self_learn.invocation.fake import FakeBackend, Text
from test_ask import person  # noqa: F401 -- the autouse person's-shell fixture
from test_followups2 import _EDIT_FROM, _EDIT_TO, _tampered, _tampered_item


def test_the_ask_agents_first_prompt_carries_the_decided_text(tmp_path, monkeypatch):
    """Mutation (the gate's M6b): the ask verb builds its packet with no
    `decided_reader` -> red."""
    monkeypatch.setattr(attention, "_systemctl_active", lambda unit: True)
    ledger, case_id, _path = _tampered(tmp_path, monkeypatch)
    item = _tampered_item(ledger, case_id, monkeypatch)
    backend = FakeBackend([Text("It was edited by hand.")])
    monkeypatch.setattr(ask, "_backend", backend)

    code, _emitter = ask.run_ask(ledger, item["id"], "What did the case say when it was decided?",
                                 stream=True, out=io.StringIO(), err=io.StringIO())

    assert code == 0  # control: the turn ran
    packet = json.loads((ask.workspace_dir(ledger, item["id"]) / "packet.json").read_text("utf-8"))
    decided = packet["case_edit"]["decided"]
    assert decided is not None and _EDIT_FROM in decided["text"] and _EDIT_TO not in decided["text"]
    prompt = backend.specs[0].prompt
    assert "## The hand edit of" in prompt and _EDIT_FROM in prompt.split("Sections 1-4 as decided", 1)[1]
