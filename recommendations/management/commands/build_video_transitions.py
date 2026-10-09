from django.core.management.base import BaseCommand
from django.db import connection, transaction

# Two views in the same session this close together count as "watched next".
SESSION_GAP = '2 hours'
# Signed-in history is coarser (one row per video, last watch time).
HISTORY_GAP = '6 hours'
MIN_TRANSITIONS = 2
TOP_N_PER_VIDEO = 20
LOOKBACK = '90 days'

SQL = f"""
with session_seq as (
    select video_id,
           lead(video_id)  over w as next_id,
           lead(timestamp) over w - timestamp as gap
    from view_logs
    where session_id is not null and timestamp >= now() - interval '{LOOKBACK}'
    window w as (partition by session_id order by timestamp)
),
history_seq as (
    select video_id,
           lead(video_id)        over w as next_id,
           lead(last_watched_at) over w - last_watched_at as gap
    from watch_history
    where last_watched_at >= now() - interval '{LOOKBACK}'
    window w as (partition by user_id order by last_watched_at)
),
pairs as (
    select video_id, next_id from session_seq
    where next_id is not null and next_id <> video_id and gap <= interval '{SESSION_GAP}'
    union all
    select video_id, next_id from history_seq
    where next_id is not null and next_id <> video_id and gap <= interval '{HISTORY_GAP}'
),
counted as (
    select video_id, next_id, count(*) as n from pairs group by video_id, next_id
),
scored as (
    -- P(next | current), shrunk toward 0 for videos with little traffic.
    select c.video_id, c.next_id, c.n,
           c.n::double precision / (sum(c.n) over (partition by c.video_id) + 5) as score
    from counted c
),
ranked as (
    select *, row_number() over (partition by video_id order by score desc, n desc) as rn
    from scored where n >= %(min_transitions)s
)
insert into video_transitions (video_id, next_video_id, transitions, score, computed_at)
select video_id, next_id, n, score, now() from ranked where rn <= %(top_n)s
on conflict (video_id, next_video_id) do update
    set transitions = excluded.transitions,
        score       = excluded.score,
        computed_at = excluded.computed_at;
"""


def build(min_transitions=MIN_TRANSITIONS, top_n=TOP_N_PER_VIDEO):
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(SQL, {'min_transitions': min_transitions, 'top_n': top_n})
            written = cur.rowcount
            # Same transaction: rows not refreshed by this run are stale.
            cur.execute("delete from video_transitions where computed_at < now()")
            pruned = cur.rowcount
    return written, pruned


class Command(BaseCommand):
    help = 'Rebuild "up next" transitions from viewing sessions and watch history.'

    def add_arguments(self, parser):
        parser.add_argument('--min-transitions', type=int, default=MIN_TRANSITIONS)

    def handle(self, *args, **options):
        written, pruned = build(min_transitions=options['min_transitions'])
        self.stdout.write(f'{written} transitions written, {pruned} stale removed.')
