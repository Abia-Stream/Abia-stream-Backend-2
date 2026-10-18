# verification/urls.py
from django.urls import path
from verification.views import (
    AdminReviewVerificationView,
    CheckVerificationJobView,
    ReviewAttemptView,
    ReviewQueueView,
    SmileCallbackView,
    SmileSessionView,
    SubmitVerificationView,
    VerificationConfigView,
    VerificationStatusView,
)

urlpatterns = [
    path('verification/config/', VerificationConfigView.as_view()),
    path('verification/smile/session/', SmileSessionView.as_view()),
    path('verification/smile/callback/', SmileCallbackView.as_view()),
    path('verification/submit/', SubmitVerificationView.as_view()),
    path('verification/status/', VerificationStatusView.as_view()),
    path('verification/check/', CheckVerificationJobView.as_view()),
    path('verification/review/', ReviewQueueView.as_view()),
    path('verification/review/attempts/<uuid:attempt_id>/', ReviewAttemptView.as_view()),
    path('verification/review/<uuid:user_id>/', AdminReviewVerificationView.as_view()),
]
