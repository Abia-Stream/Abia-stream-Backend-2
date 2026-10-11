import json
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from abiastream.pagination import StandardPagination
from creator_channels.models import CreatorChannel
from moderation.permissions import IsAdmin
from monetization import paystack, services
from monetization.models import (
    AdRevenuePeriod, CreatorEarning, Membership, MembershipPlan, Payment, Payout, PayoutAccount,
)


def _error(exc, code=status.HTTP_400_BAD_REQUEST):
    return Response({'detail': str(exc)}, status=code)


# ── Serializers ───────────────────────────────────────────────────────────────

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['id', 'kind', 'amount_kobo', 'currency', 'status', 'provider_reference',
                  'creator_id', 'video_id', 'livestream_id', 'membership_id', 'message',
                  'paid_at', 'created_at']


class MembershipSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.channel_name', read_only=True)
    channel_slug = serializers.CharField(source='channel.channel_slug', read_only=True)
    has_access = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ['id', 'channel_id', 'channel_name', 'channel_slug', 'status', 'price_kobo',
                  'current_period_end', 'started_at', 'cancelled_at', 'has_access', 'created_at']

    def get_has_access(self, membership):
        return membership.grants_access()


class EarningSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreatorEarning
        fields = ['id', 'kind', 'amount_kobo', 'description', 'payment_id', 'payout_id',
                  'ad_period_id', 'created_at']


class PayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = ['id', 'amount_kobo', 'status', 'reference', 'failure_reason', 'created_at',
                  'completed_at']


class PayoutAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutAccount
        fields = ['bank_code', 'bank_name', 'account_number_last4', 'account_name', 'updated_at']


class AdPeriodCreateSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    gross_revenue_kobo = serializers.IntegerField(min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True)


class AdPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdRevenuePeriod
        fields = ['id', 'period_start', 'period_end', 'gross_revenue_kobo', 'platform_fee_percent',
                  'creator_pool_kobo', 'status', 'notes', 'created_at', 'distributed_at']


# ── Viewers: tips ─────────────────────────────────────────────────────────────

class TipView(APIView):
    """
    POST /api/v1/monetization/tips/
      {"video_id" | "livestream_id" | "creator_id": "<uuid>", "amount_kobo": 50000, "message": "optional"}
    Returns a Paystack checkout: open `authorization_url` (or use `access_code`
    with Paystack Popup). The tip counts once Paystack confirms the payment.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from accounts.models import User
        from livestreams.models import LiveStream
        from videos.models import Video

        data = request.data
        try:
            amount = int(data.get('amount_kobo'))
        except (TypeError, ValueError):
            return _error('amount_kobo (integer, kobo) is required.')
        video = livestream = None
        if data.get('video_id'):
            video = get_object_or_404(Video, id=data['video_id'], status=Video.Status.PUBLISHED)
            creator = video.creator
        elif data.get('livestream_id'):
            livestream = get_object_or_404(LiveStream, id=data['livestream_id'])
            creator = livestream.creator
        elif data.get('creator_id'):
            creator = get_object_or_404(User, id=data['creator_id'])
        else:
            return _error('Provide video_id, livestream_id or creator_id.')
        try:
            payment, checkout = services.start_tip(request.user, creator, amount, video=video,
                                                   livestream=livestream, message=data.get('message'))
        except services.MonetizationError as exc:
            return _error(exc)
        return Response({**checkout, 'payment_id': str(payment.id),
                         'public_key': getattr(settings, 'PAYSTACK_PUBLIC_KEY', '') or None},
                        status=status.HTTP_201_CREATED)


class VerifyPaymentView(APIView):
    """
    GET /api/v1/monetization/payments/<reference>/
    Call after Paystack redirects back. Re-checks with Paystack (the webhook
    may not have arrived yet) and returns the payment's status.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        payment = get_object_or_404(Payment, provider_reference=reference, payer=request.user)
        payment = services.confirm_payment(reference) or payment
        return Response(PaymentSerializer(payment).data)


# ── Memberships ───────────────────────────────────────────────────────────────

class ChannelMembershipView(APIView):
    """
    GET  /api/v1/channels/<slug>/membership/        plan + whether you're a member
    POST /api/v1/channels/<slug>/membership/join/   start a Paystack subscription checkout
    """

    def get_permissions(self):
        return [IsAuthenticated()] if self.request.method == 'POST' else [AllowAny()]

    def get(self, request, channel_slug):
        channel = get_object_or_404(CreatorChannel, channel_slug=channel_slug)
        plan = MembershipPlan.objects.filter(channel=channel, is_active=True).first()
        membership = services.live_membership(request.user, channel)
        return Response({
            'offers_membership': bool(plan and plan.paystack_plan_code),
            'price_kobo': plan.price_kobo if plan else None,
            'membership': MembershipSerializer(membership).data if membership else None,
        })

    def post(self, request, channel_slug):
        channel = get_object_or_404(CreatorChannel, channel_slug=channel_slug)
        try:
            membership, checkout = services.start_membership(request.user, channel)
        except services.MonetizationError as exc:
            return _error(exc)
        return Response({**checkout, 'membership_id': str(membership.id),
                         'public_key': getattr(settings, 'PAYSTACK_PUBLIC_KEY', '') or None},
                        status=status.HTTP_201_CREATED)


