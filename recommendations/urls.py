from django.urls import path
from recommendations.views import RelatedVideosView

urlpatterns = [
    path('videos/<uuid:video_id>/related/', RelatedVideosView.as_view()),
]
