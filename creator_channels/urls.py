from django.urls import path
from creator_channels.views import (
    CreateChannelView, MyChannelView, DeleteChannelView,
    PublicChannelView, ChannelVideosView, ChannelListView,
    CreatorDashboardView, CreatorAnalyticsView,
    VideoAnalyticsView, ContentListView,

    # Image uploads
    ChannelBannerUploadView, ChannelBannerSignedParamsView,
    UpdateChannelBannerFromCloudinaryView,
    ChannelThumbnailUploadView, ChannelThumbnailSignedParamsView,
    UpdateChannelThumbnailFromCloudinaryView,
)

urlpatterns = [
    # Channel management
    path('channels/', ChannelListView.as_view()),
    path('channels/create/', CreateChannelView.as_view()),
    path('channels/me/', MyChannelView.as_view()),
    path('channels/me/delete/', DeleteChannelView.as_view()),

    # Dashboard
    path('channels/me/dashboard/', CreatorDashboardView.as_view()),
    path('channels/me/performance/', CreatorAnalyticsView.as_view()),
    path('channels/me/content/', ContentListView.as_view()),
    path('channels/me/videos/<uuid:video_id>/analytics/', VideoAnalyticsView.as_view()),

    # Channel banner
    path('channels/me/banner/', ChannelBannerUploadView.as_view()),
    path('channels/me/banner/signed-params/', ChannelBannerSignedParamsView.as_view()),
    path('channels/me/banner/from-cloudinary/', UpdateChannelBannerFromCloudinaryView.as_view()),

    # Channel thumbnail
    path('channels/me/thumbnail/', ChannelThumbnailUploadView.as_view()),
    path('channels/me/thumbnail/signed-params/', ChannelThumbnailSignedParamsView.as_view()),
    path('channels/me/thumbnail/from-cloudinary/', UpdateChannelThumbnailFromCloudinaryView.as_view()),

    # Public
    path('channels/<slug:channel_slug>/', PublicChannelView.as_view()),
    path('channels/<slug:channel_slug>/videos/', ChannelVideosView.as_view()),
]