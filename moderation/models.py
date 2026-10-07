import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ContentReport(models.Model):
    """A user's report of a video or comment. Schema: sql/007_moderation.sql."""

    class TargetType(models.TextChoices):
        VIDEO = 'video', 'Video'
        COMMENT = 'comment', 'Comment'

    class Reason(models.TextChoices):
        SPAM = 'spam', 'Spam'
        HARASSMENT = 'harassment', 'Harassment or bullying'
        HATE = 'hate', 'Hate speech'
        VIOLENCE = 'violence', 'Violence'
        SEXUAL = 'sexual', 'Sexual content'
        CHILD_SAFETY = 'child_safety', 'Child safety'
        COPYRIGHT = 'copyright', 'Copyright'
        MISINFORMATION = 'misinformation', 'Misinformation'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        ACTIONED = 'actioned', 'Actioned'
        DISMISSED = 'dismissed', 'Dismissed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='reporter_id', related_name='reports_filed',
    )
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    video = models.ForeignKey(
        'videos.Video', on_delete=models.CASCADE, null=True, blank=True,
        db_column='video_id', related_name='reports',
    )
    comment = models.ForeignKey(
        'comments.Comment', on_delete=models.CASCADE, null=True, blank=True,
        db_column='comment_id', related_name='reports',
    )
    reason = models.CharField(max_length=30, choices=Reason.choices)
    details = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        db_column='reviewed_by', related_name='reports_reviewed',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'content_reports'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.target_type} report ({self.reason}) [{self.status}]'


class ModerationAction(models.Model):
    """Audit log of moderator decisions. Append-only."""

    class Action(models.TextChoices):
        BLOCK_VIDEO = 'block_video', 'Block video'
        RESTORE_VIDEO = 'restore_video', 'Restore video'
        REMOVE_COMMENT = 'remove_comment', 'Remove comment'
        RESTORE_COMMENT = 'restore_comment', 'Restore comment'
        SUSPEND_USER = 'suspend_user', 'Suspend user'
        UNSUSPEND_USER = 'unsuspend_user', 'Unsuspend user'
        DISMISS = 'dismiss', 'Dismiss reports'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        db_column='moderator_id', related_name='moderation_actions',
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    video = models.ForeignKey(
        'videos.Video', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='video_id', related_name='moderation_actions',
    )
    comment = models.ForeignKey(
        'comments.Comment', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='comment_id', related_name='moderation_actions',
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        db_column='target_user_id', related_name='moderation_actions_received',
    )
    note = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'moderation_actions'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} by {self.moderator_id}'
