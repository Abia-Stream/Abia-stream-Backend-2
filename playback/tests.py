import uuid
from datetime import datetime, timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from abiastream.testing import make_user, make_video, client_for
from playback.models import ViewLog, WatchHistory
from playback.tasks import ensure_view_log_partitions


class RecordViewTests(TestCase):

    def test_records_view_now(self):
        """Regression: needs a view_logs partition covering the current month (sql/005)."""
        video = make_video(make_user())
        response = client_for().post('/api/v1/playback/view/', {
            'video_id': str(video.id), 'watch_duration_seconds': 30,
        }, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['counted'])
        self.assertEqual(ViewLog.objects.filter(video=video).count(), 1)
        video.refresh_from_db()
        self.assertEqual(video.views_count, 1)

    def test_repeat_view_in_same_session_not_counted(self):
        video = make_video(make_user())
        session = str(uuid.uuid4())
        client = client_for()
        payload = {'video_id': str(video.id), 'session_id': session}

        client.post('/api/v1/playback/view/', payload, format='json')
        second = client.post('/api/v1/playback/view/', payload, format='json')

        self.assertFalse(second.json()['counted'])
        self.assertEqual(ViewLog.objects.filter(video=video).count(), 2)
        video.refresh_from_db()
        self.assertEqual(video.views_count, 1)


class CreatorTotalViewsTests(TestCase):

    def test_profile_total_views_counts_once_per_session_from_null(self):
        from profiles.models import Profile
        creator = make_user()
        profile = Profile.objects.create(user=creator)  # total_views starts NULL
        video = make_video(creator)
        client = client_for()
        payload = {'video_id': str(video.id), 'session_id': str(uuid.uuid4())}

        client.post('/api/v1/playback/view/', payload, format='json')
        client.post('/api/v1/playback/view/', payload, format='json')  # refresh
        client.post('/api/v1/playback/view/', {'video_id': str(video.id)}, format='json')

        profile.refresh_from_db()
        self.assertEqual(profile.total_views, 2)


class ProgressTests(TestCase):

    def test_progress_creates_history_and_autocompletes(self):
        user = make_user()
        video = make_video(make_user(), duration_seconds=100)
        response = client_for(user).post('/api/v1/playback/progress/', {
            'video_id': str(video.id), 'watch_progress_seconds': 95,
        }, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        entry = WatchHistory.objects.get(user=user, video=video)
        self.assertTrue(entry.completed)


PARTITION_NOW = 'playback.management.commands.ensure_view_log_partitions.timezone.now'


def partitions():
    with connection.cursor() as cur:
        cur.execute(
            "select c.relname from pg_inherits i join pg_class c on c.oid = i.inhrelid "
            "join pg_class p on p.oid = i.inhparent where p.relname = 'view_logs'")
        return {r[0] for r in cur.fetchall()}


class ViewLogPartitionTests(TestCase):

    @mock.patch(PARTITION_NOW, return_value=datetime(2026, 11, 15, tzinfo=dt_timezone.utc))
    def test_creates_upcoming_months_idempotently(self, _now):
        call_command('ensure_view_log_partitions', months_ahead=3, stdout=StringIO())
        self.assertTrue({'view_logs_2027_01', 'view_logs_2027_02'} <= partitions())

        out = StringIO()
        call_command('ensure_view_log_partitions', months_ahead=3, stdout=out)
        self.assertNotIn('created', out.getvalue())

        # Rows land in the new partition, not the default.
        video = make_video(make_user())
        ViewLog.objects.create(video=video, timestamp=datetime(2027, 1, 31, 23, 30,
                                                              tzinfo=dt_timezone.utc))
        with connection.cursor() as cur:
            cur.execute('select count(*) from view_logs_2027_01')
            self.assertEqual(cur.fetchone()[0], 1)

    @mock.patch(PARTITION_NOW, return_value=datetime(2027, 2, 1, tzinfo=dt_timezone.utc))
    def test_reports_conflict_with_rows_in_default_partition(self, _now):
        video = make_video(make_user())
        ViewLog.objects.create(video=video, timestamp=datetime(2027, 3, 10,
                                                              tzinfo=dt_timezone.utc))
        err = StringIO()
        with self.assertRaises(SystemExit):
            call_command('ensure_view_log_partitions', months_ahead=2,
                         stdout=StringIO(), stderr=err)
        self.assertIn('view_logs_2027_03', err.getvalue())
        # The non-conflicting months were still created.
        self.assertTrue({'view_logs_2027_02', 'view_logs_2027_04'} <= partitions())

    @mock.patch(PARTITION_NOW, return_value=datetime(2026, 12, 1, tzinfo=dt_timezone.utc))
    def test_celery_task_runs(self, _now):
        ensure_view_log_partitions.delay()
        self.assertIn('view_logs_2027_01', partitions())
