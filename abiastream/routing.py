from django.urls import path
from realtime.consumers import LiveStreamConsumer, NotificationConsumer, VideoStatusConsumer

websocket_urlpatterns = [
    path('ws/notifications/', NotificationConsumer.as_asgi()),
    path('ws/video/<uuid:video_id>/', VideoStatusConsumer.as_asgi()),
    path('ws/livestream/<uuid:livestream_id>/', LiveStreamConsumer.as_asgi()),
]