"""Caller provenance through collections and statically known helper calls."""
import json
from pathlib import Path

import pytest
from self_learn.script_screen import screen

DATA = Path(__file__).parent / 'data'
PREFIX = '#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nroot = Path(sys.argv[1])\n'
PROBES = json.loads((DATA / 'script_screen_probes_flow.json').read_text())
CONTROLS = {'py_allowed_report', 'sh_allowed_report', 'py_csv_writer_stdout_ok', 'py_open_x_caller'}


@pytest.mark.parametrize('name', ['drm-state', 'notes-digest'])
def test_live_trial_controls(name):
    checked = screen((DATA / f'script-control-{name}.txt').read_text())
    assert checked.ok, checked.rules


@pytest.mark.parametrize('expression', [
    'sorted(root.glob("*"))', 'reversed(list(root.glob("*")))',
    'list(root.glob("*"))', 'tuple(root.glob("*"))', 'set(root.glob("*"))',
    'filter(lambda p: True, root.glob("*"))', 'filter(keep, root.glob("*"))',
    '[p for p in root.glob("*")]', '{p for p in root.glob("*")}',
    '(p for p in root.glob("*"))', 'sorted(p for p in root.glob("*") if p.is_dir())',
])
def test_collection_wrappers_carry_elements(expression):
    checked = screen(PREFIX + f'def keep(p): return True\nfor p in {expression}:\n    print(p.read_text())\n')
    assert checked.ok, checked.rules


@pytest.mark.parametrize('assignments', [
    'outs = sorted(p for p in root.glob("card*"))',
    'outs = sorted(root.glob("*"))\nouts = tuple(root.rglob("*"))',
    'outs: list = list(root.glob("*"))',
    'first = sorted(root.glob("*"))\nouts = reversed(first)',
])
def test_bound_collections_carry_every_assignment(assignments):
    checked = screen(PREFIX + assignments + '\nfor out in outs:\n    print((out / "status").read_text())\n')
    assert checked.ok, checked.rules


@pytest.mark.parametrize('setup', [
    'outs = sorted([root, "/etc/x"])',
    'outs = [root]\nouts = ["/etc/x"]',
    'outs = [root]\n[(outs := ["/etc/x"]) for item in [0]]',
    'outs = [root]\nmatch ["/etc/x"]:\n    case outs: pass',
    'outs = list(root.glob("*"))\nouts.append("/etc/x")',
    'outs = list(root.glob("*"))\nalias = outs\nalias.append("/etc/x")',
    'outs = list(root.glob("*"))\nouts[0] = "/etc/x"',
    'outs = list(root.glob("*"))\nouts += ["/etc/x"]',
    'outs = ["/etc/x" for p in root.glob("*")]',
    'outs = sorted([root, Path("/etc/x")])',
    'def sorted(items): return ["/etc/x"]\nouts = sorted(root.glob("*"))',
])
def test_mixed_or_mutated_collection_refused(setup):
    checked = screen(PREFIX + setup + '\nfor out in outs:\n    print(Path(out).read_text())\n')
    assert not checked.ok and any(r.startswith('input-path:') for r in checked.rules), checked.rules


@pytest.mark.parametrize('code', [
    'def read(path): return path.read_text()\nread(root / "x")',
    'def read(path): return Path(path).read_text()\nread(root)\nread(path=root / "x")',
    'def read(path=root): return path.read_text()\nread()',
    'def read(*, path): return path.read_text()\nread(path=root)',
    'def read(path, /): return path.read_text()\nread(root)',
    'def read(path):\n    if path.is_file(): return path.read_text()\n    return read(path / "x")\nread(root)',
    'def read(path): return path.read_text()\ndef call(path): return read(path / "x")\ncall(root)',
    'def read(path): return path.read_text()\ndef main():\n    path = root / "x"\n    return read(path)\nmain()',
])
def test_helper_parameters_require_all_calls(code):
    checked = screen(PREFIX + code + '\n')
    assert checked.ok, checked.rules


@pytest.mark.parametrize('code', [
    'def read(path): return Path(path).read_text()\nread(root)\nread("/etc/x")',
    'def read(path): return Path(path).read_text()\nread(root)\nread("relative.txt")',
    'def read(path="relative.txt"): return Path(path).read_text()\nread(root)',
    'def read(path): return Path(path).read_text()\nread(root)\nread(Path("/etc/passwd"))',
    'def read(path): return Path(path).read_text()\nread(root)\nlist(map(read, [root]))',
    'def read(path): return Path(path).read_text()\nread(root)\nalias = read',
    'def read(path): return Path(path).read_text()\nread(root)\ndef other(): return read',
    'def read(path):\n    path = "/etc/x"\n    return Path(path).read_text()\nread(root)',
    'def read(path): return Path(path).read_text()\nread(*[root])',
    'def read(path): return Path(path).read_text()\nread(**{"path": root})',
    'def read(path): return Path(path).read_text()\nread(root)\ndef other(root): return read(root)\nother("/etc/x")',
    'def read(path): return Path(path).read_text()\nread = str\nread(root)',
    'def read(path): return Path(path).read_text()\nfilter(read, [root])',
])
def test_underived_or_escaped_helper_parameters_refused(code):
    checked = screen(PREFIX + code + '\n')
    assert not checked.ok and any(r.startswith('input-path:') for r in checked.rules), checked.rules


@pytest.mark.parametrize('name', list(PROBES))
def test_all_reviewer_screen_probes(name):
    checked = screen(PROBES[name])
    assert checked.ok == (name.split(':')[1] in CONTROLS), (name, checked.rules)
    if not checked.ok:
        assert checked.rules and all(':' in r for r in checked.rules)


@pytest.mark.parametrize('expression', ['"data" + ".txt"', 'f"{prefix}.txt"', '"".join([prefix, ".txt"])'])
def test_relative_constant_folding_still_allowed(expression):
    checked = screen(PREFIX + f'prefix = "data"\nprint(Path({expression}).read_text())\n')
    assert checked.ok, checked.rules


def test_helper_stored_under_same_name_in_class_is_escaped():
    code = PREFIX + "def read(path): return Path(path).read_text()\nread(root)\nclass Holder:\n    read = read\nHolder.read('/etc/x')\n"
    checked = screen(code)
    assert not checked.ok and any(r.startswith('input-path:') for r in checked.rules), checked.rules
