"""Minimal Django settings used to exercise the modelcluster implementation.

Mirrors the kind of project a real django-modelcluster user would configure: the
``tests_app`` application defines ClusterableModel subclasses wired together with
ParentalKey / ParentalManyToManyField / ClusterTaggableManager, alongside
``taggit`` (required by the contrib.taggit subsystem). SQLite is used so the
suite is self-contained, and USE_TZ / TIME_ZONE are set so the datetime
serialization behaviour can be exercised.
"""

import tempfile

SECRET_KEY = "modelcluster-test-secret"

USE_TZ = True

TIME_ZONE = "America/Chicago"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "taggit",
    "tests_app",
]

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# FileField serialization writes uploaded files to storage during to_json();
# point MEDIA_ROOT at a throwaway temp directory so this works in the grader.
MEDIA_ROOT = tempfile.mkdtemp(prefix="modelcluster-media-")

USE_DEPRECATED_PYTZ = False
