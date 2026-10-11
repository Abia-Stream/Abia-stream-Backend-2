from django.urls import path
from interactions.views import InteractWithVideoView, VideoInteractionStatusView, VideoInteractionsCountView, UserLikedVideosView, UserSavedVideosView, UserFavouriteVideosView, ShareVideoView


urlpatterns = [
    path('interactions/', InteractWithVideoView.as_view()),
    path('interactions/video/<uuid:video_id>/status/', VideoInteractionStatusView.as_view()),
    path('interactions/video/<uuid:video_id>/counts/', VideoInteractionsCountView.as_view()),
    path('interactions/liked/', UserLikedVideosView.as_view()),
    path('interactions/saved/', UserSavedVideosView.as_view()),
    path('interactions/favourites/', UserFavouriteVideosView.as_view()),
    path('videos/<uuid:video_id>/share/', ShareVideoView.as_view()),
]