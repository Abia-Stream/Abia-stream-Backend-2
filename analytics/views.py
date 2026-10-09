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


def _view_stats(start, end, include_end=False):
    # The current period ends at "now" and must include it: on a coarse clock a
    # row written just before the request can carry exactly that timestamp.
    # The previous period ends where the current one starts, so it excludes it.
    upper = {'timestamp__lte' if include_end else 'timestamp__lt': end}
    stats = ViewLog.objects.filter(timestamp__gte=start, **upper).aggregate(
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

        views = _view_stats(start, end, include_end=True)
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
            ViewLog.objects.filter(timestamp__gte=start, timestamp__lte=end), 'timestamp',
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
            ViewLog.objects.filter(timestamp__gte=start, timestamp__lte=end)
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
            event_type=Event.Type.SEARCH, occurred_at__gte=start, occurred_at__lte=end)

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


def _two_proportion_test(success_a, total_a, success_b, total_b):
    """Two-sided z-test for a difference in rates. Returns (z, p) or (None, None)."""
    import math
    if not total_a or not total_b:
        return None, None
    pooled = (success_a + success_b) / (total_a + total_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / total_a + 1 / total_b))
    if se == 0:
        return None, None
    z = (success_b / total_b - success_a / total_a) / se
    p = math.erfc(abs(z) / math.sqrt(2))
    return round(z, 3), round(p, 4)


class ExperimentResultsView(APIView):
    """
    How each arm of an A/B experiment is doing.

    GET /api/v1/analytics/experiments/<key>/?period=7d|28d|90d

    feed_ranker: of the feed items shown, how many were watched within 30
    minutes (watch rate). search_personalization: of the searches, how many
    led to watching one of the results. `comparison` is treatment vs control
    with a two-proportion z-test; treat p >= 0.05 as "no difference yet".
    """
    permission_classes = [IsAdmin]

    def get(self, request, key):
        from django.shortcuts import get_object_or_404
        from experiments.models import Experiment, ExperimentAssignment
        from recommendations.ranker import watched_after

        experiment = get_object_or_404(Experiment, key=key)
        try:
            period, start, end, _ = _period(request, default='28d')
        except ValueError as exc:
            return _bad_period(exc)

        variants = {name: {'assigned': 0} for name in (experiment.variants or [])}
        for variant, n in (ExperimentAssignment.objects.filter(experiment=experiment)
                           .values_list('variant').annotate(n=Count('id'))):
            variants.setdefault(variant, {})['assigned'] = n

        if key == 'feed_ranker':
            event_type, unit = Event.Type.FEED_SERVED, 'items_shown'
        elif key == 'search_personalization':
            event_type, unit = Event.Type.SEARCH, 'searches'
        else:
            event_type, unit = None, None

        if event_type:
            events = list(Event.objects.filter(
                event_type=event_type, occurred_at__gte=start, occurred_at__lte=end,
                payload__has_key='variant'))
            watched = watched_after(events)
            for name in variants:
                variants[name].update({unit: 0, 'watched': 0})
            for event in events:
                name = (event.payload or {}).get('variant')
                if name not in variants:
                    continue
                seen = {str(v) for v in watched.get(event.id, ())}
                if event_type == Event.Type.FEED_SERVED:
                    ids = [item.get('video_id') for item in event.payload.get('items', [])]
                    variants[name][unit] += len(ids)
                    variants[name]['watched'] += sum(1 for i in ids if i in seen)
                else:
                    variants[name][unit] += 1
                    ids = set(event.payload.get('result_ids') or [])
                    variants[name]['watched'] += 1 if ids & seen else 0
            for stats in variants.values():
                total = stats.get(unit) or 0
                stats['watch_rate'] = round(stats['watched'] / total, 4) if total else None

        comparison = None
        control, treatment = variants.get('control'), variants.get('treatment')
        if unit and control and treatment:
            z, p = _two_proportion_test(control['watched'], control[unit],
                                        treatment['watched'], treatment[unit])
            comparison = {
                'lift': (round(treatment['watch_rate'] / control['watch_rate'] - 1, 4)
                         if control['watch_rate'] and treatment['watch_rate'] is not None else None),
                'z': z, 'p_value': p,
                'significant': p is not None and p < 0.05,
            }

        return Response({
            'experiment': key, 'is_active': experiment.is_active, 'period': period,
            'measure': unit and f'watched / {unit}', 'variants': variants,
            'comparison': comparison,
        })
