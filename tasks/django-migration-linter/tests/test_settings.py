"""Minimal Django settings exercising the migration linter.

Mirrors a real project: ``django_migration_linter`` is installed (which provides
the ``lintmigrations`` management command and overrides ``makemigrations``)
alongside a handful of small applications whose migration fixtures cover the
backward-incompatible scenarios the linter must detect. SQLite keeps the suite
self-contained.
"""

SECRET_KEY = "django-migration-linter-test-secret"

USE_TZ = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django_migration_linter",
    "app_correct",
    "app_add_not_null",
    "app_drop_table",
    "app_rename_table",
    "app_ignore",
    "app_data_migration",
    "app_makemig",
]

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
