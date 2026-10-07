-- 008_livestreaming.sql
-- Livestreaming on Cloudinary Live Streaming (`livestreams` Django app).
-- The livestreams / stream_viewers tables already exist (empty, unused); this
-- adds what the integration needs, live chat, and moderation hooks.
-- Additive and idempotent.

-- ── livestreams ───────────────────────────────────────────────────────────────
alter table livestreams add column if not exists cloudinary_stream_id text null;
alter table livestreams add column if not exists cloudinary_archive_public_id text null;
-- Recording: saved as a normal video when the stream ends.
alter table livestreams add column if not exists save_recording boolean not null default true;
alter table livestreams add column if not exists publish_recording boolean not null default false;
alter table livestreams add column if not exists recording_video_id uuid null
    references videos(id) on delete set null;
-- Cloudinary has no webhooks for live state; status is refreshed on read, at
-- most every few seconds per stream.
alter table livestreams add column if not exists status_checked_at timestamptz null;
alter table livestreams add column if not exists updated_at timestamptz not null default now();

create unique index if not exists livestreams_cloudinary_stream_id_uniq
    on livestreams (cloudinary_stream_id) where cloudinary_stream_id is not null;
create index if not exists livestreams_status_idx
    on livestreams (status, scheduled_start_time);
create index if not exists livestreams_creator_idx
    on livestreams (creator_id, created_at desc);

-- ── stream_viewers ────────────────────────────────────────────────────────────
-- One row per viewer session per stream; left_at is bumped by heartbeats, so
-- "watching now" = left_at within the last minute.
alter table stream_viewers add column if not exists session_id uuid null;
create unique index if not exists stream_viewers_session_uniq
    on stream_viewers (livestream_id, session_id) where session_id is not null;
create index if not exists stream_viewers_active_idx
    on stream_viewers (livestream_id, left_at);

-- ── live chat ─────────────────────────────────────────────────────────────────
create table if not exists livestream_chat_messages (
    id            uuid        primary key default gen_random_uuid(),
    livestream_id uuid        not null references livestreams(id) on delete cascade,
    user_id       uuid        not null references users(id) on delete cascade,
    content       text        not null check (char_length(content) between 1 and 500),
    is_deleted    boolean     not null default false,
    created_at    timestamptz not null default now()
);
create index if not exists livestream_chat_messages_stream_time_idx
    on livestream_chat_messages (livestream_id, created_at);

-- ── moderation hooks ──────────────────────────────────────────────────────────
alter table moderation_actions add column if not exists livestream_id uuid null
    references livestreams(id) on delete set null;
alter table moderation_actions add column if not exists chat_message_id uuid null
    references livestream_chat_messages(id) on delete set null;

alter table moderation_actions drop constraint if exists moderation_actions_action_check;
alter table moderation_actions add constraint moderation_actions_action_check
    check (action in (
        'block_video', 'restore_video',
        'remove_comment', 'restore_comment',
        'suspend_user', 'unsuspend_user',
        'dismiss',
        'end_livestream', 'remove_chat_message'));
