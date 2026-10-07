from django.test import TestCase

from abiastream.testing import make_user, make_video, client_for
from accounts.models import User
from comments.models import Comment
from moderation.models import ContentReport, ModerationAction
from notifications.models import Notification
from videos.models import Video


def make_comment(video, user, **extra):
    return Comment.objects.create(video=video, user=user, content='hello', **extra)


class ReportingTests(TestCase):

    def setUp(self):
        self.creator = make_user()
        self.video = make_video(self.creator)
        self.reporter = make_user()

    def test_report_video(self):
        response = client_for(self.reporter).post('/api/v1/reports/', {
            'video_id': str(self.video.id), 'reason': 'spam', 'details': 'link farm',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.content)
        report = ContentReport.objects.get()
        self.assertEqual((report.target_type, report.reason, report.status),
                         ('video', 'spam', 'open'))

    def test_re_report_is_idempotent(self):
        client = client_for(self.reporter)
        body = {'video_id': str(self.video.id), 'reason': 'spam'}
        first = client.post('/api/v1/reports/', body, format='json')
        second = client.post('/api/v1/reports/', body, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(ContentReport.objects.count(), 1)

    def test_report_comment_records_its_video(self):
        comment = make_comment(self.video, make_user())
        response = client_for(self.reporter).post('/api/v1/reports/', {
            'comment_id': str(comment.id), 'reason': 'harassment'}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        report = ContentReport.objects.get()
        self.assertEqual((report.target_type, report.comment_id, report.video_id),
                         ('comment', comment.id, self.video.id))

    def test_cannot_report_own_content(self):
        response = client_for(self.creator).post('/api/v1/reports/', {
            'video_id': str(self.video.id), 'reason': 'spam'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_needs_exactly_one_target(self):
        response = client_for(self.reporter).post('/api/v1/reports/', {
            'reason': 'spam'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_requires_login(self):
        response = client_for().post('/api/v1/reports/', {
            'video_id': str(self.video.id), 'reason': 'spam'}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_my_reports_hide_reviewer(self):
        client_for(self.reporter).post('/api/v1/reports/', {
            'video_id': str(self.video.id), 'reason': 'spam'}, format='json')
        mine = client_for(self.reporter).get('/api/v1/reports/').json()['results']
        self.assertEqual(len(mine), 1)
        self.assertNotIn('reviewed_by_id', mine[0])

    def test_one_click_report_interaction_feeds_queue(self):
        client = client_for(self.reporter)
        body = {'video_id': str(self.video.id), 'interaction_type': 'report'}

        added = client.post('/api/v1/interactions/', body, format='json')
        self.assertEqual(added.status_code, 201, added.content)
        self.assertEqual(ContentReport.objects.filter(status='open').count(), 1)

        removed = client.post('/api/v1/interactions/', body, format='json')
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(ContentReport.objects.count(), 0)


class QueueTests(TestCase):

    def test_queue_groups_and_ranks_by_report_count(self):
        creator = make_user()
        busy, quiet = make_video(creator, title='busy'), make_video(creator, title='quiet')
        for reason in ['spam', 'spam', 'hate']:
            ContentReport.objects.create(reporter=make_user(), target_type='video',
                                         video=busy, reason=reason)
        ContentReport.objects.create(reporter=make_user(), target_type='video',
                                     video=quiet, reason='other')

        moderator = make_user(role=User.Role.MODERATOR)
        data = client_for(moderator).get('/api/v1/moderation/queue/').json()

        rows = data['results']
        self.assertEqual([r['target']['title'] for r in rows], ['busy', 'quiet'])
        self.assertEqual(rows[0]['report_count'], 3)
        self.assertEqual(rows[0]['reasons'], {'spam': 2, 'hate': 1})

    def test_queue_forbidden_to_regular_users(self):
        for user in (make_user(), make_user(role=User.Role.CREATOR)):
            response = client_for(user).get('/api/v1/moderation/queue/')
            self.assertEqual(response.status_code, 403)
        self.assertEqual(client_for().get('/api/v1/moderation/queue/').status_code, 401)

    def test_admin_can_see_queue(self):
        admin = make_user(role=User.Role.ADMIN)
        self.assertEqual(client_for(admin).get('/api/v1/moderation/queue/').status_code, 200)


class ActionTests(TestCase):

    def setUp(self):
        self.moderator = make_user(role=User.Role.MODERATOR)
        self.client = client_for(self.moderator)
        self.creator = make_user()
        self.video = make_video(self.creator)

    def act(self, **body):
        return self.client.post('/api/v1/moderation/actions/', body, format='json')

    def test_block_then_restore_video(self):
        for _ in range(2):
            ContentReport.objects.create(reporter=make_user(), target_type='video',
                                         video=self.video, reason='spam')

        response = self.act(action='block_video', video_id=str(self.video.id), note='spam')

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['reports_resolved'], 2)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.BLOCKED)
        self.assertFalse(ContentReport.objects.filter(status='open').exists())
        self.assertTrue(Notification.objects.filter(
            user=self.creator, notification_type='video_blocked').exists())
        # Hidden from the public.
        self.assertEqual(client_for().get(f'/api/v1/videos/{self.video.id}/').status_code, 404)
        # The creator cannot edit their way out.
        patch = client_for(self.creator).patch(
            f'/api/v1/videos/{self.video.id}/', {'status': 'published'}, format='json')
        self.assertEqual(patch.status_code, 403)

        restore = self.act(action='restore_video', video_id=str(self.video.id))
        self.assertEqual(restore.status_code, 201, restore.content)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.PUBLISHED)

        log = list(ModerationAction.objects.filter(video=self.video)
                   .order_by('created_at').values_list('action', flat=True))
        self.assertEqual(log, ['block_video', 'restore_video'])

    def test_block_twice_rejected(self):
        self.act(action='block_video', video_id=str(self.video.id))
        self.assertEqual(self.act(action='block_video', video_id=str(self.video.id)).status_code, 400)
        self.assertEqual(ModerationAction.objects.count(), 1)

    def test_remove_and_restore_comment_keeps_text_and_counts(self):
        parent = make_comment(self.video, make_user(), replies_count=1)
        reply = make_comment(self.video, make_user(), parent=parent)
        ContentReport.objects.create(reporter=make_user(), target_type='comment',
                                     comment=reply, video=self.video, reason='hate')

        self.assertEqual(self.act(action='remove_comment', comment_id=str(reply.id)).status_code, 201)
        reply.refresh_from_db()
        parent.refresh_from_db()
        self.assertTrue(reply.is_deleted)
        self.assertEqual(reply.content, 'hello')
        self.assertEqual(parent.replies_count, 0)
        self.assertFalse(ContentReport.objects.filter(status='open').exists())

        self.assertEqual(self.act(action='restore_comment', comment_id=str(reply.id)).status_code, 201)
        reply.refresh_from_db()
        parent.refresh_from_db()
        self.assertFalse(reply.is_deleted)
        self.assertEqual(parent.replies_count, 1)

    def test_cannot_restore_comment_deleted_by_its_author(self):
        comment = make_comment(self.video, make_user(), is_deleted=True)
        self.assertEqual(self.act(action='restore_comment', comment_id=str(comment.id)).status_code, 400)

    def test_dismiss(self):
        ContentReport.objects.create(reporter=make_user(), target_type='video',
                                     video=self.video, reason='other')
        response = self.act(action='dismiss', video_id=str(self.video.id))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ContentReport.objects.get().status, 'dismissed')
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.PUBLISHED)
        # Nothing left to dismiss.
        self.assertEqual(self.act(action='dismiss', video_id=str(self.video.id)).status_code, 400)

    def test_suspend_locks_user_out_and_unsuspend_restores(self):
        target = make_user()
        self.assertEqual(self.act(action='suspend_user', user_id=str(target.id)).status_code, 201)
        target.refresh_from_db()
        self.assertEqual(target.status, User.Status.SUSPENDED)
        self.assertEqual(client_for(target).get('/api/v1/reports/').status_code, 401)

        self.assertEqual(self.act(action='unsuspend_user', user_id=str(target.id)).status_code, 201)
        target.refresh_from_db()
        self.assertEqual(target.status, User.Status.ACTIVE)

    def test_staff_protection(self):
        other_mod = make_user(role=User.Role.MODERATOR)
        admin = make_user(role=User.Role.ADMIN)
        self.assertEqual(self.act(action='suspend_user', user_id=str(other_mod.id)).status_code, 400)
        self.assertEqual(self.act(action='suspend_user', user_id=str(admin.id)).status_code, 400)
        self.assertEqual(self.act(action='suspend_user', user_id=str(self.moderator.id)).status_code, 400)
        # An admin may suspend a moderator.
        response = client_for(admin).post('/api/v1/moderation/actions/', {
            'action': 'suspend_user', 'user_id': str(other_mod.id)}, format='json')
        self.assertEqual(response.status_code, 201)

    def test_regular_user_cannot_act(self):
        response = client_for(make_user()).post('/api/v1/moderation/actions/', {
            'action': 'block_video', 'video_id': str(self.video.id)}, format='json')
        self.assertEqual(response.status_code, 403)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.PUBLISHED)

    def test_audit_log_listing(self):
        self.act(action='block_video', video_id=str(self.video.id), note='why')
        data = self.client.get('/api/v1/moderation/actions/',
                               {'video_id': str(self.video.id)}).json()
        self.assertEqual(data['results'][0]['action'], 'block_video')
        self.assertEqual(data['results'][0]['metadata'], {'previous_status': 'published'})
        self.assertEqual(data['results'][0]['moderator_id'], str(self.moderator.id))
