# profiles/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404

from profiles.models import Profile
from profiles.serializers import MyProfileSerializer, ProfileSerializer, ProfileUpdateSerializer
from videos.file_security import validate_image_file
from videos.cloudinary_service import (
    upload_image_to_cloudinary,
    generate_signed_image_upload_params,
)


class MyProfileView(APIView):
    """Get or update the logged-in user's own profile."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(Profile.objects.select_related('user'), user_id=request.user.id)
        serializer = MyProfileSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        profile = get_object_or_404(Profile, user_id=request.user.id)
        serializer = ProfileUpdateSerializer(
            profile, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MyProfileSerializer(profile).data, status=status.HTTP_200_OK)


class PublicProfileView(APIView):
    """View any user's public profile by user_id."""
    permission_classes = [AllowAny]

    def get(self, request, user_id):
        profile = get_object_or_404(Profile, user_id=user_id)
        serializer = ProfileSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ── Avatar Upload ─────────────────────────────────────────────────────────────

class AvatarUploadView(APIView):
    """
    Server-side avatar upload.
    POST /api/v1/profile/avatar/
    Content-Type: multipart/form-data
    Field: avatar (file)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        avatar_file = request.FILES.get('avatar')
        if not avatar_file:
            return Response(
                {'detail': 'No file provided. Use field name: avatar'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Security checks
        try:
            file_info = validate_image_file(avatar_file)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Rename to safe name
        avatar_file.name = file_info['safe_name']

        # Upload to Cloudinary
        try:
            result = upload_image_to_cloudinary(
                avatar_file,
                folder='abia_stream/avatars'
            )
        except Exception as e:
            return Response(
                {'detail': f'Upload failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Update profile
        profile = get_object_or_404(Profile, user_id=request.user.id)
        profile.avatar_url = result['secure_url']
        profile.save()

        return Response({
            'detail': 'Avatar updated successfully.',
            'avatar_url': result['secure_url'],
        }, status=status.HTTP_200_OK)


class BannerUploadView(APIView):
    """
    Server-side banner upload.
    POST /api/v1/profile/banner/
    Content-Type: multipart/form-data
    Field: banner (file)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        banner_file = request.FILES.get('banner')
        if not banner_file:
            return Response(
                {'detail': 'No file provided. Use field name: banner'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Security checks
        try:
            file_info = validate_image_file(banner_file)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        banner_file.name = file_info['safe_name']

        # Upload to Cloudinary
        try:
            result = upload_image_to_cloudinary(
                banner_file,
                folder='abia_stream/banners'
            )
        except Exception as e:
            return Response(
                {'detail': f'Upload failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Update profile
        profile = get_object_or_404(Profile, user_id=request.user.id)
        profile.banner_url = result['secure_url']
        profile.save()

        return Response({
            'detail': 'Banner updated successfully.',
            'banner_url': result['secure_url'],
        }, status=status.HTTP_200_OK)


# ── Signed Upload Params (client-side) ────────────────────────────────────────

class AvatarSignedParamsView(APIView):
    """
    Get signed params for direct frontend → Cloudinary avatar upload.
    GET /api/v1/profile/avatar/signed-params/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = generate_signed_image_upload_params(
            folder='abia_stream/avatars'
        )
        return Response(params)


class BannerSignedParamsView(APIView):
    """
    Get signed params for direct frontend → Cloudinary banner upload.
    GET /api/v1/profile/banner/signed-params/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = generate_signed_image_upload_params(
            folder='abia_stream/banners'
        )
        return Response(params)


class UpdateAvatarFromCloudinaryView(APIView):
    """
    Save avatar URL after frontend uploads directly to Cloudinary.
    POST /api/v1/profile/avatar/from-cloudinary/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        avatar_url = request.data.get('avatar_url')
        if not avatar_url:
            return Response(
                {'detail': 'avatar_url is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        profile = get_object_or_404(Profile, user_id=request.user.id)
        profile.avatar_url = avatar_url
        profile.save()

        return Response({
            'detail': 'Avatar updated successfully.',
            'avatar_url': avatar_url,
        }, status=status.HTTP_200_OK)


class UpdateBannerFromCloudinaryView(APIView):
    """
    Save banner URL after frontend uploads directly to Cloudinary.
    POST /api/v1/profile/banner/from-cloudinary/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        banner_url = request.data.get('banner_url')
        if not banner_url:
            return Response(
                {'detail': 'banner_url is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        profile = get_object_or_404(Profile, user_id=request.user.id)
        profile.banner_url = banner_url
        profile.save()

        return Response({
            'detail': 'Banner updated successfully.',
            'banner_url': banner_url,
        }, status=status.HTTP_200_OK)