import uuid

from django.test import TestCase

from abiastream.testing import make_user, make_video, client_for
from events.models import Event


class RecordEventsTests(TestCase):

    def test_anonymous_batch_is_recorded(self):
        video = make_video(make_user())
        session = str(uuid.uuid4())
        response = client_for().post('/api/v1/events/', {'events': [
            {'event_type': 'impression', 'session_id': session, 'video_id': str(video.id)},
            {'event_type': 'play', 'session_id': session, 'video_id': str(video.id),
             'payload': {'position': 0}},
        ]}, format='json')

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['recorded'], 2)
        self.assertEqual(Event.objects.filter(session_id=session).count(), 2)

    def test_signed_in_user_is_attached(self):
        user = make_user()
        session = str(uuid.uuid4())
        client_for(user).post('/api/v1/events/', {'events': [
            {'event_type': 'video_click', 'session_id': session},
        ]}, format='json')
        self.assertEqual(Event.objects.get(session_id=session).user_id, user.id)

    def test_rejects_unknown_event_type(self):
        response = client_for().post('/api/v1/events/', {'events': [
            {'event_type': 'nope', 'session_id': str(uuid.uuid4())},
        ]}, format='json')
        self.assertEqual(response.status_code, 400)
