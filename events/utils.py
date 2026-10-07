import uuid
from django.utils import timezone

from events.models import Event


def resolve_session_id(request):
    """
    Events are only useful if sessions are reconstructable, including for
    anonymous users. Clients send X-Session-Id; fall back to a fresh UUID so a
    missing header degrades to an unjoined event rather than a dropped one.
    """
    raw = request.headers.get('X-Session-Id')
    if raw:
        try:
            return uuid.UUID(raw)
        except (ValueError, TypeError):
            pass
    return uuid.uuid4()


def log_event(request, event_type, video=None, payload=None):
    """
    Fire-and-forget server-side event write.

    Never raises: a failure to log must not fail the request the user actually
    made. Once Celery is configured this is the natural place to hand off to a
    task instead of writing inline.
    """
    try:
        Event.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_id=resolve_session_id(request),
            video=video,
            event_type=event_type,
            payload=payload or {},
            occurred_at=timezone.now(),
        )
    except Exception:  # noqa: BLE001 - logging must never break the response
        pass
