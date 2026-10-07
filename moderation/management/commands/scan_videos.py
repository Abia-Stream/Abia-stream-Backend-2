from django.core.management.base import BaseCommand

from moderation.models import VideoFingerprint
from videos.models import Video


def scan(limit=200):
    """Run automatic checks on ready/published videos that have no fingerprint yet."""
    fingerprinted = VideoFingerprint.objects.values('video_id')
    pending = (Video.objects
               .filter(status__in=[Video.Status.READY, Video.Status.PUBLISHED])
               .exclude(cloudinary_url='')
               .exclude(id__in=fingerprinted)
               .order_by('created_at')[:limit])
    from moderation.auto import check_video
    counts = {'scanned': 0, 'held': 0, 'unavailable': 0}
    for video in pending:
        result = check_video(video)
        counts['scanned'] += 1
        counts['held'] += int(result['held'])
        counts['unavailable'] += int(not result['checked'])
    return counts


class Command(BaseCommand):
    help = ('Fingerprint and check ready/published videos that missed the upload-time '
            'checks (e.g. Cloudinary was unreachable). Safe to run any time.')

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=200)

    def handle(self, *args, **options):
        counts = scan(options['limit'])
        self.stdout.write(', '.join(f'{k}: {v}' for k, v in counts.items()))
