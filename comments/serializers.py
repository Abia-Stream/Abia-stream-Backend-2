from rest_framework import serializers
from comments.models import Comment


class CommentUserSerializer(serializers.Serializer):
    """
    Minimal user info for comment display. Comments are public, so this must
    never include the email address.
    """
    id = serializers.UUIDField()
    display_name = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    def get_display_name(self, obj):
        from accounts.display import display_name
        return display_name(obj)

    def get_full_name(self, obj):
        try:
            return obj.profile.full_name
        except Exception:
            return None

    def get_avatar_url(self, obj):
        try:
            return obj.profile.avatar_url
        except Exception:
            return None


class ReplySerializer(serializers.ModelSerializer):
    user = CommentUserSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id', 'user', 'content', 'likes_count',
            'is_edited', 'is_deleted', 'created_at', 'updated_at',
            'is_liked',
        ]

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False


class CommentSerializer(serializers.ModelSerializer):
    user = CommentUserSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id', 'user', 'content', 'likes_count', 'replies_count',
            'is_edited', 'is_deleted', 'created_at', 'updated_at',
            'is_liked', 'replies',
        ]

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_replies(self, obj):
        # Return first 3 replies — frontend loads more on demand
        replies = obj.replies.filter(
            is_deleted=False
        ).order_by('created_at')[:3]
        return ReplySerializer(
            replies, many=True, context=self.context
        ).data


class CreateCommentSerializer(serializers.Serializer):
    content = serializers.CharField(min_length=1, max_length=2000)
    parent_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError('Comment cannot be empty.')
        return value.strip()