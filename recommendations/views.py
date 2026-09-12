from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404

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
            ).select_related('category', 'creator').prefetch_related('tags')
        }

        ordered = [videos[vid] for vid in related_ids if vid in videos]
        return Response(VideoSerializer(ordered, many=True).data)
