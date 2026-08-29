#!/usr/bin/env bash
# m72.sh -- CNT2's fourth precondition (gate M-13): the ORIGINAL merge, an
# AMENDED merge, and a SECOND merge on top of it all satisfy conditions
# (1)-(3) alone (a merge commit, not an ancestor of origin/master, a
# matching state-file record) -- only the recorded-merge-sha-and-parents
# comparison (condition 4) tells them apart. Expect: 3 pass (1)-(3), 1
# passes all four (the original).
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
SRC="$ROOT/plugins/self-learn/cli/src"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

bare="$tmp/origin.git"
work="$tmp/work"
git init -q --bare "$bare"
git init -q -b master "$work" 2>/dev/null || { git init -q "$work"; git -C "$work" symbolic-ref HEAD refs/heads/master; }
git -C "$work" config user.email t@example.invalid
git -C "$work" config user.name Test
echo base > "$work/f.txt"
git -C "$work" add f.txt
git -C "$work" commit -q -m base
git -C "$work" remote add origin "$bare"
git -C "$work" push -q origin master

git -C "$work" checkout -q -b feature
echo feature >> "$work/f.txt"
git -C "$work" commit -q -am feature

git -C "$work" checkout -q master
git -C "$work" merge -q --no-ff -m "merge feature" feature
orig_sha=$(git -C "$work" rev-parse HEAD)
orig_parents=$(git -C "$work" log -1 --format=%P HEAD)

export XDG_CACHE_HOME="$tmp/cache"
export SELF_LEARN_HOME="$tmp/self-learn-home-unused"
python3 - "$work" "$orig_sha" "$orig_parents" "$SRC" <<'PYEOF'
import json, os, subprocess, sys
work, orig_sha, orig_parents, src = sys.argv[1:5]
sys.path.insert(0, src)
from self_learn.landing import state as st

branch = "feature"
base_sha = subprocess.run(["git", "-C", work, "rev-parse", "origin/master"], capture_output=True, text=True).stdout.strip()
st.write_state(branch, base_sha=base_sha, refusal_step="push", merge_sha=orig_sha, parent_shas=orig_parents.split())

def scenario():
    d = st.evaluate_continue(__import__("pathlib").Path(work), branch)
    return d.in_post_commit_refusal_state, d.ok

results = []
# 1: original merge, HEAD unchanged
results.append(scenario())

# 2: amended merge (new sha, same parents typically)
subprocess.run(["git", "-C", work, "commit", "--amend", "-q", "-m", "merge feature (amended)"], check=True)
results.append(scenario())

# 3: a second merge on top -- merge a third throwaway branch
subprocess.run(["git", "-C", work, "checkout", "-q", "-b", "extra"], check=True)
with open(os.path.join(work, "g.txt"), "w") as f:
    f.write("extra\n")
subprocess.run(["git", "-C", work, "add", "g.txt"], check=True)
subprocess.run(["git", "-C", work, "commit", "-q", "-m", "extra"], check=True)
subprocess.run(["git", "-C", work, "checkout", "-q", "master"], check=True)
subprocess.run(["git", "-C", work, "merge", "-q", "--no-ff", "-m", "second merge", "extra"], check=True)
results.append(scenario())

pass123 = sum(1 for a, b in results if a)
pass1234 = sum(1 for a, b in results if a and b)
print(f"pass123={pass123} pass1234={pass1234}")
PYEOF
