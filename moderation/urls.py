from django.urls import path

from moderation.views import (
    ModerationActionView, ModerationQueueView, ModerationReportListView, ReportView,
)

urlpatterns = [
    path('reports/', ReportView.as_view()),
    path('moderation/queue/', ModerationQueueView.as_view()),
    path('moderation/reports/', ModerationReportListView.as_view()),
    path('moderation/actions/', ModerationActionView.as_view()),
]
