"""The model-free commands on Windows (Stage 4 integration, batches B1-B3).

Each batch drives the real ``self-learn`` console script against a scratch
profile, ledger and host whose paths carry a space, a non-ASCII letter and,
for the host, brackets. On Windows every batch runs as PowerShell scripts in
separate ``pwsh`` processes, one command per step; on Linux the same steps
run as one process each, so the sequence is checked on both systems. A
``sitecustomize`` observer loaded by every CLI interpreter fails any child
process other than git, which is what "no model, no spawn, no systemd, no
desktop program" means here. After each script the ledger's status is
clean, ``git fsck`` passes and every committed file is LF.

The ledger write helpers are checked separately on Windows: a name with
brackets is a literal path, so a sibling the brackets would match as a
pattern is never staged or committed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_windows_capture import git, scratch_env

windows = pytest.mark.skipif(os.name != "nt", reason="native Windows ledger verbs")

CLI = Path(sys.executable).with_name("self-learn.exe" if os.name == "nt" else "self-learn")

# Loaded by every CLI interpreter through PYTHONPATH. Any child other than
# git raises inside the CLI (the step then fails); the fake embedder stands
# in for Gemini so `index build` embeds without a network or a key.
OBSERVER = r"""
import os, sys
from pathlib import Path

def observe(program):
    name = Path(str(program)).name.lower()
    with open(os.environ['W4_OBSERVED'], 'a', encoding='utf-8') as stream:
        print(name, file=stream)
    if name not in ('git', 'git.exe'):
        raise RuntimeError('unexpected child ' + name)

if os.name == 'nt':
    import win32process
    original = win32process.CreateProcess
    def create(program, *args):
        observe(program)
        return original(program, *args)
    win32process.CreateProcess = create

def audit(event, args):
    if event != 'subprocess.Popen':
        return
    program, argv = args[0], args[1]
    if program is None:
        if isinstance(argv, (list, tuple)):
            program = argv[0]
        elif os.name == 'nt':
            import win32api
            program = win32api.CommandLineToArgv(argv)[0]
        else:
            program = argv
    observe(os.fsdecode(program) if isinstance(program, bytes) else program)

sys.addaudithook(audit)

if os.environ.get('W4_FAKE_EMBED'):
    from self_learn.index import fake, registry
    registry.load_provider = lambda name=None, *, dim=None: (fake.FakeEmbeddingProvider(), '')
"""

# One PowerShell process runs every step of one script: the CLI as a native
# command, its stdout and stderr captured separately, its exit code kept.
PWSH = r"""
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$steps = Get-Content -Raw -Encoding utf8 $env:W4_STEPS | ConvertFrom-Json
$errFile = Join-Path $env:W4_ROOT 'step-stderr.txt'
$results = [Collections.ArrayList]::new()
foreach ($step in $steps) {
  Set-Location -LiteralPath $step.cwd
  $argv = @($step.argv)
  $out = & $env:W4_CLI @argv 2> $errFile
  $rc = $LASTEXITCODE
  $err = if (Test-Path -LiteralPath $errFile) { Get-Content -Raw -Encoding utf8 -LiteralPath $errFile } else { '' }
  [void]$results.Add(@{argv = $argv; rc = $rc; out = (@($out) -join "`n"); err = "$err"})
}
@{pid = $PID; results = $results} | ConvertTo-Json -Depth 6 -Compress |
  Set-Content -Encoding utf8 -LiteralPath $env:W4_RESULTS
