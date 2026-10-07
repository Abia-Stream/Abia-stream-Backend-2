from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

# view_logs is RANGE-partitioned on "timestamp" by calendar month (UTC). See
# sql/005_view_logs_partitions.sql for the verified partition shape.
DEFAULT_MONTHS_AHEAD = 3


def month_start(year, month):
    return datetime(year, month, 1, tzinfo=dt_timezone.utc)


def add_months(year, month, n):
    index = year * 12 + (month - 1) + n
    return index // 12, index % 12 + 1


def ensure_partitions(months_ahead=DEFAULT_MONTHS_AHEAD, dry_run=False):
    """
    Create monthly view_logs partitions from the current month through
    `months_ahead` months ahead. Idempotent.

    Returns a list of (partition_name, outcome) where outcome is one of
    'created', 'exists', 'would create' or an error message.
    """
    now = timezone.now()
    results = []

    with connection.cursor() as cur:
        cur.execute(
            "select c.relname from pg_inherits i "
            "join pg_class c on c.oid = i.inhrelid "
            "join pg_class p on p.oid = i.inhparent "
            "where p.relname = 'view_logs'"
        )
        existing = {row[0] for row in cur.fetchall()}

    for offset in range(months_ahead + 1):
        year, month = add_months(now.year, now.month, offset)
        next_year, next_month = add_months(year, month, 1)
        name = f'view_logs_{year:04d}_{month:02d}'

        if name in existing:
            results.append((name, 'exists'))
            continue
        if dry_run:
            results.append((name, 'would create'))
            continue

        start = month_start(year, month).isoformat()
        end = month_start(next_year, next_month).isoformat()
        try:
            # Savepoint per month so one failure does not abort the others.
            with transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute(
                        f'create table if not exists "{name}" partition of view_logs '
                        'for values from (%s) to (%s)',
                        [start, end],
                    )
            results.append((name, 'created'))
        except DatabaseError as exc:
            # Typically: rows for this month already landed in
            # view_logs_default, or a differently-named partition overlaps.
            # Writes keep working via the default partition; a human decides.
            results.append((name, f'error: {exc}'.strip()))

    return results


class Command(BaseCommand):
    help = 'Create upcoming monthly view_logs partitions (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--months-ahead', type=int, default=DEFAULT_MONTHS_AHEAD)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        results = ensure_partitions(options['months_ahead'], options['dry_run'])
        failed = False
        for name, outcome in results:
            if outcome.startswith('error'):
                failed = True
                self.stderr.write(self.style.ERROR(f'{name}: {outcome}'))
            else:
                self.stdout.write(f'{name}: {outcome}')
        if failed:
            raise SystemExit(1)
