#!/usr/bin/env python3
"""Seeded-sandbox launcher for the self-learn UI.

Brings up the REAL UI — real ASGI app, real ``RealRunner`` subprocess
queue, real git — against a throwaway ledger seeded with a consumable
corpus, so an agent driving a browser can graduate/park/discard records
for real without touching anything the user owns.

Why this exists at all
----------------------
``tests/test_js_dom.py`` gets its isolation from a pytest fixture that
builds an ``EnvConfig`` in-process and never mutates ``os.environ`` —
correct there, because pytest shares ONE process across the whole suite
and a global mutation would leak between tests.

That protection does not transfer to an out-of-process browser. An MCP
browser talks HTTP to a server that must already be listening, and the
in-process seams a fixture uses are unreachable from it. A dedicated
launcher process, by contrast, *owns* its environment — so here the
right move is the opposite one: set the redirects globally and early,
because several resolution paths read real process env at call time and
cannot be threaded an explicit mapping:

    self_learn.ledger.resolve_home        SELF_LEARN_HOME
    self_learn.worker.cache_dir           XDG_CACHE_HOME  (+ per-home hash)
    self_learn_ui.middleware.resolve_token_path
                                          XDG_RUNTIME_DIR, else cache_dir
    self_learn_ui.uilog.ui_log_path       cache_dir
    self_learn.selfcheck                  SELF_LEARN_CLAUDE_DIR
    self_learn.miner                      SELF_LEARN_TRANSCRIPTS_DIR
    everything "~"-relative               HOME

XDG_RUNTIME_DIR is the one that bites hardest and is easiest to miss:
``write_token_file`` writes ``$XDG_RUNTIME_DIR/self-learn/ui-token``, so
an unredirected sandbox start would overwrite the bearer token of a REAL
``self-learn-ui`` the user has running and lock them out of it.

HOME is the one that MATTERS MOST, and the first version of this file
did not redirect it. The five named vars cover where the UI's own
infrastructure writes — they say nothing about where the VERBS it spawns
write. ``self_learn.verbs.DEFAULT_USER_CLAUDE_MD`` is the literal
``Path("~/.claude/CLAUDE.md")``, expanded at use, with no CLI flag and no
env var to override it: a user-scope ``route`` lands on the operator's
REAL global instructions file. SELF_LEARN_CLAUDE_DIR does not help —
that governs only hook symlinks and settings.json. Redirecting HOME is
what contains it, and it contains every other "~"-relative path in the
tree at the same time (including the global gitconfig the seeded repos
would otherwise inherit).

``ledger._invoke_json`` and ``RealRunner.run`` both pin SELF_LEARN_HOME
onto each spawned subprocess themselves, but both build from
``dict(os.environ)`` — so the other redirects reach the children only by
being set here, in the parent.

Usage
-----
    uv run --project . python tools/sandbox_ui.py verify
    uv run --project . python tools/sandbox_ui.py selftest
    uv run --project . python tools/sandbox_ui.py up --records 24
    uv run --project . python tools/sandbox_ui.py up --fresh   # rebuild
    uv run --project . python tools/sandbox_ui.py reset

``verify`` runs the isolation gate and prints every resolved path
without starting a server or writing a corpus. ``reset`` restores the
pristine post-seed snapshot, so a destructive walk can be rewound and
re-run against a known starting state.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------- layout

STATE_ROOT = Path(tempfile.gettempdir()) / f"self-learn-ui-sandbox-{os.getuid()}"

#: Captured at import, BEFORE apply_redirects() moves HOME into the
#: sandbox — after that, Path.home() is the sandbox and can no longer
#: name what the gate is supposed to be protecting.
REAL_HOME = Path.home()

#: Every redirected location lives under <state>/live, so the isolation
#: gate is a single containment test against one root.
SUBDIRS = ("ledger-home", "host-repo", "cache", "runtime", "claude", "transcripts", "home")

#: Not part of the seeded corpus — it holds the live bearer token, which
#: must survive a `reset` (the server keeps its token in memory, so
#: restoring an older one, or none, only breaks whoever reads the file).
SNAPSHOT_SKIP = frozenset({"runtime"})

#: Places where the sandbox BEHAVES DIFFERENTLY from a real install, by
#: construction. An agent walking the UI must be told these, or it will
#: faithfully document a containment measure as a product defect — the
#: same class of fabricated finding the probe's perceptibility rules
#: exist to prevent, arriving from the other direction.
KNOWN_DIVERGENCES = (
    'Pane sessions ("Iterate", "Open bucket chat") show '
    '"Not logged in · Please run /login". The agent SDK child inherits the '
    "redirected HOME and finds no credentials there, so it fails at auth "
    "before any billable call. VERIFIED 2026-07-26: it does spawn, writes "
    "its whole ~/.claude tree (.claude.json, sessions/, backups/, "
    "projects/) INSIDE the sandbox, and reaches no model.",
    "No chezmoi source state, so route offers 'not tracked by chezmoi' on "
    "every claude-md destination.",
    "The ledger git repo has no remote — push reports 'not pushed'.",
)


def live_dir(state: Path) -> Path:
    return state / "live"


def pristine_dir(state: Path) -> Path:
    return state / "pristine"


def redirects(state: Path) -> dict[str, str]:
    """The five vars that must point inside the sandbox. Anything reading
    real process env resolves through one of these."""
    live = live_dir(state)
    return {
        # HOME first: it is the one that contains the spawned verbs'
        # write targets, not just the server's own.
        "HOME": str(live / "home"),
        "SELF_LEARN_HOME": str(live / "ledger-home"),
        "XDG_CACHE_HOME": str(live / "cache"),
        "XDG_RUNTIME_DIR": str(live / "runtime"),
        "SELF_LEARN_CLAUDE_DIR": str(live / "claude"),
        "SELF_LEARN_TRANSCRIPTS_DIR": str(live / "transcripts"),
    }


def apply_redirects(state: Path) -> None:
    os.environ.update(redirects(state))
    # The UI reads its own port/model config from env too; pin the ones
    # load_env() requires so the sandbox never inherits a stray real value.
    os.environ.setdefault("SELF_LEARN_PANE_ENGINE", "sdk")
    os.environ.setdefault("SELF_LEARN_PANE_MODEL", "sandbox-model")


# ------------------------------------------------------- isolation gate


class NotIsolated(SystemExit):
    pass


def assert_isolated(state: Path) -> list[tuple[str, Path]]:
    """Resolve every write location through the PRODUCTION functions and
    prove each one lands inside the sandbox.

    Deliberately calls the real resolvers rather than re-deriving the
    paths: a re-derivation can agree with itself while disagreeing with
    the code that actually writes, which is the failure mode this gate
    exists to rule out.

    Fails closed. With the redirects absent, ``resolve_home()`` returns
    the user's real ``~/.self-learn``, which is not under the sandbox
    root, so the gate raises rather than passing vacuously — see
    ``selftest`` for the executed negative control.
    """
    from self_learn.ledger import resolve_home
    from self_learn.miner import transcripts_root
    from self_learn.selfcheck import claude_runtime_dir
    from self_learn.verbs import DEFAULT_USER_CLAUDE_MD
    from self_learn.worker import cache_dir
    from self_learn_ui import uilog
    from self_learn_ui.middleware import resolve_token_path

    root = live_dir(state).resolve()

    # The route verb's user-scope target. Checked EXPLICITLY rather than
    # trusted to the Path.home() check below, so that if the constant
    # ever stops being "~"-relative the gate notices instead of silently
    # covering a path that moved out from under it.
    user_md = Path(DEFAULT_USER_CLAUDE_MD).expanduser()
    # Every entry goes through the resolver the writing code itself uses.
    # Reading os.environ directly here would raise KeyError when a var is
    # missing — which is the case the gate most needs to REPORT, since an
    # unset var is exactly how a write escapes to ~/.claude. (Caught by
    # `selftest` after the first fix.)
    checks: list[tuple[str, Path]] = [
        # $HOME itself — one check that contains EVERY "~"-relative path
        # in the tree, including ones no one has enumerated yet. The
        # first version of this gate listed only the six below and so
        # proved where the server writes while saying nothing about
        # where the verbs it spawns write.
        ("$HOME", Path.home()),
        ("route target", user_md),
        ("route rules dir", user_md.parent / "rules"),
        ("ledger home", Path(resolve_home())),
        ("cache dir", Path(cache_dir())),
        ("token file", Path(resolve_token_path())),
        ("ui log", Path(uilog.ui_log_path())),
        ("claude dir", Path(claude_runtime_dir())),
        ("transcripts", Path(transcripts_root())),
    ]

    escaped = [
        (name, path)
        for name, path in checks
        if not path.resolve().is_relative_to(root)
    ]
    if escaped:
        lines = "\n".join(f"    {name:<14} {path}" for name, path in escaped)
        raise NotIsolated(
            "REFUSING TO START — these resolve outside the sandbox root\n"
            f"  root: {root}\n{lines}\n"
            "The UI would write to a location the user owns."
        )
    return checks


# --------------------------------------------------------------- seeding


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "sandbox@example.invalid")
    git(repo, "config", "user.name", "UI Sandbox")


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, "--allow-empty")


def commit_paths(repo: Path, message: str, *paths: Path) -> None:
    """Commit ONLY the named paths. Worlds must use this, never
    :func:`commit_all`: composing `dirty-target,missing-dest` with an
    `add -A` silently committed the first world's uncommitted edit, so the
    sandbox came up clean while claiming to be dirty. (The product's own
    gitops module pins the same rule for the same reason.)"""
    rel = [str(p.relative_to(repo)) for p in paths]
    git(repo, "add", "-A", "--", *rel)
    git(repo, "commit", "-q", "-m", message, "--", *rel)


SKILL_MD = """---
name: {name}
description: Sandbox skill {name} for UI surface walking.
---

