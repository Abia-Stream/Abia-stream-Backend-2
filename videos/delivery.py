"""
How a video's bytes reach a viewer.

Public videos are stored as Cloudinary `upload` assets and served from their
plain URL, exactly as before. Every other visibility is stored as an
`authenticated` asset, which Cloudinary only serves through a signed URL; the
API hands those out only to requesters who passed the access check.

Signed URLs are permanent unless CLOUDINARY_AUTH_TOKEN_KEY is set, in which
case they also carry an expiring token (Cloudinary token-based
authentication, an account add-on) valid for SIGNED_URL_TTL_SECONDS.

Stored URLs (cloudinary_url, cloudinary_thumbnail_url) are always the
unsigned form. Signing happens at read time, in this module only.
"""
from urllib.parse import urlparse

import cloudinary.uploader
import cloudinary.utils
from django.conf import settings

from videos.cloudinary_service import generate_adaptive_streaming_url

PUBLIC = 'upload'
AUTHENTICATED = 'authenticated'

# HLS adaptive bitrate, same transformation as
# cloudinary_service.generate_adaptive_streaming_url.
ABR_TRANSFORMATION = [{'streaming_profile': 'auto'}]
THUMBNAIL_TRANSFORMATION = [
    {'width': 1280, 'height': 720, 'crop': 'fill'},
    {'quality': 'auto'},
    {'start_offset': '1'},
]


def desired_delivery_type(visibility):
    from videos.models import Video
    return PUBLIC if visibility == Video.Visibility.PUBLIC else AUTHENTICATED


def delivery_type_from_url(url):
    """
    Read the delivery type out of a Cloudinary URL:
    https://res.cloudinary.com/<cloud>/video/<type>/...
    Defaults to PUBLIC for anything unrecognised, which is how every legacy
    row was uploaded.
    """
    parts = urlparse(url or '').path.split('/')
    if len(parts) > 3 and parts[3] == AUTHENTICATED:
        return AUTHENTICATED
    return PUBLIC


def has_asset(video):
    """Drafts get a placeholder public id and an empty URL until upload."""
    return bool(video.cloudinary_url) and not video.cloudinary_public_id.startswith('draft_')


def _extension(video):
    path = urlparse(video.cloudinary_url or '').path
    if '.' in path.rsplit('/', 1)[-1]:
        return path.rsplit('.', 1)[-1]
    return video.format or 'mp4'


def _signing_options():
    options = {'type': AUTHENTICATED, 'sign_url': True, 'secure': True}
    key = getattr(settings, 'CLOUDINARY_AUTH_TOKEN_KEY', '')
    if key:
        options['auth_token'] = {
            'key': key,
            'duration': settings.SIGNED_URL_TTL_SECONDS,
        }
    return options


def _signed(public_id, **options):
    url, _ = cloudinary.utils.cloudinary_url(
        public_id, resource_type='video', **options, **_signing_options())
    return url


def playback_urls(video):
    """
    URLs for someone already allowed to watch `video`.

    Returns {'cloudinary_url', 'cloudinary_thumbnail_url', 'streaming_url'}.
    For public assets the first two are the stored values, unchanged.
    """
    stored_thumbnail = video.cloudinary_thumbnail_url
    if not has_asset(video):
        return {
            'cloudinary_url': video.cloudinary_url,
            'cloudinary_thumbnail_url': stored_thumbnail,
            'streaming_url': None,
        }

    if video.cloudinary_delivery_type != AUTHENTICATED:
        return {
            'cloudinary_url': video.cloudinary_url,
            'cloudinary_thumbnail_url': stored_thumbnail,
            'streaming_url': generate_adaptive_streaming_url(video.cloudinary_public_id),
        }

    public_id = video.cloudinary_public_id
    thumbnail = stored_thumbnail
    # A thumbnail generated from the video frame lives on the video asset and
    # needs signing too; a separately uploaded image thumbnail does not.
    if not thumbnail or '/video/' in thumbnail:
        thumbnail = _signed(public_id, format='jpg',
                            transformation=THUMBNAIL_TRANSFORMATION)
    return {
        'cloudinary_url': _signed(public_id, format=_extension(video)),
        'cloudinary_thumbnail_url': thumbnail,
        'streaming_url': _signed(public_id, format='m3u8',
                                 transformation=ABR_TRANSFORMATION),
    }


def withheld_urls(video):
    """For a serializer call with no authorised requester: expose nothing playable."""
    return {
        'cloudinary_url': None,
        'cloudinary_thumbnail_url': (
            video.cloudinary_thumbnail_url
            if video.cloudinary_thumbnail_url and '/video/' not in video.cloudinary_thumbnail_url
            else None
        ),
        'streaming_url': None,
    }


def sync_delivery_type(video):
    """
    Move the Cloudinary asset to the delivery type its visibility requires.

    Returns True if the asset was moved. Raises on Cloudinary errors so the
    caller (a Celery task with retries, or the sync command) can retry.
    """
    from videos.models import Video

    desired = desired_delivery_type(video.visibility)
    if not has_asset(video) or video.cloudinary_delivery_type == desired:
        return False

    result = cloudinary.uploader.rename(
        video.cloudinary_public_id,
        video.cloudinary_public_id,
        resource_type='video',
        type=video.cloudinary_delivery_type,
        to_type=desired,
        invalidate=True,
        overwrite=False,
    )
    updates = {
        'cloudinary_delivery_type': desired,
        'cloudinary_url': result.get('secure_url') or video.cloudinary_url,
    }
    if result.get('version'):
        updates['cloudinary_version'] = str(result['version'])
    Video.objects.filter(id=video.id).update(**updates)
    for field, value in updates.items():
        setattr(video, field, value)
    return True
