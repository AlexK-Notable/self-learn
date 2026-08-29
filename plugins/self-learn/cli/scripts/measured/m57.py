#!/usr/bin/env python3
"""m57.py -- RES2's EXECUTED duplicate-key case (M57's ledger block).

Reproduces the r2 per-key algorithm's dict-comprehension collapse on a
duplicate key: the defect `per_key`'s duplicate-key refusal (RES2) exists
to catch. Deliberately does NOT import resolvers.per_key, which now
refuses this input -- this script is the frozen repro of the BROKEN form.
"""
base = ["a: 1", "a: 2", "b: 9"]
ours = ["a: 1", "a: 2", "b: 10"]
theirs = ["a: 1", "a: 2", "b: 9"]

key = lambda l: l.split(":")[0].strip()
O = {key(l): l for l in ours}
B = {key(l): l for l in base}
T = {key(l): l for l in theirs}
res = []
for l in base:
    k = key(l)
    o, t, b = O[k], T[k], B[k]
    res.append(o if o != b else t)
print(res)
