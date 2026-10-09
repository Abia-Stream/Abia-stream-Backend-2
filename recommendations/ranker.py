"""
Learned ranking for the For You feed (roadmap Stage 4, "ranking model").

Two-stage design:
  1. candidate generation — the existing sources in recommendations/feed.py
     (related, subscriptions, categories, trending, fresh)
  2. ranking — this module: a logistic regression predicting "will this
     viewer watch this video if we show it", over FEATURE_NAMES.

Training data is logged by the server, not reconstructed: every feed page
served is stored as a `feed_served` event with each item's features exactly
as they were at serving time (no train/serve skew). The label is whether the
same session or user then watched that video within LABEL_WINDOW.

Safety: a model only becomes active if there is enough data AND it beats the
hand-tuned score (`heuristic`) on a later, held-out time slice. Even then it
only affects viewers in the `feed_ranker` experiment's treatment arm, and that
experiment is created switched off.

Pure Python on purpose: at our data volumes it trains in seconds and serving
is a dot product, with no numpy/scikit-learn on the web dyno.
"""
import math
import random
from collections import Counter, defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

FEATURE_NAMES = [
    's_related', 's_subscription', 's_category', 's_trending', 's_fresh',
    'heuristic', 'log_views', 'completion_rate', 'log_age_days',
    'is_subscribed', 'creator_affinity', 'category_affinity',
]
SOURCES = ('related', 'subscription', 'category', 'trending', 'fresh')

LABEL_WINDOW = timedelta(minutes=30)
TRAIN_DAYS = 30
MAX_TRAIN_ROWS = 50_000
HOLDOUT_SHARE = 0.2
MIN_ROWS = 1_000
MIN_POSITIVES = 50
MIN_HOLDOUT_POSITIVES = 10
MIN_AUC_GAIN = 0.01
# The gain must also exceed this many standard errors of the AUC estimate,
# so a model that only looks better by chance is never activated.
AUC_GAIN_STD_ERRORS = 2.0
MIN_ABSOLUTE_AUC = 0.55


# ── Features ──────────────────────────────────────────────────────────────────

class ViewerContext:
    """What we know about the viewer, computed once per feed request."""

    def __init__(self, subscribed_creators=(), creator_counts=None, category_shares=None):
        self.subscribed_creators = set(subscribed_creators)
        self.creator_counts = creator_counts or {}
        self.category_shares = category_shares or {}

    @classmethod
    def for_user(cls, user):
        if not (user and user.is_authenticated):
            return cls()
        from playback.models import WatchHistory
        from subscriptions.models import Subscription
        from videos.models import Video

        history = list(WatchHistory.objects.filter(user=user)
                       .order_by('-last_watched_at').values_list('video_id', flat=True)[:200])
        rows = list(Video.objects.filter(id__in=history).values_list('creator_id', 'category_id'))
        creators = Counter(c for c, _ in rows)
        categories = Counter(c for _, c in rows if c is not None)
        total = sum(categories.values()) or 1
        return cls(
            subscribed_creators=Subscription.objects.filter(subscriber=user)
            .values_list('channel__user_id', flat=True),
            creator_counts=dict(creators),
            category_shares={k: v / total for k, v in categories.items()},
        )


def completion_rates(video_ids, days=30):
    """{video_id: share of views completed} over recent view logs."""
    from playback.models import ViewLog
    since = timezone.now() - timedelta(days=days)
    rows = (ViewLog.objects.filter(video_id__in=video_ids, timestamp__gte=since)
            .values('video_id')
            .annotate(n=Count('id'), done=Count('id', filter=Q(completed=True))))
    return {r['video_id']: r['done'] / r['n'] for r in rows if r['n']}


def features(video, source_scores, heuristic, context, completion, now):
    age_days = max((now - video.published_at).total_seconds() / 86400, 0) \
        if video.published_at else 365.0
    values = {f's_{s}': float(source_scores.get(s, 0.0)) for s in SOURCES}
    values.update({
        'heuristic': float(heuristic),
        'log_views': math.log1p(video.views_count or 0),
        'completion_rate': float(completion.get(video.id, 0.0)),
        'log_age_days': math.log1p(age_days),
        'is_subscribed': 1.0 if video.creator_id in context.subscribed_creators else 0.0,
        'creator_affinity': math.log1p(context.creator_counts.get(video.creator_id, 0)),
        'category_affinity': float(context.category_shares.get(video.category_id, 0.0)),
    })
    return values


def vector(feature_dict, names=FEATURE_NAMES):
    return [float(feature_dict.get(name, 0.0)) for name in names]


# ── Model ─────────────────────────────────────────────────────────────────────

