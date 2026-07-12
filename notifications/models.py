import uuid
from django.db import models
from django.conf import settings


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column='user_id',
        related_name='notifications'
    )
    notification_type = models.CharField(max_length=50)
    title = models.CharField(max_length=255, null=True, blank=True)
    message = models.TextField(null=True, blank=True)
    data = models.JSONField(null=True, blank=True)
    is_read = models.BooleanField(default=False, null=True)
    is_archived = models.BooleanField(default=False, null=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        managed = False
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.email} — {self.notification_type}'