# {name}

Placeholder skill body.
"""

CLAUDE_MD = """# Sandbox host

## Behavioral expectations
- Placeholder.
"""

SKILLS = ("home-assistant", "git-hygiene", "shell-safety")


def days_ago(n: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_host(state: Path) -> Path:
    host = live_dir(state) / "host-repo"
    init_repo(host)
    for name in SKILLS:
        d = host / "plugins" / f"{name}-plugin" / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(SKILL_MD.format(name=name), encoding="utf-8")
    (host / "CLAUDE.md").write_text(CLAUDE_MD, encoding="utf-8")
    commit_all(host, "host seed")
    return host


def build_ledger(state: Path, host: Path) -> Path:
    ledger = live_dir(state) / "ledger-home"
    init_repo(ledger)
    for sub in ("skills", "projects", "user", "telemetry"):
        (ledger / sub).mkdir(exist_ok=True)
    (ledger / "hosts.yaml").write_text(
        f"skills_root: {host}\nprojects:\n  - path: {host}\n", encoding="utf-8"
    )
    commit_all(ledger, "ledger seed")
    return ledger


#: Corpus shapes chosen to vary what the UI must RENDER, not just how
#: many rows exist: scope drives bucket routing, type drives which
#: template branch runs, an Episode brief adds the `b`-toggled
#: disclosure, and the long/awkward bodies are the layout edges a
#: uniform corpus never reaches.
CORPUS: tuple[dict, ...] = (
    {
        "type": "behavior",
        "scope": "skill:home-assistant",
        "kind": "anti-pattern",
        "trigger": "About to edit .storage while Home Assistant is running.",
        "instruction": "Stop the container first — a live write clobbers state.",
        "age": 1,
        "brief": "Hand-edited the running config and it clobbered live state.",
    },
    {
        "type": "behavior",
        "scope": "skill:git-hygiene",
        "kind": "anti-pattern",
        "trigger": "About to force-push over a shared branch.",
        "instruction": "Pull and rebase first; force-with-lease if you must.",
        "age": 2,
    },
    {
        "type": "behavior",
        "scope": "skill:shell-safety",
        "kind": "surface-rule",
        "trigger": "About to read an exit code downstream of a pipe.",
        "instruction": "Capture rc unpiped or use PIPESTATUS — a pipe replaces the status.",
        "age": 3,
        "brief": "A gate reported rc=0 while the underlying command returned 1.",
    },
    {
        "type": "knowledge",
        "scope": "skill:home-assistant",
        "fact": "The router reserves 192.0.2.232 for the Beacon bridge.",
        "age": 4,
    },
    {
        "type": "behavior",
        "scope": "skill:git-hygiene",
        "kind": "reasoning-pattern",
        "trigger": "About to run a git pathspec from an unknown working directory.",
        "instruction": "Anchor the pathspec at the repo root; a cwd-relative one "
        "returns zero vacuously from the wrong directory.",
        "age": 7,
    },
    {
        "type": "knowledge",
        "scope": "project",
        "fact": "Browser tests are marked `js` and auto-skip when Chromium is absent.",
        "age": 9,
    },
    {
        "type": "behavior",
        "scope": "user",
        "kind": "surface-rule",
        "trigger": "About to run sudo from a non-interactive tool call.",
        "instruction": "Don't — there is no controlling terminal, and each failure "
        "accumulates in pam_faillock. Ask the user to run it.",
        "age": 12,
    },
    {
        "type": "behavior",
        "scope": "skill:shell-safety",
        "kind": "anti-pattern",
        "trigger": "About to accept an empty grep result as proof a gate passed.",
        "instruction": "Ask what the command prints when it cannot see the target at "
        "all. If that output is identical to 'pass', the gate is worthless "
        "until you add a positive control that varies the dimension being "
        "checked — presence alone is not enough, and a control that varies "
        "only presence will happily agree with a check that is blind to case, "
        "path, encoding, or ordering.",
        "age": 15,
        "brief": "A capital-letter grep reported a banner untested that was in fact "
        "asserted; the positive control varied presence but not case.",
    },
    {
        "type": "knowledge",
        "scope": "skill:git-hygiene",
        "fact": "Rebasing a branch that is already pushed rewrites hashes other "
        "clones depend on — coordinate or use a new branch.",
        "age": 21,
    },
    {
        "type": "behavior",
        "scope": "project",
        "kind": "surface-rule",
        "trigger": "About to write a UI assertion that only checks the DOM.",
        "instruction": "The accessibility tree carries neither opacity nor occlusion; "
        "an element at opacity:0 reports present. Assert the rendered fact.",
        "age": 30,
    },
    {
        "type": "knowledge",
        "scope": "user",
        "fact": "Ünïcödé, <angle brackets>, ampersands & 'quotes' — escaping check.",
        "age": 40,
    },
)


def seed_corpus(ledger: Path, host: Path, count: int) -> list[str]:
    """Write *count* records, cycling the shapes above. Ages are offset
    per cycle so repeated shapes do not collide on created_at."""
    from self_learn.ledger_ops import create_record
    from self_learn.records import Record

    written: list[str] = []
    for i in range(count):
        spec = dict(CORPUS[i % len(CORPUS)])
        cycle = i // len(CORPUS)
        brief = spec.pop("brief", None)
        age = spec.pop("age") + cycle * 45
        scope = spec["scope"]

        fields = {k: v for k, v in spec.items() if k != "scope"}
        record = Record.create(
            scope=scope,
            source="teach",
            created_at=days_ago(age),
            **fields,
        )
        path = create_record(
            ledger,
            record,
            project_path=host if scope == "project" else None,
        )
        if brief:
            path.write_text(
                path.read_text(encoding="utf-8").rstrip("\n")
                + f"\n\n## Episode brief\n{brief}\n",
                encoding="utf-8",
            )
        written.append(record.id)

    commit_all(ledger, f"seed {count} records")
    return written


# ------------------------------------------------------------ world states
#
# The corpus above varies what a RECORD looks like. It says nothing about
# what the WORLD the record resolves into looks like, and that axis is
# where most of this product's refusals live: the host repo is always
# committed clean, every destination already exists, every host is
# registered. Two walks reported coverage that could not have included any
# of it.
#
# Concretely: `verbs._abort_if_dirty` fires at six call sites, and the UI
# has a whole affordance behind it — `routes._commit_drift_eligible`
# renders an armed "Commit that repo's changes, then retry" button inside
# the error strip when a route's stderr carries GITOPS_DIRTY_MARKER. It
# has unit tests. Until now no walk could reach it, because nothing ever
# dirtied the seeded repo.
#
# Worlds are applied AFTER seeding and BEFORE the snapshot, so `reset`
# reproduces the world instead of washing it away. They are deliberately
# NOT listed in KNOWN_DIVERGENCES: a divergence is a containment artifact
# a walker must be told to ignore, whereas a dirty repo is a state a real
# user is in all the time and should be allowed to discover.
#
# Each world leaves part of the corpus untouched on purpose, so a walk can
# compare a refusal against a success rather than concluding the whole
# verb is broken.

WORLD_HELP = {
    "clean": "as-installed: everything committed, every destination present",
    "dirty-target": (
        "the git-hygiene skill doc has uncommitted changes, so routing any "
        "git-hygiene record hits the dirty-target refusal and the guided "
        "commit-first button. Other skills stay clean."
    ),
    "missing-dest": (
        "the shell-safety skill doc is deleted and committed, so routing "
        "there must CREATE the destination instead of appending to it."
    ),
    "analysed": (
        "every pending record carries an analyst proposal, so Approve works "
        "without cycling the destination and the post-analysis controls stop "
        "being dead ends. Compose with dirty-target to reach the refusal by "
        "the path a human actually takes."
    ),
}
DEFAULT_WORLD = "clean"


def world_clean(host: Path, ledger: Path) -> list[str]:
    return []


def world_dirty_target(host: Path, ledger: Path) -> list[str]:
    """Uncommitted edit to ONE skill's route target."""
    doc = host / "plugins" / "git-hygiene-plugin" / "skills" / "git-hygiene" / "SKILL.md"
    doc.write_text(
        doc.read_text(encoding="utf-8")
        + "\n<!-- uncommitted edit: sandbox world dirty-target -->\n",
        encoding="utf-8",
    )
    return [
        f"uncommitted edit in {doc.relative_to(host)}",
        "routing a git-hygiene record should now refuse; other skills route normally",
    ]


