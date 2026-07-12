from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.db.models import F

from subscriptions.models import Subscription
from subscriptions.serializers import SubscriptionSerializer
from creator_channels.models import CreatorChannel
from subscriptions.notifications import notify_new_subscriber


class SubscribeView(APIView):
    """
    Subscribe or unsubscribe from a channel (toggle).

    POST /api/subscriptions/<channel_slug>/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, channel_slug):
        channel = get_object_or_404(CreatorChannel, channel_slug=channel_slug)

        # Can't subscribe to own channel
        if channel.user == request.user:
            return Response(
                {'detail': 'You cannot subscribe to your own channel.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        existing = Subscription.objects.filter(
            subscriber=request.user,
            channel=channel
        ).first()

        if existing:
            # Unsubscribe
            existing.delete()

            # Decrement subscriber count
            CreatorChannel.objects.filter(id=channel.id).update(
                subscriber_count=F('subscriber_count') - 1
            )

            # Update profile total_subscribers
            from profiles.models import Profile
            Profile.objects.filter(user=channel.user).update(
                total_subscribers=F('total_subscribers') - 1
            )

            return Response({
                'detail': f'Unsubscribed from {channel.channel_name}.',
                'action': 'unsubscribed',
                'channel_slug': channel_slug,
                'subscriber_count': max(0, (channel.subscriber_count or 1) - 1),
            }, status=status.HTTP_200_OK)

        else:
            # Subscribe
            Subscription.objects.create(
                subscriber=request.user,
                channel=channel
            )

            # Increment subscriber count
            CreatorChannel.objects.filter(id=channel.id).update(
                subscriber_count=F('subscriber_count') + 1
            )

            # Update profile total_subscribers
            from profiles.models import Profile
            Profile.objects.filter(user=channel.user).update(
                total_subscribers=F('total_subscribers') + 1
            )

            # Notify channel owner
            channel.refresh_from_db()
            notify_new_subscriber(channel, request.user)

            return Response({
                'detail': f'Subscribed to {channel.channel_name}.',
                'action': 'subscribed',
                'channel_slug': channel_slug,
                'subscriber_count': channel.subscriber_count or 1,
            }, status=status.HTTP_201_CREATED)


class MySubscriptionsView(APIView):
    """
    Get all channels the authenticated user subscribes to.

    GET /api/subscriptions/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        subscriptions = Subscription.objects.filter(
            subscriber=request.user
        ).select_related('channel').order_by('-created_at')

        serializer = SubscriptionSerializer(subscriptions, many=True)
        return Response(serializer.data)


class ChannelSubscriptionStatusView(APIView):
    """
    Check if the authenticated user is subscribed to a channel.

    GET /api/subscriptions/<channel_slug>/status/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, channel_slug):
        channel = get_object_or_404(CreatorChannel, channel_slug=channel_slug)

        is_subscribed = Subscription.objects.filter(
            subscriber=request.user,
            channel=channel
        ).exists()

        return Response({
            'channel_slug': channel_slug,
            'channel_name': channel.channel_name,
            'is_subscribed': is_subscribed,
            'subscriber_count': channel.subscriber_count or 0,
        })


class ChannelSubscribersView(APIView):
    """
    Get subscriber count and list for a channel (public).

    GET /api/subscriptions/<channel_slug>/subscribers/
    """
    permission_classes = [AllowAny]

    def get(self, request, channel_slug):
        channel = get_object_or_404(CreatorChannel, channel_slug=channel_slug)

        subscribers = Subscription.objects.filter(
            channel=channel
        ).select_related('subscriber').order_by('-created_at')

        return Response({
            'channel_name': channel.channel_name,
            'subscriber_count': channel.subscriber_count or 0,
            'subscribers': [
                {
                    'id': str(sub.subscriber.id),
                    'subscribed_at': sub.created_at,
                }
                for sub in subscribers
            ]
        })