from pathlib import Path
from dotenv import load_dotenv
from decouple import config
import os
import dj_database_url
import cloudinary
import requests

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')


# Off unless explicitly enabled: a missing variable must never turn debug
# pages (route lists, tracebacks, settings) on in production.
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*').split(',')


RENDER_EXTERNAL_HOSTNAME = os.environ.get(
    "RENDER_EXTERNAL_HOSTNAME"
)

if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(
        f"https://{RENDER_EXTERNAL_HOSTNAME}"
    )

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

SECURE_CONTENT_TYPE_NOSNIFF = True       # prevent MIME sniffing
X_FRAME_OPTIONS = 'DENY'                 # prevent clickjacking
SECURE_BROWSER_XSS_FILTER = True         # XSS protection

# In production only:
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Application definition

INSTALLED_APPS = [
    'daphne',  # ← add (replaces gunicorn for ASGI)
    'corsheaders',
    # 'django.contrib.admin',
    # 'django.contrib.sessions',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',  # required for full-text search (videos/search)

    # allauth
    
    'channels',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',

    # dj-rest-auth
    'dj_rest_auth',
    'dj_rest_auth.registration',
    'rest_framework.authtoken',

    'rest_framework',
    'drf_spectacular',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'cloudinary',
       
        

    # Third party apps
    'accounts',
    'profiles',
    'videos',
    'playback',
    'creator_channels',
    'interactions',
    'subscriptions',
    'notifications',
    'realtime',
    'verification',
    'comments',
    'events',
    'recommendations',
    'experiments',
    'moderation',
    'analytics',
    'livestreams',
    'monetization',

]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
     'whitenoise.middleware.WhiteNoiseMiddleware', 
    # 'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    # 'django.contrib.auth.middleware.AuthenticationMiddleware',
    # 'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',  # ← required by allauth
]

ROOT_URLCONF = 'abiastream.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'abiastream.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT', default='5432'),
        'OPTIONS': {
            'options': '-c search_path=public'
        },
    }
}

DATABASE_ROUTERS = ['accounts.routers.SupabaseRouter']

# DATABASE_ROUTERS = ['accounts.routers.BlockDjangoInternalTablesRouter']

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

AUTH_USER_MODEL = 'accounts.User'

CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',      # frontend local dev
    'http://127.0.0.1:3000',  # frontend local dev alternative
    'https://abia-stream.vercel.app',   
]

# Allow credentials (needed for JWT in headers)
CORS_ALLOW_CREDENTIALS = True

# Allowed headers
CORS_ALLOW_HEADERS = [
    'accept',
    'authorization',
    'content-type',
    'origin',
    'x-requested-with',
    # Browsing-session id for events, experiments and view de-duplication
    # (events/utils.resolve_session_id). Without it browsers block the header.
    'x-session-id',
]


REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',

    # ── Pagination ────────────────────────────────────────────────────────
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 8,  # ← 8 per page as team lead specified

    # ── Throttling ────────────────────────────────────────────────────────
    # Scoped rather than global: the events endpoint is an open, unauthenticated
    # write endpoint and needs a ceiling, but video endpoints should not inherit
    # a limit tuned for telemetry.
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.ScopedRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        # Each request carries up to 100 events, so this is generous for a real
        # client and still caps a script.
        'events': '120/min',
        # Filing content reports (moderation/). Generous for a person, caps
        # a script trying to mass-report someone off the platform.
        'reports': '30/hour',
        # Livestreams: chat posts per viewer, and viewer heartbeats (~every 20s).
        'live_chat': '20/min',
        'live_heartbeat': '10/min',
        # Share button presses (interactions.ShareVideoView).
        'shares': '30/min',
        # Identity verification: each Smile session / manual submission.
        # Smile charges per job, so cap scripted retries.
        'verification': '10/hour',
    },
}
SPECTACULAR_SETTINGS = {
    'TITLE': 'ABIA STREAM API',
    'DESCRIPTION': 'API for ABIA STREAM',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': True,
}

