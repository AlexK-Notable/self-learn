"""CLI-through-symlink test (T1).

install.sh deploys plugins/self-learn/scripts/self-learn as a ~/bin symlink;
the wrapper must locate the uv project via `readlink -f` (resolving the real
script path), not `dirname $0` (which would resolve beside the symlink).
This test exercises exactly that path: symlink in a tmpdir -> wrapper ->
`uv run --project .../cli self-learn status --json` against an empty sandbox.

U-uvpath (2026-08-29) adds the functions below it: self-learn-host.service
crash-looped six times on 2026-08-28 22:17-22:18 with `exec: uv: not found`
(exit 127/n/a) because the wrapper's old last line, `exec uv run ...`,
resolved `uv` off ambient PATH alone, and the systemd user manager's PATH
does not reliably include ~/.local/bin (uv's pipx install dir on this host).
These tests drive the wrapper directly (not through a symlink -- that is
T1's own concern above) under a controlled, minimal environment.

Gate r1 fold (2026-08-29, MAJOR-1 round 1): every subprocess PATH built
here is HERMETIC -- it names ONLY a directory this test itself populated.

Gate r2 fold (2026-08-29): two further findings, both closed here.

MAJOR-1 (round 1's fix was incomplete): `_hermetic_bin` hermeticizes
PATH, but the wrapper's fallback candidates ($HOME/.local/bin/uv,
/usr/local/bin/uv, /usr/bin/uv) are checked by ABSOLUTE path regardless
of PATH -- that is their whole purpose. A hermetic PATH proves nothing
about them; the gate proved this with a mount namespace planting a real
uv at /usr/local/bin/uv and watching the wrapper find and exec it,
bypassing every PATH-only test double. Fixed by DECOMPOSITION, not a
test-only hook: the wrapper's `_resolve_uv_bin` function takes the
candidate list as ARGUMENTS, so `_call_resolve_uv_bin` below sources the
wrapper (loading it as a library -- the wrapper's own BASH_SOURCE[0]-vs-$0
guard skips the resolve-and-exec sequence when sourced, a plain general
bash idiom, not a test-only branch) and calls the function directly with
temp-path candidates standing in for the real system paths.

Minor (round 1): `_hermetic_bin` only provided `bash`, so `dirname`/
`readlink` -- both of which the wrapper's own last line needs --
silently failed inside every subprocess test's environment (two
"command not found" lines, `--project /../cli`) while the tests passed
anyway, because none of them checked stderr. Now provides `dirname` and
`readlink` too, and every call site asserts the directory holds exactly
those three names -- proof, not assumption, and no longer overclaimed
in this docstring (round 1's version claimed "each caller" already made
the assertion; it was false for 2 of this file's 4 call sites).

Gate r3 fold (2026-08-29): round 2's decomposition was necessary but
not sufficient. `_resolve_uv_bin`'s new function-level tests
(`_call_resolve_uv_bin` above) are hermetic, but the WHOLE-WRAPPER
subprocess tests below never touched /usr/local/bin/uv or
/usr/bin/uv -- the gate reproduced round 2's exact signature in an
unprivileged mount namespace with a real uv planted at
/usr/local/bin/uv (2 CLI failures, named at each affected test). Fixed
with `_run_wrapper_uv_masked`: runs the REAL wrapper end to end inside
a fresh, unprivileged `unshare --user --map-root-user --mount`
namespace where /usr/local/bin and /usr/bin are guaranteed uv-free (or,
for this file's own mutation-verification, guaranteed to hold a
controlled stub) -- regardless of what this host actually has there,
and never visible outside that namespace. See that function's own
docstring for the mirror/clone mechanism, and the affected tests'
docstrings for the regression each closes.

Gate r4 fold (2026-08-29): CLEAN verdict, four Nits folded. Nit 1
(elevated by the coordinator): `_run_wrapper_uv_masked`'s mirror/clone
directories used to leak onto the real, shared /tmp (measured: 2 per
invocation, one holding ~5,962 symlinks, never cleaned) -- now created
via nested `tempfile.TemporaryDirectory` context managers under the
caller's own `tmp_path`, guaranteeing cleanup on every exit path.
Before/after measured directly: the OLD code leaked exactly 4 real
`/tmp` directories across 2 test invocations (reproduced live); the
FIXED code leaves zero across every affected test in both packages,
repeatedly. Nit 2: `_unprivileged_userns_available`'s probe now also
catches `subprocess.SubprocessError` (`TimeoutExpired` is one, NOT an
`OSError` -- a slow probe under load used to fail COLLECTION of this
whole file, losing all 9 tests, rather than skipping the 2-3 that need
the namespace; reproduced and fixed, confirmed via a real timed-out
probe against the shipped function). Nit 3: `plant_stub_uv_at` now has
a shipped call site, `test_uv_masked_namespace_resolves_a_planted_stub_uv`
(parametrized over both branches) -- the positive affirmative proof the
mask can show presence, not just absence."""

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "self-learn"