"""

FORBIDDEN = ("CLAUDE", "CODEX", "HERMES", "AI_AGENT", "SELF_LEARN_OVERRIDE", "SELF_LEARN_ANALYST", "GEMINI", "SELF_LEARN_GEMINI")


class Session:
    """A scratch profile, ledger, cache and one registered project host."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "w4 été"
        self.root.mkdir()
        env = scratch_env(self.root)
        for key in list(env):
            if key.startswith(FORBIDDEN):
                del env[key]
        self.ledger = self.root / "lédger home"
        env["SELF_LEARN_HOME"] = str(self.ledger)
        observer = self.root / "observer"
        observer.mkdir()
        (observer / "sitecustomize.py").write_text(OBSERVER, encoding="utf-8")
        self.observed = self.root / "observed.txt"
        env.update(PYTHONPATH=str(observer), W4_OBSERVED=str(self.observed), W4_ROOT=str(self.root),
                   W4_CLI=str(CLI), W4_FAKE_EMBED="1", PYTHONUTF8="1",
                   SELF_LEARN_WORKER_AUTOKICK="0", SELF_LEARN_MINER_AUTOKICK="0",
                   SELF_LEARN_EMBED_PROVIDER="gemini")
        if os.name == "nt":
            # The kicks are disabled inside worker.kick and miner.maybe_kick on
            # Windows; asking for them shows the switch is not what stops them.
            env.update(SELF_LEARN_WORKER_AUTOKICK="1", SELF_LEARN_MINER_AUTOKICK="1")
        self.env = env
        self.profile = Path(env["USERPROFILE"])
        self.claude = Path(env["SELF_LEARN_CLAUDE_DIR"])
        git(self.root, "config", "--global", "core.autocrlf", "true", env=env)
        self.proj = self.root / "projet été [1]"
        self.proj.mkdir()
        git(self.proj, "init", "-q", env=env)
        git(self.proj, "config", "core.autocrlf", "false", env=env)
        (self.proj / "CLAUDE.md").write_bytes("# Projet été\r\n\r\nTeam notes.\r\n".encode())
        (self.proj / ".gitignore").write_bytes(b"CLAUDE.local.md\r\n")
        git(self.proj, "add", "--", "CLAUDE.md", ".gitignore", env=env)
        git(self.proj, "commit", "-q", "-m", "seed", env=env)
        self.processes: set[int] = set()

    def git(self, repo: Path, *args: str) -> bytes:
        return git(repo, *args, env=self.env)

    def script(self, *steps, cwd: Path | None = None) -> list[dict]:
        """Run *steps* (each an argv list, or ``(argv, expected_rc)``) and
        return each result; a step with an unexpected exit code fails."""
        plan = []
        for step in steps:
            argv, rc = (step, 0) if isinstance(step, list) else step
            plan.append({"argv": [str(a) for a in argv], "rc": rc, "cwd": str(cwd or self.proj)})
        if os.name == "nt":
            steps_file, results_file = self.root / "steps.json", self.root / "results.json"
            steps_file.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            results_file.unlink(missing_ok=True)
            env = {**self.env, "W4_STEPS": str(steps_file), "W4_RESULTS": str(results_file)}
            proc = subprocess.run(["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", PWSH],
                                  cwd=self.root, env=env, capture_output=True, timeout=900)
            assert proc.returncode == 0, (proc.stdout, proc.stderr)
            payload = json.loads(results_file.read_text(encoding="utf-8-sig"))
            self.processes.add(payload["pid"])
            results = payload["results"]
            if isinstance(results, dict):
                results = [results]
            for result in results:  # PowerShell ends each captured line with CRLF
                result["out"] = (result["out"] or "").replace("\r\n", "\n")
                result["err"] = (result["err"] or "").replace("\r\n", "\n")
        else:
            results = []
            for item in plan:
                proc = subprocess.run([str(CLI), *item["argv"]], cwd=item["cwd"], env=self.env,
                                      capture_output=True, timeout=300)
                results.append({"argv": item["argv"], "rc": proc.returncode,
                                "out": proc.stdout.decode("utf-8").rstrip("\n"),
                                "err": proc.stderr.decode("utf-8")})
                self.processes.add(-len(self.processes) - 1)
        assert len(results) == len(plan)
        for item, result in zip(plan, results):
            if item["rc"] is not None and result["rc"] != item["rc"]:
                pytest.fail(f"expected exit {item['rc']}: " + json.dumps(result, ensure_ascii=True, indent=1))
        return results

    def json(self, result: dict):
        return json.loads(result["out"])

    def check_ledger(self):
        """The ledger after a script: clean, sound, every committed file LF,
        and no child process but git."""
        assert self.git(self.ledger, "status", "--porcelain", "-z", "--untracked-files=all") == b""
        self.git(self.ledger, "fsck", "--strict", "--no-progress")
        eol = self.git(self.ledger, "ls-files", "--eol", "-z").split(b"\0")
        rows = [row for row in eol if row]
        assert rows  # positive control: the ledger has committed files
        bad = [row for row in rows if not row.split()[0] in (b"i/lf", b"i/none", b"i/")]
        assert bad == []
        observed = set(self.observed.read_text(encoding="utf-8").split()) if self.observed.exists() else set()
        assert observed and observed <= {"git", "git.exe"}, observed

    def setup_lessons(self, n: int = 3, scope: str = "project") -> list[str]:
        results = self.script(
            ["init"], ["host", "add", str(self.proj)],
            *[["teach", f"--{scope}", "--no-push", "--json", "--fact", f"Synthetic fact {i} café"]
              for i in range(n)],
        )
        return [self.json(r)["id"] for r in results[2:]]


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path.resolve())


