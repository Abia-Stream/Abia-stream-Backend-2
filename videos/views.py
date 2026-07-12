import uuid
from resend.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils import timezone
from videos.file_security import validate_video_file
from abiastream.pagination import StandardPagination
from videos.models import Video, Category, Tag, VideoTag
from django.db.models import F
from django.db import connection, models
from videos.serializers import (
    VideoUploadSerializer, VideoFromCloudinarySerializer,
    VideoSerializer, VideoUpdateSerializer,
    CategorySerializer, TagSerializer,
)
from videos.cloudinary_service import (
    upload_video_to_cloudinary,
    generate_thumbnail_url,
    generate_signed_upload_params,
    delete_video_from_cloudinary,
)

UPLOAD_ROLES = ['viewer', 'creator', 'admin']



# ── Helpers ───────────────────────────────────────────────────────────────────

# def check_upload_permission(user):
#     """Reusable role check for all upload views."""
#     if user.role not in UPLOAD_ROLES:
#         return Response(
#             {'detail': 'Only creators and admins can upload videos.'},
#             status=status.HTTP_403_FORBIDDEN
#         )
#     return None



def attach_tags(video, tag_ids):
    """Attach tags to a video using raw SQL to avoid id column issue."""
    from django.utils import timezone
    for tag_id in tag_ids:
        try:
            tag = Tag.objects.get(id=tag_id)
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO video_tags (video_id, tag_id, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (video_id, tag_id) DO NOTHING
                """, [str(video.id), tag_id, timezone.now()])
            # Increment tag usage count
            Tag.objects.filter(id=tag_id).update(
                usage_count=models.F('usage_count') + 1
            )
        except Tag.DoesNotExist:
            pass


def detach_tags(video):
    """Remove all tags from a video."""
    with connection.cursor() as cursor:
        # Get tag ids first to decrement counts
        cursor.execute(
            "SELECT tag_id FROM video_tags WHERE video_id = %s",
            [str(video.id)]
        )
        tag_ids = [row[0] for row in cursor.fetchall()]

        # Decrement usage counts
        for tag_id in tag_ids:
            Tag.objects.filter(id=tag_id).update(
                usage_count=models.F('usage_count') - 1
            )

        # Delete all video tags
        cursor.execute(
            "DELETE FROM video_tags WHERE video_id = %s",
            [str(video.id)]
        )




def is_video_accessible(video, user):
    if video.visibility == Video.Visibility.PUBLIC:
        return True
    if video.visibility == Video.Visibility.UNLISTED:
        return True
    if not user.is_authenticated:
        return False
    if video.creator == user:
        return True
    if video.visibility == Video.Visibility.PRIVATE:
        return False
    if video.visibility == Video.Visibility.SUBSCRIBERS_ONLY:
        # Check if user is subscribed to the creator's channel
        from subscriptions.models import Subscription
        try:
            channel = video.creator.channel
            return Subscription.objects.filter(
                subscriber=user,
                channel=channel
            ).exists()
        except Exception:
            return False
    return False


# ── Server-side Upload ────────────────────────────────────────────────────────



class VideoUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = VideoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        video_file = serializer.validated_data.pop('video_file')
        tag_ids = serializer.validated_data.pop('tag_ids', [])

        # ── Security checks ───────────────────────────────────────────────
        try:
            file_info = validate_video_file(video_file)
        except ValidationError as e:
            return Response(
                {'detail': e.detail},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Rename file to safe name before uploading
        video_file.name = file_info['safe_name']

        # ── Upload to Cloudinary ──────────────────────────────────────────
        try:
            result = upload_video_to_cloudinary(video_file)
        except Exception as e:
            return Response(
                {'detail': f'Upload failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        thumbnail_url = generate_thumbnail_url(result['public_id'])

        # ── Save to DB using ORM (parameterized queries) ──────────────────
        video = Video.objects.create(
            creator=request.user,
            cloudinary_public_id=result['public_id'],
            cloudinary_url=result['secure_url'],
            cloudinary_thumbnail_url=thumbnail_url,
            cloudinary_resource_type=result.get('resource_type', 'video'),
            cloudinary_version=str(result.get('version', '')),
            duration_seconds=int(result.get('duration', 0) or 0),
            width=result.get('width'),
            height=result.get('height'),
            format=result.get('format'),
            file_size=result.get('bytes'),
            bitrate=result.get('bit_rate'),
            status=Video.Status.PROCESSING,
            **serializer.validated_data
        )

        attach_tags(video, tag_ids)

        return Response(
            VideoSerializer(video).data,
            status=status.HTTP_201_CREATED
        )


# ── Client-side Upload ────────────────────────────────────────────────────────

class SignedUploadParamsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from videos.cloudinary_service import generate_signed_upload_params
        import uuid

        params = generate_signed_upload_params()

        # Add unique upload ID for chunked uploads
        params['unique_upload_id'] = uuid.uuid4().hex
        params['chunk_size'] = 10 * 1024 * 1024  # 10MB chunks

        return Response(params)

class VideoFromCloudinaryView(APIView):
    """
    Save video metadata after frontend uploads directly to Cloudinary.

    POST /api/videos/upload/from-cloudinary/
    Content-Type: application/json

    Fields:
      - cloudinary_public_id (string, required)
      - cloudinary_url (string, required)
      - cloudinary_thumbnail_url (string, optional)
      - title (string, required)
      - description (string, optional)
      - duration_seconds (int, optional)
      - width (int, optional)
      - height (int, optional)
      - format (string, optional)
      - file_size (int, optional)
      - bitrate (int, optional)
      - category (int, optional)
      - visibility (string, optional)
      - is_monetized (bool, optional)
      - revenue_share_percent (decimal, optional)
      - tag_ids (list of ints, optional)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # denied = check_upload_permission(request.user)
        # if denied:
        #     return denied
        serializer = VideoFromCloudinarySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tag_ids = serializer.validated_data.pop('tag_ids', [])

        video = Video.objects.create(
            creator=request.user,
            cloudinary_resource_type='video',
            status=Video.Status.PROCESSING,
            **serializer.validated_data
        )

        attach_tags(video, tag_ids)

        return Response(
            VideoSerializer(video).data,
            status=status.HTTP_201_CREATED
        )


# ── Video Listing ─────────────────────────────────────────────────────────────

class VideoListView(APIView):
    """
    List all published public videos.

    GET /api/videos/
    Query params:
      - category (int) — filter by category ID
      - tag (int)      — filter by tag ID
      - creator (uuid) — filter by creator ID
    """
    permission_classes = [AllowAny]

    def get(self, request):
        queryset = Video.objects.filter(
            status=Video.Status.PUBLISHED,
            visibility=Video.Visibility.PUBLIC,
        ).select_related('category', 'creator').prefetch_related('tags')

        # Optional filters
        category_id = request.query_params.get('category')
        tag_id = request.query_params.get('tag')
        creator_id = request.query_params.get('creator')

        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if tag_id:
            queryset = queryset.filter(tags__id=tag_id)
        if creator_id:
            queryset = queryset.filter(creator_id=creator_id)

        
        # ── Ordering ──────────────────────────────────────────────────────
        ordering = request.query_params.get('ordering', '-created_at')
        allowed_orderings = [
            '-views_count',     # trending
            '-published_at',    # new release
            '-likes_count',     # most liked
            '-created_at',      # default
            'created_at',
        ]
        if ordering not in allowed_orderings:
            ordering = '-created_at'
        queryset = queryset.order_by(ordering)

        # Paginate
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = VideoSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)




