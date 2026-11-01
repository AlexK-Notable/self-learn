"""S-NEXT-attribution (cures CU-4): every ledger commit says who made it.

Written under the user's 2026-10-30 rule (tests run only for a significant
change): the orchestrator runs these once over the combined landing. Each
test names the mutation it was checked against.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from self_learn import (
    attribution,
    cli,
    gitops,
    miner,
    premise_sweep,
    serve,
    settings,
    steward,
    worker,
)
from self_learn.overseer import run as overseer_run
from support import git, init_repo, make_env

SRC = Path(__file__).resolve().parents[1] / "src" / "self_learn"


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    """A person's terminal: no agent marker, scratch cache."""
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _body(repo: Path) -> str:
    return git(repo, "log", "-1", "--format=%B").stdout


def _subject(repo: Path) -> str:
    return git(repo, "log", "-1", "--format=%s").stdout.strip()


def _final_block(body: str) -> list[str]:
    return body.strip().rpartition("\n\n")[2].splitlines()


# ------------------------------------------------------------ the two shells


def test_a_persons_config_set_says_by_human_and_an_agents_says_by_agent(tmp_path, monkeypatch):
    """Mutation: skip the stamp in `gitops.stage_and_commit` (pass `body`
    through) -> the person's commit has no trailer and this fails."""
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    assert cli.main(["config", "set", "miner.cap_max", "3"]) == 0
    assert _subject(env.ledger).startswith("self-learn: config set miner.cap_max")  # control
    assert _final_block(_body(env.ledger)) == ["By: human"]

    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["config", "set", "miner.cap_max", "4", "--note", "the user asked for 4"]) == 0
    body = _body(env.ledger)
    assert "the user asked for 4" in body
    assert _final_block(body) == ["By: agent"]


def test_a_persons_host_add_says_by_human(tmp_path, monkeypatch):
    """`host` was on S-102's "not covered" list. Mutation as above."""
    env = make_env(tmp_path)
    proj = tmp_path / "proj"
    init_repo(proj)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    assert cli.main(["host", "add", str(proj)]) == 0
    assert _subject(env.ledger).startswith("self-learn: host add project")
    assert _final_block(_body(env.ledger)) == ["By: human"]


def test_a_library_call_with_no_actor_is_left_unstamped(tmp_path):
    """The control for the two tests above: outside `cli.main` and every job
    nothing is set, so a commit body is exactly what the caller gave."""
    env = make_env(tmp_path)
    assert attribution.current_actor() is None
    (env.ledger / "x.txt").write_text("x\n", encoding="utf-8")
    gitops.stage_and_commit(env.ledger, [env.ledger / "x.txt"], "self-learn: x", "why")
    assert _body(env.ledger).strip() == "self-learn: x\n\nwhy"


def test_main_runs_in_its_own_context_so_nothing_leaks_into_the_next_call(tmp_path, monkeypatch):
    """Mutation: call `_attributed_main` directly instead of through
    `copy_context().run` and set the process actor without resetting it ->
    the actor is still `human` after `main` returns."""
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    assert cli.main(["config", "set", "miner.cap_max", "3"]) == 0
    assert attribution.current_actor() is None
    assert attribution.authority() is None


# --------------------------------------------------------------- the jobs


class _Probe(Exception):
    pass


@pytest.mark.parametrize(
    "module, actor",
    [
        (worker, "worker"),
        (miner, "miner"),
        (steward, "steward"),
        (premise_sweep, "sweep"),
        (overseer_run, "overseer"),
    ],
    ids=["worker", "miner", "steward", "sweep", "overseer"],
)
def test_each_job_entry_point_commits_as_the_job_even_from_an_agents_shell(
    module, actor, tmp_path, monkeypatch
):
    """A worker auto-kicked from an agent's command line is still `worker`.
    The probe replaces the module's `Path` (each entry point's first call)
    and reads the actor there. Mutation: drop `@attribution.as_job("worker")`
    from `worker.run` -> the worker case reads `agent`."""
    seen: list[str | None] = []

    def probe(*_args, **_kwargs):
        seen.append(attribution.current_actor())
        raise _Probe()

    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(module, "Path", probe)
    with attribution.process("agent"):
        assert attribution.current_actor() == "agent"  # control
        with pytest.raises(_Probe):
            module.run(tmp_path)
        assert attribution.current_actor() == "agent"  # the job's actor ends with it
    assert seen == [actor]


