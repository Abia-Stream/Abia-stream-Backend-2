-- 010_personalization.sql
-- Roadmap Stage 4: learned feed ranking, "up next" sequences, personalised
-- search. Additive and idempotent. Nothing here changes behaviour on its own:
-- both experiments are created switched OFF.

-- ── Trained ranking models ───────────────────────────────────────────────────
-- A logistic-regression ranker stored as plain numbers, so serving needs no
-- ML libraries. At most one active model per name.
create table if not exists ranker_models (
    id            bigserial        primary key,
    name          text             not null default 'feed',
    feature_names jsonb            not null,
    weights       jsonb            not null,
    intercept     double precision not null,
    means         jsonb            not null,
    stds          jsonb            not null,
    metrics       jsonb            not null default '{}'::jsonb,
    is_active     boolean          not null default false,
    created_at    timestamptz      not null default now()
);
create unique index if not exists ranker_models_one_active
    on ranker_models (name) where is_active;

-- ── "Up next": what people watch right after a video ─────────────────────────
-- Rebuilt in batch by: python manage.py build_video_transitions
create table if not exists video_transitions (
    id            bigserial        primary key,
    video_id      uuid             not null references videos(id) on delete cascade,
    next_video_id uuid             not null references videos(id) on delete cascade,
    transitions   integer          not null default 0,
    score         double precision not null default 0,
    computed_at   timestamptz      not null default now(),
    unique (video_id, next_video_id)
);
create index if not exists video_transitions_lookup_idx
    on video_transitions (video_id, score desc);

-- Session timelines for transitions and ranking labels.
create index if not exists view_logs_session_time_idx
    on view_logs (session_id, timestamp);

-- ── Experiments (created OFF; switch on with is_active = true) ───────────────
insert into experiments (key, description, variants, is_active) values
    ('feed_ranker',
     'For You feed ordered by the trained ranker (treatment) vs the hand-tuned score (control). '
     'Treatment only differs once a ranker model is active.',
     '["control", "treatment"]'::jsonb, false),
    ('search_personalization',
     'Search results nudged toward the viewer''s categories and creators (treatment) vs plain relevance (control).',
     '["control", "treatment"]'::jsonb, false)
on conflict (key) do nothing;
