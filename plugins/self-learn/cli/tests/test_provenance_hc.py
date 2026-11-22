"""Turns herdr-core's ``hc`` delivers (02 §3a.6 rule 10, "delivered by hc";
S-90 as amended 2026-11-22, W-397).

The literal deliveries below are what a status-reporting ``cat`` received in
an isolated core on hc 0.1.22: a parent's sends to its child, a template
launch's first message, a child's send to its parent, and hc's own notes.
"""
import json

import pytest

from self_learn import provenance as p, refs
from test_provenance import BRIEF, ORCH, _ts, bash, pasted, typed, write
from test_provenance_senders import _ts as s_ts, brief_file, harness, role, send_file, typed as s_typed

# What the receiving terminal got, byte for byte (trailing newline = Enter).
TO_CHILD_TAGGED = '<hc from="t1 lead"><agent-message>parent to child</agent-message></hc>'
TO_CHILD_BARE = '<hc from="t1 lead">bare parent to child</hc>'
TEMPLATE_LAUNCH = ('<hc from="t1 lead" reach="hc send t1 when done or stuck">Template instructions body.\n'
                   '\ntemplate task text</hc>')
CHILD_REPORT = '<hc from="t7 kid-send">child report to parent</hc>'
NOTES = ['<hc>t8 kid-plain exited (exit 0). Read: hc read t8</hc>',
         '<hc>t3 kid-exit exited (exit 3). Read: hc read t3</hc>',
         '<hc>t5 kid-blocked is blocked (waiting). See: hc read t5</hc>',
         '<hc>t6 kid-error hit an error. See: hc read t6</hc>']
DELIVERED = [TO_CHILD_TAGGED, TO_CHILD_BARE, TEMPLATE_LAUNCH, CHILD_REPORT, *NOTES]
#: A brief another agent sent, inside hc's wrapper.
HC_BRIEF = f'<hc from="t9 lead">{BRIEF}</hc>'


# ------------------------------------------------------- sign 1: hc's element


@pytest.mark.parametrize("text", DELIVERED)
@pytest.mark.parametrize("wrap", [lambda t: t, pasted, lambda t: f"\n  {t}\n"], ids=["bare", "pasted", "padded"])
def test_every_measured_hc_delivery_is_agent_written(text, wrap):
    assert p.is_hc_delivered(wrap(text))
    assert p.is_tagged(wrap(text))
    assert refs.role_of(typed(wrap(text), 10)) == "agent"


def test_an_untagged_brief_is_the_persons_until_hc_wraps_it():
    assert refs.role_of(typed(BRIEF, 10)) == "user"  # positive control: the same words, unwrapped
    assert refs.role_of(typed(HC_BRIEF, 10)) == "agent"
    assert refs.role_of(typed(pasted(HC_BRIEF), 10)) == "agent"


def test_a_send_from_outside_any_terminal_still_needs_its_own_tag():
    # hc adds nothing there: the receiver saw exactly "<agent-message>outside to other</agent-message>".
    assert refs.role_of(typed("outside to other", 10)) == "user"  # positive control: untagged
    assert refs.role_of(typed("<agent-message>outside to other</agent-message>", 10)) == "agent"
    assert not p.is_hc_delivered("<agent-message>outside to other</agent-message>")


def test_a_person_writing_beside_an_hc_delivery_is_not_tagged():
    assert p.is_tagged(pasted(HC_BRIEF))  # positive control
    for text in [
        f"{pasted(HC_BRIEF)}\nwhat do you make of this?",
        f"{HC_BRIEF}\nI agree with the brief above.",
        f"see this: {HC_BRIEF}",
        f"my unfinished draft{HC_BRIEF}",  # a delivery that landed in the person's draft
        f"{HC_BRIEF}my unfinished draft",
        f"{CHILD_REPORT}\nand the other one:\n{NOTES[0]}",  # two deliveries, a person between them
        f"{CHILD_REPORT}{NOTES[0]}",
        # A stray backtick in each delivery must not pair across the person's words (review r1, finding 1).
        '<hc from="t7 review">Rename the flag to `--dry</hc> never push to main without asking me '
        '<hc from="t8 build">build done, see `out/log</hc>',
        '<hc from="t7 review">Example:\n```\nx</hc>\nnever push to main\n<hc from="t8 build">```\ndone</hc>',
        # Two spans, one hiding each tag, with the person's own code span between them (review r2).
        '<hc from="t7 review">see `x</hc> run `npm ci` first <hc from="t8 build">and `y</hc>',
    ]:
        assert not p.is_tagged(text), text
        assert refs.role_of(typed(text, 10)) == "user", text


