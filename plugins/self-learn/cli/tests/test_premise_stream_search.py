"""A ``file-match`` ``contains`` probe streams a file larger than the read
limit (so the installed ``claude`` program can be searched for a string),
refuses one over the hard search bound, and keeps every path rule."""

from __future__ import annotations

import os

import pytest

from self_learn import premises
from self_learn.premises import ProbeEnv

OBS_UNAVAILABLE = premises.OBS_UNAVAILABLE


def _env(tmp_path) -> ProbeEnv:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return ProbeEnv(
        home=home,
        path_env="/usr/bin",
        ledger_home=None,
        runtime_dir="/nonexistent-runtime-dir",
        now=lambda: "2026-10-30T00:00:00Z",
    )


def _probe(path: str, needle: str) -> dict:
    return {"kind": "file-match", "path": path, "contains": needle}


def _big(tmp_path, body: bytes, name: str = "prog.bin") -> str:
    env_home = tmp_path / "home"
    env_home.mkdir(exist_ok=True)
    (env_home / name).write_bytes(body)
    return f"~/{name}"


def test_needle_found_in_a_file_over_the_old_limit(tmp_path):
    filler = b"\x00\xff" * premises.READ_LIMIT  # binary, well over the limit
    path = _big(tmp_path, filler + b"too complex to verify" + filler)
    assert os.path.getsize(tmp_path / "home" / "prog.bin") > premises.READ_LIMIT
    obs = premises.run_probe(_probe(path, "too complex to verify"), _env(tmp_path))
    assert obs.state == premises.OBS_OK
    assert obs.shown == premises.PRESENT


def test_needle_absent_from_a_large_file(tmp_path):
    path = _big(tmp_path, b"\x00\xff" * premises.READ_LIMIT)
    obs = premises.run_probe(_probe(path, "too complex to verify"), _env(tmp_path))
    assert obs.state == premises.OBS_OK
    assert obs.shown == premises.ABSENT


@pytest.mark.parametrize("split", [1, 5, 10, 20])
def test_needle_straddling_a_chunk_boundary_is_found(tmp_path, monkeypatch, split):
    monkeypatch.setattr(premises, "SEARCH_CHUNK", 64)
    needle = "straddle-this-literal"  # 21 bytes
    cut = 64 * 3  # a chunk boundary
    body = bytearray(b"a" * 400)
    body[cut - split : cut - split + len(needle)] = needle.encode()
    path = _big(tmp_path, bytes(body))
    obs = premises.run_probe(_probe(path, needle), _env(tmp_path))
    assert obs.shown == premises.PRESENT


def test_a_needle_longer_than_a_chunk_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(premises, "SEARCH_CHUNK", 8)
    needle = "a-needle-much-longer-than-a-chunk"
    path = _big(tmp_path, b"xxxxx" + needle.encode() + b"yyyyy")
    assert premises.run_probe(_probe(path, needle), _env(tmp_path)).shown == premises.PRESENT


def test_a_partial_needle_split_across_the_end_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(premises, "SEARCH_CHUNK", 16)
    path = _big(tmp_path, b"q" * 40 + b"straddle-this-lite")  # one byte short
    obs = premises.run_probe(_probe(path, "straddle-this-literal"), _env(tmp_path))
    assert obs.shown == premises.ABSENT


def test_a_small_file_answers_the_same_shape(tmp_path):
    path = _big(tmp_path, b"hello needle world\n", "small.txt")
    hit = premises.run_probe(_probe(path, "needle"), _env(tmp_path))
    miss = premises.run_probe(_probe(path, "other"), _env(tmp_path))
    assert (hit.state, hit.shown) == (premises.OBS_OK, premises.PRESENT)
    assert (miss.state, miss.shown) == (premises.OBS_OK, premises.ABSENT)
    assert hit.value_sha is not None and miss.value_sha is not None


def test_a_file_over_the_hard_bound_is_still_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(premises, "SEARCH_LIMIT", 4096)
    path = _big(tmp_path, b"needle" + b"x" * 5000)
    reads: list[int] = []
    real_read = os.read
    monkeypatch.setattr(os, "read", lambda fd, n: (reads.append(n), real_read(fd, n))[1])
    obs = premises.run_probe(_probe(path, "needle"), _env(tmp_path))
    monkeypatch.setattr(os, "read", real_read)
    assert reads == []  # refused on the size alone, nothing read
    assert obs.state == OBS_UNAVAILABLE
    assert "search limit" in obs.reason
    assert obs.value_sha is None
    # Control: the same file just inside the bound is searched.
    monkeypatch.setattr(premises, "SEARCH_LIMIT", 8192)
    assert premises.run_probe(_probe(path, "needle"), _env(tmp_path)).shown == premises.PRESENT


def test_the_real_bound_admits_a_large_program():
    assert premises.SEARCH_LIMIT >= 1024 * 1024 * 1024
    assert premises.SEARCH_LIMIT > 400 * 1024 * 1024


def test_line_probe_keeps_the_read_limit(tmp_path):
    path = _big(tmp_path, b"x\n" * premises.READ_LIMIT)
    obs = premises.run_probe({"kind": "file-match", "path": path, "line": "x"}, _env(tmp_path))
    assert obs.state == OBS_UNAVAILABLE and "read limit" in obs.reason


def test_a_large_file_behind_a_refused_location_is_still_refused(tmp_path):
    env = _env(tmp_path)
    keydir = env.home / ".ssh"
    keydir.mkdir()
    (keydir / "config").write_bytes(b"SENTINEL-4711" + b"x" * (premises.READ_LIMIT + 10))
    plain = _big(tmp_path, b"SENTINEL-4711" + b"x" * (premises.READ_LIMIT + 10), "plain.bin")
    # Control: the same large content in a plain file is searched.
    assert premises.run_probe(_probe(plain, "SENTINEL"), env).shown == premises.PRESENT
    (env.home / "link.bin").symlink_to(keydir / "config")
    obs = premises.run_probe(_probe("~/link.bin", "SENTINEL"), env)
    assert obs.state == OBS_UNAVAILABLE and "refused location" in obs.reason
    with pytest.raises(premises.PremiseError, match="credential or key location"):
        premises.run_probe(_probe("~/.ssh/config", "SENTINEL"), env)


def test_a_fifo_is_not_streamed(tmp_path):
    env = _env(tmp_path)
    os.mkfifo(env.home / "pipe")
    obs = premises.run_probe(_probe("~/pipe", "x"), env)
    assert obs.state == OBS_UNAVAILABLE and "regular file" in obs.reason


def test_a_missing_file_is_unavailable_not_absent(tmp_path):
    obs = premises.run_probe(_probe("~/nope.bin", "x"), _env(tmp_path))
    assert obs.state == OBS_UNAVAILABLE


def test_a_file_growing_past_the_bound_while_read_is_unavailable(tmp_path, monkeypatch):
    # fstat says small; the read stream is longer than the bound.
    monkeypatch.setattr(premises, "SEARCH_LIMIT", 100)
    monkeypatch.setattr(premises, "SEARCH_CHUNK", 64)
    path = _big(tmp_path, b"z" * 90)
    real_open = premises._open_regular

    def liar(p, env):
        got = real_open(p, env)
        if isinstance(got, tuple):
            (tmp_path / "home" / "prog.bin").write_bytes(b"z" * 500)
        return got

    monkeypatch.setattr(premises, "_open_regular", liar)
    obs = premises.run_probe(_probe(path, "needle"), _env(tmp_path))
    assert obs.state == OBS_UNAVAILABLE and "search limit" in obs.reason
