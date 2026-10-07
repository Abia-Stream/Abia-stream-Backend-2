-- 002_video_search.sql
-- Postgres full-text search over videos. Stage 0 "basic search".
-- Apply after 001_events.sql.

alter table videos
    add column if not exists search_vector tsvector
    generated always as (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'B')
    ) stored;

create index if not exists videos_search_idx on videos using gin (search_vector);

-- Supports the trending aggregate in videos/views.py (TrendingVideosView).
create index if not exists view_logs_timestamp_idx on view_logs (timestamp desc);
create index if not exists view_logs_video_time_idx on view_logs (video_id, timestamp desc);
