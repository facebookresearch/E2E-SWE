"""pytest bootstrap for the django-computedfields test suite.

Ensures the test directory (holding ``test_settings`` and the ``tests_app``
package) is importable and points Django at the test settings module before
pytest-django performs its setup.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "test_settings")
