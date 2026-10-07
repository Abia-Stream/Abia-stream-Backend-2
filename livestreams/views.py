import uuid
from datetime import timedelta

from django.db.models import Case, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from abiastream.pagination import StandardPagination
from livestreams import services
from livestreams.models import ChatMessage, LiveStream
from livestreams.serializers import (
    ChatMessageSerializer, CreateLiveStreamSerializer, LiveStreamSerializer,
    OwnerLiveStreamSerializer, UpdateLiveStreamSerializer,
)
from moderation.permissions import is_staff_role

Status = LiveStream.Status

# A list request refreshes at most this many stale streams from Cloudinary.
LIST_REFRESH_LIMIT = 10
CHAT_PAGE = 100


def _serialize(stream, request):
    owner = request.user.is_authenticated and stream.creator_id == request.user.id
    cls = OwnerLiveStreamSerializer if owner else LiveStreamSerializer
    return cls(stream, context={'request': request}).data


def _error(exc, code=status.HTTP_400_BAD_REQUEST):
    return Response({'detail': str(exc)}, status=code)


def _owned_stream(request, livestream_id):
    return get_object_or_404(LiveStream, id=livestream_id, creator=request.user)


class LiveStreamListView(APIView):
    """
    GET  /api/v1/livestreams/?status=live|scheduled|ended
         Default: live now (most viewers first), then upcoming.
    POST /api/v1/livestreams/  — verified creators with a channel.
         Returns the owner view incl. rtmp_url + stream_key for OBS/encoder.
    """

    def get_permissions(self):
        return [IsAuthenticated()] if self.request.method == 'POST' else [AllowAny()]

    def get(self, request):
        wanted = request.query_params.get('status')
        if wanted and wanted not in (Status.LIVE, Status.SCHEDULED, Status.ENDED):
            return _error('status must be live, scheduled or ended.')

        # Cloudinary has no webhooks: freshen the streams most likely to have
        # changed (live ones, and scheduled ones due about now).
        soon = timezone.now() + timedelta(minutes=15)
        stale = LiveStream.objects.filter(
            Q(status=Status.LIVE)
            | Q(status=Status.SCHEDULED, scheduled_start_time__lte=soon)
            | Q(status=Status.SCHEDULED, scheduled_start_time__isnull=True),
        ).order_by('status_checked_at')[:LIST_REFRESH_LIMIT]
        for stream in stale:
            services.refresh_status(stream)

        streams = LiveStream.objects.select_related(
            'creator', 'creator__channel', 'recording_video')
        if wanted:
            streams = streams.filter(status=wanted)
        else:
            streams = streams.filter(status__in=LiveStream.OPEN_STATUSES)

        streams = streams.annotate(live_first=Case(
            When(status=Status.LIVE, then=Value(0)), default=Value(1),
            output_field=IntegerField(),
        ))
        if wanted == Status.ENDED:
            streams = streams.order_by('-actual_end_time')
        else:
            streams = streams.order_by('live_first', '-viewer_count',
                                       'scheduled_start_time', '-created_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(streams, request)
        return paginator.get_paginated_response(
            LiveStreamSerializer(page, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = CreateLiveStreamSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            stream = services.create_livestream(request.user, **serializer.validated_data)
        except services.LiveStreamError as exc:
            refused = services.go_live_refusal(request.user)
            return _error(exc, status.HTTP_403_FORBIDDEN if refused else status.HTTP_400_BAD_REQUEST)
        return Response(OwnerLiveStreamSerializer(stream).data, status=status.HTTP_201_CREATED)


class MyLiveStreamsView(APIView):
    """GET /api/v1/livestreams/me/ — the creator's streams, all statuses."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        streams = LiveStream.objects.filter(creator=request.user).select_related(
            'creator', 'recording_video')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(streams, request)
        return paginator.get_paginated_response(
            OwnerLiveStreamSerializer(page, many=True).data)


class LiveStreamDetailView(APIView):
    """
    GET   /api/v1/livestreams/<id>/  — anyone; poll every ~10s to see it go live.
    PATCH /api/v1/livestreams/<id>/  — owner, before it ends.
    """

    def get_permissions(self):
        return [AllowAny()] if self.request.method == 'GET' else [IsAuthenticated()]

    def get(self, request, livestream_id):
        stream = get_object_or_404(LiveStream, id=livestream_id)
        if stream.status in (Status.CANCELLED, Status.FAILED) and not (
                request.user.is_authenticated and stream.creator_id == request.user.id):
            return _error('Stream not found.', status.HTTP_404_NOT_FOUND)
        stream = services.refresh_status(stream)
        if stream.status == Status.ENDED and stream.creator_id == getattr(request.user, 'id', None):
            services.finalize_recording(stream)
        return Response(_serialize(stream, request))

    def patch(self, request, livestream_id):
        stream = _owned_stream(request, livestream_id)
        serializer = UpdateLiveStreamSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if stream.status not in LiveStream.OPEN_STATUSES:
            # Only the recording choice still matters once it is over.
            if set(data) - {'publish_recording'} or stream.recording_video_id:
                return _error('This stream has ended and can no longer be edited.')
        for field, value in data.items():
            setattr(stream, field, value if value != '' else None)
        stream.save(update_fields=[*data, 'updated_at'])
        return Response(_serialize(stream, request))


class EndLiveStreamView(APIView):
    """POST /api/v1/livestreams/<id>/end/ — owner. Ending a not-yet-live stream cancels it."""
    permission_classes = [IsAuthenticated]

    def post(self, request, livestream_id):
        stream = _owned_stream(request, livestream_id)
        try:
            stream = services.end_stream(stream)
        except services.LiveStreamError as exc:
            return _error(exc)
        return Response(_serialize(stream, request))


class CancelLiveStreamView(APIView):
    """POST /api/v1/livestreams/<id>/cancel/ — owner, before it goes live."""
    permission_classes = [IsAuthenticated]

    def post(self, request, livestream_id):
        stream = _owned_stream(request, livestream_id)
        try:
            stream = services.cancel_stream(stream)
        except services.LiveStreamError as exc:
            return _error(exc)
        return Response(_serialize(stream, request))


class HeartbeatView(APIView):
    """
    POST /api/v1/livestreams/<id>/heartbeat/  {"session_id": "<uuid>"}
    Viewers call this every ~20s while watching. Returns the live viewer count.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'live_heartbeat'

    def post(self, request, livestream_id):
        stream = services.refresh_status(get_object_or_404(LiveStream, id=livestream_id))
        if stream.status != Status.LIVE:
            return Response({'status': stream.status, 'viewer_count': 0})

        try:
            session_id = uuid.UUID(str(request.data.get('session_id')
                                       or request.headers.get('X-Session-Id')))
        except (TypeError, ValueError):
            return _error('session_id (uuid) is required.')

        from playback.views import get_client_ip
        count = services.record_heartbeat(
            stream, session_id=session_id, user=request.user,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT'),
        )
        return Response({'status': stream.status, 'viewer_count': count})


class ChatView(APIView):
    """
    GET  /api/v1/livestreams/<id>/chat/?after=<message_id>
         Oldest-first, up to 100. Poll with the last id you have when not on
         the websocket (ws/livestream/<id>/).
    POST /api/v1/livestreams/<id>/chat/  {"content": "..."}  — signed in.
    """
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'live_chat'

    def get_permissions(self):
        return [IsAuthenticated()] if self.request.method == 'POST' else [AllowAny()]

    def get_throttles(self):
        return super().get_throttles() if self.request.method == 'POST' else []

    def get(self, request, livestream_id):
        stream = get_object_or_404(LiveStream, id=livestream_id)
        messages = ChatMessage.objects.filter(
            livestream=stream, is_deleted=False).select_related('user')
        after = request.query_params.get('after')
        if after:
            anchor = ChatMessage.objects.filter(livestream=stream, id=after).first() \
                if _is_uuid(after) else None
            if anchor is None:
                return _error('Unknown "after" message id.')
            messages = messages.filter(
                Q(created_at__gt=anchor.created_at)
                | Q(created_at=anchor.created_at, id__gt=anchor.id))
            messages = messages.order_by('created_at', 'id')[:CHAT_PAGE]
        else:
            # Latest page, returned oldest-first.
            messages = list(messages.order_by('-created_at', '-id')[:CHAT_PAGE])[::-1]
        return Response({
            'chat_enabled': stream.chat_enabled,
            'messages': ChatMessageSerializer(messages, many=True).data,
        })

    def post(self, request, livestream_id):
        stream = services.refresh_status(get_object_or_404(LiveStream, id=livestream_id))
        try:
            message = services.post_chat_message(stream, request.user, request.data.get('content'))
        except services.LiveStreamError as exc:
            return _error(exc)
        return Response(ChatMessageSerializer(message).data, status=status.HTTP_201_CREATED)


class ChatMessageDetailView(APIView):
    """
    DELETE /api/v1/livestreams/chat/<message_id>/
    The author or the stream owner. Moderators/admins go through the audited
    moderation action (remove_chat_message), which this does for them.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, message_id):
        message = get_object_or_404(
            ChatMessage.objects.select_related('livestream'), id=message_id, is_deleted=False)
        user = request.user
        if message.user_id == user.id or message.livestream.creator_id == user.id:
            services.hide_chat_message(message)
        elif is_staff_role(user):
            from moderation.services import apply_action
            apply_action(user, 'remove_chat_message', chat_message=message)
        else:
            return _error('You cannot delete this message.', status.HTTP_403_FORBIDDEN)
        return Response({'detail': 'Message deleted.'})


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False
