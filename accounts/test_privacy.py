"""Email addresses are private: nothing public or user-to-user may contain one."""
import json

from django.test import TestCase

from abiastream.testing import client_for, make_user, make_video
from accounts.display import FALLBACK_NAME, display_name
from creator_channels.models import CreatorChannel
from notifications.models import Notification
from profiles.models import Profile


def assert_no_email(test, payload, *users):
    text = json.dumps(payload, default=str)
    for user in users:
        test.assertNotIn(user.email, text)


class DisplayNameTests(TestCase):

    def test_prefers_profile_then_channel_then_fallback(self):
        bare = make_user()
        self.assertEqual(display_name(bare), FALLBACK_NAME)

        CreatorChannel.objects.create(user=bare, channel_name='Ada Cooks', channel_slug='ada')
        bare = type(bare).objects.get(id=bare.id)
        self.assertEqual(display_name(bare), 'Ada Cooks')

        Profile.objects.create(user=bare, full_name='Ada Obi')
        bare = type(bare).objects.get(id=bare.id)
        self.assertEqual(display_name(bare), 'Ada Obi')


class CommentPrivacyTests(TestCase):

    def test_comments_and_notifications_hide_email(self):
        creator = make_user()
        video = make_video(creator)
        commenter = make_user()
        Profile.objects.create(user=commenter, full_name='Chidi')

        posted = client_for(commenter).post(
            f'/api/v1/videos/{video.id}/comments/', {'content': 'great video'}, format='json')
        self.assertEqual(posted.status_code, 201, posted.content)

        listing = client_for().get(f'/api/v1/videos/{video.id}/comments/').json()
        assert_no_email(self, listing, commenter, creator)
        self.assertIn('Chidi', json.dumps(listing))

        note = Notification.objects.get(user=creator, notification_type='new_comment')
        self.assertTrue(note.message.startswith('Chidi commented'))
        self.assertNotIn(commenter.email, note.message)

        comment_id = posted.json()['id']
        replier = make_user()
        client_for(replier).post(f'/api/v1/videos/{video.id}/comments/',
                                 {'content': 'agreed', 'parent_id': comment_id}, format='json')
        client_for(replier).post(f'/api/v1/comments/{comment_id}/like/')
        notes = Notification.objects.filter(user=commenter)
        self.assertEqual(sorted(n.notification_type for n in notes),
                         ['comment_like', 'comment_reply'])
        for note in notes:
            self.assertNotIn(replier.email, note.message)
            self.assertIn(FALLBACK_NAME, note.message)


class ChannelPrivacyTests(TestCase):

    def setUp(self):
        self.owner = make_user()
        self.channel = CreatorChannel.objects.create(
            user=self.owner, channel_name='Owner Chan', channel_slug='owner-chan')

    def test_public_channel_views_hide_owner_email(self):
        detail = client_for().get('/api/v1/channels/owner-chan/').json()
        listing = client_for().get('/api/v1/channels/').json()
        assert_no_email(self, detail, self.owner)
        assert_no_email(self, listing, self.owner)
        self.assertEqual(detail['owner_id'], str(self.owner.id))

    def test_owner_still_sees_own_email(self):
        mine = client_for(self.owner).get('/api/v1/channels/me/').json()
        self.assertEqual(mine['owner_email'], self.owner.email)

    def test_subscribe_notification_hides_email(self):
        fan = make_user()
        client_for(fan).post('/api/v1/subscriptions/owner-chan/')
        note = Notification.objects.get(user=self.owner, notification_type='new_subscriber')
        self.assertNotIn(fan.email, note.message)
