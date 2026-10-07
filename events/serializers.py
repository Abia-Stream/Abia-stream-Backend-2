from rest_framework import serializers
from events.models import Event


class EventSerializer(serializers.Serializer):
    """A single client-reported event."""

    event_type = serializers.ChoiceField(choices=Event.Type.choices)
    session_id = serializers.UUIDField()
    video_id = serializers.UUIDField(required=False, allow_null=True)
    payload = serializers.JSONField(required=False, default=dict)
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('payload must be an object.')
        return value


class EventBatchSerializer(serializers.Serializer):
    """
    Clients buffer events and flush them periodically, so ingest is batched.
    Capped to keep a single request bounded.
    """

    events = EventSerializer(many=True, allow_empty=False, max_length=100)
