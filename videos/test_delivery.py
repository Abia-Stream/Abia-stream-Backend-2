"""ABR streaming URLs and signed delivery for non-public videos."""
from io import StringIO
from unittest import mock

import cloudinary.utils
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from abiastream.testing import make_user, make_video, client_for
from videos.models import Video
from videos.serializers import VideoSerializer

RENAME = 'videos.delivery.cloudinary.uploader.rename'


def authenticated_video(creator, **extra):
    video = make_video(creator, **extra)
    video.cloudinary_delivery_type = 'authenticated'
    video.cloudinary_url = video.cloudinary_url.replace('/video/upload/', '/video/authenticated/')
    video.save()
    return video


def fake_rename(public_id, _to_public_id, **kwargs):
    to_type = kwargs['to_type']
    return {
        'secure_url': f'https://res.cloudinary.com/test-cloud/video/{to_type}/v2/{public_id}.mp4',
        'version': 2,
    }


class PublicDeliveryTests(TestCase):

    def test_public_video_gets_unsigned_abr_url(self):
        video = make_video(make_user())
        data = client_for().get(f'/api/v1/videos/{video.id}/').json()

        self.assertEqual(data['cloudinary_url'], video.cloudinary_url)
        self.assertIn('/video/upload/sp_auto/', data['streaming_url'])
        self.assertTrue(data['streaming_url'].endswith('.m3u8'))
        self.assertNotIn('s--', data['streaming_url'])

    def test_lists_include_streaming_url(self):
        make_video(make_user())
        result = client_for().get('/api/v1/videos/').json()['results'][0]
        self.assertTrue(result['streaming_url'].endswith('.m3u8'))

    def test_draft_without_asset_has_no_streaming_url(self):
        draft = client_for(make_user()).post(
            '/api/v1/videos/draft/', {'title': 'x'}, format='json')
        self.assertIsNone(draft.json()['streaming_url'])


class SignedDeliveryTests(TestCase):

    def test_owner_gets_signed_urls_for_private_video(self):
        owner = make_user()
        video = authenticated_video(owner, visibility=Video.Visibility.PRIVATE)

        data = client_for(owner).get(f'/api/v1/videos/{video.id}/').json()

        self.assertIn('/video/authenticated/s--', data['cloudinary_url'])
        self.assertIn('/video/authenticated/s--', data['streaming_url'])
        self.assertIn('sp_auto', data['streaming_url'])
        self.assertIn('/video/authenticated/s--', data['cloudinary_thumbnail_url'])

    def test_other_users_are_refused(self):
        video = authenticated_video(make_user(), visibility=Video.Visibility.PRIVATE)
        response = client_for(make_user()).get(f'/api/v1/videos/{video.id}/')
        self.assertEqual(response.status_code, 403)

    def test_unlisted_link_holder_gets_signed_url(self):
        video = authenticated_video(make_user(), visibility=Video.Visibility.UNLISTED)
        data = client_for().get(f'/api/v1/videos/{video.id}/').json()
        self.assertIn('/video/authenticated/s--', data['cloudinary_url'])

    def test_no_requester_means_urls_withheld(self):
        video = authenticated_video(make_user(), visibility=Video.Visibility.PRIVATE)
        data = VideoSerializer(video).data
        self.assertIsNone(data['cloudinary_url'])
        self.assertIsNone(data['streaming_url'])
        self.assertIsNone(data['cloudinary_thumbnail_url'])

    def test_owner_list_signs(self):
        owner = make_user()
        authenticated_video(owner, visibility=Video.Visibility.PRIVATE)
        result = client_for(owner).get('/api/v1/videos/me/').json()['results'][0]
        self.assertIn('/video/authenticated/s--', result['cloudinary_url'])

    @override_settings(CLOUDINARY_AUTH_TOKEN_KEY='00112233aabbccdd', SIGNED_URL_TTL_SECONDS=600)
    def test_token_key_adds_expiring_token(self):
        owner = make_user()
        video = authenticated_video(owner, visibility=Video.Visibility.PRIVATE)
        data = client_for(owner).get(f'/api/v1/videos/{video.id}/').json()
        self.assertIn('__cld_token__=', data['cloudinary_url'])
        self.assertIn('exp=', data['cloudinary_url'])


