import uuid
from datetime import timedelta
from unittest import mock

import cloudinary.exceptions
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import TestCase
from django.utils import timezone

from abiastream.testing import client_for, make_user, make_video
from accounts.models import User
from creator_channels.models import CreatorChannel
from livestreams import cloudinary_live
from livestreams.models import ChatMessage, LiveStream, StreamViewer
from livestreams.services import sync_all
from moderation.models import ModerationAction
from notifications.models import Notification
from subscriptions.models import Subscription
from videos.models import Video


class FakeCloudinaryLive:
    """In-memory stand-in for the Live Streaming API, shaped like the real responses."""

    def __init__(self):
        self.streams = {}
        self.calls = []
        self.fail = False

    def _check(self, name):
        self.calls.append(name)
        if self.fail:
            raise cloudinary_live.LiveStreamingError('cloudinary down')

    def create_stream(self, name, idle_timeout_sec, max_runtime_sec):
        self._check('create')
        sid = uuid.uuid4().hex
        self.streams[sid] = {
            'id': sid, 'name': name, 'status': 'idle',
            'input': {'type': 'rtmp', 'uri': 'rtmp://live.cloudinary.com/streams',
                      'stream_key': uuid.uuid4().hex},
            'outputs': [
                {'id': 'hls1', 'type': 'hls',
                 'uri': f'https://res.cloudinary.com/test-cloud/video/live/live_stream_{sid}_hls.m3u8'},
                {'id': 'arc1', 'type': 'archive', 'public_id': f'live_stream_{sid}_archive'},
            ],
        }
        return self.streams[sid]

    def get_stream(self, sid):
        self._check('get')
        if sid not in self.streams:
            raise cloudinary_live.LiveStreamNotFound(sid)
        return self.streams[sid]

    def idle_stream(self, sid):
        self._check('idle')
        self.streams[sid]['status'] = 'idle'

    def delete_stream(self, sid):
        self._check('delete')
        if self.streams.pop(sid, None) is None:
            raise cloudinary_live.LiveStreamNotFound(sid)

    def delete_output(self, sid, oid):
        self._check('delete_output')
        self.streams[sid]['outputs'] = [o for o in self.streams[sid]['outputs'] if o['id'] != oid]

    # Test helpers
    def set_status(self, stream, status):
        self.streams[stream.cloudinary_stream_id]['status'] = status


def verified_creator(**extra):
    user = make_user(role=User.Role.CREATOR,
                     verification_status=User.VerificationStatus.APPROVED, **extra)
    CreatorChannel.objects.create(user=user, channel_name=f'Chan {user.id.hex[:6]}',
                                  channel_slug=f'chan-{user.id.hex[:6]}')
    return user


def archive_asset(public_id):
    return {'public_id': public_id, 'version': 3, 'duration': 754.2, 'width': 1280,
            'height': 720, 'format': 'mp4', 'bytes': 12345,
            'secure_url': f'https://res.cloudinary.com/test-cloud/video/upload/v3/{public_id}.mp4'}


