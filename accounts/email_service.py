"""
Transactional email (verification and password-reset codes).

The provider is chosen by settings.EMAIL_PROVIDER:
  resend - Resend API. Needs a domain verified in Resend; the default sender
           onboarding@resend.dev can only deliver to the Resend account owner.
  brevo  - Brevo API. Can send from a single verified address, no domain needed.
Failures raise EmailDeliveryError so callers can tell the user.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BREVO_URL = 'https://api.brevo.com/v3/smtp/email'
TIMEOUT = 15


class EmailDeliveryError(Exception):
    pass


def _send_resend(to, subject, html):
    import resend
    resend.api_key = settings.RESEND_API_KEY
    try:
        resend.Emails.send({
            'from': f'{settings.EMAIL_FROM_NAME} <{settings.DEFAULT_FROM_EMAIL}>',
            'to': to,
            'subject': subject,
            'html': html,
        })
    except Exception as exc:  # noqa: BLE001 - resend raises several unrelated types
        raise EmailDeliveryError(f'Resend: {exc}') from exc


def _send_brevo(to, subject, html):
    try:
        response = requests.post(
            BREVO_URL,
            headers={'api-key': settings.BREVO_API_KEY, 'accept': 'application/json'},
            json={
                'sender': {'name': settings.EMAIL_FROM_NAME, 'email': settings.DEFAULT_FROM_EMAIL},
                'to': [{'email': to}],
                'subject': subject,
                'htmlContent': html,
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise EmailDeliveryError(f'Brevo: {exc}') from exc
    if response.status_code not in (201, 202):
        raise EmailDeliveryError(f'Brevo returned {response.status_code}: {response.text[:300]}')


PROVIDERS = {'resend': _send_resend, 'brevo': _send_brevo}


def send_email(to, subject, html):
    provider = PROVIDERS.get(settings.EMAIL_PROVIDER)
    if provider is None:
        raise EmailDeliveryError(f'Unknown EMAIL_PROVIDER {settings.EMAIL_PROVIDER!r}')
    provider(to, subject, html)


def _code_email(heading, intro, otp, footer):
    return f"""
        <div style="font-family: sans-serif; max-width: 400px; margin: auto;">
            <h2>{heading}</h2>
            <p>{intro}</p>
            <h1 style="letter-spacing: 8px; color: #4F46E5;">{otp}</h1>
            <p style="color: #888;">{footer}</p>
        </div>
    """


def send_verification_otp(email: str, otp: str):
    send_email(email, 'Verify your email', _code_email(
        'Email Verification', 'Enter this code to verify your email:', otp,
        'Expires in 10 minutes. Do not share this code.'))


def send_password_reset_otp(email: str, otp: str):
    send_email(email, 'Password Reset Code', _code_email(
        'Password Reset', 'Enter this code to reset your password:', otp,
        "Expires in 10 minutes. Ignore if you didn't request this."))