def _sigmoid(x):
    if x < -35:
        return 0.0
    if x > 35:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


class Ranker:
    """Serving-side view of a RankerModel row."""

    def __init__(self, feature_names, weights, intercept, means, stds, model_id=None):
        self.feature_names = list(feature_names)
        self.weights = list(weights)
        self.intercept = float(intercept)
        self.means = list(means)
        self.stds = list(stds)
        self.model_id = model_id

    @classmethod
    def from_row(cls, row):
        return cls(row.feature_names, row.weights, row.intercept, row.means, row.stds, row.id)

    def score(self, feature_dict):
        x = vector(feature_dict, self.feature_names)
        z = sum(w * (v - m) / s for w, v, m, s in zip(self.weights, x, self.means, self.stds))
        return _sigmoid(self.intercept + z)


def active_ranker(name='feed'):
    from recommendations.models import RankerModel
    row = RankerModel.objects.filter(name=name, is_active=True).first()
    return Ranker.from_row(row) if row else None


def fit_logistic(rows, labels, epochs=8, learning_rate=0.05, l2=1e-4, seed=7):
    """Standardised logistic regression by SGD. Returns (weights, intercept, means, stds)."""
    n_features = len(rows[0])
    means = [sum(r[j] for r in rows) / len(rows) for j in range(n_features)]
    stds = []
    for j in range(n_features):
        var = sum((r[j] - means[j]) ** 2 for r in rows) / len(rows)
        stds.append(math.sqrt(var) or 1.0)
    data = [([(r[j] - means[j]) / stds[j] for j in range(n_features)], y)
            for r, y in zip(rows, labels)]

    # Balance the classes: positives are rare, and plain SGD would learn
    # "nobody clicks anything".
    positives = sum(labels) or 1
    pos_weight = (len(labels) - positives) / positives

    weights = [0.0] * n_features
    intercept = 0.0
    rng = random.Random(seed)
    for epoch in range(epochs):
        rng.shuffle(data)
        lr = learning_rate / (1 + epoch)
        for x, y in data:
            p = _sigmoid(intercept + sum(w * v for w, v in zip(weights, x)))
            g = (p - y) * (pos_weight if y else 1.0)
            intercept -= lr * g
            for j in range(n_features):
                weights[j] -= lr * (g * x[j] + l2 * weights[j])
    return weights, intercept, means, stds


def auc(scores, labels):
    """Area under the ROC curve (rank-sum, ties averaged). None if one class only."""
    pairs = sorted(zip(scores, labels))
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if not n_pos or not n_neg:
        return None
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2
        rank_sum += avg_rank * sum(1 for k in range(i, j) if pairs[k][1])
        i = j
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def auc_standard_error(auc_value, n_pos, n_neg):
    """Hanley & McNeil (1982) standard error of an AUC estimate."""
    a = auc_value
    q1 = a / (2 - a)
    q2 = 2 * a * a / (1 + a)
    var = (a * (1 - a) + (n_pos - 1) * (q1 - a * a)
           + (n_neg - 1) * (q2 - a * a)) / (n_pos * n_neg)
    return math.sqrt(max(var, 0.0))


# ── Training data ─────────────────────────────────────────────────────────────

def watched_after(served_events):
    """
    {event_id: set(video_ids)} that the event's session or user went on to
    watch within LABEL_WINDOW of being served the page.
    """
    from events.models import Event
    from playback.models import ViewLog

    served_events = list(served_events)
    if not served_events:
        return {}
    start = min(e.occurred_at for e in served_events)
    end = max(e.occurred_at for e in served_events) + LABEL_WINDOW

    watches = defaultdict(list)  # (kind, key) -> [(timestamp, video_id)]
    for session_id, user_id, video_id, ts in ViewLog.objects.filter(
            timestamp__gte=start, timestamp__lte=end).values_list(
            'session_id', 'user_id', 'video_id', 'timestamp'):
        if session_id:
            watches[('s', session_id)].append((ts, video_id))
        if user_id:
            watches[('u', user_id)].append((ts, video_id))
    for session_id, user_id, video_id, ts in Event.objects.filter(
            event_type__in=[Event.Type.PLAY, Event.Type.VIDEO_CLICK],
            occurred_at__gte=start, occurred_at__lte=end,
            video_id__isnull=False).values_list('session_id', 'user_id', 'video_id', 'occurred_at'):
        watches[('s', session_id)].append((ts, video_id))
        if user_id:
            watches[('u', user_id)].append((ts, video_id))

    result = {}
    for event in served_events:
        found = set()
        for key in (('s', event.session_id), ('u', event.user_id)):
            for ts, video_id in watches.get(key, ()):
                if event.occurred_at <= ts <= event.occurred_at + LABEL_WINDOW:
                    found.add(video_id)
        result[event.id] = found
    return result


