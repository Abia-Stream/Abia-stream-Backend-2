import uuid
from django.db import models
from django.conf import settings


class Subscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscriber = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column='subscriber_id',
        related_name='subscriptions'
    )
    channel = models.ForeignKey(
        'creator_channels.CreatorChannel',
        on_delete=models.CASCADE,
        db_column='channel_id',
        related_name='subscribers'
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        managed = False
        db_table = 'subscriptions'
        unique_together = ('subscriber', 'channel')

    def __str__(self):
        return f'{self.subscriber.email} → {self.channel.channel_name}'