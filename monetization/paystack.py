"""
Minimal Paystack client (https://api.paystack.co, Bearer secret key).

Endpoints and fields follow Paystack's published OpenAPI spec
(github.com/PaystackOSS/openapi, dist/paystack.yaml). Amounts are kobo.

Webhooks: Paystack signs the raw request body with HMAC-SHA512 keyed by the
secret key and sends the hex digest in `x-paystack-signature`; it retries
non-200 responses and may deliver duplicates.
"""
import hashlib
import hmac

import requests
from django.conf import settings

BASE_URL = 'https://api.paystack.co'
TIMEOUT_SECONDS = 20


class PaystackError(Exception):
    pass


def configured():
    return bool(getattr(settings, 'PAYSTACK_SECRET_KEY', ''))


def _call(method, path, **kwargs):
    if not configured():
        raise PaystackError('Payments are not configured (PAYSTACK_SECRET_KEY is missing).')
    try:
        response = requests.request(
            method, BASE_URL + path, timeout=TIMEOUT_SECONDS,
            headers={'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}'}, **kwargs)
    except requests.RequestException as exc:
        raise PaystackError(f'Paystack unreachable: {exc}') from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok or body.get('status') is False:
        raise PaystackError(body.get('message') or f'Paystack error {response.status_code}')
    return body.get('data', body)


def initialize_transaction(*, email, amount_kobo, reference, metadata, plan=None, callback_url=None):
    payload = {'email': email, 'amount': amount_kobo, 'reference': reference,
               'currency': 'NGN', 'metadata': metadata}
    if plan:
        payload['plan'] = plan
    if callback_url:
        payload['callback_url'] = callback_url
    return _call('POST', '/transaction/initialize', json=payload)


def verify_transaction(reference):
    return _call('GET', f'/transaction/verify/{reference}')


def create_plan(*, name, amount_kobo, interval='monthly'):
    return _call('POST', '/plan', json={'name': name, 'amount': amount_kobo,
                                         'interval': interval, 'currency': 'NGN'})


def disable_subscription(*, code, email_token):
    return _call('POST', '/subscription/disable', json={'code': code, 'token': email_token})


def list_banks():
    return _call('GET', '/bank', params={'country': 'nigeria', 'perPage': 100})


def resolve_account(*, account_number, bank_code):
    return _call('GET', '/bank/resolve', params={'account_number': account_number,
                                                  'bank_code': bank_code})


def create_transfer_recipient(*, name, account_number, bank_code):
    return _call('POST', '/transferrecipient', json={
        'type': 'nuban', 'name': name, 'account_number': account_number,
        'bank_code': bank_code, 'currency': 'NGN'})


def initiate_transfer(*, amount_kobo, recipient_code, reference, reason):
    return _call('POST', '/transfer', json={
        'source': 'balance', 'amount': amount_kobo, 'recipient': recipient_code,
        'reference': reference, 'reason': reason, 'currency': 'NGN'})


def signature_valid(raw_body, signature):
    if not configured() or not signature:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode('utf-8'), raw_body,
                        hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
