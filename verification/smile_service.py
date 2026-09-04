import base64
import hashlib
import json
import time
import requests
from django.conf import settings


SMILE_SANDBOX_URL = 'https://testapi.smileidentity.com/v1'
SMILE_PROD_URL = 'https://api.smileidentity.com/v1'


def get_api_url():
    if settings.SMILE_IDENTITY_ENVIRONMENT == 'production':
        return SMILE_PROD_URL
    return SMILE_SANDBOX_URL


def encode_image(image_file):
    """Convert image file to base64."""
    image_file.seek(0)
    return base64.b64encode(image_file.read()).decode('utf-8')


def generate_signature():
    """Generate Smile Identity API signature."""
    timestamp = str(int(time.time()))
    partner_id = settings.SMILE_IDENTITY_PARTNER_ID
    api_key = settings.SMILE_IDENTITY_API_KEY

    signature_string = f'{timestamp}{partner_id}{api_key}'
    signature = hashlib.sha256(signature_string.encode()).hexdigest()

    return {
        'signature': signature,
        'timestamp': timestamp,
    }


def submit_kyc_verification(user, id_image_file, selfie_image_file, id_type='NATIONAL_ID'):
    """
    Submit KYC verification to Smile Identity.

    id_type options:
    - NATIONAL_ID
    - DRIVERS_LICENSE
    - PASSPORT
    - VOTERS_ID
    """
    sig = generate_signature()

    # Encode images to base64
    id_image_b64 = encode_image(id_image_file)
    selfie_b64 = encode_image(selfie_image_file)

    job_id = f'job_{user.id}_{int(time.time())}'

    payload = {
        'source_sdk': 'rest_api',
        'source_sdk_version': '1.0.0',
        'partner_id': settings.SMILE_IDENTITY_PARTNER_ID,
        'signature': sig['signature'],
        'timestamp': sig['timestamp'],
        'smile_client_id': str(user.id),
        'job_id': job_id,
        'job_type': 1,  # 1 = SmartSelfie + ID verification
        'country': 'NG',  # Nigeria — update based on user's country
        'id_type': id_type,
        'images': [
            {
                'image_type_id': 1,  # selfie
                'image': selfie_b64,
            },
            {
                'image_type_id': 3,  # ID document front
                'image': id_image_b64,
            },
        ],
        'return_job_status': True,
        'return_history': False,
        'return_images': False,
    }

    try:
        response = requests.post(
            f'{get_api_url()}/submission',
            json=payload,
            timeout=30
        )
        result = response.json()
        return result, job_id
    except Exception as e:
        return {'error': str(e)}, job_id


def check_verification_status(job_id, user_id):
    """Check the status of a verification job."""
    sig = generate_signature()

    payload = {
        'partner_id': settings.SMILE_IDENTITY_PARTNER_ID,
        'signature': sig['signature'],
        'timestamp': sig['timestamp'],
        'job_id': job_id,
        'user_id': str(user_id),
        'return_job_status': True,
        'return_history': False,
        'return_images': False,
    }

    try:
        response = requests.post(
            f'{get_api_url()}/job_status',
            json=payload,
            timeout=30
        )
        return response.json()
    except Exception as e:
        return {'error': str(e)}