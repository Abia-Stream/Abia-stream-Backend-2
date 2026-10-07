from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from experiments.models import Experiment
from experiments.utils import get_variant


class MyVariantsView(APIView):
    """
    Variants assigned to the current subject across all active experiments.

    GET /api/v1/experiments/variants/

    Lets the client render the correct treatment without a round trip per
    experiment.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        keys = Experiment.objects.filter(is_active=True).values_list('key', flat=True)
        return Response({key: get_variant(request, key) for key in keys})
