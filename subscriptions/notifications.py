# subscriptions/notifications.py
from accounts.display import display_name
from notifications.utils import create_notification


def notify_new_subscriber(channel, subscriber):
    create_notification(
        user=channel.user,
        notification_type='new_subscriber',
        title='New Subscriber',
        message=f'{display_name(subscriber)} subscribed to your channel',
        data={
            'subscriber_id': str(subscriber.id),
            'channel_id': str(channel.id),
            'channel_name': channel.channel_name,
        }
    )