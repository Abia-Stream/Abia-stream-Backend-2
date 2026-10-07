"""
Moderation operations. Views stay thin; everything that changes content goes
through apply_action so that it is atomic, audited and resolves the reports
it answers.
"""
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import User
from comments.models import Comment
from moderation.models import ContentReport, ModerationAction
from moderation.permissions import STAFF_ROLES
from videos.models import Video

Action = ModerationAction.Action


class ModerationError(Exception):
    """A rejected moderation request; the message is safe to show the caller."""


# ── Reports ───────────────────────────────────────────────────────────────────

def file_report(reporter, *, video=None, comment=None, reason, details=None):
    """
    Record a report. Idempotent per reporter and target while the report is
    open. Returns (report, created).
    """
    if comment is not None:
        target_type = ContentReport.TargetType.COMMENT
        video = comment.video
        if comment.user_id == reporter.id:
            raise ModerationError('You cannot report your own comment.')
        lookup = {'comment': comment}
    elif video is not None:
        target_type = ContentReport.TargetType.VIDEO
        if video.creator_id == reporter.id:
            raise ModerationError('You cannot report your own video.')
        lookup = {'video': video, 'comment__isnull': True}
    else:
        raise ModerationError('A video or comment is required.')

    open_reports = ContentReport.objects.filter(
        reporter=reporter, target_type=target_type,
        status=ContentReport.Status.OPEN, **lookup,
    )
    existing = open_reports.first()
    if existing:
        return existing, False

    try:
        with transaction.atomic():
            report = ContentReport.objects.create(
                reporter=reporter, target_type=target_type,
                video=video, comment=comment,
                reason=reason, details=details or None,
            )
    except IntegrityError:
        # Lost a race with an identical request; the partial unique index
        # guarantees the other one exists.
        return open_reports.get(), False
    return report, True


def withdraw_video_report(reporter, video):
    """Used when the one-click `report` interaction is toggled off."""
    ContentReport.objects.filter(
        reporter=reporter, video=video, comment__isnull=True,
        target_type=ContentReport.TargetType.VIDEO,
        status=ContentReport.Status.OPEN,
    ).delete()


# ── Actions ───────────────────────────────────────────────────────────────────

def _notify(user, notification_type, title, message, data):
    from notifications.utils import create_notification
    create_notification(user=user, notification_type=notification_type,
                        title=title, message=message, data=data)


def _resolve_reports(moderator, status, note, *, video=None, comment=None):
    reports = ContentReport.objects.filter(status=ContentReport.Status.OPEN)
    if comment is not None:
        reports = reports.filter(comment=comment)
    else:
        reports = reports.filter(video=video, target_type=ContentReport.TargetType.VIDEO)
    return reports.update(
        status=status, reviewed_by=moderator,
        reviewed_at=timezone.now(), resolution_note=note,
    )


def _check_user_target(moderator, target):
    if target.id == moderator.id:
        raise ModerationError('You cannot moderate your own account.')
    if target.role == User.Role.ADMIN:
        raise ModerationError('Admins cannot be suspended here.')
    if target.role in STAFF_ROLES and moderator.role != User.Role.ADMIN:
        raise ModerationError('Only an admin can suspend a moderator.')


