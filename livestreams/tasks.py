import logging

from celery import shared_task

from livestreams.services import sync_all

logger = logging.getLogger(__name__)


@shared_task
def sync_livestreams():
    counts = sync_all()
    if any(counts.values()):
        logger.info('sync_livestreams: %s', counts)
