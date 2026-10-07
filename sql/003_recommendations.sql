-- 003_recommendations.sql
-- Precomputed item-to-item similarity ("users who watched X also watched Y").
-- Rebuilt in batch by: python manage.py build_related_videos

create table if not exists related_videos (
    id            bigserial primary key,
    video_id      uuid        not null references videos(id) on delete cascade,
    related_id    uuid        not null references videos(id) on delete cascade,
    score         double precision not null default 0,
    co_view_count integer     not null default 0,
    computed_at   timestamptz not null default now(),
    unique (video_id, related_id)
);

create index if not exists related_videos_lookup_idx
    on related_videos (video_id, score desc);
