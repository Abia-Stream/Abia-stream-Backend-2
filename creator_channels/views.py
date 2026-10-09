from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum, Count
from django.db.models.functions import TruncDay, TruncWeek
from datetime import timedelta
from abiastream.pagination import StandardPagination
from videos.models import Video
from playback.models import ViewLog, WatchHistory
from creator_channels.models import CreatorChannel
from subscriptions.models import Subscription
from creator_channels.serializers import (
    CreatorChannelSerializer,
    OwnerChannelSerializer,
    CreateChannelSerializer,
    UpdateChannelSerializer,
)
from accounts.models import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def require_channel(user):
    """Check user has a channel. Returns (channel, None) or (None, error Response)."""
    try:
        return CreatorChannel.objects.get(user=user), None
    except CreatorChannel.DoesNotExist:
        return None, Response(
            {'detail': 'You need to create a channel to access the creator dashboard.'},
            status=status.HTTP_403_FORBIDDEN
        )


def get_date_range(period):
    """Return start date based on period string."""
    now = timezone.now()
    periods = {'7d': 7, '28d': 28, '90d': 90}
    return now - timedelta(days=periods.get(period, 28))


# ── Channel Management ────────────────────────────────────────────────────────

class CreateChannelView(APIView):
    """
    Create a creator channel.
    Automatically promotes user role from viewer to creator.
    POST /api/channels/create/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.verification_status != 'approved':
            return Response(
                {
                    'detail': 'Identity verification required before creating a channel.',
                    'verification_status': request.user.verification_status,
                    'action': 'Please submit your ID at POST /api/v1/verification/submit/'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        if CreatorChannel.objects.filter(user=request.user).exists():
            return Response(
                {'detail': 'You already have a channel.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = CreateChannelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_name = serializer.validated_data['channel_name']
        channel_slug = slugify(channel_name)

        with transaction.atomic():
            channel = CreatorChannel.objects.create(
                user=request.user,
                channel_name=channel_name,
                channel_slug=channel_slug,
                channel_description=serializer.validated_data.get('channel_description', ''),
                banner_url=serializer.validated_data.get('banner_url', ''),
                custom_thumbnail_url=serializer.validated_data.get('custom_thumbnail_url', ''),
                subscriber_count=0,
                total_videos=0,
                is_verified=False,
            )

            # Promote viewer → creator
            if request.user.role == User.Role.VIEWER:
                request.user.role = User.Role.CREATOR
                request.user.save(update_fields=['role'])

        return Response(
            OwnerChannelSerializer(channel).data,
            status=status.HTTP_201_CREATED
        )


class MyChannelView(APIView):
    """
    GET   /api/channels/me/   — get own channel
    PATCH /api/channels/me/   — update own channel
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)
        return Response(OwnerChannelSerializer(channel).data)

    def patch(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)
        serializer = UpdateChannelSerializer(
            channel, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)

        if 'channel_name' in serializer.validated_data:
            serializer.validated_data['channel_slug'] = slugify(
                serializer.validated_data['channel_name']
            )

        serializer.save()
        channel.refresh_from_db()
        return Response(OwnerChannelSerializer(channel).data)


