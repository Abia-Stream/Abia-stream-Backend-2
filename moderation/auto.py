"""
Automatic moderation (roadmap Stage 2).

Policy (decided 2026-10-07):
  - strong match  -> video HELD from the public until a moderator approves
                     or blocks it, plus a queue entry
                     (re-upload of a blocked video)
  - weaker signal -> queue entry only, content stays up
                     (copy of another creator's video, spammy text)

Every function here is best-effort: a failure is logged and the upload,
publish or comment goes through, so checks can never take the site down.
The `scan_videos` command (and its beat task) catches anything missed.
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from moderation import fingerprint as fp
from moderation import text_checks
from moderation.models import ContentReport, VideoFingerprint

logger = logging.getLogger(__name__)

REUPLOAD_OF_BLOCKED = 'reupload_of_blocked'
DUPLICATE_OF_OTHER_CREATOR = 'duplicate_of_other_creator'

TEXT_SIGNAL_REASON = {
    text_checks.SPAM_LINKS: ContentReport.Reason.SPAM,
    text_checks.CONTACT_SPAM: ContentReport.Reason.SPAM,
    text_checks.BANNED_TERM: ContentReport.Reason.OTHER,
}


# ── Queue entries ─────────────────────────────────────────────────────────────

def flag(*, signal, reason, details=None, video=None, comment=None):
    """Add an automatic entry to the moderation queue (idempotent while open)."""
    if comment is not None:
        target = {'target_type': ContentReport.TargetType.COMMENT, 'comment': comment,
                  'video_id': comment.video_id}
        lookup = {'comment': comment}
    else:
        target = {'target_type': ContentReport.TargetType.VIDEO, 'video': video}
        lookup = {'video': video, 'target_type': ContentReport.TargetType.VIDEO}

    existing = ContentReport.objects.filter(
        source=ContentReport.Source.AUTO, signal=signal,
        status=ContentReport.Status.OPEN, **lookup).first()
    if existing:
        return existing
    try:
        with transaction.atomic():
            return ContentReport.objects.create(
                source=ContentReport.Source.AUTO, reporter=None, signal=signal,
                reason=reason, signal_details=details or {}, **target)
    except IntegrityError:
        return ContentReport.objects.filter(
            source=ContentReport.Source.AUTO, signal=signal,
            status=ContentReport.Status.OPEN, **lookup).first()


# ── Holding ───────────────────────────────────────────────────────────────────

def hold_video(video, *, signal, details):
    """Hide `video` until reviewed. Returns True if this call put it on hold."""
    from notifications.utils import create_notification
    from videos.models import Video

    with transaction.atomic():
        locked = Video.objects.select_for_update().get(id=video.id)
        if locked.status in (Video.Status.HELD, Video.Status.BLOCKED):
            return False
        previous = locked.status
        locked.status = Video.Status.HELD
        locked.save(update_fields=['status', 'updated_at'])
        flag(video=locked, signal=signal, reason=ContentReport.Reason.COPYRIGHT,
             details={**details, 'previous_status': previous})

    video.status = Video.Status.HELD
    create_notification(
        user=locked.creator, notification_type='video_held', title='Video under review',
        message=f'Your video "{locked.title}" is being reviewed by our moderators before '
                'it can be shown. You will be notified when the review is done.',
        data={'video_id': str(locked.id)},
    )
    return True


def pre_hold_status(video):
    """The status a held video had before it was held (for approve / block)."""
    from videos.models import Video

    report = (ContentReport.objects.filter(
        video=video, source=ContentReport.Source.AUTO,
        signal_details__has_key='previous_status').order_by('-created_at').first())
    previous = report.signal_details.get('previous_status') if report else None
    if previous in Video.Status.values and previous not in (Video.Status.HELD, Video.Status.BLOCKED):
        return previous
    return Video.Status.PUBLISHED if video.published_at else Video.Status.READY


# ── Fingerprints ──────────────────────────────────────────────────────────────

def ensure_fingerprint(video, refresh=False):
    """Stored fingerprint for `video`, computing it if needed. None if unavailable."""
    from videos.delivery import has_asset

    if not refresh:
        stored = VideoFingerprint.objects.filter(video=video).first()
        if stored:
            return stored
    if not has_asset(video):
        return None
    try:
        hashes = fp.compute(video)
    except fp.FingerprintUnavailable as exc:
        logger.error('Could not fingerprint video %s: %s', video.id, exc)
        return None
    stored, _ = VideoFingerprint.objects.update_or_create(
        video=video,
        defaults={'frame_hashes': hashes, 'duration_seconds': video.duration_seconds,
                  'computed_at': timezone.now()})
    return stored


def find_matches(fingerprint, *, exclude_video_id):
    """[(other_fingerprint, score)] for stored videos that look like the same video."""
    matches = []
    others = VideoFingerprint.objects.exclude(video_id=exclude_video_id).select_related('video')
    for other in others.iterator():
        same, score = fp.is_same_video(
            (fingerprint.frame_hashes, fingerprint.duration_seconds),
            (other.frame_hashes, other.duration_seconds))
        if same:
            matches.append((other, score))
    return matches


# ── Checks ────────────────────────────────────────────────────────────────────

def check_video(video):
    """
    Run every automatic check on `video`. Returns {'checked', 'held', 'signals'}.
    Never raises.
    """
    from videos.models import Video

    result = {'checked': False, 'held': False, 'signals': []}
    try:
        for signal, details in text_checks.check_text(f'{video.title}\n{video.description or ""}'):
            flag(video=video, signal=signal, reason=TEXT_SIGNAL_REASON[signal], details=details)
            result['signals'].append(signal)

        stored = ensure_fingerprint(video)
        if stored is None:
            return result
        result['checked'] = True

        for other, score in find_matches(stored, exclude_video_id=video.id):
            original = other.video
            details = {'matched_video_id': str(original.id), 'similarity': round(score, 2)}
            if original.status == Video.Status.BLOCKED:
                result['held'] = hold_video(video, signal=REUPLOAD_OF_BLOCKED, details=details) \
                    or result['held'] or video.status == Video.Status.HELD
                result['signals'].append(REUPLOAD_OF_BLOCKED)
            elif (original.creator_id != video.creator_id
                  and original.status == Video.Status.PUBLISHED
                  and original.created_at and video.created_at
                  and original.created_at < video.created_at):
                flag(video=video, signal=DUPLICATE_OF_OTHER_CREATOR,
                     reason=ContentReport.Reason.COPYRIGHT,
                     details={**details, 'matched_creator_id': str(original.creator_id)})
                result['signals'].append(DUPLICATE_OF_OTHER_CREATOR)
    except Exception:  # noqa: BLE001 - checks must never break an upload or publish
        logger.exception('Automatic check failed for video %s', video.id)
    return result


def hold_reuploads_of(blocked_video):
    """After a block: hold every other video that is the same video. Returns count."""
    from videos.models import Video

    held = 0
    try:
        stored = ensure_fingerprint(blocked_video)
        if stored is None:
            return 0
        for other, score in find_matches(stored, exclude_video_id=blocked_video.id):
            if other.video.status in (Video.Status.BLOCKED, Video.Status.HELD,
                                      Video.Status.DRAFT):
                continue
            if hold_video(other.video, signal=REUPLOAD_OF_BLOCKED,
                          details={'matched_video_id': str(blocked_video.id),
                                   'similarity': round(score, 2)}):
                held += 1
    except Exception:  # noqa: BLE001
        logger.exception('Re-upload sweep failed for blocked video %s', blocked_video.id)
    return held


def check_comment(comment):
    try:
        for signal, details in text_checks.check_text(comment.content):
            flag(comment=comment, signal=signal, reason=TEXT_SIGNAL_REASON[signal],
                 details=details)
    except Exception:  # noqa: BLE001
        logger.exception('Automatic check failed for comment %s', comment.id)


def screen_before_publish(video):
    """
    Called just before a video goes public. Returns True if it may be
    published now, False if it has been held for review.
    """
    from videos.models import Video
    result = check_video(video)
    return not result['held'] and video.status != Video.Status.HELD
