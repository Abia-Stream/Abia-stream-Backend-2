"""Automatic moderation: fingerprints, holds, text signals, upload limits."""
import io
import random
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from abiastream.testing import client_for, make_user, make_video
from accounts.models import User
from comments.models import Comment
from moderation import fingerprint as fp
from moderation import text_checks
from moderation.auto import check_video
from moderation.models import ContentReport, VideoFingerprint
from notifications.models import Notification
from videos.models import Video

COMPUTE = 'moderation.fingerprint.compute'


def hashes(seed, n=6):
    """Deterministic 'informative' frame hashes (about half the bits set)."""
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        h = fp.to_signed(rng.getrandbits(64))
        if fp.is_informative(h):
            out.append(h)
    return out


def flip_bits(h, count):
    u = fp.to_unsigned(h)
    for bit in range(count):
        u ^= 1 << (bit * 7 % 64)
    return fp.to_signed(u)


def fingerprint(video, frame_hashes, duration=None):
    return VideoFingerprint.objects.create(
        video=video, frame_hashes=frame_hashes,
        duration_seconds=duration if duration is not None else video.duration_seconds)


class FingerprintMathTests(TestCase):

    def test_dhash_of_gradient(self):
        # Brightness rising left to right: every left<right comparison is 1.
        image = Image.new('L', (9, 8))
        image.putdata([col * 20 for _ in range(8) for col in range(9)])
        self.assertEqual(fp.dhash(image), (1 << 64) - 1)

    def test_signed_round_trip(self):
        for value in (0, 1, (1 << 63), (1 << 64) - 1):
            self.assertEqual(fp.to_unsigned(fp.to_signed(value)), value)

    def test_similarity(self):
        a = hashes(1)
        self.assertEqual(fp.similarity(a, a), 1.0)
        self.assertEqual(fp.similarity(a, [flip_bits(h, 4) for h in a]), 1.0)   # re-encode
        self.assertEqual(fp.similarity(a[1:5], a), 1.0)                          # trimmed copy
        self.assertLess(fp.similarity(a, hashes(2)), 0.5)                        # different video
        flat = [0, -1, 0, 0, -1, 0]
        self.assertIsNone(fp.similarity(flat, flat))                             # black frames

    def test_same_video_needs_similar_duration(self):
        a = hashes(3)
        self.assertTrue(fp.is_same_video((a, 120), (a, 125))[0])
        self.assertFalse(fp.is_same_video((a, 120), (a, 600))[0])


class HoldTests(TestCase):

    def setUp(self):
        self.original_owner = make_user()
        self.blocked = make_video(self.original_owner, status=Video.Status.BLOCKED, title='bad')
        self.frames = hashes(10)
        fingerprint(self.blocked, self.frames)
        self.uploader = make_user()

    def publish(self, video):
        return client_for(self.uploader).post(f'/api/v1/videos/{video.id}/publish/')

    def test_reupload_of_blocked_video_is_held_not_published(self):
        reupload = make_video(self.uploader, status=Video.Status.READY, published_at=None)
        with mock.patch(COMPUTE, return_value=[flip_bits(h, 3) for h in self.frames]):
            response = self.publish(reupload)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['status'], 'held')
        reupload.refresh_from_db()
        self.assertEqual(reupload.status, Video.Status.HELD)
        self.assertIsNone(reupload.published_at)
        # Hidden from the public and from lists.
        self.assertEqual(client_for().get(f'/api/v1/videos/{reupload.id}/').status_code, 404)
        self.assertEqual(client_for().get('/api/v1/videos/').json()['results'], [])
        flag = ContentReport.objects.get(video=reupload, source='auto')
        self.assertEqual((flag.signal, flag.reporter_id, flag.signal_details['previous_status']),
                         ('reupload_of_blocked', None, 'ready'))
        self.assertEqual(flag.signal_details['matched_video_id'], str(self.blocked.id))
        self.assertIsNone(flag.details)  # the human free-text field is untouched
        self.assertTrue(Notification.objects.filter(
            user=self.uploader, notification_type='video_held').exists())

    def test_creator_cannot_change_status_while_held(self):
        held = make_video(self.uploader, status=Video.Status.HELD)
        response = client_for(self.uploader).patch(
            f'/api/v1/videos/{held.id}/', {'status': 'draft'}, format='json')
        self.assertEqual(response.status_code, 403)
        ok = client_for(self.uploader).patch(
            f'/api/v1/videos/{held.id}/', {'title': 'fixed title'}, format='json')
        self.assertEqual(ok.status_code, 200)

    def test_patch_publish_is_screened_too(self):
        reupload = make_video(self.uploader, status=Video.Status.READY, published_at=None)
        with mock.patch(COMPUTE, return_value=self.frames):
            response = client_for(self.uploader).patch(
                f'/api/v1/videos/{reupload.id}/',
                {'status': 'published', 'title': 'new'}, format='json')
        self.assertEqual(response.json()['status'], 'held')
        self.assertEqual(response.json()['title'], 'new')

    def test_unrelated_video_publishes(self):
        clean = make_video(self.uploader, status=Video.Status.READY, published_at=None)
        with mock.patch(COMPUTE, return_value=hashes(99)):
            response = self.publish(clean)
        self.assertEqual(response.json()['status'], 'published')
        self.assertTrue(VideoFingerprint.objects.filter(video=clean).exists())

    def test_cloudinary_unreachable_fails_open_then_scan_catches_up(self):
        video = make_video(self.uploader, status=Video.Status.READY, published_at=None)
        with mock.patch(COMPUTE, side_effect=fp.FingerprintUnavailable('down')):
            response = self.publish(video)
        self.assertEqual(response.json()['status'], 'published')
        self.assertFalse(VideoFingerprint.objects.filter(video=video).exists())

        with mock.patch(COMPUTE, return_value=self.frames):
            call_command('scan_videos', stdout=io.StringIO())
        video.refresh_from_db()
        self.assertEqual(video.status, Video.Status.HELD)

    def test_webhook_holds_instead_of_announcing_ready(self):
        video = make_video(self.uploader, status=Video.Status.PROCESSING, published_at=None,
                           cloudinary_public_id='abia_stream/videos/hook9')
        with mock.patch(COMPUTE, return_value=self.frames):
            response = client_for().post('/api/v1/videos/webhook/cloudinary/', {
                'notification_type': 'upload', 'public_id': 'abia_stream/videos/hook9'},
                format='json')
        self.assertEqual(response.json()['detail'], 'Held for review.')
        video.refresh_from_db()
        self.assertEqual(video.status, Video.Status.HELD)
        self.assertFalse(Notification.objects.filter(notification_type='video_ready').exists())


