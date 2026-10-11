import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from abiastream.testing import client_for, make_user, make_video
from events.models import Event
from videos.models import Video


def share(video, client=None, session=None, **body):
    headers = {'HTTP_X_SESSION_ID': str(session)} if session else {}
    return (client or client_for()).post(f'/api/v1/videos/{video.id}/share/', body,
                                         format='json', **headers)


class ShareTests(TestCase):

    def setUp(self):
        self.video = make_video(make_user())

    def test_counts_once_per_session_per_day(self):
        session = uuid.uuid4()
        first = share(self.video, session=session, destination='whatsapp')
        again = share(self.video, session=session, destination='copy_link')
        other = share(self.video, session=uuid.uuid4(), destination='x')

        self.assertEqual(first.json(), {'counted': True, 'shares_count': 1})
        self.assertEqual(again.json(), {'counted': False, 'shares_count': 1})
        self.assertEqual(other.json(), {'counted': True, 'shares_count': 2})
        self.assertEqual(Event.objects.filter(event_type='share').count(), 3)  # all logged

    def test_signed_in_user_counted_once_across_sessions(self):
        client = client_for(make_user())
        share(self.video, client=client, session=uuid.uuid4())
        second = share(self.video, client=client, session=uuid.uuid4())
        self.assertFalse(second.json()['counted'])

    def test_counts_again_after_a_day(self):
        session = uuid.uuid4()
        share(self.video, session=session)
        Event.objects.filter(event_type='share').update(occurred_at=timezone.now() - timedelta(hours=25))
        self.assertTrue(share(self.video, session=session).json()['counted'])

    def test_shows_in_interaction_counts(self):
        share(self.video, session=uuid.uuid4())
        counts = client_for(make_user()).get(f'/api/v1/interactions/video/{self.video.id}/counts/').json()
        self.assertEqual(counts['shares_count'], 1)

    def test_rules(self):
        self.assertEqual(share(self.video, destination='carrier-pigeon').status_code, 400)
        private = make_video(make_user(), visibility=Video.Visibility.PRIVATE)
        self.assertEqual(share(private).status_code, 404)
        draft = make_video(make_user(), status=Video.Status.DRAFT)
        self.assertEqual(share(draft).status_code, 404)

    def test_clients_cannot_send_share_events_directly(self):
        response = client_for().post('/api/v1/events/', {'events': [
            {'event_type': 'share', 'session_id': str(uuid.uuid4()), 'video_id': str(self.video.id)}]},
            format='json')
        self.assertEqual(response.status_code, 400)
