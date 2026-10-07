-- 009_auto_moderation.sql
-- Automatic moderation signals (roadmap Stage 2): video fingerprints, a
-- "held for review" video status, and automated entries in the existing
-- moderation queue (content_reports). Additive and idempotent.

-- ── Held videos ───────────────────────────────────────────────────────────────
-- A strong automatic match (e.g. a re-upload of a blocked video) is held from
-- the public until a moderator approves or blocks it.
alter type video_status add value if not exists 'held';

-- ── Fingerprints ──────────────────────────────────────────────────────────────
-- One 64-bit perceptual hash (dHash) per sampled frame, stored signed.
create table if not exists video_fingerprints (
    video_id         uuid        primary key references videos(id) on delete cascade,
    frame_hashes     bigint[]    not null,
    duration_seconds integer     null,
    computed_at      timestamptz not null default now()
);

-- ── Automated entries in the moderation queue ─────────────────────────────────
alter table content_reports alter column reporter_id drop not null;
alter table content_reports add column if not exists source text not null default 'user';
alter table content_reports add column if not exists signal text null;
-- Named signal_details: content_reports.details already exists (the reporter's
-- free-text explanation), and `add column if not exists` would silently skip.
alter table content_reports add column if not exists signal_details jsonb not null default '{}'::jsonb;

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'content_reports_source_check') then
        alter table content_reports add constraint content_reports_source_check check (
            (source = 'user' and reporter_id is not null) or
            (source = 'auto' and signal is not null)
        );
    end if;
end $$;

-- One open automated flag per target per signal.
create unique index if not exists content_reports_open_auto_video_uniq
    on content_reports (video_id, signal)
    where status = 'open' and source = 'auto' and target_type = 'video';
create unique index if not exists content_reports_open_auto_comment_uniq
    on content_reports (comment_id, signal)
    where status = 'open' and source = 'auto' and target_type = 'comment';

-- ── Moderation actions: approve a held video ──────────────────────────────────
alter table moderation_actions drop constraint if exists moderation_actions_action_check;
alter table moderation_actions add constraint moderation_actions_action_check
    check (action in (
        'block_video', 'restore_video', 'approve_video',
        'remove_comment', 'restore_comment',
        'suspend_user', 'unsuspend_user',
        'dismiss',
        'end_livestream', 'remove_chat_message'));
