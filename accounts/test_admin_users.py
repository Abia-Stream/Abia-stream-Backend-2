from unittest import mock

from django.test import TestCase

from abiastream.testing import client_for, make_user
from accounts.models import User
from notifications.models import Notification

URL = '/api/v1/admin/users/'


class AccessTests(TestCase):

    def test_admin_only(self):
        target = make_user()
        for user, expected in ((None, 401), (make_user(), 403),
                               (make_user(role=User.Role.MODERATOR), 403)):
            self.assertEqual(client_for(user).get(URL).status_code, expected)
            self.assertEqual(client_for(user).patch(f'{URL}{target.id}/', {'role': 'admin'},
                                                    format='json').status_code, expected)
        target.refresh_from_db()
        self.assertEqual(target.role, User.Role.VIEWER)


class ListTests(TestCase):

    def test_list_filter_and_search(self):
        admin = make_user(role=User.Role.ADMIN)
        mod = make_user(role=User.Role.MODERATOR)
        make_user()
        client = client_for(admin)

        everyone = client.get(URL).json()
        self.assertEqual(everyone['pagination']['total'], 3)
        self.assertNotIn('password', everyone['results'][0])

        mods = client.get(URL, {'role': 'moderator'}).json()['results']
        self.assertEqual([u['id'] for u in mods], [str(mod.id)])

        found = client.get(URL, {'q': mod.email[:6]}).json()['results']
        self.assertEqual([u['id'] for u in found], [str(mod.id)])


class UpdateTests(TestCase):

    def setUp(self):
        self.admin = make_user(role=User.Role.ADMIN)
        self.client_ = client_for(self.admin)

    def patch(self, user, **body):
        return self.client_.patch(f'{URL}{user.id}/', body, format='json')

    def test_appoint_moderator_and_notify(self):
        user = make_user()
        response = self.patch(user, role='moderator')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['role'], 'moderator')
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.MODERATOR)
        self.assertTrue(Notification.objects.filter(user=user, notification_type='role_changed').exists())
        # The new moderator can use the queue.
        self.assertEqual(client_for(user).get('/api/v1/moderation/queue/').status_code, 200)

    def test_invalid_values_rejected_cleanly(self):
        user = make_user()
        self.assertEqual(self.patch(user, role='superuser').status_code, 400)
        self.assertEqual(self.patch(user, status='gone').status_code, 400)
        self.assertEqual(self.patch(user).status_code, 400)

    def test_cannot_change_own_role_or_status(self):
        self.assertEqual(self.patch(self.admin, role='viewer').status_code, 400)
        self.assertEqual(self.patch(self.admin, status='suspended').status_code, 400)
        self.assertEqual(self.patch(self.admin, is_email_verified=True).status_code, 200)

    def test_demoted_admin_loses_access_immediately(self):
        other = make_user(role=User.Role.ADMIN)
        other_client = client_for(other)
        self.assertEqual(self.patch(other, role='viewer').status_code, 200)
        # Their still-valid token no longer grants admin access.
        response = other_client.patch(f'{URL}{self.admin.id}/', {'role': 'viewer'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.ADMIN)

    def test_requester_rechecked_inside_the_lock(self):
        # Simulates the concurrent case: the requester was demoted by someone
        # else after authentication but before the change is applied.
        other = make_user(role=User.Role.ADMIN)
        target = make_user()
        original = User.objects.select_for_update

        def demote_requester_first(*args, **kwargs):
            User.objects.filter(id=self.admin.id).update(role=User.Role.VIEWER)
            return original(*args, **kwargs)

        with mock.patch.object(User.objects, 'select_for_update', side_effect=demote_requester_first):
            response = self.patch(target, role='moderator')
        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertEqual(target.role, User.Role.VIEWER)
        self.assertTrue(User.objects.filter(id=other.id, role=User.Role.ADMIN).exists())

    def test_suspend_locks_user_out(self):
        user = make_user()
        self.assertEqual(self.patch(user, status='suspended').status_code, 200)
        self.assertEqual(client_for(user).get('/api/v1/reports/').status_code, 401)

    def test_detail(self):
        user = make_user()
        data = self.client_.get(f'{URL}{user.id}/').json()
        self.assertEqual((data['id'], data['role'], data['has_channel']), (str(user.id), 'viewer', False))
