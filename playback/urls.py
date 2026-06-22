from django.urls import path
from playback.views import (
    WatchHistoryListView, UpdateProgressView,
    ClearWatchHistoryView, RemoveFromHistoryView,
    RecordViewView, ContinueWatchingView,
)

urlpatterns = [
    # Watch history
    path('playback/history/', WatchHistoryListView.as_view()),
    path('playback/history/clear/', ClearWatchHistoryView.as_view()),      # DELETE
    path('playback/history/<uuid:video_id>/', RemoveFromHistoryView.as_view()),

    # Progress tracking
    path('playback/progress/', UpdateProgressView.as_view()),

    # View logging
    path('playback/view/', RecordViewView.as_view()),

    # Continue watching
    path('playback/continue-watching/', ContinueWatchingView.as_view()),
]