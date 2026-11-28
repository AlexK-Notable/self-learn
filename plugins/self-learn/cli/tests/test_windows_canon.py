"""Lessons written into Claude Code's instruction files on Windows (stage 4C).

The Windows tests drive the real verbs through ``cli.main`` against a scratch
profile (a folder name with a space and a non-ASCII letter), with the Windows
capability gate opened for the ledger and canon verbs only. The files they
write into have CRLF line endings, one has mixed endings, and every check
compares bytes. The line-ending helper is a pure function and is checked on
both systems; the POSIX test pins that Linux still writes the compiler's text
as it always has.
"""

import json
import os
import shutil
import string
import subprocess
import tempfile
from pathlib import Path

import pytest

from self_learn import cli, compilers, places, settings
from self_learn.compilers import keep_line_endings
from self_learn.primitives import names

windows = pytest.mark.skipif(os.name != "nt", reason="native Windows canon")
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX canon contract")

BEGIN = compilers.BEGIN_MARKER.encode()
END = compilers.END_MARKER.encode()
PBEGIN = compilers.POINTER_BEGIN_MARKER.encode()
PEND = compilers.POINTER_END_MARKER.encode()


def read_universal(path: Path) -> str:
    with open(path, encoding="utf-8", newline=None) as stream:
        return stream.read()


def only_crlf(data: bytes) -> bool:
    return b"\n" not in data.replace(b"\r\n", b"") and b"\r" not in data.replace(b"\r\n", b"")


def only_lf(data: bytes) -> bool:
    return b"\r" not in data


# ---------------------------------------------------------- helper, both systems


@pytest.mark.parametrize(
    ("raw", "edit", "expected"),
    [
        # A CRLF file: the inserted line takes CRLF, every other byte stays.
        (b"a\r\nb\r\nc\r\n", lambda t: t.replace("b\n", "b\nnew\n"), b"a\r\nb\r\nnew\r\nc\r\n"),
        # A line taken out leaves its neighbours alone.
        (b"a\r\nb\r\nc\r\n", lambda t: t.replace("b\n", ""), b"a\r\nc\r\n"),
        # Mixed endings: the untouched lines keep theirs; CRLF is the majority.
        (b"a\r\nb\nc\r\nd\r\n", lambda t: t.replace("c\n", "C\nC2\n"), b"a\r\nb\nC\r\nC2\r\nd\r\n"),
        # A minority LF line after the edit keeps its LF.
        (b"a\r\nb\r\nc\nd\r\n", lambda t: t.replace("a\n", "A\n"), b"A\r\nb\r\nc\nd\r\n"),
        # Mixed with LF the majority: the new line takes LF.
        (b"a\nb\nc\r\n", lambda t: t + "z\n", b"a\nb\nc\r\nz\n"),
        # An LF file is written exactly as the compiler gave it.
        (b"a\nb\n", lambda t: t + "\nz\n", b"a\nb\n\nz\n"),
        # A last line without a terminator gains the file's convention.
        (b"a\r\nb", lambda t: t + "\n\nz\n", b"a\r\nb\r\n\r\nz\r\n"),
        # A lone CR stays where nothing touches it.
        (b"a\rb\r\nc\r\n", lambda t: t.replace("c\n", "C\n"), b"a\rb\r\nC\r\n"),
        # A lone CR next to a new LF line would merge into one ending: it takes the convention.
        (b"a\rb\nc\n", lambda t: t.replace("b\n", "\nb\n"), b"a\n\nb\nc\n"),
        # A UTF-8 BOM and non-ASCII text survive.
        ("﻿é\r\nü\r\n".encode(), lambda t: t + "ß\n", "﻿é\r\nü\r\nß\r\n".encode()),
        # Nothing changes: the file's own bytes come back.
        (b"a\r\n\r\nb\r\n", lambda t: t, b"a\r\n\r\nb\r\n"),
    ],
    ids=["crlf-insert", "crlf-remove", "mixed-crlf-majority", "mixed-tail-kept", "mixed-lf-majority", "lf",
         "unterminated", "lone-cr-kept", "lone-cr-boundary", "bom-unicode", "unchanged"],
)
def test_keep_line_endings_contract(tmp_path, raw, edit, expected):
    path = tmp_path / "CLAUDE.md"
    path.write_bytes(raw)
    text = read_universal(path)
    new = edit(text)
    result = keep_line_endings(path, new)
    assert result.encode("utf-8") == expected
    out = tmp_path / "out.md"
    out.write_bytes(result.encode("utf-8"))
    assert read_universal(out) == new  # reads back as exactly the compiler's text


