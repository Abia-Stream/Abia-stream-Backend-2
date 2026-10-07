from rest_framework.permissions import BasePermission

from accounts.models import User

STAFF_ROLES = {User.Role.ADMIN, User.Role.MODERATOR}


def is_staff_role(user):
    return bool(user and user.is_authenticated and user.role in STAFF_ROLES)


class IsModerator(BasePermission):
    """Moderators and admins."""
    message = 'Moderator access required.'

    def has_permission(self, request, view):
        return is_staff_role(request.user)


class IsAdmin(BasePermission):
    message = 'Admin access required.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == User.Role.ADMIN)
