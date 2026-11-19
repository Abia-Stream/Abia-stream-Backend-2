from django.test import TestCase

from abiastream.testing import client_for, make_user
from notifications.models import Notification


class NotificationArchiveTests(TestCase):

    def test_archived_notifications_can_be_listed_and_restored(self):
        user = make_user()
        notification = Notification.objects.create(
            user=user,
            notification_type='test',
            title='Archived notification',
            is_archived=True,
        )
        another_user_notification = Notification.objects.create(
            user=make_user(),
            notification_type='test',
            title='Another user notification',
            is_archived=True,
        )
        client = client_for(user)

        archived = client.get('/api/v1/notifications/archived/')
        self.assertEqual(archived.status_code, 200, archived.content)
        self.assertEqual(
            [item['id'] for item in archived.json()['results']],
            [str(notification.id)],
        )
        self.assertNotIn(
            str(another_user_notification.id),
            [item['id'] for item in archived.json()['results']],
        )
        denied = client.patch(
            f'/api/v1/notifications/{another_user_notification.id}/unarchive/')
        self.assertEqual(denied.status_code, 404)

        restored = client.patch(
            f'/api/v1/notifications/{notification.id}/unarchive/')
        self.assertEqual(restored.status_code, 200, restored.content)
        notification.refresh_from_db()
        self.assertFalse(notification.is_archived)

        visible = client.get('/api/v1/notifications/')
        self.assertEqual(
            [item['id'] for item in visible.json()['results']],
            [str(notification.id)],
        )
