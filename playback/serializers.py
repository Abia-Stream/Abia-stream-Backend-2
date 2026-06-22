from rest_framework import serializers
from playback.models import WatchHistory, ViewLog


class WatchHistorySerializer(serializers.ModelSerializer):
    video_id = serializers.UUIDField(source='video.id', read_only=True)
    video_title = serializers.CharField(source='video.title', read_only=True)
    video_thumbnail = serializers.CharField(
        source='video.cloudinary_thumbnail_url', read_only=True
    )
    video_duration = serializers.IntegerField(
        source='video.duration_seconds', read_only=True
    )

    class Meta:
        model = WatchHistory
        fields = [
            'id', 'video_id', 'video_title', 'video_thumbnail',
            'video_duration', 'watch_progress_seconds', 'completed',
            'device_type', 'last_watched_at',
        ]
        read_only_fields = ['id', 'last_watched_at']


class UpdateProgressSerializer(serializers.Serializer):
    """Used when user updates their watch progress."""
    video_id = serializers.UUIDField()
    watch_progress_seconds = serializers.IntegerField(min_value=0)
    completed = serializers.BooleanField(default=False)
    device_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    session_id = serializers.UUIDField(required=False, allow_null=True)


class RecordViewSerializer(serializers.Serializer):
    """Used when a video view is recorded (anonymous or authenticated)."""
    video_id = serializers.UUIDField()
    watch_duration_seconds = serializers.IntegerField(min_value=0, default=0)
    completed = serializers.BooleanField(default=False)
    device_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    referrer = serializers.CharField(max_length=500, required=False, allow_blank=True)
    session_id = serializers.UUIDField(required=False, allow_null=True)