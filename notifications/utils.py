import uuid
from django.utils import timezone


def create_notification(user, notification_type, title, message, data=None):
    """
    Central helper to create notifications from any app.
    Used by subscriptions, interactions, videos etc.
    """
    from notifications.models import Notification
    try:
        Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data or {},
            is_read=False,
            is_archived=False,
        )
    except Exception as e:
        print(f'Notification creation failed: {e}')
        # Never crash the main flow because of a notification failure