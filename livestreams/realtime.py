"""
Push livestream events to `ws/livestream/<id>/` subscribers
(realtime.consumers.LiveStreamConsumer).

Websockets are an enhancement here, not a dependency: every event is also
visible through the REST endpoints (stream detail, chat polling), so a
missing channel layer or a WSGI-only deployment degrades to polling.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def group_name(stream_id):
    return f'livestream_{stream_id}'


def broadcast(stream_id, event, **payload):
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(group_name(stream_id), {
            'type': 'livestream_event',
            'event': event,
            'payload': payload,
        })
    except Exception:  # noqa: BLE001 - a push failure must not fail the request
        logger.exception('Could not broadcast %s for livestream %s', event, stream_id)
