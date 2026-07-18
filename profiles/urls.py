# profiles/urls.py
from django.urls import path
from profiles.views import (
    MyProfileView,
    PublicProfileView,
    AvatarUploadView,
    BannerUploadView,
    AvatarSignedParamsView,
    BannerSignedParamsView,
    UpdateAvatarFromCloudinaryView,
    UpdateBannerFromCloudinaryView,
)

urlpatterns = [
    # Profile
    path('profile/me/', MyProfileView.as_view()),
    path('profile/<uuid:user_id>/', PublicProfileView.as_view()),

    # Avatar — server-side
    path('profile/avatar/', AvatarUploadView.as_view()),
    # Avatar — client-side
    path('profile/avatar/signed-params/', AvatarSignedParamsView.as_view()),
    path('profile/avatar/from-cloudinary/', UpdateAvatarFromCloudinaryView.as_view()),

    # Banner — server-side
    path('profile/banner/', BannerUploadView.as_view()),
    # Banner — client-side
    path('profile/banner/signed-params/', BannerSignedParamsView.as_view()),
    path('profile/banner/from-cloudinary/', UpdateBannerFromCloudinaryView.as_view()),
]