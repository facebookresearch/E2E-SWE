"""Fixtures for the binjgb test suite.

CTRF is emitted by the pytest-json-ctrf plugin (`pytest --ctrf ...` in
test.sh), so this file only wires up the tester binary fixture.
"""

import os
import sys

import pytest

# Allow importing helpers.py from the same dir when running under /tests/.
sys.path.insert(0, os.path.dirname(__file__))

import helpers  # noqa: E402


@pytest.fixture(scope="session")
def tester_bin():
    path = os.path.abspath(helpers.BINJGB_TESTER)
    assert os.path.exists(path), (
        f"binjgb-tester binary not found at {path}; setup.sh must build "
        f"./bin/binjgb-tester at the repo root"
    )
    assert os.access(path, os.X_OK), f"binjgb-tester at {path} is not executable"
    return path