class SignedUploadParamsTests(TestCase):

    def test_default_response_unchanged(self):
        data = client_for(make_user()).get('/api/v1/videos/upload/signed-params/').json()
        self.assertNotIn('type', data)
        expected = cloudinary.utils.api_sign_request(
            {'folder': data['folder'], 'timestamp': data['timestamp']},
            'test-cloudinary-secret')
        self.assertEqual(data['signature'], expected)

    def test_private_upload_signs_authenticated_type(self):
        data = client_for(make_user()).get(
            '/api/v1/videos/upload/signed-params/', {'visibility': 'private'}).json()
        self.assertEqual(data['type'], 'authenticated')
        expected = cloudinary.utils.api_sign_request(
            {'folder': data['folder'], 'timestamp': data['timestamp'],
             'type': 'authenticated'},
            'test-cloudinary-secret')
        self.assertEqual(data['signature'], expected)

    def test_public_visibility_param_is_plain(self):
        data = client_for(make_user()).get(
            '/api/v1/videos/upload/signed-params/', {'visibility': 'public'}).json()
        self.assertNotIn('type', data)


class DeliverySyncTests(TestCase):

    def from_cloudinary(self, user, visibility, url_type='upload'):
        public_id = 'abia_stream/videos/abc123'
        return client_for(user).post('/api/v1/videos/upload/from-cloudinary/', {
            'title': 'Uploaded',
            'visibility': visibility,
            'cloudinary_public_id': public_id,
            'cloudinary_url':
                f'https://res.cloudinary.com/test-cloud/video/{url_type}/v1/{public_id}.mp4',
        }, format='json')

    def test_private_upload_without_type_is_moved(self):
        with mock.patch(RENAME, side_effect=fake_rename) as rename:
            response = self.from_cloudinary(make_user(), 'private')

        self.assertEqual(response.status_code, 201, response.content)
        rename.assert_called_once()
        self.assertEqual(rename.call_args.kwargs['type'], 'upload')
        self.assertEqual(rename.call_args.kwargs['to_type'], 'authenticated')
        video = Video.objects.get(id=response.json()['id'])
        self.assertEqual(video.cloudinary_delivery_type, 'authenticated')
        self.assertIn('/video/authenticated/', video.cloudinary_url)

    def test_private_upload_with_type_is_not_moved(self):
        with mock.patch(RENAME) as rename:
            response = self.from_cloudinary(make_user(), 'private', url_type='authenticated')
        rename.assert_not_called()
        video = Video.objects.get(id=response.json()['id'])
        self.assertEqual(video.cloudinary_delivery_type, 'authenticated')

    def test_public_upload_untouched(self):
        with mock.patch(RENAME) as rename:
            response = self.from_cloudinary(make_user(), 'public')
        rename.assert_not_called()
        video = Video.objects.get(id=response.json()['id'])
        self.assertEqual(video.cloudinary_delivery_type, 'upload')

    def test_visibility_change_moves_both_ways(self):
        owner = make_user()
        video = make_video(owner)
        client = client_for(owner)
        with mock.patch(RENAME, side_effect=fake_rename) as rename:
            client.patch(f'/api/v1/videos/{video.id}/', {'visibility': 'private'}, format='json')
            video.refresh_from_db()
            self.assertEqual(video.cloudinary_delivery_type, 'authenticated')

            client.patch(f'/api/v1/videos/{video.id}/', {'visibility': 'public'}, format='json')
            video.refresh_from_db()
            self.assertEqual(video.cloudinary_delivery_type, 'upload')
        self.assertEqual(rename.call_count, 2)

    def test_cloudinary_failure_does_not_fail_request(self):
        owner = make_user()
        video = make_video(owner)
        with mock.patch(RENAME, side_effect=RuntimeError('cloudinary down')):
            response = client_for(owner).patch(
                f'/api/v1/videos/{video.id}/', {'visibility': 'private'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        video.refresh_from_db()
        self.assertEqual(video.visibility, 'private')
        # Left for the retrying task / sync command to repair.
        self.assertEqual(video.cloudinary_delivery_type, 'upload')

    def test_sync_command_dry_run_then_apply(self):
        stale = make_video(make_user(), visibility=Video.Visibility.PRIVATE)
        make_video(make_user())  # public + 'upload': already correct

        out = StringIO()
        with mock.patch(RENAME) as rename:
            call_command('sync_video_delivery', stdout=out)
        rename.assert_not_called()
        self.assertIn(f'would move {stale.id}', out.getvalue())

        with mock.patch(RENAME, side_effect=fake_rename):
            call_command('sync_video_delivery', '--apply', stdout=StringIO())
        stale.refresh_from_db()
        self.assertEqual(stale.cloudinary_delivery_type, 'authenticated')

    def test_delete_uses_delivery_type(self):
        owner = make_user()
        video = authenticated_video(owner, visibility=Video.Visibility.PRIVATE)
        with mock.patch('videos.cloudinary_service.cloudinary.uploader.destroy') as destroy:
            response = client_for(owner).delete(f'/api/v1/videos/{video.id}/')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(destroy.call_args.kwargs['type'], 'authenticated')


class ServerUploadTests(TestCase):

    @mock.patch('videos.views.validate_video_file', return_value={'safe_name': 'v.mp4'})
    @mock.patch('videos.cloudinary_service.cloudinary.uploader.upload_large')
    def test_private_server_upload_is_authenticated(self, upload_large, _validate):
        upload_large.return_value = {
            'public_id': 'abia_stream/videos/srv1', 'resource_type': 'video', 'version': 1,
            'secure_url': 'https://res.cloudinary.com/test-cloud/video/authenticated/v1/'
                          'abia_stream/videos/srv1.mp4',
        }
        owner = make_user()
        response = client_for(owner).post('/api/v1/videos/upload/', {
            'title': 'Server upload', 'visibility': 'private',
            'video_file': SimpleUploadedFile('v.mp4', b'0' * 10, content_type='video/mp4'),
        }, format='multipart')

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(upload_large.call_args.kwargs['type'], 'authenticated')
        video = Video.objects.get(id=response.json()['id'])
        self.assertEqual(video.cloudinary_delivery_type, 'authenticated')
        self.assertIn('/video/authenticated/s--', response.json()['cloudinary_url'])


class WebhookSignatureTests(TestCase):
    """Cloudinary notifications; see CloudinaryWebhookView."""

    URL = '/api/v1/videos/webhook/cloudinary/'

    def setUp(self):
        self.video = make_video(make_user(), status=Video.Status.PROCESSING,
                                cloudinary_public_id='abia_stream/videos/hook1')
        self.body = (
            '{"notification_type": "upload", "public_id": "abia_stream/videos/hook1"}'
        )

    def post(self, signed=True, timestamp=None):
        import time
        ts = int(timestamp or time.time())
        headers = {}
        if signed:
            sig = cloudinary.utils.compute_hex_hash(
                f'{self.body}{ts}test-cloudinary-secret',
                cloudinary.config().signature_algorithm)
            headers = {'HTTP_X_CLD_TIMESTAMP': str(ts), 'HTTP_X_CLD_SIGNATURE': sig}
        return client_for().post(self.URL, self.body, content_type='application/json',
                                 **headers)

    @override_settings(CLOUDINARY_WEBHOOK_VERIFY='enforce')
    def test_enforce_accepts_valid_signature(self):
        self.assertEqual(self.post().status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.READY)

    @override_settings(CLOUDINARY_WEBHOOK_VERIFY='enforce')
    def test_enforce_rejects_forgery_and_replay(self):
        self.assertEqual(self.post(signed=False).status_code, 401)
        self.assertEqual(self.post(timestamp=1_000_000_000).status_code, 401)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.PROCESSING)

    def test_default_log_mode_still_processes(self):
        with self.assertLogs('videos.views', level='ERROR'):
            self.assertEqual(self.post(signed=False).status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.READY)
