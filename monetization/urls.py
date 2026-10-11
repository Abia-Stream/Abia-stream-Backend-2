from django.urls import path

from monetization.views import (
    AdRevenueDetailView, AdRevenueDistributeView, AdRevenueListView, BanksView, CancelMembershipView, ChannelMembershipView,
    EarningsView, MonetizationOverviewView, MonetizationSettingsView, MyMembershipPlanView,
    MyMembershipsView, PayoutAccountView, PayoutsView, PaystackWebhookView, TipView,
    VerifyPaymentView,
)

urlpatterns = [
    # Viewers
    path('monetization/tips/', TipView.as_view()),
    path('monetization/payments/<str:reference>/', VerifyPaymentView.as_view()),
    path('monetization/memberships/', MyMembershipsView.as_view()),
    path('monetization/memberships/<uuid:membership_id>/cancel/', CancelMembershipView.as_view()),
    path('channels/me/membership/', MyMembershipPlanView.as_view()),
    path('channels/<slug:channel_slug>/membership/', ChannelMembershipView.as_view()),
    path('channels/<slug:channel_slug>/membership/join/', ChannelMembershipView.as_view()),
    # Creators
    path('monetization/earnings/', EarningsView.as_view()),
    path('monetization/payouts/', PayoutsView.as_view()),
    path('monetization/payouts/banks/', BanksView.as_view()),
    path('monetization/payouts/account/', PayoutAccountView.as_view()),
    # Paystack
    path('monetization/paystack/webhook/', PaystackWebhookView.as_view()),
    # Admin
    path('admin/monetization/settings/', MonetizationSettingsView.as_view()),
    path('admin/monetization/overview/', MonetizationOverviewView.as_view()),
    path('admin/ad-revenue/', AdRevenueListView.as_view()),
    path('admin/ad-revenue/<int:period_id>/', AdRevenueDetailView.as_view()),
    path('admin/ad-revenue/<int:period_id>/distribute/', AdRevenueDistributeView.as_view()),
]