def training_rows(days=TRAIN_DAYS, now=None):
    """[(occurred_at, feature_vector, label)] oldest first."""
    from events.models import Event

    now = now or timezone.now()
    served = list(Event.objects.filter(
        event_type=Event.Type.FEED_SERVED,
        occurred_at__gte=now - timedelta(days=days),
        occurred_at__lte=now - LABEL_WINDOW,          # labels must be complete
    ).order_by('-occurred_at')[:MAX_TRAIN_ROWS])
    labels = watched_after(served)

    rows = []
    for event in reversed(served):
        watched = {str(v) for v in labels.get(event.id, ())}
        for item in (event.payload or {}).get('items', []):
            rows.append((event.occurred_at, vector(item.get('features') or {}),
                         1 if item.get('video_id') in watched else 0))
    return rows[-MAX_TRAIN_ROWS:]


# ── Train + decide ────────────────────────────────────────────────────────────

def train(name='feed', days=TRAIN_DAYS, now=None, save=True):
    """
    Train on recent served feeds. Returns a report dict. Stores the model
    (and activates it) only if there is enough data and it beats the
    hand-tuned score on the held-out, most recent slice.
    """
    from recommendations.models import RankerModel

    rows = training_rows(days=days, now=now)
    positives = sum(label for _, _, label in rows)
    report = {'rows': len(rows), 'positives': positives, 'activated': False}

    if len(rows) < MIN_ROWS or positives < MIN_POSITIVES:
        report['decision'] = (f'not enough data yet: need {MIN_ROWS} shown items and '
                              f'{MIN_POSITIVES} watches, have {len(rows)} and {positives}')
        return report

    split = int(len(rows) * (1 - HOLDOUT_SHARE))        # time-ordered: no leakage
    train_rows, holdout = rows[:split], rows[split:]
    holdout_positives = sum(label for _, _, label in holdout)
    if holdout_positives < MIN_HOLDOUT_POSITIVES or not any(l for _, _, l in train_rows):
        report['decision'] = 'not enough watches in the held-out slice to judge a model'
        return report

    weights, intercept, means, stds = fit_logistic(
        [x for _, x, _ in train_rows], [y for _, _, y in train_rows])
    model = Ranker(FEATURE_NAMES, weights, intercept, means, stds)
    holdout_labels = [y for _, _, y in holdout]
    model_auc = auc([model.score(dict(zip(FEATURE_NAMES, x))) for _, x, _ in holdout],
                    holdout_labels)
    baseline_auc = auc([x[FEATURE_NAMES.index('heuristic')] for _, x, _ in holdout],
                       holdout_labels)

    required_gain = None
    activate = False
    if model_auc is not None and model_auc >= MIN_ABSOLUTE_AUC:
        n_pos = holdout_positives
        n_neg = len(holdout_labels) - n_pos
        # Both AUCs are noisy estimates on the same small slice; the gain has
        # to clear the uncertainty of their difference, not just the model's.
        se_model = auc_standard_error(model_auc, n_pos, n_neg)
        se_base = auc_standard_error(baseline_auc, n_pos, n_neg) if baseline_auc is not None else 0.0
        required_gain = max(MIN_AUC_GAIN,
                            AUC_GAIN_STD_ERRORS * math.sqrt(se_model ** 2 + se_base ** 2))
        activate = baseline_auc is None or model_auc >= baseline_auc + required_gain
    report.update({
        'train_rows': len(train_rows), 'holdout_rows': len(holdout),
        'holdout_positives': holdout_positives,
        'auc': round(model_auc, 4) if model_auc is not None else None,
        'baseline_auc': round(baseline_auc, 4) if baseline_auc is not None else None,
        'required_gain': round(required_gain, 4) if required_gain is not None else None,
        'weights': {n: round(w, 4) for n, w in zip(FEATURE_NAMES, weights)},
        'activated': activate,
        'decision': ('activated: clearly beats the hand-tuned score on held-out data'
                     if activate else
                     'kept inactive: not clearly better than the hand-tuned score'),
    })
    if save:
        with transaction.atomic():
            if activate:
                RankerModel.objects.filter(name=name, is_active=True).update(is_active=False)
            row = RankerModel.objects.create(
                name=name, feature_names=FEATURE_NAMES, weights=weights,
                intercept=intercept, means=means, stds=stds,
                metrics={k: v for k, v in report.items() if k != 'weights'},
                is_active=activate)
        report['model_id'] = row.id
    return report