class LiveTestCase(TestCase):

    def setUp(self):
        self.cloud = FakeCloudinaryLive()
        for name in ('create_stream', 'get_stream', 'idle_stream', 'delete_stream', 'delete_output'):
            patcher = mock.patch.object(cloudinary_live, name, getattr(self.cloud, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.resource = mock.patch('livestreams.services.cloudinary.api.resource',
                                   side_effect=cloudinary.exceptions.NotFound('not yet'))
        self.resource_mock = self.resource.start()
        self.addCleanup(self.resource.stop)
        self.creator = verified_creator()
        self.owner = client_for(self.creator)

    def create(self, **body):
        body.setdefault('title', 'Friday night live')
        response = self.owner.post('/api/v1/livestreams/', body, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return LiveStream.objects.get(id=response.json()['id']), response.json()

    def go_live(self, stream):
        self.cloud.set_status(stream, 'active')
        LiveStream.objects.filter(id=stream.id).update(status_checked_at=None)
        return client_for().get(f'/api/v1/livestreams/{stream.id}/').json()

    def archive_ready(self, stream):
        self.resource_mock.side_effect = None
        self.resource_mock.return_value = archive_asset(stream.cloudinary_archive_public_id)


class CreateTests(LiveTestCase):

    def test_verified_creator_gets_encoder_settings(self):
        stream, data = self.create(description='Q&A', chat_enabled=True)

        self.assertEqual(data['status'], 'scheduled')
        self.assertEqual(data['rtmp_url'], 'rtmp://live.cloudinary.com/streams')
        self.assertTrue(data['stream_key'])
        self.assertIsNone(data['playback_url'])
        self.assertTrue(stream.save_recording)
        self.assertTrue(stream.cloudinary_archive_public_id.endswith('_archive'))

    def test_unverified_or_channelless_users_refused(self):
        unverified = make_user(role=User.Role.CREATOR)
        CreatorChannel.objects.create(user=unverified, channel_name='U', channel_slug='u')
        no_channel = make_user(verification_status=User.VerificationStatus.APPROVED)
        for user in (unverified, no_channel):
            response = client_for(user).post('/api/v1/livestreams/', {'title': 'x'}, format='json')
            self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(self.cloud.calls, [])
        self.assertEqual(client_for().post('/api/v1/livestreams/', {'title': 'x'},
                                           format='json').status_code, 401)

    def test_no_recording_removes_archive_output(self):
        stream, data = self.create(save_recording=False)
        self.assertFalse(stream.save_recording)
        self.assertIsNone(stream.cloudinary_archive_public_id)
        outputs = self.cloud.streams[stream.cloudinary_stream_id]['outputs']
        self.assertEqual([o['type'] for o in outputs], ['hls'])

    def test_cloudinary_outage_is_a_clean_error(self):
        self.cloud.fail = True
        response = self.owner.post('/api/v1/livestreams/', {'title': 'x'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('temporarily unavailable', response.json()['detail'])
        self.assertFalse(LiveStream.objects.exists())

    def test_db_failure_does_not_orphan_cloud_stream(self):
        with mock.patch.object(LiveStream.objects, 'create', side_effect=RuntimeError('db')):
            with self.assertRaises(RuntimeError):
                self.owner.post('/api/v1/livestreams/', {'title': 'x'}, format='json')
        self.assertEqual(self.cloud.streams, {})

    def test_open_stream_limit(self):
        for _ in range(5):
            self.create()
        response = self.owner.post('/api/v1/livestreams/', {'title': 'x'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_key_hidden_from_others(self):
        stream, _ = self.create()
        for client in (client_for(), client_for(make_user())):
            data = client.get(f'/api/v1/livestreams/{stream.id}/').json()
            self.assertNotIn('stream_key', data)
            self.assertNotIn('rtmp_url', data)
        listed = client_for().get('/api/v1/livestreams/').json()['results'][0]
        self.assertNotIn('stream_key', listed)


class LifecycleTests(LiveTestCase):

    def test_goes_live_notifies_subscribers_and_exposes_playback(self):
        fan = make_user()
        Subscription.objects.create(subscriber=fan, channel=self.creator.channel)
        stream, _ = self.create()

        data = self.go_live(stream)

        self.assertEqual(data['status'], 'live')
        self.assertTrue(data['playback_url'].endswith('_hls.m3u8'))
        self.assertIsNotNone(data['actual_start_time'])
        note = Notification.objects.get(user=fan)
        self.assertEqual(note.notification_type, 'livestream_started')
        self.assertEqual(note.data, {'livestream_id': str(stream.id)})
        # Second refresh does not notify again.
        self.go_live(stream)
        self.assertEqual(Notification.objects.filter(user=fan).count(), 1)

    def test_status_checks_are_rate_limited(self):
        stream, _ = self.create()
        LiveStream.objects.filter(id=stream.id).update(status_checked_at=None)
        client = client_for()
        for _ in range(3):
            client.get(f'/api/v1/livestreams/{stream.id}/')
        self.assertEqual(self.cloud.calls.count('get'), 1)

    def test_cloudinary_outage_during_refresh_keeps_last_state(self):
        stream, _ = self.create()
        self.go_live(stream)
        self.cloud.fail = True
        LiveStream.objects.filter(id=stream.id).update(status_checked_at=None)
        response = client_for().get(f'/api/v1/livestreams/{stream.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'live')

    def test_encoder_disconnect_ends_stream(self):
        stream, _ = self.create()
        self.go_live(stream)
        self.cloud.set_status(stream, 'idle')
        LiveStream.objects.filter(id=stream.id).update(status_checked_at=None)

        data = client_for().get(f'/api/v1/livestreams/{stream.id}/').json()

        self.assertEqual(data['status'], 'ended')
        self.assertIsNone(data['playback_url'])
        self.assertIsNotNone(data['actual_end_time'])

    def test_owner_ends_and_recording_becomes_a_draft_video(self):
        stream, _ = self.create()
        self.go_live(stream)

        ended = self.owner.post(f'/api/v1/livestreams/{stream.id}/end/').json()
        self.assertEqual(ended['status'], 'ended')
        self.assertIn('idle', self.cloud.calls)
        self.assertIsNone(ended['recording_video_id'])  # archive not written yet

        self.archive_ready(stream)
        data = self.owner.get(f'/api/v1/livestreams/{stream.id}/').json()

        video = Video.objects.get(id=data['recording_video_id'])
        self.assertEqual((video.status, video.creator_id, video.title, video.duration_seconds),
                         (Video.Status.READY, self.creator.id, 'Friday night live', 754))
        # Not published, so the public doesn't see it.
        self.assertIsNone(client_for().get(f'/api/v1/livestreams/{stream.id}/').json()
                          ['recording_video_id'])
        # Idempotent.
        self.owner.get(f'/api/v1/livestreams/{stream.id}/')
        self.assertEqual(Video.objects.filter(cloudinary_public_id=video.cloudinary_public_id).count(), 1)

    def test_publish_recording_goes_straight_to_channel(self):
        stream, _ = self.create(publish_recording=True)
        self.go_live(stream)
        self.owner.post(f'/api/v1/livestreams/{stream.id}/end/')
        self.archive_ready(stream)
        self.owner.get(f'/api/v1/livestreams/{stream.id}/')

        public = client_for().get(f'/api/v1/livestreams/{stream.id}/').json()
        video = Video.objects.get(id=public['recording_video_id'])
        self.assertEqual(video.status, Video.Status.PUBLISHED)
        self.assertIsNotNone(video.published_at)

    def test_cancel_only_before_live(self):
        stream, _ = self.create()
        cloud_id = stream.cloudinary_stream_id
        data = self.owner.post(f'/api/v1/livestreams/{stream.id}/cancel/').json()
        self.assertEqual(data['status'], 'cancelled')
        self.assertNotIn(cloud_id, self.cloud.streams)
        # Hidden from the public.
        self.assertEqual(client_for().get(f'/api/v1/livestreams/{stream.id}/').status_code, 404)

        live_stream, _ = self.create()
        self.go_live(live_stream)
        response = self.owner.post(f'/api/v1/livestreams/{live_stream.id}/cancel/')
        self.assertEqual(response.status_code, 400)

    def test_only_owner_can_control(self):
        stream, _ = self.create()
        other = client_for(make_user())
        for path in ('end/', 'cancel/'):
            self.assertEqual(other.post(f'/api/v1/livestreams/{stream.id}/{path}').status_code, 404)
        self.assertEqual(other.patch(f'/api/v1/livestreams/{stream.id}/', {'title': 'x'},
                                     format='json').status_code, 404)

    def test_edit_before_and_after(self):
        stream, _ = self.create()
        data = self.owner.patch(f'/api/v1/livestreams/{stream.id}/',
                                {'title': 'New title', 'chat_enabled': False}, format='json').json()
        self.assertEqual((data['title'], data['chat_enabled']), ('New title', False))

        self.go_live(stream)
        self.owner.post(f'/api/v1/livestreams/{stream.id}/end/')
        self.assertEqual(self.owner.patch(f'/api/v1/livestreams/{stream.id}/', {'title': 'late'},
                                          format='json').status_code, 400)
        ok = self.owner.patch(f'/api/v1/livestreams/{stream.id}/', {'publish_recording': True},
                              format='json')
        self.assertEqual(ok.status_code, 200)

    def test_list_live_first(self):
        upcoming, _ = self.create(title='later')
        live, _ = self.create(title='now')
        self.go_live(live)
        LiveStream.objects.update(status_checked_at=timezone.now())

        titles = [s['title'] for s in client_for().get('/api/v1/livestreams/').json()['results']]
        self.assertEqual(titles, ['now', 'later'])
        only_live = client_for().get('/api/v1/livestreams/', {'status': 'live'}).json()['results']
        self.assertEqual([s['title'] for s in only_live], ['now'])
        mine = self.owner.get('/api/v1/livestreams/me/').json()['results']
        self.assertTrue(all('stream_key' in s for s in mine))


class ViewerTests(LiveTestCase):

    def beat(self, stream, session):
        return client_for().post(f'/api/v1/livestreams/{stream.id}/heartbeat/',
                                 {'session_id': str(session)}, format='json')

    def test_counts_distinct_active_sessions(self):
        stream, _ = self.create()
        self.go_live(stream)
        a, b = uuid.uuid4(), uuid.uuid4()

        self.assertEqual(self.beat(stream, a).json()['viewer_count'], 1)
        self.assertEqual(self.beat(stream, a).json()['viewer_count'], 1)
        self.assertEqual(self.beat(stream, b).json()['viewer_count'], 2)

        # a goes quiet for over a minute.
        StreamViewer.objects.filter(session_id=a).update(
            left_at=timezone.now() - timedelta(minutes=2))
        self.assertEqual(self.beat(stream, b).json()['viewer_count'], 1)

        stream.refresh_from_db()
        self.assertEqual((stream.viewer_count, stream.max_concurrent_viewers), (1, 2))

    def test_not_live_reports_zero(self):
        stream, _ = self.create()
        data = self.beat(stream, uuid.uuid4()).json()
        self.assertEqual(data, {'status': 'scheduled', 'viewer_count': 0})
        self.assertFalse(StreamViewer.objects.exists())

    def test_session_required(self):
        stream, _ = self.create()
        self.go_live(stream)
        response = client_for().post(f'/api/v1/livestreams/{stream.id}/heartbeat/', {}, format='json')
        self.assertEqual(response.status_code, 400)


class ChatTests(LiveTestCase):

    def setUp(self):
        super().setUp()
        self.stream, _ = self.create()
        self.go_live(self.stream)
        self.viewer = make_user()
        self.url = f'/api/v1/livestreams/{self.stream.id}/chat/'

    def say(self, user, content='hello'):
        return client_for(user).post(self.url, {'content': content}, format='json')

    def test_post_and_poll(self):
        first = self.say(self.viewer, 'first').json()
        # Coarse clocks (Windows, ~15 ms) can give both the same timestamp;
        # make the order unambiguous as it is in production.
        ChatMessage.objects.filter(id=first['id']).update(
            created_at=timezone.now() - timedelta(seconds=1))
        self.say(self.viewer, 'second')

        everything = client_for().get(self.url).json()
        self.assertTrue(everything['chat_enabled'])
        self.assertEqual([m['content'] for m in everything['messages']], ['first', 'second'])
        self.assertNotIn('email', everything['messages'][0]['user'])

        newer = client_for().get(self.url, {'after': first['id']}).json()['messages']
        self.assertEqual([m['content'] for m in newer], ['second'])

    def test_rules(self):
        self.assertEqual(client_for().post(self.url, {'content': 'x'}, format='json').status_code, 401)
        self.assertEqual(self.say(self.viewer, '   ').status_code, 400)
        self.assertEqual(self.say(self.viewer, 'x' * 501).status_code, 400)

        LiveStream.objects.filter(id=self.stream.id).update(chat_enabled=False)
        self.assertEqual(self.say(self.viewer).status_code, 400)

        LiveStream.objects.filter(id=self.stream.id).update(chat_enabled=True, status='ended')
        self.assertEqual(self.say(self.viewer).status_code, 400)

    def test_delete_permissions(self):
        mine = self.say(self.viewer).json()['id']
        theirs = self.say(make_user()).json()['id']
        another = self.say(make_user()).json()['id']

        self.assertEqual(client_for(self.viewer).delete(
            f'/api/v1/livestreams/chat/{theirs}/').status_code, 403)
        self.assertEqual(client_for(self.viewer).delete(
            f'/api/v1/livestreams/chat/{mine}/').status_code, 200)
        self.assertEqual(self.owner.delete(f'/api/v1/livestreams/chat/{theirs}/').status_code, 200)

        moderator = make_user(role=User.Role.MODERATOR)
        self.assertEqual(client_for(moderator).delete(
            f'/api/v1/livestreams/chat/{another}/').status_code, 200)
        self.assertTrue(ModerationAction.objects.filter(
            action='remove_chat_message', chat_message_id=another).exists())

        remaining = client_for().get(self.url).json()['messages']
        self.assertEqual(remaining, [])

    def test_websocket_receives_chat(self):
        from abiastream.asgi import application

        async def scenario():
            communicator = WebsocketCommunicator(application, f'/ws/livestream/{self.stream.id}/')
            communicator.scope['headers'] = [(b'origin', b'http://testserver'),
                                             (b'host', b'testserver')]
            connected, _ = await communicator.connect()
            assert connected
            from asgiref.sync import sync_to_async
            await sync_to_async(self.say)(self.viewer, 'over the wire')
            event = await communicator.receive_json_from(timeout=3)
            await communicator.disconnect()
            return event

        event = async_to_sync(scenario)()
        self.assertEqual(event['type'], 'chat_message')
        self.assertEqual(event['message']['content'], 'over the wire')


class ModerationTests(LiveTestCase):

    def test_moderator_ends_stream_recording_kept_unpublished(self):
        stream, _ = self.create(publish_recording=True)
        self.go_live(stream)
        moderator = make_user(role=User.Role.MODERATOR)

        response = client_for(moderator).post('/api/v1/moderation/actions/', {
            'action': 'end_livestream', 'livestream_id': str(stream.id), 'note': 'nudity',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.content)
        stream.refresh_from_db()
        self.assertEqual((stream.status, stream.publish_recording), ('ended', False))
        self.assertTrue(Notification.objects.filter(
            user=self.creator, notification_type='livestream_ended_by_moderator').exists())
        self.archive_ready(stream)
        self.owner.get(f'/api/v1/livestreams/{stream.id}/')
        stream.refresh_from_db()
        self.assertEqual(stream.recording_video.status, Video.Status.READY)

    def test_regular_user_cannot(self):
        stream, _ = self.create()
        self.go_live(stream)
        response = client_for(make_user()).post('/api/v1/moderation/actions/', {
            'action': 'end_livestream', 'livestream_id': str(stream.id)}, format='json')
        self.assertEqual(response.status_code, 403)


class HousekeepingTests(LiveTestCase):

    def test_sync_all(self):
        # Abandoned: scheduled two days ago, never started.
        abandoned, _ = self.create(title='abandoned')
        LiveStream.objects.filter(id=abandoned.id).update(
            scheduled_start_time=timezone.now() - timedelta(days=2))
        # Finished, archive now available, ended long enough ago to delete.
        done, _ = self.create(title='done')
        self.go_live(done)
        self.owner.post(f'/api/v1/livestreams/{done.id}/end/')
        LiveStream.objects.filter(id=done.id).update(
            actual_end_time=timezone.now() - timedelta(minutes=30))
        self.archive_ready(done)
        cloud_id = done.cloudinary_stream_id

        counts = sync_all()

        self.assertEqual(LiveStream.objects.get(id=abandoned.id).status, 'cancelled')
        done.refresh_from_db()
        self.assertIsNotNone(done.recording_video_id)
        self.assertIsNone(done.cloudinary_stream_id)
        self.assertNotIn(cloud_id, self.cloud.streams)
        self.assertEqual((counts['abandoned'], counts['recordings'], counts['cloud_deleted']),
                         (1, 1, 1))

    def test_stream_deleted_on_cloudinary_marks_failed(self):
        stream, _ = self.create()
        del self.cloud.streams[stream.cloudinary_stream_id]
        sync_all()
        self.assertEqual(LiveStream.objects.get(id=stream.id).status, 'failed')

    def test_command_and_task(self):
        from io import StringIO
        from django.core.management import call_command
        from livestreams.tasks import sync_livestreams
        out = StringIO()
        call_command('sync_livestreams', stdout=out)
        self.assertIn('refreshed', out.getvalue())
        sync_livestreams.delay()


class RecordingWithoutArchiveTests(LiveTestCase):

    def test_no_recording_stream_is_deleted_on_end(self):
        stream, _ = self.create(save_recording=False)
        self.go_live(stream)
        cloud_id = stream.cloudinary_stream_id
        self.owner.post(f'/api/v1/livestreams/{stream.id}/end/')
        stream.refresh_from_db()
        self.assertIsNone(stream.cloudinary_stream_id)
        self.assertNotIn(cloud_id, self.cloud.streams)
        self.assertIsNone(stream.recording_video_id)
        make_video(self.creator)  # unrelated videos unaffected


class CloudinaryRequestTests(TestCase):
    """The real request builder (the other tests use a fake Cloudinary)."""

    def test_max_runtime_capped_at_cloudinary_limit(self):
        from unittest import mock as _mock
        ok = _mock.Mock(status_code=200, ok=True, json=lambda: {'data': {'id': 'x', 'outputs': []}})
        with _mock.patch.object(cloudinary_live.requests, 'request', return_value=ok) as request:
            cloudinary_live.create_stream('abiastream-test', idle_timeout_sec=120, max_runtime_sec=4 * 3600)
        self.assertEqual(request.call_args.kwargs['json']['max_runtime_sec'], 3 * 3600)

    def test_default_setting_within_limit(self):
        from django.conf import settings
        self.assertLessEqual(settings.LIVESTREAM_MAX_RUNTIME_SECONDS,
                             cloudinary_live.MAX_RUNTIME_WITH_ARCHIVE_SEC)
