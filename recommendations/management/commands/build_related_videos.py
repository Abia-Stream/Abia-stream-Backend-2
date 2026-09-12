from django.core.management.base import BaseCommand
from django.db import connection, transaction

# Users with implausibly broad history skew co-occurrence toward globally
# popular videos rather than genuinely related ones.
MAX_HISTORY_PER_USER = 500

# Below this, a pairing is noise rather than signal.
MIN_CO_VIEWS = 3

# Rows kept per video.
TOP_N_PER_VIDEO = 20


SQL = """
with eligible as (
    -- One row per (user, video). Drop hyperactive users whose history would
    -- otherwise link everything to everything.
    select wh.user_id, wh.video_id
    from watch_history wh
    join (
        select user_id
        from watch_history
        group by user_id
        having count(*) between 2 and %(max_history)s
    ) u on u.user_id = wh.user_id
),
video_counts as (
    select video_id, count(distinct user_id)::double precision as viewers
    from eligible
    group by video_id
),
co_views as (
    -- Self-join on shared users. a.video_id < b.video_id keeps each unordered
    -- pair once; both directions are written out below.
    select a.video_id as video_id,
           b.video_id as related_id,
           count(distinct a.user_id) as co_view_count
    from eligible a
    join eligible b
      on a.user_id = b.user_id
     and a.video_id < b.video_id
    group by a.video_id, b.video_id
    having count(distinct a.user_id) >= %(min_co_views)s
),
scored as (
    -- Cosine similarity over binary user vectors: co / sqrt(|A| * |B|).
    -- Normalising is what stops popular videos being "related" to everything.
    select c.video_id, c.related_id, c.co_view_count,
           c.co_view_count / sqrt(va.viewers * vb.viewers) as score
    from co_views c
    join video_counts va on va.video_id = c.video_id
    join video_counts vb on vb.video_id = c.related_id
),
both_directions as (
    select video_id, related_id, co_view_count, score from scored
    union all
    select related_id, video_id, co_view_count, score from scored
),
ranked as (
    select *, row_number() over (
        partition by video_id order by score desc, co_view_count desc
    ) as rn
    from both_directions
)
insert into related_videos (video_id, related_id, score, co_view_count, computed_at)
select video_id, related_id, score, co_view_count, now()
from ranked
where rn <= %(top_n)s
on conflict (video_id, related_id) do update
    set score = excluded.score,
        co_view_count = excluded.co_view_count,
        computed_at = excluded.computed_at;
"""


class Command(BaseCommand):
    help = (
        'Rebuild item-to-item video similarity from watch history '
        '("users who watched X also watched Y").'
    )

    def add_arguments(self, parser):
        parser.add_argument('--min-co-views', type=int, default=MIN_CO_VIEWS)
        parser.add_argument('--top-n', type=int, default=TOP_N_PER_VIDEO)
        parser.add_argument(
            '--prune',
            action='store_true',
            help='Delete rows not refreshed by this run.',
        )

    def handle(self, *args, **options):
        params = {
            'max_history': MAX_HISTORY_PER_USER,
            'min_co_views': options['min_co_views'],
            'top_n': options['top_n'],
        }

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(SQL, params)
                written = cursor.rowcount

                if options['prune']:
                    cursor.execute(
                        "delete from related_videos "
                        "where computed_at < now() - interval '1 hour'"
                    )
                    self.stdout.write(f'Pruned {cursor.rowcount} stale rows.')

        if written == 0:
            self.stdout.write(self.style.WARNING(
                'No pairs met the threshold. Expected until watch history '
                'accumulates - lower --min-co-views to inspect earlier.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Wrote {written} related-video rows.'
            ))