# ----------------------------------------------------------------- B1 read-only

STAGE = """kind: resolution
trigger: nightly
outcome: reject
records: [{rid}]
scope: project
question: what should become of this pending lesson?
evidence:
  - ref: transcript:547ce0a4#L137
    quote: It exited cleanly, but the stall carried on.
decision:
  verb: reject
  because: the evidence settles it
  confidence: settled
dependencies: {{statements: [], user_model: [], conditions: [], capabilities: []}}
"""


def test_b1_read_only_commands(session):
    s = session
    # Positive control: the observer fails a child that is not git.
    probe = subprocess.run([sys.executable, "-c", "import subprocess; subprocess.run(['synthetic-sdk.exe'])"],
                           env=s.env, capture_output=True, timeout=60)
    assert probe.returncode and b"unexpected child synthetic-sdk.exe" in probe.stderr
    assert s.observed.read_text(encoding="utf-8").split() == ["synthetic-sdk.exe"]
    s.observed.unlink()
    ids = s.setup_lessons(3)
    stage = s.root / "stage été.yaml"
    stage.write_text(STAGE.format(rid=ids[2]), encoding="utf-8")
    setup = s.script(
        ["teach", "--user", "--no-push", "--json", "--fact", "User fact über"],
        ["route", ids[0], "--dest", "claude-md", "--no-push", "--json"],
        ["case", "record", str(stage), "--actor", "human", "--json"],
        ["statement", "add", "--verbatim", "Keep it small.", "--ref", "transcript:synthetic#L1",
         "--recorded-by", "human", "--json"],
    )
    user_id, case_id = s.json(setup[0])["id"], s.json(setup[2])["case"]
    statement_id = s.json(setup[3])["statement"]
    s.check_ledger()
    head = s.git(s.ledger, "rev-parse", "HEAD")
    r = s.script(
        ["status", "--json"], ["status"], ["status", "--fast"],
        ["report", "--json"], ["report"],
        ["case", "list", "--json"], ["case", "show", case_id, "--json"],
        ["statement", "list", "--json"], ["grant", "list", "--json"],
        ["notice", "list", "--json"], ["notice", "list", "--all"],
        ["index", "status", "--json"],
        ["select", "--query", "synthetic fact café", "--project", str(s.proj), "--no-embed", "--json"],
        ["skill", "list", "--json"], ["skill", "script", "list"],
        ["doctor", "settings"],
        ["config", "get"], ["config", "get", "worker.coalesce_secs", "--json"],
        ["overseer", "status", "--json"],
        (["overseer", "open"], 1), (["proposal", "validate", ids[1]], 1),
        ["host", "list"], ["show", user_id, "--json"], ["list", "--json"],
    )
    status = s.json(r[0])
    assert status["total_pending"] == 3 and status["total_unreadable"] == 0
    assert any(b["label"] == s.proj.name and Path(b["path"]) == s.proj for b in status["buckets"]), status
    assert "pending" in r[1]["out"] and r[2]["out"]
    assert s.json(r[3])["routed_ever"] == 1 and r[4]["out"]
    assert [row["case"] for row in s.json(r[5])] == [case_id]
    assert case_id in r[6]["out"] and ids[2] in r[6]["out"]
    assert [row["id"] for row in s.json(r[7])] == [statement_id]
    assert s.json(r[8])["rows"] == [] and s.json(r[9]) == []
    assert "none" in r[10]["out"]
    assert s.json(r[11])["built"] is False
    selected = s.json(r[12])
    assert [row["id"] for row in selected["lessons"]] == [ids[0]], selected
    assert "registrations" in r[13]["out"]
    assert "worker.coalesce_secs" in r[15]["out"] and "doctor: " in r[15]["out"]
    assert "worker.coalesce_secs" in r[16]["out"]
    assert s.json(r[17])[0]["name"] == "worker.coalesce_secs"
    assert s.json(r[18])["last"] is None
    assert "no latest report" in r[19]["err"] and "no proposal sibling" in r[20]["err"]
    assert str(s.proj) in r[21]["out"]
    assert s.json(r[22])["id"] == user_id
    assert {row["id"] for row in s.json(r[23])} == {ids[1], ids[2], user_id}
    assert s.git(s.ledger, "rev-parse", "HEAD") == head  # nothing read-only moved HEAD
    s.check_ledger()