def test_keep_line_endings_new_and_empty_files_get_lf(tmp_path):
    missing = tmp_path / "missing.md"
    assert keep_line_endings(missing, "a\nb\n") == "a\nb\n"
    assert not missing.exists()
    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    assert keep_line_endings(empty, "a\nb\n") == "a\nb\n"
    single = tmp_path / "single.md"
    single.write_bytes(b"one line")
    assert keep_line_endings(single, "one line\n\nz\n") == "one line\n\nz\n"


def test_keep_line_endings_round_trips_every_small_file(tmp_path):
    """Every file of up to five lines over three contents and four endings,
    with one line inserted, changed or removed at each position: the result
    reads back as the edit, and every untouched leading and trailing line
    keeps its bytes."""
    endings = ["\r\n", "\n", "\r", ""]
    path = tmp_path / "f.md"
    checked = 0
    for count in range(1, 5):
        for seed in range(4 ** count):
            ends = [endings[(seed // 4 ** i) % 4] for i in range(count)]
            if "" in ends[:-1]:
                continue  # only the last line may lack a terminator
            lines = [f"{string.ascii_lowercase[i % 3]}{end}" for i, end in enumerate(ends)]
            raw = "".join(lines)
            path.write_bytes(raw.encode())
            text = read_universal(path)
            split = text.splitlines(keepends=True)
            for at in range(len(split) + 1):
                for new in (split[:at] + ["NEW\n"] + split[at:],
                            split[:at] + split[at + 1:],
                            split[:at] + ["X\n"] + split[at + 1:]):
                    edited = "".join(new)
                    result = keep_line_endings(path, edited)
                    out = tmp_path / "o.md"
                    out.write_bytes(result.encode())
                    assert read_universal(out) == edited, (raw, edited, result)
                    # Untouched leading lines keep their exact bytes.
                    same = 0
                    while same < min(len(split), len(new)) and split[same] == new[same]:
                        same += 1
                    keep = "".join(lines[:max(same - 1, 0)])
                    assert result.startswith(keep), (raw, edited, result)
                    # And so do untouched trailing lines.
                    tail = 0
                    while (tail < min(len(split), len(new)) - same
                           and split[-1 - tail] == new[-1 - tail]):
                        tail += 1
                    assert result.endswith("".join(lines[len(lines) - tail:])), (raw, edited, result)
                    checked += 1
    assert checked > 1000


@posix
def test_posix_compile_writes_the_compiler_text(tmp_path):
    """Linux is unchanged: the compiler's own text is what lands, so a CRLF
    file is still written as LF there, and the pointer token is the names
    backend's, unconverted."""
    target = tmp_path / "CLAUDE.md"
    target.write_bytes(b"# Mine\r\n\r\nKeep.\r\n")
    expected = compilers.compile_managed_text(target.read_text(encoding="utf-8"), []).text
    compilers.compile_managed_file(target, [])
    assert target.read_bytes() == expected.encode("utf-8")
    surface, shelf = tmp_path / "CLAUDE.md", tmp_path / "references" / "LEARNINGS.md"
    assert compilers.pointer_token(surface, shelf) == names.pointer_token(surface, shelf)


# ----------------------------------------------------------------- Windows


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=60).stdout


class Canon:
    """A scratch profile, ledger and cache, the canon capability gate open."""

    def __init__(self, root: Path, monkeypatch, capsys):
        from self_learn.primitives import capabilities

        self.root, self.capsys, self.monkeypatch = root, capsys, monkeypatch
        self.profile = root / "prof été"
        (self.profile / ".claude").mkdir(parents=True)
        for key in ("SELF_LEARN_CLAUDE_DIR", "CLAUDE_CONFIG_DIR", "PYTHONUTF8",
                    *settings.AGENT_CALLER_MARKERS):
            monkeypatch.delenv(key, raising=False)
        env = {
            "USERPROFILE": self.profile, "HOME": self.profile,
            "SELF_LEARN_HOME": root / "ledger", "XDG_CACHE_HOME": root / "cache",
            "GIT_CONFIG_GLOBAL": self.profile / "gitconfig",
        }
        for key, value in env.items():
            monkeypatch.setenv(key, str(value))
        drive, rest = os.path.splitdrive(str(self.profile))
        monkeypatch.setenv("HOMEDRIVE", drive)
        monkeypatch.setenv("HOMEPATH", rest)
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
        for role in ("AUTHOR", "COMMITTER"):
            monkeypatch.setenv(f"GIT_{role}_NAME", "Canon Test")
            monkeypatch.setenv(f"GIT_{role}_EMAIL", "canon@example.invalid")
        monkeypatch.setenv("SELF_LEARN_ACTOR", "canon-test")
        # Git for Windows' own installer default; the ledger sets its own.
        subprocess.run(["git", "config", "--global", "core.autocrlf", "true"], check=True, timeout=30)
        monkeypatch.setitem(capabilities.AVAILABLE, "ledger", True)
        monkeypatch.setitem(capabilities.AVAILABLE, "canon", True)
        self.ledger = root / "ledger"
        self.run("init")

    def run(self, *argv: str) -> str:
        code = cli.main(list(argv))
        out = self.capsys.readouterr()
        assert code == 0, (argv, code, out.out, out.err)
        self.stdout = out.out
        return out.out + out.err

    def teach(self, where: Path, scope: str, fact: str) -> str:
        self.monkeypatch.chdir(where)
        code = cli.main(["teach", f"--{scope}", "--no-push", "--json", "--fact", fact])
        out = self.capsys.readouterr()
        assert code == 0, (code, out.out, out.err)
        return json.loads(out.out)["id"]

    def route(self, record_id: str, dest: str, *extra: str) -> str:
        return self.run("route", record_id, "--dest", dest, "--no-push", *extra)


def block(data: bytes, begin: bytes = BEGIN, end: bytes = END) -> tuple[bytes, bytes, bytes]:
    at = data.index(begin)
    stop = data.index(end, at) + len(end)
    return data[:at], data[at:stop], data[stop:]


def entry(record_id: str, fact: str) -> bytes:
    return f"- {fact} *({record_id})*\r\n".encode()


USER_SEED = b"# Mine\r\n\r\nKeep this line.\r\n\r\n" + BEGIN + b"\r\n" + END + b"\r\n\r\nAfter the block.\r\n"
PROJECT_SEED = "# Projet été\r\n\r\nTeam notes stay as they are.\r\n".encode()
LOCAL_SEED = b"# Local\r\n\r\n" + BEGIN + b"\r\n" + END + b"\r\n\r\nMy own trailing note.\r\n"
RULES_MIXED = b"---\r\ndescription: Windows rules\r\n---\r\n# Windows rules\n\nAn LF line here.\r\n"
RULES_PATHED = b"---\r\ndescription: Python rules\r\n---\r\n\r\n# Python\r\n"
NOTES_SEED = b"# Notes\r\n\r\nOld entry.\r\n"


def project_host(c: Canon) -> Path:
    proj = c.root / "projet été"
    (proj / ".claude" / "rules").mkdir(parents=True)
    (proj / "src").mkdir()
    (proj / "references").mkdir()
    git(proj, "init", "-q")
    git(proj, "config", "core.autocrlf", "false")
    files = {
        "CLAUDE.md": PROJECT_SEED, ".gitignore": b"CLAUDE.local.md\r\n",
        ".claude/rules/windows.md": RULES_MIXED, ".claude/rules/python.md": RULES_PATHED,
        "src/app.py": b"print('ok')\r\n", "references/notes.md": NOTES_SEED,
    }
    for name, data in files.items():
        (proj / name).write_bytes(data)
    (proj / "CLAUDE.local.md").write_bytes(LOCAL_SEED)
    git(proj, "add", "--", *files)
    git(proj, "commit", "-q", "-m", "seed")
    c.run("host", "add", str(proj))
    return proj


def snapshot(*paths: Path) -> dict[Path, bytes | None]:
    return {p: (p.read_bytes() if p.is_file() else None) for p in paths}


@pytest.fixture
def canon(tmp_path, monkeypatch, capsys):
    return Canon(tmp_path.resolve(), monkeypatch, capsys)


def route_everywhere(c: Canon) -> dict:
    proj = project_host(c)
    user_md = c.profile / ".claude" / "CLAUDE.md"
    user_md.write_bytes(USER_SEED)
    assert names.user_claude_file(Path("~/.claude/CLAUDE.md")) == user_md  # the real default root
    ids = {
        "user": c.teach(proj, "user", "Windows user fact"),
        "project": c.teach(proj, "project", "Projet fact"),
        "local": c.teach(proj, "project", "Local fact"),
        "rules": c.teach(proj, "project", "Mixed rules fact"),
        "pathed": c.teach(proj, "project", "Pathed rules fact"),
        "shelf": c.teach(proj, "project", "Shelf fact"),
        "notes": c.teach(proj, "project", "Notes fact"),
    }
    c.route(ids["user"], "claude-md")
    c.route(ids["project"], "claude-md")
    c.route(ids["local"], "claude-md:local")
    c.route(ids["rules"], "claude-md:rules:windows")
    c.route(ids["pathed"], "claude-md:rules:python", "--rules-path", "src/*.py")
    before_pointer = (proj / "CLAUDE.md").read_bytes()
    c.route(ids["shelf"], "reference")
    before_notes_pointer = (proj / "CLAUDE.md").read_bytes()
    c.route(ids["notes"], "reference:notes.md")
    return {"proj": proj, "user_md": user_md, "ids": ids, "before_pointer": before_pointer,
            "before_notes_pointer": before_notes_pointer}


@windows
def test_windows_routes_keep_bytes_outside_the_block(canon):
    r = route_everywhere(canon)
    proj, ids = r["proj"], r["ids"]

    # User CLAUDE.md under %USERPROFILE%\.claude: an existing block in the middle.
    pre, inner, post = block(r["user_md"].read_bytes())
    seed_pre, _, seed_post = block(USER_SEED)
    assert (pre, post) == (seed_pre, seed_post)
    assert inner == BEGIN + b"\r\n" + entry(ids["user"], "Windows user fact") + END
    assert only_crlf(r["user_md"].read_bytes())

    # Project CLAUDE.md: the block bootstrapped at the end, then the pointer block.
    data = (proj / "CLAUDE.md").read_bytes()
    managed = BEGIN + b"\r\n" + entry(ids["project"], "Projet fact") + END
    assert r["before_pointer"] == PROJECT_SEED + b"\r\n" + managed + b"\r\n"
    pre, pointers, post = block(data, PBEGIN, PEND)
    assert pre == r["before_pointer"] + b"\r\n" and post == b"\r\n"
    assert b"- `references/LEARNINGS.md` \xe2\x80\x94 " in pointers
    assert b"- `references/notes.md` \xe2\x80\x94 " in pointers
    assert only_crlf(data)

    # CLAUDE.local.md: ignored by git, block in the middle.
    pre, inner, post = block((proj / "CLAUDE.local.md").read_bytes())
    assert (pre, post) == block(LOCAL_SEED)[::2]
    assert inner == BEGIN + b"\r\n" + entry(ids["local"], "Local fact") + END

    # A mixed-ending rules file: every line kept, the block in CRLF (the majority).
    data = (proj / ".claude" / "rules" / "windows.md").read_bytes()
    pre, inner, post = block(data)
    assert pre == RULES_MIXED + b"\r\n" and post == b"\r\n"
    assert inner == BEGIN + b"\r\n" + entry(ids["rules"], "Mixed rules fact") + END

    # paths: frontmatter rewritten in a CRLF rules file, the rest untouched.
    data = (proj / ".claude" / "rules" / "python.md").read_bytes()
    assert compilers.read_paths_frontmatter(data.decode()) == ("src/*.py",)
    assert data.startswith(b"---\r\ndescription: Python rules\r\npaths:\r\n")
    assert b"\r\n---\r\n\r\n# Python\r\n\r\n" + BEGIN in data
    assert only_crlf(data)

    # The default shelf is new (LF); the named CRLF shelf gains a CRLF entry.
    assert only_lf((proj / "references" / "LEARNINGS.md").read_bytes())
    notes = (proj / "references" / "notes.md").read_bytes()
    assert notes.startswith(NOTES_SEED + b"\r\n## ") and only_crlf(notes)
    assert f"— {ids['notes']}\r\n".encode() in notes

    # Every host commit names its file with slashes; the host tree is clean.
    subjects = git(proj, "log", "--format=%s").decode("utf-8").splitlines()
    assert any(s.endswith("→ .claude/rules/windows.md (claude-md)") for s in subjects), subjects
    assert git(proj, "status", "--porcelain", "-z") == b""

    # recompile twice: nothing to do, nothing changes, the ledger stays put.
    files = [r["user_md"], *(proj / n for n in ("CLAUDE.md", "CLAUDE.local.md",
             ".claude/rules/windows.md", ".claude/rules/python.md",
             "references/LEARNINGS.md", "references/notes.md"))]
    routed = snapshot(*files)
    head = git(canon.ledger, "rev-parse", "HEAD")
    canon.run("recompile", "--no-push")
    assert snapshot(*files) == routed
    canon.run("recompile", "--no-push")
    assert snapshot(*files) == routed
    assert git(canon.ledger, "rev-parse", "HEAD") == head


@windows
def test_windows_retire_and_replace_leave_neighbours(canon):
    r = route_everywhere(canon)
    proj, ids = r["proj"], r["ids"]
    claude_md = proj / "CLAUDE.md"

    # retire: the project lesson's one line goes, nothing else moves.
    before = claude_md.read_bytes()
    canon.run("retire", ids["project"], "--covered-by", "claude-md:team-notes", "--no-push")
    assert claude_md.read_bytes() == before.replace(entry(ids["project"], "Projet fact"), b"")

    # Retiring the default shelf's only entry removes its pointer line and the shelf.
    before = claude_md.read_bytes()
    pointer_line = next(line for line in before.splitlines(keepends=True)
                        if line.startswith(b"- `references/LEARNINGS.md`"))
    assert pointer_line.endswith(b"\r\n")
    canon.run("retire", ids["shelf"], "--covered-by", "claude-md:team-notes", "--no-push")
    assert claude_md.read_bytes() == before.replace(pointer_line, b"")
    assert not (proj / "references" / "LEARNINGS.md").exists()

    # Retiring the named CRLF shelf's entry gives back its exact original bytes.
    canon.run("retire", ids["notes"], "--covered-by", "claude-md:team-notes", "--no-push")
    assert (proj / "references" / "notes.md").read_bytes() == NOTES_SEED
    subjects = git(proj, "log", "--format=%s").decode("utf-8").splitlines()
    assert any(s.endswith("→ references/notes.md (reference retired)") for s in subjects), subjects

    # replace: the old line out, the new line in, in CRLF; the rest untouched.
    canon.run("replace", ids["user"], "--fact", "Rewritten user fact",
              "--because", "clearer wording", "--no-push")
    data = r["user_md"].read_bytes()
    pre, inner, post = block(data)
    assert (pre, post) == block(USER_SEED)[::2]
    assert b"Windows user fact" not in inner and b"- Rewritten user fact *(lrn-" in inner
    assert only_crlf(data)
    assert git(proj, "status", "--porcelain", "-z") == b""


def other_drive(tmp: Path):
    """A writable folder on a drive letter other than *tmp*'s: a real second
    volume when the runner has one (``D:`` on GitHub's images), else a
    ``subst`` drive mapped onto a scratch folder (an ordinary user can make
    one), so the pointer still crosses a real drive letter."""
    for letter in "DEFGH":
        root = Path(f"{letter}:\\")
        if root.drive.upper() == tmp.drive.upper() or not root.is_dir():
            continue
        try:
            return Path(tempfile.mkdtemp(prefix="canon-", dir=root)), None
        except OSError:
            continue
    used = {Path(f"{c}:\\").drive for c in string.ascii_uppercase if Path(f"{c}:\\").exists()}
    letter = next(c for c in "ZYXWVU" if f"{c}:" not in used)
    backing = tmp / "subst-backing"
    backing.mkdir()
    subprocess.run(["subst", f"{letter}:", str(backing)], check=True, timeout=30)
    return Path(f"{letter}:\\"), letter


@windows
def test_windows_cross_drive_pointer(canon):
    folder, subst = other_drive(canon.root)
    print(f"other drive: {folder} ({'subst' if subst else 'volume'})")
    try:
        plain = canon.root / "plain projet"
        plain.mkdir()
        surface = plain / "CLAUDE.md"
        surface.write_bytes(b"# Plain\r\n\r\nOwn text.\r\n")
        shelf = folder / "shared notes é.md"
        shelf.write_bytes(NOTES_SEED)
        canon.run("host", "add", str(plain), "--mode", "plain")
        record_id = canon.teach(plain, "project", "Cross-drive fact")
        assert os.path.splitdrive(str(shelf))[0].upper() != os.path.splitdrive(str(surface))[0].upper()
        # The verb reaches the region check with the other-drive shelf and
        # refuses it as on Linux: a plain host's existing foreign shelf has
        # no compile record yet. Nothing is written.
        assert cli.main(["route", record_id, "--dest", f"reference:{shelf}", "--no-push"]) == 1
        refusal = canon.capsys.readouterr().err
        assert "hand-edited outside self-learn (unknown)" in refusal and "recompile --adopt" in refusal
        assert surface.read_bytes() == b"# Plain\r\n\r\nOwn text.\r\n" and shelf.read_bytes() == NOTES_SEED

        # The host write's own calls, as the route makes them once the shelf
        # is accepted: append to the other-drive shelf, point at it.
        from self_learn.records import Record

        record = Record.create(type="knowledge", scope="project", source="teach", fact="Cross-drive fact")
        appended = compilers.compile_reference(plain / "references", record, dest=str(shelf))
        assert appended.applied and appended.path == shelf
        token = compilers.pointer_token(surface, shelf)
        assert token == shelf.as_posix() and "\\" not in token and token[1:3] == ":/"
        pointer = compilers.apply_pointer(surface, appended.path, label="cross-drive shelf")
        assert pointer.changed and pointer.token == token
        data = surface.read_bytes()
        pre, pointers, post = block(data, PBEGIN, PEND)
        assert pre == b"# Plain\r\n\r\nOwn text.\r\n\r\n" and post == b"\r\n"
        assert f"- `{token}` \u2014 cross-drive shelf\r\n".encode() in pointers
        assert only_crlf(data)
        assert compilers.surface_names_target(surface, shelf)
        notes = shelf.read_bytes()
        assert notes.startswith(NOTES_SEED + b"\r\n## ") and only_crlf(notes)
        compilers.retire_reference(plain / "references", record.id, dest=str(shelf))
        assert shelf.read_bytes() == NOTES_SEED
    finally:
        if subst:
            subprocess.run(["subst", f"{subst}:", "/D"], check=False, timeout=30)
        else:
            shutil.rmtree(folder, ignore_errors=True)


@windows
def test_windows_memory_prune_keeps_index_line_endings(canon):
    proj = project_host(canon)
    memory = canon.profile / ".claude" / "projects" / "projet" / "memory"
    memory.mkdir(parents=True)
    index = "- [One](one.md) — first\r\n- [Two](two.md) — second\r\n".encode()
    (memory / "MEMORY.md").write_bytes(index)
    for name in ("one", "two"):
        (memory / f"{name}.md").write_bytes(
            f"---\r\nname: {name}\r\ndescription: Memory {name}\r\nmetadata:\r\n  type: project\r\n---\r\n"
            f"\r\nBody {name}.\r\n".encode())
    canon.monkeypatch.chdir(proj)
    canon.run("import", "--memory", str(memory))
    canon.run("list", "--json")
    one = next(item["id"] for item in json.loads(canon.stdout) if "Memory one" in item["title"])
    canon.run("reject", one, "--no-push")
    canon.run("prune-memory", str(memory))
    assert not (memory / "one.md").exists() and (memory / "two.md").exists()
    assert (memory / "MEMORY.md").read_bytes() == "- [Two](two.md) — second\r\n".encode()


@windows
def test_windows_display_labels_use_slashes(canon):
    shown = places.display_path(canon.profile / "repos" / "projet")
    assert shown == "~/repos/projet"
    from self_learn.ledger import discover_buckets

    canon.teach(canon.root, "user", "Label fact")
    user = [b for b in discover_buckets(canon.ledger) if b.scope == "user"]
    assert places.bucket_places(user)[("user", user[0].name)]["path"] == "~/.claude"
    # The route's budget note names the user's file with slashes.
    (canon.profile / ".claude" / "CLAUDE.md").write_bytes(USER_SEED)
    record_id = canon.teach(canon.root, "user", "Budget fact")
    assert "~/.claude/CLAUDE.md is " in canon.route(record_id, "claude-md")
