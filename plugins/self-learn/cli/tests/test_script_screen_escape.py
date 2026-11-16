"""D1: collection escape invalidates provenance, and paths cannot walk upward."""
import json
from pathlib import Path

import pytest
from self_learn.script_screen import screen

PREFIX = '#!/usr/bin/env python3\nimport sys\nimport os.path\nfrom pathlib import Path\nroot = Path(sys.argv[1])\n'
BASE = PREFIX + 'paths = sorted(root.iterdir())\n'
USE = '\nfor p in paths:\n    print(p.read_bytes())\n'
DATA = Path(__file__).parent / 'data'
PROBES = json.loads((DATA / 'script_screen_probes_escape.json').read_text())
CONTROLS = {'control_sorted_derived', 'closure_rebind_nonlocal_free', 'comprehension_shadow_sorted', 'isolated_str_literal', 'control', 'with_suffix_ok'}


@pytest.mark.parametrize('escape', [
    'alias = [paths][0]', 'alias = (paths,)[0]', 'alias = {paths}',
    'alias = {"k": paths}', 'alias = {paths: 1}',
    'class Box: pass\nb = Box()\nb.items = paths',
    'holder = {}\nholder["k"] = paths',
    'holder = {}\nholder["k"]: list = paths',
    'class Box:\n    items = paths', 'class Box:\n    paths = paths', 'class Box:\n    items: list = paths',
    'alias = paths\nholder = [alias]', 'first = paths\nalias = first\nholder = (alias,)',
    'alias = paths\nif len(sys.argv) > 2: alias = []\nholder = [alias]',
    'alias: list = paths\nif len(sys.argv) > 2: alias = []\nfirst = alias\nholder = {"k": first}',
    'match paths:\n    case alias: holder = [alias]',
    'class Box:\n    def __eq__(self, other): self.items = other\nb = Box()\npaths == b',
    'class Box:\n    def __add__(self, other): self.items = other\nb = Box()\nb + paths',
    'class Box:\n    def __contains__(self, other): self.items = other\nb = Box()\npaths in b',
    'holder = [(alias := paths)]', 'holder = [paths for n in range(1)]',
    'holder = (paths for n in range(1))',
    'list.extend(paths, [root])', 'list.append(paths, root)',
    'list(paths)', 'tuple(paths)', 'set(paths)', 'filter(lambda p: True, paths)',
    'def store(xs): return xs\nstore(paths)',
    'def store(xs): yield xs\nstore(xs=paths)',
    'def store(xs=paths): return xs\nstore()',
    'def store(xs=paths): xs.append(root)\nstore()',
    'def mutate(xs): xs.append(root)\nmutate(paths)',
    'def store(xs): holder = [xs]\nstore(paths)',
    'def store(xs): holder = [xs]\ndef forward(xs): store(xs)\nforward(paths)',
    'def store(xs): return len(xs)\nalias = store\nstore(paths)',
    'reader = lambda: len(paths)',
    'def reader(): return paths', 'def reader(): yield paths',
    'def reader(): yield from paths',
    'def reader():\n    global paths\n    print(paths)',
])
def test_escaped_collection_loses_derivation(escape):
    checked = screen(BASE + escape + USE)
    assert not checked.ok and any(r.startswith('input-path:') for r in checked.rules), checked.rules


def test_nonlocal_collection_loses_derivation():
    code = PREFIX + 'def outer():\n    paths = sorted(root.iterdir())\n    def inner():\n        nonlocal paths\n        print(paths)\n    for p in paths:\n        print(p.read_bytes())\nouter()\n'
    checked = screen(code)
    assert not checked.ok and any(r.startswith('input-path:') for r in checked.rules), checked.rules


