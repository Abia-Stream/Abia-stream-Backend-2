from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.db.models import F
from abiastream.pagination import StandardPagination
from interactions.models import Interaction
from interactions.serializers import InteractionSerializer, CreateInteractionSerializer
from videos.models import Video


def update_video_counter(video, interaction_type, increment=True):
    """Update the relevant counter on the video when interaction changes."""
    amount = 1 if increment else -1

    if interaction_type == Interaction.InteractionType.LIKE:
        Video.objects.filter(id=video.id).update(likes_count=F('likes_count') + amount)
    elif interaction_type == Interaction.InteractionType.SAVE:
        Video.objects.filter(id=video.id).update(saves_count=F('saves_count') + amount)


def sync_report_to_queue(user, video, interaction_type, added):
    """
    The one-click `report` interaction predates the moderation app. Mirror it
    into the moderation queue (reason 'other') so those reports get reviewed.
    Best-effort: the interaction itself must succeed regardless.
    """
    if interaction_type != Interaction.InteractionType.REPORT:
        return
    import logging
    from moderation.services import file_report, withdraw_video_report
    try:
        if added:
            file_report(user, video=video, reason='other')
        else:
            withdraw_video_report(user, video)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception('Could not mirror report to moderation queue')


class InteractWithVideoView(APIView):
    """
    Add or remove an interaction on a video.
    If interaction already exists → remove it (toggle off).
    If interaction doesn't exist → create it (toggle on).

    POST /api/interactions/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateInteractionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        video_id = serializer.validated_data['video_id']
        interaction_type = serializer.validated_data['interaction_type']

        video = get_object_or_404(Video, id=video_id)

        # Block reporting own video
        if interaction_type == Interaction.InteractionType.REPORT:
            if video.creator == request.user:
                return Response(
                    {'detail': 'You cannot report your own video.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Check if interaction already exists
        existing = Interaction.objects.filter(
            user=request.user,
            video=video,
            interaction_type=interaction_type
        ).first()

        if existing:
            # Toggle off — remove interaction
            existing.delete()
            update_video_counter(video, interaction_type, increment=False)
            sync_report_to_queue(request.user, video, interaction_type, added=False)
            return Response(
                {
                    'detail': f'{interaction_type.capitalize()} removed.',
                    'action': 'removed',
                    'interaction_type': interaction_type,
                },
                status=status.HTTP_200_OK
            )
        else:
            # Toggle on — create interaction
            # Special rule: like and dislike are mutually exclusive
            if interaction_type == Interaction.InteractionType.LIKE:
                dislike = Interaction.objects.filter(
                    user=request.user,
                    video=video,
                    interaction_type=Interaction.InteractionType.DISLIKE
                ).first()
                if dislike:
                    dislike.delete()

            elif interaction_type == Interaction.InteractionType.DISLIKE:
                like = Interaction.objects.filter(
                    user=request.user,
                    video=video,
                    interaction_type=Interaction.InteractionType.LIKE
                ).first()
                if like:
                    like.delete()
                    # Decrement likes_count since like was removed
                    update_video_counter(
                        video,
                        Interaction.InteractionType.LIKE,
                        increment=False
                    )

            interaction = Interaction.objects.create(
                user=request.user,
                video=video,
                interaction_type=interaction_type
            )
            update_video_counter(video, interaction_type, increment=True)
            sync_report_to_queue(request.user, video, interaction_type, added=True)

            return Response(
                {
                    'detail': f'{interaction_type.capitalize()} added.',
                    'action': 'added',
                    'interaction_type': interaction_type,
                    'id': str(interaction.id),
                },
                status=status.HTTP_201_CREATED
            )


class VideoInteractionStatusView(APIView):
    """
    Check which interactions the current user has on a video.

    GET /api/interactions/video/<video_id>/status/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, video_id):
        video = get_object_or_404(Video, id=video_id)

        user_interactions = Interaction.objects.filter(
            user=request.user,
            video=video
        ).values_list('interaction_type', flat=True)

        return Response({
            'video_id': str(video_id),
            'liked': 'like' in user_interactions,
            'disliked': 'dislike' in user_interactions,
            'saved': 'save' in user_interactions,
            'favourited': 'favourite' in user_interactions,
            'reported': 'report' in user_interactions,
            'likes_count': video.likes_count or 0,
            'saves_count': video.saves_count or 0,
        })


