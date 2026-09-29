"""Test isolation: drop any connection-attached CQRS state between tests.

Some implementations track transaction-scoped de-duplication state on the DB
connection object. Under pytest-django the connection object is reused across
tests (and DB rollback does not clear Python attributes on it), so such state
can leak between tests and mask events. Clearing cqrs-named connection
attributes after each test keeps every test deterministic and independent.

This is a no-op for implementations that scope that state to the model instance.
"""

import pytest
from django.db import connections


@pytest.fixture(autouse=True)
def _clear_cqrs_connection_state():
    yield
    for conn in connections.all():
        for attr in [a for a in list(vars(conn)) if 'cqrs' in a.lower()]:
            try:
                delattr(conn, attr)
            except Exception:
                pass
