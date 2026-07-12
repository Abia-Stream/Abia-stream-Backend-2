# realtime/broadcaster.py
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

channel_layer = get_channel_layer()


def broadcast_notification(user_id, notification_data):
    """
    Send a real-time notification to a specific user.
    Call this from anywhere in your Django code.
    """
    async_to_sync(channel_layer.group_send)(
        f'notifications_{user_id}',
        {
            'type': 'new_notification',
            'notification': notification_data,
        }
    )


def broadcast_video_status(video_id, status):
    """
    Broadcast video status change to all connected clients watching this video.
    Call this from webhook or anywhere status changes.
    """
    async_to_sync(channel_layer.group_send)(
        f'video_{video_id}',
        {
            'type': 'video_status_changed',
            'video_id': str(video_id),
            'status': status,
        }
    )


def broadcast_notification_to_user(user_id, video_id, status):
    """Notify user's notification panel about video status."""
    async_to_sync(channel_layer.group_send)(
        f'notifications_{user_id}',
        {
            'type': 'video_status_update',
            'video_id': str(video_id),
            'status': status,
        }
    )