import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings


class Event(models.Model):
    """
    Unified behavioural event log.

    Deliberately one table with a JSONB payload rather than a table per event
    type — the shape of each event differs, but every downstream consumer
    (search ranking, collaborative filtering, A/B analysis) reads them together.

    Schema lives in sql/001_events.sql; this model mirrors it.
    """

    class Type(models.TextChoices):
        SEARCH = 'search', 'Search'
        SEARCH_RESULT_CLICK = 'search_result_click', 'Search Result Click'
        IMPRESSION = 'impression', 'Impression'
        VIDEO_CLICK = 'video_click', 'Video Click'
        PLAY = 'play', 'Play'
        PAUSE = 'pause', 'Pause'
        SEEK = 'seek', 'Seek'
        SKIP = 'skip', 'Skip'
        COMPLETE = 'complete', 'Complete'

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        db_column='user_id',
        related_name='events',
    )
    session_id = models.UUIDField()
    video = models.ForeignKey(
        'videos.Video',
        on_delete=models.CASCADE,
        null=True, blank=True,
        db_column='video_id',
        related_name='events',
    )
    event_type = models.CharField(max_length=50, choices=Type.choices)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'events'
        ordering = ['-occurred_at']

    def __str__(self):
        return f'{self.event_type} @ {self.occurred_at}'
