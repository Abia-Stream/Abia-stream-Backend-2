"""
Auto-picked thumbnails for every upload path.

Server uploads already get Cloudinary's best-frame thumbnail
(cloudinary_service.generate_thumbnail_url, `so_auto`). Direct uploads used
to store whatever frame URL the frontend built (e.g. `so_1`, often a black or
title frame). Here a thumbnail that is just a frame of the video itself is
upgraded to the best-frame one; a separately uploaded image (a creator's
deliberate choice, `/image/upload/...`) is never touched.

Cloudinary builds the best-frame image on first request and answers
423 (Locked) until it's ready — up to a minute for larger videos (verified
2026-10-09). So the switch only happens once the image is confirmed ready;
until then the old thumbnail stays and nothing ever shows a broken image:

    upload            -> warm(): start generation in the background
    processing done   -> upgrade_when_ready()
    publish           -> upgrade_when_ready()
    backfill command  -> refresh_auto_thumbnails
"""
import logging
import re
import threading
from urllib.parse import urlparse

import requests

from videos.cloudinary_service import generate_thumbnail_url
from videos.delivery import has_asset

logger = logging.getLogger(__name__)

READY_CHECK_TIMEOUT_SECONDS = 10

UPDATED, PENDING, UNCHANGED = 'updated', 'pending', 'unchanged'


def is_frame_of_video(url, public_id):
    """True if `url` is a Cloudinary still taken from this video's own asset."""
    if not url:
        return False
    parsed = urlparse(url)
    parts = parsed.path.split('/')
    return (parsed.netloc.endswith('cloudinary.com') and len(parts) > 2
            and parts[2] == 'video' and public_id in parsed.path)


def asset_version(video):
    """The asset version (cache-busting `v123…` segment), if we know it."""
    if video.cloudinary_version:
        return video.cloudinary_version
    match = re.search(r'/v(\d+)/', urlparse(video.cloudinary_url or '').path)
    return match.group(1) if match else None


def best_thumbnail(video):
    """The best-frame URL this video should use, or None to leave it alone."""
    if not has_asset(video):
        return None
    current = video.cloudinary_thumbnail_url
    if current and not is_frame_of_video(current, video.cloudinary_public_id):
        return None  # a custom image thumbnail: keep it
    best = generate_thumbnail_url(video.cloudinary_public_id, version=asset_version(video))
    return None if current == best else best


def is_ready(url):
    """True once Cloudinary serves the image (False while it answers 423)."""
    try:
        response = requests.get(url, timeout=READY_CHECK_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 - not ready as far as we can tell
        return False
    return response.status_code == 200 and \
        response.headers.get('content-type', '').startswith('image/')


def warm(video):
    """Ask Cloudinary to start building the best frame, without waiting."""
    url = best_thumbnail(video)
    if url:
        threading.Thread(target=is_ready, args=(url,), daemon=True).start()


def upgrade_when_ready(video, save=True):
    """
    Switch to the best-frame thumbnail if Cloudinary has it ready.
    Returns UPDATED, PENDING (not ready yet, old one kept) or UNCHANGED.
    Never raises.
    """
    from videos.models import Video
    try:
        url = best_thumbnail(video)
        if url is None:
            return UNCHANGED
        if not is_ready(url):
            return PENDING
        video.cloudinary_thumbnail_url = url
        if save:
            Video.objects.filter(id=video.id).update(cloudinary_thumbnail_url=url)
        return UPDATED
    except Exception:  # noqa: BLE001 - thumbnails must never break an upload or publish
        logger.exception('Thumbnail upgrade failed for video %s', video.id)
        return UNCHANGED
