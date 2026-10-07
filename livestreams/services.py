"""
Livestream lifecycle.

    scheduled --(encoder connects)--> live --(encoder gone / end)--> ended
        \--(cancel before going live)--> cancelled

Cloudinary does not notify us of state changes, so refresh_status() asks it,
at most every STATUS_CHECK_SECONDS per stream. It is called whenever a stream
is read (detail, heartbeat, list) and by the `sync_livestreams` command /
Celery beat task, so state stays current with or without a worker.

Every Cloudinary failure is logged and leaves our state as it was: a viewer
loading a page must never get a 500 because Cloudinary hiccupped.
"""
import logging
from datetime import timedelta
from uuid import uuid4

import cloudinary.api
import cloudinary.exceptions
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models.functions import Greatest
from django.db.models import Value
from django.utils import timezone

from livestreams import cloudinary_live as live
from livestreams.models import ChatMessage, LiveStream, StreamViewer
from livestreams.realtime import broadcast

logger = logging.getLogger(__name__)

Status = LiveStream.Status

STATUS_CHECK_SECONDS = 10
VIEWER_ACTIVE_SECONDS = 60
MAX_OPEN_STREAMS_PER_CREATOR = 5
# Give Cloudinary time to finish writing the archive before deleting the
# stream (which permanently invalidates its key).
DELETE_STREAM_AFTER_END = timedelta(minutes=10)
ABANDON_SCHEDULED_AFTER = timedelta(hours=24)
STOP_LOOKING_FOR_RECORDING_AFTER = timedelta(hours=48)


class LiveStreamError(Exception):
    """A rejected request; the message is safe to show the caller."""


# ── Who may stream ────────────────────────────────────────────────────────────

def go_live_refusal(user):
    """None if `user` may create streams, else the reason."""
    from accounts.models import User
    from creator_channels.models import CreatorChannel

    if user.verification_status != User.VerificationStatus.APPROVED:
        return 'Only verified creators can go live. Complete identity verification first.'
    if not CreatorChannel.objects.filter(user=user).exists():
        return 'You need a channel to go live.'
    return None


# ── Create / cancel / end ─────────────────────────────────────────────────────

def create_livestream(user, *, title, description=None, scheduled_start_time=None,
                      chat_enabled=True, save_recording=True, publish_recording=False,
                      thumbnail_url=None):
    refusal = go_live_refusal(user)
    if refusal:
        raise LiveStreamError(refusal)
    open_count = LiveStream.objects.filter(
        creator=user, status__in=LiveStream.OPEN_STATUSES).count()
    if open_count >= MAX_OPEN_STREAMS_PER_CREATOR:
        raise LiveStreamError(
            f'You can have at most {MAX_OPEN_STREAMS_PER_CREATOR} scheduled or live streams.')

    stream_id = uuid4()
    try:
        data = live.create_stream(
            name=f'abiastream-{stream_id}',
            idle_timeout_sec=settings.LIVESTREAM_IDLE_TIMEOUT_SECONDS,
            max_runtime_sec=settings.LIVESTREAM_MAX_RUNTIME_SECONDS,
        )
    except live.LiveStreamingError as exc:
        logger.error('Could not create Cloudinary live stream: %s', exc)
        raise LiveStreamError('Live streaming is temporarily unavailable. Try again shortly.')

    cloud_id = data['id']
    try:
        hls = live.output_of_type(data, 'hls')
        archive = live.output_of_type(data, 'archive')
        if archive and not save_recording:
            # Cloudinary adds an archive by default; drop it so nothing is stored.
            live.delete_output(cloud_id, archive['id'])
            archive = None
        return LiveStream.objects.create(
            id=stream_id,
            creator=user,
            title=title,
            description=description or None,
            stream_key=data['input']['stream_key'],
            rtmp_url=data['input']['uri'],
            hls_url=hls['uri'] if hls else None,
            thumbnail_url=thumbnail_url or None,
            cloudinary_stream_id=cloud_id,
            cloudinary_archive_public_id=archive['public_id'] if archive else None,
            scheduled_start_time=scheduled_start_time,
            chat_enabled=chat_enabled,
            save_recording=bool(archive),
            publish_recording=publish_recording,
            status_checked_at=timezone.now(),
        )
    except Exception:
        # Never leave a stream on Cloudinary that we have no row for.
        _delete_cloud_stream_quietly(cloud_id)
        raise


