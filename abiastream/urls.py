from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


urlpatterns = [
    path('api/v1/', include('accounts.urls')),
    path('api/v1/', include('profiles.urls')),
    path('api/v1/', include('videos.urls')),
    path('api/v1/', include('playback.urls')),
    path('api/v1/', include('creator_channels.urls')),
    path('api/v1/', include('interactions.urls')),
    path('api/v1/', include('subscriptions.urls')),
    path('api/v1/', include('notifications.urls')),

    # API Docs
    path('api/docs/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/ui', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
