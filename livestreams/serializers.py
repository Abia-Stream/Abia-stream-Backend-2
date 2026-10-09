from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from livestreams.models import ChatMessage, LiveStream


class CreateLiveStreamSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    scheduled_start_time = serializers.DateTimeField(required=False, allow_null=True)
    thumbnail_url = serializers.URLField(required=False, allow_blank=True, max_length=500)
    chat_enabled = serializers.BooleanField(default=True)
    save_recording = serializers.BooleanField(default=True)
    publish_recording = serializers.BooleanField(default=False)

    def validate_scheduled_start_time(self, value):
        if value and value < timezone.now() - timedelta(minutes=5):
            raise serializers.ValidationError('Scheduled start time is in the past.')
        return value


class UpdateLiveStreamSerializer(serializers.Serializer):
    """save_recording is fixed at creation (it decides Cloudinary's outputs)."""
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    scheduled_start_time = serializers.DateTimeField(required=False, allow_null=True)
    thumbnail_url = serializers.URLField(required=False, allow_blank=True, max_length=500)
    chat_enabled = serializers.BooleanField(required=False)
    publish_recording = serializers.BooleanField(required=False)


def _creator_summary(user):
    try:
        channel = user.channel
    except Exception:  # noqa: BLE001 - RelatedObjectDoesNotExist
        channel = None
    return {
        'id': str(user.id),
        'channel_name': channel.channel_name if channel else None,
        'channel_slug': channel.channel_slug if channel else None,
        'is_verified': bool(channel.is_verified) if channel else False,
    }


class LiveStreamSerializer(serializers.ModelSerializer):
    """
    Public view. `playback_url` (HLS) is only set while the stream is live.
    `recording_video_id` only once a published recording exists.
    """
    creator = serializers.SerializerMethodField()
    playback_url = serializers.SerializerMethodField()
    recording_video_id = serializers.SerializerMethodField()

    class Meta:
        model = LiveStream
        fields = [
            'id', 'title', 'description', 'thumbnail_url', 'status', 'creator',
            'scheduled_start_time', 'actual_start_time', 'actual_end_time',
            'viewer_count', 'max_concurrent_viewers', 'chat_enabled',
            'playback_url', 'recording_video_id', 'created_at',
        ]

    def get_creator(self, stream):
        return _creator_summary(stream.creator)

    def get_playback_url(self, stream):
        return stream.hls_url if stream.status == LiveStream.Status.LIVE else None

    def get_recording_video_id(self, stream):
        from videos.models import Video
        video = stream.recording_video
        if video and video.status == Video.Status.PUBLISHED \
                and video.visibility == Video.Visibility.PUBLIC:
            return str(video.id)
        return None


class OwnerLiveStreamSerializer(LiveStreamSerializer):
    """
    The creator's own view: adds the encoder settings (keep the key secret —
    anyone holding it can broadcast as this stream) and recording details.
    """
    recording_video_id = serializers.UUIDField(read_only=True)

    class Meta(LiveStreamSerializer.Meta):
        fields = LiveStreamSerializer.Meta.fields + [
            'rtmp_url', 'stream_key', 'hls_url', 'save_recording', 'publish_recording',
        ]


class ChatUserSerializer(serializers.Serializer):
    """Display info only — never the email (chat is public)."""
    id = serializers.UUIDField()
    display_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    def get_display_name(self, user):
        from accounts.display import display_name
        return display_name(user)

    def get_avatar_url(self, user):
        try:
            return user.profile.avatar_url
        except Exception:  # noqa: BLE001
            return None


class ChatMessageSerializer(serializers.ModelSerializer):
    user = ChatUserSerializer(read_only=True)
    livestream_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ChatMessage
        fields = ['id', 'livestream_id', 'user', 'content', 'created_at']
