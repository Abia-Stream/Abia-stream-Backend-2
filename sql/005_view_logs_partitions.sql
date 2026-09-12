-- 005_view_logs_partitions.sql
-- view_logs is RANGE-partitioned but only view_logs_2026_01 exists, so every
-- insert dated outside January 2026 fails with
--   "no partition of relation view_logs found for row".
-- This is why view_logs has zero rows.
--
-- PARTITION SHAPE VERIFIED 2026-09-12, empirically via rolled-back inserts:
--   partition key  = `timestamp` (pg_partitioned_table.partattrs = 12), RANGE
--   2025-12-31T23:00Z  rejected
--   2026-01-01T00:00Z  accepted
--   2026-01-31T23:59Z  accepted
--   2026-02-01T00:00Z  rejected
--   2026-09-12T12:00Z  rejected  <- current traffic has nowhere to land
-- So view_logs_2026_01 covers ['2026-01-01','2026-02-01') and the monthly
-- bounds below line up with it exactly. Safe to run as written.

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