def cancel_stream(stream):
    stream = refresh_status(stream, force=True)
    if stream.status != Status.SCHEDULED:
        raise LiveStreamError('Only a stream that has not started can be cancelled.')
    updated = LiveStream.objects.filter(id=stream.id, status=Status.SCHEDULED).update(
        status=Status.CANCELLED, updated_at=timezone.now())
    if updated:
        _delete_cloud_stream_quietly(stream.cloudinary_stream_id)
        LiveStream.objects.filter(id=stream.id).update(cloudinary_stream_id=None)
    stream.refresh_from_db()
    broadcast(stream.id, 'status_changed', status=stream.status)
    return stream


def end_stream(stream, *, by_moderator=False):
    """End a live stream now (owner or moderator). Ending a scheduled one cancels it."""
    stream = refresh_status(stream, force=True)
    if stream.status == Status.SCHEDULED:
        return cancel_stream(stream)
    if stream.status != Status.LIVE:
        raise LiveStreamError('This stream is not live.')

    try:
        live.idle_stream(stream.cloudinary_stream_id)
    except live.LiveStreamingError as exc:
        # Still mark it ended here; the delete after the archive settles cuts
        # the encoder off for good.
        logger.error('Could not idle Cloudinary stream %s: %s', stream.cloudinary_stream_id, exc)

    extra = {'publish_recording': False} if by_moderator else {}
    _mark_ended(stream, **extra)
    stream.refresh_from_db()
    return stream


def _mark_ended(stream, **extra):
    now = timezone.now()
    updated = LiveStream.objects.filter(id=stream.id, status=Status.LIVE).update(
        status=Status.ENDED, actual_end_time=now, viewer_count=0,
        status_checked_at=now, updated_at=now, **extra)
    if updated:
        broadcast(stream.id, 'status_changed', status=Status.ENDED)
        if not stream.save_recording:
            _delete_cloud_stream_quietly(stream.cloudinary_stream_id)
            LiveStream.objects.filter(id=stream.id).update(cloudinary_stream_id=None)
    return updated


# ── Status sync ───────────────────────────────────────────────────────────────

def refresh_status(stream, force=False):
    """Bring `stream.status` in line with Cloudinary. Never raises."""
    if stream.status not in LiveStream.OPEN_STATUSES or not stream.cloudinary_stream_id:
        return stream
    now = timezone.now()
    if (not force and stream.status_checked_at
            and now - stream.status_checked_at < timedelta(seconds=STATUS_CHECK_SECONDS)):
        return stream

    try:
        data = live.get_stream(stream.cloudinary_stream_id)
    except live.LiveStreamNotFound:
        logger.error('Cloudinary stream %s for livestream %s no longer exists',
                     stream.cloudinary_stream_id, stream.id)
        LiveStream.objects.filter(id=stream.id, status__in=LiveStream.OPEN_STATUSES).update(
            status=Status.FAILED, status_checked_at=now, updated_at=now)
        stream.refresh_from_db()
        broadcast(stream.id, 'status_changed', status=stream.status)
        return stream
    except live.LiveStreamingError as exc:
        logger.error('Could not check Cloudinary stream %s: %s', stream.cloudinary_stream_id, exc)
        LiveStream.objects.filter(id=stream.id).update(status_checked_at=now)
        stream.status_checked_at = now
        return stream

    if data.get('status') == 'active' and stream.status == Status.SCHEDULED:
        went_live = LiveStream.objects.filter(id=stream.id, status=Status.SCHEDULED).update(
            status=Status.LIVE, actual_start_time=now, status_checked_at=now, updated_at=now)
        if went_live:
            broadcast(stream.id, 'status_changed', status=Status.LIVE)
            _notify_subscribers(stream)
    elif data.get('status') != 'active' and stream.status == Status.LIVE:
        # Cloudinary keeps a dropped stream 'active' for idle_timeout_sec, so
        # 'idle' here means the broadcast is really over.
        _mark_ended(stream)
    else:
        LiveStream.objects.filter(id=stream.id).update(status_checked_at=now)

    stream.refresh_from_db()
    return stream


