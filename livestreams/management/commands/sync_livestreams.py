from django.core.management.base import BaseCommand

from livestreams.services import sync_all


class Command(BaseCommand):
    help = (
        'Livestream housekeeping: refresh live/scheduled status from Cloudinary, '
        'turn finished recordings into videos, cancel abandoned scheduled streams '
        'and delete finished Cloudinary streams. Safe to run any time.'
    )

    def handle(self, *args, **options):
        counts = sync_all()
        self.stdout.write(', '.join(f'{k}: {v}' for k, v in counts.items()))
