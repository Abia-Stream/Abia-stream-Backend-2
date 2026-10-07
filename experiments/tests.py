import uuid

from django.test import TestCase

from abiastream.testing import make_user, client_for
from experiments.models import Experiment, ExperimentAssignment


class VariantTests(TestCase):

    def setUp(self):
        Experiment.objects.create(key='feed_v2', variants=['control', 'treatment'],
                                  is_active=True)
        Experiment.objects.create(key='off', is_active=False)

    def test_signed_in_assignment_is_sticky(self):
        client = client_for(make_user())
        first = client.get('/api/v1/experiments/variants/').json()
        second = client.get('/api/v1/experiments/variants/').json()

        self.assertEqual(list(first), ['feed_v2'])
        self.assertIn(first['feed_v2'], ['control', 'treatment'])
        self.assertEqual(first, second)
        self.assertEqual(ExperimentAssignment.objects.count(), 1)

    def test_anonymous_keyed_on_session(self):
        session = str(uuid.uuid4())
        client = client_for()
        client.get('/api/v1/experiments/variants/', HTTP_X_SESSION_ID=session)
        client.get('/api/v1/experiments/variants/', HTTP_X_SESSION_ID=session)
        self.assertEqual(
            ExperimentAssignment.objects.filter(session_id=session).count(), 1)
