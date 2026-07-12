from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from notifications.models import Notification
from notifications.serializers import NotificationSerializer
from abiastream.pagination import StandardPagination


class NotificationListView(APIView):
    """
    GET /api/v1/notifications/
    Query params: is_read (true/false), type (notification_type)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Notification.objects.filter(
            user=request.user,
            is_archived=False
        )

        # Optional filters
        is_read = request.query_params.get('is_read')
        notification_type = request.query_params.get('type')

        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == 'true')
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = NotificationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class UnreadCountView(APIView):
    """GET /api/v1/notifications/unread-count/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(
            user=request.user,
            is_read=False,
            is_archived=False
        ).count()
        return Response({'unread_count': count})


class MarkAsReadView(APIView):
    """PATCH /api/v1/notifications/<notification_id>/read/"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, notification_id):
        notification = get_object_or_404(
            Notification, id=notification_id, user=request.user
        )
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return Response({'detail': 'Notification marked as read.'})


class MarkAllAsReadView(APIView):
    """PATCH /api/v1/notifications/read-all/"""
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        updated = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).update(is_read=True)
        return Response({'detail': f'{updated} notifications marked as read.'})


class ArchiveNotificationView(APIView):
    """PATCH /api/v1/notifications/<notification_id>/archive/"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, notification_id):
        notification = get_object_or_404(
            Notification, id=notification_id, user=request.user
        )
        notification.is_archived = True
        notification.save(update_fields=['is_archived'])
        return Response({'detail': 'Notification archived.'})


class DeleteNotificationView(APIView):
    """DELETE /api/v1/notifications/<notification_id>/"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, notification_id):
        notification = get_object_or_404(
            Notification, id=notification_id, user=request.user
        )
        notification.delete()
        return Response({'detail': 'Notification deleted.'})