from rest_framework import serializers
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from django.db import transaction
from rest_framework.exceptions import APIException
import logging


User = get_user_model()
logger = logging.getLogger(__name__)


class VerificationEmailUnavailable(APIException):
    status_code = 503
    default_detail = ("We couldn't send your verification code right now, so your account "
                      "wasn't created. Please try again in a few minutes.")
    default_code = 'verification_email_unavailable'


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    full_name = serializers.CharField(max_length=255, write_only=True)

    class Meta:
        model = User
        fields = ['email', 'password', 'full_name']
        # Uniqueness is checked in validate_email with a clearer message.
        extra_kwargs = {'email': {'validators': []}}

    def validate_email(self, value):
        existing = User.objects.filter(email__iexact=value).first()
        if existing is None:
            return value
        if not existing.is_email_verified:
            raise serializers.ValidationError(
                'This email is registered but not verified yet. Use "Resend code" to get a new '
                'verification code.')
        raise serializers.ValidationError('An account with this email already exists. Please log in.')

    def create(self, validated_data):
        from profiles.models import Profile
        from accounts.utils import generate_otp, hash_token, get_otp_expiry
        from accounts.email_service import send_verification_otp

        full_name = validated_data.pop('full_name')
        otp = generate_otp()

        try:
            with transaction.atomic():
                user = User(email=validated_data['email'])
                user.set_password(validated_data['password'])
                user.email_verification_token = hash_token(otp)
                user.password_reset_expires = get_otp_expiry()
                user.is_email_verified = False
                user.save()

                Profile.objects.create(user=user, full_name=full_name)

                # Inside the transaction: if the code can't be emailed, the
                # account isn't created, so the user can simply try again
                # (previously they were left unverified with no code).
                try:
                    send_verification_otp(user.email, otp)
                except Exception:
                    logger.exception('Verification email failed for a new registration')
                    raise VerificationEmailUnavailable()

        except VerificationEmailUnavailable:
            raise
        except Exception as e:
            raise serializers.ValidationError({'detail': str(e)})

        return user

class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=6, max_length=6)


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyPasswordResetOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=6, max_length=6)


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=6, max_length=6)
    new_password = serializers.CharField(min_length=8, write_only=True)
    confirm_password = serializers.CharField(min_length=8, write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return attrs
    
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'role', 'status', 'is_email_verified', 'created_at']
        read_only_fields = ['id', 'created_at']