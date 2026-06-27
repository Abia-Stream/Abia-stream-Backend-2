from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.db import transaction

from channels.models import CreatorChannel
from channels.serializers import CreatorChannelSerializer, CreateChannelSerializer, UpdateChannelSerializer
from accounts.models import User


class CreateChannelView(APIView):
    """
    Create a creator channel.
    Automatically promotes user role from viewer to creator.

    POST /api/channels/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Check if user already has a channel
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

            # Promote user role to creator
            if request.user.role == User.Role.VIEWER:
                request.user.role = User.Role.CREATOR
                request.user.save(update_fields=['role'])

        return Response(
            CreatorChannelSerializer(channel).data,
            status=status.HTTP_201_CREATED
        )


class MyChannelView(APIView):
    """
    Get or update the authenticated user's own channel.

    GET   /api/channels/me/
    PATCH /api/channels/me/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)
        return Response(CreatorChannelSerializer(channel).data)

    def patch(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)
        serializer = UpdateChannelSerializer(
            channel, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)

        # Update slug if channel_name changed
        if 'channel_name' in serializer.validated_data:
            serializer.validated_data['channel_slug'] = slugify(
                serializer.validated_data['channel_name']
            )

        serializer.save()
        channel.refresh_from_db()
        return Response(CreatorChannelSerializer(channel).data)


class DeleteChannelView(APIView):
    """
    Delete the authenticated user's channel.
    Demotes user role back to viewer.

    DELETE /api/channels/me/
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)

        with transaction.atomic():
            channel.delete()

            # Demote back to viewer
            request.user.role = User.Role.VIEWER
            request.user.save(update_fields=['role'])

        return Response(
            {'detail': 'Channel deleted successfully.'},
            status=status.HTTP_200_OK
        )


class PublicChannelView(APIView):
    """
    Get any channel by slug.

    GET /api/channels/<channel_slug>/
    """
    permission_classes = [AllowAny]

    def get(self, request, channel_slug):
        channel = get_object_or_404(CreatorChannel, channel_slug=channel_slug)
        return Response(CreatorChannelSerializer(channel).data)


class ChannelVideosView(APIView):
    """
    Get all published videos for a channel.

    GET /api/channels/<channel_slug>/videos/
    """
    permission_classes = [AllowAny]

    def get(self, request, channel_slug):
        from videos.models import Video
        from videos.serializers import VideoSerializer

        channel = get_object_or_404(CreatorChannel, channel_slug=channel_slug)

        videos = Video.objects.filter(
            creator=channel.user,
            status=Video.Status.PUBLISHED,
            visibility=Video.Visibility.PUBLIC,
        ).select_related('category').prefetch_related('tags').order_by('-published_at')

        from videos.serializers import VideoSerializer
        return Response(VideoSerializer(videos, many=True).data)


class ChannelListView(APIView):
    """
    List all creator channels.

    GET /api/channels/
    """
    permission_classes = [AllowAny]

    def get(self, request):
        channels = CreatorChannel.objects.select_related('user').order_by('-created_at')
        return Response(CreatorChannelSerializer(channels, many=True).data)