# ---------------------------------------------------------- B2 ledger mutations


def show(s: Session, rid: str) -> dict:
    return s.json(s.script(["show", rid, "--json"])[0])


def test_b2_a_lessons_life_without_a_model(session):
    s = session
    remote = s.root / "remote été.git"
    s.git(s.root, "init", "-q", "--bare", str(remote))
    ids = s.setup_lessons(6)
    a, b, c, d, e, f = ids
    s.git(s.ledger, "remote", "add", "origin", str(remote))
    branch = s.git(s.ledger, "branch", "--show-current").decode().strip()
    s.git(s.ledger, "push", "-q", "-u", "origin", branch)
    transcript = s.claude / "projects" / "w4 projet" / "synthetic.jsonl"
    transcript.parent.mkdir(parents=True)
    rows = [{"type": "user", "message": {"content": "Keep it small."}},
            {"type": "user", "message": {"content": "You may record lessons for me."}}]
    transcript.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    s.check_ledger()
    r = s.script(
        ["note", a, "--append", "Extra context é", "--no-push", "--json"],
        ["revise", a, "--section", "Fact", "--text", "Synthetic fact zero, reworded", "--because",
         "clearer wording", "--no-push"],
        ["defer", b, "--until", "2099-01-01", "--no-push", "--json"],
        ["undefer", b, "--no-push"],
        ["reject", c, "--note", "not durable", "--no-push", "--json"],
        ["reopen", c, "--no-push"],
        ["supersede", d, e, "--no-push", "--json"],
        ["link", "contradicts", a, f, "--no-push"],
        ["route", f, "--dest", "claude-md", "--no-push"],
        ["followup", "add", f, "--action", "Check the wording", "--no-push"],
        ["followup", "done", f, "--note", "checked", "--no-push"],
        ["statement", "add", "--verbatim", "You may record lessons for me.", "--ref",
         "transcript:synthetic#L2", "--recorded-by", "human", "--json"],
    )
    statement_id = s.json(r[-1])["statement"]
    s.check_ledger()
    assert show(s, b)["status"] == "pending" and show(s, c)["status"] == "pending"
    assert show(s, d)["status"] == "superseded"
    second = s.root / "second host"
    second.mkdir()
    s.git(second, "init", "-q")
    moved = s.root / "moved host"
    r = s.script(
        ["grant", "add", "--statement", statement_id, "--note", "a standing grant", "--json"],
        ["grant", "list", "--json"],
        ["config", "set", "worker.coalesce_secs", "300", "--note", "shorter window"],
        ["config", "get", "worker.coalesce_secs", "--json"],
        ["config", "unset", "worker.coalesce_secs", "--note", "back to the default"],
        ["host", "add", str(second)],
        ["host", "set-mode", str(second), "plain", "--note", "plain host"],
        ["reconcile", "--no-push", "--json"],
        ["index", "build", "--json"], ["index", "status", "--json"],
        ["index", "related", a, "--json"], ["index", "groups", "--json"],
        ["canary", "plant", "--lesson", "Synthetic canary lesson"],
        ["telemetry", "note", "offer-made"], ["telemetry", "flush"],
        ["bucket", "prune", "--dry-run", "--no-push"],
        ["push"],
    )
    grant_id = s.json(r[0])["grant"]
    assert [row["id"] for row in s.json(r[1])["rows"]] == [grant_id]
    assert s.json(r[3])
    built = s.json(r[8])
    assert built["embedded"], built  # the fake embedder ran
    assert s.json(r[9])["built"] is True
    assert s.git(remote, "rev-parse", branch) == s.git(s.ledger, "rev-parse", "HEAD")
    s.check_ledger()
    second.rename(moved)
    r = s.script(
        ["grant", "revoke", grant_id, "--note", "no longer needed"],
        ["host", "rebind", str(second), str(moved), "--note", "the folder moved"],
        ["host", "remove", str(moved), "--note", "not a project any more"],
        ["host", "list"],
    )
    assert str(moved) not in r[-1]["out"] and str(s.proj) in r[-1]["out"]
    s.check_ledger()