_BASH = shutil.which("bash")


def _has_exact_token(content: str, token: str) -> bool:
    """True iff `token` occurs in `content` and is not immediately
    followed by another identifier character -- so a check for a
    literal path cannot be satisfied by an extended/renamed variant of
    it (gate r1 M5's `uv`->`uvx` class)."""
    return re.search(re.escape(token) + r"(?![A-Za-z0-9_])", content) is not None


def _hermetic_bin(tmp_path: Path, name: str = "hermetic-bin") -> Path:
    """A directory containing ONLY symlinks to `bash`, `dirname`, and
    `readlink` -- no other file, `uv` included, real or stub. These
    three are the only external binaries the wrapper's own EXECUTION
    needs (bash for the shebang; dirname/readlink for its last line's
    `readlink -f "$0"` / `dirname` resolution). Used as the sole PATH
    entry so `command -v uv` is GUARANTEED to find nothing via PATH on
    any host, packaged `uv` or not -- proven, not assumed, by the
    directory-contents assertion EVERY caller in this file makes."""
    real_bash = shutil.which("bash")
    real_dirname = shutil.which("dirname")
    real_readlink = shutil.which("readlink")
    assert real_bash and real_dirname and real_readlink, (
        "bash, dirname, and readlink must all be resolvable to build a hermetic PATH"
    )
    d = tmp_path / name
    d.mkdir()
    (d / "bash").symlink_to(real_bash)
    (d / "dirname").symlink_to(real_dirname)
    (d / "readlink").symlink_to(real_readlink)
    return d


