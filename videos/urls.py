from django.urls import path
from videos.views import (
    VideoUploadView, SignedUploadParamsView, VideoFromCloudinaryView,
    VideoListView, MyVideosView, VideoDetailView,
    PublishVideoView, ArchiveVideoView,
    CategoryListView, TagListView,
)
from videos.views import SaveDraftView, UpdateDraftView

urlpatterns = [
    # Upload
    path('videos/upload/', VideoUploadView.as_view()),
    path('videos/upload/signed-params/', SignedUploadParamsView.as_view()),  #frontend calls this first
    path('videos/upload/from-cloudinary/', VideoFromCloudinaryView.as_view()), # frontend sends this to cloudinary

    # Listing
    path('videos/', VideoListView.as_view()), # Fetch all videos
    path('videos/me/', MyVideosView.as_view()), # Fetch user's own videos

    # Single video
    path('videos/<uuid:video_id>/', VideoDetailView.as_view()), # Fetch a specific video

    # Status actions
    path('videos/<uuid:video_id>/publish/', PublishVideoView.as_view()), # publish video
    path('videos/<uuid:video_id>/archive/', ArchiveVideoView.as_view()), # archive video

    # Categories & Tags
    path('categories/', CategoryListView.as_view()), # Fetch all categories
    path('tags/', TagListView.as_view()), # Fetch all tags

    # Draft videos
    path('videos/draft/', SaveDraftView.as_view()),                    # POST
    path('videos/draft/<uuid:video_id>/', UpdateDraftView.as_view()),
]