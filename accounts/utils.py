import random
import string
import hashlib
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken


def generate_otp(length=6) -> str:
    """Generate a secure 6-digit numeric OTP."""
    return ''.join(random.choices(string.digits, k=length))


def hash_token(token: str) -> str:
    """Hash OTP/token before storing in DB."""
    return hashlib.sha256(token.encode()).hexdigest()


def get_otp_expiry():
    return timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }