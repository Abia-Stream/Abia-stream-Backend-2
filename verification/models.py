"""Identity verification attempts (sql/012_verification_attempts.sql)."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class VerificationAttempt(models.Model):
    class Method(models.TextChoices):
        SMILE = 'smile', 'Smile ID'
        MANUAL = 'manual', 'Manual review'

    class Status(models.TextChoices):
        STARTED = 'started', 'Started'              # Smile token issued, nothing submitted yet
        PENDING = 'pending', 'Awaiting review'      # manual upload in the admin queue
        ATTENTION = 'attention', 'Flagged by Smile'  # Smile asked for a human decision
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        ERROR = 'error', 'Could not be processed'

    IN_REVIEW = (Status.PENDING, Status.ATTENTION)
    FINAL = (Status.APPROVED, Status.REJECTED, Status.ERROR)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             db_column='user_id', related_name='verification_attempts')
    method = models.CharField(max_length=10, choices=Method.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.STARTED)
    smile_job_id = models.TextField(null=True, blank=True, unique=True)
    id_type = models.TextField(null=True, blank=True)
    document_public_id = models.TextField(null=True, blank=True)
    selfie_public_id = models.TextField(null=True, blank=True)
    result_status = models.TextField(null=True, blank=True)
    result_message = models.TextField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, db_column='reviewed_by', related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'verification_attempts'
        ordering = ['-created_at']
