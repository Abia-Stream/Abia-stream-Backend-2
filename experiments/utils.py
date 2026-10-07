import hashlib
from django.utils import timezone

from experiments.models import Experiment, ExperimentAssignment
from events.utils import resolve_session_id


def _bucket(subject_key, experiment_key, variants):
    """
    Deterministic hash bucketing.

    Salted with the experiment key so a subject is not correlated across
    experiments — without the salt, the same users would land in the same arm
    of every test and results would interact.
    """
    digest = hashlib.sha256(
        f'{experiment_key}:{subject_key}'.encode('utf-8')
    ).hexdigest()
    return variants[int(digest[:8], 16) % len(variants)]


def get_variant(request, experiment_key, default='control'):
    """
    Resolve (and persist) this subject's variant for an experiment.

    Returns `default` when the experiment is missing or inactive, so callers
    can be written once and the experiment switched on later.
    """
    try:
        experiment = Experiment.objects.get(key=experiment_key, is_active=True)
    except Experiment.DoesNotExist:
        return default

    variants = experiment.variants or ['control', 'treatment']

    user = request.user if request.user.is_authenticated else None
    session_id = None if user else resolve_session_id(request)

    lookup = {'experiment': experiment}
    lookup['user'] = user if user else None
    if not user:
        lookup = {'experiment': experiment, 'session_id': session_id}

    existing = ExperimentAssignment.objects.filter(**lookup).first()
    if existing:
        return existing.variant

    subject_key = str(user.id) if user else str(session_id)
    variant = _bucket(subject_key, experiment_key, variants)

    try:
        ExperimentAssignment.objects.create(
            experiment=experiment,
            user=user,
            session_id=session_id,
            variant=variant,
            assigned_at=timezone.now(),
        )
    except Exception:  # noqa: BLE001 - a racing insert is fine; bucketing is deterministic
        pass

    return variant
