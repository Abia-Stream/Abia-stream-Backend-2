import logging

from celery import shared_task

from verification.services import purge_documents

logger = logging.getLogger(__name__)


@shared_task
def purge_verification_documents():
    counts = purge_documents()
    if counts['due']:
        logger.info('purge_verification_documents: %s', counts)
