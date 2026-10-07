from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from events.models import Event
from events.serializers import EventBatchSerializer


class RecordEventsView(APIView):
    """
    Ingest a batch of behavioural events.

    POST /api/v1/events/

    Open to anonymous clients — anonymous traffic is most of the early volume
    and excluding it would bias every model trained on this data. `session_id`
    is required precisely so anonymous sessions stay reconstructable.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'events'

    def post(self, request):
        serializer = EventBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user if request.user.is_authenticated else None
        now = timezone.now()

        rows = [
            Event(
                user=user,
                session_id=item['session_id'],
                video_id=item.get('video_id'),
                event_type=item['event_type'],
                payload=item.get('payload') or {},
                # Trust the client's timestamp only as far as ordering within a
                # batch; fall back to server time when absent.
                occurred_at=item.get('occurred_at') or now,
            )
            for item in serializer.validated_data['events']
        ]

        Event.objects.bulk_create(rows)

        return Response(
            {'recorded': len(rows)},
            status=status.HTTP_201_CREATED,
        )
