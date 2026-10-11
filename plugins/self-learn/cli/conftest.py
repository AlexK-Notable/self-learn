"""Package-root conftest: isolate the tests from the developer's git config.

pytest loads this before ``tests/conftest.py`` (which is byte-pinned by
``tests/test_armor.py``), for every run: the suite runner, a single file,
and every CLI subprocess a test spawns, since those inherit ``os.environ``.

Only the tests are exempted. The product, and the developer's own shell,
keep reading ``~/.gitconfig`` as before.
"""

import os
from pathlib import Path

os.environ["GIT_CONFIG_GLOBAL"] = str(Path(__file__).parent / "tests" / "gitconfig.test")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
