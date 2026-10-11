"""Monetization tables (sql/011_monetization.sql). All money is integer kobo."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class PlatformSetting(models.Model):
    key = models.TextField(primary_key=True)
    value = models.JSONField()
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, db_column='updated_by', related_name='+')
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'platform_settings'


class MembershipPlan(models.Model):
    channel = models.OneToOneField('creator_channels.CreatorChannel', on_delete=models.CASCADE,
                                   primary_key=True, db_column='channel_id', related_name='membership_plan')
    price_kobo = models.BigIntegerField()
    paystack_plan_code = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'membership_plans'


class Membership(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending payment'
        ACTIVE = 'active', 'Active'
        NON_RENEWING = 'non_renewing', 'Cancelled, active until period end'
        PAST_DUE = 'past_due', 'Payment failed'
        CANCELLED = 'cancelled', 'Cancelled'

    LIVE = (Status.ACTIVE, Status.NON_RENEWING, Status.PAST_DUE)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               db_column='member_id', related_name='memberships')
    channel = models.ForeignKey('creator_channels.CreatorChannel', on_delete=models.CASCADE,
                                db_column='channel_id', related_name='memberships')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    price_kobo = models.BigIntegerField()
    paystack_plan_code = models.TextField(null=True, blank=True)
    paystack_subscription_code = models.TextField(null=True, blank=True)
    paystack_email_token = models.TextField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'memberships'
        ordering = ['-created_at']

    def grants_access(self, now=None):
        now = now or timezone.now()
        if self.status == self.Status.ACTIVE:
            return True
        # Cancelled-but-paid and failed-renewal members keep access until the
        # period they paid for ends.
        return (self.status in (self.Status.NON_RENEWING, self.Status.PAST_DUE)
                and self.current_period_end is not None and self.current_period_end > now)


class Payment(models.Model):
    class Kind(models.TextChoices):
        TIP = 'tip', 'Tip'
        MEMBERSHIP = 'membership', 'Membership'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    payer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                              blank=True, db_column='payer_id', related_name='payments_made')
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                db_column='creator_id', related_name='payments_received')
    amount_kobo = models.BigIntegerField()
    currency = models.CharField(max_length=3, default='NGN')
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    platform_fee_kobo = models.BigIntegerField(null=True, blank=True)
    creator_amount_kobo = models.BigIntegerField(null=True, blank=True)
    video = models.ForeignKey('videos.Video', on_delete=models.SET_NULL, null=True, blank=True,
                              db_column='video_id', related_name='payments')
    livestream = models.ForeignKey('livestreams.LiveStream', on_delete=models.SET_NULL, null=True,
                                   blank=True, db_column='livestream_id', related_name='payments')
    membership = models.ForeignKey(Membership, on_delete=models.SET_NULL, null=True, blank=True,
                                   db_column='membership_id', related_name='payments')
    message = models.TextField(null=True, blank=True)
    provider_reference = models.TextField(unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'payments'
        ordering = ['-created_at']


class PayoutAccount(models.Model):
    creator = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True,
                                   db_column='creator_id', related_name='payout_account')
    bank_code = models.TextField()
    bank_name = models.TextField(null=True, blank=True)
    account_number_last4 = models.TextField()
    account_name = models.TextField()
    paystack_recipient_code = models.TextField()
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'payout_accounts'


class Payout(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        AWAITING_OTP = 'awaiting_otp', 'Awaiting OTP approval in Paystack'
        PAID = 'paid', 'Paid'
        FAILED = 'failed', 'Failed'
        REVERSED = 'reversed', 'Reversed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                db_column='creator_id', related_name='payouts')
    amount_kobo = models.BigIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reference = models.TextField(unique=True)
    paystack_transfer_code = models.TextField(null=True, blank=True)
    failure_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'payouts'
        ordering = ['-created_at']


class AdRevenuePeriod(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        DISTRIBUTED = 'distributed', 'Distributed'

    id = models.BigAutoField(primary_key=True)
    period_start = models.DateField()
    period_end = models.DateField()
    gross_revenue_kobo = models.BigIntegerField()
    platform_fee_percent = models.DecimalField(max_digits=5, decimal_places=2)
    creator_pool_kobo = models.BigIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   blank=True, db_column='created_by', related_name='+')
    created_at = models.DateTimeField(default=timezone.now)
    distributed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'ad_revenue_periods'
        ordering = ['-period_start']


class CreatorEarning(models.Model):
    class Kind(models.TextChoices):
        TIP = 'tip', 'Tip'
        MEMBERSHIP = 'membership', 'Membership'
        AD_SHARE = 'ad_share', 'Ad revenue share'
        PAYOUT = 'payout', 'Payout'
        PAYOUT_REVERSAL = 'payout_reversal', 'Payout returned'
        ADJUSTMENT = 'adjustment', 'Adjustment'

    id = models.BigAutoField(primary_key=True)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                db_column='creator_id', related_name='earnings')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount_kobo = models.BigIntegerField()
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True,
                                db_column='payment_id', related_name='+')
    payout = models.ForeignKey(Payout, on_delete=models.SET_NULL, null=True, blank=True,
                               db_column='payout_id', related_name='+')
    ad_period = models.ForeignKey(AdRevenuePeriod, on_delete=models.SET_NULL, null=True, blank=True,
                                  db_column='ad_period_id', related_name='+')
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'creator_earnings'
        ordering = ['-created_at']


class PaystackEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    event = models.TextField()
    data_id = models.TextField()
    reference = models.TextField(null=True, blank=True)
    payload = models.JSONField()
    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'paystack_events'
        unique_together = ('event', 'data_id')