# ------------------------------------------------------------- B3 canon writes

BEGIN = b"<!-- self-learn:begin"
USER_SEED = b"# Mine\r\n\r\nKeep this line.\r\n"
LOCAL_SEED = b"# Local\r\n\r\nMy own note.\r\n"
RULES_SEED = b"---\r\ndescription: Windows rules\r\n---\r\n# Windows rules\r\n"
NOTES_SEED = b"# Notes\r\n\r\nOld entry.\r\n"
SKILL = "w4-skill"
SKILL_MD = ("---\nname: {name}\ndescription: \"Use when checking the Windows port of the ledger verbs end to end.\"\n"
            "---\n\n# Windows port\n\nHow the pieces fit; the steps are in [the list](references/steps.md).\n")


def only_crlf(data: bytes) -> bool:
    """Windows keeps each file's CRLF; Linux writes the compiler's LF text."""
    if os.name != "nt":
        return True
    return b"\n" not in data.replace(b"\r\n", b"") and b"\r" not in data.replace(b"\r\n", b"")


def starts(data: bytes, seed: bytes) -> bool:
    return data.startswith(seed if os.name == "nt" else seed.replace(b"\r\n", b"\n"))


def is_link(path: Path) -> bool:
    if os.name == "nt":
        return os.path.isjunction(path)
    return path.is_symlink()


def write_draft(folder: Path, name: str) -> Path:
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD.format(name=name), encoding="utf-8")
    (folder / "references" / "steps.md").write_text("# Steps\n\nOne row per step.\n", encoding="utf-8")
    return folder


