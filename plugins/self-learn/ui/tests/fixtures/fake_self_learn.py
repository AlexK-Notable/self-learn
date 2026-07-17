#!/usr/bin/env python3
"""A PATH/``argv_prefix``-shimmed fake ``self-learn`` binary (10 §0 rule 7)
for :mod:`self_learn_ui.runner`'s :class:`RealRunner` tests — task U4.

Never inspects flags semantically (mirrors ``tests/fixtures/fake_claude.py``'s
"argv is accepted and ignored beyond logging" posture); every scripted
behavior is driven entirely by environment variables so a test can control
exit code / stderr / timing per invocation WITHOUT a control file, and so
concurrent invocations (the serialization test) each read only their own
env, never a shared mutable file the test would have to lock:

- ``FAKE_SELF_LEARN_LOG``: path to append one JSON line per invocation —
  ``{"argv": [...], "start": <epoch float>, "end": <epoch float>,
  "pid": N, "home": "<SELF_LEARN_HOME as seen by this process>"}``. Used
  to assert both the exact argv sequence (argv shape tests) AND, for the
  serialization test, that no two invocations' ``[start, end]`` windows
  overlap (proof the real runner actually serializes rather than merely
  intending to).
- ``FAKE_SELF_LEARN_SLEEP``: seconds to sleep mid-invocation (default 0)
  — gives the serialization test room: a real overlap would only be
  observable if at least one invocation takes long enough to still be
  running when the second would (incorrectly, if unserialized) start.
- ``FAKE_SELF_LEARN_EXIT_CODE`` / ``FAKE_SELF_LEARN_STDERR``: the exit
  code / stderr text this invocation returns (defaults ``0`` / empty).
- ``FAKE_SELF_LEARN_FAIL_ARGV_CONTAINS``: when set, the exit
  code/stderr above apply ONLY to an invocation whose argv contains this
  exact token; every other invocation exits 0 with no stderr — this is
  what lets the bulk-loop "abort at item N" test fail exactly one
  ``graduate <id>`` call while its siblings (and the terminal ``push``)
  succeed.
"""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> int:
    argv = sys.argv[1:]
    start = time.time()
    sleep_s = float(os.environ.get("FAKE_SELF_LEARN_SLEEP", "0") or "0")
    if sleep_s:
        time.sleep(sleep_s)
    end = time.time()

    log_path = os.environ.get("FAKE_SELF_LEARN_LOG")
    if log_path:
        entry = {
            "argv": argv,
            "start": start,
            "end": end,
            "pid": os.getpid(),
            "home": os.environ.get("SELF_LEARN_HOME"),
        }
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    fail_needle = os.environ.get("FAKE_SELF_LEARN_FAIL_ARGV_CONTAINS")
    exit_code = int(os.environ.get("FAKE_SELF_LEARN_EXIT_CODE", "0") or "0")
    stderr_text = os.environ.get("FAKE_SELF_LEARN_STDERR", "")
    if fail_needle is not None and fail_needle not in argv:
        exit_code = 0
        stderr_text = ""

    if stderr_text:
        sys.stderr.write(stderr_text if stderr_text.endswith("\n") else stderr_text + "\n")
    # stdout is never parsed by the real runner (09 §3: outcome comes from
    # exit status, never human stdout) — print a harmless placeholder so a
    # test asserting "stdout is captured but ignored" has something to see.
    print("{}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
