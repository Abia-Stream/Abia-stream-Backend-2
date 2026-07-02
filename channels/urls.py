# channels/urls.py
from django.urls import path
from channels.views import CreateChannelView, MyChannelView, DeleteChannelView, PublicChannelView, ChannelVideosView, ChannelListView
from channels.views import CreatorDashboardView, CreatorAnalyticsView, VideoAnalyticsView, ContentListView



urlpatterns = [
    # Public
    path('channels/', ChannelListView.as_view()),
    path('channels/<slug:channel_slug>/', PublicChannelView.as_view()),
    path('channels/<slug:channel_slug>/videos/', ChannelVideosView.as_view()),

    # Creator channel management
    path('creator/create/', CreateChannelView.as_view()),
    path('creator/me/', MyChannelView.as_view()),
    path('creator/me/delete/', DeleteChannelView.as_view()),

    # Creator dashboard
    path('creator/me/dashboard/', CreatorDashboardView.as_view()),
    path('creator/me/performance/', CreatorAnalyticsView.as_view()),
    path('creator/me/content/', ContentListView.as_view()),
    path('creator/me/videos/<uuid:video_id>/analytics/', VideoAnalyticsView.as_view()),
]

