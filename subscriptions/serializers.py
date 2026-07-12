from rest_framework import serializers
from subscriptions.models import Subscription


class SubscriptionSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(
        source='channel.channel_name', read_only=True
    )
    channel_slug = serializers.CharField(
        source='channel.channel_slug', read_only=True
    )
    channel_thumbnail = serializers.CharField(
        source='channel.custom_thumbnail_url', read_only=True
    )
    subscriber_count = serializers.IntegerField(
        source='channel.subscriber_count', read_only=True
    )

    class Meta:
        model = Subscription
        fields = [
            'id', 'channel_id', 'channel_name', 'channel_slug',
            'channel_thumbnail', 'subscriber_count', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']