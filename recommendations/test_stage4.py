"""Stage 4: learned ranker, feed logging, up next, personalised search, A/B results."""
import random
import uuid
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from abiastream.testing import client_for, make_user, make_video
from accounts.models import User
from events.models import Event
from experiments.models import Experiment, ExperimentAssignment
from playback.models import ViewLog, WatchHistory
from recommendations import ranker
from recommendations.models import RankerModel, RelatedVideo, VideoTransition
from videos.models import Category


def force_variant(experiment_key, user, variant):
    experiment = Experiment.objects.get(key=experiment_key)
    experiment.is_active = True
    experiment.save(update_fields=['is_active'])
    ExperimentAssignment.objects.create(experiment=experiment, user=user, variant=variant)


class ModelMathTests(TestCase):

    def test_auc(self):
        self.assertEqual(ranker.auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]), 1.0)
        self.assertEqual(ranker.auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]), 0.0)
        self.assertEqual(ranker.auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]), 0.5)
        self.assertIsNone(ranker.auc([0.1, 0.2], [1, 1]))

    def test_logistic_learns_the_signal(self):
        rng = random.Random(1)
        rows, labels = [], []
        for _ in range(2000):
            signal, noise = rng.random(), rng.random()
            rows.append([signal, noise])
            labels.append(1 if rng.random() < signal ** 3 else 0)
        weights, intercept, means, stds = ranker.fit_logistic(rows, labels)
        self.assertGreater(weights[0], 0.5)
        self.assertLess(abs(weights[1]), 0.3)
        model = ranker.Ranker(['a', 'b'], weights, intercept, means, stds)
        scores = [model.score({'a': r[0], 'b': r[1]}) for r in rows]
        self.assertGreater(ranker.auc(scores, labels), 0.75)


class FeedLoggingTests(TestCase):

    def test_feed_page_is_logged_with_features(self):
        for i in range(3):
            make_video(make_user(), title=f'v{i}')
        viewer = make_user()
        response = client_for(viewer).get('/api/v1/videos/feed/', {'page_size': 2},
                                          HTTP_X_SESSION_ID=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 200)

        event = Event.objects.get(event_type='feed_served')
        self.assertEqual(event.user_id, viewer.id)
        self.assertEqual(event.payload['variant'], 'control')
        self.assertIsNone(event.payload['model_id'])
        items = event.payload['items']
        self.assertEqual([i['position'] for i in items], [0, 1])
        self.assertEqual([i['video_id'] for i in items],
                         [v['id'] for v in response.json()['results']])
        self.assertEqual(set(items[0]['features']), set(ranker.FEATURE_NAMES))

    def test_clients_cannot_forge_feed_served(self):
        response = client_for().post('/api/v1/events/', {'events': [
            {'event_type': 'feed_served', 'session_id': str(uuid.uuid4())}]}, format='json')
        self.assertEqual(response.status_code, 400)


class LabelTests(TestCase):

    def test_watched_after_matches_session_or_user_within_window(self):
        user = make_user()
        a, b, c = (make_video(make_user()) for _ in range(3))
        session = uuid.uuid4()
        served_at = timezone.now() - timedelta(hours=2)
        event = Event.objects.create(event_type='feed_served', session_id=session,
                                     user=user, occurred_at=served_at, payload={})
        ViewLog.objects.create(video=a, session_id=session, timestamp=served_at + timedelta(minutes=5))
        ViewLog.objects.create(video=b, user=user, session_id=uuid.uuid4(),
                               timestamp=served_at + timedelta(minutes=20))
        ViewLog.objects.create(video=c, session_id=session, timestamp=served_at + timedelta(hours=1))

        self.assertEqual(ranker.watched_after([event])[event.id], {a.id, b.id})


