from django.urls import path
from accounts.views import (
    RegisterView, VerifyEmailView, ResendOTPView,
    ForgotPasswordView, VerifyPasswordResetOTPView, ResetPasswordView, LoginView, TokenRefreshView, LogoutView, GoogleAuthView
)

urlpatterns = [
    # Email verification
    path('auth/register/', RegisterView.as_view()),
    path('auth/verify-email/', VerifyEmailView.as_view()),
    path('auth/resend-otp/', ResendOTPView.as_view()),
        path('auth/login/', LoginView.as_view()),
    path('auth/token/refresh/', TokenRefreshView.as_view()),
    path('auth/logout/', LogoutView.as_view()),

    # Password reset
    path('auth/forgot-password/', ForgotPasswordView.as_view()),
    path('auth/verify-reset-otp/', VerifyPasswordResetOTPView.as_view()),
    path('auth/reset-password/', ResetPasswordView.as_view()),
    
    # Google signup
    path('auth/google/', GoogleAuthView.as_view()),   # ← add this
]