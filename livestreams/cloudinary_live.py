"""
Thin client for Cloudinary's Live Streaming API (not covered by the Python SDK).

    https://api.cloudinary.com/v2/video/<cloud>/live_streams

Response shapes verified against the live API on 2026-10-07. A new stream
comes with an RTMP input (uri + permanent stream_key), a "default hls" output
(the playback URL) and a "default archive" output that records the stream to a
normal video asset. At most one archive output is allowed per stream.

Cloudinary has no webhooks for live state, so callers poll get_stream().
"""
import requests
from django.conf import settings

TIMEOUT_SECONDS = 15


class LiveStreamingError(Exception):
    pass


class LiveStreamNotFound(LiveStreamingError):
    pass


def _base_url():
    return f'https://api.cloudinary.com/v2/video/{settings.CLOUDINARY_CLOUD_NAME}/live_streams'


def _call(method, path='', **kwargs):
    try:
        response = requests.request(
            method, _base_url() + path,
            auth=(settings.CLOUDINARY_API_KEY, settings.CLOUDINARY_API_SECRET),
            timeout=TIMEOUT_SECONDS, **kwargs,
        )
    except requests.RequestException as exc:
        raise LiveStreamingError(f'Cloudinary live streaming unreachable: {exc}') from exc

    if response.status_code == 404:
        raise LiveStreamNotFound(path)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        message = (body.get('error') or {}).get('message') or response.text[:200]
        raise LiveStreamingError(f'Cloudinary live streaming error {response.status_code}: {message}')
    return body.get('data', body)


def create_stream(name, idle_timeout_sec, max_runtime_sec):
    return _call('POST', json={
        'name': name,
        'input': {'type': 'rtmp'},
        'idle_timeout_sec': idle_timeout_sec,
        'max_runtime_sec': max_runtime_sec,
    })


def get_stream(stream_id):
    return _call('GET', f'/{stream_id}')


def idle_stream(stream_id):
    return _call('POST', f'/{stream_id}/idle')


def delete_stream(stream_id):
    return _call('DELETE', f'/{stream_id}')


def delete_output(stream_id, output_id):
    return _call('DELETE', f'/{stream_id}/outputs/{output_id}')


def output_of_type(stream_data, output_type):
    for output in stream_data.get('outputs') or []:
        if output.get('type') == output_type:
            return output
    return None