def log_synthetic_feeds(n_events, rng, now, informative=True):
    """
    Feed pages whose watches depend on category_affinity (which the hand-tuned
    `heuristic` ignores) when informative=True, or on nothing otherwise.
    """
    creator = make_user()
    videos = [make_video(creator, title=f's{i}') for i in range(10)]
    for e in range(n_events):
        session = uuid.uuid4()
        served_at = now - timedelta(days=10) + timedelta(minutes=10 * e)
        items, watched = [], []
        for pos, video in enumerate(rng.sample(videos, 10)):
            affinity, heuristic = rng.random(), rng.random()
            items.append({'video_id': str(video.id), 'position': pos, 'reason': 'fresh',
                          'features': {'category_affinity': affinity, 'heuristic': heuristic}})
            p = (0.02 + 0.5 * affinity ** 2) if informative else 0.1
            if rng.random() < p:
                watched.append(video)
        Event.objects.create(event_type='feed_served', session_id=session,
                             occurred_at=served_at, payload={'variant': 'control', 'items': items})
        for video in watched:
            ViewLog.objects.create(video=video, session_id=session,
                                   timestamp=served_at + timedelta(minutes=2))
    return videos


class TrainingTests(TestCase):

    def test_not_enough_data_stores_nothing(self):
        report = ranker.train()
        self.assertFalse(report['activated'])
        self.assertIn('not enough data', report['decision'])
        self.assertFalse(RankerModel.objects.exists())

    def test_learns_and_activates_when_it_beats_the_baseline(self):
        log_synthetic_feeds(150, random.Random(3), timezone.now())

        out = StringIO()
        call_command('train_feed_ranker', stdout=out)

        model = RankerModel.objects.get()
        self.assertTrue(model.is_active, out.getvalue())
        self.assertGreater(model.metrics['auc'], model.metrics['baseline_auc'] + 0.05)
        weights = dict(zip(model.feature_names, model.weights))
        self.assertGreater(weights['category_affinity'], abs(weights['heuristic']))

    def test_model_that_does_not_beat_baseline_stays_inactive(self):
        log_synthetic_feeds(150, random.Random(4), timezone.now(), informative=False)
        report = ranker.train()
        self.assertFalse(report['activated'])
        self.assertFalse(RankerModel.objects.filter(is_active=True).exists())

    def test_dry_run_stores_nothing(self):
        log_synthetic_feeds(150, random.Random(5), timezone.now())
        call_command('train_feed_ranker', '--dry-run', stdout=StringIO())
        self.assertFalse(RankerModel.objects.exists())


class RankerServingTests(TestCase):

    def setUp(self):
        music = Category.objects.create(name='Music', slug='music')
        self.viewer = make_user()
        old = timezone.now() - timedelta(days=40)
        seen = make_video(make_user(), category=music, published_at=old)
        WatchHistory.objects.create(user=self.viewer, video=seen, completed=True,
                                    last_watched_at=timezone.now())
        # Hand-tuned order prefers the fresh upload; a model that has learned
        # category affinity prefers the older music video.
        self.fresh = make_video(make_user(), title='fresh')
        self.music = make_video(make_user(), title='music', category=music,
                                published_at=timezone.now() - timedelta(days=60))
        names = ranker.FEATURE_NAMES
        weights = [5.0 if n == 'category_affinity' else 0.0 for n in names]
        RankerModel.objects.create(feature_names=names, weights=weights, intercept=0.0,
                                   means=[0.0] * len(names), stds=[1.0] * len(names),
                                   is_active=True)

    def titles(self):
        return [v['title'] for v in client_for(self.viewer).get(
            '/api/v1/videos/feed/').json()['results']]

    def test_control_keeps_hand_tuned_order(self):
        force_variant('feed_ranker', self.viewer, 'control')
        self.assertEqual(self.titles()[0], 'fresh')
        self.assertIsNone(Event.objects.get(event_type='feed_served').payload['model_id'])

    def test_treatment_uses_the_model(self):
        force_variant('feed_ranker', self.viewer, 'treatment')
        self.assertEqual(self.titles()[0], 'music')
        logged = Event.objects.get(event_type='feed_served').payload
        self.assertEqual((logged['variant'], logged['model_id']),
                         ('treatment', RankerModel.objects.get().id))

    def test_experiment_off_means_control(self):
        self.assertEqual(self.titles()[0], 'fresh')