def apply_action(moderator, action, *, video=None, comment=None, user=None, note=None,
                 livestream=None, chat_message=None):
    """
    Apply one moderator decision. Returns (ModerationAction, reports_resolved).
    Raises ModerationError for an invalid request; nothing is changed then.
    """
    note = note or None
    metadata = {}
    resolved = 0

    with transaction.atomic():
        if action == Action.BLOCK_VIDEO:
            if video is None:
                raise ModerationError('video_id is required.')
            video = Video.objects.select_for_update().get(pk=video.pk)
            if video.status == Video.Status.BLOCKED:
                raise ModerationError('Video is already blocked.')
            from moderation.auto import pre_hold_status
            # Restoring later returns it to where it was before any hold.
            metadata['previous_status'] = (pre_hold_status(video)
                                           if video.status == Video.Status.HELD else video.status)
            video.status = Video.Status.BLOCKED
            video.save(update_fields=['status', 'updated_at'])
            resolved = _resolve_reports(moderator, ContentReport.Status.ACTIONED, note,
                                        video=video)
            user = video.creator

        elif action == Action.RESTORE_VIDEO:
            if video is None:
                raise ModerationError('video_id is required.')
            video = Video.objects.select_for_update().get(pk=video.pk)
            if video.status != Video.Status.BLOCKED:
                raise ModerationError('Video is not blocked.')
            last_block = ModerationAction.objects.filter(
                video=video, action=Action.BLOCK_VIDEO).order_by('-created_at').first()
            previous = (last_block.metadata.get('previous_status') if last_block else None)
            if previous not in Video.Status.values or previous == Video.Status.BLOCKED:
                previous = Video.Status.PUBLISHED if video.published_at else Video.Status.READY
            metadata['restored_status'] = previous
            video.status = previous
            video.save(update_fields=['status', 'updated_at'])
            user = video.creator

        elif action == Action.APPROVE_VIDEO:
            if video is None:
                raise ModerationError('video_id is required.')
            video = Video.objects.select_for_update().get(pk=video.pk)
            if video.status != Video.Status.HELD:
                raise ModerationError('Video is not held for review.')
            from moderation.auto import pre_hold_status
            restored = pre_hold_status(video)
            metadata['restored_status'] = restored
            video.status = restored
            video.save(update_fields=['status', 'updated_at'])
            resolved = _resolve_reports(moderator, ContentReport.Status.DISMISSED, note,
                                        video=video)
            user = video.creator

        elif action == Action.REMOVE_COMMENT:
            if comment is None:
                raise ModerationError('comment_id is required.')
            comment = Comment.objects.select_for_update().get(pk=comment.pk)
            if comment.is_deleted:
                raise ModerationError('Comment is already removed.')
            # Content is kept (unlike a user delete) so the decision can be reversed.
            comment.is_deleted = True
            comment.save(update_fields=['is_deleted'])
            if comment.parent_id:
                Comment.objects.filter(id=comment.parent_id).update(
                    replies_count=F('replies_count') - 1)
            resolved = _resolve_reports(moderator, ContentReport.Status.ACTIONED, note,
                                        comment=comment)
            video, user = comment.video, comment.user

        elif action == Action.RESTORE_COMMENT:
            if comment is None:
                raise ModerationError('comment_id is required.')
            comment = Comment.objects.select_for_update().get(pk=comment.pk)
            removed_by_moderator = ModerationAction.objects.filter(
                comment=comment, action=Action.REMOVE_COMMENT).exists()
            if not comment.is_deleted or not removed_by_moderator:
                raise ModerationError('Only comments removed by moderation can be restored.')
            comment.is_deleted = False
            comment.save(update_fields=['is_deleted'])
            if comment.parent_id:
                Comment.objects.filter(id=comment.parent_id).update(
                    replies_count=F('replies_count') + 1)
            video, user = comment.video, comment.user

        elif action == Action.SUSPEND_USER:
            if user is None:
                raise ModerationError('user_id is required.')
            user = User.objects.select_for_update().get(pk=user.pk)
            _check_user_target(moderator, user)
            if user.status == User.Status.SUSPENDED:
                raise ModerationError('User is already suspended.')
            metadata['previous_status'] = user.status
            user.status = User.Status.SUSPENDED
            user.save(update_fields=['status', 'updated_at'])

        elif action == Action.UNSUSPEND_USER:
            if user is None:
                raise ModerationError('user_id is required.')
            user = User.objects.select_for_update().get(pk=user.pk)
            _check_user_target(moderator, user)
            if user.status != User.Status.SUSPENDED:
                raise ModerationError('User is not suspended.')
            user.status = User.Status.ACTIVE
            user.save(update_fields=['status', 'updated_at'])

        elif action == Action.DISMISS:
            if comment is None and video is None:
                raise ModerationError('video_id or comment_id is required.')
            resolved = _resolve_reports(moderator, ContentReport.Status.DISMISSED, note,
                                        video=video, comment=comment)
            if comment is not None:
                video = comment.video
            if resolved == 0:
                raise ModerationError('There are no open reports to dismiss.')

        elif action == Action.END_LIVESTREAM:
            from livestreams.services import LiveStreamError, end_stream
            if livestream is None:
                raise ModerationError('livestream_id is required.')
            try:
                # Recording is kept but not published, for review.
                livestream = end_stream(livestream, by_moderator=True)
            except LiveStreamError as exc:
                raise ModerationError(str(exc))
            user = livestream.creator

        elif action == Action.REMOVE_CHAT_MESSAGE:
            from livestreams.services import hide_chat_message
            if chat_message is None:
                raise ModerationError('chat_message_id is required.')
            if not hide_chat_message(chat_message):
                raise ModerationError('Message is already removed.')
            livestream, user = chat_message.livestream, chat_message.user

        else:
            raise ModerationError(f'Unknown action: {action}.')

        record = ModerationAction.objects.create(
            moderator=moderator, action=action,
            video=video, comment=comment, target_user=user,
            livestream=livestream, chat_message=chat_message,
            note=note, metadata=metadata,
        )

    if action == Action.BLOCK_VIDEO:
        # Re-uploads of what was just blocked are held too (no network: uses
        # stored fingerprints).
        from moderation.auto import hold_reuploads_of
        metadata_held = hold_reuploads_of(video)
        if metadata_held:
            ModerationAction.objects.filter(id=record.id).update(
                metadata={**record.metadata, 'reuploads_held': metadata_held})
            record.metadata = {**record.metadata, 'reuploads_held': metadata_held}

    _notify_affected(action, video=video, comment=comment, user=user, note=note,
                     livestream=livestream)
    return record, resolved


def _notify_affected(action, *, video, comment, user, note, livestream=None):
    reason = f' Reason: {note}' if note else ''
    if action == Action.BLOCK_VIDEO:
        _notify(user, 'video_blocked', 'Video removed',
                f'Your video "{video.title}" was removed for violating the community '
                f'guidelines.{reason}', {'video_id': str(video.id)})
    elif action == Action.APPROVE_VIDEO:
        _notify(user, 'video_approved', 'Review complete',
                f'Your video "{video.title}" passed review and is available again.',
                {'video_id': str(video.id)})
    elif action == Action.RESTORE_VIDEO:
        _notify(user, 'video_restored', 'Video restored',
                f'Your video "{video.title}" has been restored.',
                {'video_id': str(video.id)})
    elif action == Action.REMOVE_COMMENT:
        _notify(user, 'comment_removed', 'Comment removed',
                f'One of your comments was removed for violating the community '
                f'guidelines.{reason}',
                {'comment_id': str(comment.id), 'video_id': str(comment.video_id)})
    elif action == Action.END_LIVESTREAM:
        _notify(user, 'livestream_ended_by_moderator', 'Stream ended',
                f'Your stream "{livestream.title}" was ended by a moderator. The recording '
                f'is kept unpublished.{reason}', {'livestream_id': str(livestream.id)})
