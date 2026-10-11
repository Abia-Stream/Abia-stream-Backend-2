import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from abiastream.testing import client_for, make_user, make_video
from accounts.models import User
from creator_channels.models import CreatorChannel
from monetization import paystack, services
from monetization.models import (
    AdRevenuePeriod, CreatorEarning, Membership, Payment, Payout, PaystackEvent,
)
from notifications.models import Notification
from playback.models import ViewLog
from videos.models import Video

SECRET = 'sk_test_unit_tests_only'


class FakePaystack:
    """Stands in for the Paystack API; records calls, returns spec-shaped data."""

    def __init__(self):
        self.calls = []
        self.transactions = {}      # reference -> {'amount', 'status', 'plan'}
        self.fail = None            # name of a call that should raise
        self.transfer_status = 'pending'

    def _call(self, call, **kw):
        self.calls.append((call, kw))
        if self.fail == call:
            raise paystack.PaystackError('paystack is down')

    def initialize_transaction(self, *, email, amount_kobo, reference, metadata, plan=None, callback_url=None):
        self._call('initialize', reference=reference, plan=plan, amount=amount_kobo)
        self.transactions[reference] = {'amount': amount_kobo, 'status': 'abandoned', 'plan': plan}
        return {'authorization_url': f'https://checkout.paystack.com/{reference}',
                'access_code': 'ac_' + reference[-6:], 'reference': reference}

    def pay(self, reference, amount=None):
        txn = self.transactions.setdefault(reference, {'amount': amount, 'plan': None})
        txn['status'] = 'success'
        if amount is not None:
            txn['amount'] = amount

    def verify_transaction(self, reference):
        self._call('verify', reference=reference)
        txn = self.transactions.get(reference, {'status': 'failed', 'amount': 0})
        return {'status': txn['status'], 'amount': txn['amount'], 'currency': 'NGN',
                'reference': reference, 'paid_at': timezone.now().isoformat()}

    def create_plan(self, *, name, amount_kobo, interval='monthly'):
        self._call('create_plan', amount=amount_kobo)
        return {'plan_code': f'PLN_{uuid.uuid4().hex[:8]}', 'amount': amount_kobo}

    def disable_subscription(self, *, code, email_token):
        self._call('disable', code=code, token=email_token)
        return {}

    def list_banks(self):
        self._call('banks')
        return [{'name': 'Access Bank', 'code': '044'}, {'name': 'GTBank', 'code': '058'}]

    def resolve_account(self, *, account_number, bank_code):
        self._call('resolve', account_number=account_number)
        return {'account_name': 'ADA OBI', 'account_number': account_number}

    def create_transfer_recipient(self, *, name, account_number, bank_code):
        self._call('recipient', name=name)
        return {'recipient_code': 'RCP_test123', 'details': {'bank_name': 'GTBank'}}

    def initiate_transfer(self, *, amount_kobo, recipient_code, reference, reason):
        self._call('transfer', amount=amount_kobo, reference=reference)
        return {'status': self.transfer_status, 'transfer_code': 'TRF_' + reference[-6:],
                'reference': reference}


def verified_creator(**extra):
    user = make_user(role=User.Role.CREATOR, verification_status=User.VerificationStatus.APPROVED, **extra)
    CreatorChannel.objects.create(user=user, channel_name=f'Chan {user.id.hex[:6]}',
                                  channel_slug=f'chan-{user.id.hex[:6]}')
    return user


