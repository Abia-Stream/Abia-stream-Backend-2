from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from .models import Profile
from .serializers import ProfileSerializer, ProfileUpdateSerializer


class MyProfileView(APIView):
    """Get or update the logged-in user's own profile."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(Profile, user_id=request.user.id)
        serializer = ProfileSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        profile = get_object_or_404(Profile, user_id=request.user.id)
        serializer = ProfileUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProfileSerializer(profile).data, status=status.HTTP_200_OK)


class PublicProfileView(APIView):
    """View any user's public profile by user_id."""
    permission_classes = [AllowAny]

    def get(self, request, user_id):
        profile = get_object_or_404(Profile, user_id=user_id)
        serializer = ProfileSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)