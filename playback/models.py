import uuid
from django.db import models
from django.conf import settings


class WatchHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column='user_id',
        related_name='watch_history'
    )
    video = models.ForeignKey(
        'videos.Video',
        on_delete=models.CASCADE,
        db_column='video_id',
        related_name='watch_history'
    )
    last_watched_at = models.DateTimeField(null=True, blank=True)
    watch_progress_seconds = models.IntegerField(null=True, blank=True, default=0)
    completed = models.BooleanField(null=True, blank=True, default=False)
    device_type = models.CharField(max_length=50, null=True, blank=True)
    session_id = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'watch_history'

    def __str__(self):
        return f'{self.user.email} watched {self.video.title}'


class ViewLog(models.Model):
    # Must be BigAutoField, not BigIntegerField. With a non-auto pk, Django
    # sends an explicit id=NULL on INSERT, which overrides the column's serial
    # default and violates the NOT NULL constraint — every create() fails.
    id = models.BigAutoField(primary_key=True)
    video = models.ForeignKey(
        'videos.Video',
        on_delete=models.CASCADE,
        db_column='video_id',
        related_name='view_logs'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        db_column='user_id',
        related_name='view_logs'
    )
    session_id = models.UUIDField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    referrer = models.CharField(max_length=500, null=True, blank=True)
    watch_duration_seconds = models.IntegerField(null=True, blank=True, default=0)
    completed = models.BooleanField(null=True, blank=True, default=False)
    device_type = models.CharField(max_length=50, null=True, blank=True)
    country_code = models.CharField(max_length=2, null=True, blank=True)
    timestamp = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'view_logs'

    def __str__(self):
        return f'View log for {self.video.title}'