def webhook(event, data, secret=SECRET):
    body = json.dumps({'event': event, 'data': data}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return client_for().post('/api/v1/monetization/paystack/webhook/', body,
                             content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=sig)


class PaystackTestCase(TestCase):

    def setUp(self):
        self.ps = FakePaystack()
        for name in ('initialize_transaction', 'verify_transaction', 'create_plan',
                     'disable_subscription', 'list_banks', 'resolve_account',
                     'create_transfer_recipient', 'initiate_transfer'):
            patcher = mock.patch.object(paystack, name, getattr(self.ps, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.creator = verified_creator()
        self.fan = make_user()

    def tip(self, amount=50_000, **target):
        target = target or {'creator_id': str(self.creator.id)}
        return client_for(self.fan).post('/api/v1/monetization/tips/',
                                         {'amount_kobo': amount, **target}, format='json')

    def charge_success(self, reference, amount, data_id=None, **extra):
        return webhook('charge.success', {'id': data_id or uuid.uuid4().int % 10**9,
                                          'reference': reference, 'amount': amount,
                                          'status': 'success', 'currency': 'NGN', **extra})


class FeeTests(TestCase):

    def test_split_rounds_half_up_to_the_kobo(self):
        self.assertEqual(services.split(50_000, 20), (10_000, 40_000))
        self.assertEqual(services.split(10_001, 20), (2_000, 8_001))     # 2000.2 -> 2000
        self.assertEqual(services.split(10_003, 12.5), (1_250, 8_753))   # 1250.375 -> 1250
        self.assertEqual(services.split(10_004, 12.5), (1_251, 8_753))   # 1250.5 -> 1251
        self.assertEqual(services.split(1_000, 0), (0, 1_000))


class TipTests(PaystackTestCase):

    def test_tip_credits_creator_once_after_paystack_confirms(self):
        response = self.tip(50_000, video_id=str(make_video(self.creator).id))
        self.assertEqual(response.status_code, 201, response.content)
        ref = response.json()['reference']
        self.assertTrue(response.json()['authorization_url'].startswith('https://checkout.paystack.com/'))
        self.assertEqual(services.balance_kobo(self.creator), 0)       # nothing until paid

        self.ps.pay(ref)
        self.assertEqual(self.charge_success(ref, 50_000, data_id=1).status_code, 200)
        self.assertEqual(self.charge_success(ref, 50_000, data_id=1).json()['result'], 'duplicate')
        self.charge_success(ref, 50_000, data_id=2)                     # same charge, new event id

        payment = Payment.objects.get(provider_reference=ref)
        self.assertEqual((payment.status, payment.platform_fee_kobo, payment.creator_amount_kobo),
                         ('success', 10_000, 40_000))
        self.assertEqual(services.balance_kobo(self.creator), 40_000)
        self.assertEqual(CreatorEarning.objects.filter(payment=payment).count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.creator,
                                                    notification_type='tip_received').exists())

    def test_redirect_check_settles_too(self):
        ref = self.tip().json()['reference']
        self.ps.pay(ref)
        data = client_for(self.fan).get(f'/api/v1/monetization/payments/{ref}/').json()
        self.assertEqual(data['status'], 'success')
        self.charge_success(ref, 50_000)                                # webhook arrives later
        self.assertEqual(services.balance_kobo(self.creator), 40_000)

    def test_forged_or_unsigned_webhook_rejected(self):
        ref = self.tip().json()['reference']
        self.ps.pay(ref)
        forged = webhook('charge.success', {'id': 9, 'reference': ref, 'amount': 50_000},
                         secret='sk_test_attacker')
        self.assertEqual(forged.status_code, 401)
        unsigned = client_for().post('/api/v1/monetization/paystack/webhook/',
                                     {'event': 'charge.success'}, format='json')
        self.assertEqual(unsigned.status_code, 401)
        self.assertEqual(services.balance_kobo(self.creator), 0)
        self.assertFalse(PaystackEvent.objects.exists())

    def test_webhook_alone_is_not_trusted(self):
        # A correctly signed event for a charge Paystack says never succeeded.
        ref = self.tip().json()['reference']
        self.charge_success(ref, 50_000)
        self.assertEqual(Payment.objects.get(provider_reference=ref).status, 'failed')
        self.assertEqual(services.balance_kobo(self.creator), 0)

    def test_amount_mismatch_not_credited(self):
        ref = self.tip(50_000).json()['reference']
        self.ps.pay(ref, amount=100)          # paid far less than initialised
        self.charge_success(ref, 100)
        self.assertEqual(Payment.objects.get(provider_reference=ref).status, 'pending')
        self.assertEqual(services.balance_kobo(self.creator), 0)

    def test_rules(self):
        self.assertEqual(self.tip(5_000).status_code, 400)                       # below ₦100
        self.assertEqual(client_for(self.creator).post('/api/v1/monetization/tips/', {
            'amount_kobo': 50_000, 'creator_id': str(self.creator.id)}, format='json').status_code, 400)
        unverified = make_user()
        self.assertEqual(self.tip(creator_id=str(unverified.id)).status_code, 400)
        self.assertEqual(client_for().post('/api/v1/monetization/tips/', {}, format='json').status_code, 401)

    def test_paystack_down_is_a_clean_error(self):
        self.ps.fail = 'initialize'
        response = self.tip()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Payment.objects.get().status, 'failed')

    def test_fee_change_applies_to_new_payments_only(self):
        first = self.tip().json()['reference']
        self.ps.pay(first)
        self.charge_success(first, 50_000)
        services.set_setting('platform_fee_percent', 10, None)
        second = self.tip().json()['reference']
        self.ps.pay(second)
        self.charge_success(second, 50_000)
        fees = dict(Payment.objects.values_list('provider_reference', 'platform_fee_kobo'))
        self.assertEqual((fees[first], fees[second]), (10_000, 5_000))

    def test_livestream_tip_is_broadcast(self):
        from livestreams.models import LiveStream
        stream = LiveStream.objects.create(creator=self.creator, title='Live', stream_key='k1')
        ref = self.tip(livestream_id=str(stream.id)).json()['reference']
        self.ps.pay(ref)
        with mock.patch('livestreams.realtime.broadcast') as broadcast:
            self.charge_success(ref, 50_000)
        self.assertEqual(broadcast.call_args.args[1], 'tip')
        self.assertEqual(broadcast.call_args.kwargs['amount_kobo'], 50_000)


class MembershipTests(PaystackTestCase):

    def setUp(self):
        super().setUp()
        self.channel = self.creator.channel
        response = client_for(self.creator).put('/api/v1/channels/me/membership/',
                                                {'price_kobo': 150_000}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.plan_code = self.channel.membership_plan.paystack_plan_code

    def join(self, user=None):
        return client_for(user or self.fan).post(
            f'/api/v1/channels/{self.channel.channel_slug}/membership/join/')

    def activate(self):
        response = self.join()
        ref = response.json()['reference']
        self.ps.pay(ref)
        self.charge_success(ref, 150_000, plan={'plan_code': self.plan_code},
                            customer={'email': self.fan.email})
        return Membership.objects.get(member=self.fan)

    def test_join_activates_and_credits(self):
        membership = self.activate()
        self.assertEqual(membership.status, 'active')
        self.assertGreater(membership.current_period_end, timezone.now() + timedelta(days=29))
        self.assertEqual(services.balance_kobo(self.creator), 120_000)   # 80% of ₦1,500
        self.assertEqual(self.ps.calls[1][1]['plan'], self.plan_code)
        info = client_for(self.fan).get(f'/api/v1/channels/{self.channel.channel_slug}/membership/').json()
        self.assertTrue(info['offers_membership'])
        self.assertEqual(info['membership']['status'], 'active')

    def test_members_only_video_access(self):
        video = make_video(self.creator, visibility=Video.Visibility.MEMBERS_ONLY)
        url = f'/api/v1/videos/{video.id}/'
        self.assertEqual(client_for(self.fan).get(url).status_code, 403)
        self.assertEqual(client_for().get(url).status_code, 403)
        self.activate()
        self.assertEqual(client_for(self.fan).get(url).status_code, 200)
        self.assertEqual(client_for(self.creator).get(url).status_code, 200)
        # Members-only videos never appear in public lists.
        self.assertEqual(client_for(self.fan).get('/api/v1/videos/').json()['pagination']['total'], 0)

    def test_subscription_lifecycle(self):
        membership = self.activate()
        webhook('subscription.create', {'id': 77, 'subscription_code': 'SUB_abc', 'email_token': 'tok_1',
                                        'plan': {'plan_code': self.plan_code},
                                        'customer': {'email': self.fan.email},
                                        'next_payment_date': (timezone.now() + timedelta(days=30)).isoformat()})
        membership.refresh_from_db()
        self.assertEqual((membership.paystack_subscription_code, membership.paystack_email_token),
                         ('SUB_abc', 'tok_1'))

        # Monthly renewal: a charge we didn't initialise, matched by plan + email.
        before = membership.current_period_end
        self.ps.pay('renewal_ref_1', amount=150_000)
        self.charge_success('renewal_ref_1', 150_000, plan={'plan_code': self.plan_code},
                            customer={'email': self.fan.email})
        self.charge_success('renewal_ref_1', 150_000, plan={'plan_code': self.plan_code},
                            customer={'email': self.fan.email})              # duplicate delivery
        membership.refresh_from_db()
        self.assertGreater(membership.current_period_end, before)
        self.assertEqual(services.balance_kobo(self.creator), 240_000)

        webhook('invoice.payment_failed', {'id': 78, 'subscription': {'subscription_code': 'SUB_abc'}})
        membership.refresh_from_db()
        self.assertEqual(membership.status, 'past_due')
        self.assertTrue(membership.grants_access())          # paid period not over yet

    def test_cancel_keeps_access_until_period_end(self):
        membership = self.activate()
        Membership.objects.filter(id=membership.id).update(paystack_subscription_code='SUB_x',
                                                           paystack_email_token='tok_x')
        data = client_for(self.fan).post(f'/api/v1/monetization/memberships/{membership.id}/cancel/').json()
        self.assertEqual(data['status'], 'non_renewing')
        self.assertTrue(data['has_access'])
        self.assertIn(('disable', {'code': 'SUB_x', 'token': 'tok_x'}), self.ps.calls)

        video = make_video(self.creator, visibility=Video.Visibility.MEMBERS_ONLY)
        Membership.objects.filter(id=membership.id).update(
            current_period_end=timezone.now() - timedelta(minutes=1))
        self.assertEqual(client_for(self.fan).get(f'/api/v1/videos/{video.id}/').status_code, 403)

    def test_join_rules(self):
        self.activate()
        self.assertEqual(self.join().status_code, 400)                          # already a member
        self.assertEqual(self.join(self.creator).status_code, 400)              # own channel
        no_plan = verified_creator()
        self.assertEqual(client_for(self.fan).post(
            f'/api/v1/channels/{no_plan.channel.channel_slug}/membership/join/').status_code, 400)
        unverified = make_user(role=User.Role.CREATOR)
        CreatorChannel.objects.create(user=unverified, channel_name='U', channel_slug='u-chan')
        self.assertEqual(client_for(unverified).put('/api/v1/channels/me/membership/',
                                                    {'price_kobo': 150_000}, format='json').status_code, 400)

    def test_price_change_creates_new_plan_for_new_members(self):
        old_code = self.plan_code
        client_for(self.creator).put('/api/v1/channels/me/membership/', {'price_kobo': 200_000}, format='json')
        self.channel.membership_plan.refresh_from_db()
        self.assertNotEqual(self.channel.membership_plan.paystack_plan_code, old_code)


class PayoutTests(PaystackTestCase):

    def setUp(self):
        super().setUp()
        CreatorEarning.objects.create(creator=self.creator, kind='tip', amount_kobo=500_000)
        self.client_ = client_for(self.creator)
        response = self.client_.put('/api/v1/monetization/payouts/account/',
                                    {'bank_code': '058', 'account_number': '0123456789'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)

    def payout(self, amount):
        return self.client_.post('/api/v1/monetization/payouts/', {'amount_kobo': amount}, format='json')

    def test_account_stores_only_last_four_digits(self):
        data = self.client_.get('/api/v1/monetization/payouts/account/').json()
        self.assertEqual((data['account_number_last4'], data['account_name'], data['bank_name']),
                         ('6789', 'ADA OBI', 'GTBank'))
        self.assertNotIn('0123456789', json.dumps(data))

    def test_payout_then_success(self):
        response = self.payout(300_000)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['status'], 'processing')
        self.assertEqual(services.balance_kobo(self.creator), 200_000)
        webhook('transfer.success', {'id': 5, 'reference': response.json()['reference'], 'amount': 300_000})
        self.assertEqual(Payout.objects.get().status, 'paid')
        self.assertTrue(Notification.objects.filter(user=self.creator, notification_type='payout_paid').exists())

    def test_failed_transfer_returns_money_once(self):
        ref = self.payout(300_000).json()['reference']
        webhook('transfer.failed', {'id': 6, 'reference': ref, 'reason': 'Account closed'})
        webhook('transfer.reversed', {'id': 7, 'reference': ref})
        self.assertEqual(services.balance_kobo(self.creator), 500_000)
        self.assertEqual(Payout.objects.get().status, 'failed')

    def test_limits(self):
        self.assertEqual(self.payout(50_000).status_code, 400)       # below ₦1,000 minimum
        self.assertEqual(self.payout(600_000).status_code, 400)      # above balance
        self.assertEqual(Payout.objects.count(), 0)

    def test_paystack_error_reverses_debit(self):
        self.ps.fail = 'transfer'
        self.assertEqual(self.payout(300_000).status_code, 400)
        self.assertEqual(services.balance_kobo(self.creator), 500_000)
        self.assertEqual(Payout.objects.get().status, 'failed')

    def test_otp_required(self):
        self.ps.transfer_status = 'otp'
        self.assertEqual(self.payout(300_000).json()['status'], 'awaiting_otp')

    def test_earnings_summary(self):
        data = self.client_.get('/api/v1/monetization/earnings/').json()
        self.assertEqual((data['balance_kobo'], data['eligible']), (500_000, True))
        self.assertEqual(data['lifetime']['earned_kobo'], 500_000)
        self.assertEqual(data['results'][0]['kind'], 'tip')


class AdRevenueTests(PaystackTestCase):

    def test_split_by_watch_time_and_distribute_once(self):
        admin = make_user(role=User.Role.ADMIN)
        other = verified_creator()
        unverified = make_user()
        day = timezone.make_aware(timezone.datetime(2026, 10, 5, 12))
        for creator, seconds, monetized in ((self.creator, 3000, True), (other, 1000, True),
                                            (other, 9999, False), (unverified, 5000, True)):
            ViewLog.objects.create(video=make_video(creator, is_monetized=monetized),
                                   watch_duration_seconds=seconds, timestamp=day)
        client = client_for(admin)

        draft = client.post('/api/v1/admin/ad-revenue/', {
            'period_start': '2026-10-01', 'period_end': '2026-10-31',
            'gross_revenue_kobo': 1_000_001}, format='json')
        self.assertEqual(draft.status_code, 201, draft.content)
        data = draft.json()
        self.assertEqual(data['creator_pool_kobo'], 800_001)          # after 20% fee
        amounts = {a['creator_id']: a['amount_kobo'] for a in data['allocations']}
        self.assertEqual(sum(amounts.values()), 800_001)              # adds up exactly
        self.assertEqual(set(amounts), {str(self.creator.id), str(other.id)})
        self.assertEqual(amounts[str(self.creator.id)], 600_001)      # 3/4, largest remainder
        self.assertEqual(services.balance_kobo(self.creator), 0)       # draft credits nothing

        period_id = data['id']
        self.assertEqual(client.post(f'/api/v1/admin/ad-revenue/{period_id}/distribute/').status_code, 200)
        self.assertEqual(client.post(f'/api/v1/admin/ad-revenue/{period_id}/distribute/').status_code, 400)
        self.assertEqual(services.balance_kobo(self.creator), 600_001)
        self.assertEqual(AdRevenuePeriod.objects.get().status, 'distributed')
        # The detail URL is read-only.
        client.post(f'/api/v1/admin/ad-revenue/{period_id}/')
        self.assertEqual(services.balance_kobo(other), 200_000)

    def test_admin_only(self):
        for path in ('/api/v1/admin/ad-revenue/', '/api/v1/admin/monetization/settings/',
                     '/api/v1/admin/monetization/overview/'):
            self.assertEqual(client_for(make_user(role=User.Role.MODERATOR)).get(path).status_code, 403)


class SettingsTests(PaystackTestCase):

    def test_admin_settings_and_overview(self):
        client = client_for(make_user(role=User.Role.ADMIN))
        self.assertEqual(client.get('/api/v1/admin/monetization/settings/').json(),
                         {'platform_fee_percent': 20, 'min_payout_kobo': 100_000})
        self.assertEqual(client.patch('/api/v1/admin/monetization/settings/',
                                      {'platform_fee_percent': 75}, format='json').status_code, 400)
        updated = client.patch('/api/v1/admin/monetization/settings/',
                               {'platform_fee_percent': 15, 'min_payout_kobo': 200_000}, format='json').json()
        self.assertEqual((updated['platform_fee_percent'], updated['min_payout_kobo']), (15, 200_000))

        ref = self.tip().json()['reference']
        self.ps.pay(ref)
        self.charge_success(ref, 50_000)
        overview = client.get('/api/v1/admin/monetization/overview/').json()
        self.assertEqual((overview['gross_kobo'], overview['platform_fees_kobo'], overview['tips']),
                         (50_000, 7_500, 1))

    def test_creator_dashboard_shows_earnings(self):
        CreatorEarning.objects.create(creator=self.creator, kind='tip', amount_kobo=40_000)
        CreatorEarning.objects.create(creator=self.creator, kind='payout', amount_kobo=-10_000)
        data = client_for(self.creator).get('/api/v1/channels/me/dashboard/').json()['summary']
        self.assertEqual((data['recent_earnings'], data['monetization_enabled']), (40_000, True))

    @override_settings(PAYSTACK_SECRET_KEY='')
    def test_not_configured(self):
        self.assertFalse(paystack.signature_valid(b'{}', 'abc'))
        self.assertEqual(webhook('charge.success', {'id': 1}).status_code, 401)