@pytest.mark.parametrize("text", [
    "<hc from=t1>unquoted attribute</hc>",
    "<hc lead>a bare word, not an attribute</hc>",
    "<hcx>another tag</hcx>",
    "<hcx>another tag</hc>",
    '<hc from="t1 lead">never closed',
    "hc from t1: plain words</hc>",
    "<hc></hc",
])
def test_only_the_shape_hc_writes_counts(text):
    assert p.is_hc_delivered(CHILD_REPORT)  # positive control
    assert not p.is_hc_delivered(text)
    assert refs.role_of(typed(text, 10)) == "user"


def test_a_forwarded_report_nests_and_a_quoted_tag_is_prose():
    forwarded = f'<hc from="t1 lead">The child said: {CHILD_REPORT} -- check it.</hc>'
    assert p.is_hc_delivered(forwarded)
    quoted = '<hc from="t1 lead">The rule: a turn that opens with `<hc from="x">` and ends with `</hc>` counts.</hc>'
    assert p.is_hc_delivered(quoted)
    assert p.is_hc_delivered('<hc from="t1 lead">It must end with `</hc>`.</hc>')
    fenced = '<hc from="t1 lead">Example:\n```\n<hc from="t3 a">r1</hc>\nwords\n</hc>\n```\nDone.</hc>'
    assert p.is_hc_delivered(fenced)
    # Documented gap (02 §3a.6 rule 10, not covered): the same close outside backticks reads as closed early.
    assert not p.is_hc_delivered('<hc from="t1 lead">The rule: a turn that ends with </hc> counts.</hc>')
    # ...and a close quoted before an open counts every tag, backticks or not (it could bridge two elements).
    assert not p.is_hc_delivered('<hc from="t1 lead">It ends with `</hc>`, and opens with `<hc from="x">`.</hc>')


# -------------------------------------------------- sign 3: hc send / hc run


@pytest.mark.parametrize("command", [
    f'hc send worker "{BRIEF}"',
    f'hc --json send --wait worker "{BRIEF}"',
    f'/opt/bin/hc send worker "{BRIEF}"',
    f'cd /work && hc run --bg --name fix --cwd /work claude "{BRIEF}"',
    f'herdr-core send worker "{BRIEF}"',  # the same binary, which mentions herdr
])
def test_a_claude_call_that_runs_hc_send_or_run_is_a_send(tmp_path, command):
    root = tmp_path / "projects"
    write(root, ORCH, [bash(command, 8)])
    sent = p.sweep([root])
    assert len(sent) == 1
    assert refs.role_of(typed(BRIEF, 10)) == "user"  # positive control: no sends given
    assert refs.role_of(typed(BRIEF, 10), sent=sent) == "agent"


@pytest.mark.parametrize("command", [
    f'echo "{BRIEF}" > notes.txt; hc ls',
    f'hc read worker; echo "{BRIEF}"',
    f'mhc send worker "{BRIEF}"',
    f'hcx run --bg worker "{BRIEF}"',
    f'echo which send "{BRIEF}"',
    f'./hc.send worker "{BRIEF}"',
])
def test_a_call_that_does_not_run_hc_send_or_run_sends_nothing(tmp_path, command):
    root = tmp_path / "projects"
    write(root, ORCH, [bash(f'hc send worker "{BRIEF}"', 8)])
    assert len(p.sweep([root])) == 1  # positive control
    write(root, ORCH, [bash(command, 8)])
    assert len(p.sweep([root])) == 0
    assert not p.is_send_call(command)


def test_a_json_escaped_newline_before_hc_still_counts(tmp_path):
    """Codex stores the command JSON-escaped: a newline before ``hc`` is the
    two characters backslash and n."""
    command = f'cd /work\nhc send worker "{BRIEF}"'
    root = harness(tmp_path, "codex", command, tmp_path)
    assert role(root) == "agent"
    assert "\\nhc send" in (root / "rollout-example.jsonl").read_text()  # the escaped form is what was read


