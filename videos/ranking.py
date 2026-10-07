from datetime import timedelta

from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from playback.models import ViewLog

# A completed view counts this many times a raw view when ranking trending.
TRENDING_COMPLETION_WEIGHT = 3
TRENDING_LIMIT = 50


def trending_video_ids(days=7, limit=TRENDING_LIMIT):
    """
    Video ids ranked by completion-weighted views over the last `days`.

    Raw views reward clickbait; a view that was actually watched through is
    the stronger signal. Not filtered by status/visibility — callers do that
    when loading the videos.
    """
    since = timezone.now() - timedelta(days=days)

    recent = (
        ViewLog.objects.filter(timestamp__gte=since)
        .values('video_id')
        .annotate(
            views=Count('id'),
            completions=Count('id', filter=Q(completed=True)),
            watch_seconds=Coalesce(Sum('watch_duration_seconds'), Value(0)),
        )
    )

    ranked = sorted(
        recent,
        key=lambda r: r['completions'] * TRENDING_COMPLETION_WEIGHT + r['views'],
        reverse=True,
    )[:limit]

    return [r['video_id'] for r in ranked]