class UpNextTests(TestCase):

    def test_transitions_then_related_then_creator(self):
        creator = make_user()
        current = make_video(creator, title='current')
        nxt = make_video(make_user(), title='watched next')
        rel = make_video(make_user(), title='related')
        make_video(creator, title='sibling')
        finished = make_video(make_user(), title='finished')
        now = timezone.now()
        for _ in range(3):
            session = uuid.uuid4()
            ViewLog.objects.create(video=current, session_id=session, timestamp=now - timedelta(minutes=30))
            ViewLog.objects.create(video=nxt, session_id=session, timestamp=now - timedelta(minutes=10))
        RelatedVideo.objects.create(video=current, related=rel, score=0.5)
        RelatedVideo.objects.create(video=current, related=finished, score=0.9)
        viewer = make_user()
        WatchHistory.objects.create(user=viewer, video=finished, completed=True,
                                    last_watched_at=now)

        out = StringIO()
        call_command('build_video_transitions', stdout=out)
        self.assertTrue(VideoTransition.objects.filter(video=current, next_video=nxt).exists())

        data = client_for(viewer).get(f'/api/v1/videos/{current.id}/up-next/').json()
        pairs = [(v['title'], v['up_next_reason']) for v in data]
        self.assertEqual(pairs[:3], [('watched next', 'watched_next'), ('related', 'related'),
                                     ('sibling', 'same_creator')])
        self.assertNotIn('finished', [t for t, _ in pairs])
        self.assertNotIn('current', [t for t, _ in pairs])

    def test_rebuild_prunes_stale_pairs(self):
        a, b = make_video(make_user()), make_video(make_user())
        VideoTransition.objects.create(video=a, next_video=b, transitions=9, score=0.9,
                                       computed_at=timezone.now() - timedelta(days=2))
        call_command('build_video_transitions', stdout=StringIO())
        self.assertFalse(VideoTransition.objects.exists())


class PersonalisedSearchTests(TestCase):

    def setUp(self):
        self.music = Category.objects.create(name='Music', slug='music')
        self.viewer = make_user()
        for _ in range(3):
            WatchHistory.objects.create(
                user=self.viewer, video=make_video(make_user(), category=self.music),
                last_watched_at=timezone.now())
        # Same relevance and a near-tie on popularity: the personal nudge is
        # meant to break near-ties, not to override big popularity gaps.
        self.popular = make_video(make_user(), title='Owambe party', views_count=3)
        self.musical = make_video(make_user(), title='Owambe party', category=self.music)

    def search(self):
        return [v['id'] for v in client_for(self.viewer).get(
            '/api/v1/videos/search/', {'q': 'owambe'}).json()['results']]

    def test_control_is_plain_relevance(self):
        force_variant('search_personalization', self.viewer, 'control')
        self.assertEqual(self.search()[0], str(self.popular.id))

    def test_treatment_prefers_the_viewers_category(self):
        force_variant('search_personalization', self.viewer, 'treatment')
        self.assertEqual(self.search()[0], str(self.musical.id))
        logged = Event.objects.get(event_type='search').payload
        self.assertEqual(logged['variant'], 'treatment')
        self.assertEqual(logged['result_ids'][0], str(self.musical.id))

    def test_signed_out_search_unchanged(self):
        data = client_for().get('/api/v1/videos/search/', {'q': 'owambe'}).json()
        self.assertEqual(data['results'][0]['id'], str(self.popular.id))


class ExperimentResultsTests(TestCase):

    def test_feed_ranker_watch_rates_and_significance(self):
        admin = make_user(role=User.Role.ADMIN)
        videos = [make_video(make_user()) for _ in range(5)]
        now = timezone.now()
        for variant, watch_every in (('control', 10), ('treatment', 3)):
            for e in range(60):
                session = uuid.uuid4()
                served = now - timedelta(days=1, minutes=e)
                Event.objects.create(event_type='feed_served', session_id=session,
                                     occurred_at=served, payload={
                                         'variant': variant,
                                         'items': [{'video_id': str(v.id)} for v in videos]})
                if e % watch_every == 0:
                    ViewLog.objects.create(video=videos[0], session_id=session,
                                           timestamp=served + timedelta(minutes=1))

        data = client_for(admin).get('/api/v1/analytics/experiments/feed_ranker/').json()

        self.assertEqual(data['variants']['control']['items_shown'], 300)
        self.assertEqual(data['variants']['control']['watched'], 6)
        self.assertEqual(data['variants']['treatment']['watched'], 20)
        self.assertGreater(data['comparison']['lift'], 1)
        self.assertTrue(data['comparison']['significant'])

    def test_admin_only(self):
        self.assertEqual(client_for(make_user()).get(
            '/api/v1/analytics/experiments/feed_ranker/').status_code, 403)