def world_missing_dest(host: Path, ledger: Path) -> list[str]:
    """Route target absent, committed so the repo stays clean — the
    create-vs-append branch, which nothing else in the seed reaches."""
    doc = host / "plugins" / "shell-safety-plugin" / "skills" / "shell-safety" / "SKILL.md"
    doc.unlink()
    commit_paths(host, "world missing-dest: remove shell-safety skill doc", doc)
    return [
        f"{doc.relative_to(host)} deleted (committed — repo is clean)",
        "routing a shell-safety record must create the file rather than append",
    ]


def world_analysed(host: Path, ledger: Path) -> list[str]:
    """Give every pending record a valid analyst proposal.

    Without this the whole seed sits in "no analysis yet", which gates far
    more than it looks: `route` refuses with NoProposalError before any
    other check runs, so the dirty-target refusal below it was unreachable
    even once the repo WAS dirty — reaching it needed the destination
    cycler, which is not the path a human takes. Walk 2 hit the same wall
    from the other side and reported `t`, `c`, `y` as unreachable.

    Proposals are written through the product's own write/stamp functions,
    never hand-rolled YAML: `stamp_proposal` computes `record_sha` from the
    record's normalized body, and a proposal whose sha does not match its
    record is rejected downstream."""
    from self_learn.ledger_ops import stamp_proposal, write_proposal
    from self_learn.records import Record

    dest_for = {"skill": "skill-md", "project": "claude-md", "user": "claude-md"}
    n = 0
    for path in sorted(ledger.rglob("pending/lrn-*.md")):
        record = Record.from_path(path)
        family = record.scope.split(":", 1)[0]
        write_proposal(
            ledger,
            record.id,
            {
                "destination": dest_for.get(family, "reference"),
                "rationale": (
                    "Sandbox proposal: this belongs in the scope's standing "
                    "instructions — it is a durable rule, not a one-off."
                ),
                "model": "sandbox-seed",
                "analyzed_at": days_ago(0),
            },
        )
        stamp_proposal(ledger, record.id)
        n += 1
    commit_all(ledger, f"world analysed: {n} proposals")
    return [
        f"{n} pending records now carry an analyst proposal",
        "Approve routes without cycling the destination first",
    ]