from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,       # issue new refresh on every refresh
    'BLACKLIST_AFTER_ROTATION': True,      # blacklist old refresh token
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# allauth settings

# ACCOUNT_EMAIL_REQUIRED = True
# ACCOUNT_USERNAME_REQUIRED = False
# ACCOUNT_AUTHENTICATION_METHOD = 'email'
SITE_ID = 1
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'none'     # we handle verification ourselves

GOOGLE_CLIENT_ID = config('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = config('GOOGLE_CLIENT_SECRET')

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'OAUTH_PKCE_ENABLED': True,
        'APP': {
            'client_id': GOOGLE_CLIENT_ID,
            'secret': GOOGLE_CLIENT_SECRET,
            'key': ''
        }
    }
}

ASGI_APPLICATION = 'abiastream.asgi.application'

# DRF throttling stores its counters here. Without a shared backend it falls
# back to per-process local memory, which means the rate limit is enforced
# per Gunicorn worker rather than per deployment.
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://localhost:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            # A cache outage must not take the API down with it.
            'IGNORE_EXCEPTIONS': True,
        },
    }
}
DJANGO_REDIS_IGNORE_EXCEPTIONS = True

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [config('REDIS_URL', default='redis://localhost:6379')],
        },
    },
}

# ── Celery ────────────────────────────────────────────────────────────────────
# See abiastream/celery.py. Shares REDIS_URL with the cache and channel layer
# unless CELERY_BROKER_URL is set; their key names do not collide.
from celery.schedules import crontab

CELERY_BROKER_URL = config(
    'CELERY_BROKER_URL', default=config('REDIS_URL', default='redis://localhost:6379/0')
)
CELERY_TASK_IGNORE_RESULT = True          # nothing reads task results
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_ACKS_LATE = True              # a crashed worker's task is redelivered
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_TIMEOUT = 3      # bound how long a web request can wait
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_ALWAYS_EAGER = config('CELERY_TASK_ALWAYS_EAGER', default=False, cast=bool)

CELERY_BEAT_SCHEDULE = {
    # Keeps view_logs writable: creates next months' partitions ahead of time.
    'ensure-view-log-partitions': {
        'task': 'playback.tasks.ensure_view_log_partitions',
        'schedule': crontab(hour=1, minute=0),
    },
    # "Users who watched this also watched" — see recommendations/.
    'rebuild-related-videos': {
        'task': 'recommendations.tasks.rebuild_related_videos',
        'schedule': crontab(hour=3, minute=0),
    },
    # Livestream status/recordings/cleanup. Also happens on read, so this
    # only keeps things tidy when nobody is watching.
    # Stage 4 personalization (recommendations/ranker.py, up-next).
    'build-video-transitions': {
        'task': 'recommendations.tasks.build_video_transitions',
        'schedule': crontab(hour=3, minute=30),
    },
    'train-feed-ranker': {
        'task': 'recommendations.tasks.train_feed_ranker',
        'schedule': crontab(hour=4, minute=0),
    },
    # Fingerprint videos missed by upload-time checks (Cloudinary down, etc.).
    'scan-videos': {
        'task': 'moderation.tasks.scan_videos',
        'schedule': crontab(minute=20),
    },
    'sync-livestreams': {
        'task': 'livestreams.tasks.sync_livestreams',
        'schedule': 60.0,
    },
}

# Alternative — no extra table created
REST_AUTH = {
    'TOKEN_MODEL': None,
}

# Tell dj-rest-auth to use JWT
REST_USE_JWT = True
JWT_AUTH_COOKIE = 'access-token'
JWT_AUTH_REFRESH_COOKIE = 'refresh-token'

# Custom adapter
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.CustomSocialAccountAdapter'
ACCOUNT_ADAPTER = 'accounts.adapters.CustomAccountAdapter'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'ERROR',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': True,
        },
    },
}

