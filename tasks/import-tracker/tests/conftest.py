"""Test configuration: add sample_libs to sys.path and reset sys.modules between tests."""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.absolute() / "sample_libs"))


@pytest.fixture(autouse=True)
def reset_sys_modules():
    """Reset sys.modules to pre-test state after each test to avoid cross-contamination."""
    before_keys = list(sys.modules.keys())
    yield
    added_keys = [k for k in sys.modules.keys() if k not in before_keys]
    for k in added_keys:
        mod = sys.modules.pop(k)
        del mod


@pytest.fixture(autouse=True)
def configure_logging():
    """Set logging to WARNING by default to keep output clean."""
    logging.basicConfig()
    logging.getLogger().setLevel(logging.WARNING)
