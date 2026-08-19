"""U-fake §3.4 -- `install_fake` and its friends: the T1 injection point
onto `self_learn.invocation.FakeBackend` for suite consumers that want
the in-process backend instead of a bash PATH shim (U-seam §3.8,
`Fake-1`).

`BK-a` (measured, `B-7`): the injection patches
`self_learn.invocation.registry.backend_for` -- never the package-level
re-export `self_learn.invocation.backend_for`, which is a SEPARATE
binding (`from .registry import backend_for` in `invocation/__init__.py`)
that `_dispatch` never reads. Patching the re-export is a silent no-op.

`BK-b` (measured, `B-5a`): `pytest.MonkeyPatch` has no `addfinalizer` --
teardown registration belongs to `request`, so `install_fake` leads with
it and registers `assert_fake_was_used` as a finalizer through it.
`assert_fake_was_used` is public precisely so a criterion can also
invoke it directly, to observe the assertion FIRE rather than merely not
fire (`BK2`).
"""

from __future__ import annotations

from self_learn import invocation
from self_learn.invocation import FakeBackend, FakeStep, Text

__all__ = ["install_fake", "assert_fake_was_used", "analyst_text"]


def install_fake(request, monkeypatch, steps: list[FakeStep]) -> FakeBackend:
    """Patch `self_learn.invocation.registry.backend_for` so every
    unqualified `write_session`/`text_session` call reaches `fake`
    instead of resolving a real `CliBackend`, and register
    `assert_fake_was_used` as a finalizer on `fake` through `request` --
    `monkeypatch` itself cannot (`BK-b`)."""
    fake = FakeBackend(steps)
    monkeypatch.setattr(
        invocation.registry, "backend_for", lambda *args, **kwargs: fake
    )
    request.addfinalizer(lambda: assert_fake_was_used(fake))
    return fake


def assert_fake_was_used(fake: FakeBackend) -> None:
    """Raise, naming the missed-patch fail-open, when `fake` recorded no
    calls -- public so `BK2` can invoke it directly on an unused
    `FakeBackend` and observe it fire."""
    if not fake.specs:
        raise AssertionError(
            "FakeBackend recorded no calls — a consumer fell through to a "
            "real backend (self_learn.invocation.registry.backend_for was "
            "never reached by install_fake's patch)"
        )


def analyst_text(yaml_body: str) -> Text:
    """Wrap `yaml_body` in the ```` ```yaml ```` fence
    `self_learn.analyst._parse_yaml_map` expects, as a `Text` step."""
    return Text(f"```yaml\n{yaml_body}```\n")
