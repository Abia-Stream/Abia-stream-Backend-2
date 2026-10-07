"""
Settings for running the test suite.

    python manage.py test --settings=abiastream.test_settings

Every table in this project is unmanaged (the schema lives in Supabase), so
Django cannot build a test database on its own. abiastream/test_runner.py
creates one on a LOCAL Postgres from sql/baseline + sql/0*.sql instead.

The values below are forced (not defaulted) so a real .env can never leak a
live database, Cloudinary account or Redis instance into a test run.
"""
import os

os.environ['SECRET_KEY'] = 'test-secret-key-not-for-production'
os.environ['DEBUG'] = 'False'
os.environ['CLOUDINARY_CLOUD_NAME'] = 'test-cloud'
os.environ['CLOUDINARY_API_KEY'] = '000000000000000'
os.environ['CLOUDINARY_API_SECRET'] = 'test-cloudinary-secret'
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-google-client')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', 'test-google-secret')
for key in ('DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST'):
    os.environ.setdefault(key, 'unused')

from abiastream.settings import *  # noqa: E402,F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('TEST_DB_NAME', 'abiastream'),
        'USER': os.environ.get('TEST_DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('TEST_DB_PASSWORD', ''),
        'HOST': os.environ.get('TEST_DB_HOST', 'localhost'),
        'PORT': os.environ.get('TEST_DB_PORT', '5432'),
    }
}

TEST_RUNNER = 'abiastream.test_runner.SchemaTestRunner'

# No Redis needed to run tests.
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = 'memory://'

SECURE_SSL_REDIRECT = False
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