@pytest.mark.parametrize('use', [
    'sorted(paths)', 'len(paths)', 'print(paths)', 'reversed(paths)',
    'enumerate(paths)', 'zip(paths, paths)', 'str(paths)', 'any(paths)',
    'all(paths)', 'alias = paths',
    'def report(xs):\n    for p in xs: print(p.read_bytes())\nreport(paths)',
    'def report(*, xs):\n    for p in xs: print(p.read_bytes())\nreport(xs=paths)',
    'def report(xs=paths):\n    for p in xs: print(p.read_bytes())\nreport()',
    'def report(*, xs=paths):\n    for p in xs: print(p.read_bytes())\nreport(xs=paths)',
    'def inner(xs):\n    for p in xs: print(p.read_bytes())\ndef outer(xs): inner(xs)\nouter(paths)',
    'def leaf(p): return p.read_bytes()\ndef middle(p): return leaf(p)\ndef outer(p): return middle(p)\nouter(root)',
    'def report(xs, depth):\n    for p in xs: print(p.read_bytes())\n    if depth: report(xs, depth - 1)\nreport(paths, 2)',
])
def test_readonly_collection_uses_still_qualify(use):
    checked = screen(BASE + use + USE)
    assert checked.ok, checked.rules


@pytest.mark.parametrize('expression', [
    'root.parent', 'root.parent.parent', 'root.parents[-1]',
    'root.anchor', 'root.root', 'root.drive', 'os.path.dirname(root)',
    'root.resolve().parents[-1] / "dev" / "zero"',
    'root.resolve().parent', 'root.absolute().parent.parent',
])
def test_upward_path_is_underived(expression):
    checked = screen(PREFIX + f'print(Path({expression}).read_bytes())\n')
    assert not checked.ok and any(r.startswith('input-path:') for r in checked.rules), checked.rules


@pytest.mark.parametrize('component', ['..', '../x', '/etc/x', 'dev/zero', './dev/zero', 'proc/self/maps', 'sys/kernel', 'sys.argv[2]'])
@pytest.mark.parametrize('join', ['root / PART', 'root.joinpath(PART)', 'Path(root, PART)', 'Path(os.path.join(root, PART))'])
def test_unsafe_join_is_underived(component, join):
    part = component if component == 'sys.argv[2]' else repr(component)
    checked = screen(PREFIX + f'print(({join.replace("PART", part)}).read_bytes())\n')
    assert not checked.ok and any(r.startswith('input-path:') for r in checked.rules), checked.rules


@pytest.mark.parametrize('expression', ['root.resolve()', 'root.absolute()', 'root / "status"', 'root.joinpath("status")', 'Path(root, "status")', 'Path(os.path.join(root, "status"))'])
def test_safe_path_normalization_and_join(expression):
    checked = screen(PREFIX + f'print(({expression}).read_bytes())\n')
    assert checked.ok, checked.rules


@pytest.mark.parametrize('name', list(PROBES))
def test_reviewer_escape_probes(name):
    checked = screen(PROBES[name])
    assert checked.ok == (name.split(':')[1] in CONTROLS), (name, checked.rules)
    assert checked.ok or all(':' in rule for rule in checked.rules)


@pytest.mark.parametrize('code, escapes', [
    ('min(paths)', True), ('max(paths)', True),
    ('r = max(paths, [])\nr.append(root)', True),
    ('r = min(paths, paths)\nr.append(root)', True),
    ('r = max(paths or [], [])\nr.append(root)', True),
    ('print(paths or [])', True), ('len([] or paths)', True),
    ('print(paths and [])', True), ('len(True and paths)', True),
    ('print(paths if True else [])', True),
    ('print([] if False else paths)', True),
    ('print((paths or []) if True else [])', True),
    ('print(paths or (paths if True else []))', True),
    ('if len(paths or []): pass', True),
    ('if print(paths if True else []): pass', True),
    ('if paths or []: pass', False), ('if paths and True: pass', False),
    ('if paths if True else []: pass', False),
    ('if [] if False else paths: pass', False),
    ('if (paths or []) and (paths if True else []): pass', False),
    ('while paths or []: break', False),
    ('print(1 if paths else 2)', False),
])
def test_min_max_and_boolean_collection_escape(code, escapes):
    checked = screen(BASE + code + USE)
    assert any(r.startswith('input-path:') for r in checked.rules) == escapes, checked.rules
    if not escapes and not code.startswith('while '):
        assert checked.ok, checked.rules
