from rest_framework import serializers

from moderation.models import ContentReport, ModerationAction


class CreateReportSerializer(serializers.Serializer):
    video_id = serializers.UUIDField(required=False)
    comment_id = serializers.UUIDField(required=False)
    reason = serializers.ChoiceField(choices=ContentReport.Reason.choices)
    details = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attrs):
        if bool(attrs.get('video_id')) == bool(attrs.get('comment_id')):
            raise serializers.ValidationError('Provide exactly one of video_id or comment_id.')
        return attrs


class ReportSerializer(serializers.ModelSerializer):
    reporter_id = serializers.UUIDField(read_only=True)
    video_id = serializers.UUIDField(read_only=True)
    comment_id = serializers.UUIDField(read_only=True)
    reviewed_by_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ContentReport
        fields = [
            'id', 'reporter_id', 'target_type', 'video_id', 'comment_id',
            'reason', 'details', 'status', 'reviewed_by_id', 'reviewed_at',
            'resolution_note', 'created_at',
        ]


class MyReportSerializer(serializers.ModelSerializer):
    """What a reporter sees about their own report: no moderator identity."""
    video_id = serializers.UUIDField(read_only=True)
    comment_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ContentReport
        fields = ['id', 'target_type', 'video_id', 'comment_id', 'reason',
                  'details', 'status', 'created_at']


class ApplyActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ModerationAction.Action.choices)
    video_id = serializers.UUIDField(required=False)
    comment_id = serializers.UUIDField(required=False)
    user_id = serializers.UUIDField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ModerationActionSerializer(serializers.ModelSerializer):
    moderator_id = serializers.UUIDField(read_only=True)
    video_id = serializers.UUIDField(read_only=True)
    comment_id = serializers.UUIDField(read_only=True)
    target_user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ModerationAction
        fields = ['id', 'moderator_id', 'action', 'video_id', 'comment_id',
                  'target_user_id', 'note', 'metadata', 'created_at']
