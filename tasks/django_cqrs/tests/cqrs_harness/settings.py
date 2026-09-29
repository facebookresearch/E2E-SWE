SECRET_KEY = 'cqrs-pilot-secret'
DEBUG = True
USE_TZ = False

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'cqrs_harness',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    },
}

CQRS = {
    'transport': 'cqrs_harness.transport.CapturingTransport',
    'queue': 'replica',
    'master': {
        'CQRS_AUTO_UPDATE_FIELDS': False,
        'CQRS_MESSAGE_TTL': 3600,
        'correlation_function': None,
        'meta_function': None,
    },
    'replica': {
        'CQRS_MAX_RETRIES': 5,
        'CQRS_RETRY_DELAY': 1,
        'delay_queue_max_size': 1000,
    },
}
