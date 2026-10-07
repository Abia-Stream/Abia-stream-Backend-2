from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from abiastream.testing import make_user, make_video, client_for
from creator_channels.models import CreatorChannel
from playback.models import ViewLog, WatchHistory
from recommendations.models import RelatedVideo
from subscriptions.models import Subscription
from videos.models import Category, Video

FEED = '/api/v1/videos/feed/'


def feed(user=None, **params):
    response = client_for(user).get(FEED, {'page_size': 50, **params})
    assert response.status_code == 200, response.content
    return response.json()


def ids(data):
    return [item['id'] for item in data['results']]


class ForYouFeedTests(TestCase):

    def setUp(self):
        self.viewer = make_user()

    def test_signed_out_gets_trending_and_fresh(self):
        creator = make_user()
        hot = make_video(creator, title='hot',
                         published_at=timezone.now() - timedelta(days=20))
        new = make_video(creator, title='new')
        for _ in range(5):
            ViewLog.objects.create(video=hot, timestamp=timezone.now(), completed=True)

        data = feed()

        self.assertEqual(set(ids(data)), {str(hot.id), str(new.id)})
        reasons = {item['title']: item['feed_reason'] for item in data['results']}
        self.assertEqual(reasons, {'hot': 'trending', 'new': 'fresh'})
        self.assertIn('pagination', data)

    def test_only_published_public_videos(self):
        creator = make_user()
        make_video(creator, visibility=Video.Visibility.PRIVATE)
        make_video(creator, visibility=Video.Visibility.UNLISTED)
        make_video(creator, status=Video.Status.BLOCKED)
        shown = make_video(creator)
        self.assertEqual(ids(feed(self.viewer)), [str(shown.id)])

    def test_excludes_own_and_finished_videos(self):
        mine = make_video(self.viewer)
        finished = make_video(make_user())
        WatchHistory.objects.create(user=self.viewer, video=finished, completed=True,
                                    last_watched_at=timezone.now())
        result = ids(feed(self.viewer))
        self.assertNotIn(str(mine.id), result)
        self.assertNotIn(str(finished.id), result)

    def test_related_to_recent_watch_ranks_first(self):
        old = timezone.now() - timedelta(days=60)
        seed = make_video(make_user(), published_at=old)
        neighbour = make_video(make_user(), title='neighbour', published_at=old)
        make_video(make_user(), title='unrelated new upload')
        WatchHistory.objects.create(user=self.viewer, video=seed,
                                    last_watched_at=timezone.now())
        RelatedVideo.objects.create(video=seed, related=neighbour, score=0.9)

        data = feed(self.viewer)

        self.assertEqual(data['results'][0]['id'], str(neighbour.id))
        self.assertEqual(data['results'][0]['feed_reason'], 'related')

    def test_subscribed_channel_upload_beats_stranger(self):
        followed = make_user()
        channel = CreatorChannel.objects.create(
            user=followed, channel_name='Followed', channel_slug='followed')
        Subscription.objects.create(subscriber=self.viewer, channel=channel)
        from_followed = make_video(followed, title='from followed')
        make_video(make_user(), title='stranger')

        data = feed(self.viewer)

        self.assertEqual(data['results'][0]['id'], str(from_followed.id))
        self.assertEqual(data['results'][0]['feed_reason'], 'subscription')

    def test_favourite_category_boosted(self):
        music = Category.objects.create(name='Music', slug='music')
        news = Category.objects.create(name='News', slug='news')
        old = timezone.now() - timedelta(days=30)
        watched = make_video(make_user(), category=music, published_at=old)
        WatchHistory.objects.create(user=self.viewer, video=watched, completed=True,
                                    last_watched_at=timezone.now())
        song = make_video(make_user(), category=music, published_at=old, title='song')
        make_video(make_user(), category=news, published_at=old, title='bulletin')

        data = feed(self.viewer)

        self.assertEqual(data['results'][0]['id'], str(song.id))
        self.assertEqual(data['results'][0]['feed_reason'], 'category')

    def test_one_creator_cannot_flood_a_page(self):
        prolific = make_user()
        for i in range(6):
            make_video(prolific, title=f'p{i}')
        others = [make_video(make_user(), title=f'o{i}',
                             published_at=timezone.now() - timedelta(days=2))
                  for i in range(3)]

        results = feed(self.viewer)['results']

        # The prolific creator's newer uploads score higher, but after two of
        # them every other creator is pulled ahead of their third.
        head = results[:5]
        self.assertEqual(sum(v['creator_id'] == str(prolific.id) for v in head), 2)
        self.assertEqual({v['id'] for v in head} - {str(o.id) for o in others},
                         {v['id'] for v in head[:2]})
        # Deferred, not dropped.
        self.assertEqual(len(results), 9)

    def test_empty_platform(self):
        self.assertEqual(feed(self.viewer)['results'], [])
