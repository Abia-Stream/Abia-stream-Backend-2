from io import StringIO

from celery import shared_task
from django.core.management import call_command


@shared_task
def rebuild_related_videos():
    # --prune drops pairs that no longer meet the threshold; safe because the
    # rebuild and the prune run in one transaction.
    call_command('build_related_videos', prune=True, stdout=StringIO())
