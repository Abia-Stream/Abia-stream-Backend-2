from rest_framework import serializers
from videos.models import Video, Category, Tag


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'thumbnail_url', 'display_order']


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug', 'usage_count']


class VideoUploadSerializer(serializers.ModelSerializer):
    video_file = serializers.FileField(write_only=True)
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model = Video
        fields = [
            'title', 'description', 'category',
            'visibility', 'is_monetized', 'revenue_share_percent',
            'video_file', 'tag_ids',
        ]

    def validate_video_file(self, value):
        allowed_types = ['video/mp4', 'video/avi', 'video/quicktime',
                         'video/x-matroska', 'video/webm']
        if value.content_type not in allowed_types:
            raise serializers.ValidationError('Unsupported video format.')
        if value.size > 500 * 1024 * 1024:  # 500MB
            raise serializers.ValidationError('File too large. Max 500MB.')
        return value

    def validate_visibility(self, value):
        valid = [v.value for v in Video.Visibility]
        if value not in valid:
            raise serializers.ValidationError(
                f'Invalid visibility. Choose from: {valid}'
            )
        return value

    def validate_revenue_share_percent(self, value):
        if value is not None and not (0 <= value <= 100):
            raise serializers.ValidationError(
                'Revenue share must be between 0 and 100.'
            )
        return value


class VideoFromCloudinarySerializer(serializers.ModelSerializer):
    """Used when frontend uploads directly to Cloudinary."""
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    cloudinary_public_id = serializers.CharField()
    cloudinary_url = serializers.CharField()
    cloudinary_thumbnail_url = serializers.CharField(required=False, allow_blank=True)
    duration_seconds = serializers.IntegerField(required=False)
    width = serializers.IntegerField(required=False)
    height = serializers.IntegerField(required=False)
    format = serializers.CharField(required=False)
    file_size = serializers.IntegerField(required=False)
    bitrate = serializers.IntegerField(required=False)

    class Meta:
        model = Video
        fields = [
            'title', 'description', 'category',
            'visibility', 'is_monetized', 'revenue_share_percent',
            'cloudinary_public_id', 'cloudinary_url', 'cloudinary_thumbnail_url',
            'duration_seconds', 'width', 'height', 'format', 'file_size', 'bitrate',
            'tag_ids',
        ]


class VideoSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True, read_only=True)
    category = CategorySerializer(read_only=True)
    creator_id = serializers.UUIDField(source='creator.id', read_only=True)

    class Meta:
        model = Video
        fields = [
            'id', 'creator_id', 'title', 'description',
            'cloudinary_url', 'cloudinary_thumbnail_url',
            'duration_seconds', 'width', 'height', 'format',
            'file_size', 'bitrate',
            'category', 'tags',
            'views_count', 'likes_count', 'saves_count', 'shares_count',
            'status', 'visibility', 'is_monetized', 'revenue_share_percent',
            'published_at', 'created_at', 'updated_at',
        ]


class VideoUpdateSerializer(serializers.ModelSerializer):
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model = Video
        fields = [
            'title', 'description', 'category',
            'visibility', 'status', 'is_monetized',
            'revenue_share_percent', 'cloudinary_thumbnail_url', 'tag_ids',
        ]

    def validate_status(self, value):
        # Only allow these transitions from outside
        allowed = [
            Video.Status.DRAFT,
            Video.Status.PUBLISHED,
            Video.Status.ARCHIVED,
        ]
        if value not in allowed:
            raise serializers.ValidationError(
                f'You can only set status to: draft, published, archived.'
            )
        if value == Video.Status.PUBLISHED:
            if not self.instance.cloudinary_url:
                raise serializers.ValidationError(
                    'Cannot publish a video without a valid Cloudinary URL.'
                )
            if self.instance.status not in [Video.Status.READY, Video.Status.DRAFT]:
                raise serializers.ValidationError(
                    'Video must be in ready or draft state before publishing.'
                )
        return value