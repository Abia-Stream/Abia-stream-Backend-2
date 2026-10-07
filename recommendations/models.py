from django.db import models
from django.utils import timezone


class RelatedVideo(models.Model):
    """
    Precomputed item-to-item similarity.

    Computed offline rather than at request time — co-view similarity is an
    O(n^2)-ish aggregate over watch history and cannot be served live.
    Schema lives in sql/003_recommendations.sql.
    """

    id = models.BigAutoField(primary_key=True)
    video = models.ForeignKey(
        'videos.Video',
        on_delete=models.CASCADE,
        db_column='video_id',
        related_name='related_to',
    )
    related = models.ForeignKey(
        'videos.Video',
        on_delete=models.CASCADE,
        db_column='related_id',
        related_name='related_from',
    )
    score = models.FloatField(default=0)
    co_view_count = models.IntegerField(default=0)
    computed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'related_videos'
        unique_together = ('video', 'related')
        ordering = ['-score']

    def __str__(self):
        return f'{self.video_id} -> {self.related_id} ({self.score:.3f})'
