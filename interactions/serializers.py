from rest_framework import serializers
from interactions.models import Interaction


class InteractionSerializer(serializers.ModelSerializer):
    video_id = serializers.UUIDField(source='video.id', read_only=True)
    video_title = serializers.CharField(source='video.title', read_only=True)
    video_thumbnail = serializers.CharField(source='video.cloudinary_thumbnail_url', read_only=True)

    class Meta:
        model = Interaction
        fields = [
            'id', 'video_id', 'video_title',
            'video_thumbnail', 'interaction_type', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class CreateInteractionSerializer(serializers.Serializer):
    video_id = serializers.UUIDField()
    interaction_type = serializers.ChoiceField(choices=Interaction.InteractionType.choices)