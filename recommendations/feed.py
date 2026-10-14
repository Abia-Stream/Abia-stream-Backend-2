"""
The personalized "For You" home feed.

Candidates come from several cheap sources, each contributing a weighted
score; a video found by several sources accumulates them. Then:
  - only published, public videos survive
  - the viewer's own videos and videos they finished are dropped
  - no creator gets more than MAX_PER_CREATOR_IN_A_ROW slots before others
    have had a turn (diversity), deferred rather than dropped

Sources, signed-in:
  related       precomputed co-watch neighbours of recently watched videos
  subscription  recent uploads from subscribed channels
  category      popular recent videos in the viewer's most-watched categories
Sources, everyone:
  trending      completion-weighted views, last 7 days (videos/ranking.py)
  fresh         newest uploads, so new creators can surface at all

Weights are guesses until impression/click events (events app) accumulate;
they are module constants so they can be tuned, or A/B tested via the
experiments app, without touching the logic. A trained ranker
(recommendations/ranker.py) can replace the hand-tuned ordering for viewers
in the `feed_ranker` experiment's treatment arm.
"""
import math
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from playback.models import WatchHistory
from recommendations.models import RelatedVideo
from videos.models import Video
from videos.ranking import trending_video_ids

WEIGHTS = {
    'related': 1.0,
    'subscription': 0.8,
    'category': 0.4,
    'trending': 0.3,
    'fresh': 0.2,
}

RECENT_HISTORY = 20          # watched videos used as "seeds" for related
SUBSCRIPTION_WINDOW_DAYS = 30
CATEGORY_WINDOW_DAYS = 90
TOP_CATEGORIES = 3
PER_SOURCE_LIMIT = 50
MAX_FEED_SIZE = 100
MAX_PER_CREATOR_IN_A_ROW = 2
DIVERSITY_WINDOW = 8         # one page


def _recency(published_at, now, half_life_days=7):
    if not published_at:
        return 0.0
    age_days = max((now - published_at).total_seconds() / 86400, 0)
    return 1.0 / (1.0 + age_days / half_life_days)


class _Scores:
    def __init__(self):
        self.total = defaultdict(float)
        self.by_source = defaultdict(lambda: defaultdict(float))

    def add(self, video_id, source, value):
        if value <= 0:
            return
        weighted = WEIGHTS[source] * value
        self.total[video_id] += weighted
        self.by_source[video_id][source] += weighted

    def reason(self, video_id):
        sources = self.by_source[video_id]
        return max(sources, key=sources.get) if sources else None


def _published_public():
    return Video.objects.filter(
        status=Video.Status.PUBLISHED, visibility=Video.Visibility.PUBLIC)


def _add_personal_sources(scores, user, now):
    history = list(
        WatchHistory.objects.filter(user=user)
        .order_by('-last_watched_at')
        .values_list('video_id', flat=True)[:200]
    )
    recent = history[:RECENT_HISTORY]

    # related: neighbours of what they watched recently
    for row in (RelatedVideo.objects.filter(video_id__in=recent)
                .values('related_id', 'score')
                .order_by('-score')[:PER_SOURCE_LIMIT * 4]):
        scores.add(row['related_id'], 'related', row['score'])

    # subscription: new uploads from channels they follow
    from subscriptions.models import Subscription
    creator_ids = Subscription.objects.filter(subscriber=user).values('channel__user_id')
    for video_id, published_at in (
            _published_public()
            .filter(creator_id__in=creator_ids,
                    published_at__gte=now - timedelta(days=SUBSCRIPTION_WINDOW_DAYS))
            .order_by('-published_at')
            .values_list('id', 'published_at')[:PER_SOURCE_LIMIT]):
        scores.add(video_id, 'subscription', _recency(published_at, now))

    # category: popular recent videos in their favourite categories
    top = list(
        Video.objects.filter(id__in=history, category__isnull=False)
        .values('category_id').annotate(n=Count('id')).order_by('-n')
        .values_list('category_id', flat=True)[:TOP_CATEGORIES]
    )
    if top:
        rows = list(
            _published_public()
            .filter(category_id__in=top,
                    published_at__gte=now - timedelta(days=CATEGORY_WINDOW_DAYS))
            .order_by('-views_count')
            .values_list('id', 'views_count')[:PER_SOURCE_LIMIT]
        )
        max_views = max((v or 0 for _, v in rows), default=0)
        for video_id, views in rows:
            # log-damped popularity in [0, 1]; a floor so zero-view videos still count
            pop = math.log1p(views or 0) / math.log1p(max_views) if max_views else 0
            scores.add(video_id, 'category', 0.2 + 0.8 * pop)


def _add_global_sources(scores, now):
    trending = trending_video_ids(days=7, limit=PER_SOURCE_LIMIT)
    for rank, video_id in enumerate(trending):
        scores.add(video_id, 'trending', 1.0 - rank / max(len(trending), 1))

    for video_id, published_at in (
            _published_public().order_by('-published_at')
            .values_list('id', 'published_at')[:PER_SOURCE_LIMIT]):
        scores.add(video_id, 'fresh', _recency(published_at, now, half_life_days=3))


def _diversify(videos):
    """Defer a creator's 3rd+ video within any page-sized window; never drop."""
    result, deferred = [], []
    for video in videos:
        window = result[-(DIVERSITY_WINDOW - 1):]
        if sum(1 for v in window if v.creator_id == video.creator_id) >= MAX_PER_CREATOR_IN_A_ROW:
            deferred.append(video)
        else:
            result.append(video)
    return result + deferred


def rank_feed(user=None, use_ranker=False):
    """
    Returns (items, model_id) where items is [(video, reason, features)],
    best first, at most MAX_FEED_SIZE long. With use_ranker and an active
    trained model (recommendations/ranker.py), the model orders the
    candidates; otherwise the hand-tuned score does. model_id is None when
    the hand-tuned score was used.
    """
    from recommendations import ranker

    now = timezone.now()
    scores = _Scores()
    signed_in = bool(user and user.is_authenticated)

    if signed_in:
        _add_personal_sources(scores, user, now)
    _add_global_sources(scores, now)

    if not scores.total:
        return [], None

    candidates = _published_public().filter(id__in=list(scores.total))
    if signed_in:
        finished = WatchHistory.objects.filter(user=user, completed=True).values('video_id')
        candidates = candidates.exclude(creator=user).exclude(id__in=finished)

    videos = list(candidates.select_related('category', 'creator', 'creator__channel').prefetch_related('tags'))
    context = ranker.ViewerContext.for_user(user)
    completion = ranker.completion_rates([v.id for v in videos])
    feature_map = {
        v.id: ranker.features(v, scores.by_source[v.id], scores.total[v.id],
                              context, completion, now)
        for v in videos
    }

    model = ranker.active_ranker() if use_ranker else None
    if model:
        key = {v.id: model.score(feature_map[v.id]) for v in videos}
    else:
        key = scores.total
    videos.sort(key=lambda v: (
        -key[v.id],
        -(v.published_at.timestamp() if v.published_at else 0),
    ))
    videos = _diversify(videos)[:MAX_FEED_SIZE]
    items = [(video, scores.reason(video.id), feature_map[video.id]) for video in videos]
    return items, (model.model_id if model else None)


def build_feed(user=None):
    """Hand-tuned feed: [(video, reason), ...] best first."""
    items, _ = rank_feed(user)
    return [(video, reason) for video, reason, _ in items]
