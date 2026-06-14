import uuid
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils import timezone

from videos.models import Video, Category, Tag, VideoTag
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

UPLOAD_ROLES = ['creator', 'admin']



# ── Helpers ───────────────────────────────────────────────────────────────────

def check_upload_permission(user):
    """Reusable role check for all upload views."""
    if user.role not in UPLOAD_ROLES:
        return Response(
            {'detail': 'Only creators and admins can upload videos.'},
            status=status.HTTP_403_FORBIDDEN
        )
    return None

def attach_tags(video, tag_ids):
    """Attach tags to a video and increment usage counts."""
    for tag_id in tag_ids:
        try:
            tag = Tag.objects.get(id=tag_id)
            VideoTag.objects.get_or_create(video=video, tag=tag)
            tag.usage_count = (tag.usage_count or 0) + 1
            tag.save()
        except Tag.DoesNotExist:
            pass


def detach_tags(video):
    """Remove all tags from a video and decrement usage counts."""
    for vt in VideoTag.objects.filter(video=video):
        tag = vt.tag
        tag.usage_count = max(0, (tag.usage_count or 1) - 1)
        tag.save()
    VideoTag.objects.filter(video=video).delete()


def is_video_accessible(video, user):
    """Check if a user can view a video based on visibility."""
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
        # TODO: check subscription when Subscription Service is built
        return False
    return False


# ── Server-side Upload ────────────────────────────────────────────────────────

class VideoUploadView(APIView):
    """
    Upload a video file directly to Django.
    Django then uploads it to Cloudinary server-side.

    POST /api/videos/upload/
    Content-Type: multipart/form-data

    Fields:
      - video_file (file, required)
      - title (string, required)
      - description (string, optional)
      - category (int, optional) — category ID
      - visibility (string, optional) — public | unlisted | private | subscribers_only
      - is_monetized (bool, optional)
      - revenue_share_percent (decimal, optional)
      - tag_ids (list of ints, optional)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        denied = check_upload_permission(request.user)
        if denied:
            return denied
        serializer = VideoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        video_file = serializer.validated_data.pop('video_file')
        tag_ids = serializer.validated_data.pop('tag_ids', [])

        # Upload to Cloudinary
        try:
            result = upload_video_to_cloudinary(video_file)
        except Exception as e:
            return Response(
                {'detail': f'Cloudinary upload failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        thumbnail_url = generate_thumbnail_url(result['public_id'])

        # Create video record
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
    """
    Get signed params for direct frontend → Cloudinary upload.

    GET /api/videos/upload/signed-params/

    Frontend uses these params to upload directly to Cloudinary,
    then calls /api/videos/upload/from-cloudinary/ with the result.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        denied = check_upload_permission(request.user)
        if denied:
            return denied
        params = generate_signed_upload_params()
        return Response(params, status=status.HTTP_200_OK)


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
        denied = check_upload_permission(request.user)
        if denied:
            return denied
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

        serializer = VideoSerializer(queryset, many=True)
        return Response(serializer.data)


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

        serializer = VideoSerializer(queryset, many=True)
        return Response(serializer.data)


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
        denied = check_upload_permission(request.user)
        if denied:
            return denied
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
        denied = check_upload_permission(request.user)
        if denied:
            return denied
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