class MyMembershipsView(APIView):
    """GET /api/v1/monetization/memberships/ — channels you're a member of."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        memberships = Membership.objects.filter(member=request.user).exclude(
            status=Membership.Status.PENDING).select_related('channel')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(memberships, request)
        return paginator.get_paginated_response(MembershipSerializer(page, many=True).data)


class CancelMembershipView(APIView):
    """POST /api/v1/monetization/memberships/<id>/cancel/ — stops renewal; access lasts to period end."""
    permission_classes = [IsAuthenticated]

    def post(self, request, membership_id):
        membership = get_object_or_404(Membership, id=membership_id, member=request.user)
        try:
            membership = services.cancel_membership(membership)
        except services.MonetizationError as exc:
            return _error(exc)
        return Response(MembershipSerializer(membership).data)


class MyMembershipPlanView(APIView):
    """
    GET /api/v1/channels/me/membership/
    PUT /api/v1/channels/me/membership/  {"price_kobo": 150000, "is_active": true}
    Creator sets a monthly price. Changing the price applies to new members.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)
        plan = MembershipPlan.objects.filter(channel=channel).first()
        return Response({
            'price_kobo': plan.price_kobo if plan else None,
            'is_active': plan.is_active if plan else False,
            'active_members': Membership.objects.filter(channel=channel,
                                                        status=Membership.Status.ACTIVE).count(),
        })

    def put(self, request):
        channel = get_object_or_404(CreatorChannel, user=request.user)
        try:
            price = int(request.data.get('price_kobo'))
        except (TypeError, ValueError):
            return _error('price_kobo (integer, kobo) is required.')
        try:
            plan = services.set_membership_plan(channel, price,
                                                bool(request.data.get('is_active', True)))
        except services.MonetizationError as exc:
            return _error(exc)
        return Response({'price_kobo': plan.price_kobo, 'is_active': plan.is_active})


# ── Creators: earnings and payouts ────────────────────────────────────────────

class EarningsView(APIView):
    """
    GET /api/v1/monetization/earnings/
    Balance, totals by source and a paginated ledger (newest first).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        entries = CreatorEarning.objects.filter(creator=user)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(entries, request)
        response = paginator.get_paginated_response(EarningSerializer(page, many=True).data)
        response.data = {
            'balance_kobo': services.balance_kobo(user),
            'pending_payouts_kobo': services.pending_payouts_kobo(user),
            'last_28_days': services.earnings_summary(user, timezone.now() - timedelta(days=28)),
            'lifetime': services.earnings_summary(user),
            'eligible': services.earning_refusal(user) is None,
            'eligibility_detail': services.earning_refusal(user),
            **response.data,
        }
        return response


class BanksView(APIView):
    """GET /api/v1/monetization/payouts/banks/ — Nigerian banks (name, code)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        banks = cache.get('paystack:banks')
        if banks is None:
            try:
                banks = [{'name': b['name'], 'code': b['code']} for b in paystack.list_banks()]
            except paystack.PaystackError as exc:
                return _error(f'Could not load banks: {exc}', status.HTTP_503_SERVICE_UNAVAILABLE)
            cache.set('paystack:banks', banks, 24 * 3600)
        return Response(banks)


class PayoutAccountView(APIView):
    """
    GET /api/v1/monetization/payouts/account/
    PUT /api/v1/monetization/payouts/account/  {"bank_code": "058", "account_number": "0123456789"}
    The account is verified with the bank; only the last 4 digits are stored.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        account = PayoutAccount.objects.filter(creator=request.user).first()
        return Response(PayoutAccountSerializer(account).data if account else None)

    def put(self, request):
        bank_code = request.data.get('bank_code')
        account_number = request.data.get('account_number')
        if not bank_code or not account_number:
            return _error('bank_code and account_number are required.')
        try:
            account = services.set_payout_account(request.user, str(bank_code), account_number)
        except services.MonetizationError as exc:
            return _error(exc)
        return Response(PayoutAccountSerializer(account).data)


class PayoutsView(APIView):
    """
    GET  /api/v1/monetization/payouts/
    POST /api/v1/monetization/payouts/  {"amount_kobo": 500000}
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        paginator = StandardPagination()
        page = paginator.paginate_queryset(Payout.objects.filter(creator=request.user), request)
        return paginator.get_paginated_response(PayoutSerializer(page, many=True).data)

    def post(self, request):
        try:
            amount = int(request.data.get('amount_kobo'))
        except (TypeError, ValueError):
            return _error('amount_kobo (integer, kobo) is required.')
        try:
            payout = services.request_payout(request.user, amount)
        except services.MonetizationError as exc:
            return _error(exc)
        return Response(PayoutSerializer(payout).data, status=status.HTTP_201_CREATED)