def _notify_subscribers(stream):
    from notifications.models import Notification
    from subscriptions.models import Subscription

    try:
        subscriber_ids = list(Subscription.objects.filter(
            channel__user_id=stream.creator_id).values_list('subscriber_id', flat=True))
        Notification.objects.bulk_create([
            Notification(
                user_id=user_id,
                notification_type='livestream_started',
                title='Live now',
                message=f'{stream.title} is live.',
                data={'livestream_id': str(stream.id)},
                is_read=False, is_archived=False,
            )
            for user_id in subscriber_ids
        ])
    except Exception:  # noqa: BLE001 - notifications must not affect the stream
        logger.exception('Could not notify subscribers for livestream %s', stream.id)


# ── Recording ─────────────────────────────────────────────────────────────────

def finalize_recording(stream):
    """
    Once Cloudinary has written the archive, turn it into a Video on the
    creator's channel. Returns the Video, or None if not ready / not wanted.
    Safe to call repeatedly.
    """
    from videos.cloudinary_service import generate_thumbnail_url
    from videos.models import Video

    if (stream.status != Status.ENDED or not stream.save_recording
            or stream.recording_video_id or not stream.cloudinary_archive_public_id):
        return None

    try:
        asset = cloudinary.api.resource(stream.cloudinary_archive_public_id,
                                        resource_type='video')
    except cloudinary.exceptions.NotFound:
        return None  # not written yet
    except Exception as exc:  # noqa: BLE001
        logger.error('Could not look up recording for livestream %s: %s', stream.id, exc)
        return None

    with transaction.atomic():
        locked = LiveStream.objects.select_for_update().get(id=stream.id)
        if locked.recording_video_id:
            return locked.recording_video

        publish = locked.publish_recording
        video = Video.objects.create(
            creator_id=locked.creator_id,
            title=locked.title,
            description=locked.description,
            cloudinary_public_id=asset['public_id'],
            cloudinary_url=asset['secure_url'],
            cloudinary_thumbnail_url=locked.thumbnail_url or generate_thumbnail_url(asset['public_id']),
            cloudinary_resource_type='video',
            cloudinary_version=str(asset.get('version') or ''),
            duration_seconds=int(asset.get('duration') or 0) or None,
            width=asset.get('width'),
            height=asset.get('height'),
            format=asset.get('format'),
            file_size=asset.get('bytes'),
            status=Video.Status.PUBLISHED if publish else Video.Status.READY,
            visibility=Video.Visibility.PUBLIC,
            published_at=timezone.now() if publish else None,
        )
        locked.recording_video = video
        locked.save(update_fields=['recording_video', 'updated_at'])

    stream.recording_video = video
    # Same automatic checks as any upload; a held recording stays hidden.
    from moderation.auto import check_video
    check_video(video)
    broadcast(stream.id, 'recording_ready', video_id=str(video.id))
    return video


# ── Viewers ───────────────────────────────────────────────────────────────────

