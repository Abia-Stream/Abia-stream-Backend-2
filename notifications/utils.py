# notifications/utils.py
def create_notification(user, notification_type, title, message, data=None):
    from notifications.models import Notification
    try:
        notification = Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data or {},
            is_read=False,
            is_archived=False,
        )

        # ── Broadcast in real-time ────────────────────────────────────────
        from realtime.broadcaster import broadcast_notification
        broadcast_notification(str(user.id), {
            'id': str(notification.id),
            'notification_type': notification_type,
            'title': title,
            'message': message,
            'data': data or {},
            'is_read': False,
            'created_at': notification.created_at.isoformat(),
        })

    except Exception as e:
        print(f'Notification error: {e}')