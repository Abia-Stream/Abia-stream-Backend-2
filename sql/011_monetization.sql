-- 011_monetization.sql
-- Creator monetization on Paystack: tips, paid channel memberships, ad
-- revenue share, payouts, and an earnings ledger (`monetization` app).
-- New tables plus one new video visibility. Additive and idempotent.
-- All money is stored as integer kobo (NGN).

-- ── Members-only videos ───────────────────────────────────────────────────────
-- New visibility for paying channel members. `subscribers_only` (free
-- followers) is deliberately left unchanged.
alter type video_visibility add value if not exists 'members_only';

-- ── Settings (platform fee, minimum payout) ──────────────────────────────────
create table if not exists platform_settings (
    key        text        primary key,
    value      jsonb       not null,
    updated_by uuid        null references users(id) on delete set null,
    updated_at timestamptz not null default now()
);
insert into platform_settings (key, value) values
    ('platform_fee_percent', '20'::jsonb),
    ('min_payout_kobo', '100000'::jsonb)          -- ₦1,000
on conflict (key) do nothing;

-- ── Paid channel memberships ──────────────────────────────────────────────────
create table if not exists membership_plans (
    channel_id         uuid        primary key references creator_channels(id) on delete cascade,
    price_kobo         bigint      not null check (price_kobo >= 10000),   -- ≥ ₦100/month
    paystack_plan_code text        null,
    is_active          boolean     not null default true,
    updated_at         timestamptz not null default now()
);

create table if not exists memberships (
    id                         uuid        primary key default gen_random_uuid(),
    member_id                  uuid        not null references users(id) on delete cascade,
    channel_id                 uuid        not null references creator_channels(id) on delete cascade,
    status                     text        not null default 'pending'
                               check (status in ('pending', 'active', 'non_renewing', 'past_due', 'cancelled')),
    price_kobo                 bigint      not null,
    paystack_plan_code         text        null,
    paystack_subscription_code text        null,
    paystack_email_token       text        null,
    current_period_end         timestamptz null,
    started_at                 timestamptz null,
    cancelled_at               timestamptz null,
    created_at                 timestamptz not null default now()
);
-- One live membership per member per channel.
create unique index if not exists memberships_live_uniq
    on memberships (member_id, channel_id)
    where status in ('active', 'non_renewing', 'past_due');
create index if not exists memberships_channel_idx on memberships (channel_id, status);
create index if not exists memberships_subscription_idx on memberships (paystack_subscription_code);

-- ── Payments (money in) ──────────────────────────────────────────────────────
create table if not exists payments (
    id                  uuid          primary key default gen_random_uuid(),
    kind                text          not null check (kind in ('tip', 'membership')),
    payer_id            uuid          null references users(id) on delete set null,
    creator_id          uuid          not null references users(id) on delete cascade,
    amount_kobo         bigint        not null check (amount_kobo > 0),
    currency            text          not null default 'NGN',
    fee_percent         numeric(5, 2) null,
    platform_fee_kobo   bigint        null,
    creator_amount_kobo bigint        null,
    video_id            uuid          null references videos(id) on delete set null,
    livestream_id       uuid          null references livestreams(id) on delete set null,
    membership_id       uuid          null references memberships(id) on delete set null,
    message             text          null check (char_length(message) <= 200),
    provider_reference  text          not null unique,
    status              text          not null default 'pending'
                        check (status in ('pending', 'success', 'failed')),
    paid_at             timestamptz   null,
    created_at          timestamptz   not null default now()
);
create index if not exists payments_creator_idx on payments (creator_id, created_at desc);

-- ── Payouts (money out) ──────────────────────────────────────────────────────
create table if not exists payout_accounts (
    creator_id              uuid        primary key references users(id) on delete cascade,
    bank_code               text        not null,
    bank_name               text        null,
    account_number_last4    text        not null,
    account_name            text        not null,
    paystack_recipient_code text        not null,
    updated_at              timestamptz not null default now()
);

create table if not exists payouts (
    id                     uuid        primary key default gen_random_uuid(),
    creator_id             uuid        not null references users(id) on delete cascade,
    amount_kobo            bigint      not null check (amount_kobo > 0),
    status                 text        not null default 'pending'
                           check (status in ('pending', 'processing', 'awaiting_otp', 'paid', 'failed', 'reversed')),
    reference              text        not null unique,
    paystack_transfer_code text        null,
    failure_reason         text        null,
    created_at             timestamptz not null default now(),
    completed_at           timestamptz null
);
create index if not exists payouts_creator_idx on payouts (creator_id, created_at desc);

-- ── Ad revenue share ─────────────────────────────────────────────────────────
create table if not exists ad_revenue_periods (
    id                   bigserial     primary key,
    period_start         date          not null,
    period_end           date          not null,
    gross_revenue_kobo   bigint        not null check (gross_revenue_kobo >= 0),
    platform_fee_percent numeric(5, 2) not null,
    creator_pool_kobo    bigint        not null,
    status               text          not null default 'draft' check (status in ('draft', 'distributed')),
    notes                text          null,
    created_by           uuid          null references users(id) on delete set null,
    created_at           timestamptz   not null default now(),
    distributed_at       timestamptz   null,
    check (period_end >= period_start)
);

-- ── Earnings ledger ──────────────────────────────────────────────────────────
-- Every change to a creator's balance is one row; balance = sum(amount_kobo).
-- Credits are positive, payouts negative, a failed payout is credited back.
create table if not exists creator_earnings (
    id           bigserial   primary key,
    creator_id   uuid        not null references users(id) on delete cascade,
    kind         text        not null
                 check (kind in ('tip', 'membership', 'ad_share', 'payout', 'payout_reversal', 'adjustment')),
    amount_kobo  bigint      not null,
    payment_id   uuid        null references payments(id) on delete set null,
    payout_id    uuid        null references payouts(id) on delete set null,
    ad_period_id bigint      null references ad_revenue_periods(id) on delete set null,
    description  text        null,
    created_at   timestamptz not null default now()
);
create index if not exists creator_earnings_creator_idx on creator_earnings (creator_id, created_at desc);
-- Idempotency: each payment, payout step and ad period credits a creator once.
create unique index if not exists creator_earnings_payment_uniq
    on creator_earnings (payment_id) where payment_id is not null;
create unique index if not exists creator_earnings_payout_uniq
    on creator_earnings (payout_id, kind) where payout_id is not null;
create unique index if not exists creator_earnings_ad_uniq
    on creator_earnings (ad_period_id, creator_id) where ad_period_id is not null;

-- ── Paystack webhook log (idempotency + audit) ───────────────────────────────
create table if not exists paystack_events (
    id           bigserial   primary key,
    event        text        not null,
    data_id      text        not null,
    reference    text        null,
    payload      jsonb       not null,
    received_at  timestamptz not null default now(),
    processed_at timestamptz null,
    error        text        null,
    unique (event, data_id)
);
