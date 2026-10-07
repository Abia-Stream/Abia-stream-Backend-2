from collections import Counter

from django.db.models import Count, Max, Min
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from abiastream.pagination import StandardPagination
from accounts.models import User
from comments.models import Comment
from moderation.models import ContentReport, ModerationAction
from moderation.permissions import IsModerator
from moderation.serializers import (
    ApplyActionSerializer, CreateReportSerializer, ModerationActionSerializer,
    MyReportSerializer, ReportSerializer,
)
from moderation.services import ModerationError, apply_action, file_report
from videos.models import Video


# ── User-facing ───────────────────────────────────────────────────────────────

class ReportView(APIView):
    """
    Report a video or comment.

    POST /api/v1/reports/
      {"video_id": "<uuid>" | "comment_id": "<uuid>",
       "reason": "spam|harassment|hate|violence|sexual|child_safety|copyright|misinformation|other",
       "details": "optional text"}

    Re-reporting the same target while the first report is open returns the
    existing report (200) instead of creating a duplicate (201).

    GET /api/v1/reports/ — the caller's own reports.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'reports'

    def get_throttles(self):
        # Only filing is rate limited.
        return super().get_throttles() if self.request.method == 'POST' else []

    def post(self, request):
        serializer = CreateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        video = comment = None
        if data.get('comment_id'):
            comment = get_object_or_404(Comment, id=data['comment_id'], is_deleted=False)
        else:
            video = get_object_or_404(Video, id=data['video_id'])

        try:
            report, created = file_report(
                request.user, video=video, comment=comment,
                reason=data['reason'], details=data.get('details'),
            )
        except ModerationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            MyReportSerializer(report).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def get(self, request):
        reports = ContentReport.objects.filter(reporter=request.user).order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(reports, request)
        return paginator.get_paginated_response(MyReportSerializer(page, many=True).data)


# ── Moderator-facing ──────────────────────────────────────────────────────────

def _video_summary(video):
    return {
        'id': str(video.id),
        'title': video.title,
        'status': video.status,
        'visibility': video.visibility,
        'thumbnail_url': video.cloudinary_thumbnail_url,
        'creator_id': str(video.creator_id),
        'creator_email': video.creator.email,
    }


def _comment_summary(comment):
    return {
        'id': str(comment.id),
        'content': comment.content,
        'is_deleted': comment.is_deleted,
        'video_id': str(comment.video_id),
        'author_id': str(comment.user_id),
        'author_email': comment.user.email,
    }


class ModerationQueueView(APIView):
    """
    Reported content awaiting review, one row per target, most-reported first.

    GET /api/v1/moderation/queue/?target_type=video|comment&status=open
    """
    permission_classes = [IsModerator]

    def get(self, request):
        report_status = request.query_params.get('status', ContentReport.Status.OPEN)
        if report_status not in ContentReport.Status.values:
            return Response({'detail': 'Invalid status.'}, status=status.HTTP_400_BAD_REQUEST)

        reports = ContentReport.objects.filter(status=report_status)
        target_type = request.query_params.get('target_type')
        if target_type:
            if target_type not in ContentReport.TargetType.values:
                return Response({'detail': 'Invalid target_type.'},
                                status=status.HTTP_400_BAD_REQUEST)
            reports = reports.filter(target_type=target_type)

        grouped = (
            reports.values('target_type', 'video_id', 'comment_id')
            .annotate(report_count=Count('id'),
                      first_reported_at=Min('created_at'),
                      last_reported_at=Max('created_at'))
            .order_by('-report_count', 'first_reported_at')
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(grouped, request)

        video_ids = {row['video_id'] for row in page if row['target_type'] == 'video'}
        comment_ids = {row['comment_id'] for row in page if row['comment_id']}
        videos = {v.id: v for v in Video.objects.filter(id__in=video_ids).select_related('creator')}
        comments = {c.id: c for c in
                    Comment.objects.filter(id__in=comment_ids).select_related('user')}

        reasons = {}
        for row in reports.filter(
                video_id__in=video_ids, target_type='video').values('video_id', 'reason'):
            reasons.setdefault(('video', row['video_id']), Counter())[row['reason']] += 1
        for row in reports.filter(comment_id__in=comment_ids).values('comment_id', 'reason'):
            reasons.setdefault(('comment', row['comment_id']), Counter())[row['reason']] += 1

        results = []
        for row in page:
            if row['target_type'] == 'video':
                key = ('video', row['video_id'])
                target = videos.get(row['video_id'])
                summary = _video_summary(target) if target else None
            else:
                key = ('comment', row['comment_id'])
                target = comments.get(row['comment_id'])
                summary = _comment_summary(target) if target else None
            results.append({
                'target_type': row['target_type'],
                'target': summary,
                'report_count': row['report_count'],
                'reasons': dict(reasons.get(key, {})),
                'first_reported_at': row['first_reported_at'],
                'last_reported_at': row['last_reported_at'],
            })
        return paginator.get_paginated_response(results)


class ModerationReportListView(APIView):
    """
    Individual reports, e.g. to read every report on one target.

    GET /api/v1/moderation/reports/?video_id=&comment_id=&status=
    """
    permission_classes = [IsModerator]

    def get(self, request):
        reports = ContentReport.objects.all().order_by('-created_at')
        params = request.query_params
        if params.get('comment_id'):
            reports = reports.filter(comment_id=params['comment_id'])
        elif params.get('video_id'):
            reports = reports.filter(video_id=params['video_id'], target_type='video')
        if params.get('status'):
            reports = reports.filter(status=params['status'])

        paginator = StandardPagination()
        page = paginator.paginate_queryset(reports, request)
        return paginator.get_paginated_response(ReportSerializer(page, many=True).data)


class ModerationActionView(APIView):
    """
    Apply a moderation decision, or read the audit log.

    POST /api/v1/moderation/actions/
      {"action": "block_video|restore_video|remove_comment|restore_comment|
                  suspend_user|unsuspend_user|dismiss",
       "video_id" | "comment_id" | "user_id": "<uuid>",
       "note": "optional; included in the notification to the creator"}

    block_video / remove_comment / dismiss also resolve the target's open
    reports (actioned / dismissed).

    GET /api/v1/moderation/actions/?video_id=&comment_id=&user_id=
    """
    permission_classes = [IsModerator]

    def post(self, request):
        serializer = ApplyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        video = comment = user = None
        if data.get('video_id'):
            video = get_object_or_404(Video, id=data['video_id'])
        if data.get('comment_id'):
            comment = get_object_or_404(Comment, id=data['comment_id'])
        if data.get('user_id'):
            user = get_object_or_404(User, id=data['user_id'])

        try:
            record, resolved = apply_action(
                request.user, data['action'],
                video=video, comment=comment, user=user, note=data.get('note'),
            )
        except ModerationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'action': ModerationActionSerializer(record).data,
            'reports_resolved': resolved,
        }, status=status.HTTP_201_CREATED)

    def get(self, request):
        actions = ModerationAction.objects.all()
        params = request.query_params
        if params.get('video_id'):
            actions = actions.filter(video_id=params['video_id'])
        if params.get('comment_id'):
            actions = actions.filter(comment_id=params['comment_id'])
        if params.get('user_id'):
            actions = actions.filter(target_user_id=params['user_id'])

        paginator = StandardPagination()
        page = paginator.paginate_queryset(actions, request)
        return paginator.get_paginated_response(
            ModerationActionSerializer(page, many=True).data)
