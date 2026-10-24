"""Identity verification: Smile ID v3 (token, webhook, status) and manual review."""
import base64
import hashlib
import hmac
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from abiastream.testing import client_for, make_user
from accounts.models import User
from notifications.models import Notification
from verification import review as review_rules
from verification import smile_service as smile
from verification.models import VerificationAttempt as Attempt

SMILE = dict(SMILE_IDENTITY_PARTNER_ID='2001', SMILE_IDENTITY_API_KEY='test-api-key',
             SMILE_IDENTITY_ENVIRONMENT='sandbox')
NO_SMILE = dict(SMILE_IDENTITY_PARTNER_ID='', SMILE_IDENTITY_API_KEY='')
JOB = 'job_01m326p53pe1ztjdxh2d9jn9ck'
OTHER_JOB = 'job_01m326p53pe1ztjdxh2d9jn9cm'
CALLBACK = '/api/v1/verification/smile/callback/'
ALL_TICKED = {key: True for key in review_rules.CHECKLIST_KEYS}


def png(name='id.png'):
    return SimpleUploadedFile(name, b'\x89PNG\r\n\x1a\n' + b'\x00' * 2048, content_type='image/png')


def smile_headers(timestamp='2026-10-18T10:00:00.000000+00:00', key='test-api-key', partner='2001'):
    # Computed independently from the documented formula.
    signature = base64.b64encode(hmac.new(key.encode(), f'{timestamp}{partner}sid_request'.encode(),
                                          hashlib.sha256).digest()).decode()
    return {'HTTP_RESPONSE_TIMESTAMP': timestamp, 'HTTP_RESPONSE_SIGNATURE': signature,
            'HTTP_SMILEID_JOB_ID': JOB}


def status_of(user, verdict, message='done'):
    return {'status': verdict, 'user_id': str(user.id), 'message': message, 'job_id': JOB}


