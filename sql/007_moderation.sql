-- 007_moderation.sql
-- User reports and the moderator review queue (`moderation` Django app).
-- New tables only; nothing existing is altered. Idempotent.

create table if not exists content_reports (
    id              uuid        primary key default gen_random_uuid(),
    reporter_id     uuid        not null references users(id) on delete cascade,
    target_type     text        not null check (target_type in ('video', 'comment')),
    -- For comment reports video_id holds the comment's video, for context.
    video_id        uuid        null references videos(id) on delete cascade,
    comment_id      uuid        null references comments(id) on delete cascade,
    reason          text        not null check (reason in (
                        'spam', 'harassment', 'hate', 'violence', 'sexual',
                        'child_safety', 'copyright', 'misinformation', 'other')),
    details         text        null,
    status          text        not null default 'open'
                                check (status in ('open', 'actioned', 'dismissed')),
    reviewed_by     uuid        null references users(id) on delete set null,
    reviewed_at     timestamptz null,
    resolution_note text        null,
    created_at      timestamptz not null default now(),
    constraint content_reports_target_check check (
        (target_type = 'video'   and video_id   is not null and comment_id is null) or
        (target_type = 'comment' and comment_id is not null)
    )
);

-- One open report per reporter per target; re-reporting is a no-op.
create unique index if not exists content_reports_open_video_uniq
    on content_reports (reporter_id, video_id)
    where status = 'open' and target_type = 'video';
create unique index if not exists content_reports_open_comment_uniq
    on content_reports (reporter_id, comment_id)
    where status = 'open' and target_type = 'comment';

create index if not exists content_reports_queue_idx
    on content_reports (status, created_at);
create index if not exists content_reports_video_idx   on content_reports (video_id);
create index if not exists content_reports_comment_idx on content_reports (comment_id);

-- Audit log of every moderator decision. Never updated or deleted by the app.
create table if not exists moderation_actions (
    id             uuid        primary key default gen_random_uuid(),
    moderator_id   uuid        null references users(id) on delete set null,
    action         text        not null check (action in (
                       'block_video', 'restore_video',
                       'remove_comment', 'restore_comment',
                       'suspend_user', 'unsuspend_user',
                       'dismiss')),
    video_id       uuid        null references videos(id) on delete set null,
    comment_id     uuid        null references comments(id) on delete set null,
    target_user_id uuid        null references users(id) on delete set null,
    note           text        null,
    -- e.g. {"previous_status": "published"} so a block can be undone exactly.
    metadata       jsonb       not null default '{}'::jsonb,
    created_at     timestamptz not null default now()
);

create index if not exists moderation_actions_time_idx
    on moderation_actions (created_at desc);
create index if not exists moderation_actions_video_idx on moderation_actions (video_id);
