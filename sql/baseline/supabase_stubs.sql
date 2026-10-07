-- Minimal stand-ins for Supabase objects referenced by the live schema
-- (row-level-security policies call auth.uid()). Test databases only.
create schema if not exists auth;
create or replace function auth.uid() returns uuid
    language sql stable as 'select null::uuid';