class MyVideosView(APIView):
    """
    List the authenticated user's own videos (all statuses).

    GET /api/videos/me/
    Query params:
      - status (string) — filter by status
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Video.objects.filter(
            creator=request.user
        ).select_related('category').prefetch_related('tags')

        video_status = request.query_params.get('status')
        if video_status:
            queryset = queryset.filter(status=video_status)

        
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = VideoSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ── Single Video ──────────────────────────────────────────────────────────────

class VideoDetailView(APIView):
    """
    Get, update, or delete a single video.

    GET    /api/videos/<video_id>/  — public (visibility rules apply)
    PATCH  /api/videos/<video_id>/  — owner only
    DELETE /api/videos/<video_id>/  — owner only
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request, video_id):
        video = get_object_or_404(
            Video.objects.select_related('category', 'creator')
                         .prefetch_related('tags'),
            id=video_id
        )

        # Block unpublished videos from non-owners
        if video.status != Video.Status.PUBLISHED:
            if not request.user.is_authenticated or video.creator != request.user:
                return Response(
                    {'detail': 'Video not found.'},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Visibility check
        if not is_video_accessible(video, request.user):
            return Response(
                {'detail': 'You do not have access to this video.'},
                status=status.HTTP_403_FORBIDDEN
            )

        return Response(VideoSerializer(video).data)

    def patch(self, request, video_id):
        video = get_object_or_404(Video, id=video_id, creator=request.user)

        # Prevent editing blocked videos
        if video.status == Video.Status.BLOCKED:
            return Response(
                {'detail': 'This video has been blocked and cannot be edited.'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = VideoUpdateSerializer(video, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        tag_ids = serializer.validated_data.pop('tag_ids', None)

        # Set published_at on first publish
        if serializer.validated_data.get('status') == Video.Status.PUBLISHED:
            if not video.published_at:
                serializer.validated_data['published_at'] = timezone.now()

        serializer.save()

        # Replace tags if provided
        if tag_ids is not None:
            detach_tags(video)
            attach_tags(video, tag_ids)

        video.refresh_from_db()
        return Response(VideoSerializer(video).data)

    def delete(self, request, video_id):
        video = get_object_or_404(Video, id=video_id, creator=request.user)

        # Try to delete from Cloudinary (don't fail if it errors)
        try:
            delete_video_from_cloudinary(video.cloudinary_public_id)
        except Exception:
            pass

        video.delete()
        return Response(
            {'detail': 'Video deleted successfully.'},
            status=status.HTTP_204_NO_CONTENT
        )


# ── Publish / Archive shortcuts ───────────────────────────────────────────────

class PublishVideoView(APIView):
    """
    Publish a video that is in ready or draft state.

    POST /api/videos/<video_id>/publish/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, video_id):
        # denied = check_upload_permission(request.user)
        # if denied:
        #     return denied
        video = get_object_or_404(Video, id=video_id, creator=request.user)

        if video.status not in [Video.Status.READY, Video.Status.DRAFT]:
            return Response(
                {'detail': f'Cannot publish a video with status: {video.status}.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        video.status = Video.Status.PUBLISHED
        if not video.published_at:
            video.published_at = timezone.now()
        video.save()

        return Response(VideoSerializer(video).data)


class ArchiveVideoView(APIView):
    """
    Archive a published video.

    POST /api/videos/<video_id>/archive/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, video_id):
        # denied = check_upload_permission(request.user)
        # if denied:
        #     return denied
        video = get_object_or_404(Video, id=video_id, creator=request.user)

        if video.status != Video.Status.PUBLISHED:
            return Response(
                {'detail': 'Only published videos can be archived.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        video.status = Video.Status.ARCHIVED
        video.save()

        return Response(VideoSerializer(video).data)


# ── Categories & Tags ─────────────────────────────────────────────────────────

class CategoryListView(APIView):
    """
    List all active categories.

    GET /api/categories/
    """
    permission_classes = [AllowAny]

    def get(self, request):
        categories = Category.objects.filter(
            is_active=True
        ).order_by('display_order')
        return Response(CategorySerializer(categories, many=True).data)


class TagListView(APIView):
    """
    List all tags ordered by usage.

    GET /api/tags/
    """
    permission_classes = [AllowAny]

    def get(self, request):
        tags = Tag.objects.all().order_by('-usage_count')
        return Response(TagSerializer(tags, many=True).data)
    

class SaveDraftView(APIView):
    """
    Save video metadata as draft before or without uploading.
    Frontend calls this when user fills form but hasn't uploaded yet.

    POST /api/v1/videos/draft/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        title = request.data.get('title', '')
        if not title:
            return Response(
                {'detail': 'Title is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        video = Video.objects.create(
            creator=request.user,
            title=title,
            description=request.data.get('description', ''),
            category_id=request.data.get('category'),
            visibility=request.data.get('visibility', 'private'),
            is_monetized=request.data.get('is_monetized', False),
            status=Video.Status.DRAFT,
            # Cloudinary fields empty for now
            cloudinary_public_id=f'draft_{request.user.id}_{uuid.uuid4().hex}',
            cloudinary_url='',
        )

        return Response(
            VideoSerializer(video).data,
            status=status.HTTP_201_CREATED
        )


class UpdateDraftView(APIView):
    """
    Update draft with Cloudinary data after video is uploaded.
    Called after frontend finishes chunked upload to Cloudinary.

    PATCH /api/v1/videos/draft/<video_id>/
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, video_id):
        video = get_object_or_404(
            Video, id=video_id, creator=request.user
        )

        if video.status not in [Video.Status.DRAFT, Video.Status.PROCESSING]:
            return Response(
                {'detail': 'Only draft or processing videos can be updated.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update fields
        updatable_fields = [
            'title', 'description', 'visibility',
            'is_monetized', 'revenue_share_percent',
        ]
        cloudinary_fields = [
            'cloudinary_public_id', 'cloudinary_url',
            'cloudinary_thumbnail_url', 'cloudinary_resource_type',
            'duration_seconds', 'width', 'height',
            'format', 'file_size', 'bitrate',
        ]

        for field in updatable_fields + cloudinary_fields:
            if field in request.data:
                setattr(video, field, request.data[field])

        if request.data.get('category'):
            video.category_id = request.data['category']

        # Update status to processing when video is added
        if 'cloudinary_url' in request.data and request.data['cloudinary_url']:
            video.status = Video.Status.PROCESSING

        video.save()

        # Update tags if provided
        tag_ids = request.data.get('tag_ids', [])
        if tag_ids:
            detach_tags(video)
            attach_tags(video, tag_ids)

        video.refresh_from_db()
        return Response(VideoSerializer(video).data)


class CloudinaryWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        notification_type = request.data.get('notification_type')
        public_id = request.data.get('public_id')
        status_field = request.data.get('status')

        if notification_type in ['eager', 'upload']:
            if status_field in ['complete', None]:
                videos = Video.objects.filter(
                    cloudinary_public_id=public_id,
                    status=Video.Status.PROCESSING
                )

                if videos.exists():
                    video = videos.first()
                    videos.update(status=Video.Status.READY)

                    # ── Broadcast status change in real-time ──────────────
                    from realtime.broadcaster import (
                        broadcast_video_status,
                        broadcast_notification_to_user
                    )
                    broadcast_video_status(video.id, 'ready')
                    broadcast_notification_to_user(
                        video.creator_id, video.id, 'ready'
                    )

                    # ── Notify creator ────────────────────────────────────
                    from notifications.utils import create_notification
                    create_notification(
                        user=video.creator,
                        notification_type='video_ready',
                        title='Video Ready',
                        message=f'Your video "{video.title}" is ready to publish.',
                        data={'video_id': str(video.id)}
                    )

                    return Response({'detail': 'Status updated to ready.'})

            elif status_field == 'failed':
                videos = Video.objects.filter(
                    cloudinary_public_id=public_id,
                    status=Video.Status.PROCESSING
                )
                if videos.exists():
                    video = videos.first()
                    videos.update(status=Video.Status.FAILED)

                    from realtime.broadcaster import broadcast_video_status
                    broadcast_video_status(video.id, 'failed')

                    return Response({'detail': 'Status updated to failed.'})

        return Response({'detail': 'Ignored.'})