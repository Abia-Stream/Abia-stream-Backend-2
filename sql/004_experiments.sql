-- 004_experiments.sql
-- Minimal A/B testing infrastructure (Stage 3).

create table if not exists experiments (
    id          bigserial primary key,
    key         text        not null unique,
    description text        null,
    variants    jsonb       not null default '["control","treatment"]'::jsonb,
    is_active   boolean     not null default false,
    created_at  timestamptz not null default now()
);

create table if not exists experiment_assignments (
    id            bigserial primary key,
    experiment_id bigint      not null references experiments(id) on delete cascade,
    user_id       uuid        null references users(id) on delete cascade,
    session_id    uuid        null,
    variant       text        not null,
    assigned_at   timestamptz not null default now(),
    -- One assignment per subject per experiment. Anonymous subjects are keyed
    -- on session_id, signed-in ones on user_id.
    unique (experiment_id, user_id),
    unique (experiment_id, session_id)
);

create index if not exists experiment_assignments_lookup_idx
    on experiment_assignments (experiment_id, variant);
