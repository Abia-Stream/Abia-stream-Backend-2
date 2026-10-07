from django.urls import path
from recommendations.views import ForYouFeedView, RelatedVideosView

urlpatterns = [
    path('videos/feed/', ForYouFeedView.as_view()),
    path('videos/<uuid:video_id>/related/', RelatedVideosView.as_view()),
]