def test_serve_runs_each_scheduled_job_under_its_actor(tmp_path):
    """Mutation: drop the `attribution.job(...)` span in `run_one_job` (and
    keep the entry points) -> a job reaching the ledger some other way reads
    `serve`."""
    with attribution.process("serve"):
        record = serve.run_one_job(
            tmp_path, serve.Job("premises", "premises", attribution.current_actor)
        )
        mine = serve.run_one_job(tmp_path, serve.Job("mine", "miner", attribution.current_actor))
        other = serve.run_one_job(tmp_path, serve.Job("other", "x", attribution.current_actor))
    assert (record.result, mine.result, other.result) == ("sweep", "miner", "serve")


# ---------------------------------------------------------- the stamp itself


def _commit(repo: Path, body: str | None) -> str:
    (repo / "f.txt").write_text(f"{body}\n", encoding="utf-8")
    gitops.stage_and_commit(repo, [repo / "f.txt"], "self-learn: probe", body)
    return _body(repo)


def test_a_sheet_lines_execution_block_stays_the_one_final_block(tmp_path):
    """Inside the job that runs the sheet (and in the daemon around it).
    Mutation: stamp unconditionally (append `By: <actor>` whatever the body
    ends in) -> a second block follows the execution block."""
    repo = tmp_path / "ledger"
    init_repo(repo)
    block = "By: steward\nCase: case-0000aaaa\nSheet: 0123abcd\nItem: 1"
    with attribution.process("serve"), attribution.job("steward"):
        body = _commit(repo, f"moved\n\n{block}")
    assert body.strip().endswith(block)
    assert body.count("By:") == 1
    with attribution.process("serve"):
        body = _commit(repo, f"moved again\n\n{block}")
    assert body.strip().endswith(block)
    assert body.count("By:") == 1


@pytest.mark.parametrize("shell", ["agent", "human"])
def test_an_execution_block_typed_into_a_shell_cannot_pass_for_the_steward(shell, tmp_path):
    """Gate r1 finding 2: a note ending in a well-formed execution block (a
    tier-A `config set`'s body is the note) is not the steward's in a shell.
    Mutation: accept a sheet runner's execution block in a shell too (drop
    `actor not in SHELL_ACTORS` from `_owns`) -> it stays the final block."""
    repo = tmp_path / "ledger"
    init_repo(repo)
    block = "By: steward\nCase: case-0000aaaa\nSheet: 0123abcd\nItem: 1"
    with attribution.process(shell):
        body = _commit(repo, f"why\n\n{block}")
    assert block in body  # control: the note's text is kept as written
    assert _final_block(body) == [f"By: {shell}"]


def test_a_job_commit_whose_text_ends_in_by_human_is_still_the_jobs(tmp_path):
    """Gate r1 finding 2: model-written case text reaches the body; inside
    the steward's job a body ending `By: human` gets the steward's block.
    Mutation: keep any final `By:` block inside a job (`_owns` returns True
    for every non-shell actor) -> the commit reads `By: human`."""
    repo = tmp_path / "ledger"
    init_repo(repo)
    with attribution.process("serve"), attribution.job("steward"):
        body = _commit(repo, "the case question\n\nBy: human")
    assert _final_block(body) == ["By: steward"]


def test_the_workers_own_analyst_trailer_is_kept_as_its_block(tmp_path):
    """The worker routes with `by="analyst"`; that block is the worker's own,
    so no second block follows it. Mutation: empty `_JOB_OWN_TRAILERS` ->
    `By: worker` follows `By: analyst`."""
    repo = tmp_path / "ledger"
    init_repo(repo)
    with attribution.process("agent"), attribution.job("worker"):
        body = _commit(repo, "routed\n\nBy: analyst")
    assert _final_block(body) == ["By: analyst"]
    assert body.count("By:") == 1
    with attribution.process("agent"), attribution.job("worker"):  # control
        body = _commit(repo, "routed\n\nBy: steward")
    assert _final_block(body) == ["By: worker"]


def test_a_note_ending_in_another_actors_by_line_cannot_pass_for_it_in_a_shell(tmp_path):
    """A note typed into an agent's shell that ends in `By: steward` gets the
    shell's own block after it. Mutation: keep any final `By:` block as is ->
    the census would read `steward`."""
    repo = tmp_path / "ledger"
    init_repo(repo)
    with attribution.process("agent"):
        body = _commit(repo, "why\n\nBy: steward")
    assert _final_block(body) == ["By: agent"]
    with attribution.process("agent"):  # control: its own block is left alone
        body = _commit(repo, "why 2\n\nBy: agent")
    assert body.count("By: agent") == 1


