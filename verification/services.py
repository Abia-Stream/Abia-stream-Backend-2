"""
Identity verification state changes. Every path (Smile webhook, the user's
own status check, admin review) goes through record_outcome(), which locks
the user and the attempt, applies each outcome once, and never downgrades
an approved user.
"""
import logging
import uuid

import cloudinary.uploader
import cloudinary.utils
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from verification import smile_service as smile
from verification.models import VerificationAttempt as Attempt

logger = logging.getLogger(__name__)

DOCUMENT_FOLDER = 'abia_stream/verification_docs'

# Smile verdict -> attempt status
SMILE_OUTCOMES = {
    smile.CLEAR: Attempt.Status.APPROVED,
    smile.BLOCK: Attempt.Status.REJECTED,
    smile.ATTENTION: Attempt.Status.ATTENTION,
    smile.ERROR: Attempt.Status.ERROR,
}

NOTIFICATIONS = {
    Attempt.Status.APPROVED: ('verification_approved', 'Identity Verified',
                              'Your identity has been verified. You can now create a channel.'),
    Attempt.Status.REJECTED: ('verification_rejected', 'Verification Failed',
                              'Your identity verification was not approved. You can try again '
                              'with clear photos of a valid ID.'),
    Attempt.Status.ERROR: ('verification_error', 'Verification Not Completed',
                           "We couldn't complete your identity verification. Please try again."),
}


class VerificationError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def can_start(user):
    """None if the user may start a new attempt, else the reason they can't."""
    if user.verification_status == User.VerificationStatus.APPROVED:
        return 'Your identity is already verified.'
    if user.verification_status == User.VerificationStatus.PENDING:
        return 'Your verification is pending review.'
    return None


# ── Outcomes ──────────────────────────────────────────────────────────────────

def record_outcome(attempt_id, outcome, message=None, *, result_status=None,
                   reviewer=None, note=None):
    """
    Apply an outcome (an Attempt.Status) to an attempt and its user.
    Returns True if anything changed. Final attempts are never changed again,
    so webhook retries and repeated status checks are harmless.
    """
    with transaction.atomic():
        attempt = Attempt.objects.select_for_update().get(pk=attempt_id)
        user = User.objects.select_for_update().get(pk=attempt.user_id)
        if attempt.status in Attempt.FINAL or attempt.status == outcome:
            return False

        now = timezone.now()
        attempt.status = outcome
        attempt.result_status = result_status or attempt.result_status
        attempt.result_message = message or attempt.result_message
        attempt.updated_at = now
        if reviewer is not None:
            attempt.reviewed_by = reviewer
            attempt.reviewed_at = now
            attempt.review_note = note
        attempt.save()

        already_approved = user.verification_status == User.VerificationStatus.APPROVED
        fields = []
        if outcome == Attempt.Status.APPROVED and not already_approved:
            user.verification_status = User.VerificationStatus.APPROVED
            user.verified_at = now
            fields += ['verification_status', 'verified_at']
        elif not already_approved:
            user.verification_status = {
                Attempt.Status.REJECTED: User.VerificationStatus.REJECTED,
                Attempt.Status.ATTENTION: User.VerificationStatus.PENDING,
                Attempt.Status.PENDING: User.VerificationStatus.PENDING,
                # A processing error isn't a decision about the person: let them retry.
                Attempt.Status.ERROR: User.VerificationStatus.NOT_SUBMITTED,
            }[outcome]
            fields.append('verification_status')
        if attempt.smile_job_id and user.verification_job_id != attempt.smile_job_id:
            user.verification_job_id = attempt.smile_job_id
            fields.append('verification_job_id')
        if fields:
            user.save(update_fields=fields)

        if outcome in NOTIFICATIONS and not (already_approved and outcome != Attempt.Status.APPROVED):
            notification_type, title, text = NOTIFICATIONS[outcome]
            transaction.on_commit(lambda: _notify(user, notification_type, title, text))
        return True


def _notify(user, notification_type, title, text):
    from notifications.utils import create_notification
    create_notification(user=user, notification_type=notification_type,
                        title=title, message=text, data={})


# ── Smile ID ──────────────────────────────────────────────────────────────────

