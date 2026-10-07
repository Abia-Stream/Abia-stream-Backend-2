"""
Celery application.

    celery -A abiastream worker -l info     # runs tasks
    celery -A abiastream beat -l info       # schedules the periodic ones

Both need REDIS_URL (or CELERY_BROKER_URL). The web process does not depend
on either running: request-path code enqueues through abiastream.tasks.enqueue,
which logs and carries on if the broker is unreachable.
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'abiastream.settings')

app = Celery('abiastream')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
