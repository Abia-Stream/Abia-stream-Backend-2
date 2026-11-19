from django.urls import path
from videos.views import (
    VideoUploadView, SignedUploadParamsView, VideoFromCloudinaryView,
    VideoListView, MyVideosView, VideoDetailView,
    PublishVideoView, ArchiveVideoView, UnarchiveVideoView,
    CategoryListView, TagListView,
)
from videos.views import VideoSearchView, TrendingVideosView
from videos.views import SaveDraftView, UpdateDraftView, CloudinaryWebhookView, VideoThumbnailSignedParamsView, VideoThumbnailUploadView, UpdateVideoThumbnailFromCloudinaryView

urlpatterns = [
    # Upload
    path('videos/upload/', VideoUploadView.as_view()),
    path('videos/upload/signed-params/', SignedUploadParamsView.as_view()),  #frontend calls this first
    path('videos/upload/from-cloudinary/', VideoFromCloudinaryView.as_view()), # frontend sends this to cloudinary

    # Discovery — must precede the <uuid:video_id> route
    path('videos/search/', VideoSearchView.as_view()),      # full-text search
    path('videos/trending/', TrendingVideosView.as_view()), # most watched recently

    # Listing
    path('videos/', VideoListView.as_view()), # Fetch all videos
    path('videos/me/', MyVideosView.as_view()), # Fetch user's own videos

    # Single video
    path('videos/<uuid:video_id>/', VideoDetailView.as_view()), # Fetch a specific video

    # Status actions
    path('videos/<uuid:video_id>/publish/', PublishVideoView.as_view()), # publish video
    path('videos/<uuid:video_id>/archive/', ArchiveVideoView.as_view()), # archive video
    path('videos/<uuid:video_id>/unarchive/', UnarchiveVideoView.as_view()), # restore archived video

    # Categories & Tags
    path('categories/', CategoryListView.as_view()), # Fetch all categories
    path('tags/', TagListView.as_view()), # Fetch all tags

    # Draft videos
    path('videos/draft/', SaveDraftView.as_view()),                    # POST
    path('videos/draft/<uuid:video_id>/', UpdateDraftView.as_view()),

    # cloundinaryWebhook
    path('videos/webhook/cloudinary/', CloudinaryWebhookView.as_view()),

    # Video thumbnail
    path('videos/<uuid:video_id>/thumbnail/', VideoThumbnailUploadView.as_view()),
    path('videos/<uuid:video_id>/thumbnail/signed-params/', VideoThumbnailSignedParamsView.as_view()),
    path('videos/<uuid:video_id>/thumbnail/from-cloudinary/', UpdateVideoThumbnailFromCloudinaryView.as_view()),
]