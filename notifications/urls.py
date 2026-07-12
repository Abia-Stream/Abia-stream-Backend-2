from django.urls import path
from notifications.views import (
    NotificationListView,
    UnreadCountView,
    MarkAsReadView,
    MarkAllAsReadView,
    ArchiveNotificationView,
    DeleteNotificationView,
)

urlpatterns = [
    path('notifications/', NotificationListView.as_view()),
    path('notifications/unread-count/', UnreadCountView.as_view()),
    path('notifications/read-all/', MarkAllAsReadView.as_view()),
    path('notifications/<uuid:notification_id>/read/', MarkAsReadView.as_view()),
    path('notifications/<uuid:notification_id>/archive/', ArchiveNotificationView.as_view()),
    path('notifications/<uuid:notification_id>/', DeleteNotificationView.as_view()),
]