def start_smile_session(user):
    """Mint a Smile token bound to this user and open an attempt."""
    reason = can_start(user)
    if reason:
        raise VerificationError(reason)
    if not smile.is_configured():
        raise VerificationError('Automatic identity verification is not available right now. '
                                'You can submit your ID for manual review instead.', 503)
    try:
        token = smile.mint_token(smile.smile_user_id(user))
    except smile.SmileError:
        logger.exception('Smile token request failed')
        raise VerificationError('Identity verification is temporarily unavailable. '
                                'Please try again later.', 503)
    Attempt.objects.create(user=user, method=Attempt.Method.SMILE)
    return token


def sync_smile_job(job_id, user=None):
    """
    Ask Smile for a job's verdict and apply it. With `user`, the job must
    belong to that user (a user reporting their own job id); without, the
    owner is taken from Smile's answer (the webhook).
    Returns (attempt, smile_status).
    """
    status = smile.get_status(job_id)
    if status.get('status') == smile.NOT_FOUND:
        raise VerificationError('Verification job not found.', 404)

    owner_id = status.get('user_id')
    if user is not None:
        if owner_id != smile.smile_user_id(user):
            raise VerificationError('This verification job does not belong to you.', 403)
        owner = user
    else:
        try:
            owner = User.objects.get(pk=uuid.UUID(str(owner_id)))
        except (ValueError, User.DoesNotExist):
            raise VerificationError('Verification job is not linked to a known user.', 404)

    attempt = _attempt_for_job(owner, job_id)
    verdict = status.get('status')
    message = status.get('message')
    if verdict in SMILE_OUTCOMES:
        record_outcome(attempt.id, SMILE_OUTCOMES[verdict], message, result_status=verdict)
    elif attempt.status == Attempt.Status.STARTED:
        # Submitted and still processing: show it as pending.
        record_outcome(attempt.id, Attempt.Status.PENDING, message, result_status=verdict)
    attempt.refresh_from_db()
    return attempt, verdict


def _attempt_for_job(user, job_id):
    with transaction.atomic():
        attempt = Attempt.objects.select_for_update().filter(smile_job_id=job_id).first()
        if attempt:
            return attempt
        attempt = (Attempt.objects.select_for_update()
                   .filter(user=user, method=Attempt.Method.SMILE,
                           status=Attempt.Status.STARTED, smile_job_id__isnull=True)
                   .first())
        if attempt is None:
            attempt = Attempt(user=user, method=Attempt.Method.SMILE)
        attempt.smile_job_id = job_id
        attempt.updated_at = timezone.now()
        attempt.save()
        return attempt


# ── Manual review ─────────────────────────────────────────────────────────────

def submit_manual(user, id_document, selfie, id_type):
    """Store the photos privately and queue the attempt for an admin."""
    reason = can_start(user)
    if reason:
        raise VerificationError(reason)
    document = _upload_private(id_document)
    selfie_upload = _upload_private(selfie)
    attempt = Attempt.objects.create(
        user=user, method=Attempt.Method.MANUAL, status=Attempt.Status.STARTED, id_type=id_type,
        document_public_id=document, selfie_public_id=selfie_upload)
    record_outcome(attempt.id, Attempt.Status.PENDING)
    return attempt


def _upload_private(file):
    file.seek(0)
    result = cloudinary.uploader.upload(
        file, resource_type='image', type='authenticated', folder=DOCUMENT_FOLDER)
    return result['public_id']


def signed_image_url(public_id):
    """Signed URL for a private image (expires if CLOUDINARY_AUTH_TOKEN_KEY is set)."""
    if not public_id:
        return None
    options = {'resource_type': 'image', 'type': 'authenticated', 'sign_url': True, 'secure': True}
    key = getattr(settings, 'CLOUDINARY_AUTH_TOKEN_KEY', '')
    if key:
        options['auth_token'] = {'key': key, 'duration': settings.SIGNED_URL_TTL_SECONDS}
    url, _ = cloudinary.utils.cloudinary_url(public_id, **options)
    return url


def review(attempt_id, reviewer, decision, note=None):
    """Admin decision on an attempt in the queue."""
    outcome = {'approve': Attempt.Status.APPROVED, 'reject': Attempt.Status.REJECTED}.get(decision)
    if outcome is None:
        raise VerificationError('decision must be approve or reject.')
    attempt = Attempt.objects.filter(pk=attempt_id).first()
    if attempt is None:
        raise VerificationError('Verification attempt not found.', 404)
    if attempt.status not in Attempt.IN_REVIEW:
        raise VerificationError('This attempt is not awaiting review.', 409)
    record_outcome(attempt.id, outcome, reviewer=reviewer, note=note)
    attempt.refresh_from_db()
    return attempt
