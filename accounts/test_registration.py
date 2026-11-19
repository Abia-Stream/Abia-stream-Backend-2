"""Password sign-up end to end, plus the production issues reported on 14 Oct 2026."""
from unittest import mock

from django.test import TestCase

from abiastream.testing import client_for, make_user, make_video
from accounts.models import User
from creator_channels.models import CreatorChannel

SEND = 'accounts.email_service.send_verification_otp'


class PasswordSignupTests(TestCase):

    def register(self, **body):
        payload = {'email': 'ada@example.com', 'password': 'Str0ngPass!word', 'full_name': 'Ada Obi'}
        payload.update(body)
        return client_for().post('/api/v1/auth/register/', payload, format='json')

    def test_register_verify_login(self):
        with mock.patch(SEND) as send:
            response = self.register()
        self.assertEqual(response.status_code, 201, response.content)
        email, otp = send.call_args.args
        self.assertEqual(email, 'ada@example.com')

        verified = client_for().post('/api/v1/auth/verify-email/', {'email': email, 'otp': otp},
                                     format='json')
        self.assertEqual(verified.status_code, 200, verified.content)
        self.assertIn('access', verified.json())
        self.assertIn('refresh', verified.json())
        self.assertEqual(verified.json()['user']['email'], email)

        login = client_for().post('/api/v1/auth/login/', {'email': email, 'password': 'Str0ngPass!word'},
                                  format='json')
        self.assertEqual(login.status_code, 200, login.content)
        self.assertIn('access', login.json())

    def test_email_failure_creates_nothing(self):
        with mock.patch(SEND, side_effect=RuntimeError('resend: testing emails only to owner')):
            response = self.register()
        self.assertEqual(response.status_code, 503)
        self.assertIn("wasn't created", response.json()['detail'])
        self.assertFalse(User.objects.filter(email='ada@example.com').exists())
        # The user can simply try again once email works.
        with mock.patch(SEND):
            self.assertEqual(self.register().status_code, 201)

    def test_unverified_email_gets_clear_guidance(self):
        with mock.patch(SEND):
            self.register()
            again = self.register()
        self.assertEqual(again.status_code, 400)
        self.assertIn('Resend code', again.json()['email'][0])
        with mock.patch('accounts.views.send_verification_otp') as send:
            resend = client_for().post('/api/v1/auth/resend-otp/', {'email': 'ada@example.com'},
                                       format='json')
        self.assertEqual(resend.status_code, 200)
        send.assert_called_once()

    def test_existing_verified_email(self):
        User.objects.filter(pk=make_user().pk).update(email='taken@example.com')
        with mock.patch(SEND):
            response = self.register(email='Taken@Example.com')
        self.assertEqual(response.status_code, 400)
        self.assertIn('already exists', response.json()['email'][0])

    def test_required_fields(self):
        response = client_for().post('/api/v1/auth/register/', {'email': 'x@example.com',
                                                                'password': 'Str0ngPass!word'},
                                     format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('full_name', response.json())


class DebugDefaultTests(TestCase):

    def test_debug_off_unless_explicitly_enabled(self):
        import os
        from decouple import config
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DEBUG', None)
            with mock.patch('decouple.AutoConfig.__call__',
                            side_effect=lambda key, default=None, cast=None: default):
                self.assertFalse(config('DEBUG', default=False, cast=bool))
        source = open('abiastream/settings.py', encoding='utf-8').read()
        self.assertIn("DEBUG = config('DEBUG', default=False, cast=bool)", source)


class VideoChannelFieldsTests(TestCase):

    def test_video_has_channel_slug_and_name(self):
        creator = make_user()
        CreatorChannel.objects.create(user=creator, channel_name='Abia Vibes', channel_slug='abia-vibes')
        video = make_video(creator)
        no_channel = make_video(make_user())

        detail = client_for().get(f'/api/v1/videos/{video.id}/').json()
        self.assertEqual((detail['channel_slug'], detail['channel_name']), ('abia-vibes', 'Abia Vibes'))

        listed = {v['id']: v for v in client_for().get('/api/v1/videos/').json()['results']}
        self.assertEqual(listed[str(video.id)]['channel_slug'], 'abia-vibes')
        self.assertIsNone(listed[str(no_channel.id)]['channel_slug'])

    def test_list_does_not_query_per_video(self):
        for i in range(6):
            creator = make_user()
            CreatorChannel.objects.create(user=creator, channel_name=f'C{i}', channel_slug=f'c{i}')
            make_video(creator)
        client = client_for()
        client.get('/api/v1/videos/')                        # warm-up
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as six:
            client.get('/api/v1/videos/')
        for i in range(6, 8):
            creator = make_user()
            CreatorChannel.objects.create(user=creator, channel_name=f'C{i}', channel_slug=f'c{i}')
            make_video(creator)
        with CaptureQueriesContext(connection) as eight:
            client.get('/api/v1/videos/')
        self.assertEqual(len(six), len(eight))               # constant, not +1 per video
