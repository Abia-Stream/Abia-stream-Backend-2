from django.db import models
from django.conf import settings


class Experiment(models.Model):
    """Schema lives in sql/004_experiments.sql."""

    id = models.BigAutoField(primary_key=True)
    key = models.CharField(max_length=255, unique=True)
    description = models.TextField(null=True, blank=True)
    variants = models.JSONField(default=list)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'experiments'

    def __str__(self):
        return self.key


class ExperimentAssignment(models.Model):
    """
    A subject's sticky variant for one experiment.

    Assignment is persisted rather than recomputed per request so that a user
    who signs in, changes device, or clears storage keeps the same variant —
    otherwise results are contaminated by subjects crossing between arms.
    """

    id = models.BigAutoField(primary_key=True)
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        db_column='experiment_id',
        related_name='assignments',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        db_column='user_id',
        related_name='experiment_assignments',
    )
    session_id = models.UUIDField(null=True, blank=True)
    variant = models.CharField(max_length=100)
    assigned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'experiment_assignments'

    def __str__(self):
        return f'{self.experiment_id}:{self.variant}'
