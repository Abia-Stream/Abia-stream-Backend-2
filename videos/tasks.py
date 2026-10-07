from celery import shared_task

from videos.delivery import sync_delivery_type


@shared_task(bind=True, max_retries=5)
def sync_video_delivery_type(self, video_id):
    """
    Queued when a video's visibility and its Cloudinary delivery type disagree
    (visibility changed, or an upload came in without the signed `type`).
    The `sync_video_delivery` command repairs anything this misses.
    """
    from videos.models import Video

    video = Video.objects.filter(id=video_id).first()
    if video is None:
        return
    try:
        sync_delivery_type(video)
    except Exception as exc:  # noqa: BLE001 - Cloudinary/network; retry with backoff
        raise self.retry(exc=exc, countdown=60 * 2 ** self.request.retries)
