import logging

from celery import shared_task

from moderation.management.commands.scan_videos import scan

logger = logging.getLogger(__name__)


@shared_task
def scan_videos():
    counts = scan()
    if counts['scanned']:
        logger.info('scan_videos: %s', counts)
