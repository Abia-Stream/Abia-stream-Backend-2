from videos.models import Video


def is_video_accessible(video, user):
    if video.visibility == Video.Visibility.PUBLIC:
        return True
    if video.visibility == Video.Visibility.UNLISTED:
        return True
    if not user or not user.is_authenticated:
        return False
    if video.creator_id == user.id:
        return True
    if video.visibility == Video.Visibility.PRIVATE:
        return False
    if video.visibility == Video.Visibility.SUBSCRIBERS_ONLY:
        # Check if user is subscribed to the creator's channel
        from subscriptions.models import Subscription
        try:
            channel = video.creator.channel
            return Subscription.objects.filter(
                subscriber=user,
                channel=channel
            ).exists()
        except Exception:
            return False
    return False
