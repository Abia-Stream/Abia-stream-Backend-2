-- 001_events.sql
-- Unified event log. Feeds search ranking, collaborative filtering and A/B analysis.
-- Apply in the Supabase SQL editor before deploying the `events` Django app.

create table if not exists events (
    id          bigserial primary key,
    user_id     uuid        null references users(id) on delete set null,
    session_id  uuid        not null,
    video_id    uuid        null references videos(id) on delete cascade,
    event_type  text        not null,
    payload     jsonb       not null default '{}'::jsonb,
    occurred_at timestamptz not null default now()
);

create index if not exists events_type_time_idx  on events (event_type, occurred_at desc);
create index if not exists events_user_time_idx  on events (user_id, occurred_at desc);
create index if not exists events_video_time_idx on events (video_id, occurred_at desc);
create index if not exists events_session_idx    on events (session_id, occurred_at);

-- Search queries are read as text often enough to earn their own index.
create index if not exists events_search_query_idx
    on events ((payload->>'query'))
    where event_type = 'search';