class ModeratorReviewTests(TestCase):

    def setUp(self):
        self.moderator = make_user(role=User.Role.MODERATOR)
        self.creator = make_user()
        self.frames = hashes(20)

    def act(self, **body):
        return client_for(self.moderator).post('/api/v1/moderation/actions/', body, format='json')

    def held_video(self, previous):
        video = make_video(self.creator, status=previous)
        from moderation.auto import hold_video
        hold_video(video, signal='reupload_of_blocked', details={'matched_video_id': 'x'})
        return video

    def test_approve_restores_previous_status_and_dismisses(self):
        video = self.held_video(Video.Status.PUBLISHED)
        response = self.act(action='approve_video', video_id=str(video.id))

        self.assertEqual(response.status_code, 201, response.content)
        video.refresh_from_db()
        self.assertEqual(video.status, Video.Status.PUBLISHED)
        self.assertEqual(ContentReport.objects.get(video=video).status, 'dismissed')
        self.assertTrue(Notification.objects.filter(
            user=self.creator, notification_type='video_approved').exists())
        self.assertEqual(self.act(action='approve_video', video_id=str(video.id)).status_code, 400)

    def test_block_held_then_restore_skips_the_hold(self):
        video = self.held_video(Video.Status.READY)
        self.assertEqual(self.act(action='block_video', video_id=str(video.id)).status_code, 201)
        self.assertEqual(self.act(action='restore_video', video_id=str(video.id)).status_code, 201)
        video.refresh_from_db()
        self.assertEqual(video.status, Video.Status.READY)

    def test_blocking_holds_existing_reuploads(self):
        original = make_video(self.creator)
        copy = make_video(make_user())
        draft_copy = make_video(make_user(), status=Video.Status.DRAFT)
        for video in (original, copy, draft_copy):
            fingerprint(video, self.frames)

        response = self.act(action='block_video', video_id=str(original.id))

        self.assertEqual(response.json()['action']['metadata']['reuploads_held'], 1)
        copy.refresh_from_db()
        draft_copy.refresh_from_db()
        self.assertEqual(copy.status, Video.Status.HELD)
        self.assertEqual(draft_copy.status, Video.Status.DRAFT)

    def test_queue_shows_automatic_signals(self):
        video = self.held_video(Video.Status.PUBLISHED)
        row = client_for(self.moderator).get('/api/v1/moderation/queue/').json()['results'][0]
        self.assertEqual(row['target']['id'], str(video.id))
        self.assertEqual(row['automatic_signals'][0]['signal'], 'reupload_of_blocked')
        self.assertEqual(row['target']['status'], 'held')


