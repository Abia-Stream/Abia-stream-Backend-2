from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from abiastream.testing import make_user, make_video, client_for
from events.models import Event
from playback.models import ViewLog
from videos.models import Video


class VideoListTests(TestCase):

    def test_lists_only_published_public_videos(self):
        creator = make_user()
        shown = make_video(creator)
        make_video(creator, visibility=Video.Visibility.PRIVATE)
        make_video(creator, status=Video.Status.DRAFT)

        response = client_for().get('/api/v1/videos/')

        self.assertEqual(response.status_code, 200)
        ids = [v['id'] for v in response.json()['results']]
        self.assertEqual(ids, [str(shown.id)])

    def test_cloudinary_url_unchanged_for_public_video(self):
        video = make_video(make_user())
        response = client_for().get(f'/api/v1/videos/{video.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['cloudinary_url'], video.cloudinary_url)


class VideoWriteTests(TestCase):
    """Regression: search_vector is a generated column and must never be written."""

    def test_save_draft_and_publish(self):
        user = make_user()
        client = client_for(user)

        draft = client.post('/api/v1/videos/draft/', {'title': 'Draft'}, format='json')
        self.assertEqual(draft.status_code, 201, draft.content)

        video_id = draft.json()['id']
        updated = client.patch(
            f'/api/v1/videos/draft/{video_id}/',
            {'description': 'now with words'}, format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.content)

        published = client.post(f'/api/v1/videos/{video_id}/publish/')
        self.assertEqual(published.status_code, 200, published.content)
        self.assertEqual(published.json()['status'], 'published')

    def test_patch_video(self):
        user = make_user()
        video = make_video(user)
        response = client_for(user).patch(
            f'/api/v1/videos/{video.id}/', {'title': 'Renamed'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['title'], 'Renamed')


class SearchTests(TestCase):

    def test_finds_by_title_and_logs_search_event(self):
        creator = make_user()
        hit = make_video(creator, title='Nollywood comedy special')
        make_video(creator, title='Cooking jollof rice')
        make_video(creator, title='Nollywood private cut',
                   visibility=Video.Visibility.PRIVATE)

        response = client_for().get('/api/v1/videos/search/', {'q': 'nollywood'})

        self.assertEqual(response.status_code, 200, response.content)
        ids = [v['id'] for v in response.json()['results']]
        self.assertEqual(ids, [str(hit.id)])
        event = Event.objects.get(event_type=Event.Type.SEARCH)
        self.assertEqual(event.payload['query'], 'nollywood')
        self.assertEqual(event.payload['result_count'], 1)

    def test_requires_query(self):
        response = client_for().get('/api/v1/videos/search/')
        self.assertEqual(response.status_code, 400)


class TrendingTests(TestCase):

    def test_ranks_completions_above_raw_views(self):
        creator = make_user()
        clicked = make_video(creator, title='clickbait')
        watched = make_video(creator, title='watched through')
        now = timezone.now()
        for _ in range(4):
            ViewLog.objects.create(video=clicked, timestamp=now, completed=False)
        for _ in range(2):
            ViewLog.objects.create(video=watched, timestamp=now, completed=True)
        # Outside the window: must be ignored.
        for _ in range(10):
            ViewLog.objects.create(video=clicked, timestamp=now - timedelta(days=30))

        response = client_for().get('/api/v1/videos/trending/', {'days': 7})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [v['id'] for v in response.json()],
            [str(watched.id), str(clicked.id)],
        )
