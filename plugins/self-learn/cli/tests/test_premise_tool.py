"""premise_tool.py (premise-check design, unit U5; S-NEXT-u5-probe-tool):
the steward's read-only `premise_probe` tool, and the seam change that
lets the steward carry it beside its built-in tools.

Hermetic: the probes' commands run through an injected command runner (a
recording fake), never a real `systemctl`, `pacman` or `git`; no model is
called, no session started (the seam tests build the SDK options and call
the tool through the built in-process server, as `test_seam_mcp_tools.py`
does). Every ledger is a scratch sandbox. The tool's own tests that touch
files avoid the words the credential-path rule refuses in test names (a
test's `tmp_path` directory is named after it).

Written to fail on master: `premise_tool.py` does not exist there, the
seam refuses a steward session that names an `mcp__` tool, and the
steward's containment is the five built-in tools.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
import threading
from pathlib import Path

import pytest
from mcp import types as mcp_types

from self_learn import invocation, ledger_ops, premise_tool, premises, provider, scan, steward
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import charter as charter_mod
from self_learn.premise_tool import PlacementReading, PremiseProbeTool
from self_learn.premises import CommandResult, ProbeEnv
from support import make_behavior, make_home

NAME = "mcp__premises__premise_probe"
NOW = "2026-10-31T00:00:00Z"

OO7_PROBE = {"kind": "systemd-show", "scope": "user", "unit": "oo7-daemon.service",
             "property": "BindsTo"}


# ---------------------------------------------------------------- helpers


class Runner:
    """A recording command runner. `stdout` may be changed between calls."""

    def __init__(self, stdout: bytes = b"", rc: int = 0, stderr: bytes = b"",
                 raises: BaseException | None = None,
                 by_prog: dict[str, bytes] | None = None) -> None:
        self.stdout, self.rc, self.stderr, self.raises = stdout, rc, stderr, raises
        #: a program's own answer, over `stdout` (pacman answers
        #: `<name> <version>`; systemctl answers the bare value)
        self.by_prog = dict(by_prog or {})
        self.calls: list[list[str]] = []
        self.threads: list[threading.Thread] = []

    def __call__(self, argv, env, timeout) -> CommandResult:
        self.calls.append(list(argv))
        self.threads.append(threading.current_thread())
        if self.raises is not None:
            raise self.raises
        return CommandResult(self.rc, self.by_prog.get(argv[0], self.stdout), self.stderr)


def _env(home: Path, runner: Runner | None = None) -> ProbeEnv:
    return ProbeEnv(
        home=home, path_env="/nonexistent-bin", runner=runner or Runner(),
        runtime_dir=None, now=lambda: NOW,
    )


def _tool(tmp_path: Path, runner: Runner | None = None, *, placement=None,
          ledger: Path | None = None) -> PremiseProbeTool:
    return PremiseProbeTool(
        ledger if ledger is not None else tmp_path / "no-ledger",
        env=_env(tmp_path, runner), placement=placement,
    )


def _ok(reply) -> str:
    assert not reply.is_error, reply.text
    return reply.text


def _err(reply) -> str:
    assert reply.is_error, reply.text
    return reply.text


def _lesson(home: Path, record_id: str, premises_value) -> None:
    record = make_behavior(record_id=record_id)
    record.set_premises(premises_value)
    ledger_ops.create_record(home, record)


def _written() -> list[dict]:
    return [
        {"id": "p1", "claim": "oo7-daemon.service is not bound to the session bus",
         "probe": OO7_PROBE, "holds_if": "absent", "match": "dbus-broker.service",
         "baseline": {"state": "holds", "value_sha": premises.value_sha(""), "observed_at":
                      "2026-09-22T06:24:50Z"}},
        {"id": "p2", "claim": "the daemon can outlive a bus restart without reconnecting",
         "probe": None},
        {"id": "p3", "claim": "the package is installed",
         "probe": {"kind": "package", "name": "oo7"}},
    ]


def _server_call(server, arguments: dict) -> tuple[str, bool]:
    handler = server.request_handlers[mcp_types.CallToolRequest]
    request = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name="premise_probe", arguments=arguments),
    )
    result = asyncio.run(handler(request)).root
    return "".join(block.text for block in result.content), bool(result.isError)


def _steward_spec(tmp_path: Path):
    home = make_home(tmp_path)
    spec = steward._session_spec(home, tmp_path / "run", "a brief", label="t")
    return home, spec


# ===================================================================== #
# 1. The tool's shape
# ===================================================================== #


def test_the_toolset_is_one_read_only_tool_named_for_the_steward(tmp_path):
    toolset = premise_tool.build_toolset(tmp_path)
    assert toolset.server == "premises"
    assert toolset.qualified_names == (NAME,) == (premise_tool.QUALIFIED_NAME,)
    (tool,) = toolset.tools
    assert tool.name == "premise_probe" and tool.read_only is True
    assert tool.input_schema["type"] == "object" and tool.input_schema["properties"]


def test_the_schema_names_exactly_the_catalogs_kinds_and_fields():
    schema = premise_tool.TOOL_DEFINITION["input_schema"]
    probe = schema["properties"]["probe"]
    assert probe["properties"]["kind"]["enum"] == sorted(premises.PROBE_KINDS)
    union = set().union(*premises._PROBE_FIELDS.values())
    assert set(probe["properties"]) == union
    assert schema["properties"]["holds_if"]["enum"] == sorted(premises.HOLDS_IF_VALUES)
    description = premise_tool.TOOL_DEFINITION["description"]
    for kind in premises.PROBE_KINDS:
        assert kind in description
    # No top-level oneOf/anyOf/allOf: the API refuses them in a tool schema.
    assert not {"oneOf", "anyOf", "allOf"} & set(schema)


def test_the_tool_is_served_by_the_sdk_server_and_listed_read_only(tmp_path):
    home, spec = _steward_spec(tmp_path)
    kwargs = backend_mod.options_kwargs(spec)
    server = kwargs["mcp_servers"]["premises"]["instance"]
    handler = server.request_handlers[mcp_types.ListToolsRequest]
    (listed,) = asyncio.run(handler(None)).root.tools
    assert listed.name == "premise_probe"
    assert listed.annotations.readOnlyHint is True
    assert listed.inputSchema == premise_tool.TOOL_DEFINITION["input_schema"]


# ===================================================================== #
# 2. `probe`: a probe the steward is writing
# ===================================================================== #


def test_a_probe_shows_the_value_and_the_baseline_a_premise_would_record(tmp_path):
    runner = Runner(stdout=b"\n")
    tool = _tool(tmp_path, runner)
    text = _ok(tool.dispatch(
        {"probe": OO7_PROBE, "holds_if": "absent", "match": "dbus-broker.service"}
    ))
    assert "state: ok" in text
    assert "value: (empty)" in text  # `systemctl show --value` prints nothing when unbound
    assert f"value_sha: {premises.value_sha('')}" in text
    assert "claim: holds (holds_if absent 'dbus-broker.service')" in text
    assert "baseline if written now: holds" in text
    # The commands run are the catalog's own read-only shape: the unit's
    # LoadState first (integration 2026-10-31: U1 fix round 1, 66bd21f, reads it
    # so an unknown unit is `unavailable`, never an empty value), then the
    # property asked for.
    assert runner.calls == [[
        "systemctl", "--user", "show", "--no-pager", "--no-ask-password", "--property",
        prop, "--value", "--", "oo7-daemon.service",
    ] for prop in ("LoadState", "BindsTo")]


def test_a_first_value_that_contradicts_the_claim_is_reported_at_write_time(tmp_path):
    # The oo7 replay: before the drop-in the claim holds; after it, the
    # first value already contradicts it (design D10).
    runner = Runner(stdout=b"dbus-broker.service\n")
    text = _ok(_tool(tmp_path, runner).dispatch(
        {"probe": OO7_PROBE, "holds_if": "absent", "match": "dbus-broker.service"}
    ))
    assert 'value: "dbus-broker.service"' in text
    assert "claim: contradicted" in text
    assert "baseline if written now: contradicts-claim" in text
    runner.stdout = b""
    text = _ok(_tool(tmp_path, runner).dispatch(
        {"probe": OO7_PROBE, "holds_if": "absent", "match": "dbus-broker.service"}
    ))
    assert "claim: holds" in text and "contradicts-claim" not in text  # positive control


def test_a_probe_that_cannot_observe_is_unavailable_never_a_verdict(tmp_path):
    for runner in (
        Runner(raises=FileNotFoundError()),
        Runner(rc=1),
        Runner(raises=subprocess.TimeoutExpired("systemctl", 5)),
    ):
        text = _ok(_tool(tmp_path, runner).dispatch({"probe": OO7_PROBE, "holds_if": "absent",
                                                      "match": "x"}))
        assert "state: unavailable" in text
        assert "reason:" in text
        assert "neither changed nor unchanged" in text
        for line in ("claim:", "value:", "baseline if written now"):
            assert line not in text


def test_a_changed_probe_is_unjudged_until_it_has_a_baseline(tmp_path):
    text = _ok(_tool(tmp_path, Runner(stdout=b"oo7 1.2.3-1\n")).dispatch(
        {"probe": {"kind": "package", "name": "oo7"}}
    ))
    assert "claim: unjudged" in text and "baseline if written now: holds" in text
    runner = Runner(stdout=b"oo7 0.5.1-1\n")
    text = _ok(_tool(tmp_path, runner).dispatch(
        {"probe": {"kind": "package", "name": "oo7"}, "holds_if": "version",
         "match": ">=0.5,<0.6"}
    ))
    assert 'value: "0.5.1-1"' in text and "claim: holds" in text
    assert runner.calls == [["pacman", "-Q", "--", "oo7"]]


@pytest.mark.parametrize(
    "arguments, fragment",
    [
        ({"probe": {"kind": "shell", "cmd": "reboot"}}, "invalid arguments"),
        ({"probe": {"kind": "systemd-show", "scope": "user", "unit": "x.service",
                    "property": "BindsTo", "extra": 1}}, "invalid arguments"),
        ({"probe": {"kind": "systemd-show", "scope": "user", "unit": "x; reboot",
                    "property": "BindsTo"}}, "unit"),
        ({"probe": {"kind": "file-match", "path": "~/.ssh/config", "contains": "x"}},
         "refused"),
        ({"probe": {"kind": "file-match", "path": "/etc/hosts"}}, "exactly one of"),
        ({"probe": {"kind": "path", "path": "relative/path"}}, "absolute"),
        ({"probe": OO7_PROBE, "holds_if": "absent"}, "match"),
        ({"probe": OO7_PROBE, "holds_if": "changed", "match": "x"}, "takes no match"),
        ({"probe": {"kind": "path", "path": "/etc"}, "holds_if": "version", "match": ">=1"},
         "package"),
        ({"probe": OO7_PROBE, "premise": "p1"}, "goes with `lesson`"),
        ({"probe": OO7_PROBE, "lesson": "lrn-0000000a"}, "exactly one"),
        ({}, "exactly one"),
        ({"lesson": "lrn-0000000a", "holds_if": "absent", "match": "x"}, "go with `probe`"),
        ({"lesson": "not-an-id"}, "invalid arguments"),
        # the schema's `$` lets a trailing newline through; the handler does not
        ({"lesson": "lrn-0000000a\n"}, "not a lesson id"),
        ({"lesson": "lrn-0000000a", "premise": "p9"}, "invalid arguments"),
        ({"frobnicate": True}, "invalid arguments"),
    ],
)
def test_a_call_the_catalog_would_refuse_is_refused_and_runs_nothing(tmp_path, arguments,
                                                                      fragment):
    runner = Runner(stdout=b"x")
    text = _err(_tool(tmp_path, runner).dispatch(arguments))
    assert fragment in text
    assert runner.calls == []


def test_a_forbidden_command_cannot_be_asked_for_through_the_tool(tmp_path):
    # The probe schema has no field that reaches an argv outside the three
    # catalog shapes; every attempt is refused before the runner is called,
    # and a plain valid probe still runs (the positive control).
    runner = Runner(stdout=b"x")
    tool = _tool(tmp_path, runner)
    for bad in (
        {"kind": "systemd-show", "scope": "user", "unit": "x.service", "property": "ActiveState",
         "verb": "start"},
        {"kind": "systemd-show", "scope": "user", "unit": "--help.service", "property": "Id"},
        {"kind": "package", "name": "-S"},
        {"kind": "git-file", "repo": "/tmp", "path": "--output=x", "contains": "a"},
    ):
        assert tool.dispatch({"probe": bad}).is_error
    assert runner.calls == []
    _ok(tool.dispatch({"probe": {"kind": "systemd-show", "scope": "user", "unit": "x.service",
                                  "property": "ActiveState"}}))
    assert [c[6] for c in runner.calls] == ["LoadState", "ActiveState"]  # 66bd21f: LoadState first


def test_a_file_probe_never_returns_the_files_text(tmp_path):
    conf = tmp_path / "app.conf"
    conf.write_text("CANARY-LINE-4711 first\nexec-once = waybar\n", encoding="utf-8")
    tool = _tool(tmp_path)
    for probe in (
        {"kind": "file-match", "path": str(conf), "contains": "first"},
        {"kind": "file-match", "path": str(conf), "line": "exec-once = waybar"},
        {"kind": "file-match", "path": str(conf), "lines": "1-2"},
    ):
        text = _ok(tool.dispatch({"probe": probe}))
        # The first line echoes the probe as asked; the answer below it
        # carries no text of the file.
        answer = text.split("\n", 1)[1]
        assert "state: ok" in answer
        assert "CANARY" not in text and "waybar" not in answer
    present = _ok(tool.dispatch({"probe": {"kind": "file-match", "path": str(conf),
                                           "contains": "first"}, "holds_if": "present",
                                 "match": "present"}))
    assert 'value: "present"' in present and "claim: holds" in present


def test_a_key_probe_shows_a_short_value_and_hides_a_long_or_flagged_one(tmp_path):
    flagged = "ghp_" + "a1B2" * 9
    assert scan.scan(flagged)  # positive control: the scan does flag this value
    doc = tmp_path / "config.json"
    doc.write_text(json.dumps({"mode": "fast", "long": "word " * 60, "login": flagged}),
                   encoding="utf-8")
    tool = _tool(tmp_path)
    short = _ok(tool.dispatch({"probe": {"kind": "json-key", "path": str(doc), "key": "mode"}}))
    assert 'value: "\\"fast\\""' in short
    for key in ("long", "login"):
        text = _ok(tool.dispatch({"probe": {"kind": "json-key", "path": str(doc), "key": key}}))
        assert "(not shown" in text and "value_sha:" in text
        assert flagged not in text and "word word word" not in text


def test_the_ledger_probe_reads_this_tools_ledger(tmp_path):
    home = make_home(tmp_path)
    ledger_ops.create_record(home, make_behavior(record_id="lrn-0000000b"))
    tool = _tool(tmp_path, ledger=home)
    text = _ok(tool.dispatch({"probe": {"kind": "ledger", "ref": "lrn-0000000b"}}))
    assert 'value: "pending"' in text
    # integration 2026-10-31 (u1 gate MINOR): an id the ledger does not hold is
    # `unavailable` (it means the wrong ledger), not the value `not-found`.
    missing = _ok(tool.dispatch({"probe": {"kind": "ledger", "ref": "lrn-0000000e"}}))
    assert "state: unavailable" in missing and "not in this ledger" in missing
    # An injected environment cannot point the tool at another ledger.
    other = PremiseProbeTool(home, env=dataclasses.replace(_env(tmp_path),
                                                            ledger_home=tmp_path / "elsewhere"))
    assert 'value: "pending"' in _ok(other.dispatch(
        {"probe": {"kind": "ledger", "ref": "lrn-0000000b"}}))


def test_an_unexpected_failure_names_only_its_type(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("CANARY-private-detail")

    monkeypatch.setattr(premises, "observe", boom)
    reply = _tool(tmp_path).dispatch({"probe": OO7_PROBE})
    assert reply.is_error and "RuntimeError" in reply.text and "CANARY" not in reply.text


# ===================================================================== #
# 3. `lesson`: a placed lesson's recorded premises
# ===================================================================== #


def test_a_lesson_with_premises_is_probed_and_judged_against_its_baseline(tmp_path):
    home = make_home(tmp_path)
    _lesson(home, "lrn-0000000a", _written())
    runner = Runner(by_prog={"systemctl": b"dbus-broker.service\n", "pacman": b"oo7 0.5.1-1\n"})
    text = _ok(_tool(tmp_path, runner, ledger=home).dispatch({"lesson": "lrn-0000000a"}))
    assert text.startswith("lesson lrn-0000000a [pending]")
    assert "premises: 3 recorded" in text
    assert "p1: oo7-daemon.service is not bound to the session bus" in text
    assert "verdict: moved" in text  # the bound value contradicts `absent`
    assert "baseline: holds, value (empty), value_sha " + premises.value_sha("") in text
    assert 'now: value "dbus-broker.service"' in text
    # the behaviour premise is written down and never probed
    assert "p2: the daemon can outlive a bus restart without reconnecting" in text
    assert "probe: none (a behaviour premise" in text and "verdict: no-probe" in text
    # p3 has no baseline yet
    assert "verdict: no-baseline" in text
    # p1's two systemctl reads (LoadState, then BindsTo: 66bd21f) and p3's
    # pacman; p2 ran nothing
    assert [c[0] for c in runner.calls] == ["systemctl", "systemctl", "pacman"]
    runner.by_prog["systemctl"] = b""
    held = _ok(_tool(tmp_path, runner, ledger=home).dispatch({"lesson": "lrn-0000000a"}))
    assert "verdict: holds" in held and "verdict: moved" not in held  # positive control


def test_asking_for_one_premise_runs_only_that_probe(tmp_path):
    home = make_home(tmp_path)
    _lesson(home, "lrn-0000000a", _written())
    runner = Runner(stdout=b"")
    text = _ok(_tool(tmp_path, runner, ledger=home).dispatch(
        {"lesson": "lrn-0000000a", "premise": "p1"}
    ))
    assert "premises: 3 recorded, showing p1" in text
    assert "p1:" in text and "p2:" not in text and "p3:" not in text
    # p1's two systemctl reads (LoadState, then BindsTo: 66bd21f), nothing else
    assert [c[0] for c in runner.calls] == ["systemctl", "systemctl"]
    behaviour = _ok(_tool(tmp_path, runner, ledger=home).dispatch(
        {"lesson": "lrn-0000000a", "premise": "p2"}
    ))
    assert "verdict: no-probe" in behaviour and len(runner.calls) == 2
    missing = _err(_tool(tmp_path, runner, ledger=home).dispatch(
        {"lesson": "lrn-0000000b", "premise": "p1"}
    ))
    assert "no lesson lrn-0000000b" in missing
    two = make_behavior(record_id="lrn-0000000c")
    two.set_premises(_written()[:1])
    ledger_ops.create_record(home, two)
    absent = _err(_tool(tmp_path, runner, ledger=home).dispatch(
        {"lesson": "lrn-0000000c", "premise": "p4"}
    ))
    assert "has no premise p4" in absent and "['p1']" in absent


def test_no_premises_recorded_and_the_explicit_empty_list_read_differently(tmp_path):
    home = make_home(tmp_path)
    ledger_ops.create_record(home, make_behavior(record_id="lrn-0000000a"))
    _lesson(home, "lrn-0000000b", [])
    tool = _tool(tmp_path, ledger=home)
    none = _ok(tool.dispatch({"lesson": "lrn-0000000a"}))
    empty = _ok(tool.dispatch({"lesson": "lrn-0000000b"}))
    assert "none recorded yet" in none and "decided" not in none
    assert "premises: []" in empty and "decided: this lesson rests on no fact" in empty


def test_a_lesson_call_changes_nothing_in_the_ledger(tmp_path):
    home = make_home(tmp_path)
    _lesson(home, "lrn-0000000a", _written())

    def snapshot() -> tuple:
        files = sorted(p for p in home.rglob("*") if p.is_file() and ".git" not in p.parts)
        digest = tuple((str(p), p.read_bytes()) for p in files)
        head = subprocess.run(["git", "-C", str(home), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout
        status = subprocess.run(["git", "-C", str(home), "status", "--porcelain"],
                                capture_output=True, text=True, check=True).stdout
        return digest, head, status

    before = snapshot()
    assert before[0]  # the lesson file is part of what is compared
    tool = _tool(tmp_path, Runner(stdout=b"x"), ledger=home)
    _ok(tool.dispatch({"lesson": "lrn-0000000a"}))
    _ok(tool.dispatch({"probe": {"kind": "ledger", "ref": "lrn-0000000a"}}))
    assert snapshot() == before


# --------------------------------------------------- placement premises (U8)


def test_without_a_placement_reader_the_tool_says_so_and_invents_nothing(tmp_path):
    home = make_home(tmp_path)
    _lesson(home, "lrn-0000000a", [])
    tool = _tool(tmp_path, ledger=home)
    text = _ok(tool.dispatch({"lesson": "lrn-0000000a"}))
    assert "placement premises (@reach, @writable, @intact): not available" in text
    for wanted in ("@reach", "@writable", "@intact"):
        refusal = _err(tool.dispatch({"lesson": "lrn-0000000a", "premise": wanted}))
        assert "placement premise" in refusal and "not available" in refusal


def test_a_placement_reader_is_shown_beside_the_written_premises(tmp_path):
    home = make_home(tmp_path)
    _lesson(home, "lrn-0000000a", _written()[:2])
    seen = []

    def reader(ledger, record):
        seen.append((ledger, record.id))
        return [
            PlacementReading("@reach", "holds", "the file is on a loaded path"),
            PlacementReading("@writable", "moved", "CLAUDE.md is tracked by git in a plain host"),
            PlacementReading("@intact", "nonsense", "an odd verdict"),
        ]

    tool = _tool(tmp_path, Runner(stdout=b""), placement=reader, ledger=home)
    text = _ok(tool.dispatch({"lesson": "lrn-0000000a"}))
    assert seen == [(home, "lrn-0000000a")]
    assert "@reach: holds (the file is on a loaded path)" in text
    assert "@writable: moved (CLAUDE.md is tracked by git in a plain host)" in text
    # a verdict outside the vocabulary reads as unavailable, never as a change
    assert "@intact: unavailable (an odd verdict)" in text
    assert "p1:" in text and "p2:" in text
    only = _ok(tool.dispatch({"lesson": "lrn-0000000a", "premise": "@writable"}))
    assert "@writable: moved" in only and "@reach" not in only and "p1:" not in only
    # asking for one placement premise does not probe the written ones
    runner = Runner(stdout=b"")
    _ok(_tool(tmp_path, runner, placement=reader, ledger=home).dispatch(
        {"lesson": "lrn-0000000a", "premise": "@reach"}))
    assert runner.calls == []
    # a written premise's id asks for that premise alone, without placement
    lines = _ok(_tool(tmp_path, Runner(stdout=b""), placement=reader, ledger=home).dispatch(
        {"lesson": "lrn-0000000a", "premise": "p1"}))
    assert "@reach" not in lines


def test_a_failing_placement_reader_is_its_own_answer(tmp_path):
    home = make_home(tmp_path)
    _lesson(home, "lrn-0000000a", [])

    def reader(ledger, record):
        raise RuntimeError("CANARY-detail")

    text = _ok(_tool(tmp_path, placement=reader, ledger=home).dispatch({"lesson": "lrn-0000000a"}))
    assert "could not be read (RuntimeError)" in text and "CANARY" not in text


# ===================================================================== #
# 4. Through the session's own server
# ===================================================================== #


def test_the_handler_runs_its_probes_off_the_event_loop(tmp_path):
    home = make_home(tmp_path)
    runner = Runner(stdout=b"dbus-broker.service\n")
    toolset = PremiseProbeTool(home, env=_env(tmp_path, runner)).toolset()
    spec = invocation.SessionSpec(
        surface="steward", prompt="p", cwd=tmp_path,
        timeout=20.0,
        containment=invocation.containment_for(
            "steward", allowed_tools="Read," + NAME, disallowed_tools="Bash",
            stage_dir=tmp_path / "run",
        ),
        log=lambda _m: None, ledger_home=home, mcp_toolset=toolset,
    )
    server = backend_mod.options_kwargs(spec)["mcp_servers"]["premises"]["instance"]
    text, is_error = _server_call(server, {"probe": OO7_PROBE})
    assert is_error is False and 'value: "dbus-broker.service"' in text
    assert runner.threads and all(t is not threading.main_thread() for t in runner.threads)
    # an error the model can correct arrives as an error reply
    text, is_error = _server_call(server, {"probe": {"kind": "path", "path": "~/.ssh/id_rsa"}})
    assert is_error is True


# ===================================================================== #
# 5. The seam: own tools beside the built-ins, for the steward only
# ===================================================================== #


def test_a_steward_session_keeps_its_builtin_tools_and_gains_its_own(tmp_path):
    home, spec = _steward_spec(tmp_path)
    kwargs = backend_mod.options_kwargs(spec)
    # No `tools` key: the built-ins are not switched off, as before.
    assert "tools" not in kwargs
    assert list(kwargs["mcp_servers"]) == ["premises"]
    assert kwargs["mcp_servers"]["premises"]["type"] == "sdk"
    # The floor is untouched: nothing pre-approved, strict MCP, no settings.
    assert kwargs["allowed_tools"] == []
    assert kwargs["strict_mcp_config"] is True and kwargs["setting_sources"] == []
    assert "Bash" in kwargs["disallowed_tools"]
    # Positive control: the same steward spec with no toolset (and the
    # five built-ins only) differs in nothing but the server.
    plain_containment = dataclasses.replace(
        spec.containment, allowed_tools="Read,Grep,Glob,Write,Edit"
    )
    plain = backend_mod.options_kwargs(
        dataclasses.replace(spec, mcp_toolset=None, containment=plain_containment)
    )
    assert plain["mcp_servers"] == {} and "tools" not in plain
    ignore = {"mcp_servers", "can_use_tool"}
    assert {k: v for k, v in plain.items() if k not in ignore} == {
        k: v for k, v in kwargs.items() if k not in ignore
    }


def test_the_seam_refuses_a_steward_whose_containment_and_toolset_disagree(tmp_path, monkeypatch):
    home, spec = _steward_spec(tmp_path)
    builtins = "Read,Grep,Glob,Write,Edit"

    def refusal(**changes) -> str:
        with pytest.raises(ValueError) as exc:
            backend_mod.options_kwargs(dataclasses.replace(spec, **changes))
        return str(exc.value)

    def contain(allowed: str):
        return dataclasses.replace(spec.containment, allowed_tools=allowed)

    # The toolset is served but the containment does not allow it.
    message = refusal(containment=contain(builtins))
    assert f"its own but not allowed: ['{NAME}']" in message
    # The containment allows a tool of another server.
    message = refusal(containment=contain(f"{builtins},{NAME},mcp__other__tool"))
    assert "allowed but not its own: ['mcp__other__tool']" in message
    # The containment names the tool but the session does not serve it (a
    # repair spec that dropped its toolset would look like this).
    message = refusal(mcp_toolset=None)
    assert f"allowed but not its own: ['{NAME}']" in message
    # An SDK without `mcp_servers` cannot serve the tool: refused.
    real_fields = backend_mod._dataclass_fields
    with monkeypatch.context() as patch:
        patch.setattr(
            backend_mod, "_dataclass_fields",
            lambda cls: [f for f in real_fields(cls) if f.name != "mcp_servers"],
        )
        assert "has no mcp_servers" in refusal()
    # Positive control: the real spec is accepted.
    assert list(backend_mod.options_kwargs(spec)["mcp_servers"]) == ["premises"]


def test_a_surface_other_than_the_steward_keeps_the_exact_names_rule(tmp_path):
    home = make_home(tmp_path)
    toolset = premise_tool.build_toolset(home)

    def spec_for(surface: str, allowed: str):
        return invocation.SessionSpec(
            surface=surface, prompt="p", cwd=tmp_path, timeout=20.0,
            containment=invocation.containment_for(
                surface, allowed_tools=allowed, disallowed_tools="Bash",
                stage_dir=tmp_path / "run",
            ),
            log=lambda _m: None, ledger_home=home, mcp_toolset=toolset,
        )

    worker_spec = dataclasses.replace(
        spec_for("overseer", NAME),
        surface="worker",
        containment=invocation.containment_for(
            "worker", allowed_tools=f"Read,{NAME}", disallowed_tools="Bash",
            home=str(home), stage_dir=tmp_path / "run", stage_on=False,
        ),
    )
    for spec in (spec_for("overseer", f"Read,{NAME}"), worker_spec):
        with pytest.raises(ValueError, match=r"allowed but not its own: \['Read'\]"):
            backend_mod.options_kwargs(spec)
    # Positive control: exactly its own tool is accepted there, and the
    # built-ins ARE switched off (`tools == []`), unlike the steward.
    ok = backend_mod.options_kwargs(spec_for("overseer", NAME))
    assert ok["tools"] == []


def test_the_charter_allows_the_probe_tool_and_nothing_else_from_another_server(tmp_path):
    home, spec = _steward_spec(tmp_path)
    can_use = charter_mod.build_can_use_tool(spec.containment, cwd=spec.cwd)

    def decide(tool: str) -> str:
        return asyncio.run(can_use(tool, {}, None)).behavior

    assert decide(NAME) == "allow"
    assert decide("Bash") == "deny"
    assert decide("mcp__premises__other_tool") == "deny"
    assert decide("mcp__other__premise_probe") == "deny"


# ===================================================================== #
# 6. The steward's wiring and the doctor's row
# ===================================================================== #


def test_the_stewards_spec_names_and_serves_the_probe_tool(tmp_path):
    home, spec = _steward_spec(tmp_path)
    assert steward._ALLOWED_TOOLS == "Read,Grep,Glob,Write,Edit," + NAME
    assert spec.containment.allowed_tools == steward._ALLOWED_TOOLS
    assert spec.mcp_toolset is not None
    assert spec.mcp_toolset.qualified_names == (NAME,)
    # It still has no shell.
    assert "Bash" in spec.containment.disallowed_tools.split(",")
    assert "Bash" not in spec.containment.allowed_tools.split(",")


def test_the_repair_round_carries_the_toolset(tmp_path):
    home, spec = _steward_spec(tmp_path)
    repair = steward._repair_spec(spec, "a stage file failed its check")
    assert repair.mcp_toolset is spec.mcp_toolset
    assert repair.containment is spec.containment
    # Positive control: the repair session builds, so the seam accepts it.
    assert list(backend_mod.options_kwargs(repair)["mcp_servers"]) == ["premises"]
    # Dropping the toolset (what a field-by-field rebuild that forgot it
    # would do) is refused by the seam, never run.
    with pytest.raises(ValueError, match="allowed but not its own"):
        backend_mod.options_kwargs(dataclasses.replace(repair, mcp_toolset=None))


def test_the_doctor_row_passes_with_the_probe_tool_and_fails_without_it(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    row = provider._steward_containment_row(home)
    assert row.verdict == "PASS"
    assert "premise_probe" in row.detail and "writes confined to the run directory" in row.detail

    # The containment forgets the tool.
    with monkeypatch.context() as patch:
        patch.setattr(steward, "_ALLOWED_TOOLS", "Read,Grep,Glob,Write,Edit")
        failed = provider._steward_containment_row(home)
        assert failed.verdict == "FAIL" and "own_tools=" in failed.detail
    assert provider._steward_containment_row(home).verdict == "PASS"  # control

    # The session stops serving it.
    with monkeypatch.context() as patch:
        patch.setattr(premise_tool, "build_toolset", lambda _home, **_k: None)
        assert provider._steward_containment_row(home).verdict == "FAIL"
    assert provider._steward_containment_row(home).verdict == "PASS"  # control

    # A tool that could write is not the probe tool the row allows.
    def writable(ledger, **_k):
        tool = premise_tool.PremiseProbeTool(ledger).tool()
        return invocation.McpToolset("premises", (dataclasses.replace(tool, read_only=False),))

    with monkeypatch.context() as patch:
        patch.setattr(premise_tool, "build_toolset", writable)
        assert provider._steward_containment_row(home).verdict == "FAIL"
