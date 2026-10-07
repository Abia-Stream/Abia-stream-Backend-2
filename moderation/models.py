import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
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
    class Source(models.TextChoices):
        USER = 'user', 'User report'
        AUTO = 'auto', 'Automatic check'

    # Null for automatic flags (source='auto').
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        db_column='reporter_id', related_name='reports_filed',
    )
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.USER)
    # What tripped an automatic flag, e.g. 'reupload_of_blocked' (moderation/auto.py).
    signal = models.CharField(max_length=50, null=True, blank=True)
    # What the automatic check found, e.g. {"matched_video_id": ..., "similarity": 0.9}.
    # (`details` is the human reporter's free text.)
    signal_details = models.JSONField(default=dict, blank=True)
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


class VideoFingerprint(models.Model):
    """Perceptual frame hashes of a video (moderation/fingerprint.py)."""

    video = models.OneToOneField(
        'videos.Video', on_delete=models.CASCADE, primary_key=True,
        db_column='video_id', related_name='fingerprint',
    )
    frame_hashes = ArrayField(models.BigIntegerField())
    duration_seconds = models.IntegerField(null=True, blank=True)
    computed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'video_fingerprints'


class ModerationAction(models.Model):
    """Audit log of moderator decisions. Append-only."""

    class Action(models.TextChoices):
        BLOCK_VIDEO = 'block_video', 'Block video'
        RESTORE_VIDEO = 'restore_video', 'Restore video'
        APPROVE_VIDEO = 'approve_video', 'Approve held video'
        REMOVE_COMMENT = 'remove_comment', 'Remove comment'
        RESTORE_COMMENT = 'restore_comment', 'Restore comment'
        SUSPEND_USER = 'suspend_user', 'Suspend user'
        UNSUSPEND_USER = 'unsuspend_user', 'Unsuspend user'
        DISMISS = 'dismiss', 'Dismiss reports'
        END_LIVESTREAM = 'end_livestream', 'End livestream'
        REMOVE_CHAT_MESSAGE = 'remove_chat_message', 'Remove chat message'

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
    livestream = models.ForeignKey(
        'livestreams.LiveStream', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='livestream_id', related_name='moderation_actions',
    )
    chat_message = models.ForeignKey(
        'livestreams.ChatMessage', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='chat_message_id', related_name='moderation_actions',
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
