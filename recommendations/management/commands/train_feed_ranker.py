import json

from django.core.management.base import BaseCommand

from recommendations import ranker


class Command(BaseCommand):
    help = ('Train the For You ranker on logged feed impressions. Activates the new '
            'model only if it beats the hand-tuned score on held-out data.')

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=ranker.TRAIN_DAYS)
        parser.add_argument('--dry-run', action='store_true',
                            help='Train and report, but store nothing.')

    def handle(self, *args, **options):
        report = ranker.train(days=options['days'], save=not options['dry_run'])
        self.stdout.write(json.dumps(report, indent=2, default=str))
