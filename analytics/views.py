"""
Platform-wide analytics for admins. Read-only aggregates over existing
tables; no schema of its own. Per-creator analytics stay in
creator_channels (channels/me/dashboard, channels/me/performance).
"""
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce, Lower, TruncDay
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from events.models import Event
from moderation.models import ContentReport, ModerationAction
from moderation.permissions import IsAdmin
from playback.models import ViewLog
from subscriptions.models import Subscription
from videos.models import Video

PERIODS = {'1d': 1, '7d': 7, '28d': 28, '90d': 90}


def _period(request, default='28d'):
    """Returns (period_key, start, end, previous_start) or raises ValueError."""
    key = request.query_params.get('period', default)
    if key not in PERIODS:
        raise ValueError(f'Invalid period. Use one of: {", ".join(PERIODS)}.')
    end = timezone.now()
    start = end - timedelta(days=PERIODS[key])
    previous_start = start - timedelta(days=PERIODS[key])
    return key, start, end, previous_start


def _bad_period(exc):
    return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _change(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _view_stats(start, end):
    stats = ViewLog.objects.filter(timestamp__gte=start, timestamp__lt=end).aggregate(
        views=Count('id'),
        completed=Count('id', filter=Q(completed=True)),
        watch_seconds=Coalesce(Sum('watch_duration_seconds'), 0),
        signed_in_viewers=Count('user_id', distinct=True),
        sessions=Count('session_id', distinct=True),
    )
    stats['watch_hours'] = round(stats.pop('watch_seconds') / 3600, 1)
    stats['completion_rate'] = (
        round(stats['completed'] / stats['views'] * 100, 1) if stats['views'] else 0
    )
    return stats


class OverviewView(APIView):
    """
    Headline platform numbers for a period, with change vs the previous one.

    GET /api/v1/analytics/overview/?period=1d|7d|28d|90d
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        try:
            key, start, end, prev_start = _period(request)
        except ValueError as exc:
            return _bad_period(exc)

        users = User.objects.all()
        new_users = users.filter(created_at__gte=start).count()
        prev_new_users = users.filter(created_at__gte=prev_start, created_at__lt=start).count()

        uploads = Video.objects.filter(created_at__gte=start).exclude(
            status=Video.Status.DRAFT).count()
        prev_uploads = Video.objects.filter(
            created_at__gte=prev_start, created_at__lt=start).exclude(
            status=Video.Status.DRAFT).count()

        views = _view_stats(start, end)
        prev_views = _view_stats(prev_start, start)

        new_subs = Subscription.objects.filter(created_at__gte=start).count()

        return Response({
            'period': key,
            'start': start,
            'end': end,
            'users': {
                'total': users.count(),
                'new': new_users,
                'new_change_percent': _change(new_users, prev_new_users),
                'by_role': dict(users.values_list('role').annotate(n=Count('id'))),
                'by_status': dict(users.values_list('status').annotate(n=Count('id'))),
            },
            'videos': {
                'total': Video.objects.count(),
                'uploaded': uploads,
                'uploaded_change_percent': _change(uploads, prev_uploads),
                'by_status': dict(Video.objects.values_list('status').annotate(n=Count('id'))),
            },
            'engagement': {
                **views,
                'views_change_percent': _change(views['views'], prev_views['views']),
                'watch_hours_change_percent': _change(views['watch_hours'],
                                                      prev_views['watch_hours']),
                'new_subscriptions': new_subs,
            },
            'moderation': {
                'open_reports': ContentReport.objects.filter(
                    status=ContentReport.Status.OPEN).count(),
                'reports_filed': ContentReport.objects.filter(created_at__gte=start).count(),
                'actions_taken': ModerationAction.objects.filter(created_at__gte=start).count(),
            },
        })


class DailyActivityView(APIView):
    """
    Day-by-day series for charts.

    GET /api/v1/analytics/daily/?period=7d|28d|90d
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        try:
            key, start, end, _ = _period(request)
        except ValueError as exc:
            return _bad_period(exc)

        def by_day(queryset, field, **aggregates):
            return {
                row['day'].date(): row
                for row in queryset.annotate(day=TruncDay(field))
                .values('day').annotate(**aggregates).order_by('day')
            }

        views = by_day(
            ViewLog.objects.filter(timestamp__gte=start, timestamp__lt=end), 'timestamp',
            views=Count('id'), watch_seconds=Coalesce(Sum('watch_duration_seconds'), 0))
        users = by_day(User.objects.filter(created_at__gte=start), 'created_at',
                       n=Count('id'))
        uploads = by_day(
            Video.objects.filter(created_at__gte=start).exclude(status=Video.Status.DRAFT),
            'created_at', n=Count('id'))

        series = []
        day = start.date()
        while day <= end.date():
            v = views.get(day, {})
            series.append({
                'date': day.isoformat(),
                'views': v.get('views', 0),
                'watch_hours': round(v.get('watch_seconds', 0) / 3600, 2),
                'new_users': users.get(day, {}).get('n', 0),
                'uploads': uploads.get(day, {}).get('n', 0),
            })
            day += timedelta(days=1)

        return Response({'period': key, 'series': series})


class TopVideosView(APIView):
    """
    Most-watched videos in the period, with completion rate.

    GET /api/v1/analytics/top-videos/?period=7d&limit=20
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        try:
            key, start, end, _ = _period(request, default='7d')
        except ValueError as exc:
            return _bad_period(exc)
        try:
            limit = max(1, min(int(request.query_params.get('limit', 20)), 100))
        except ValueError:
            limit = 20

        rows = list(
            ViewLog.objects.filter(timestamp__gte=start, timestamp__lt=end)
            .values('video_id')
            .annotate(views=Count('id'),
                      completed=Count('id', filter=Q(completed=True)),
                      watch_seconds=Coalesce(Sum('watch_duration_seconds'), 0))
            .order_by('-views')[:limit]
        )
        videos = Video.objects.in_bulk([r['video_id'] for r in rows])

        results = []
        for row in rows:
            video = videos.get(row['video_id'])
            if video is None:
                continue
            results.append({
                'video_id': str(video.id),
                'title': video.title,
                'creator_id': str(video.creator_id),
                'status': video.status,
                'views': row['views'],
                'completion_rate': round(row['completed'] / row['views'] * 100, 1),
                'watch_hours': round(row['watch_seconds'] / 3600, 2),
            })
        return Response({'period': key, 'results': results})


class SearchInsightsView(APIView):
    """
    What people search for, and what they search for but do not find.
    Zero-result queries are the clearest signal of missing content.

    GET /api/v1/analytics/search/?period=7d&limit=20
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        try:
            key, start, end, _ = _period(request, default='7d')
        except ValueError as exc:
            return _bad_period(exc)
        try:
            limit = max(1, min(int(request.query_params.get('limit', 20)), 100))
        except ValueError:
            limit = 20

        searches = Event.objects.filter(
            event_type=Event.Type.SEARCH, occurred_at__gte=start, occurred_at__lt=end)

        def top(queryset):
            return [
                {'query': row['q'], 'count': row['n']}
                for row in queryset.values(q=Lower(KeyTextTransform('query', 'payload')))
                .exclude(q=None).annotate(n=Count('id')).order_by('-n', 'q')[:limit]
            ]

        return Response({
            'period': key,
            'total_searches': searches.count(),
            'top_queries': top(searches),
            'zero_result_queries': top(searches.filter(payload__result_count=0)),
        })
