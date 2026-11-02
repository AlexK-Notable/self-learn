"""File reads reuse parsing without reusing callers' mutable records."""

import os
from pathlib import Path

import pytest

from self_learn import records
from self_learn.records import Record, RecordError


FIXTURE = Path(__file__).parent / "fixtures" / "record-02s1-example.md"


@pytest.fixture(autouse=True)
def empty_parse_cache():
    records._cached_parse.cache_clear()
    yield
    records._cached_parse.cache_clear()


def test_same_size_same_mtime_rewrite_is_read(tmp_path):
    path = tmp_path / "lesson.md"
    original = FIXTURE.read_text(encoding="utf-8")
    path.write_text(original, encoding="utf-8")
    before = path.stat()
    assert Record.from_path(path).sightings == 2
    changed = original.replace("sightings: 2", "sightings: 3")
    assert changed != original and len(changed.encode()) == before.st_size
    path.write_text(changed, encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert path.stat().st_size == before.st_size
    assert Record.from_path(path).sightings == 3


@pytest.mark.parametrize("timestamp", [
    "2026-07-12T09:14:00Z",
    "2026-07-12T09:14:00.123456+05:30",
])
def test_cold_and_warm_reads_do_not_share_mutable_state(tmp_path, timestamp):
    path = tmp_path / "lesson.md"
    original = FIXTURE.read_text(encoding="utf-8").replace(
        "2026-07-12T09:14:00Z", timestamp
    )
    extras = """extra_base: &base {stamp: 2026-07-12T09:14:00.123456+05:30, nested: [one, two]}
extra_merged: {<<: *base}
&key "extra_key": value
extra_alias: *key
"""
    original = original.replace("---\n\n## Trigger", extras + "---\n\n## Trigger")
    original = Record.from_text(original).to_text()
    path.write_text(original, encoding="utf-8")
    first = Record.from_path(path)
    assert first.to_text() == original  # comments, quotes and timestamps survive
    assert first.created_at == Record.from_text(original).created_at
    first.set_body("\n## Trigger\nChanged\n\n## Instruction\nChanged\n")
    first.append_evidence({"origin": "new provenance"})
    first.set_status("deferred")
    # Exercise nested ruamel objects as well as the public mutation API.
    first._fm["evidence"][0]["quote"] = "changed quote"
    first._fm["routing"]["by"] = "agent"
    key = next(k for k in first._fm if k == "extra_key")
    assert key is first._fm["extra_alias"]
    key.yaml_set_anchor("changed", always_dump=True)
    first._fm["extra_base"]["nested"].append("three")
    assert first._fm["extra_merged"].merge[0] is first._fm["extra_base"]
    first.created_at._yaml["t"] = False
    first._fm["evidence"][0]["ts"]._yaml["t"] = False
    first._fm.yaml_add_eol_comment("changed comment", key="sightings")
    assert first.to_text() != original
    second = Record.from_path(path)
    assert second is not first
    assert second.to_text() == original
    second.append_evidence({"origin": "second provenance"})
    second._fm["evidence"][0]["quote"] = "second quote"
    third = Record.from_path(path)
    assert third is not second
    assert third.to_text() == original
    # Mutation remains writable; the next read sees those new bytes.
    first.created_at._yaml["t"] = True
    first._fm["evidence"][0]["ts"]._yaml["t"] = True
    first.write(path)
    assert Record.from_path(path).to_text() == first.to_text()
    assert third.to_text() == original


@pytest.mark.parametrize("bad_text", [
    "no frontmatter\n",
    "---\nid: lrn-12345678\n",
    "---\nid: [\n---\n",
    "---\nid: a\nid: b\n---\n",
    "---\ncreated_at: 2026-13-45\n---\n",
    FIXTURE.read_text(encoding="utf-8").replace("status: pending", "status: [pending]"),
    FIXTURE.read_text(encoding="utf-8").replace("## Trigger", "## Wrong"),
])
def test_parse_error_is_unchanged_and_retried(tmp_path, monkeypatch, bad_text):
    path = tmp_path / "invalid.md"
    path.write_text(bad_text, encoding="utf-8")
    with pytest.raises(RecordError) as expected:
        Record.from_text(bad_text)
    original = Record.from_text.__func__
    attempts = []

    def counted(cls, text):
        attempts.append(text)
        return original(cls, text)

    monkeypatch.setattr(Record, "from_text", classmethod(counted))
    errors = []
    for _ in range(2):
        with pytest.raises(type(expected.value)) as actual:
            Record.from_path(path)
        assert type(actual.value) is type(expected.value)
        assert str(actual.value) == str(expected.value)
        errors.append(actual.value)
    assert errors[0] is not errors[1]
    assert attempts == [bad_text, bad_text]


def test_repeated_text_parses_once_across_paths(tmp_path, monkeypatch):
    original = Record.from_text.__func__
    parsed = []

    def counted(cls, text):
        parsed.append(text)
        return original(cls, text)

    monkeypatch.setattr(Record, "from_text", classmethod(counted))
    text = FIXTURE.read_text(encoding="utf-8")
    one, two = tmp_path / "one.md", tmp_path / "two.md"
    one.write_text(text, encoding="utf-8")
    two.write_text(text, encoding="utf-8")
    for path in (one, one, two, two):
        assert Record.from_path(path).to_text() == text
    assert parsed == [text]

    class CustomRecord(Record):
        @classmethod
        def from_text(cls, text):
            record = super().from_text(text)
            record.marker = object()
            return record

    custom = CustomRecord.from_path(one)
    another = CustomRecord.from_path(one)
    assert isinstance(custom, CustomRecord)
    assert custom.marker is not another.marker
    custom.set_status("deferred")
    assert another.status == "pending"