WORLDS = {
    "clean": world_clean,
    "dirty-target": world_dirty_target,
    "missing-dest": world_missing_dest,
    "analysed": world_analysed,
}


def apply_worlds(state: Path, host: Path, ledger: Path, names: list[str]) -> None:
    marker = live_dir(state) / ".world"
    notes: list[str] = []
    for name in names:
        notes.extend(f"[{name}] {line}" for line in WORLDS[name](host, ledger))
    marker.write_text(",".join(names) + "\n", encoding="utf-8")
    if notes:
        print("\n  WORLD STATE (deliberate — not a containment artifact):")
        for line in notes:
            print(f"    - {line}")


def _world_list(raw: str) -> list[str]:
    names = [p.strip() for p in raw.split(",") if p.strip()]
    unknown = [n for n in names if n not in WORLDS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown world(s) {', '.join(unknown)} — choices: {', '.join(WORLDS)}"
        )
    return names or [DEFAULT_WORLD]


def current_world(state: Path) -> str:
    marker = live_dir(state) / ".world"
    if marker.is_file():
        return marker.read_text(encoding="utf-8").strip()
    return DEFAULT_WORLD


# ------------------------------------------------------- snapshot/restore


def _mirror(src: Path, dst: Path, skip: frozenset[str] = frozenset()) -> None:
    """Make *dst*'s contents match *src*'s, RECURSING into directories
    that exist in both rather than deleting and re-copying them.

    Preserving directory inodes is load-bearing. ``watchfiles.awatch``
    registers on the ledger-home inode, and the watch coroutine does not
    re-scan (ledger.py:519-524 says so). A naive rmtree+copytree restore
    therefore kills external-change detection for the rest of the
    server's life — silently, since in-UI verbs still refresh via
    RealRunner's own callback, so the UI looks fine while it has stopped
    noticing anything it did not do itself. Measured: writes after an
    rmtree-style restore produced zero watch events.
    """
    dst.mkdir(parents=True, exist_ok=True)
    keep = {c.name for c in src.iterdir()}

    for child in list(dst.iterdir()):
        if child.name in skip or child.name in keep:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()

    for child in src.iterdir():
        if child.name in skip:
            continue
        target = dst / child.name
        if child.is_dir() and not child.is_symlink():
            if target.is_dir() and not target.is_symlink():
                _mirror(child, target)  # recurse — keeps target's inode
                continue
            if target.exists() or target.is_symlink():
                target.unlink()
            shutil.copytree(child, target, symlinks=True)
        else:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            shutil.copy2(child, target, follow_symlinks=False)


