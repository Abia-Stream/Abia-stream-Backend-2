from django.conf import settings
from django.core.management.base import BaseCommand

from verification.services import purge_documents


class Command(BaseCommand):
    help = ('Delete private ID photos of verification attempts decided more than '
            'VERIFICATION_DOCUMENT_RETENTION_DAYS ago. Dry run unless --apply.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Actually delete (default: dry run).')
        parser.add_argument('--days', type=int, default=None,
                            help=f'Override the retention period '
                                 f'(default {settings.VERIFICATION_DOCUMENT_RETENTION_DAYS}).')

    def handle(self, *args, **options):
        counts = purge_documents(options['days'], dry_run=not options['apply'])
        prefix = '' if options['apply'] else '(dry run) '
        self.stdout.write(prefix + ', '.join(f'{k}: {v}' for k, v in counts.items()))