class DeleteChannelView(APIView):
    """
    DELETE /api/channels/me/delete/ — delete channel, demote to viewer
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)

        with transaction.atomic():
            channel.delete()
            request.user.role = User.Role.VIEWER
            request.user.save(update_fields=['role'])

        return Response(
            {'detail': 'Channel deleted successfully.'},
            status=status.HTTP_200_OK
        )


class PublicChannelView(APIView):
    """GET /api/channels/<channel_slug>/"""
    permission_classes = [AllowAny]

    def get(self, request, channel_slug):
        channel = get_object_or_404(CreatorChannel, channel_slug=channel_slug)
        return Response(CreatorChannelSerializer(channel).data)


class ChannelVideosView(APIView):
    """GET /api/channels/<channel_slug>/videos/"""
    permission_classes = [AllowAny]

    def get(self, request, channel_slug):
        from videos.serializers import VideoSerializer

        channel = get_object_or_404(CreatorChannel, channel_slug=channel_slug)
        videos = Video.objects.filter(
            creator=channel.user,
            status=Video.Status.PUBLISHED,
            visibility=Video.Visibility.PUBLIC,
        ).select_related('category').prefetch_related('tags').order_by('-published_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(videos, request)
        serializer = VideoSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)



class ChannelListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        ordering = request.query_params.get('ordering', '-created_at')
        allowed_orderings = [
            '-subscriber_count',  # top creators
            '-total_videos',
            '-created_at',
        ]
        if ordering not in allowed_orderings:
            ordering = '-created_at'

        channels = CreatorChannel.objects.select_related('user').order_by(ordering)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(channels, request)
        serializer = CreatorChannelSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

# ── Creator Dashboard ─────────────────────────────────────────────────────────

class CreatorDashboardView(APIView):
    """
    Creator dashboard summary stats.
    GET /api/channels/me/dashboard/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        channel, error = require_channel(request.user)
        if error:
            return error

        creator_videos = Video.objects.filter(creator=request.user)
        published_videos = creator_videos.filter(status=Video.Status.PUBLISHED)
        video_ids = list(creator_videos.values_list('id', flat=True))

        now = timezone.now()
        last_28_days = now - timedelta(days=28)
        previous_28_start = last_28_days - timedelta(days=28)

        # Total views
        total_views = creator_videos.aggregate(
            total=Sum('views_count')
        )['total'] or 0

        # Recent views + % change
        recent_views = ViewLog.objects.filter(
            video_id__in=video_ids,
            timestamp__gte=last_28_days
        ).count()

        previous_views = ViewLog.objects.filter(
            video_id__in=video_ids,
            timestamp__gte=previous_28_start,
            timestamp__lt=last_28_days,
        ).count()

        views_change_percent = round(
            ((recent_views - previous_views) / previous_views) * 100, 1
        ) if previous_views > 0 else 0

        # Watch time
        total_watch_seconds = WatchHistory.objects.filter(
            video_id__in=video_ids
        ).aggregate(total=Sum('watch_progress_seconds'))['total'] or 0
        total_watch_hours = round(total_watch_seconds / 3600, 1)

        # Top videos
        top_videos = published_videos.order_by('-views_count')[:5].values(
            'id', 'title', 'views_count',
            'likes_count', 'cloudinary_thumbnail_url', 'published_at'
        )

        return Response({
            'channel': {
                'id': str(channel.id),
                'channel_name': channel.channel_name,
                'channel_slug': channel.channel_slug,
                'is_verified': channel.is_verified,
            },
            'summary': {
                'total_views': total_views,
                'views_last_28_days': recent_views,
                'views_change_percent': views_change_percent,
                'total_watch_hours': total_watch_hours,
                'subscriber_count': channel.subscriber_count or 0,
                'new_subscribers_last_28_days': Subscription.objects.filter(
                    channel=channel, created_at__gte=last_28_days,
                ).count(),
                'total_videos': creator_videos.count(),
                'published_videos': published_videos.count(),
                'draft_videos': creator_videos.filter(status=Video.Status.DRAFT).count(),
                'processing_videos': creator_videos.filter(
                    status=Video.Status.PROCESSING
                ).count(),
                'recent_earnings': None,        # Phase 4
                'monetization_enabled': False,  # Phase 4
            },
            'top_videos': list(top_videos),
        })


class CreatorAnalyticsView(APIView):
    """
    Views and watch time chart data.
    GET /api/channels/me/performance/?period=28d
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        channel, error = require_channel(request.user)
        if error:
            return error

        period = request.query_params.get('period', '28d')
        if period not in ['7d', '28d', '90d']:
            return Response(
                {'detail': 'Invalid period. Use 7d, 28d or 90d.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        now = timezone.now()
        start_date = get_date_range(period)

        video_ids = list(
            Video.objects.filter(
                creator=request.user
            ).values_list('id', flat=True)
        )

        view_logs = ViewLog.objects.filter(
            video_id__in=video_ids,
            timestamp__gte=start_date,
            timestamp__lte=now,
        )

        trunc_fn = TruncDay if period == '7d' else TruncWeek

        views_by_period = view_logs.annotate(
            period=trunc_fn('timestamp')
        ).values('period').annotate(
            views=Count('id'),
            watch_seconds=Sum('watch_duration_seconds')
        ).order_by('period')

        chart_data = [
            {
                'date': entry['period'].strftime('%Y-%m-%d'),
                'views': entry['views'],
                'watch_hours': round((entry['watch_seconds'] or 0) / 3600, 2),
                'revenue': None,
            }
            for entry in views_by_period
        ]

        period_totals = view_logs.aggregate(
            total_views=Count('id'),
            total_watch_seconds=Sum('watch_duration_seconds')
        )

        return Response({
            'period': period,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': now.strftime('%Y-%m-%d'),
            'totals': {
                'views': period_totals['total_views'] or 0,
                'watch_hours': round(
                    (period_totals['total_watch_seconds'] or 0) / 3600, 2
                ),
                'revenue': None,
            },
            'chart_data': chart_data,
        })


class VideoAnalyticsView(APIView):
    """
    Analytics for a single video.
    GET /api/channels/me/videos/<video_id>/analytics/?period=28d
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, video_id):
        channel, error = require_channel(request.user)
        if error:
            return error

        video = get_object_or_404(Video, id=video_id, creator=request.user)

        period = request.query_params.get('period', '28d')
        start_date = get_date_range(period)
        now = timezone.now()

        view_logs = ViewLog.objects.filter(
            video=video,
            timestamp__gte=start_date,
        )

        views_over_time = view_logs.annotate(
            day=TruncDay('timestamp')
        ).values('day').annotate(
            views=Count('id'),
            watch_seconds=Sum('watch_duration_seconds')
        ).order_by('day')

        device_breakdown = view_logs.values('device_type').annotate(
            count=Count('id')
        ).order_by('-count')

        total_views = view_logs.count()
        completed_views = view_logs.filter(completed=True).count()
        completion_rate = round(
            (completed_views / total_views * 100) if total_views > 0 else 0, 1
        )

        total_watch_seconds = view_logs.aggregate(
            total=Sum('watch_duration_seconds')
        )['total'] or 0

        return Response({
            'video': {
                'id': str(video.id),
                'title': video.title,
                'thumbnail': video.cloudinary_thumbnail_url,
                'published_at': video.published_at,
                'duration_seconds': video.duration_seconds,
            },
            'period': period,
            'summary': {
                'total_views': video.views_count or 0,
                'likes': video.likes_count or 0,
                'saves': video.saves_count or 0,
                'period_views': total_views,
                'completion_rate': completion_rate,
                'watch_hours': round(total_watch_seconds / 3600, 2),
            },
            'device_breakdown': list(device_breakdown),
            'views_over_time': [
                {
                    'date': entry['day'].strftime('%Y-%m-%d'),
                    'views': entry['views'],
                    'watch_hours': round((entry['watch_seconds'] or 0) / 3600, 2),
                }
                for entry in views_over_time
            ],
        })


