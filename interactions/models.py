# interactions/models.py
import uuid
from django.db import models
from django.conf import settings


class Interaction(models.Model):
    class InteractionType(models.TextChoices):
        LIKE = 'like', 'Like'
        DISLIKE = 'dislike', 'Dislike'
        SAVE = 'save', 'Save'
        FAVOURITE = 'favourite', 'Favourite'
        REPORT = 'report', 'Report'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='user_id', related_name='interactions')
    video = models.ForeignKey('videos.Video', on_delete=models.CASCADE, db_column='video_id', related_name='interactions')
    interaction_type = models.CharField(max_length=20, choices=InteractionType.choices)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        managed = False
        db_table = 'interactions'
        unique_together = ('user', 'video', 'interaction_type')

    def __str__(self):
        return f'{self.user.email} {self.interaction_type} {self.video.title}'