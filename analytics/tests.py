import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from abiastream.testing import make_user, make_video, client_for
from accounts.models import User
from creator_channels.models import CreatorChannel
from events.models import Event
from moderation.models import ContentReport
from playback.models import ViewLog
from subscriptions.models import Subscription


class AccessTests(TestCase):

    def test_admin_only(self):
        for path in ('overview', 'daily', 'top-videos', 'search'):
            url = f'/api/v1/analytics/{path}/'
            self.assertEqual(client_for().get(url).status_code, 401, url)
            self.assertEqual(client_for(make_user()).get(url).status_code, 403, url)
            self.assertEqual(
                client_for(make_user(role=User.Role.MODERATOR)).get(url).status_code, 403, url)
            self.assertEqual(
                client_for(make_user(role=User.Role.ADMIN)).get(url).status_code, 200, url)

    def test_bad_period(self):
        admin = make_user(role=User.Role.ADMIN)
        response = client_for(admin).get('/api/v1/analytics/overview/', {'period': '5y'})
        self.assertEqual(response.status_code, 400)


class NumbersTests(TestCase):

    def setUp(self):
        self.admin = make_user(role=User.Role.ADMIN)
        self.client = client_for(self.admin)
        self.creator = make_user(role=User.Role.CREATOR)
        self.video = make_video(self.creator, title='popular')
        now = timezone.now()
        ViewLog.objects.create(video=self.video, timestamp=now, completed=True,
                               watch_duration_seconds=3600, session_id=uuid.uuid4())
        ViewLog.objects.create(video=self.video, timestamp=now, completed=False,
                               watch_duration_seconds=0, session_id=uuid.uuid4())
        # Previous period, for the % change.
        ViewLog.objects.create(video=self.video, timestamp=now - timedelta(days=10))

    def test_overview(self):
        data = self.client.get('/api/v1/analytics/overview/', {'period': '7d'}).json()

        self.assertEqual(data['users']['total'], 2)
        self.assertEqual(data['users']['by_role'], {'admin': 1, 'creator': 1})
        self.assertEqual(data['videos']['by_status'], {'published': 1})
        eng = data['engagement']
        self.assertEqual((eng['views'], eng['completed'], eng['completion_rate']), (2, 1, 50.0))
        self.assertEqual(eng['watch_hours'], 1.0)
        self.assertEqual(eng['sessions'], 2)
        self.assertEqual(eng['views_change_percent'], 100.0)
        self.assertEqual(data['moderation']['open_reports'], 0)

    def test_daily_series_is_gap_free(self):
        data = self.client.get('/api/v1/analytics/daily/', {'period': '7d'}).json()
        self.assertEqual(len(data['series']), 8)  # 7 days back through today
        self.assertEqual(data['series'][-1]['views'], 2)
        self.assertEqual(sum(day['views'] for day in data['series']), 2)

    def test_top_videos(self):
        data = self.client.get('/api/v1/analytics/top-videos/', {'period': '7d'}).json()
        self.assertEqual(data['results'][0]['title'], 'popular')
        self.assertEqual(data['results'][0]['views'], 2)
        self.assertEqual(data['results'][0]['completion_rate'], 50.0)

    def test_search_insights(self):
        session = uuid.uuid4()
        for query, count in [('Jollof', 3), ('jollof', 0), ('owambe', 0)]:
            Event.objects.create(session_id=session, event_type='search',
                                 payload={'query': query, 'result_count': count})

        data = self.client.get('/api/v1/analytics/search/').json()

        self.assertEqual(data['total_searches'], 3)
        self.assertEqual(data['top_queries'][0], {'query': 'jollof', 'count': 2})
        self.assertEqual(data['zero_result_queries'],
                         [{'query': 'jollof', 'count': 1}, {'query': 'owambe', 'count': 1}])

    def test_open_reports_counted(self):
        ContentReport.objects.create(reporter=make_user(), target_type='video',
                                     video=self.video, reason='spam')
        data = self.client.get('/api/v1/analytics/overview/').json()
        self.assertEqual(data['moderation']['open_reports'], 1)


class CreatorDashboardTests(TestCase):

    def test_new_subscribers_last_28_days(self):
        creator = make_user(role=User.Role.CREATOR)
        channel = CreatorChannel.objects.create(
            user=creator, channel_name='Chan', channel_slug='chan')
        Subscription.objects.create(subscriber=make_user(), channel=channel)
        old = Subscription.objects.create(subscriber=make_user(), channel=channel)
        Subscription.objects.filter(id=old.id).update(
            created_at=timezone.now() - timedelta(days=40))

        data = client_for(creator).get('/api/v1/channels/me/dashboard/').json()
        self.assertEqual(data['summary']['new_subscribers_last_28_days'], 1)
