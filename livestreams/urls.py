from django.urls import path

from livestreams.views import (
    CancelLiveStreamView, ChatMessageDetailView, ChatView, EndLiveStreamView,
    HeartbeatView, LiveStreamDetailView, LiveStreamListView, MyLiveStreamsView,
)

urlpatterns = [
    path('livestreams/', LiveStreamListView.as_view()),
    path('livestreams/me/', MyLiveStreamsView.as_view()),
    path('livestreams/chat/<uuid:message_id>/', ChatMessageDetailView.as_view()),
    path('livestreams/<uuid:livestream_id>/', LiveStreamDetailView.as_view()),
    path('livestreams/<uuid:livestream_id>/end/', EndLiveStreamView.as_view()),
    path('livestreams/<uuid:livestream_id>/cancel/', CancelLiveStreamView.as_view()),
    path('livestreams/<uuid:livestream_id>/heartbeat/', HeartbeatView.as_view()),
    path('livestreams/<uuid:livestream_id>/chat/', ChatView.as_view()),
]
