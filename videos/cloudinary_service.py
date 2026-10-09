# videos/cloudinary_service.py
import time
import cloudinary
import cloudinary.uploader
import cloudinary.utils
import cloudinary.api
from django.conf import settings


# ── Video Upload ──────────────────────────────────────────────────────────────

def upload_video_to_cloudinary(file, public_id=None, delivery_type='upload'):
    """
    Server-side video upload to Cloudinary.
    delivery_type 'authenticated' stores the asset so only signed URLs work
    (see videos/delivery.py).
    """
    result = cloudinary.uploader.upload_large(
        file,
        resource_type='video',
        type=delivery_type,
        public_id=public_id,
        folder='abia_stream/videos',
        chunk_size=6000000,
        overwrite=False,
        eager=[
            {
                'width': 1280,
                'height': 720,
                'crop': 'scale',
                'format': 'mp4',
                'quality': 'auto',
            },
        ],
        eager_async=True,
    )
    return result


# ── Image Upload ──────────────────────────────────────────────────────────────

def upload_image_to_cloudinary(file, folder='abia_stream/avatars'):
    """
    Server-side image upload to Cloudinary.
    Used for avatars, banners, thumbnails.
    Pass the correct folder for each type.
    """
    result = cloudinary.uploader.upload(
        file,
        resource_type='image',
        folder=folder,
        transformation=[
            {'quality': 'auto', 'fetch_format': 'auto'},
        ],
        overwrite=True,
    )
    return result


# ── Signed Upload Params (client-side video) ──────────────────────────────────

def generate_signed_upload_params(folder='abia_stream/videos', delivery_type=None):
    """
    Signed params for direct frontend → Cloudinary VIDEO upload.
    Uses Cloudinary's official signing utility.

    With delivery_type='authenticated' the signature covers `type`, so the
    frontend MUST send the returned `type` field with the upload or Cloudinary
    rejects the signature. Omitted by default: existing clients are unaffected.
    """
    timestamp = int(time.time())

    params_to_sign = {
        'folder': folder,
        'timestamp': timestamp,
        # Do NOT include resource_type — Cloudinary excludes it from signing
    }
    if delivery_type and delivery_type != 'upload':
        params_to_sign['type'] = delivery_type

    signature = cloudinary.utils.api_sign_request(
        params_to_sign,
        settings.CLOUDINARY_API_SECRET
    )

    params = {
        'timestamp': timestamp,
        'signature': signature,
        'api_key': settings.CLOUDINARY_API_KEY,
        'cloud_name': settings.CLOUDINARY_CLOUD_NAME,
        'folder': folder,
        'upload_url': f'https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/video/upload',
    }
    if 'type' in params_to_sign:
        params['type'] = params_to_sign['type']
    return params


# ── Signed Upload Params (client-side image) ──────────────────────────────────

def generate_signed_image_upload_params(folder='abia_stream/avatars'):
    """
    Signed params for direct frontend → Cloudinary IMAGE upload.
    Pass the correct folder for each image type:
      avatars:            abia_stream/avatars
      profile banners:    abia_stream/banners
      channel banners:    abia_stream/channel_banners
      channel thumbnails: abia_stream/channel_thumbnails
      video thumbnails:   abia_stream/thumbnails
    """
    timestamp = int(time.time())

    params_to_sign = {
        'folder': folder,
        'timestamp': timestamp,
        # Do NOT include resource_type — Cloudinary excludes it from signing
    }

    signature = cloudinary.utils.api_sign_request(
        params_to_sign,
        settings.CLOUDINARY_API_SECRET
    )

    return {
        'timestamp': timestamp,
        'signature': signature,
        'api_key': settings.CLOUDINARY_API_KEY,
        'cloud_name': settings.CLOUDINARY_CLOUD_NAME,
        'folder': folder,
        'upload_url': f'https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload',
    }


# ── Thumbnail ─────────────────────────────────────────────────────────────────

def generate_thumbnail_url(public_id, timestamp_seconds='auto', version=None):
    """
    Auto-generate a thumbnail from the video. The default 'auto' lets
    Cloudinary pick the most visually interesting frame (roadmap Stage 2:
    better auto-picked thumbnails) instead of a fixed second, which is often
    a black or title frame. Pass a number of seconds for a fixed frame.
    """
    options = {'version': version} if version else {}
    return cloudinary.CloudinaryVideo(public_id).build_url(
        resource_type='video',
        format='jpg',
        transformation=[
            {'width': 1280, 'height': 720, 'crop': 'fill'},
            {'quality': 'auto'},
            {'start_offset': str(timestamp_seconds)},
        ],
        **options,
    )


def generate_thumbnail_url_at_percent(public_id, percent=10):
    """Generate thumbnail at a percentage through the video."""
    return cloudinary.CloudinaryVideo(public_id).build_url(
        resource_type='video',
        format='jpg',
        transformation=[
            {'width': 1280, 'height': 720, 'crop': 'fill'},
            {'quality': 'auto'},
            {'start_offset': f'{percent}p'},
        ]
    )


# ── Streaming ─────────────────────────────────────────────────────────────────

def generate_streaming_url(public_id, format='m3u8'):
    """Generate HLS streaming URL."""
    return cloudinary.CloudinaryVideo(public_id).build_url(
        resource_type='video',
        format=format,
        transformation=[
            {'streaming_profile': 'hd', 'format': 'm3u8'},
        ]
    )


def generate_adaptive_streaming_url(public_id):
    """Generate adaptive bitrate HLS URL."""
    return cloudinary.CloudinaryVideo(public_id).build_url(
        resource_type='video',
        format='m3u8',
        transformation=[
            {'streaming_profile': 'auto'},
        ]
    )


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_video_from_cloudinary(public_id, delivery_type='upload'):
    """Delete video from Cloudinary."""
    return cloudinary.uploader.destroy(
        public_id,
        resource_type='video',
        type=delivery_type,
        invalidate=True,
    )


def delete_image_from_cloudinary(public_id):
    """Delete image from Cloudinary."""
    return cloudinary.uploader.destroy(
        public_id,
        resource_type='image',
        invalidate=True,
    )


# ── Video Info ────────────────────────────────────────────────────────────────

def get_video_info(public_id):
    """Fetch metadata for an existing Cloudinary video."""
    return cloudinary.api.resource(
        public_id,
        resource_type='video',
    )