class DuplicateTests(TestCase):

    def test_copy_of_other_creators_video_is_queued_not_held(self):
        frames = hashes(30)
        original = make_video(make_user())
        fingerprint(original, frames)
        copier = make_user()
        copy = make_video(copier, status=Video.Status.READY, published_at=None)

        with mock.patch(COMPUTE, return_value=frames):
            response = client_for(copier).post(f'/api/v1/videos/{copy.id}/publish/')

        self.assertEqual(response.json()['status'], 'published')
        flag = ContentReport.objects.get(video=copy)
        self.assertEqual((flag.signal, flag.reason), ('duplicate_of_other_creator', 'copyright'))

    def test_own_duplicate_is_ignored(self):
        frames = hashes(31)
        creator = make_user()
        fingerprint(make_video(creator), frames)
        mine = make_video(creator, status=Video.Status.READY, published_at=None)
        with mock.patch(COMPUTE, return_value=frames):
            check_video(mine)
        self.assertFalse(ContentReport.objects.exists())


class TextSignalTests(TestCase):

    def test_check_text(self):
        signals = lambda text: [s for s, _ in text_checks.check_text(text)]  # noqa: E731
        self.assertEqual(signals('Great video, thanks!'), [])
        self.assertEqual(signals('see https://example.com for more'), [])
        self.assertEqual(signals('free money at bit.ly/xyz'), ['spam_links'])
        self.assertEqual(signals('visit a.com and b.net'), ['spam_links'])
        self.assertEqual(signals('call 0803 123 4567 now'), ['contact_spam'])
        self.assertEqual(signals('whatsapp +2348031234567'), ['contact_spam'])
        with override_settings(MODERATION_BANNED_TERMS=['scamword']):
            self.assertEqual(signals('this is a SCAMWORD here'), ['banned_term'])
            self.assertEqual(signals('scamwords is fine'), [])

    def test_spam_comment_goes_to_queue(self):
        video = make_video(make_user())
        spammer = make_user()
        client_for(spammer).post(f'/api/v1/videos/{video.id}/comments/',
                                 {'content': 'earn daily bit.ly/abc'}, format='json')
        client_for(spammer).post(f'/api/v1/videos/{video.id}/comments/',
                                 {'content': 'nice one'}, format='json')

        flag = ContentReport.objects.get()
        self.assertEqual((flag.source, flag.target_type, flag.signal),
                         ('auto', 'comment', 'spam_links'))
        self.assertEqual(Comment.objects.filter(is_deleted=False).count(), 2)  # not hidden

    def test_video_text_checked_on_publish(self):
        creator = make_user()
        video = make_video(creator, status=Video.Status.READY, published_at=None,
                           description='DM me on whatsapp 08031234567')
        with mock.patch(COMPUTE, return_value=hashes(40)):
            client_for(creator).post(f'/api/v1/videos/{video.id}/publish/')
        self.assertEqual(ContentReport.objects.get(video=video).signal, 'contact_spam')

    def test_chat_rejects_links_and_numbers(self):
        self.assertFalse(text_checks.allowed_in_chat('join www.example.com'))
        self.assertFalse(text_checks.allowed_in_chat('call 08031234567'))
        self.assertTrue(text_checks.allowed_in_chat('this stream is great'))


class UploadLimitTests(TestCase):

    @mock.patch('videos.limits.cloudinary.api.usage',
                return_value={'media_limits': {'video_max_size_bytes': 104857600}})
    def test_signed_params_report_real_limit(self, _usage):
        from django.core.cache import cache
        cache.clear()
        data = client_for(make_user()).get('/api/v1/videos/upload/signed-params/').json()
        self.assertEqual(data['max_file_size'], 104857600)

    def test_fallback_when_cloudinary_unreadable(self):
        from django.core.cache import cache
        from videos.limits import max_video_bytes
        cache.clear()
        with mock.patch('videos.limits.cloudinary.api.usage', side_effect=RuntimeError('down')), \
                self.assertLogs('videos.limits', level='ERROR'):
            self.assertEqual(max_video_bytes(), 100 * 1024 * 1024)

    @mock.patch('videos.limits.max_video_bytes', return_value=1000)
    def test_server_upload_over_limit_is_refused_before_cloudinary(self, _limit):
        from django.core.files.uploadedfile import SimpleUploadedFile
        with mock.patch('videos.cloudinary_service.cloudinary.uploader.upload_large') as upload:
            response = client_for(make_user()).post('/api/v1/videos/upload/', {
                'title': 'big', 'video_file': SimpleUploadedFile(
                    'v.mp4', b'0' * 2000, content_type='video/mp4')}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('File too large', str(response.content))
        upload.assert_not_called()

    def test_auto_thumbnail(self):
        from videos.cloudinary_service import generate_thumbnail_url
        self.assertIn('so_auto', generate_thumbnail_url('abia_stream/videos/x'))
        self.assertIn('so_5', generate_thumbnail_url('abia_stream/videos/x', 5))