def record_heartbeat(stream, *, session_id, user=None, ip_address=None, user_agent=None):
    """Mark this viewer session as watching. Returns the current viewer count."""
    now = timezone.now()
    signed_in = bool(user and user.is_authenticated)
    defaults = {
        'user': user if signed_in else None,
        'is_anonymous': not signed_in,
        'joined_at': now,
        'left_at': now,
        'ip_address': ip_address,
        'user_agent': (user_agent or '')[:1000] or None,
    }
    try:
        with transaction.atomic():
            viewer, created = StreamViewer.objects.get_or_create(
                livestream=stream, session_id=session_id, defaults=defaults)
    except IntegrityError:
        viewer, created = StreamViewer.objects.get(livestream=stream, session_id=session_id), False

    if not created:
        StreamViewer.objects.filter(id=viewer.id).update(
            left_at=now,
            watch_duration_seconds=int((now - viewer.joined_at).total_seconds()),
        )

    count = StreamViewer.objects.filter(
        livestream=stream, left_at__gte=now - timedelta(seconds=VIEWER_ACTIVE_SECONDS),
    ).count()
    LiveStream.objects.filter(id=stream.id).update(
        viewer_count=count,
        max_concurrent_viewers=Greatest('max_concurrent_viewers', Value(count)),
    )
    return count


# ── Chat ──────────────────────────────────────────────────────────────────────

def post_chat_message(stream, user, content):
    content = (content or '').strip()
    if not stream.chat_enabled:
        raise LiveStreamError('Chat is turned off for this stream.')
    if stream.status not in LiveStream.OPEN_STATUSES:
        raise LiveStreamError('Chat is closed: this stream is not live.')
    if not 1 <= len(content) <= 500:
        raise LiveStreamError('Message must be 1–500 characters.')
    from moderation.text_checks import allowed_in_chat
    if not allowed_in_chat(content):
        raise LiveStreamError("Links, phone numbers and blocked words aren't allowed in chat.")
    message = ChatMessage.objects.create(livestream=stream, user=user, content=content)
    from livestreams.serializers import ChatMessageSerializer
    broadcast(stream.id, 'chat_message', message=ChatMessageSerializer(message).data)
    return message


def hide_chat_message(message):
    if message.is_deleted:
        return False
    ChatMessage.objects.filter(id=message.id).update(is_deleted=True)
    message.is_deleted = True
    broadcast(message.livestream_id, 'chat_message_deleted', message_id=str(message.id))
    return True


# ── Housekeeping (sync_livestreams command / Celery beat) ─────────────────────

def _delete_cloud_stream_quietly(cloud_id):
    if not cloud_id:
        return
    try:
        live.delete_stream(cloud_id)
    except live.LiveStreamNotFound:
        pass
    except live.LiveStreamingError as exc:
        logger.error('Could not delete Cloudinary stream %s: %s', cloud_id, exc)


def sync_all():
    """One housekeeping pass. Returns a dict of counts for logging."""
    now = timezone.now()
    counts = {'refreshed': 0, 'abandoned': 0, 'recordings': 0, 'cloud_deleted': 0}

    for stream in LiveStream.objects.filter(status__in=LiveStream.OPEN_STATUSES):
        if (stream.status == Status.SCHEDULED and stream.scheduled_start_time
                and now - stream.scheduled_start_time > ABANDON_SCHEDULED_AFTER):
            refreshed = refresh_status(stream, force=True)
            if refreshed.status == Status.SCHEDULED:
                cancel_stream(refreshed)
                counts['abandoned'] += 1
            continue
        refresh_status(stream, force=True)
        counts['refreshed'] += 1

    for stream in LiveStream.objects.filter(
            status=Status.ENDED, save_recording=True, recording_video__isnull=True,
            actual_end_time__gte=now - STOP_LOOKING_FOR_RECORDING_AFTER):
        if finalize_recording(stream):
            counts['recordings'] += 1

    # Delete finished Cloudinary streams so their keys stop working.
    for stream in LiveStream.objects.filter(
            status=Status.ENDED, cloudinary_stream_id__isnull=False,
            actual_end_time__lte=now - DELETE_STREAM_AFTER_END):
        recording_settled = (not stream.save_recording or stream.recording_video_id
                             or now - stream.actual_end_time > STOP_LOOKING_FOR_RECORDING_AFTER)
        if recording_settled:
            _delete_cloud_stream_quietly(stream.cloudinary_stream_id)
            LiveStream.objects.filter(id=stream.id).update(cloudinary_stream_id=None)
            counts['cloud_deleted'] += 1

    return counts
