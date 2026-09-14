import uuid
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db.models import F
from playback.models import WatchHistory, ViewLog
from playback.serializers import (
    WatchHistorySerializer,
    UpdateProgressSerializer,
    RecordViewSerializer,
)
from videos.models import Video
from abiastream.pagination import StandardPagination
from profiles.models import Profile


def get_client_ip(request):
    """Extract real IP from request headers."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def get_device_type(user_agent):
    """Simple device detection from user agent string."""
    if not user_agent:
        return 'unknown'
    ua = user_agent.lower()
    if 'mobile' in ua or 'android' in ua or 'iphone' in ua:
        return 'mobile'
    if 'tablet' in ua or 'ipad' in ua:
        return 'tablet'
    return 'desktop'


# ── Watch History ─────────────────────────────────────────────────────────────

class WatchHistoryListView(APIView):
    """
    Get the authenticated user's watch history.

    GET /api/playback/history/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        history = WatchHistory.objects.filter(
            user=request.user
        ).select_related('video').order_by('-last_watched_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(history, request)
        serializer = WatchHistorySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)



class UpdateProgressView(APIView):
    """
    Update or create watch progress for a video.
    Called periodically while the user is watching (every 10-30 seconds).

    POST /api/playback/progress/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UpdateProgressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        video_id = serializer.validated_data['video_id']
        progress = serializer.validated_data['watch_progress_seconds']
        completed = serializer.validated_data['completed']
        device_type = serializer.validated_data.get('device_type', '')
        session_id = serializer.validated_data.get('session_id')

        video = get_object_or_404(Video, id=video_id)

        # Auto-mark completed if progress >= 90% of duration
        if video.duration_seconds and not completed:
            if progress >= video.duration_seconds * 0.9:
                completed = True

        # Update or create watch history entry
        watch_entry, created = WatchHistory.objects.update_or_create(
            user=request.user,
            video=video,
            defaults={
                'watch_progress_seconds': progress,
                'completed': completed,
                'last_watched_at': timezone.now(),
                'device_type': device_type or get_device_type(
                    request.META.get('HTTP_USER_AGENT', '')
                ),
                'session_id': session_id,
            }
        )

        return Response(
            WatchHistorySerializer(watch_entry).data,
            status=status.HTTP_200_OK
        )


class ClearWatchHistoryView(APIView):
    """
    Clear the authenticated user's entire watch history.

    DELETE /api/playback/history/
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        deleted_count, _ = WatchHistory.objects.filter(user=request.user).delete()
        return Response(
            {'detail': f'Watch history cleared. {deleted_count} entries removed.'},
            status=status.HTTP_200_OK
        )


class RemoveFromHistoryView(APIView):
    """
    Remove a single video from watch history.

    DELETE /api/playback/history/<video_id>/
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, video_id):
        entry = get_object_or_404(
            WatchHistory, user=request.user, video_id=video_id
        )
        entry.delete()
        return Response(
            {'detail': 'Removed from watch history.'},
            status=status.HTTP_200_OK
        )


# ── View Logging ──────────────────────────────────────────────────────────────

class RecordViewView(APIView):
    """
    Record a video view. Works for both authenticated and anonymous users.
    Called when a user starts watching or finishes watching a video.

    POST /api/playback/view/
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RecordViewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        video_id = serializer.validated_data['video_id']
        watch_duration = serializer.validated_data['watch_duration_seconds']
        completed = serializer.validated_data['completed']
        device_type = serializer.validated_data.get('device_type', '')
        referrer = serializer.validated_data.get('referrer', '')
        session_id = serializer.validated_data.get('session_id') or uuid.uuid4()

        video = get_object_or_404(Video, id=video_id)

        ip_address = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        detected_device = device_type or get_device_type(user_agent)

        # Log the view
        ViewLog.objects.create(
            video=video,
            user=request.user if request.user.is_authenticated else None,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            referrer=referrer,
            watch_duration_seconds=watch_duration,
            completed=completed,
            device_type=detected_device,
            timestamp=timezone.now(),
        )

        # Update creator's total views on their profile
        Profile.objects.filter(user=video.creator).update(
            total_views=F('total_views') + 1
        )

        # Increment video view count
        Video.objects.filter(id=video.id).update(
            views_count=F('views_count') + 1
        )

        return Response(
            {'detail': 'View recorded.'},
            status=status.HTTP_200_OK
        )


# ── Continue Watching ─────────────────────────────────────────────────────────

class ContinueWatchingView(APIView):
    """
    Get videos the user has started but not completed.

    GET /api/playback/continue-watching/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        history = WatchHistory.objects.filter(
            user=request.user,
            completed=False,
            watch_progress_seconds__gt=0,
        ).select_related('video').order_by('-last_watched_at')[:20]

        serializer = WatchHistorySerializer(history, many=True)
        return Response(serializer.data)