from django.core.management.base import BaseCommand

from videos.models import Video
from videos.thumbnails import PENDING, UPDATED, best_thumbnail, upgrade_when_ready


class Command(BaseCommand):
    help = ('Switch videos whose thumbnail is just a frame of the video (e.g. at 1 s) '
            'to the best-frame thumbnail, once Cloudinary has it ready. Custom image '
            'thumbnails are left alone. Dry run unless --apply; re-run to pick up any '
            'still pending.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        counts = {UPDATED: 0, PENDING: 0}
        for video in Video.objects.exclude(cloudinary_url='').order_by('created_at'):
            url = best_thumbnail(video)
            if url is None:
                continue
            if not options['apply']:
                counts[UPDATED] += 1
                self.stdout.write(f'would update {video.id} "{video.title[:40]}"\n'
                                  f'    {video.cloudinary_thumbnail_url or "(none)"}\n -> {url}')
                continue
            outcome = upgrade_when_ready(video)
            if outcome in counts:
                counts[outcome] += 1
                self.stdout.write(f'{outcome} {video.id} "{video.title[:40]}"')
        if options['apply']:
            self.stdout.write(f'{counts[UPDATED]} video(s) updated, {counts[PENDING]} pending '
                              '(Cloudinary still generating; re-run in a minute).')
        else:
            self.stdout.write(f'{counts[UPDATED]} video(s) would be updated (dry run; add --apply).')