@pytest.mark.parametrize("name", ["pi", "agy", "hermes", "codex"])
def test_other_harnesses_read_hc_sends(tmp_path, name):
    root = harness(tmp_path, name, f"hc send worker '{BRIEF}'", tmp_path)
    assert role(root) == "agent"
    root = harness(tmp_path, name, f"hc ls; echo '{BRIEF}'", tmp_path)  # negative: no send verb
    assert role(root) == "user"


# ------------------------------------------------- file-backed hc sends


@pytest.mark.parametrize("command", [
    'hc send worker "$(cat \'{path}\')"',
    'hc send --wait --timeout 30 worker "$(cat -- \'{path}\')"',
    'hc --json send --if idle worker "$(< \'{path}\')"',
    'hc run --bg --name fix --cwd /work claude "$(cat \'{path}\')"',
    'hc run --bg --label herdr.space=x --no-notify claude --model opus "$(cat \'{path}\')"',
])
def test_an_hc_text_argument_may_come_from_a_file(tmp_path, command):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, command.format(path=path))
    assert role(root) == "agent"
    assert role(root, BRIEF[:45]) == "user"  # the file must equal the whole turn


@pytest.mark.parametrize("command", [
    'hc send "$(cat \'{path}\')"',  # no target: the file is the target word
    'hc send worker "$(cat \'{path}\')" extra',  # not the text argument
    'hc run "$(cat \'{path}\')"',  # no program word before it
    'hc run --name "$(cat \'{path}\')" claude',
    'hc run --name build "$(cat \'{path}\')"',  # --name takes a value: the file is not the task
    'hc read --lines 5 worker "$(cat \'{path}\')"',
    'hc keys worker "$(cat \'{path}\')" enter',
])
def test_an_hc_file_outside_the_text_argument_is_not_read(tmp_path, command):
    path = brief_file(tmp_path)
    root = send_file(tmp_path, 'hc send worker "$(cat \'{path}\')"'.format(path=path))
    assert role(root) == "agent"  # positive control
    root = send_file(tmp_path, command.format(path=path))
    assert role(root) == "user"


