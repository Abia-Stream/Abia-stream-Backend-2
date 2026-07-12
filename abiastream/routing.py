from django.urls import path
from realtime.consumers import NotificationConsumer, VideoStatusConsumer

websocket_urlpatterns = [
    path('ws/notifications/', NotificationConsumer.as_asgi()),
    path('ws/video/<uuid:video_id>/', VideoStatusConsumer.as_asgi()),
]