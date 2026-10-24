"""Email providers, and what users see when email can't be sent."""
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from abiastream.testing import client_for, make_user
from accounts import email_service
from accounts.models import User


@override_settings(EMAIL_PROVIDER='brevo', BREVO_API_KEY='brevo-key',
                   DEFAULT_FROM_EMAIL='abiastream@gmail.com', EMAIL_FROM_NAME='Abia Stream')
class BrevoTests(TestCase):

    def test_request_shape(self):
        ok = mock.Mock(status_code=201, text='{"messageId":"x"}')
        with mock.patch.object(email_service.requests, 'post', return_value=ok) as post:
            email_service.send_verification_otp('ada@example.com', '123456')
        args, kwargs = post.call_args
        self.assertEqual(args[0], 'https://api.brevo.com/v3/smtp/email')
        self.assertEqual(kwargs['headers']['api-key'], 'brevo-key')
        body = kwargs['json']
        self.assertEqual(body['sender'], {'name': 'Abia Stream', 'email': 'abiastream@gmail.com'})
        self.assertEqual(body['to'], [{'email': 'ada@example.com'}])
        self.assertIn('123456', body['htmlContent'])

    def test_rejection_raises(self):
        bad = mock.Mock(status_code=400, text='{"message":"sender not valid"}')
        with mock.patch.object(email_service.requests, 'post', return_value=bad):
            with self.assertRaises(email_service.EmailDeliveryError):
                email_service.send_password_reset_otp('ada@example.com', '1')


@override_settings(EMAIL_PROVIDER='apps_script', APPS_SCRIPT_EMAIL_URL='https://script.google.com/macros/s/X/exec',
                   APPS_SCRIPT_EMAIL_SECRET='s3cret', EMAIL_FROM_NAME='Abia Stream')
class AppsScriptTests(TestCase):

    def test_request_shape(self):
        ok = mock.Mock(status_code=200, json=lambda: {'ok': True, 'remaining': 99})
        with mock.patch.object(email_service.requests, 'post', return_value=ok) as post:
            email_service.send_verification_otp('ada@example.com', '654321')
        args, kwargs = post.call_args
        self.assertEqual(args[0], 'https://script.google.com/macros/s/X/exec')
        body = kwargs['json']
        self.assertEqual((body['secret'], body['to'], body['name']), ('s3cret', 'ada@example.com', 'Abia Stream'))
        self.assertIn('654321', body['html'])

    def test_script_refusal_raises(self):
        for answer in ({'ok': False, 'error': 'daily Gmail quota used up'}, ValueError):
            response = mock.Mock(status_code=200, text='<html>sign in</html>')
            response.json = mock.Mock(side_effect=answer) if answer is ValueError else (lambda a=answer: a)
            with mock.patch.object(email_service.requests, 'post', return_value=response):
                with self.assertRaises(email_service.EmailDeliveryError):
                    email_service.send_email('a@example.com', 's', 'h')

    @override_settings(APPS_SCRIPT_EMAIL_URL='')
    def test_not_configured(self):
        with mock.patch.object(email_service.requests, 'post') as post:
            with self.assertRaises(email_service.EmailDeliveryError):
                email_service.send_email('a@example.com', 's', 'h')
        post.assert_not_called()


class ProviderSelectionTests(TestCase):

    @override_settings(EMAIL_PROVIDER='resend', RESEND_API_KEY='re_test')
    def test_resend_errors_are_wrapped(self):
        with mock.patch('resend.Emails.send', side_effect=RuntimeError('only to owner')):
            with self.assertRaises(email_service.EmailDeliveryError):
                email_service.send_email('a@example.com', 's', 'h')

    @override_settings(EMAIL_PROVIDER='pigeon')
    def test_unknown_provider(self):
        with self.assertRaises(email_service.EmailDeliveryError):
            email_service.send_email('a@example.com', 's', 'h')


class EmailFailureResponsesTests(TestCase):

    def test_resend_code_failure_is_503(self):
        user = make_user(is_email_verified=False, status=User.Status.PENDING_VERIFICATION)
        with mock.patch('accounts.views.send_verification_otp', side_effect=RuntimeError('down')):
            response = client_for().post('/api/v1/auth/resend-otp/', {'email': user.email}, format='json')
        self.assertEqual(response.status_code, 503)

    def test_forgot_password_failure_is_503(self):
        user = make_user()
        with mock.patch('accounts.views.send_password_reset_otp', side_effect=RuntimeError('down')):
            response = client_for().post('/api/v1/auth/forgot-password/', {'email': user.email}, format='json')
        self.assertEqual(response.status_code, 503)


class VideoUploadValidationTests(TestCase):
    """videos/views.py caught the Resend library's ValidationError, so rejected files gave 500."""

    def test_disguised_file_is_400(self):
        fake = SimpleUploadedFile('clip.mp4', b'MZ' + b'\x00' * 4096, content_type='video/mp4')
        response = client_for(make_user()).post('/api/v1/videos/upload/',
                                                {'title': 'x', 'video_file': fake}, format='multipart')
        self.assertEqual(response.status_code, 400, response.content)