class UserLikedVideosView(APIView):
    """
    Get all videos the user has liked.

    GET /api/interactions/liked/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        interactions = Interaction.objects.filter(
            user=request.user,
            interaction_type=Interaction.InteractionType.LIKE
        ).select_related('video').order_by('-created_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(interactions, request)
        serializer = InteractionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class UserSavedVideosView(APIView):
    """
    Get all videos the user has saved.

    GET /api/interactions/saved/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        interactions = Interaction.objects.filter(
            user=request.user,
            interaction_type=Interaction.InteractionType.SAVE
        ).select_related('video').order_by('-created_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(interactions, request)
        serializer = InteractionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class UserFavouriteVideosView(APIView):
    """
    Get all videos the user has favourited.

    GET /api/interactions/favourites/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        interactions = Interaction.objects.filter(
            user=request.user,
            interaction_type=Interaction.InteractionType.FAVOURITE
        ).select_related('video').order_by('-created_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(interactions, request)
        serializer = InteractionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class VideoInteractionsCountView(APIView):
    """
    Get interaction counts for a video (public).

    GET /api/interactions/video/<video_id>/counts/
    """
    permission_classes = [AllowAny]

    def get(self, request, video_id):
        video = get_object_or_404(Video, id=video_id)

        return Response({
            'video_id': str(video_id),
            'likes_count': video.likes_count or 0,
            'saves_count': video.saves_count or 0,
            'views_count': video.views_count or 0,
            'shares_count': video.shares_count or 0,
        })

SHARE_DESTINATIONS = ('whatsapp', 'facebook', 'x', 'telegram', 'instagram', 'tiktok',
                      'copy_link', 'native', 'other')
# The same session sharing the same video again within this window isn't
# counted again (the share is still logged).
SHARE_DEDUPE_HOURS = 24


class ShareVideoView(APIView):
    """
    Record that a viewer shared a video (the frontend opens the share sheet /
    copies the link itself; this only counts it).

    POST /api/v1/videos/<video_id>/share/   {"destination": "whatsapp"}
    Auth optional; send X-Session-Id so repeat shares aren't double counted.

    Returns {"counted": true|false, "shares_count": n}.
    """
    permission_classes = [AllowAny]
    throttle_scope = 'shares'

    def get_throttles(self):
        from rest_framework.throttling import ScopedRateThrottle
        return [ScopedRateThrottle()]

    def post(self, request, video_id):
        from datetime import timedelta
        from django.utils import timezone
        from events.models import Event
        from events.utils import resolve_session_id
        from videos.access import is_video_accessible

        video = get_object_or_404(Video, id=video_id, status=Video.Status.PUBLISHED)
        if not is_video_accessible(video, request.user):
            return Response({'detail': 'Video not found.'}, status=status.HTTP_404_NOT_FOUND)

        destination = request.data.get('destination') or 'other'
        if destination not in SHARE_DESTINATIONS:
            return Response({'detail': f'destination must be one of: {", ".join(SHARE_DESTINATIONS)}.'},
                            status=status.HTTP_400_BAD_REQUEST)

        session_id = resolve_session_id(request)
        user = request.user if request.user.is_authenticated else None
        since = timezone.now() - timedelta(hours=SHARE_DEDUPE_HOURS)
        earlier = Event.objects.filter(event_type=Event.Type.SHARE, video=video, occurred_at__gte=since)
        earlier = earlier.filter(user=user) if user else earlier.filter(session_id=session_id)
        counted = not earlier.exists()

        Event.objects.create(user=user, session_id=session_id, video=video,
                             event_type=Event.Type.SHARE,
                             payload={'destination': destination, 'counted': counted})
        if counted:
            Video.objects.filter(id=video.id).update(shares_count=F('shares_count') + 1)
        video.refresh_from_db(fields=['shares_count'])
        return Response({'counted': counted, 'shares_count': video.shares_count or 0})
