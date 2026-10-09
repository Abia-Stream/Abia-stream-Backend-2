from django.urls import path

from analytics.views import (
    DailyActivityView, ExperimentResultsView, OverviewView, SearchInsightsView,
    TopVideosView,
)

urlpatterns = [
    path('analytics/overview/', OverviewView.as_view()),
    path('analytics/daily/', DailyActivityView.as_view()),
    path('analytics/top-videos/', TopVideosView.as_view()),
    path('analytics/search/', SearchInsightsView.as_view()),
    path('analytics/experiments/<slug:key>/', ExperimentResultsView.as_view()),
]
