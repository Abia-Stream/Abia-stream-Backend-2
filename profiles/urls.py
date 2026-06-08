from django.urls import path
from profiles.views import MyProfileView, PublicProfileView

urlpatterns = [
    path('profile/me/', MyProfileView.as_view()),
    path('profile/<uuid:user_id>/', PublicProfileView.as_view()),
]