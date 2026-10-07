import logging

logger = logging.getLogger(__name__)


def enqueue(task, *args, **kwargs):
    """
    Queue a Celery task from request-path code without letting broker trouble
    fail the request. Background work is best-effort here; every task queued
    this way also has a management command or periodic task that catches up.

    Returns True if the task was queued (or ran eagerly), False otherwise.
    """
    try:
        task.delay(*args, **kwargs)
        return True
    except Exception:  # noqa: BLE001 - a broker outage must not become a 500
        logger.exception('Could not enqueue %s', getattr(task, 'name', task))
        return False
