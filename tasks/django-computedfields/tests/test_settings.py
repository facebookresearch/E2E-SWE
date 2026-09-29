"""Minimal Django settings used to exercise the computedfields implementation.

Mirrors a real django-computedfields project: ``computedfields`` is installed
(its app config seals the resolver and connects the ORM signal handlers on
startup) alongside ``tests_app``, which defines the ComputedFieldsModel
subclasses wired together with @computed / ComputedField across FK, reverse-FK,
M2M, O2O, self and inheritance relations. SQLite in-memory keeps the suite
self-contained; ``tests_app`` ships no migrations so its schema (including the
computed columns) is created via run-syncdb at test-DB setup.
"""

SECRET_KEY = "computedfields-test-secret"

USE_TZ = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "computedfields",
    "tests_app",
]

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
