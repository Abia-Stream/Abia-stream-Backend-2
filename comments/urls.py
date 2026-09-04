# comments/urls.py
from django.urls import path
from comments.views import (
    VideoCommentsView,
    CommentRepliesView,
    CommentDetailView,
    LikeCommentView,
    MyCommentsView,
)

urlpatterns = [
    # Video comments
    path('videos/<uuid:video_id>/comments/', VideoCommentsView.as_view()),

    # Comment actions
    path('comments/<uuid:comment_id>/replies/', CommentRepliesView.as_view()),
    path('comments/<uuid:comment_id>/', CommentDetailView.as_view()),
    path('comments/<uuid:comment_id>/like/', LikeCommentView.as_view()),

    # My comments
    path('comments/me/', MyCommentsView.as_view()),
]