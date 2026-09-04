# verification/urls.py
from django.urls import path
from verification.views import (
    SubmitVerificationView,
    VerificationStatusView,
    CheckVerificationJobView,
    AdminReviewVerificationView,
)

urlpatterns = [
    path('verification/submit/', SubmitVerificationView.as_view()),
    path('verification/status/', VerificationStatusView.as_view()),
    path('verification/check/', CheckVerificationJobView.as_view()),
    path('verification/review/<uuid:user_id>/', AdminReviewVerificationView.as_view()),
]