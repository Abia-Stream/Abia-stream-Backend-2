-- 005_view_logs_partitions.sql
-- view_logs is RANGE-partitioned but only view_logs_2026_01 exists, so every
-- insert dated outside January 2026 fails with
--   "no partition of relation view_logs found for row".
-- This is why view_logs has zero rows.
--
-- VERIFY THE PARTITION KEY BEFORE RUNNING:
--   select pg_get_expr(relpartbound, oid) from pg_class
--    where relname = 'view_logs_2026_01';
-- The bounds below assume monthly ranges on `timestamp`. If the existing
-- partition is shaped differently, adjust to match rather than running as-is.

create table if not exists view_logs_2026_02 partition of view_logs
    for values from ('2026-02-01') to ('2026-03-01');
create table if not exists view_logs_2026_03 partition of view_logs
    for values from ('2026-03-01') to ('2026-04-01');
create table if not exists view_logs_2026_04 partition of view_logs
    for values from ('2026-04-01') to ('2026-05-01');
create table if not exists view_logs_2026_05 partition of view_logs
    for values from ('2026-05-01') to ('2026-06-01');
create table if not exists view_logs_2026_06 partition of view_logs
    for values from ('2026-06-01') to ('2026-07-01');
create table if not exists view_logs_2026_07 partition of view_logs
    for values from ('2026-07-01') to ('2026-08-01');
create table if not exists view_logs_2026_08 partition of view_logs
    for values from ('2026-08-01') to ('2026-09-01');
create table if not exists view_logs_2026_09 partition of view_logs
    for values from ('2026-09-01') to ('2026-10-01');
create table if not exists view_logs_2026_10 partition of view_logs
    for values from ('2026-10-01') to ('2026-11-01');
create table if not exists view_logs_2026_11 partition of view_logs
    for values from ('2026-11-01') to ('2026-12-01');
create table if not exists view_logs_2026_12 partition of view_logs
    for values from ('2026-12-01') to ('2027-01-01');

-- Catch-all so a missing future partition degrades to a slow write rather than
-- a failed one. Creating this AFTER the monthly partitions above matters:
-- adding a new partition later requires scanning the default for conflicting
-- rows, which is cheap only while the default stays near-empty.
create table if not exists view_logs_default partition of view_logs default;
