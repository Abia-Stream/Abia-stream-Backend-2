"""
Creator monetization: tips, paid channel memberships, ad revenue share,
payouts, all through one earnings ledger.

Money rules:
  - Amounts are integer kobo. The platform fee is computed once, at the moment
    a payment succeeds, from the setting in force then, and stored on the
    payment; the creator is credited the rest.
  - A payment counts only after Paystack confirms it server-side (Verify
    Transaction), whether we learn of it from the signed webhook or from the
    frontend's return redirect. The amount is taken from Paystack, never the
    client, and must match what we initialised.
  - Every balance change is one creator_earnings row, protected by unique
    indexes, so retries and duplicate webhooks can never credit twice.
  - A payout debits the ledger when requested; if Paystack fails or reverses
    the transfer, the amount is credited back.
"""
import logging
import uuid
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from monetization import paystack
from monetization.models import (
    AdRevenuePeriod, CreatorEarning, Membership, MembershipPlan, Payment, PaystackEvent,
    PlatformSetting, Payout, PayoutAccount,
)

logger = logging.getLogger(__name__)

MIN_TIP_KOBO = 10_000            # ₦100
MAX_TIP_KOBO = 100_000_000       # ₦1,000,000
MEMBERSHIP_PERIOD = timedelta(days=30)
DEFAULTS = {'platform_fee_percent': 20, 'min_payout_kobo': 100_000}


class MonetizationError(Exception):
    """A rejected request; the message is safe to show the caller."""


def naira(kobo):
    return f'₦{Decimal(kobo) / 100:,.2f}'


# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key):
    row = PlatformSetting.objects.filter(key=key).first()
    return row.value if row else DEFAULTS[key]


def set_setting(key, value, user):
    PlatformSetting.objects.update_or_create(
        key=key, defaults={'value': value, 'updated_by': user, 'updated_at': timezone.now()})


