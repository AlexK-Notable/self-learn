#!/usr/bin/env bash
# m69.sh -- SUI8's STABLE PREDICATES (gate B-2/M-19/N-20): from the repo
# root, `uv run --project` sets the venv but not pytest's cwd, so
# collection hits the CLI tree too (rc 2, >=1 id under cli/tests); from
# inside plugins/self-learn/ui, collection is clean (rc 0, 0 ids outside
# ui/tests). Counts are deliberately NOT asserted (§4.6's OBSERVED table:
# they depend on untracked scratch state) -- only these predicates.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

root_out=$(cd "$ROOT" && env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT \
  uv run --project plugins/self-learn/ui pytest --collect-only -q 2>&1)
root_rc=$?
root_cli_ids_ge1=no
# a bash builtin substring test, not `| grep -q` -- `-q` exits after the
# first match, SIGPIPEs the upstream printf on this much output, and
# pipefail then reports the WHOLE pipeline as failed even though grep
# itself matched (the exact class this spec's own `EXC1` is about, one
# helper over).
case "$root_out" in
  *plugins/self-learn/cli/tests*) root_cli_ids_ge1=yes ;;
esac

ui_out=$(cd "$ROOT/plugins/self-learn/ui" && env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT \
  uv run pytest --collect-only -q 2>&1)
ui_rc=$?
# node ids in --collect-only -q output are lines of the form <path>::<test>
ui_outside=$(printf '%s\n' "$ui_out" | grep -E '::' | grep -vc '^tests/' || true)

printf 'root_rc=%s root_cli_ids_ge1=%s ui_rc=%s ui_outside=%s\n' "$root_rc" "$root_cli_ids_ge1" "$ui_rc" "$ui_outside"
