from rest_framework import serializers
from channels.models import CreatorChannel
from django.utils.text import slugify
import re


class CreatorChannelSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source='user.email', read_only=True)
    owner_role = serializers.CharField(source='user.role', read_only=True)

    class Meta:
        model = CreatorChannel
        fields = [
            'id', 'owner_email', 'owner_role',
            'channel_name', 'channel_slug',
            'banner_url', 'channel_description',
            'subscriber_count', 'total_videos',
            'is_verified', 'custom_thumbnail_url',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'channel_slug', 'subscriber_count',
            'total_videos', 'is_verified', 'created_at', 'updated_at',
        ]


class CreateChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreatorChannel
        fields = ['channel_name', 'channel_description', 'banner_url', 'custom_thumbnail_url']

    def validate_channel_name(self, value):
        # Only allow letters, numbers, spaces, hyphens, underscores
        if not re.match(r'^[\w\s\-]+$', value):
            raise serializers.ValidationError(
                'Channel name can only contain letters, numbers, spaces, hyphens and underscores.'
            )
        # Check uniqueness
        slug = slugify(value)
        if CreatorChannel.objects.filter(channel_slug=slug).exists():
            raise serializers.ValidationError(
                'A channel with this name already exists.'
            )
        return value


class UpdateChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreatorChannel
        fields = [
            'channel_name', 'channel_description',
            'banner_url', 'custom_thumbnail_url',
        ]

    def validate_channel_name(self, value):
        if not re.match(r'^[\w\s\-]+$', value):
            raise serializers.ValidationError(
                'Channel name can only contain letters, numbers, spaces, hyphens and underscores.'
            )
        slug = slugify(value)
        # Check uniqueness excluding current channel
        if CreatorChannel.objects.filter(
            channel_slug=slug
        ).exclude(id=self.instance.id).exists():
            raise serializers.ValidationError(
                'A channel with this name already exists.'
            )
        return value