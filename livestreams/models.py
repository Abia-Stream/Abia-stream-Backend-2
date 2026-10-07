import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class LiveStream(models.Model):
    """
    A broadcast. One Cloudinary live stream per row (its archive becomes the
    recording). Table predates the app; columns added in sql/008.
    """

    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Scheduled'
        LIVE = 'live', 'Live'
        ENDED = 'ended', 'Ended'
        CANCELLED = 'cancelled', 'Cancelled'
        FAILED = 'failed', 'Failed'

    OPEN_STATUSES = (Status.SCHEDULED, Status.LIVE)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='creator_id', related_name='livestreams',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(null=True, blank=True)

    # Ingest/playback, copied from Cloudinary at creation.
    stream_key = models.CharField(max_length=255, unique=True)
    rtmp_url = models.CharField(max_length=255, null=True, blank=True)
    hls_url = models.CharField(max_length=500, null=True, blank=True)
    thumbnail_url = models.CharField(max_length=500, null=True, blank=True)
    cloudinary_stream_id = models.TextField(null=True, blank=True)
    cloudinary_archive_public_id = models.TextField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    scheduled_start_time = models.DateTimeField(null=True, blank=True)
    actual_start_time = models.DateTimeField(null=True, blank=True)
    actual_end_time = models.DateTimeField(null=True, blank=True)
    status_checked_at = models.DateTimeField(null=True, blank=True)

    viewer_count = models.IntegerField(default=0)
    max_concurrent_viewers = models.IntegerField(default=0)
    chat_enabled = models.BooleanField(default=True)

    save_recording = models.BooleanField(default=True)
    publish_recording = models.BooleanField(default=False)
    recording_video = models.ForeignKey(
        'videos.Video', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='recording_video_id', related_name='source_livestreams',
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'livestreams'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} [{self.status}]'


class StreamViewer(models.Model):
    """One viewer session on one stream; left_at is the last heartbeat."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    livestream = models.ForeignKey(
        LiveStream, on_delete=models.CASCADE,
        db_column='livestream_id', related_name='viewers',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        db_column='user_id', related_name='stream_views',
    )
    session_id = models.UUIDField(null=True, blank=True)
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    watch_duration_seconds = models.IntegerField(default=0)
    is_anonymous = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'stream_viewers'


class ChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    livestream = models.ForeignKey(
        LiveStream, on_delete=models.CASCADE,
        db_column='livestream_id', related_name='chat_messages',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='user_id', related_name='livestream_chat_messages',
    )
    content = models.TextField()
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'livestream_chat_messages'
        ordering = ['created_at']