def split(amount_kobo, fee_percent):
    """(platform_fee_kobo, creator_kobo) — fee rounded half-up to the kobo."""
    fee = int((Decimal(amount_kobo) * Decimal(str(fee_percent)) / 100)
              .quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return fee, amount_kobo - fee


# ── Eligibility ───────────────────────────────────────────────────────────────

def earning_refusal(user):
    """None if `user` can receive money, else why not."""
    from accounts.models import User
    from creator_channels.models import CreatorChannel

    if user.status != User.Status.ACTIVE:
        return 'This creator cannot receive payments right now.'
    if user.verification_status != User.VerificationStatus.APPROVED:
        return 'Only verified creators can receive payments.'
    if not CreatorChannel.objects.filter(user=user).exists():
        return 'A channel is required to receive payments.'
    return None


# ── Ledger ────────────────────────────────────────────────────────────────────

def balance_kobo(creator):
    return CreatorEarning.objects.filter(creator=creator).aggregate(
        total=Sum('amount_kobo'))['total'] or 0


def _credit(**fields):
    """Insert a ledger row; a duplicate (retry) is silently ignored."""
    try:
        with transaction.atomic():
            return CreatorEarning.objects.create(**fields)
    except IntegrityError:
        return None


def _notify(user, kind, title, message, data):
    from notifications.utils import create_notification
    create_notification(user=user, notification_type=kind, title=title, message=message, data=data)


# ── Tips ──────────────────────────────────────────────────────────────────────

def start_tip(payer, creator, amount_kobo, *, video=None, livestream=None, message=None):
    """Create a pending tip and a Paystack checkout. Returns (payment, checkout)."""
    if creator.id == payer.id:
        raise MonetizationError("You can't tip yourself.")
    refusal = earning_refusal(creator)
    if refusal:
        raise MonetizationError(refusal)
    if not MIN_TIP_KOBO <= amount_kobo <= MAX_TIP_KOBO:
        raise MonetizationError(f'Tips must be between {naira(MIN_TIP_KOBO)} and {naira(MAX_TIP_KOBO)}.')

    payment = Payment.objects.create(
        kind=Payment.Kind.TIP, payer=payer, creator=creator, amount_kobo=amount_kobo,
        video=video, livestream=livestream, message=(message or '').strip()[:200] or None,
        provider_reference=f'tip_{uuid.uuid4().hex}')
    return payment, _checkout(payment, payer.email)


def _checkout(payment, email, plan=None):
    try:
        data = paystack.initialize_transaction(
            email=email, amount_kobo=payment.amount_kobo, reference=payment.provider_reference,
            plan=plan, callback_url=getattr(settings, 'PAYSTACK_CALLBACK_URL', '') or None,
            metadata={'payment_id': str(payment.id), 'kind': payment.kind})
    except paystack.PaystackError as exc:
        logger.error('Paystack initialise failed for %s: %s', payment.provider_reference, exc)
        Payment.objects.filter(id=payment.id).update(status=Payment.Status.FAILED)
        raise MonetizationError('Payments are temporarily unavailable. Please try again.')
    return {'authorization_url': data.get('authorization_url'),
            'access_code': data.get('access_code'), 'reference': payment.provider_reference}


# ── Confirming payments (shared by webhook and redirect check) ───────────────

def confirm_payment(reference):
    """
    Verify `reference` with Paystack and, if paid, settle it exactly once.
    Returns the Payment (or None if the reference isn't ours).
    """
    payment = Payment.objects.filter(provider_reference=reference).first()
    if payment is None or payment.status == Payment.Status.SUCCESS:
        return payment
    try:
        data = paystack.verify_transaction(reference)
    except paystack.PaystackError as exc:
        logger.error('Paystack verify failed for %s: %s', reference, exc)
        return payment

    if data.get('status') in ('failed', 'abandoned', 'reversed'):
        Payment.objects.filter(id=payment.id, status=Payment.Status.PENDING).update(
            status=Payment.Status.FAILED)
        payment.refresh_from_db()
        return payment
    if data.get('status') != 'success':
        return payment
    if int(data.get('amount') or 0) != payment.amount_kobo or data.get('currency', 'NGN') != 'NGN':
        logger.error('Amount mismatch for %s: paid %s %s, expected %s', reference,
                     data.get('amount'), data.get('currency'), payment.amount_kobo)
        return payment
    return _settle(payment, paid_at=parse_datetime(data.get('paid_at') or '') or timezone.now(),
                   subscription_data=data)


def _settle(payment, *, paid_at, subscription_data=None):
    fee_percent = get_setting('platform_fee_percent')
    fee, net = split(payment.amount_kobo, fee_percent)
    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(id=payment.id)
        if locked.status == Payment.Status.SUCCESS:
            return locked
        locked.status = Payment.Status.SUCCESS
        locked.paid_at = paid_at
        locked.fee_percent = Decimal(str(fee_percent))
        locked.platform_fee_kobo = fee
        locked.creator_amount_kobo = net
        locked.save(update_fields=['status', 'paid_at', 'fee_percent', 'platform_fee_kobo',
                                   'creator_amount_kobo'])
        kind = (CreatorEarning.Kind.TIP if locked.kind == Payment.Kind.TIP
                else CreatorEarning.Kind.MEMBERSHIP)
        _credit(creator_id=locked.creator_id, kind=kind, amount_kobo=net, payment=locked,
                description=f'{locked.get_kind_display()} {naira(locked.amount_kobo)} '
                            f'(platform fee {naira(fee)})')
        if locked.kind == Payment.Kind.MEMBERSHIP and locked.membership_id:
            _activate_membership(locked.membership_id, paid_at)

    _after_settlement(locked)
    return locked


def _after_settlement(payment):
    from accounts.display import display_name
    payer = display_name(payment.payer) if payment.payer else 'Someone'
    if payment.kind == Payment.Kind.TIP:
        note = f' "{payment.message}"' if payment.message else ''
        _notify(payment.creator, 'tip_received', 'You received a tip',
                f'{payer} tipped you {naira(payment.amount_kobo)}.{note}',
                {'payment_id': str(payment.id), 'amount_kobo': payment.amount_kobo})
        if payment.livestream_id:
            from livestreams.realtime import broadcast
            broadcast(payment.livestream_id, 'tip', from_name=payer,
                      amount_kobo=payment.amount_kobo, message=payment.message)
    elif payment.membership_id:
        _notify(payment.creator, 'membership_payment', 'Membership payment',
                f'{payer} paid {naira(payment.amount_kobo)} for your channel membership.',
                {'payment_id': str(payment.id), 'membership_id': str(payment.membership_id)})


# ── Memberships ───────────────────────────────────────────────────────────────

def set_membership_plan(channel, price_kobo, is_active=True):
    refusal = earning_refusal(channel.user)
    if refusal:
        raise MonetizationError(refusal)
    if price_kobo < 10_000:
        raise MonetizationError('The monthly price must be at least ₦100.')
    plan = MembershipPlan.objects.filter(channel=channel).first()
    code = plan.paystack_plan_code if plan else None
    if not plan or plan.price_kobo != price_kobo or not code:
        # A new price is a new Paystack plan; existing members keep theirs.
        try:
            code = paystack.create_plan(name=f'{channel.channel_name} membership',
                                        amount_kobo=price_kobo)['plan_code']
        except paystack.PaystackError as exc:
            logger.error('Paystack plan creation failed for channel %s: %s', channel.id, exc)
            raise MonetizationError('Payments are temporarily unavailable. Please try again.')
    plan, _ = MembershipPlan.objects.update_or_create(
        channel=channel, defaults={'price_kobo': price_kobo, 'paystack_plan_code': code,
                                   'is_active': is_active, 'updated_at': timezone.now()})
    return plan


def live_membership(user, channel):
    if not (user and user.is_authenticated):
        return None
    return Membership.objects.filter(member=user, channel=channel,
                                     status__in=Membership.LIVE).first()


def has_member_access(user, creator):
    """Does `user` have members-only access to `creator`'s videos?"""
    if not (user and user.is_authenticated):
        return False
    if user.id == creator.id:
        return True
    now = timezone.now()
    return any(m.grants_access(now) for m in Membership.objects.filter(
        member=user, channel__user=creator, status__in=Membership.LIVE))


def start_membership(member, channel):
    plan = MembershipPlan.objects.filter(channel=channel, is_active=True).first()
    if plan is None or not plan.paystack_plan_code:
        raise MonetizationError("This channel doesn't offer memberships.")
    if channel.user_id == member.id:
        raise MonetizationError("You can't join your own channel.")
    refusal = earning_refusal(channel.user)
    if refusal:
        raise MonetizationError(refusal)
    if live_membership(member, channel):
        raise MonetizationError("You're already a member of this channel.")

    membership = Membership.objects.create(
        member=member, channel=channel, price_kobo=plan.price_kobo,
        paystack_plan_code=plan.paystack_plan_code)
    payment = Payment.objects.create(
        kind=Payment.Kind.MEMBERSHIP, payer=member, creator=channel.user,
        amount_kobo=plan.price_kobo, membership=membership,
        provider_reference=f'mem_{uuid.uuid4().hex}')
    return membership, _checkout(payment, member.email, plan=plan.paystack_plan_code)


def _activate_membership(membership_id, paid_at):
    membership = Membership.objects.select_for_update().get(id=membership_id)
    first = membership.status == Membership.Status.PENDING
    period_end = max(membership.current_period_end or paid_at, paid_at) + MEMBERSHIP_PERIOD
    membership.status = Membership.Status.ACTIVE
    membership.started_at = membership.started_at or paid_at
    membership.current_period_end = period_end
    membership.save(update_fields=['status', 'started_at', 'current_period_end'])
    if first:
        from accounts.display import display_name
        _notify(membership.channel.user, 'new_member', 'New channel member',
                f'{display_name(membership.member)} joined your channel membership.',
                {'membership_id': str(membership.id)})


def cancel_membership(membership):
    if membership.status not in Membership.LIVE and membership.status != Membership.Status.PENDING:
        raise MonetizationError('This membership is already cancelled.')
    if membership.paystack_subscription_code and membership.paystack_email_token:
        try:
            paystack.disable_subscription(code=membership.paystack_subscription_code,
                                          email_token=membership.paystack_email_token)
        except paystack.PaystackError as exc:
            logger.error('Paystack disable failed for membership %s: %s', membership.id, exc)
            raise MonetizationError('Could not cancel right now. Please try again.')
    now = timezone.now()
    status = (Membership.Status.NON_RENEWING if membership.current_period_end
              and membership.current_period_end > now else Membership.Status.CANCELLED)
    Membership.objects.filter(id=membership.id).update(status=status, cancelled_at=now)
    membership.refresh_from_db()
    return membership


def _membership_for(plan_code, email):
    return (Membership.objects.filter(paystack_plan_code=plan_code, member__email__iexact=email)
            .exclude(status=Membership.Status.CANCELLED).order_by('-created_at').first())


# ── Payouts ───────────────────────────────────────────────────────────────────

def set_payout_account(creator, bank_code, account_number):
    refusal = earning_refusal(creator)
    if refusal:
        raise MonetizationError(refusal)
    account_number = ''.join(ch for ch in str(account_number) if ch.isdigit())
    if len(account_number) != 10:
        raise MonetizationError('Enter a 10-digit NUBAN account number.')
    try:
        resolved = paystack.resolve_account(account_number=account_number, bank_code=bank_code)
        recipient = paystack.create_transfer_recipient(
            name=resolved['account_name'], account_number=account_number, bank_code=bank_code)
    except paystack.PaystackError as exc:
        raise MonetizationError(f'Could not verify that bank account: {exc}')
    account, _ = PayoutAccount.objects.update_or_create(
        creator=creator, defaults={
            'bank_code': bank_code,
            'bank_name': (recipient.get('details') or {}).get('bank_name'),
            'account_number_last4': account_number[-4:],
            'account_name': resolved['account_name'],
            'paystack_recipient_code': recipient['recipient_code'],
            'updated_at': timezone.now()})
    return account


def request_payout(creator, amount_kobo):
    account = PayoutAccount.objects.filter(creator=creator).first()
    if account is None:
        raise MonetizationError('Add a bank account first.')
    minimum = int(get_setting('min_payout_kobo'))
    if amount_kobo < minimum:
        raise MonetizationError(f'The minimum payout is {naira(minimum)}.')

    with transaction.atomic():
        # Serialise payouts per creator so two requests can't both spend the balance.
        PayoutAccount.objects.select_for_update().get(creator=creator)
        available = balance_kobo(creator)
        if amount_kobo > available:
            raise MonetizationError(f'Your available balance is {naira(available)}.')
        payout = Payout.objects.create(creator=creator, amount_kobo=amount_kobo,
                                       reference=f'payout_{uuid.uuid4().hex}')
        _credit(creator=creator, kind=CreatorEarning.Kind.PAYOUT, amount_kobo=-amount_kobo,
                payout=payout, description=f'Payout to {account.bank_name or "bank"} '
                                           f'••••{account.account_number_last4}')

    try:
        data = paystack.initiate_transfer(
            amount_kobo=amount_kobo, recipient_code=account.paystack_recipient_code,
            reference=payout.reference, reason='Abia Stream creator payout')
    except paystack.PaystackError as exc:
        _payout_failed(payout, str(exc))
        raise MonetizationError(f'The payout could not be sent: {exc}')

    status = {'success': Payout.Status.PAID, 'otp': Payout.Status.AWAITING_OTP}.get(
        data.get('status'), Payout.Status.PROCESSING)
    Payout.objects.filter(id=payout.id).update(
        status=status, paystack_transfer_code=data.get('transfer_code'),
        completed_at=timezone.now() if status == Payout.Status.PAID else None)
    payout.refresh_from_db()
    return payout


def _payout_failed(payout, reason, status=Payout.Status.FAILED):
    with transaction.atomic():
        locked = Payout.objects.select_for_update().get(id=payout.id)
        if locked.status in (Payout.Status.FAILED, Payout.Status.REVERSED):
            return
        locked.status = status
        locked.failure_reason = reason[:500]
        locked.completed_at = timezone.now()
        locked.save(update_fields=['status', 'failure_reason', 'completed_at'])
        _credit(creator_id=locked.creator_id, kind=CreatorEarning.Kind.PAYOUT_REVERSAL,
                amount_kobo=locked.amount_kobo, payout=locked,
                description=f'Payout {status}: returned to balance')
    _notify(locked.creator, 'payout_failed', 'Payout not completed',
            f'Your payout of {naira(locked.amount_kobo)} could not be completed and is back in '
            'your balance.', {'payout_id': str(locked.id)})


# ── Ad revenue share ──────────────────────────────────────────────────────────

def ad_allocations(period_start, period_end, pool_kobo):
    """
    [(creator_id, watch_seconds, amount_kobo)] — the pool split by watch time on
    monetized videos of eligible creators within the period (largest-remainder
    rounding, so the amounts add up to the pool exactly).
    """
    from accounts.models import User
    from playback.models import ViewLog

    start = timezone.make_aware(datetime.combine(period_start, time.min))
    end = timezone.make_aware(datetime.combine(period_end + timedelta(days=1), time.min))
    rows = (ViewLog.objects.filter(timestamp__gte=start, timestamp__lt=end,
                                   video__is_monetized=True,
                                   video__creator__status=User.Status.ACTIVE,
                                   video__creator__verification_status=User.VerificationStatus.APPROVED,
                                   video__creator__channel__isnull=False)
            .values('video__creator_id').annotate(seconds=Sum('watch_duration_seconds'))
            .filter(seconds__gt=0).order_by('video__creator_id'))
    totals = [(r['video__creator_id'], int(r['seconds'])) for r in rows]
    grand = sum(s for _, s in totals)
    if not grand or not pool_kobo:
        return [(cid, s, 0) for cid, s in totals]
    exact = [(cid, s, Decimal(pool_kobo) * s / grand) for cid, s in totals]
    floors = [(cid, s, int(x), x - int(x)) for cid, s, x in exact]
    leftover = pool_kobo - sum(f for _, _, f, _ in floors)
    bonus = {cid for cid, _, _, _ in sorted(floors, key=lambda t: (-t[3], str(t[0])))[:leftover]}
    return [(cid, s, f + (1 if cid in bonus else 0)) for cid, s, f, _ in floors]


def create_ad_period(admin, period_start, period_end, gross_kobo, notes=None):
    if period_end < period_start:
        raise MonetizationError('period_end is before period_start.')
    fee_percent = get_setting('platform_fee_percent')
    fee, pool = split(gross_kobo, fee_percent)
    return AdRevenuePeriod.objects.create(
        period_start=period_start, period_end=period_end, gross_revenue_kobo=gross_kobo,
        platform_fee_percent=Decimal(str(fee_percent)), creator_pool_kobo=pool,
        notes=notes, created_by=admin)


def distribute_ad_period(period):
    with transaction.atomic():
        locked = AdRevenuePeriod.objects.select_for_update().get(id=period.id)
        if locked.status == AdRevenuePeriod.Status.DISTRIBUTED:
            raise MonetizationError('This period has already been distributed.')
        allocations = ad_allocations(locked.period_start, locked.period_end, locked.creator_pool_kobo)
        credited = []
        for creator_id, seconds, amount in allocations:
            if amount <= 0:
                continue
            row = _credit(creator_id=creator_id, kind=CreatorEarning.Kind.AD_SHARE, amount_kobo=amount,
                          ad_period=locked, description=f'Ad revenue {locked.period_start} – '
                                                        f'{locked.period_end} ({seconds // 60} min watched)')
            if row:
                credited.append(row)
        locked.status = AdRevenuePeriod.Status.DISTRIBUTED
        locked.distributed_at = timezone.now()
        locked.save(update_fields=['status', 'distributed_at'])
    for row in credited:
        _notify(row.creator, 'ad_share_credited', 'Ad revenue share',
                f'You earned {naira(row.amount_kobo)} in ad revenue.', {'ad_period_id': locked.id})
    return locked, credited


# ── Webhooks ──────────────────────────────────────────────────────────────────

def handle_webhook(payload):
    """Record and process one verified Paystack event, exactly once."""
    event = payload.get('event') or ''
    data = payload.get('data') or {}
    data_id = str(data.get('id') or data.get('reference') or data.get('subscription_code') or '')
    try:
        with transaction.atomic():
            record = PaystackEvent.objects.create(event=event, data_id=data_id,
                                                  reference=data.get('reference'), payload=payload)
    except IntegrityError:
        return 'duplicate'

    try:
        _dispatch(event, data)
        PaystackEvent.objects.filter(id=record.id).update(processed_at=timezone.now())
        return 'processed'
    except Exception as exc:  # noqa: BLE001 - keep the record; answer 200 so Paystack stops retrying
        logger.exception('Paystack event %s failed', event)
        PaystackEvent.objects.filter(id=record.id).update(error=str(exc)[:1000])
        return 'error'


def _dispatch(event, data):
    if event == 'charge.success':
        reference = data.get('reference')
        if Payment.objects.filter(provider_reference=reference).exists():
            confirm_payment(reference)
        elif (data.get('plan') or {}).get('plan_code'):
            _renewal(data)
    elif event == 'subscription.create':
        membership = _membership_for((data.get('plan') or {}).get('plan_code'),
                                     (data.get('customer') or {}).get('email', ''))
        if membership:
            updates = {'paystack_subscription_code': data.get('subscription_code'),
                       'paystack_email_token': data.get('email_token')}
            next_payment = parse_datetime(data.get('next_payment_date') or '')
            if next_payment:
                updates['current_period_end'] = next_payment
            Membership.objects.filter(id=membership.id).update(**updates)
    elif event in ('subscription.disable', 'subscription.not_renew'):
        for membership in Membership.objects.filter(
                paystack_subscription_code=data.get('subscription_code')):
            now = timezone.now()
            status = (Membership.Status.NON_RENEWING if membership.current_period_end
                      and membership.current_period_end > now else Membership.Status.CANCELLED)
            Membership.objects.filter(id=membership.id).update(status=status,
                                                               cancelled_at=membership.cancelled_at or now)
    elif event == 'invoice.payment_failed':
        code = (data.get('subscription') or {}).get('subscription_code')
        Membership.objects.filter(paystack_subscription_code=code,
                                  status=Membership.Status.ACTIVE).update(status=Membership.Status.PAST_DUE)
    elif event == 'transfer.success':
        payout = Payout.objects.filter(reference=data.get('reference')).first()
        if payout and payout.status not in (Payout.Status.PAID, Payout.Status.FAILED,
                                            Payout.Status.REVERSED):
            Payout.objects.filter(id=payout.id).update(status=Payout.Status.PAID,
                                                       completed_at=timezone.now())
            _notify(payout.creator, 'payout_paid', 'Payout sent',
                    f'{naira(payout.amount_kobo)} is on its way to your bank account.',
                    {'payout_id': str(payout.id)})
    elif event in ('transfer.failed', 'transfer.reversed'):
        payout = Payout.objects.filter(reference=data.get('reference')).first()
        if payout:
            _payout_failed(payout, data.get('reason') or event,
                           Payout.Status.REVERSED if event == 'transfer.reversed' else Payout.Status.FAILED)


def _renewal(data):
    """A recurring membership charge (not initialised by us): record and credit it."""
    membership = _membership_for(data['plan']['plan_code'], (data.get('customer') or {}).get('email', ''))
    if membership is None:
        logger.warning('Renewal charge %s matches no membership', data.get('reference'))
        return
    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                kind=Payment.Kind.MEMBERSHIP, payer=membership.member, creator=membership.channel.user,
                amount_kobo=int(data.get('amount') or 0), membership=membership,
                provider_reference=data['reference'])
    except IntegrityError:
        return  # already recorded
    confirm_payment(payment.provider_reference)


