"""Shared fixtures for the test suite (see abiastream/test_runner.py)."""
import uuid

from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from videos.models import Video


def make_user(role=User.Role.VIEWER, **extra):
    extra.setdefault('status', User.Status.ACTIVE)
    extra.setdefault('is_email_verified', True)
    return User.objects.create_user(
        email=f'{uuid.uuid4().hex[:10]}@example.com',
        password='pass-word-123',
        role=role,
        **extra,
    )


def make_video(creator, **extra):
    public_id = extra.pop('cloudinary_public_id', f'abia_stream/videos/{uuid.uuid4().hex}')
    defaults = {
        'title': 'Test video',
        'cloudinary_public_id': public_id,
        'cloudinary_url': f'https://res.cloudinary.com/test-cloud/video/upload/v1/{public_id}.mp4',
        'status': Video.Status.PUBLISHED,
        'visibility': Video.Visibility.PUBLIC,
        'published_at': timezone.now(),
        'duration_seconds': 120,
    }
    defaults.update(extra)
    return Video.objects.create(creator=creator, **defaults)


def client_for(user=None):
    client = APIClient()
    if user is not None:
        token = RefreshToken.for_user(user).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client