def _write_stub_uv(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/usr/bin/env bash\necho "{marker}: $*"\n', encoding="utf-8")
    path.chmod(0o755)


def _call_resolve_uv_bin(*candidates: str) -> subprocess.CompletedProcess:
    """Gate r2 MAJOR-1: `source` the wrapper (defines `_resolve_uv_bin`/
    `_uv_is_valid` as library functions -- the wrapper's own guard skips
    the resolve-and-exec sequence when BASH_SOURCE[0] != $0, i.e. when
    sourced rather than executed) and call `_resolve_uv_bin` directly
    with test-controlled candidates, under `PATH=""` so `command -v uv`
    is guaranteed to find nothing via PATH -- proving whatever the
    candidate list finds, it finds by ABSOLUTE path, independent of
    PATH, exactly the property production relies on for
    /usr/local/bin/uv and /usr/bin/uv. `bash` is invoked by its own
    resolved absolute path (not the bare name) so launching this
    subprocess never itself depends on PATH."""
    assert _BASH, "bash must be resolvable to run this helper"
    script = 'source "$1"; shift; _resolve_uv_bin "$@"'
    return subprocess.run(
        [_BASH, "-c", script, "_", str(WRAPPER), *candidates],
        env={"PATH": ""},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _unprivileged_userns_available() -> bool:
    """Gate r3 MAJOR-1: probes whether this host permits an
    unprivileged `unshare --user --map-root-user --mount` -- the
    technique below uses it to hermeticize the wrapper's ABSOLUTE
    fallback candidates (`/usr/local/bin/uv`, `/usr/bin/uv`), which a
    hermetic PATH cannot touch (`_uv_is_valid` checks them by absolute
    path, never via PATH lookup -- that is their whole purpose). False
    on a kernel/policy that disables unprivileged user namespaces (a
    `kernel.unprivileged_userns_clone=0` sysctl, or an AppArmor policy
    some distros ship) -- the three tests below skip rather than fail
    there, so the suite stays portable. Needs no privilege of its own:
    this same probe command is what the gate itself used to prove
    round 2's MAJOR-1 was still open."""
    unshare = shutil.which("unshare")
    if not unshare:
        return False
    try:
        probe = subprocess.run(
            [unshare, "--user", "--map-root-user", "--mount", "--", "true"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        # Gate r4 Nit 2: `subprocess.TimeoutExpired` is a
        # `SubprocessError`, NOT an `OSError` -- a probe that times out
        # under load (this host regularly runs five or six concurrent
        # agents) used to propagate UNCAUGHT out of this module-level
        # call, failing collection of this ENTIRE file (measured: rc=2,
        # every test in it lost) instead of degrading to "namespace
        # unavailable, skip the three that need it". `SubprocessError`
        # is the base of `TimeoutExpired` and `CalledProcessError`
        # (the latter unreachable here since `check=` is never passed,
        # kept for robustness against a future edit that adds it).
        return False
    return probe.returncode == 0


_NAMESPACE_AVAILABLE = _unprivileged_userns_available()
_NAMESPACE_SKIP_REASON = (
    "unprivileged user namespaces unavailable on this host/policy "
    "(kernel.unprivileged_userns_clone=0 or an AppArmor restriction) -- "
    "the three namespace-hermetic wrapper tests need `unshare --user "
    "--map-root-user --mount` to neutralize /usr/local/bin/uv and "
    "/usr/bin/uv regardless of what this host actually has there"
)


def _run_wrapper_uv_masked(
    *,
    tmp_path: Path,
    home: Path,
    path_dir: Path,
    args: list[str],
    plant_stub_uv_at: str | None = None,
) -> subprocess.CompletedProcess:
    """Gate r3 MAJOR-1: run the REAL wrapper end to end inside a fresh,
    unprivileged mount namespace where `/usr/local/bin/uv` and
    `/usr/bin/uv` are GUARANTEED absent (or, with `plant_stub_uv_at`
    set, guaranteed to hold a controlled stub) -- regardless of what
    this actual host has at those absolute paths. This is the same
    class of proof the gate used to disprove round 2's MAJOR-1: a
    hermetic PATH cannot touch these two candidates, because
    `_uv_is_valid` checks them by absolute path.

    Technique: `/usr/local/bin` is replaced outright with an empty
    tmpfs (nothing there is needed by the wrapper). `/usr/bin` is
    replaced with a CLONE -- a fresh directory of symlinks pointing at
    a separately bind-mounted MIRROR of the real `/usr/bin` (so every
    other binary, `env` included -- the wrapper's own shebang target --
    keeps working exactly as before) -- EXCLUDING `uv` (or replacing it
    with a stub, when `plant_stub_uv_at` asks for one). The mirror
    indirection is load-bearing: a symlink placed directly at
    `/usr/bin/<name> -> /usr/bin/<name>` would, once the clone is
    mounted OVER `/usr/bin`, resolve to ITSELF (ELOOP) -- the mirror
    lives at a separate, stable path the swap never touches.

    A brand-new mount namespace this test creates is never visible
    outside it and never propagates back to the real host (confirmed
    directly: the real `/usr/local/bin` and `/usr/bin/uv` are
    unaffected after every run of this helper) -- `mount
    --make-rprivate /` is added defensively so this holds even on a
    host whose root mount happens to be marked shared.

    Gate r4 Nit 1 (elevated -- this codebase already paid for
    `U-cachelit`'s lesson about exactly this class of leak): the
    mirror and clone directories used to be created via `mktemp -d`
    INSIDE the namespace's own bash script, landing on the REAL,
    shared `/tmp` -- a mount namespace tears down the MOUNTS it
    creates when its last process exits, but the mirror/clone
    directories themselves are ordinary filesystem objects on the real
    `/tmp`, never namespace-scoped, so they silently outlived every
    run (measured: 2 directories per invocation, one holding the
    ~5,962-entry symlink clone of `/usr/bin`, never cleaned). Both are
    now created by THIS function, under the caller's own `tmp_path` --
    a location the pytest harness already owns and manages -- and
    removed in a `finally` covering every exit path (normal return,
    a non-zero wrapper exit, a subprocess timeout, or any other
    exception), not merely relied upon to eventually age out.

    `plant_stub_uv_at` (`"usr-local-bin"` or `"usr-bin"`) writes a
    distinguishable, non-network stub `uv` at that location BEFORE the
    final mount swap -- exercised by a shipped test
    (`test_uv_masked_namespace_resolves_a_planted_stub_uv` below),
    proving the mask can show PRESENCE as well as absence, not merely
    absence by accident of this dev host never having a packaged uv."""
    if plant_stub_uv_at not in (None, "usr-local-bin", "usr-bin"):
        raise ValueError(f"unknown plant_stub_uv_at: {plant_stub_uv_at!r}")

    # Gate r4 Nit 1: genuine context managers, not a manual mkdtemp +
    # try/finally -- `tempfile.TemporaryDirectory` guarantees cleanup on
    # every exit path via its own `__exit__`, INCLUDING the case a bare
    # try/finally around two separate `mkdtemp()` calls gets wrong: if
    # the SECOND `TemporaryDirectory.__enter__` ever raised, the first's
    # `__exit__` still fires (Python's `with A, B:` is nested `with A:
    # with B:`, verified directly). `ignore_cleanup_errors=True` matches
    # this file's own risk posture elsewhere (never let a CLEANUP
    # failure mask the actual test result).
    with (
        tempfile.TemporaryDirectory(
            prefix="ns-mirror-bin-", dir=str(tmp_path), ignore_cleanup_errors=True
        ) as mirror_bin_str,
        tempfile.TemporaryDirectory(
            prefix="ns-clone-bin-", dir=str(tmp_path), ignore_cleanup_errors=True
        ) as clone_bin_str,
    ):
        mirror_bin = Path(mirror_bin_str)
        clone_bin = Path(clone_bin_str)

        plant_local = ""
        plant_bin = ""
        if plant_stub_uv_at == "usr-local-bin":
            plant_local = (
                "printf '#!/usr/bin/env bash\necho "
                "\"NAMESPACE_PLANTED_UV: $*\"\n' > /usr/local/bin/uv\n"
                "chmod 0755 /usr/local/bin/uv\n"
            )
        elif plant_stub_uv_at == "usr-bin":
            plant_bin = (
                "printf '#!/usr/bin/env bash\necho "
                "\"NAMESPACE_PLANTED_UV: $*\"\n' > \"$CLONE_BIN/uv\"\n"
                "chmod 0755 \"$CLONE_BIN/uv\"\n"
            )

        wrapper_argv = " ".join(
            shlex.quote(a) for a in [str(WRAPPER), *args]
        )
        script = f"""
set -euo pipefail
shopt -s nullglob
mount --make-rprivate / 2>/dev/null || true
[ -d /usr/local/bin ] || mkdir -p /usr/local/bin
mount -t tmpfs tmpfs /usr/local/bin
{plant_local}MIRROR_BIN={shlex.quote(str(mirror_bin))}
CLONE_BIN={shlex.quote(str(clone_bin))}
mount --bind /usr/bin "$MIRROR_BIN"
for e in "$MIRROR_BIN"/*; do
  name="$(basename "$e")"
  if [ "$name" = "uv" ]; then continue; fi
  ln -s "$e" "$CLONE_BIN/$name"
done
{plant_bin}mount --bind "$CLONE_BIN" /usr/bin
exec env -i HOME={shlex.quote(str(home))} PATH={shlex.quote(str(path_dir))} {wrapper_argv}
"""
        return subprocess.run(
            ["unshare", "--user", "--map-root-user", "--mount", "--", "bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_wrapper_runs_through_symlink(tmp_path):
    assert WRAPPER.is_file() and os.access(WRAPPER, os.X_OK)

    link = tmp_path / "bin" / "self-learn"
    link.parent.mkdir()
    link.symlink_to(WRAPPER)

    # An INITIALIZED, record-less home (git repo + hosts.yaml — what a
    # fresh clone is): a bare dir is a BROKEN home and now exits non-zero,
    # loudly (audit 2026-07-16 BLOCKER 11). This test is about the
    # WRAPPER's path resolution, so it hands the CLI a home it can answer.
    sandbox_home = tmp_path / "empty-repo"
    sandbox_home.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(sandbox_home)], check=True)
    (sandbox_home / "hosts.yaml").write_text(
        "skills_root: null\nprojects: []\n", encoding="utf-8"
    )

    env = dict(os.environ, SELF_LEARN_HOME=str(sandbox_home))
    result = subprocess.run(
        [str(link), "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "buckets": [],
        "total_pending": 0,
        "total_unreadable": 0,
        "open_followups": 0,
        "worker_last_run": None,
        # T19 blocks (zero-state: empty mix, null medians — never fake 0s)
        "supply_mix": {},
        "metrics": {
            "time_to_triage_median_days": None,
            "pending_total": 0,
            "pending_over_30d_pct": None,
            "routed_and_corrected": 0,
        },
    }


def test_wrapper_falls_back_to_home_local_bin_uv_when_path_lacks_it(tmp_path):
    """The minimal-PATH positive control (measured 2026-08-29):
    `env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin bash -c
    'command -v uv'` finds nothing on THIS host, because uv lives only
    at ~/.local/bin/uv (a pipx symlink) -- exactly the PATH shape a
    systemd user-manager unit that loses the boot-order race sees. This
    test does not rely on that host fact holding everywhere, though:
    PATH here is `_hermetic_bin`'s single, provably uv-free directory,
    so the fallback below is the ONLY way this can succeed on ANY host.
    HOME's only uv is a stub at $HOME/.local/bin/uv; the wrapper must
    still find and exec it."""
    fake_home = tmp_path / "home"
    _write_stub_uv(fake_home / ".local" / "bin" / "uv", "STUB_UV_INVOKED")

    hermetic_bin = _hermetic_bin(tmp_path)
    # Positive proof the PATH this test hands the wrapper cannot contain
    # a real (or stray stub) `uv` anywhere, AND that the wrapper's own
    # execution has everything it needs (gate r2 Minor: dirname/readlink
    # were missing in round 1, silently breaking this same test).
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash", "dirname", "readlink"}

    env = {"HOME": str(fake_home), "PATH": str(hermetic_bin)}
    result = subprocess.run(
        [str(WRAPPER), "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.startswith("STUB_UV_INVOKED: run --project ")
    assert "self-learn status --json" in result.stdout


@pytest.mark.skipif(not _NAMESPACE_AVAILABLE, reason=_NAMESPACE_SKIP_REASON)
@pytest.mark.parametrize("plant_stub_uv_at", ["usr-local-bin", "usr-bin"])
def test_uv_masked_namespace_resolves_a_planted_stub_uv(tmp_path, plant_stub_uv_at):
    """Gate r4 Nit 3: `_run_wrapper_uv_masked`'s `plant_stub_uv_at` had
    zero shipped call sites -- exercised only manually (by the gate,
    and by this file's own scratch mutation-verification runs, neither
    of which ships). This is the positive affirmative counterpart to
    the not-found/rejection tests below: it proves the masking
    technique can show PRESENCE, not merely absence by accident of
    this dev host never packaging a real `uv` in either fallback
    location. If the wrapper's resolution logic ever stopped checking
    `/usr/local/bin/uv` or `/usr/bin/uv` at all, the not-found tests
    would stay green (nothing to find either way) -- only THIS test
    would catch it. `plant_stub_uv_at` writes a distinguishable,
    non-network stub (never a real `uv run`, preserving this module's
    own no-network invariant) at the given location just before the
    namespace's final mount swap; the wrapper must find and exec it."""
    fake_home = tmp_path / "empty-home"
    fake_home.mkdir()

    hermetic_bin = _hermetic_bin(tmp_path)
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash", "dirname", "readlink"}

    result = _run_wrapper_uv_masked(
        tmp_path=tmp_path,
        home=fake_home,
        path_dir=hermetic_bin,
        args=["status", "--json"],
        plant_stub_uv_at=plant_stub_uv_at,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.startswith("NAMESPACE_PLANTED_UV: run --project ")


@pytest.mark.skipif(not _NAMESPACE_AVAILABLE, reason=_NAMESPACE_SKIP_REASON)
def test_wrapper_fails_loudly_with_no_bare_127_when_uv_is_nowhere(tmp_path):
    """Not-found path: PATH is `_hermetic_bin`'s single uv-free
    directory, $HOME/.local/bin/uv (the only fallback candidate this
    sandboxed HOME could satisfy) doesn't exist, AND -- gate r3
    MAJOR-1 -- /usr/local/bin/uv and /usr/bin/uv are masked absent by
    `_run_wrapper_uv_masked`'s namespace, regardless of what this host
    actually has there. Round 2's version of this test hermeticized
    PATH only, so on a host that packages a real `uv` in one of those
    two absolute locations it would find and EXEC that real `uv`
    instead of hitting this diagnostic -- reproduced by the gate via a
    mount namespace planting one at /usr/local/bin/uv (CLI 2 failures).
    Before the original fix this was the measured failure itself:
    `/…/self-learn: line 6: exec: uv: not found` with no diagnostic
    naming what was looked for. The wrapper must now name every
    location it checked and exit non-zero, on ANY host."""
    fake_home = tmp_path / "empty-home"
    fake_home.mkdir()

    hermetic_bin = _hermetic_bin(tmp_path)
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash", "dirname", "readlink"}

    result = _run_wrapper_uv_masked(
        tmp_path=tmp_path, home=fake_home, path_dir=hermetic_bin, args=["status", "--json"]
    )
    assert result.returncode != 0, result.stderr
    assert result.stdout == ""
    assert "uv not found" in result.stderr
    assert "$HOME/.local/bin/uv" in result.stderr
    assert "/usr/local/bin/uv" in result.stderr
    assert "/usr/bin/uv" in result.stderr


def test_wrapper_prefers_a_path_visible_uv_over_the_fallback_location(tmp_path):
    """Gate r1 MAJOR-2: the wrapper's own comment promises "a normal
    interactive invocation, or any user-chosen uv earlier on PATH, is
    unchanged" -- nothing enforced that claim until this test. Plant
    TWO distinguishable stub `uv`s: one PATH-visible (must win), one at
    the fallback location $HOME/.local/bin/uv (must lose). If the
    wrapper ever resolved the fallback first, or resolved either
    non-deterministically, this fails."""
    fake_home = tmp_path / "home"
    _write_stub_uv(fake_home / ".local" / "bin" / "uv", "FALLBACK_UV_INVOKED")

    # The PATH-visible directory carries bash/dirname/readlink (so the
    # shebang AND the wrapper's own execution resolve) plus the
    # PATH-visible uv stub -- the one and only PATH entry, so this is
    # hermetic by construction too (MAJOR-1's concern): no other
    # directory, no real uv, can be found via PATH.
    path_bin = _hermetic_bin(tmp_path, name="path-visible-bin")
    assert {p.name for p in path_bin.iterdir()} == {"bash", "dirname", "readlink"}
    _write_stub_uv(path_bin / "uv", "PATH_UV_INVOKED")

    env = {"HOME": str(fake_home), "PATH": str(path_bin)}
    result = subprocess.run(
        [str(WRAPPER), "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.startswith("PATH_UV_INVOKED: run --project ")
    assert "FALLBACK_UV_INVOKED" not in result.stdout


@pytest.mark.skipif(not _NAMESPACE_AVAILABLE, reason=_NAMESPACE_SKIP_REASON)
def test_wrapper_rejects_a_directory_named_uv_at_the_fallback_location(tmp_path):
    """Gate r1 MINOR-2/MINOR-5 (behavioral counterpart to the static
    check in ui/tests/test_wrapper.py -- the same `_uv_is_valid` fix
    covers this wrapper too): a DIRECTORY named `uv` sitting exactly
    where the $HOME fallback would look must be treated as invalid,
    not exec'd, and -- gate r3 MAJOR-1 -- that must hold even when
    /usr/local/bin/uv or /usr/bin/uv is a REAL, valid uv on the host
    running this test: `_run_wrapper_uv_masked` masks both absent, so
    the wrapper has nowhere left to fall through to but the diagnostic.
    Round 2's version of this test only planted the directory and
    hermeticized PATH, so a host packaging uv in either absolute
    fallback location would find and exec THAT instead of ever
    reaching this diagnostic -- reproduced by the gate via a mount
    namespace (CLI 2 failures, this test named explicitly). Before the
    original fix, bare `[[ -x ]]` accepts a directory (it is
    traversable) and `exec`ing it produces bash's own opaque "Is a
    directory" (rc=126) -- measured against the pre-tightening
    wrapper. The fixed wrapper must fall through to the loud
    not-found diagnostic instead."""
    fake_home = tmp_path / "home"
    (fake_home / ".local" / "bin" / "uv").mkdir(parents=True)

    hermetic_bin = _hermetic_bin(tmp_path)
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash", "dirname", "readlink"}

    result = _run_wrapper_uv_masked(
        tmp_path=tmp_path, home=fake_home, path_dir=hermetic_bin, args=["status", "--json"]
    )
    assert result.returncode != 0, result.stderr
    assert "uv not found" in result.stderr
    assert "Is a directory" not in result.stderr


def test_resolve_uv_bin_finds_a_candidate_regardless_of_path(tmp_path):
    """Gate r2 MAJOR-1: round 1's `_hermetic_bin` only hermeticized
    PATH, but the wrapper's fallback candidates ($HOME/.local/bin/uv,
    /usr/local/bin/uv, /usr/bin/uv) are checked by ABSOLUTE path
    regardless of PATH -- a hermetic PATH proves nothing about them.
    This test proves the actual property: `_resolve_uv_bin` finds a
    candidate under `PATH=""` (nothing findable via PATH at all,
    enforced by `_call_resolve_uv_bin`), simulating a real system uv at
    a fixed location the way /usr/local/bin/uv would behave in
    production, without needing root or a mount namespace."""
    stub = tmp_path / "sim-system-location" / "uv"
    _write_stub_uv(stub, "SIM_SYSTEM_UV_INVOKED")

    result = _call_resolve_uv_bin("/no/such/path1", str(stub), "/no/such/path3")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(stub)


def test_resolve_uv_bin_returns_failure_when_no_candidate_is_valid(tmp_path):
    """The failure leg of the same decomposed function: no candidate
    valid -> empty stdout, non-zero return -- exactly what the
    resolve-and-exec sequence checks to decide whether to print the
    loud diagnostic."""
    result = _call_resolve_uv_bin("/no/such/path1", "/no/such/path2")
    assert result.returncode == 1
    assert result.stdout == ""


def test_resolve_uv_bin_rejects_a_mode_0111_candidate(tmp_path):
    """Gate r2 Minor (continued from gate r1 MINOR-2/MINOR-5): `-f`+`-x`
    alone still admits a mode-0111 (execute-only, no read bit) file --
    `exec`ing one produces bash's own opaque "Permission denied"
    (rc=126, measured directly against a throwaway mode-0111 script),
    not this script's diagnostic, because reading a shebang line needs
    read permission too. `_uv_is_valid`'s `-r` check must reject it and
    let resolution fall through to the next candidate (or failure).

    Gate r3 measured artifact, recorded so a future reader does not
    need to rediscover it: this test must NEVER be run as fake-root
    inside an unprivileged user namespace (the technique
    `_run_wrapper_uv_masked` above uses for the whole-wrapper tests) --
    `uid 0` bypasses the `-r` DAC check entirely (confirmed directly:
    `[[ -r mode0111-file ]]` is false as this suite's normal user, true
    under `unshare --user --map-root-user`), which defeats the exact
    property this test exists to verify. It uses `_call_resolve_uv_bin`
    instead, which never enters a namespace -- correct, and must stay
    that way; a future consolidation of this test into the namespace
    helper would silently make it untestable, not merely redundant."""
    candidate = tmp_path / "mode0111" / "uv"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("#!/usr/bin/env bash\necho should-never-run\n", encoding="utf-8")
    candidate.chmod(0o111)

    result = _call_resolve_uv_bin(str(candidate))
    assert result.returncode == 1
    assert result.stdout == ""


def test_wrapper_falls_back_to_well_known_absolute_uv_locations() -> None:
    """Gate r2 MAJOR-3: deleting /usr/local/bin/uv and /usr/bin/uv from
    BOTH wrappers' `_resolve_uv_bin` invocations left 17/17 tests green
    under the round-1 `_has_exact_token` check, because it only proved
    the STRING exists somewhere in the file -- the diagnostic message
    alone was enough, without these paths ever playing the ROLE of an
    actual fallback candidate. This test extracts the exact
    `_resolve_uv_bin` invocation line and asserts each path appears
    THERE, as an argument, not merely somewhere in the file."""
    content = WRAPPER.read_text(encoding="utf-8")
    invocation_line = next(
        line for line in content.splitlines() if "_resolve_uv_bin " in line
    )
    assert _has_exact_token(invocation_line, "$HOME/.local/bin/uv")
    assert _has_exact_token(invocation_line, "/usr/local/bin/uv")
    assert _has_exact_token(invocation_line, "/usr/bin/uv")