# ── Paystack webhook ──────────────────────────────────────────────────────────

class PaystackWebhookView(APIView):
    """
    POST /api/v1/monetization/paystack/webhook/
    Set this URL in the Paystack dashboard (Settings → API Keys & Webhooks).
    Unsigned or wrongly signed requests are rejected; everything else is
    answered 200 (Paystack retries anything else).
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        raw = request.body
        if not paystack.signature_valid(raw, request.headers.get('x-paystack-signature', '')):
            return Response({'detail': 'Invalid signature.'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            payload = json.loads(raw.decode('utf-8'))
        except ValueError:
            return Response({'detail': 'Invalid JSON.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'result': services.handle_webhook(payload)})


# ── Admin ─────────────────────────────────────────────────────────────────────

class MonetizationSettingsView(APIView):
    """
    GET   /api/v1/admin/monetization/settings/
    PATCH /api/v1/admin/monetization/settings/  {"platform_fee_percent": 20, "min_payout_kobo": 100000}
    The fee applies to payments made after the change; past payments keep theirs.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response({k: services.get_setting(k) for k in services.DEFAULTS})

    def patch(self, request):
        data = request.data
        if 'platform_fee_percent' in data:
            try:
                fee = float(data['platform_fee_percent'])
            except (TypeError, ValueError):
                return _error('platform_fee_percent must be a number.')
            if not 0 <= fee <= 50:
                return _error('platform_fee_percent must be between 0 and 50.')
            services.set_setting('platform_fee_percent', fee, request.user)
        if 'min_payout_kobo' in data:
            try:
                minimum = int(data['min_payout_kobo'])
            except (TypeError, ValueError):
                return _error('min_payout_kobo must be an integer.')
            if minimum < 10_000:
                return _error('min_payout_kobo must be at least 10000 (₦100).')
            services.set_setting('min_payout_kobo', minimum, request.user)
        return self.get(request)


class MonetizationOverviewView(APIView):
    """GET /api/v1/admin/monetization/overview/?days=30"""
    permission_classes = [IsAdmin]

    def get(self, request):
        try:
            days = max(1, min(int(request.query_params.get('days', 30)), 365))
        except ValueError:
            days = 30
        return Response({'days': days,
                         **services.platform_totals(timezone.now() - timedelta(days=days)),
                         'settings': {k: services.get_setting(k) for k in services.DEFAULTS}})


class AdRevenueListView(APIView):
    """
    GET  /api/v1/admin/ad-revenue/
    POST /api/v1/admin/ad-revenue/  {"period_start": "2026-10-01", "period_end": "2026-10-31",
                                     "gross_revenue_kobo": 50000000, "notes": "AdSense October"}
    Creates a draft and returns the preview split; nothing is credited until distribute.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        paginator = StandardPagination()
        page = paginator.paginate_queryset(AdRevenuePeriod.objects.all(), request)
        return paginator.get_paginated_response(AdPeriodSerializer(page, many=True).data)

    def post(self, request):
        fields = AdPeriodCreateSerializer(data=request.data)
        fields.is_valid(raise_exception=True)
        data = fields.validated_data
        try:
            period = services.create_ad_period(request.user, data['period_start'], data['period_end'],
                                               data['gross_revenue_kobo'], data.get('notes'))
        except services.MonetizationError as exc:
            return _error(exc)
        return Response(_with_preview(period), status=status.HTTP_201_CREATED)


def _with_preview(period):
    allocations = services.ad_allocations(period.period_start, period.period_end,
                                          period.creator_pool_kobo)
    return {**AdPeriodSerializer(period).data,
            'allocations': [{'creator_id': str(cid), 'watch_seconds': s, 'amount_kobo': a}
                            for cid, s, a in allocations]}


class AdRevenueDetailView(APIView):
    """GET /api/v1/admin/ad-revenue/<id>/ — the period and its preview split (read-only)."""
    permission_classes = [IsAdmin]

    def get(self, request, period_id):
        return Response(_with_preview(get_object_or_404(AdRevenuePeriod, id=period_id)))


class AdRevenueDistributeView(APIView):
    """POST /api/v1/admin/ad-revenue/<id>/distribute/ — credit creators. Once only."""
    permission_classes = [IsAdmin]

    def post(self, request, period_id):
        period = get_object_or_404(AdRevenuePeriod, id=period_id)
        try:
            period, credited = services.distribute_ad_period(period)
        except services.MonetizationError as exc:
            return _error(exc)
        return Response({**AdPeriodSerializer(period).data, 'creators_credited': len(credited),
                         'total_credited_kobo': sum(c.amount_kobo for c in credited)})