@override_settings(**SMILE)
class SmileSessionTests(TestCase):

    def test_config_exposes_sdk_settings_but_no_secret(self):
        body = client_for(make_user()).get('/api/v1/verification/config/').json()
        self.assertTrue(body['smile_enabled'])
        self.assertEqual(body['smile']['partner_id'], '2001')
        self.assertEqual(body['smile']['product'], 'doc_verification')
        self.assertTrue(body['smile']['callback_url'].endswith(CALLBACK))
        self.assertNotIn('test-api-key', str(body))

    @override_settings(**NO_SMILE)
    def test_config_without_keys_offers_manual_only(self):
        body = client_for(make_user()).get('/api/v1/verification/config/').json()
        self.assertEqual((body['smile_enabled'], body['smile'], body['manual_review_enabled']),
                         (False, None, True))

    def test_session_binds_user_and_opens_attempt(self):
        user = make_user()
        with mock.patch.object(smile, 'mint_token', return_value='jwt-token') as mint:
            response = client_for(user).post('/api/v1/verification/smile/session/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['token'], 'jwt-token')
        mint.assert_called_once_with(str(user.id))
        attempt = Attempt.objects.get(user=user)
        self.assertEqual((attempt.method, attempt.status), ('smile', 'started'))

    def test_session_refused_when_already_verified_or_pending(self):
        for state in (User.VerificationStatus.APPROVED, User.VerificationStatus.PENDING):
            user = make_user(verification_status=state)
            with mock.patch.object(smile, 'mint_token') as mint:
                response = client_for(user).post('/api/v1/verification/smile/session/')
            self.assertEqual(response.status_code, 400)
            mint.assert_not_called()

    @override_settings(**NO_SMILE)
    def test_session_without_keys_points_to_manual_review(self):
        response = client_for(make_user()).post('/api/v1/verification/smile/session/')
        self.assertEqual(response.status_code, 503)
        self.assertIn('manual review', response.json()['detail'])

    def test_smile_outage_is_503(self):
        with mock.patch.object(smile, 'mint_token', side_effect=smile.SmileError('down')):
            response = client_for(make_user()).post('/api/v1/verification/smile/session/')
        self.assertEqual(response.status_code, 503)

    def test_token_request_shape(self):
        response = mock.Mock(status_code=200, json=lambda: {'token': 't'})
        with mock.patch.object(smile.requests, 'post', return_value=response) as post:
            self.assertEqual(smile.mint_token('user-1'), 't')
        args, kwargs = post.call_args
        self.assertEqual(args[0], 'https://testapi.smileidentity.com/v3/token')
        self.assertEqual(kwargs['headers'], {'smileid-partner-id': '2001', 'smileid-api-key': 'test-api-key'})
        self.assertEqual(kwargs['files'], {'product': (None, 'document_verification'),
                                           'user_id': (None, 'user-1')})

    @override_settings(SMILE_IDENTITY_ENVIRONMENT='production')
    def test_production_url(self):
        self.assertEqual(smile.base_url(), 'https://api.smileidentity.com')


@override_settings(**SMILE)
class SmileCallbackTests(TestCase):

    def setUp(self):
        self.user = make_user()
        Attempt.objects.create(user=self.user, method='smile')

    def callback(self, verdict, body=None, **headers):
        with mock.patch.object(smile, 'get_status', return_value=status_of(self.user, verdict)) as get,                 self.captureOnCommitCallbacks(execute=True):
            response = client_for().post(CALLBACK, body or {'status': verdict}, format='json',
                                         **{**smile_headers(), **headers})
        return response, get

    def test_wrong_signature_rejected_before_any_lookup(self):
        response, get = self.callback('clear', HTTP_RESPONSE_SIGNATURE='forged')
        self.assertEqual(response.status_code, 401)
        get.assert_not_called()

    def test_clear_approves_and_notifies_once(self):
        response, get = self.callback('clear')
        self.assertEqual(response.status_code, 200, response.content)
        get.assert_called_once_with(JOB)
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_status, 'approved')
        self.assertEqual(self.user.verification_job_id, JOB)
        self.assertIsNotNone(self.user.verified_at)
        self.callback('clear')                               # Smile retries
        self.assertEqual(Notification.objects.filter(
            user=self.user, notification_type='verification_approved').count(), 1)
        self.assertEqual(Attempt.objects.filter(user=self.user).count(), 1)

    def test_body_is_not_trusted(self):
        # The signature doesn't cover the body: Smile's status endpoint decides.
        self.callback('block', body={'status': 'clear'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_status, 'rejected')

    def test_attention_goes_to_review_queue(self):
        self.callback('attention')
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_status, 'pending')
        self.assertEqual(Attempt.objects.get(user=self.user).status, 'attention')

    def test_error_lets_user_retry(self):
        self.callback('error')
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_status, 'not_submitted')
        with mock.patch.object(smile, 'mint_token', return_value='t'):
            self.assertEqual(client_for(self.user).post('/api/v1/verification/smile/session/').status_code, 200)

    def test_approved_user_never_downgraded(self):
        self.callback('clear')
        Attempt.objects.create(user=self.user, method='smile')
        with mock.patch.object(smile, 'get_status', return_value=status_of(self.user, 'block')):
            client_for().post(CALLBACK, {}, format='json', **{**smile_headers(), 'HTTP_SMILEID_JOB_ID': OTHER_JOB})
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_status, 'approved')

    def test_unknown_user_acknowledged(self):
        with mock.patch.object(smile, 'get_status', return_value={
                'status': 'clear', 'user_id': '00000000-0000-0000-0000-000000000000', 'message': ''}):
            response = client_for().post(CALLBACK, {}, format='json', **smile_headers())
        self.assertEqual((response.status_code, response.json()['result']), (200, 'ignored'))

    def test_smile_down_asks_for_retry(self):
        with mock.patch.object(smile, 'get_status', side_effect=smile.SmileError('down')):
            response = client_for().post(CALLBACK, {}, format='json', **smile_headers())
        self.assertEqual(response.status_code, 503)

    def test_status_request_shape(self):
        ok = mock.Mock(status_code=200, json=lambda: {'status': 'clear', 'user_id': 'u'})
        with mock.patch.object(smile, 'mint_token', return_value='jwt'), \
                mock.patch.object(smile.requests, 'get', return_value=ok) as get:
            self.assertEqual(smile.get_status(JOB)['status'], 'clear')
        self.assertEqual(get.call_args.args[0], f'https://testapi.smileidentity.com/v3/status/{JOB}')
        self.assertEqual(get.call_args.kwargs['headers'], {'SmileID-Partner-ID': '2001', 'SmileID-Token': 'jwt'})
        with self.assertRaises(ValueError):
            smile.get_status('../../v3/token')


