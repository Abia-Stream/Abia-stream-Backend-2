"""
User management for admins: list/search users, change role or status.

    GET   /api/v1/admin/users/?role=&status=&q=     paginated
    GET   /api/v1/admin/users/<user_id>/
    PATCH /api/v1/admin/users/<user_id>/            {"role", "status", "is_email_verified"}

This is how moderators and admins are appointed. Safety rules:
  - an admin can't change their own role or status (no accidental self-lockout)
  - the active-admin rows are locked during a change and the requester is
    re-checked, so admins demoting each other concurrently can't leave the
    platform with no admin
"""
import logging

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from abiastream.pagination import StandardPagination
from accounts.display import display_name
from accounts.models import User
from moderation.permissions import IsAdmin

logger = logging.getLogger(__name__)


class AdminUserSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    has_channel = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'display_name', 'role', 'status', 'is_email_verified',
                  'verification_status', 'has_channel', 'last_login', 'created_at']

    def get_display_name(self, user):
        return display_name(user)

    def get_has_channel(self, user):
        try:
            return user.channel is not None
        except Exception:  # noqa: BLE001 - RelatedObjectDoesNotExist
            return False


class AdminUserUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=User.Role.choices, required=False)
    status = serializers.ChoiceField(choices=User.Status.choices, required=False)
    is_email_verified = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError('Send at least one of role, status, is_email_verified.')
        return attrs


class AdminUserListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        users = User.objects.all().order_by('-created_at')
        params = request.query_params
        if params.get('role'):
            users = users.filter(role=params['role'])
        if params.get('status'):
            users = users.filter(status=params['status'])
        if params.get('q'):
            q = params['q'].strip()
            users = users.filter(Q(email__icontains=q) | Q(profile__full_name__icontains=q)
                                 | Q(channel__channel_name__icontains=q))
        users = users.select_related('profile', 'channel')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(users, request)
        return paginator.get_paginated_response(AdminUserSerializer(page, many=True).data)


class AdminUserDetailView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, user_id):
        return Response(AdminUserSerializer(get_object_or_404(User, id=user_id)).data)

    def patch(self, request, user_id):
        serializer = AdminUserUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = serializer.validated_data

        with transaction.atomic():
            # Lock every active admin row (in a fixed order) for the duration.
            # Two admins demoting each other at the same moment would otherwise
            # both succeed and leave no admin; with the lock the second one
            # waits, then sees it is no longer an admin.
            active_admins = set(User.objects.select_for_update()
                                .filter(role=User.Role.ADMIN, status=User.Status.ACTIVE)
                                .order_by('id').values_list('id', flat=True))
            if request.user.id not in active_admins:
                return Response({'detail': 'Admin access required.'},
                                status=status.HTTP_403_FORBIDDEN)
            target = get_object_or_404(User.objects.select_for_update(), id=user_id)

            if target.id == request.user.id and ({'role', 'status'} & set(changes)):
                return Response({'detail': "You can't change your own role or status."},
                                status=status.HTTP_400_BAD_REQUEST)

            losing_admin = target.id in active_admins and (
                changes.get('role', User.Role.ADMIN) != User.Role.ADMIN
                or changes.get('status', User.Status.ACTIVE) != User.Status.ACTIVE)
            if losing_admin and not (active_admins - {target.id}):
                return Response({'detail': "This is the last active admin; appoint another admin first."},
                                status=status.HTTP_400_BAD_REQUEST)

            old_role = target.role
            for field, value in changes.items():
                setattr(target, field, value)
            target.save(update_fields=[*changes, 'updated_at'])

        logger.warning('Admin %s changed user %s: %s', request.user.id, target.id, changes)
        if 'role' in changes and changes['role'] != old_role:
            from notifications.utils import create_notification
            create_notification(
                user=target, notification_type='role_changed', title='Your role changed',
                message=f'Your account role is now {target.get_role_display()}.',
                data={'role': target.role})
        return Response(AdminUserSerializer(target).data)
