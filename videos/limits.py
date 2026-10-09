"""
The largest video Cloudinary will accept on this account.

Read from Cloudinary's usage API (media_limits.video_max_size_bytes) and
cached, so it follows plan upgrades automatically. Falls back to
VIDEO_MAX_UPLOAD_BYTES_FALLBACK (the Free plan's 100 MB) if it can't be read.
"""
import logging

import cloudinary.api
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = 'cloudinary:video_max_size_bytes'
CACHE_SECONDS = 6 * 3600


def max_video_bytes():
    cached = cache.get(CACHE_KEY)
    if cached:
        return cached
    try:
        limit = int(cloudinary.api.usage()['media_limits']['video_max_size_bytes'])
    except Exception as exc:  # noqa: BLE001 - never block uploads on this lookup
        logger.error('Could not read Cloudinary upload limit: %s', exc)
        return settings.VIDEO_MAX_UPLOAD_BYTES_FALLBACK
    cache.set(CACHE_KEY, limit, CACHE_SECONDS)
    return limit


def human_size(num_bytes):
    return f'{num_bytes / (1024 * 1024):.0f} MB'