def snapshot(state: Path) -> None:
    _mirror(live_dir(state), pristine_dir(state), skip=SNAPSHOT_SKIP)


def restore(state: Path) -> None:
    src = pristine_dir(state)
    if not src.exists():
        raise SystemExit(
            f"no pristine snapshot at {src} — run `up --fresh` to build one"
        )
    _mirror(src, live_dir(state), skip=SNAPSHOT_SKIP)


# --------------------------------------------------------------- serving


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def serve(port: int) -> int:
    import uvicorn

    from self_learn_ui.app import create_app
    from self_learn_ui.env import EnvConfig
    from self_learn_ui.middleware import mint_token, write_token_file

    env = EnvConfig(
        self_learn_home=Path(os.environ["SELF_LEARN_HOME"]),
        ui_port=port,
        ui_browser=None,
        pane_model="sandbox-model",
        pane_budget_usd=1.0,
        pane_max_turns=5,
        pane_engine="sdk",
        ui_idle_exit_seconds=0,  # never idle-exit out from under a walk
    )
    # Claim the port BEFORE minting. write_token_file() overwrites a single
    # well-known path, and uvicorn does not bind until run() — so a second
    # `up` against a busy port used to mint, clobber the LIVE server's token
    # file, and only then die on bind. The running server kept serving a
    # token that no longer matched its own file, and anyone reading the file
    # got 403. Cost a whole walk: the agent was handed a dead token, fell
    # back to a stale cookie, and reported the entry link as broken.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError as exc:
        raise SystemExit(
            f"port {port} is already in use ({exc.strerror}) — refusing to "
            "start.\nThe token file was NOT touched, so any server already "
            "running on it still works."
        ) from exc
    finally:
        probe.close()

    token = mint_token()
    write_token_file(token)

    # No `runner=` — create_app defaults to the production RealRunner
    # (serialized async subprocess queue) wired to the sandbox home, so
    # verbs shell out to real `self-learn` and take real time. That
    # latency IS the subject of the walk; a FakeRunner would erase it.
    app = create_app(env=env, token=token)

    url = f"http://127.0.0.1:{port}/?token={token}"
    print("\n  sandbox UI is up")
    print(f"  {url}\n")
    print("  KNOWN SANDBOX DIVERGENCES — do not file these as UI defects:")
    for line in KNOWN_DIVERGENCES:
        print(f"    - {line}")
    print()
    print("  reset to the seeded state at any time:")
    print(f"    python {Path(__file__).name} reset\n", flush=True)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, access_log=False, log_level="warning"
    )
    uvicorn.Server(config).run()
    return 0


