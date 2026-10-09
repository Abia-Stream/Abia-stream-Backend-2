from django.urls import path
from recommendations.views import ForYouFeedView, RelatedVideosView, UpNextView

urlpatterns = [
    path('videos/feed/', ForYouFeedView.as_view()),
    path('videos/<uuid:video_id>/related/', RelatedVideosView.as_view()),
    path('videos/<uuid:video_id>/up-next/', UpNextView.as_view()),
]
