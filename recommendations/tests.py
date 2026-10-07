from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from abiastream.testing import make_user, make_video, client_for
from playback.models import WatchHistory
from recommendations.models import RelatedVideo


def watched(user, *videos):
    for video in videos:
        WatchHistory.objects.create(
            user=user, video=video, last_watched_at=timezone.now(),
            watch_progress_seconds=60,
        )


class BuildRelatedVideosTests(TestCase):

    def test_co_watched_videos_become_related(self):
        creator = make_user()
        a, b, c = (make_video(creator, title=t) for t in 'abc')
        for _ in range(3):
            watched(make_user(), a, b)
        watched(make_user(), a, c)  # below MIN_CO_VIEWS

        call_command('build_related_videos', stdout=StringIO())

        self.assertEqual(
            list(RelatedVideo.objects.filter(video=a).values_list('related_id', flat=True)),
            [b.id],
        )
        self.assertTrue(RelatedVideo.objects.filter(video=b, related=a).exists())

        response = client_for().get(f'/api/v1/videos/{a.id}/related/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([v['id'] for v in response.json()], [str(b.id)])

    def test_empty_when_nothing_computed(self):
        video = make_video(make_user())
        response = client_for().get(f'/api/v1/videos/{video.id}/related/')
        self.assertEqual(response.json(), [])


class RebuildTaskTests(TestCase):

    def test_task_rebuilds_and_prunes(self):
        creator = make_user()
        a, b, stale = (make_video(creator) for _ in range(3))
        for _ in range(3):
            watched(make_user(), a, b)
        RelatedVideo.objects.create(
            video=a, related=stale, score=0.9,
            computed_at=timezone.now() - timedelta(days=2))

        from recommendations.tasks import rebuild_related_videos
        rebuild_related_videos.delay()

        self.assertEqual(
            set(RelatedVideo.objects.filter(video=a).values_list('related_id', flat=True)),
            {b.id},
        )
