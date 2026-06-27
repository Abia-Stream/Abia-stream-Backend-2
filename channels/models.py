import uuid
from django.db import models
from django.conf import settings


class CreatorChannel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column='user_id',
        related_name='channel'
    )
    channel_name = models.CharField(max_length=255, unique=True)
    channel_slug = models.CharField(max_length=255, unique=True)
    banner_url = models.CharField(max_length=500, null=True, blank=True)
    channel_description = models.TextField(null=True, blank=True)
    subscriber_count = models.IntegerField(null=True, blank=True, default=0)
    total_videos = models.IntegerField(null=True, blank=True, default=0)
    is_verified = models.BooleanField(null=True, blank=True, default=False)
    custom_thumbnail_url = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        managed = False
        db_table = 'creator_channels'

    def __str__(self):
        return self.channel_name