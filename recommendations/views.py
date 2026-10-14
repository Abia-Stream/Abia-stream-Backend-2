from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404

from abiastream.pagination import StandardPagination
from events.models import Event
from events.utils import log_event
from recommendations.feed import build_feed, rank_feed
from recommendations.models import RelatedVideo
from videos.models import Video
from videos.serializers import VideoSerializer


class RelatedVideosView(APIView):
    """
    "Users who watched this also watched..."

    GET /api/v1/videos/<video_id>/related/

    Reads precomputed rows only. Returns an empty list rather than a fallback
    when nothing has been computed yet — a silent popularity fallback would
    make it impossible to tell whether collaborative filtering is actually
    working once it goes live.
    """
    permission_classes = [AllowAny]

    def get(self, request, video_id):
        video = get_object_or_404(Video, id=video_id)

        related_ids = list(
            RelatedVideo.objects
            .filter(video=video)
            .order_by('-score')
            .values_list('related_id', flat=True)[:20]
        )

        if not related_ids:
            return Response([])

        videos = {
            v.id: v
            for v in Video.objects.filter(
                id__in=related_ids,
                status=Video.Status.PUBLISHED,
                visibility=Video.Visibility.PUBLIC,
            ).select_related('category', 'creator', 'creator__channel').prefetch_related('tags')
        }

        ordered = [videos[vid] for vid in related_ids if vid in videos]
        return Response(VideoSerializer(ordered, many=True).data)


class ForYouFeedView(APIView):
    """
    Personalized home feed. Works signed out too (trending + fresh only).

    GET /api/v1/videos/feed/?page=1&page_size=8

    Each item is a normal video object plus `feed_reason`, one of
    related | subscription | category | trending | fresh — useful for UI copy
    ("Because you watched…") and for attributing clicks in events.

    Each page served is logged as a `feed_served` event with the items'
    ranking features: the training data for recommendations/ranker.py.
    Viewers in the `feed_ranker` experiment's treatment arm get the trained
    ranker's order once one is active.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from experiments.utils import get_variant
        variant = get_variant(request, 'feed_ranker')
        ranked, model_id = rank_feed(request.user, use_ranker=(variant == 'treatment'))

        paginator = StandardPagination()
        page = paginator.paginate_queryset(ranked, request)
        videos = [video for video, _, _ in page]
        data = VideoSerializer(videos, many=True, context={'request': request}).data
        for item, (_, reason, _) in zip(data, page):
            item['feed_reason'] = reason

        offset = (paginator.page.number - 1) * paginator.get_page_size(request)
        log_event(request, Event.Type.FEED_SERVED, payload={
            'variant': variant,
            'model_id': model_id,
            'page': paginator.page.number,
            'items': [
                {'video_id': str(video.id), 'position': offset + i, 'reason': reason,
                 'features': {k: round(v, 5) for k, v in features.items()}}
                for i, (video, reason, features) in enumerate(page)
            ],
        })
        return paginator.get_paginated_response(data)


class UpNextView(APIView):
    """
    What to watch after this video.

    GET /api/v1/videos/<video_id>/up-next/?limit=10

    Each item has `up_next_reason`: watched_next (what viewers actually
    watched next, recommendations.VideoTransition) > related (co-watched) >
    same_creator > for_you (feed fallback). Excludes the current video and,
    when signed in, videos the viewer already finished.
    """
    permission_classes = [AllowAny]

    def get(self, request, video_id):
        from recommendations.models import VideoTransition
        from playback.models import WatchHistory

        video = get_object_or_404(Video, id=video_id)
        try:
            limit = max(1, min(int(request.query_params.get('limit', 10)), 20))
        except ValueError:
            limit = 10

        excluded = {video.id}
        if request.user.is_authenticated:
            excluded |= set(WatchHistory.objects.filter(
                user=request.user, completed=True).values_list('video_id', flat=True))

        ordered = []  # (video_id, reason)

        def add(ids, reason):
            for vid in ids:
                if vid not in excluded and vid not in {v for v, _ in ordered}:
                    ordered.append((vid, reason))

        add(VideoTransition.objects.filter(video=video).order_by('-score')
            .values_list('next_video_id', flat=True)[:limit * 2], 'watched_next')
        add(RelatedVideo.objects.filter(video=video).order_by('-score')
            .values_list('related_id', flat=True)[:limit * 2], 'related')
        add(Video.objects.filter(creator_id=video.creator_id, status=Video.Status.PUBLISHED,
                                 visibility=Video.Visibility.PUBLIC)
            .order_by('-published_at').values_list('id', flat=True)[:limit], 'same_creator')
        if len(ordered) < limit:
            add([v.id for v, _ in build_feed(request.user)[:limit * 2]], 'for_you')

        playable = {
            v.id: v for v in Video.objects.filter(
                id__in=[vid for vid, _ in ordered], status=Video.Status.PUBLISHED,
                visibility=Video.Visibility.PUBLIC,
            ).select_related('category', 'creator', 'creator__channel').prefetch_related('tags')
        }
        final = [(playable[vid], reason) for vid, reason in ordered if vid in playable][:limit]
        data = VideoSerializer([v for v, _ in final], many=True,
                               context={'request': request}).data
        for item, (_, reason) in zip(data, final):
            item['up_next_reason'] = reason
        return Response(data)
