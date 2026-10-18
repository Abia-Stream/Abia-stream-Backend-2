"""
Smile ID v3 client for Document Verification through the Smile Web SDK.

Flow:
  1. The frontend asks us for a session token (mint_token). We bind our user
     id into it, so the job Smile creates is tied to that user.
  2. The frontend runs Smile's hosted capture flow (selfie, liveness frames,
     ID document) and submits straight to Smile.
  3. Smile POSTs the verdict to our webhook. Its signature only covers a
     timestamp, not the body, so the webhook is treated as a "go and check"
     signal: the verdict we act on always comes from get_status().

Docs: https://docs.usesmileid.com/api-reference/authentication
      https://docs.usesmileid.com/api-reference/core-resources/verification-status
      https://docs.usesmileid.com/developer-resources/essentials/verification-webhooks/receive-webhooks
"""
import base64
import hashlib
import hmac
import re

import requests
from django.conf import settings

SANDBOX_URL = 'https://testapi.smileidentity.com'
PRODUCTION_URL = 'https://api.smileidentity.com'
TOKEN_PRODUCT = 'document_verification'      # name used by POST /v3/token
WEB_SDK_PRODUCT = 'doc_verification'         # name used by window.SmileIdentity
TIMEOUT = 20
JOB_ID_RE = re.compile(r'^job_[0-9a-hjkmnp-tv-z]{26}$')

# Terminal verdicts returned by GET /v3/status/{job_id}.
CLEAR, ATTENTION, BLOCK, ERROR, PROCESSING, NOT_FOUND = (
    'clear', 'attention', 'block', 'error', 'processing', 'not_found')
TERMINAL = (CLEAR, ATTENTION, BLOCK, ERROR)


class SmileError(Exception):
    """Smile could not be reached or refused the request."""


def is_configured():
    return bool(settings.SMILE_IDENTITY_PARTNER_ID and settings.SMILE_IDENTITY_API_KEY)


def environment():
    return 'production' if settings.SMILE_IDENTITY_ENVIRONMENT == 'production' else 'sandbox'


def base_url():
    return PRODUCTION_URL if environment() == 'production' else SANDBOX_URL


def smile_user_id(user):
    """The user id bound into tokens and echoed back in results."""
    return str(user.id)


def _api_error(response):
    try:
        message = response.json().get('message')
    except ValueError:
        message = None
    return SmileError(f'Smile ID returned {response.status_code}: {message or response.text[:200]}')


def mint_token(user_id=None):
    """POST /v3/token. Tokens live 15 minutes; mint one per session."""
    data = {'product': TOKEN_PRODUCT}
    if user_id:
        data['user_id'] = user_id
    try:
        response = requests.post(
            f'{base_url()}/v3/token',
            headers={'smileid-partner-id': str(settings.SMILE_IDENTITY_PARTNER_ID),
                     'smileid-api-key': settings.SMILE_IDENTITY_API_KEY},
            # multipart/form-data, as the endpoint requires
            files={key: (None, value) for key, value in data.items()},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SmileError(f'Could not reach Smile ID: {exc}') from exc
    if response.status_code != 200:
        raise _api_error(response)
    token = response.json().get('token')
    if not token:
        raise SmileError('Smile ID returned no token.')
    return token


def get_status(job_id):
    """
    GET /v3/status/{job_id} -> {'status', 'user_id', 'message', ...}.
    status is one of clear, attention, block, error, processing, not_found.
    """
    if not JOB_ID_RE.match(job_id or ''):
        raise ValueError('Not a Smile ID job id.')
    token = mint_token()
    try:
        response = requests.get(
            f'{base_url()}/v3/status/{job_id}',
            headers={'SmileID-Partner-ID': str(settings.SMILE_IDENTITY_PARTNER_ID),
                     'SmileID-Token': token},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SmileError(f'Could not reach Smile ID: {exc}') from exc
    if response.status_code == 404:
        return {'status': NOT_FOUND, 'user_id': None, 'message': 'Job not found.'}
    if response.status_code not in (200, 202):
        raise _api_error(response)
    return response.json()


def expected_signature(timestamp):
    digest = hmac.new(settings.SMILE_IDENTITY_API_KEY.encode('utf-8'),
                      f'{timestamp}{settings.SMILE_IDENTITY_PARTNER_ID}sid_request'.encode('utf-8'),
                      hashlib.sha256).digest()
    return base64.b64encode(digest).decode('ascii')


def webhook_signature_valid(timestamp, signature):
    """Response-Signature = base64(HMAC-SHA256(api_key, timestamp + partner_id + 'sid_request'))."""
    if not (is_configured() and timestamp and signature):
        return False
    return hmac.compare_digest(expected_signature(timestamp), signature)