class ContentListView(APIView):
    """
    Creator's videos with stats for Content page.
    GET /api/channels/me/content/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        channel, error = require_channel(request.user)
        if error:
            return error

        videos = Video.objects.filter(
            creator=request.user
        ).select_related('category').order_by('-created_at')

        data = [
            {
                'id': str(video.id),
                'title': video.title,
                'thumbnail': video.cloudinary_thumbnail_url,
                'status': video.status,
                'visibility': video.visibility,
                'views_count': video.views_count or 0,
                'likes_count': video.likes_count or 0,
                'saves_count': video.saves_count or 0,
                'duration_seconds': video.duration_seconds,
                'category': video.category.name if video.category else None,
                'is_monetized': video.is_monetized,
                'published_at': video.published_at,
                'created_at': video.created_at,
            }
            for video in videos
        ]

        return Response(data)
    
    
from videos.file_security import validate_image_file
from videos.cloudinary_service import (
    upload_image_to_cloudinary,
    generate_signed_image_upload_params,
)


class ChannelBannerUploadView(APIView):
    """
    Server-side channel banner upload.
    POST /api/v1/channels/me/banner/
    Field: banner (File)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)

        banner_file = request.FILES.get('banner')
        if not banner_file:
            return Response(
                {'detail': 'No file provided. Use field name: banner'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            file_info = validate_image_file(banner_file)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        banner_file.name = file_info['safe_name']

        try:
            result = upload_image_to_cloudinary(
                banner_file, folder='abia_stream/channel_banners'
            )
        except Exception as e:
            return Response(
                {'detail': f'Upload failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        channel.banner_url = result['secure_url']
        channel.save(update_fields=['banner_url'])

        return Response({
            'detail': 'Channel banner updated successfully.',
            'banner_url': result['secure_url'],
        })


class ChannelBannerSignedParamsView(APIView):
    """
    GET /api/v1/channels/me/banner/signed-params/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = generate_signed_image_upload_params(
            folder='abia_stream/channel_banners'
        )
        return Response(params)


class UpdateChannelBannerFromCloudinaryView(APIView):
    """
    POST /api/v1/channels/me/banner/from-cloudinary/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)

        banner_url = request.data.get('banner_url')
        if not banner_url:
            return Response(
                {'detail': 'banner_url is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        channel.banner_url = banner_url
        channel.save(update_fields=['banner_url'])

        return Response({
            'detail': 'Channel banner updated successfully.',
            'banner_url': banner_url,
        })


class ChannelThumbnailUploadView(APIView):
    """
    Server-side channel thumbnail upload.
    POST /api/v1/channels/me/thumbnail/
    Field: thumbnail (File)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)

        thumbnail_file = request.FILES.get('thumbnail')
        if not thumbnail_file:
            return Response(
                {'detail': 'No file provided. Use field name: thumbnail'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            file_info = validate_image_file(thumbnail_file)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        thumbnail_file.name = file_info['safe_name']

        try:
            result = upload_image_to_cloudinary(
                thumbnail_file, folder='abia_stream/channel_thumbnails'
            )
        except Exception as e:
            return Response(
                {'detail': f'Upload failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        channel.custom_thumbnail_url = result['secure_url']
        channel.save(update_fields=['custom_thumbnail_url'])

        return Response({
            'detail': 'Channel thumbnail updated successfully.',
            'custom_thumbnail_url': result['secure_url'],
        })


class ChannelThumbnailSignedParamsView(APIView):
    """
    GET /api/v1/channels/me/thumbnail/signed-params/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = generate_signed_image_upload_params(
            folder='abia_stream/channel_thumbnails'
        )
        return Response(params)


class UpdateChannelThumbnailFromCloudinaryView(APIView):
    """
    POST /api/v1/channels/me/thumbnail/from-cloudinary/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)

        thumbnail_url = request.data.get('custom_thumbnail_url')
        if not thumbnail_url:
            return Response(
                {'detail': 'custom_thumbnail_url is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        channel.custom_thumbnail_url = thumbnail_url
        channel.save(update_fields=['custom_thumbnail_url'])

        return Response({
            'detail': 'Channel thumbnail updated successfully.',
            'custom_thumbnail_url': thumbnail_url,
        })

