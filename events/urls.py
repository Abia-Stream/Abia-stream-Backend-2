from django.urls import path
from events.views import RecordEventsView

urlpatterns = [
    path('events/', RecordEventsView.as_view()),
]
