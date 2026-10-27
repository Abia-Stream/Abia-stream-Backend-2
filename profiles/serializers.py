from rest_framework import serializers
from profiles.models import Profile


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = [
            'id', 'user_id', 'full_name', 'bio', 'avatar_url',
            'banner_url', 'social_links', 'website', 'location',
            'date_of_birth', 'is_creator_verified', 'total_views',
            'total_subscribers', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user_id', 'is_creator_verified',
            'total_views', 'total_subscribers', 'created_at', 'updated_at',
        ]


class MyProfileSerializer(ProfileSerializer):
    """
    The signed-in user's own profile (/profile/me/), plus their role:
    viewer | creator | moderator | admin. Read fresh on every request, since an
    admin can change it after login. Public profiles don't include it, so
    staff accounts aren't advertised. The API enforces permissions itself;
    the frontend uses this only to decide what to show.
    """
    role = serializers.CharField(source='user.role', read_only=True)

    class Meta(ProfileSerializer.Meta):
        fields = ProfileSerializer.Meta.fields + ['role']


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = [
            'full_name', 'bio', 'avatar_url', 'banner_url',
            'social_links', 'website', 'location', 'date_of_birth',
        ]

    def validate_social_links(self, value):
        """Ensure social_links is a dict if provided."""
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError('social_links must be a JSON object.')
        return value

    def validate_date_of_birth(self, value):
        from datetime import date
        if value and value >= date.today():
            raise serializers.ValidationError('Date of birth must be in the past.')
        return value