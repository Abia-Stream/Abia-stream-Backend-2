from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from abiastream.testing import client_for, make_user, make_video
from videos.models import Video
from videos.thumbnails import PENDING, UNCHANGED, UPDATED, is_frame_of_video, upgrade_when_ready

PID = 'abia_stream/videos/thumb1'
VIDEO_URL = f'https://res.cloudinary.com/test-cloud/video/upload/v1788358420/{PID}.mp4'
FRONTEND_FRAME = (f'https://res.cloudinary.com/test-cloud/video/upload/'
                  f'c_fill,h_720,w_1280/q_auto/so_1/v1788358420/{PID}.jpg')
CUSTOM_IMAGE = 'https://res.cloudinary.com/test-cloud/image/upload/v1/abia_stream/thumbnails/mine.jpg'
READY = 'videos.thumbnails.is_ready'
NO_FINGERPRINT = 'moderation.fingerprint.compute'


def frame_video(**extra):
    extra.setdefault('cloudinary_thumbnail_url', FRONTEND_FRAME)
    return make_video(make_user(), cloudinary_public_id=PID, cloudinary_url=VIDEO_URL, **extra)


class DetectionTests(TestCase):

    def test_is_frame_of_video(self):
        self.assertTrue(is_frame_of_video(FRONTEND_FRAME, PID))
        self.assertFalse(is_frame_of_video(CUSTOM_IMAGE, PID))
        self.assertFalse(is_frame_of_video(FRONTEND_FRAME, 'abia_stream/videos/other'))
        self.assertFalse(is_frame_of_video('', PID))
        self.assertFalse(is_frame_of_video('https://example.com/video/upload/x.jpg', PID))


class UpgradeTests(TestCase):

    @mock.patch(READY, return_value=True)
    def test_frame_upgraded_when_ready_keeping_version(self, _ready):
        video = frame_video()
        self.assertEqual(upgrade_when_ready(video), UPDATED)
        video.refresh_from_db()
        self.assertIn('so_auto', video.cloudinary_thumbnail_url)
        self.assertIn('/v1788358420/', video.cloudinary_thumbnail_url)
        self.assertEqual(upgrade_when_ready(video), UNCHANGED)   # idempotent

    @mock.patch(READY, return_value=False)
    def test_not_ready_keeps_old_thumbnail(self, _ready):
        video = frame_video()
        self.assertEqual(upgrade_when_ready(video), PENDING)
        video.refresh_from_db()
        self.assertEqual(video.cloudinary_thumbnail_url, FRONTEND_FRAME)

    @mock.patch(READY, return_value=True)
    def test_custom_image_and_drafts_untouched(self, ready):
        custom = frame_video(cloudinary_thumbnail_url=CUSTOM_IMAGE)
        self.assertEqual(upgrade_when_ready(custom), UNCHANGED)
        draft = make_video(make_user(), cloudinary_url='', cloudinary_public_id='draft_x_y',
                           status=Video.Status.DRAFT, cloudinary_thumbnail_url=None)
        self.assertEqual(upgrade_when_ready(draft), UNCHANGED)
        ready.assert_not_called()

    @mock.patch(READY, return_value=True)
    def test_missing_thumbnail_filled(self, _ready):
        video = frame_video(cloudinary_thumbnail_url=None)
        self.assertEqual(upgrade_when_ready(video), UPDATED)


class FlowTests(TestCase):

    def test_direct_upload_keeps_frontend_frame_and_warms(self):
        with mock.patch('videos.views.warm_thumbnail') as warm:
            response = client_for(make_user()).post('/api/v1/videos/upload/from-cloudinary/', {
                'title': 'Upload', 'cloudinary_public_id': PID, 'cloudinary_url': VIDEO_URL,
                'cloudinary_thumbnail_url': FRONTEND_FRAME}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['cloudinary_thumbnail_url'], FRONTEND_FRAME)
        warm.assert_called_once()

    @mock.patch(READY, return_value=True)
    def test_publish_upgrades(self, _ready):
        video = frame_video(status=Video.Status.READY, published_at=None)
        with mock.patch(NO_FINGERPRINT, return_value=[]):
            data = client_for(video.creator).post(f'/api/v1/videos/{video.id}/publish/').json()
        self.assertEqual(data['status'], 'published')
        self.assertIn('so_auto', data['cloudinary_thumbnail_url'])

    @mock.patch(READY, return_value=False)
    def test_publish_not_blocked_when_not_ready(self, _ready):
        video = frame_video(status=Video.Status.READY, published_at=None)
        with mock.patch(NO_FINGERPRINT, return_value=[]):
            data = client_for(video.creator).post(f'/api/v1/videos/{video.id}/publish/').json()
        self.assertEqual((data['status'], data['cloudinary_thumbnail_url']),
                         ('published', FRONTEND_FRAME))

    @mock.patch(READY, return_value=True)
    def test_processing_finished_upgrades(self, _ready):
        video = frame_video(status=Video.Status.PROCESSING, published_at=None)
        with mock.patch(NO_FINGERPRINT, return_value=[]):
            client_for().post('/api/v1/videos/webhook/cloudinary/', {
                'notification_type': 'upload', 'public_id': PID}, format='json')
        video.refresh_from_db()
        self.assertEqual(video.status, Video.Status.READY)
        self.assertIn('so_auto', video.cloudinary_thumbnail_url)

    def test_creator_chosen_thumbnail_is_respected(self):
        video = frame_video()
        response = client_for(video.creator).post(
            f'/api/v1/videos/{video.id}/thumbnail/from-cloudinary/',
            {'thumbnail_url': CUSTOM_IMAGE}, format='json')
        self.assertEqual(response.status_code, 200)
        video.refresh_from_db()
        self.assertEqual(video.cloudinary_thumbnail_url, CUSTOM_IMAGE)


class BackfillTests(TestCase):

    def test_dry_run_then_apply(self):
        old = frame_video()
        custom = make_video(make_user(), cloudinary_thumbnail_url=CUSTOM_IMAGE)

        out = StringIO()
        call_command('refresh_auto_thumbnails', stdout=out)
        self.assertIn('1 video(s) would be updated', out.getvalue())
        old.refresh_from_db()
        self.assertEqual(old.cloudinary_thumbnail_url, FRONTEND_FRAME)

        with mock.patch(READY, return_value=False):
            pending = StringIO()
            call_command('refresh_auto_thumbnails', '--apply', stdout=pending)
        self.assertIn('0 video(s) updated, 1 pending', pending.getvalue())

        with mock.patch(READY, return_value=True):
            call_command('refresh_auto_thumbnails', '--apply', stdout=StringIO())
        old.refresh_from_db()
        custom.refresh_from_db()
        self.assertIn('so_auto', old.cloudinary_thumbnail_url)
        self.assertEqual(custom.cloudinary_thumbnail_url, CUSTOM_IMAGE)