def test_b3_canon_writes_in_a_crlf_profile(session):
    s = session
    p = s.proj
    (p / ".claude" / "rules").mkdir(parents=True)
    (p / "references").mkdir()
    (p / ".claude" / "rules" / "windows.md").write_bytes(RULES_SEED)
    (p / "references" / "notes.md").write_bytes(NOTES_SEED)
    s.git(p, "add", "--", ".claude/rules/windows.md", "references/notes.md")
    s.git(p, "commit", "-q", "-m", "rules and notes")
    (p / "CLAUDE.local.md").write_bytes(LOCAL_SEED)
    user_md = s.claude / "CLAUDE.md"
    user_md.write_bytes(USER_SEED)
    skills_root = s.root / "skills root"
    skills_root.mkdir()
    s.git(skills_root, "init", "-q")
    s.git(skills_root, "config", "core.autocrlf", "false")
    (skills_root / ".claude-plugin").mkdir()
    (skills_root / ".claude-plugin" / "marketplace.json").write_bytes(
        b'{\r\n  "name": "w4-skills",\r\n  "plugins": []\r\n}\r\n')
    s.git(skills_root, "add", "--", ".claude-plugin/marketplace.json")
    s.git(skills_root, "commit", "-q", "-m", "marketplace")
    (s.claude / "skills").mkdir()
    lessons = s.setup_lessons(5)
    user = s.json(s.script(["teach", "--user", "--no-push", "--json", "--fact", "User fact ö"])[0])["id"]
    project, local, rules, shelf, moved = lessons
    r = s.script(
        ["route", user, "--dest", "claude-md", "--no-push"],
        ["route", project, "--dest", "claude-md", "--no-push"],
        ["route", local, "--dest", "claude-md:local", "--no-push"],
        ["route", rules, "--dest", "claude-md:rules:windows", "--no-push"],
        ["route", shelf, "--dest", "reference:notes.md", "--no-push"],
        ["route", moved, "--dest", "claude-md", "--no-push"],
    )
    for path in (user_md, p / "CLAUDE.md", p / "CLAUDE.local.md", p / ".claude" / "rules" / "windows.md",
                 p / "references" / "notes.md"):
        data = path.read_bytes()
        assert only_crlf(data), path
    assert starts(user_md.read_bytes(), USER_SEED) and BEGIN in user_md.read_bytes()
    assert starts((p / "CLAUDE.local.md").read_bytes(), LOCAL_SEED)
    assert starts((p / "references" / "notes.md").read_bytes(), NOTES_SEED)
    assert s.git(p, "status", "--porcelain", "-z") == b""
    s.check_ledger()
    files = [user_md, *(p / n for n in ("CLAUDE.md", "CLAUDE.local.md", ".claude/rules/windows.md",
                                         "references/notes.md"))]
    before = {f: f.read_bytes() for f in files}
    head = s.git(s.ledger, "rev-parse", "HEAD")
    s.script(["recompile", "--no-push"], ["recompile", "--no-push"])
    assert {f: f.read_bytes() for f in files} == before
    assert s.git(s.ledger, "rev-parse", "HEAD") == head

    draft = write_draft(s.root / "draft", SKILL)
    loose = write_draft(s.claude / "skills" / "w4-loose", "w4-loose")
    r = s.script(
        ["host", "add", str(skills_root), "--skills-root"],
        ["skill", "write", SKILL, "--from", str(draft), "--no-push", "--json"],
        ["skill", "register", "w4-loose", "--note", "keep this skill current", "--json"],
        ["skill", "list", "--json"],
    )
    link = s.claude / "skills" / SKILL
    assert is_link(link) and (link / "SKILL.md").is_file()
    assert is_link(s.claude / "skills" / "w4-loose")
    market = (skills_root / ".claude-plugin" / "marketplace.json").read_bytes()
    assert SKILL.encode() in market and only_crlf(market)
    r = s.script(
        ["skill", "rename", SKILL, "w4-renamed", "--no-push", "--json"],
        ["skill", "retire", "w4-renamed", "--no-push", "--json"],
        ["skill", "list", "--json"],
    )
    assert not os.path.lexists(link)
    market = (skills_root / ".claude-plugin" / "marketplace.json").read_bytes()
    assert b"w4-loose" in market and b"w4-renamed" not in market and only_crlf(market)
    assert s.git(skills_root, "status", "--porcelain", "-z") == b""
    s.check_ledger()

    memory = s.root / "memory été"
    memory.mkdir()
    (memory / "MEMORY.md").write_bytes("- [One](one.md) — first\r\n- [Two](two.md) — second\r\n".encode())
    for name in ("one", "two"):
        (memory / f"{name}.md").write_bytes(
            f"---\r\nname: {name}\r\ndescription: Memory {name}\r\nmetadata:\r\n  type: project\r\n---\r\n"
            f"\r\nBody {name}.\r\n".encode())
    sheet = s.root / "sheet.yaml"
    pending = s.json(s.script(["teach", "--project", "--no-push", "--json", "--fact", "Batch fact"])[0])["id"]
    hooked = s.json(s.script(["teach", "--project", "--no-push", "--json", "--fact", "Hook fact"])[0])["id"]
    sheet.write_text(f"version: 1\nitems:\n  - id: {pending}\n    verb: route\n    dest: claude-md\n"
                     f"  - id: {hooked}\n    verb: route\n    dest: hook\n", encoding="utf-8")
    r = s.script(
        ["replace", user, "--fact", "Rewritten user fact", "--because", "clearer wording", "--no-push"],
        ["retire", project, "--covered-by", "claude-md:team-notes", "--no-push"],
        ["reroute", moved, "--dest", "claude-md:local", "--no-push"],
        (["batch", str(sheet), "--no-push", "--json"], 8),  # EXIT_BATCH_PARTIAL
        ["import", "--memory", str(memory)],
        ["list", "--json"],
    )
    batch = r[3]
    hook_refusal = (f"{hooked}: the hook destination is unavailable in Windows capture mode"
                    if os.name == "nt" else f"{hooked}: a hook route is refused inside a batch (S-29)")
    assert hook_refusal in batch["out"] + batch["err"], batch
    assert show(s, pending)["status"] == "routed" and show(s, hooked)["status"] == "pending"
    assert b"Rewritten user fact" in user_md.read_bytes() and only_crlf(user_md.read_bytes())
    assert b"Projet" not in b"" and project.encode() not in (p / "CLAUDE.md").read_bytes()
    assert moved.encode() in (p / "CLAUDE.local.md").read_bytes()
    one = next(row["id"] for row in s.json(r[-1]) if "Memory one" in row["title"])
    s.script(["reject", one, "--no-push"], ["prune-memory", str(memory)])
    assert not (memory / "one.md").exists() and (memory / "two.md").exists()
    assert starts((memory / "MEMORY.md").read_bytes(), "- [Two](two.md) — second\r\n".encode())
    assert s.git(p, "status", "--porcelain", "-z") == b""
    s.check_ledger()


