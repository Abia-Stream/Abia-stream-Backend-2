from django.urls import path
from subscriptions.views import (
    SubscribeView,
    MySubscriptionsView,
    ChannelSubscriptionStatusView,
    ChannelSubscribersView,
)

urlpatterns = [
    path('subscriptions/', MySubscriptionsView.as_view()),
    path('subscriptions/<slug:channel_slug>/', SubscribeView.as_view()),
    path('subscriptions/<slug:channel_slug>/status/', ChannelSubscriptionStatusView.as_view()),
    path('subscriptions/<slug:channel_slug>/subscribers/', ChannelSubscribersView.as_view()),
]