# ── Reporting ─────────────────────────────────────────────────────────────────

def earnings_summary(creator, since=None):
    entries = CreatorEarning.objects.filter(creator=creator)
    if since:
        entries = entries.filter(created_at__gte=since)
    by_kind = {k: v for k, v in entries.values_list('kind').annotate(total=Sum('amount_kobo'))}
    earned = sum(v for k, v in by_kind.items() if k in ('tip', 'membership', 'ad_share', 'adjustment'))
    return {'earned_kobo': earned, 'by_source_kobo': by_kind}


def pending_payouts_kobo(creator):
    return Payout.objects.filter(creator=creator, status__in=[
        Payout.Status.PENDING, Payout.Status.PROCESSING, Payout.Status.AWAITING_OTP,
    ]).aggregate(total=Sum('amount_kobo'))['total'] or 0


def platform_totals(since=None):
    payments = Payment.objects.filter(status=Payment.Status.SUCCESS)
    if since:
        payments = payments.filter(paid_at__gte=since)
    totals = payments.aggregate(gross=Sum('amount_kobo'), fees=Sum('platform_fee_kobo'),
                                to_creators=Sum('creator_amount_kobo'))
    return {
        'gross_kobo': totals['gross'] or 0, 'platform_fees_kobo': totals['fees'] or 0,
        'creator_share_kobo': totals['to_creators'] or 0,
        'tips': payments.filter(kind=Payment.Kind.TIP).count(),
        'membership_payments': payments.filter(kind=Payment.Kind.MEMBERSHIP).count(),
        'active_memberships': Membership.objects.filter(status=Membership.Status.ACTIVE).count(),
        'payouts_pending_kobo': Payout.objects.filter(Q(status=Payout.Status.PENDING) | Q(
            status=Payout.Status.PROCESSING) | Q(status=Payout.Status.AWAITING_OTP))
        .aggregate(total=Sum('amount_kobo'))['total'] or 0,
    }