# ------------------------------------------------- hook destinations, Windows


@windows
def test_windows_hook_destinations_refuse_before_writing(session):
    s = session
    fresh, hooked, plain = s.setup_lessons(3)
    s.script(["route", hooked, "--dest", "claude-md", "--no-push"], ["route", plain, "--dest", "claude-md", "--no-push"])
    # A lesson routed to a hook on another machine (a ledger cloned from Linux).
    record = next(s.ledger.rglob(f"{hooked}.md"))
    text = record.read_bytes().replace(
        b"  destination: claude-md\n",
        b"  destination: hook\n  hook:\n    script_path: .claude/hooks/guard.sh\n    script: 'exit 0'\n")
    assert b"destination: hook" in text
    record.write_bytes(text)
    s.git(s.ledger, "add", "--", str(record.relative_to(s.ledger)).replace("\\", "/"))
    s.git(s.ledger, "commit", "-q", "-m", "a hook lesson from another machine")
    head = s.git(s.ledger, "rev-parse", "HEAD")
    host_head = s.git(s.proj, "rev-parse", "HEAD")
    # Every guard is checked on its own (no early stop), so one run shows each.
    refusals = [
        ("route to a hook", fresh, ["route", fresh, "--dest", "hook", "--no-push"]),
        ("route --dry-run to a hook", fresh, ["route", fresh, "--dest", "hook", "--dry-run"]),
        ("retire a hook lesson", hooked, ["retire", hooked, "--covered-by", "claude-md:team-notes", "--no-push"]),
        ("reroute from a hook", hooked, ["reroute", hooked, "--dest", "claude-md:local", "--no-push"]),
        ("reroute to a hook", plain, ["reroute", plain, "--dest", "hook", "--no-push"]),
    ]
    r = s.script(
        *[(argv, None) for _, _, argv in refusals],
        (["teach", "--project", "--dest", "hook", "--fact", "Hook by teach"], None),
        (["hook", "activate", hooked], None),
        (["recompile", "--no-push"], None),
    )
    problems = []
    for (label, rid, _), result in zip(refusals, r):
        if result["rc"] != 1 or f"{rid}: the hook destination is unavailable in Windows capture mode" not in result["err"]:
            problems.append(f"{label}: " + json.dumps(result, ensure_ascii=True))
    for result, verb in ((r[5], "teach"), (r[6], "hook")):
        if (result["rc"], result["err"]) != (1, f"self-learn {verb}: unavailable in Windows capture mode\n"):
            problems.append(f"{verb}: " + json.dumps(result, ensure_ascii=True))
    recompiled = r[7]
    if recompiled["rc"] != 0 or (f"{hooked}: the hook destination is unavailable in Windows capture mode"
                                 not in recompiled["out"] + recompiled["err"]):
        problems.append("recompile: " + json.dumps(recompiled, ensure_ascii=True))
    if (s.proj / ".claude" / "hooks").exists():
        problems.append("a hook folder appeared in the host")
    assert problems == []
    # Nothing but the telemetry flush (every verb's epilogue) reached the ledger.
    changed = s.git(s.ledger, "diff", "--name-only", "-z", head, "HEAD").split(b"\0")
    assert all(path.startswith(b"telemetry/") for path in changed if path), changed
    assert s.git(s.proj, "rev-parse", "HEAD") == host_head
    assert show(s, fresh)["status"] == "pending" and show(s, hooked)["status"] == "routed"
    s.check_ledger()


