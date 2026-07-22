# videos/cloudinary_service.py
import time
import hashlib
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.conf import settings


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_video_to_cloudinary(file, public_id=None):
    """
    Server-side upload — uploads video file directly from Django to Cloudinary.
    Uses chunked upload for large files.
    """
    result = cloudinary.uploader.upload_large(
        file,
        resource_type='video',
        public_id=public_id,
        folder='abia_stream/videos',
        chunk_size=6000000,  # 6MB chunks
        overwrite=False,
        eager=[
            # Auto-generate 720p version
            {
                'width': 1280,
                'height': 720,
                'crop': 'scale',
                'format': 'mp4',
                'quality': 'auto',
            },
        ],
        eager_async=True,   # process transcoding in background
    )
    return result


def upload_image_to_cloudinary(file, folder='abia_stream/thumbnails'):
    """Upload a custom thumbnail image."""
    result = cloudinary.uploader.upload(
        file,
        resource_type='image',
        folder=folder,
        transformation=[
            {'width': 1280, 'height': 720, 'crop': 'fill', 'quality': 'auto'},
        ],
    )
    return result


# ── Thumbnail ─────────────────────────────────────────────────────────────────

def generate_thumbnail_url(public_id, timestamp_seconds=1):
    """
    Auto-generate a thumbnail from a video at a given timestamp.
    Defaults to 1 second in to avoid black frames.
    """
    return cloudinary.CloudinaryVideo(public_id).build_url(
        resource_type='video',
        format='jpg',
        transformation=[
            {'width': 1280, 'height': 720, 'crop': 'fill'},
            {'quality': 'auto'},
            {'start_offset': str(timestamp_seconds)},
        ]
    )


def generate_thumbnail_url_at_percent(public_id, percent=10):
    """Generate thumbnail at a percentage through the video e.g. 10%."""
    return cloudinary.CloudinaryVideo(public_id).build_url(
        resource_type='video',
        format='jpg',
        transformation=[
            {'width': 1280, 'height': 720, 'crop': 'fill'},
            {'quality': 'auto'},
            {'start_offset': f'{percent}p'},
        ]
    )


# ── Signed Upload (client-side) ───────────────────────────────────────────────

def generate_signed_upload_params(folder='abia_stream/videos'):
    """
    Generate signed parameters for direct frontend → Cloudinary upload.

    Frontend uses these to upload directly without routing through Django.
    After upload, frontend calls /api/videos/upload/from-cloudinary/
    with the Cloudinary response data.

    Returns:
        dict with timestamp, signature, api_key, cloud_name, folder
    """
    timestamp = int(time.time())

    params_to_sign = {
        'folder': folder,
        'resource_type': 'video',
        'timestamp': timestamp,
    }

    # Build the string to sign (sorted alphabetically)
    param_str = '&'.join(
        f'{k}={v}' for k, v in sorted(params_to_sign.items())
    )
    signature_str = f'{param_str}{settings.CLOUDINARY_API_SECRET}'
    signature = hashlib.sha256(signature_str.encode()).hexdigest()

    return {
        'timestamp': timestamp,
        'signature': signature,
        'api_key': settings.CLOUDINARY_API_KEY,
        'cloud_name': settings.CLOUDINARY_CLOUD_NAME,
        'folder': folder,
        'resource_type': 'video',
        # Frontend upload URL:
        'upload_url': f'https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/video/upload',
    }


# ── Streaming URL ─────────────────────────────────────────────────────────────

def generate_streaming_url(public_id, format='m3u8'):
    """
    Generate an HLS streaming URL for a video.
    Requires Cloudinary's streaming profile.
    """
    return cloudinary.CloudinaryVideo(public_id).build_url(
        resource_type='video',
        format=format,
        transformation=[
            {'streaming_profile': 'hd', 'format': 'm3u8'},
        ]
    )


def generate_adaptive_streaming_url(public_id):
    """Generate an adaptive bitrate HLS URL (auto quality switching)."""
    return cloudinary.CloudinaryVideo(public_id).build_url(
        resource_type='video',
        format='m3u8',
        transformation=[
            {'streaming_profile': 'auto'},
        ]
    )


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_video_from_cloudinary(public_id):
    """
    Delete a video from Cloudinary by its public_id.
    Called when a video is deleted from the platform.
    """
    result = cloudinary.uploader.destroy(
        public_id,
        resource_type='video',
        invalidate=True,   # purge from CDN cache too
    )
    return result


def delete_image_from_cloudinary(public_id):
    """Delete a thumbnail or image from Cloudinary."""
    result = cloudinary.uploader.destroy(
        public_id,
        resource_type='image',
        invalidate=True,
    )
    return result


# ── Video Info ────────────────────────────────────────────────────────────────

def get_video_info(public_id):
    """
    Fetch metadata for an existing Cloudinary video.
    Useful for syncing duration, dimensions after async processing.
    """
    import cloudinary.api
    return cloudinary.api.resource(
        public_id,
        resource_type='video',
    )



def generate_signed_upload_params(folder='abia_stream/videos'):
    """
    Generate signed parameters for direct frontend → Cloudinary upload.
    Uses Cloudinary's official signing method.
    """
    import time
    import cloudinary.utils

    timestamp = int(time.time())

    params_to_sign = {
        'folder': folder,
        'timestamp': timestamp,
    }

    # Use Cloudinary's official signing utility
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
        'resource_type': 'video',
        'upload_url': f'https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/video/upload',
    }


def generate_signed_thumbnail_url(public_id, expires_in=3600):
    """Generate a signed thumbnail URL."""
    timestamp = int(time.time()) + expires_in

    signed_url = cloudinary.utils.cloudinary_url(
        public_id,
        resource_type='video',
        format='jpg',
        sign_url=True,
        expires_at=timestamp,
        transformation=[
            {'width': 1280, 'height': 720, 'crop': 'fill'},
            {'quality': 'auto'},
        ]
    )[0]

    return signed_url

# ── Image Info ────────────────────────────────────────────────────────────────

def upload_image_to_cloudinary(file, folder='abia_stream/avatars'):
    """Upload image (avatar/banner) to Cloudinary."""
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


def generate_signed_image_upload_params(folder='abia_stream/avatars'):
    import time
    import cloudinary.utils

    timestamp = int(time.time())

    # resource_type must be included in signature
    params_to_sign = {
        'folder': folder,
        'timestamp': timestamp,
        'resource_type': 'image',  # ← add this
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
        'resource_type': 'image',
        'upload_url': f'https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload',
    }


def upload_image_to_cloudinary(file, folder='abia_stream/channel_banner'):
    """Upload image (avatar/banner) to Cloudinary."""
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


def generate_signed_image_upload_params(folder='abia_stream/channel_banner'):
    import time
    import cloudinary.utils

    timestamp = int(time.time())

    # resource_type must be included in signature
    params_to_sign = {
        'folder': folder,
        'timestamp': timestamp,
        'resource_type': 'image',  # ← add this
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
        'resource_type': 'image',
        'upload_url': f'https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload',
    }