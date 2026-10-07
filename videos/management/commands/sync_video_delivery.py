from django.core.management.base import BaseCommand
from django.db.models import Q

from videos.delivery import (
    AUTHENTICATED, PUBLIC, desired_delivery_type, has_asset, sync_delivery_type,
)
from videos.models import Video


class Command(BaseCommand):
    help = (
        "Move Cloudinary assets whose delivery type doesn't match their "
        "visibility (non-public -> authenticated, public -> upload). "
        'Dry run unless --apply is given.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Actually move assets. Without it, only report.')
        parser.add_argument('--limit', type=int, default=None)

    def handle(self, *args, **options):
        mismatched = Video.objects.filter(
            (Q(visibility=Video.Visibility.PUBLIC) & ~Q(cloudinary_delivery_type=PUBLIC))
            | (~Q(visibility=Video.Visibility.PUBLIC) & ~Q(cloudinary_delivery_type=AUTHENTICATED))
        ).exclude(cloudinary_url='').order_by('created_at')

        if options['limit']:
            mismatched = mismatched[:options['limit']]

        moved = failed = 0
        for video in mismatched:
            if not has_asset(video):
                continue
            target = desired_delivery_type(video.visibility)
            label = f'{video.id} [{video.visibility}] {video.cloudinary_delivery_type} -> {target}'
            if not options['apply']:
                self.stdout.write(f'would move {label}')
                continue
            try:
                sync_delivery_type(video)
                moved += 1
                self.stdout.write(f'moved {label}')
            except Exception as exc:  # noqa: BLE001 - report and continue
                failed += 1
                self.stderr.write(self.style.ERROR(f'failed {label}: {exc}'))

        if options['apply']:
            self.stdout.write(self.style.SUCCESS(f'{moved} moved, {failed} failed.'))
        else:
            self.stdout.write('Dry run. Re-run with --apply to move these assets.')
