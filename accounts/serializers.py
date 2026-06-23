from rest_framework import serializers
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from django.db import transaction


User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    full_name = serializers.CharField(max_length=255, write_only=True)

    class Meta:
        model = User
        fields = ['email', 'password', 'full_name']

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

        except Exception as e:
            raise serializers.ValidationError({'detail': str(e)})

        send_verification_otp(user.email, otp)
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