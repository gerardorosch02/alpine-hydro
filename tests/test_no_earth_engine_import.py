"""Importing the package must not import Earth Engine.

CI has no Earth Engine login, so `ee` may only be imported inside the
functions that need it. The check runs in a fresh interpreter, because
this test process may already hold modules imported by other tests.
"""

import subprocess
import sys

CODE = """
import importlib, pkgutil, sys
import alpinehydro
import alpinehydro.cli
for m in pkgutil.walk_packages(alpinehydro.__path__, "alpinehydro."):
    importlib.import_module(m.name)
assert "ee" not in sys.modules, "an alpinehydro import pulled in Earth Engine (ee)"
"""


def test_importing_alpinehydro_does_not_import_ee():
    result = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
