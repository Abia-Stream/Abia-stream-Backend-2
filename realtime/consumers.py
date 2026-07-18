import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket for real-time notifications.
    Frontend connects to: ws://domain/ws/notifications/?token=<access_token>
    """

    async def connect(self):
        user = self.scope['user']

        if user.is_anonymous:
            await self.close()
            return

        # Each user gets their own notification group
        self.group_name = f'notifications_{user.id}'

        # Join group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        # Send unread count on connect
        unread_count = await self.get_unread_count(user)
        await self.send(text_data=json.dumps({
            'type': 'unread_count',
            'count': unread_count,
        }))

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """Handle messages from frontend."""
        data = json.loads(text_data)

        # Frontend can mark notifications as read via WebSocket
        if data.get('type') == 'mark_read':
            notification_id = data.get('notification_id')
            await self.mark_notification_read(notification_id)

    # ── Handlers for messages sent to group ──────────────────────────────────

    async def new_notification(self, event):
        """Called when a new notification is sent to this user's group."""
        await self.send(text_data=json.dumps({
            'type': 'new_notification',
            'notification': event['notification'],
        }))

    async def video_status_update(self, event):
        """Called when a video status changes."""
        await self.send(text_data=json.dumps({
            'type': 'video_status_update',
            'video_id': event['video_id'],
            'status': event['status'],
        }))

    # ── Database helpers ──────────────────────────────────────────────────────

    @database_sync_to_async
    def get_unread_count(self, user):
        from notifications.models import Notification
        return Notification.objects.filter(
            user=user,
            is_read=False,
            is_archived=False
        ).count()

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        from notifications.models import Notification
        Notification.objects.filter(
            id=notification_id,
            user=self.scope['user']
        ).update(is_read=True)


class VideoStatusConsumer(AsyncWebsocketConsumer):
    """
    WebSocket for real-time video status updates.
    Frontend connects to: wss://domain/ws/video/<video_id>/?token=<access_token>
    """

    async def connect(self):
        user = self.scope['user']

        # Check authentication first
        if user.is_anonymous:
            await self.close(code=4001)
            return

        self.video_id = str(self.scope['url_route']['kwargs']['video_id'])
        self.group_name = f'video_{self.video_id}'

        # Join group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        # Send current status on connect
        current_status = await self.get_video_status()
        await self.send(text_data=json.dumps({
            'type': 'video_status',
            'video_id': self.video_id,
            'status': current_status,
        }))

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        pass  # read-only consumer

    async def video_status_changed(self, event):
        """Called when video status changes."""
        await self.send(text_data=json.dumps({
            'type': 'video_status',
            'video_id': event['video_id'],
            'status': event['status'],
        }))

    @database_sync_to_async
    def get_video_status(self):
        from videos.models import Video
        try:
            return Video.objects.get(id=self.video_id).status
        except Video.DoesNotExist:
            return None

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        pass  # read-only consumer

    async def video_status_changed(self, event):
        """Called when video status changes."""
        await self.send(text_data=json.dumps({
            'type': 'video_status',
            'video_id': event['video_id'],
            'status': event['status'],
        }))

    @database_sync_to_async
    def get_video_status(self):
        from videos.models import Video
        try:
            return Video.objects.get(id=self.video_id).status
        except Video.DoesNotExist:
            return None