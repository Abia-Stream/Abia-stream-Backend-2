import logging

from celery import shared_task

from playback.management.commands.ensure_view_log_partitions import ensure_partitions

logger = logging.getLogger(__name__)


@shared_task
def ensure_view_log_partitions():
    for name, outcome in ensure_partitions():
        if outcome.startswith('error'):
            logger.error('view_logs partition %s: %s', name, outcome)