def test_an_authority_in_force_records_the_agent_the_grant_and_the_reason(tmp_path):
    repo = tmp_path / "ledger"
    init_repo(repo)
    granted = attribution.Authority("grant", "stmt-0000aaaa", "the user said to switch it")
    with attribution.process("agent"), attribution.acting(granted):
        body = _commit(repo, None)
    assert "the user said to switch it" in body
    assert _final_block(body) == ["By: agent", "Grant: stmt-0000aaaa"]
    with attribution.process("agent"), attribution.acting(granted):
        body = _commit(repo, "why\n\nBy: agent")  # a verb's own block gains the grant line
    assert _final_block(body) == ["By: agent", "Grant: stmt-0000aaaa"]
    assert body.count("By:") == 1
    assert "the user said to switch it" in body


def test_under_an_authority_a_block_the_agent_typed_cannot_say_human(tmp_path):
    """Gate r1 finding 2: `host add --note '...\n\nBy: human\nGrant: stmt-...'`.
    Mutation: keep any final block holding `Grant:` (the old rule) -> the
    commit ends `By: human`."""
    repo = tmp_path / "ledger"
    init_repo(repo)
    granted = attribution.Authority("grant", "stmt-0000aaaa", "moving the host")
    with attribution.process("agent"), attribution.acting(granted):
        body = _commit(repo, "moving the host\n\nBy: human\nGrant: stmt-0000aaaa")
    assert _final_block(body) == ["By: agent", "Grant: stmt-0000aaaa"]
    with attribution.process("agent"), attribution.acting(granted):
        body = _commit(repo, "x\n\nBy: agent\nGrant: stmt-0000ffff")  # another grant's
    assert _final_block(body) == ["By: agent", "Grant: stmt-0000aaaa"]


def test_a_grant_puts_the_users_words_in_every_commit_made_under_it(tmp_path):
    """Gate r1 finding 6. Mutation: `Authority.paragraphs` returns only the
    reason -> the words are not in the body."""
    repo = tmp_path / "ledger"
    init_repo(repo)
    granted = attribution.Authority(
        "grant", "stmt-0000aaaa", "the user asked", words="never  tell me\nX is waiting"
    )
    with attribution.process("agent"), attribution.acting(granted):
        body = _commit(repo, None)
    assert "Under the user's standing grant (stmt-0000aaaa): \"never tell me X is waiting\"" in body
    assert _final_block(body) == ["By: agent", "Grant: stmt-0000aaaa"]
    with attribution.process("agent"), attribution.acting(granted):  # stamped twice: once
        again = attribution.stamp(attribution.stamp("b"))
    assert again is not None and again.count("Under the user's standing grant") == 1
    assert again.count("By:") == 1


# --------------------------------------------- every ledger commit site stamps


def _commit_calls() -> list[tuple[str, int, ast.Call]]:
    out = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "commit"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "gitops"
            ):
                out.append((path.relative_to(SRC).as_posix(), node.lineno, node))
    return out


def test_every_direct_ledger_commit_passes_its_body_through_the_stamp():
    """Every `gitops.commit(home, ...)` (the ledger home) passes
    `body=attribution.stamp(...)`; host-repo commits (any other first
    argument) never do. Mutation: drop the stamp from `telemetry.flush`'s
    commit -> listed here."""
    calls = _commit_calls()
    ledger = [c for c in calls if isinstance(c[2].args[0], ast.Name) and c[2].args[0].id == "home"]
    assert len(ledger) >= 6, ledger  # control: the walk finds the six ledger sites
    missing = []
    for where, line, call in ledger:
        body = next((kw.value for kw in call.keywords if kw.arg == "body"), None)
        if not (
            isinstance(body, ast.Call)
            and isinstance(body.func, ast.Attribute)
            and body.func.attr == "stamp"
        ):
            missing.append(f"{where}:{line}")
    assert missing == []
    hosts = [c for c in calls if c not in ledger]
    assert hosts  # control
    for where, line, call in hosts:
        body = next((kw.value for kw in call.keywords if kw.arg == "body"), None)
        assert not (isinstance(body, ast.Call) and getattr(body.func, "attr", "") == "stamp"), (
            f"{where}:{line} stamps a host-repo commit"
        )
