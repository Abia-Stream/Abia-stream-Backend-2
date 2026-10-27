"""Profile endpoints."""
from django.test import TestCase

from abiastream.testing import client_for, make_user
from accounts.models import User
from profiles.models import Profile


class MyProfileRoleTests(TestCase):

    def profile_for(self, role):
        user = make_user(role=role)
        Profile.objects.create(user=user, full_name='Ada Obi')
        return user

    def test_me_includes_role(self):
        for role in (User.Role.VIEWER, User.Role.CREATOR, User.Role.MODERATOR, User.Role.ADMIN):
            user = self.profile_for(role)
            response = client_for(user).get('/api/v1/profile/me/')
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()['role'], role)

    def test_role_reflects_changes_after_login(self):
        user = self.profile_for(User.Role.VIEWER)
        client = client_for(user)
        User.objects.filter(pk=user.pk).update(role=User.Role.ADMIN)
        self.assertEqual(client.get('/api/v1/profile/me/').json()['role'], 'admin')

    def test_patch_response_includes_role_and_cannot_change_it(self):
        user = self.profile_for(User.Role.VIEWER)
        response = client_for(user).patch('/api/v1/profile/me/', {'bio': 'hi', 'role': 'admin'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['role'], 'viewer')
        user.refresh_from_db()
        self.assertEqual(user.role, 'viewer')

    def test_public_profile_does_not_reveal_role(self):
        admin = self.profile_for(User.Role.ADMIN)
        response = client_for().get(f'/api/v1/profile/{admin.id}/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn('role', response.json())
