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


class RankerModel(models.Model):
    """
    A trained logistic-regression ranker (recommendations/ranker.py).
    Stored as plain numbers so serving needs no ML library. Schema: sql/010.
    """

    id = models.BigAutoField(primary_key=True)
    name = models.TextField(default='feed')
    feature_names = models.JSONField()
    weights = models.JSONField()
    intercept = models.FloatField()
    means = models.JSONField()
    stds = models.JSONField()
    # n_train, n_positive, holdout auc, baseline auc, activation decision.
    metrics = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'ranker_models'
        ordering = ['-created_at']


class VideoTransition(models.Model):
    """How often viewers watch `next_video` right after `video` (sql/010)."""

    id = models.BigAutoField(primary_key=True)
    video = models.ForeignKey(
        'videos.Video', on_delete=models.CASCADE,
        db_column='video_id', related_name='transitions_from',
    )
    next_video = models.ForeignKey(
        'videos.Video', on_delete=models.CASCADE,
        db_column='next_video_id', related_name='transitions_to',
    )
    transitions = models.IntegerField(default=0)
    score = models.FloatField(default=0)
    computed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'video_transitions'
        unique_together = ('video', 'next_video')
