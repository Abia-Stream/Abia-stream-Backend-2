-- 012_verification_attempts.sql
-- One row per identity-verification attempt (`verification` app):
--   method 'smile'  - Smile ID v3 Document Verification via the Web SDK; the
--                     verdict arrives by webhook and is confirmed with Smile.
--   method 'manual' - photos uploaded to us, stored privately on Cloudinary
--                     (type=authenticated) and reviewed by an admin.
-- users.verification_status stays the summary the rest of the app reads.
-- Additive and idempotent.

create table if not exists verification_attempts (
    id                 uuid        primary key default gen_random_uuid(),
    user_id            uuid        not null references users(id) on delete cascade,
    method             text        not null check (method in ('smile', 'manual')),
    status             text        not null default 'started'
                       check (status in ('started', 'pending', 'attention',
                                         'approved', 'rejected', 'error')),
    smile_job_id       text        null unique,
    id_type            text        null,
    document_public_id text        null,      -- Cloudinary, type=authenticated
    selfie_public_id   text        null,
    result_status      text        null,      -- Smile: clear | attention | block | error
    result_message     text        null,
    reviewed_by        uuid        null references users(id) on delete set null,
    reviewed_at        timestamptz null,
    review_note        text        null,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create index if not exists verification_attempts_user_idx
    on verification_attempts (user_id, created_at desc);
-- The admin review queue.
create index if not exists verification_attempts_queue_idx
    on verification_attempts (created_at)
    where status in ('pending', 'attention');