# ------------------------------------------- literal ledger writers, Windows


@windows
def test_windows_ledger_writers_take_brackets_literally(tmp_path, monkeypatch):
    from self_learn import gitops, ledger, worker

    for key, value in scratch_env(tmp_path).items():
        if os.environ.get(key) != value:
            monkeypatch.setenv(key, value)
    home = Path(os.environ["SELF_LEARN_HOME"])
    ledger.init_home(home)
    named, sibling = home / "skills" / "x [1]", home / "skills" / "x 1"
    files = {}
    for folder in (named, sibling):
        (folder / "pending").mkdir(parents=True)
        for name in ("a.md", "b.md", "c.md", "d.md"):
            path = folder / "pending" / name
            path.write_bytes(b"seed\n")
            files[folder, name] = path
    (sibling / "pending" / "gone.md").write_bytes(b"only the sibling\n")
    git(home, "add", "--", "skills")
    git(home, "commit", "-q", "-m", "seed both buckets")
    for path in files.values():
        path.write_bytes(b"changed\n")

    def staged():
        return set(git(home, "diff", "--cached", "--name-only", "-z").split(b"\0")) - {b""}

    def rel(folder, name):
        return f"skills/{folder.name}/pending/{name}".encode()

    # stage and unstage name only the bracketed file.
    assert gitops.stage(home, [files[named, "a.md"]]) == [files[named, "a.md"]]
    assert staged() == {rel(named, "a.md")}
    gitops.unstage(home, [files[named, "a.md"]])
    assert staged() == set()
    # known_paths: the bracketed absent path is unknown, though the pattern
    # matches the sibling's committed file.
    assert gitops.known_paths(home, [named / "pending" / "gone.md"]) == []
    assert gitops.known_paths(home, [sibling / "pending" / "gone.md"]) == ["skills/x 1/pending/gone.md"]
    # commit with paths commits the bracketed file only.
    before = git(home, "show", "HEAD:skills/x 1/pending/b.md")
    gitops.commit(home, "self-learn: literal commit", paths=[files[named, "b.md"]])
    shown = git(home, "show", "--name-only", "--format=", "HEAD").split(b"\n")
    assert [line for line in shown if line] == [rel(named, "b.md")]
    assert git(home, "show", "HEAD:skills/x 1/pending/b.md") == before
    # remove takes the bracketed file out, never the sibling (whose local
    # edit would make a pattern match refuse the whole removal).
    files[named, "c.md"].write_bytes(b"seed\n")
    gitops.remove(home, named / "pending" / "c.md")
    assert not (named / "pending" / "c.md").exists() and (sibling / "pending" / "c.md").exists()
    assert staged() == {rel(named, "c.md")}
    gitops.commit(home, "self-learn: literal remove", paths=[named / "pending" / "c.md"])
    assert staged() == set()
    # the worker's own run-end commit: its tracked check, add and diff.
    assert not worker._tracked(home, named / "pending" / "gone.md")
    assert worker._tracked(home, sibling / "pending" / "gone.md")
    result = worker.RunResult(status="ok", touched=[files[named, "d.md"], named / "pending" / "gone.md"])
    assert worker._commit_locked(home, result)
    shown = git(home, "show", "--name-only", "--format=", "HEAD").split(b"\n")
    assert [line for line in shown if line] == [rel(named, "d.md")]
    assert staged() == set()
    # Positive control: the sibling's edits are still only in the worktree.
    status = git(home, "status", "--porcelain", "-z").split(b"\0")
    assert {line[3:] for line in status if line} == {
        rel(named, "a.md"), *(rel(sibling, n) for n in ("a.md", "b.md", "c.md", "d.md"))}
