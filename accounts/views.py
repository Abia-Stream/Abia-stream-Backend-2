from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounts.serializers import RegisterSerializer, VerifyEmailSerializer, ResendOTPSerializer, VerifyPasswordResetOTPSerializer,ForgotPasswordSerializer, ResetPasswordSerializer, LoginSerializer, TokenRefreshSerializer  
from accounts.utils import generate_otp, hash_token, get_otp_expiry
from accounts.email_service import send_verification_otp, send_password_reset_otp
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from accounts.utils import get_tokens_for_user
# third party signup
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken



MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15

User = get_user_model()


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {'detail': 'Registration successful. Check your email for the OTP.'},
            status=status.HTTP_201_CREATED
        )


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        if user.is_email_verified:
            return Response({'detail': 'Email already verified.'}, status=status.HTTP_400_BAD_REQUEST)

        # Check expiry
        if not user.password_reset_expires or timezone.now() > user.password_reset_expires:
            return Response({'detail': 'OTP has expired. Request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

        # Check OTP hash
        if user.email_verification_token != hash_token(otp):
            return Response({'detail': 'Invalid OTP.'}, status=status.HTTP_400_BAD_REQUEST)

        # Mark verified and clear token
        user.is_email_verified = True
        user.email_verification_token = None
        user.password_reset_expires = None
        user.status = User.Status.ACTIVE 
        user.save()

        return Response({'detail': 'Email verified successfully.'}, status=status.HTTP_200_OK)


class ResendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Don't leak whether email exists
            return Response({'detail': 'If that email exists, a new OTP has been sent.'})

        if user.is_email_verified:
            return Response({'detail': 'Email already verified.'}, status=status.HTTP_400_BAD_REQUEST)

        otp = generate_otp()
        user.email_verification_token = hash_token(otp)
        user.password_reset_expires = get_otp_expiry()
        user.save()

        send_verification_otp(user.email, otp)

        return Response({'detail': 'If that email exists, a new OTP has been sent.'})
    
class ForgotPasswordView(APIView):
    """Step 1 — user enters email, receives OTP."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Don't leak whether email exists
            return Response({'detail': 'If that email exists, a reset code has been sent.'})

        otp = generate_otp()
        user.password_reset_token = hash_token(otp)
        user.password_reset_expires = get_otp_expiry()
        user.save()

        send_password_reset_otp(user.email, otp)

        return Response({'detail': 'If that email exists, a reset code has been sent.'})


class VerifyPasswordResetOTPView(APIView):
    """Step 2 — validate OTP before allowing password change (optional but recommended)."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyPasswordResetOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'detail': 'Invalid request.'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.password_reset_token or not user.password_reset_expires:
            return Response({'detail': 'No reset request found.'}, status=status.HTTP_400_BAD_REQUEST)

        if timezone.now() > user.password_reset_expires:
            return Response({'detail': 'OTP has expired. Request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

        if user.password_reset_token != hash_token(otp):
            return Response({'detail': 'Invalid OTP.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'detail': 'OTP verified. Proceed to reset your password.'})


class ResetPasswordView(APIView):
    """Step 3 — submit new password with OTP for final verification."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        new_password = serializer.validated_data['new_password']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'detail': 'Invalid request.'}, status=status.HTTP_400_BAD_REQUEST)

        # Re-verify OTP at point of password change (never trust step 2 alone)
        if not user.password_reset_token or not user.password_reset_expires:
            return Response({'detail': 'No reset request found.'}, status=status.HTTP_400_BAD_REQUEST)

        if timezone.now() > user.password_reset_expires:
            return Response({'detail': 'OTP has expired. Request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

        if user.password_reset_token != hash_token(otp):
            return Response({'detail': 'Invalid OTP.'}, status=status.HTTP_400_BAD_REQUEST)

        # Set new password and clear reset fields
        user.set_password(new_password)
        user.password_reset_token = None
        user.password_reset_expires = None
        user.failed_login_attempts = 0   # unlock account if it was locked
        user.locked_until = None
        user.save()

        return Response({'detail': 'Password reset successful. You can now log in.'})
    
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Don't reveal whether email exists
            return Response(
                {'detail': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # ── Check if account is locked ────────────────────────────────────
        if user.locked_until and timezone.now() < user.locked_until:
            remaining = int((user.locked_until - timezone.now()).total_seconds() / 60)
            return Response(
                {'detail': f'Account locked. Try again in {remaining} minute(s).'},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Check if account is active ────────────────────────────────────
        if user.status != 'active':
            return Response(
                {'detail': 'Account is not active. Please verify your email or contact support.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Check if email is verified ────────────────────────────────────
        if not user.is_email_verified:
            return Response(
                {'detail': 'Email not verified. Please verify your email first.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Validate password ─────────────────────────────────────────────
        if not user.check_password(password):
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1

            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = timezone.now() + timezone.timedelta(
                    minutes=LOCKOUT_DURATION_MINUTES
                )
                user.save()
                return Response(
                    {'detail': f'Too many failed attempts. Account locked for {LOCKOUT_DURATION_MINUTES} minutes.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            user.save()
            attempts_left = MAX_FAILED_ATTEMPTS - user.failed_login_attempts
            return Response(
                {'detail': f'Invalid credentials. {attempts_left} attempt(s) remaining.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

# ── Successful login — reset lockout fields ───────────────────────
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login = timezone.now()
        user.last_ip = request.META.get('REMOTE_ADDR')
        user.save()

        tokens = get_tokens_for_user(user)

        # Get profile data
        try:
            from profiles.models import Profile
            profile = Profile.objects.get(user=user)
            full_name = profile.full_name
            avatar_url = profile.avatar_url
        except Profile.DoesNotExist:
            full_name = None
            avatar_url = None

        return Response({
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'user': {
                'id': str(user.id),
                'email': user.email,
                'role': user.role,
                'full_name': full_name,    
                'avatar_url': avatar_url,  
            }
        }, status=status.HTTP_200_OK)


class TokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            refresh = RefreshToken(serializer.validated_data['refresh'])
            return Response({
                'access': str(refresh.access_token),
            }, status=status.HTTP_200_OK)
        except TokenError as e:
            return Response(
                {'detail': 'Refresh token is invalid or expired.'},
                status=status.HTTP_401_UNAUTHORIZED
            )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response(
                    {'detail': 'Refresh token is required.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            token = RefreshToken(refresh_token)
            token.blacklist()  # invalidates the refresh token
            return Response({'detail': 'Logged out successfully.'}, status=status.HTTP_200_OK)
        except TokenError:
            return Response(
                {'detail': 'Invalid or already blacklisted token.'},
                status=status.HTTP_400_BAD_REQUEST
            )


# Admin user management lives in accounts/admin_views.py.


class GoogleAuthView(APIView):
    """
    Accepts a Google ID token from the frontend and returns JWT tokens.
    Works for both Web and Mobile.

    Web:    Frontend gets id_token from Google Sign-In button
    Mobile: Frontend gets id_token from Google Sign-In SDK

    POST /api/auth/google/
    """
    permission_classes = [AllowAny]

    def post(self, request):
        id_token_str = request.data.get('id_token')

        if not id_token_str:
            return Response(
                {'detail': 'id_token is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Verify the token with Google
            google_info = id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID
            )
        except ValueError as e:
            return Response(
                {'detail': f'Invalid Google token: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = google_info.get('email')
        full_name = google_info.get('name', '')
        avatar_url = google_info.get('picture', '')
        google_user_id = google_info.get('sub')

        if not email:
            return Response(
                {'detail': 'Could not retrieve email from Google.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get or create user
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'role': 'viewer',
                'status': 'active',
                'is_email_verified': True,
            }
        )

        if created:
            # Set unusable password for OAuth users
            user.set_unusable_password()
            user.save()

            # Create profile
            from profiles.models import Profile
            Profile.objects.create(
                user=user,
                full_name=full_name,
                avatar_url=avatar_url,
            )
        else:
            # Update avatar if it changed
            if hasattr(user, 'profile') and avatar_url:
                user.profile.avatar_url = avatar_url
                user.profile.save(update_fields=['avatar_url'])

        # Check account status
        if user.status != User.Status.ACTIVE:
            return Response(
                {'detail': 'Account is suspended or banned.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        # Update last login
        user.last_login = timezone.now()
        user.last_ip = request.META.get('REMOTE_ADDR')
        user.save(update_fields=['last_login', 'last_ip'])

        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': str(user.id),
                'email': user.email,
                'role': user.role,
                'full_name': full_name,
                'avatar_url': avatar_url,
            },
            'created': created,  # True if new user, False if existing
        }, status=status.HTTP_200_OK)