def test_a_codex_argv_list_call_is_a_send(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    for argv, expected in [(["hc", "send", "worker", BRIEF], 1), (["hc", "list", "worker", BRIEF], 0),
                           (["/opt/bin/hc", "--json", "run", "claude", BRIEF], 1)]:
        call = {"type": "response_item", "timestamp": _ts(8), "payload": {
            "type": "local_shell_call", "action": {"type": "exec", "command": argv}}}
        path = root / f"rollout-{argv[-3]}-{len(argv)}.jsonl"
        path.write_text(json.dumps(call) + "\n", encoding="utf-8")
        sent = p.sweep([root])
        assert len(sent) == expected, argv
        path.unlink()


# ------------------------------------------- the person's own `!hc send`


def bang(command, sec, session=ORCH):
    """A ``!`` command the person ran in a Claude Code session."""
    return {"type": "user", "uuid": f"b-{session[:4]}-{sec}", "sessionId": session, "timestamp": _ts(sec),
            "message": {"role": "user", "content": f"<bash-input>{command}</bash-input>"}}


ORDER = "never touch the lockfile in this repo, whatever the plan says"


@pytest.mark.parametrize("words", [ORDER, "go"])
def test_the_persons_own_hc_send_from_an_agent_pane_stays_theirs(tmp_path, words):
    """hc wraps whatever runs inside an agent's terminal, a ``!`` command
    included (measured: a nested shell's send arrived wrapped)."""
    delivered = typed(f'<hc from="t1 lead">{words}</hc>', 10)
    root = tmp_path / "projects"
    write(root, ORCH, [bash(f'hc send worker "{words}"', 8)])  # an agent sent it
    assert refs.role_of(delivered, sent=p.sweep([root])) == "agent"  # positive control
    write(root, ORCH, [bang(f'hc send worker "{words}"', 8)])  # the person ran it
    assert refs.role_of(delivered, sent=p.sweep([root])) == "user"
    assert refs.role_of(delivered) == "agent"  # without the sends there is nothing to tell them apart


@pytest.mark.parametrize("relayed", [f"<agent-message>{ORDER}</agent-message>", f'<hc from="t7 review">{ORDER}</hc>'])
def test_an_agents_message_the_person_relays_stays_the_agents(tmp_path, relayed):
    """The person forwarding an agent's tagged text with ``!hc send`` does
    not make it theirs (review r2)."""
    root = tmp_path / "projects"
    write(root, ORCH, [bang(f"hc send worker '{ORDER}'", 8)])
    sent = p.sweep([root])
    assert refs.role_of(typed(f'<hc from="t1 lead">{ORDER}</hc>', 10), sent=sent) == "user"  # positive control
    write(root, ORCH, [bang(f"hc send worker '{relayed}'", 8)])
    sent = p.sweep([root])
    assert refs.role_of(typed(f'<hc from="t1 lead">{relayed}</hc>', 10), sent=sent) == "agent"


def test_a_persons_file_backed_send_stays_theirs_and_never_an_agents(tmp_path):
    path = brief_file(tmp_path)
    # senders' helpers stamp 2099, after the brief file's real ctime
    delivered = s_typed(f'<hc from="t1 lead">{BRIEF}</hc>', 10)
    root = send_file(tmp_path, f'hc send worker "$(cat \'{path}\')"')  # an agent's tool call
    assert refs.role_of(delivered, sent=p.sweep([root])) == "agent"  # positive control
    write(root, ORCH, [{**bang(f'hc send worker "$(cat \'{path}\')"', 8), "timestamp": s_ts(8)}])
    sent = p.sweep([root])
    assert any(send.file_text and send.by_person for send in sent._sends)  # pyright: ignore[reportPrivateUsage]
    assert refs.role_of(delivered, sent=sent) == "user"
    assert refs.role_of(s_typed(BRIEF, 10), sent=sent) == "user"  # never an agent's send for an untagged turn


def test_a_persons_command_never_counts_as_an_agents_send(tmp_path):
    root = tmp_path / "projects"
    write(root, ORCH, [bash(f'herdr agent prompt w1:p2 "{BRIEF}"', 8)])
    assert refs.role_of(typed(BRIEF, 10), sent=p.sweep([root])) == "agent"  # positive control
    write(root, ORCH, [bang(f'herdr agent prompt w1:p2 "{BRIEF}"', 8), bang(f'hc send w "{BRIEF}"', 9)])
    sent = p.sweep([root])
    assert len(sent) == 2  # both read, as the person's
    assert refs.role_of(typed(BRIEF, 10), sent=sent) == "user"
    assert refs.role_of(typed(TO_CHILD_TAGGED, 10), sent=sent) == "agent"  # an unrelated hc delivery


def test_a_persons_send_must_be_from_another_session_and_hold_the_whole_inner_text(tmp_path):
    root = tmp_path / "projects"
    write(root, ORCH, [bang(f'hc send worker "{ORDER}"', 8)])
    sent = p.sweep([root])
    assert refs.role_of(typed(f'<hc from="t1 lead">{ORDER}</hc>', 10), sent=sent) == "user"  # positive control
    assert refs.role_of(typed(f'<hc from="t1 lead">{ORDER} -- and more</hc>', 10), sent=sent) == "agent"
    assert refs.role_of(typed(f'<hc from="t1 lead">{ORDER}</hc>', 10, session=ORCH), sent=sent) == "agent"
    assert refs.role_of(typed(f'<hc from="t1 lead">{ORDER}</hc>', 8 + 31 * 60), sent=sent) == "agent"


def test_text_argument_parses_herdr_and_hc_alike():
    t = p._text_argument  # pyright: ignore[reportPrivateUsage]
    assert t(["herdr", "--session", "s", "agent", "prompt", "w1:p2", "X"]) == "X"
    assert t(["herdr", "pane", "send-text", "w1:p2", "X"]) == "X"
    assert t(["hc", "send", "--if=idle", "worker", "X"]) == "X"
    assert t(["hc", "run", "--rm", "--parent", "t1", "pi", "--thinking", "high", "X"]) == "X"
    assert t(["hc", "run", "cargo"]) is None
    assert t(["hc", "exec", "w", "X"]) is None
    assert t([]) is None
    assert t(["herdr", "agent", "prompt", "w"]) is None