@override_settings(**SMILE)
class CheckJobTests(TestCase):

    def test_user_reports_own_job(self):
        user = make_user()
        Attempt.objects.create(user=user, method='smile')
        with mock.patch.object(smile, 'get_status', return_value=status_of(user, 'processing')):
            response = client_for(user).post('/api/v1/verification/check/', {'job_id': JOB}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['verification_status'], 'pending')
        with mock.patch.object(smile, 'get_status', return_value=status_of(user, 'clear')):
            response = client_for(user).get('/api/v1/verification/check/')
        self.assertTrue(response.json()['can_create_channel'])

    def test_cannot_claim_someone_elses_job(self):
        owner, thief = make_user(), make_user()
        with mock.patch.object(smile, 'get_status', return_value=status_of(owner, 'clear')):
            response = client_for(thief).post('/api/v1/verification/check/', {'job_id': JOB}, format='json')
        self.assertEqual(response.status_code, 403)
        thief.refresh_from_db()
        self.assertEqual(thief.verification_status, 'not_submitted')
        self.assertFalse(Attempt.objects.exists())

    def test_invalid_job_id(self):
        response = client_for(make_user()).post('/api/v1/verification/check/', {'job_id': 'x'}, format='json')
        self.assertEqual(response.status_code, 400)


@override_settings(**NO_SMILE, CLOUDINARY_AUTH_TOKEN_KEY='')
class ManualReviewTests(TestCase):

    def submit(self, user, **data):
        uploads = iter([{'public_id': 'abia_stream/verification_docs/doc1'},
                        {'public_id': 'abia_stream/verification_docs/selfie1'}])
        with mock.patch('verification.services.cloudinary.uploader.upload',
                        side_effect=lambda *a, **k: next(uploads)) as upload:
            response = client_for(user).post('/api/v1/verification/submit/', {
                'id_document': png(), 'selfie': png('selfie.png'), **data}, format='multipart')
        return response, upload

    def test_photos_stored_privately_and_queued(self):
        user = make_user()
        response, upload = self.submit(user, id_type='NATIONAL_ID')     # legacy name still accepted
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(upload.call_count, 2)
        for call in upload.call_args_list:
            self.assertEqual(call.kwargs['type'], 'authenticated')
        user.refresh_from_db()
        self.assertEqual(user.verification_status, 'pending')
        attempt = Attempt.objects.get(user=user)
        self.assertEqual((attempt.status, attempt.id_type), ('pending', 'IDENTITY_CARD'))
        self.assertIsNone(user.id_document_url)                # no public URL anywhere

        again, _ = self.submit(user)
        self.assertEqual(again.status_code, 400)

    def test_missing_files_and_bad_type(self):
        user = make_user()
        self.assertEqual(client_for(user).post('/api/v1/verification/submit/', {},
                                               format='multipart').status_code, 400)
        response, upload = self.submit(user, id_type='LIBRARY_CARD')
        self.assertEqual(response.status_code, 400)
        upload.assert_not_called()

    def test_admin_queue_and_decision(self):
        user = make_user()
        self.submit(user)
        admin = make_user(role=User.Role.ADMIN)
        self.assertEqual(client_for(make_user()).get('/api/v1/verification/review/').status_code, 403)

        queue = client_for(admin).get('/api/v1/verification/review/').json()['results']
        self.assertEqual(len(queue), 1)
        item = queue[0]
        self.assertIn('/image/authenticated/s--', item['document_url'])
        self.assertIn('/image/authenticated/s--', item['selfie_url'])

        url = f"/api/v1/verification/review/attempts/{item['id']}/"
        with self.captureOnCommitCallbacks(execute=True):
            response = client_for(admin).patch(url, {'decision': 'approve', 'note': 'ok',
                                                      'checklist': ALL_TICKED}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        user.refresh_from_db()
        self.assertEqual(user.verification_status, 'approved')
        self.assertTrue(Notification.objects.filter(user=user, notification_type='verification_approved').exists())
        attempt = Attempt.objects.get(pk=item['id'])
        self.assertEqual((attempt.reviewed_by_id, attempt.review_note), (admin.id, 'ok'))

        self.assertEqual(client_for(admin).patch(url, {'decision': 'reject', 'reason': 'id_expired'},
                                                  format='json').status_code, 409)
        self.assertEqual(client_for(admin).get('/api/v1/verification/review/').json()['results'], [])

    def test_reject_allows_resubmission(self):
        user = make_user()
        self.submit(user)
        admin = make_user(role=User.Role.ADMIN)
        attempt = Attempt.objects.get(user=user)
        client_for(admin).patch(f'/api/v1/verification/review/attempts/{attempt.id}/',
                                {'decision': 'reject', 'reason': 'face_mismatch'}, format='json')
        user.refresh_from_db()
        self.assertEqual(user.verification_status, 'rejected')
        response, _ = self.submit(user)
        self.assertEqual(response.status_code, 202)

    def test_legacy_per_user_override(self):
        user = make_user()
        admin = make_user(role=User.Role.ADMIN)
        response = client_for(admin).patch(f'/api/v1/verification/review/{user.id}/',
                                           {'decision': 'approve'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        user.refresh_from_db()
        self.assertEqual(user.verification_status, 'approved')
        self.assertEqual(Attempt.objects.get(user=user).reviewed_by_id, admin.id)

    def test_status_shows_latest_attempt(self):
        user = make_user()
        self.submit(user)
        body = client_for(user).get('/api/v1/verification/status/').json()
        self.assertEqual(body['latest_attempt']['status'], 'pending')
        self.assertFalse(body['can_create_channel'])


@override_settings(**NO_SMILE, CLOUDINARY_AUTH_TOKEN_KEY='')
class ReviewToolsTests(TestCase):
    """Checklist, rejection reasons, admin alerts and photo retention."""

    def setUp(self):
        self.admin = make_user(role=User.Role.ADMIN)
        self.user = make_user()
        uploads = iter([{'public_id': 'abia_stream/verification_docs/d'},
                        {'public_id': 'abia_stream/verification_docs/s'}])
        with mock.patch('verification.services.cloudinary.uploader.upload',
                        side_effect=lambda *a, **k: next(uploads)), \
                self.captureOnCommitCallbacks(execute=True):
            client_for(self.user).post('/api/v1/verification/submit/', {
                'id_document': png(), 'selfie': png('selfie.png')}, format='multipart')
        self.attempt = Attempt.objects.get(user=self.user)
        self.url = f'/api/v1/verification/review/attempts/{self.attempt.id}/'

    def decide(self, body):
        with self.captureOnCommitCallbacks(execute=True):
            return client_for(self.admin).patch(self.url, body, format='json')

    def test_admins_alerted_on_submission(self):
        alert = Notification.objects.get(user=self.admin, notification_type='verification_submitted')
        self.assertEqual(alert.data['attempt_id'], str(self.attempt.id))
        self.assertFalse(Notification.objects.filter(user=self.user,
                                                     notification_type='verification_submitted').exists())

    def test_queue_includes_checklist_and_reasons(self):
        body = client_for(self.admin).get('/api/v1/verification/review/').json()
        self.assertEqual([c['key'] for c in body['checklist']], review_rules.CHECKLIST_KEYS)
        self.assertIn('face_mismatch', [r['key'] for r in body['rejection_reasons']])

    def test_approve_requires_every_item(self):
        partial = {**ALL_TICKED, 'holding_id': False}
        response = self.decide({'decision': 'approve', 'checklist': partial})
        self.assertEqual(response.status_code, 400)
        self.assertIn('holding_id', response.json()['detail'])
        self.assertEqual(self.decide({'decision': 'approve'}).status_code, 400)
        self.assertEqual(self.decide({'decision': 'approve',
                                      'checklist': {k: 'yes' for k in ALL_TICKED}}).status_code, 400)
        response = self.decide({'decision': 'approve', 'checklist': ALL_TICKED})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['checklist'], ALL_TICKED)

    def test_reject_requires_known_reason(self):
        self.assertEqual(self.decide({'decision': 'reject'}).status_code, 400)
        self.assertEqual(self.decide({'decision': 'reject', 'reason': 'vibes'}).status_code, 400)
        self.assertEqual(self.decide({'decision': 'reject', 'reason': 'other'}).status_code, 400)

    def test_creator_told_why(self):
        response = self.decide({'decision': 'reject', 'reason': 'not_holding_id'})
        self.assertEqual(response.status_code, 200, response.content)
        notice = Notification.objects.get(user=self.user, notification_type='verification_rejected')
        self.assertIn('holding the same ID', notice.message)
        self.assertEqual(notice.data, {'reason': 'not_holding_id'})
        latest = client_for(self.user).get('/api/v1/verification/status/').json()['latest_attempt']
        self.assertEqual(latest['rejection_reason'], 'not_holding_id')
        self.assertIn('holding the same ID', latest['message'])

    def test_other_reason_uses_note(self):
        self.decide({'decision': 'reject', 'reason': 'other', 'note': 'Please use your own ID.'})
        notice = Notification.objects.get(user=self.user, notification_type='verification_rejected')
        self.assertIn('Please use your own ID.', notice.message)

    def test_photos_deleted_after_retention_only_once_decided(self):
        from datetime import timedelta
        from django.utils import timezone
        from verification.services import purge_documents
        old = timezone.now() - timedelta(days=40)

        # Still awaiting review: never deleted, however old.
        Attempt.objects.filter(pk=self.attempt.pk).update(updated_at=old)
        with mock.patch('verification.services.cloudinary.uploader.destroy') as destroy:
            self.assertEqual(purge_documents()['due'], 0)
        destroy.assert_not_called()

        self.decide({'decision': 'approve', 'checklist': ALL_TICKED})
        with mock.patch('verification.services.cloudinary.uploader.destroy') as destroy:
            self.assertEqual(purge_documents()['due'], 0)          # decided just now
        destroy.assert_not_called()

        Attempt.objects.filter(pk=self.attempt.pk).update(updated_at=old)
        self.assertEqual(purge_documents(dry_run=True), {'due': 1, 'purged': 0, 'failed': 0})
        with mock.patch('verification.services.cloudinary.uploader.destroy',
                        return_value={'result': 'ok'}) as destroy:
            self.assertEqual(purge_documents(), {'due': 1, 'purged': 1, 'failed': 0})
        self.assertEqual(destroy.call_count, 2)
        self.assertEqual(destroy.call_args.kwargs['type'], 'authenticated')
        self.attempt.refresh_from_db()
        self.assertIsNone(self.attempt.document_public_id)
        self.assertIsNotNone(self.attempt.documents_purged_at)
        self.assertEqual(self.attempt.status, 'approved')           # the record stays
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_status, 'approved')

    def test_failed_delete_is_retried_later(self):
        from datetime import timedelta
        from django.utils import timezone
        from verification.services import purge_documents
        self.decide({'decision': 'reject', 'reason': 'unreadable'})
        Attempt.objects.filter(pk=self.attempt.pk).update(updated_at=timezone.now() - timedelta(days=40))
        with mock.patch('verification.services.cloudinary.uploader.destroy',
                        return_value={'result': 'error'}):
            self.assertEqual(purge_documents()['failed'], 1)
        self.attempt.refresh_from_db()
        self.assertIsNotNone(self.attempt.document_public_id)
        with mock.patch('verification.services.cloudinary.uploader.destroy',
                        return_value={'result': 'not found'}):
            self.assertEqual(purge_documents()['purged'], 1)