# --------------------------------------------------------------- commands


def report(checks: list[tuple[str, Path]]) -> None:
    print("  isolation gate — resolved through the production functions:")
    for name, path in checks:
        print(f"    {name:<14} {path}")


def cmd_verify(args: argparse.Namespace) -> int:
    apply_redirects(args.state)
    for sub in SUBDIRS:
        (live_dir(args.state) / sub).mkdir(parents=True, exist_ok=True)
    report(assert_isolated(args.state))
    print("\n  PASS — every write location is inside the sandbox.")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Negative control: prove the gate FAILS when a redirect is removed.

    A gate that cannot be made to fail is not a gate. This runs the real
    check in a child with SELF_LEARN_HOME unset and requires a non-zero
    exit — so `verify` passing means something.
    """
    apply_redirects(args.state)
    for sub in SUBDIRS:
        (live_dir(args.state) / sub).mkdir(parents=True, exist_ok=True)
    report(assert_isolated(args.state))
    print("\n  [1/2] gate PASSES with all redirects set")

    # Strip ALL five redirects so the resolvers fall back to the user's
    # real locations, and call assert_isolated DIRECTLY — invoking the
    # `verify` subcommand here would be a fail-open control, because
    # verify calls apply_redirects() and would put back the very vars
    # the control removed. (Caught by this selftest on its first run.)
    stripped = {k: v for k, v in os.environ.items() if k not in redirects(args.state)}
    code = (
        f"import pathlib, sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); "
        f"import sandbox_ui; "
        f"sandbox_ui.assert_isolated(pathlib.Path({str(args.state)!r}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], env=stripped, capture_output=True, text=True
    )
    if proc.returncode == 0:
        print("\n  FAIL — the gate passed with every redirect stripped.")
        print("  It is not actually checking anything.")
        return 1

    blob = proc.stdout + proc.stderr
    if str(REAL_HOME) not in blob:
        print("\n  FAIL — the gate rejected, but not because it resolved into")
        print(f"  the real home ({REAL_HOME}). It may be failing for an")
        print(f"  unrelated reason:\n{blob.strip()}")
        return 1

    print(f"  [2/2] gate FAILS with the redirects stripped (rc={proc.returncode})")
    for ln in blob.splitlines():
        if str(REAL_HOME) in ln and ("route target" in ln or "$HOME" in ln):
            print(f"        would have written to: {ln.strip()}")
    print("\n  PASS — the gate is load-bearing in both directions.")
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    state = args.state
    live = live_dir(state)

    if args.fresh:
        for d in (live, pristine_dir(state)):
            if d.exists():
                shutil.rmtree(d)

    # Seed on the presence of a seeded LEDGER, not of the directory tree.
    # `verify` and `selftest` both mkdir the tree, so a `live.exists()`
    # test made the documented `verify` -> `up` order serve an empty
    # ledger while printing PASS, with `reset` permanently impossible
    # because no snapshot was ever taken.
    needs_seed = not (live / "ledger-home" / "hosts.yaml").exists()
    for sub in SUBDIRS:
        (live / sub).mkdir(parents=True, exist_ok=True)

    apply_redirects(state)
    checks = assert_isolated(state)
    report(checks)

    if needs_seed:
        host = build_host(state)
        ledger = build_ledger(state, host)
        ids = seed_corpus(ledger, host, args.records)
        # Before the snapshot, so `reset` rewinds TO the world rather than
        # out of it — a world applied afterwards evaporates on first reset
        # and gets rediscovered as "restore is broken".
        apply_worlds(state, host, ledger, args.world)
        snapshot(state)
        print(f"\n  seeded {len(ids)} records across {len(SKILLS)} skills "
              f"+ project + user scopes")
        print(f"  pristine snapshot: {pristine_dir(state)}")
    else:
        n = len(list((live / "ledger-home").rglob("lrn-*.md")))
        print(f"\n  reusing existing sandbox at {live} ({n} records)")
        print(f"  world: {current_world(state)}")
        if ",".join(args.world) != current_world(state):
            print(f"  NOTE: --world {','.join(args.world)} IGNORED — the existing "
                  "sandbox keeps the world it was seeded with. Use --fresh to "
                  "change worlds.")
        print("  (--fresh to rebuild, `reset` to rewind to the seeded state)")

    return serve(args.port or free_port())


def cmd_reset(args: argparse.Namespace) -> int:
    restore(args.state)
    print(f"  restored {live_dir(args.state)} from the pristine snapshot")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sandbox_ui.py", description=(__doc__ or "").split("\n")[0]
    )
    parser.add_argument(
        "--state", type=Path, default=STATE_ROOT,
        help=f"sandbox state root (default: {STATE_ROOT})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser(
        "up",
        help="seed if needed, then serve",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="worlds:\n"
        + "\n".join(f"  {k:<14} {v}" for k, v in WORLD_HELP.items()),
    )
    up.add_argument("--records", type=int, default=24)
    up.add_argument("--port", type=int, default=0)
    up.add_argument("--fresh", action="store_true", help="discard and rebuild")
    up.add_argument(
        # argparse applies `type` only to values the caller actually
        # passes, so the default must already be in parsed form.
        "--world",
        default=[DEFAULT_WORLD],
        type=_world_list,
        help=f"comma-separated world states (default: {DEFAULT_WORLD}); "
        f"choices: {', '.join(WORLDS)}",
    )
    up.set_defaults(func=cmd_up)

    sub.add_parser("verify", help="run the isolation gate only").set_defaults(
        func=cmd_verify
    )
    sub.add_parser(
        "selftest", help="prove the isolation gate fails when it should"
    ).set_defaults(func=cmd_selftest)
    sub.add_parser("reset", help="rewind to the seeded state").set_defaults(
        func=cmd_reset
    )

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