# Transactional email (OTP codes) goes through an HTTP API, not SMTP.
#   resend - needs a verified domain; onboarding@resend.dev only delivers to
#            the Resend account owner.
#   brevo  - needs a verified domain too.
#   apps_script - Google Apps Script web app sending from a Gmail account
#            (scripts/send_email.gs); no domain needed.
EMAIL_PROVIDER = config('EMAIL_PROVIDER', default='resend')
APPS_SCRIPT_EMAIL_URL = config('APPS_SCRIPT_EMAIL_URL', default='')
APPS_SCRIPT_EMAIL_SECRET = config('APPS_SCRIPT_EMAIL_SECRET', default='')
RESEND_API_KEY = config('RESEND_API_KEY', default='')
BREVO_API_KEY = config('BREVO_API_KEY', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='onboarding@resend.dev')
EMAIL_FROM_NAME = config('EMAIL_FROM_NAME', default='Abia Stream')

# Keep SMTP for local development only
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

OTP_EXPIRY_MINUTES = 10



CLOUDINARY_CLOUD_NAME = config('CLOUDINARY_CLOUD_NAME')
CLOUDINARY_API_KEY = config('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = config('CLOUDINARY_API_SECRET')

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

# Signed delivery for non-public videos (videos/delivery.py). Without a token
# key, signed URLs do not expire; with one (Cloudinary token-based auth add-on)
# they expire after SIGNED_URL_TTL_SECONDS.
CLOUDINARY_AUTH_TOKEN_KEY = config('CLOUDINARY_AUTH_TOKEN_KEY', default='')
SIGNED_URL_TTL_SECONDS = config('SIGNED_URL_TTL_SECONDS', default=3600, cast=int)

# Cloudinary webhook signature check: off | log | enforce (videos/views.py).
CLOUDINARY_WEBHOOK_VERIFY = config('CLOUDINARY_WEBHOOK_VERIFY', default='log')

# Cloudinary Live Streaming (livestreams/). Idle timeout: how long a dropped
# encoder can reconnect before the stream counts as ended.
LIVESTREAM_IDLE_TIMEOUT_SECONDS = config('LIVESTREAM_IDLE_TIMEOUT_SECONDS', default=120, cast=int)
LIVESTREAM_MAX_RUNTIME_SECONDS = config('LIVESTREAM_MAX_RUNTIME_SECONDS', default=4 * 3600, cast=int)

# Automatic moderation (moderation/auto.py, text_checks.py). Comma-separated
# words/phrases; matches in comments and video text go to the moderation
# queue, and are refused in live chat.
from decouple import Csv
MODERATION_BANNED_TERMS = config('MODERATION_BANNED_TERMS', default='', cast=Csv())

# Upper bound for uploads when Cloudinary's own limit can't be read
# (videos/limits.py). Free plan: 100 MB.
# Paystack (monetization/). Test keys start sk_test_/pk_test_. The webhook URL
# to set in the Paystack dashboard is <api>/api/v1/monetization/paystack/webhook/.
PAYSTACK_SECRET_KEY = config('PAYSTACK_SECRET_KEY', default='')
PAYSTACK_PUBLIC_KEY = config('PAYSTACK_PUBLIC_KEY', default='')
# Where Paystack sends the viewer after paying (a frontend page that then calls
# GET /monetization/payments/<reference>/).
PAYSTACK_CALLBACK_URL = config('PAYSTACK_CALLBACK_URL', default='')

VIDEO_MAX_UPLOAD_BYTES_FALLBACK = config('VIDEO_MAX_UPLOAD_BYTES_FALLBACK',
                                         default=100 * 1024 * 1024, cast=int)

# Smile Identity (verification/). Keys come from the Smile Identity portal;
# the environment decides which API is called (sandbox: testapi.smileidentity.com,
# production: api.smileidentity.com). Without keys, /verification/submit/
# answers 503 instead of crashing.
SMILE_IDENTITY_PARTNER_ID = config('SMILE_IDENTITY_PARTNER_ID', default='')
SMILE_IDENTITY_API_KEY = config('SMILE_IDENTITY_API_KEY', default='')
SMILE_IDENTITY_ENVIRONMENT = config('SMILE_IDENTITY_ENVIRONMENT', default='sandbox')