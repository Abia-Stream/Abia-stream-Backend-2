"""
Identity verification. Two ways in:
  - Smile ID (automatic): GET /verification/config/, POST /verification/smile/session/,
    then Smile's Web SDK; the verdict arrives at /verification/smile/callback/.
  - Manual review: POST /verification/submit/ with photos; an admin decides.
See FRONTEND_INTEGRATION.md, "Identity verification".
"""
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from moderation.permissions import IsAdmin
from verification import review as review_rules
from verification import services
from verification import smile_service as smile
from verification.models import VerificationAttempt as Attempt
from videos.file_security import validate_image_file

logger = logging.getLogger(__name__)

# Document types offered on the manual form (Smile's hosted flow has its own picker).
ID_TYPES = ['IDENTITY_CARD', 'DRIVERS_LICENSE', 'PASSPORT', 'VOTER_ID', 'RESIDENT_ID']
# Older clients sent these names.
LEGACY_ID_TYPES = {'NATIONAL_ID': 'IDENTITY_CARD', 'VOTERS_ID': 'VOTER_ID'}


def _error(exc):
    return Response({'detail': str(exc)}, status=exc.status_code)


def _callback_url(request):
    return request.build_absolute_uri('/api/v1/verification/smile/callback/')


def _latest_attempt(user):
    attempt = user.verification_attempts.order_by('-created_at').first()
    if attempt is None:
        return None
    message = attempt.result_message
    if attempt.status == Attempt.Status.REJECTED and attempt.rejection_reason:
        message = review_rules.creator_message(attempt.rejection_reason, attempt.review_note)
    return {'id': str(attempt.id), 'method': attempt.method, 'status': attempt.status,
            'rejection_reason': attempt.rejection_reason, 'message': message,
            'created_at': attempt.created_at}


class VerificationConfigView(APIView):
    """
    GET /api/v1/verification/config/
    What the frontend needs to choose a flow and initialise Smile's Web SDK.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        enabled = smile.is_configured()
        return Response({
            'smile_enabled': enabled,
            'manual_review_enabled': True,
            'smile': {
                'partner_id': str(settings.SMILE_IDENTITY_PARTNER_ID),
                'environment': smile.environment(),
                'product': smile.WEB_SDK_PRODUCT,
                'callback_url': _callback_url(request),
            } if enabled else None,
            'manual_id_types': ID_TYPES,
        })


class SmileSessionView(APIView):
    """
    POST /api/v1/verification/smile/session/
    Returns a 15-minute Smile token for window.SmileIdentity({token, ...}).
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'verification'

    def post(self, request):
        try:
            token = services.start_smile_session(request.user)
        except services.VerificationError as exc:
            return _error(exc)
        return Response({
            'token': token,
            'partner_id': str(settings.SMILE_IDENTITY_PARTNER_ID),
            'environment': smile.environment(),
            'product': smile.WEB_SDK_PRODUCT,
            'callback_url': _callback_url(request),
        })


class SmileCallbackView(APIView):
    """
    POST /api/v1/verification/smile/callback/   (called by Smile ID)
    The signature covers only a timestamp, so the body is never trusted: the
    job's verdict is fetched from Smile before anything changes.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        if not smile.webhook_signature_valid(request.headers.get('Response-Timestamp'),
                                             request.headers.get('Response-Signature')):
            return Response({'detail': 'Invalid signature.'}, status=status.HTTP_401_UNAUTHORIZED)
        job_id = request.headers.get('smileid-job-id') or (
            (request.data.get('partner_params') or {}).get('job_id')
            if isinstance(request.data, dict) else None)
        if not job_id or not smile.JOB_ID_RE.match(job_id):
            return Response({'detail': 'Missing job id.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            attempt, verdict = services.sync_smile_job(job_id)
        except services.VerificationError as exc:
            # Unknown job or user: acknowledge so Smile stops retrying.
            logger.warning('Smile callback for %s ignored: %s', job_id, exc)
            return Response({'result': 'ignored'})
        except smile.SmileError:
            logger.exception('Smile status check failed for %s', job_id)
            # Non-2xx makes Smile retry the webhook.
            return Response({'detail': 'Temporarily unavailable.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({'result': attempt.status, 'smile_status': verdict})


class SubmitVerificationView(APIView):
    """
    POST /api/v1/verification/submit/   (multipart/form-data)
    Manual review: id_document (file), selfie (file), id_type (see config).
    Photos are stored privately and only admins can view them.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'verification'

    def post(self, request):
        reason = services.can_start(request.user)
        if reason:
            return Response({'detail': reason}, status=status.HTTP_400_BAD_REQUEST)

        id_document = request.FILES.get('id_document')
        selfie = request.FILES.get('selfie')
        id_type = request.data.get('id_type', 'IDENTITY_CARD')
        id_type = LEGACY_ID_TYPES.get(id_type, id_type)
        if not id_document:
            return Response({'detail': 'id_document is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not selfie:
            return Response({'detail': 'selfie is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if id_type not in ID_TYPES:
            return Response({'detail': f'Invalid id_type. Choose from: {ID_TYPES}'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_image_file(id_document)
            validate_image_file(selfie)
        except Exception as exc:  # noqa: BLE001 - validation errors carry the user message
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            services.submit_manual(request.user, id_document, selfie, id_type)
        except services.VerificationError as exc:
            return _error(exc)
        except Exception:  # noqa: BLE001 - Cloudinary failure
            logger.exception('Verification document upload failed')
            return Response({'detail': 'We could not upload your documents. Please try again.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({
            'detail': 'Verification submitted. Under review — you will be notified once approved.',
            'verification_status': User.VerificationStatus.PENDING,
        }, status=status.HTTP_202_ACCEPTED)


class VerificationStatusView(APIView):
    """GET /api/v1/verification/status/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            'verification_status': user.verification_status,
            'verified_at': user.verified_at,
            'can_create_channel': user.verification_status == User.VerificationStatus.APPROVED,
            'latest_attempt': _latest_attempt(user),
        })


class CheckVerificationJobView(APIView):
    """
    POST /api/v1/verification/check/  {"job_id": "job_..."}   after Smile's onResult
    GET  /api/v1/verification/check/                          re-check the latest Smile job
    Asks Smile for the verdict now instead of waiting for the webhook.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        attempt = (request.user.verification_attempts
                   .filter(method=Attempt.Method.SMILE, smile_job_id__isnull=False)
                   .order_by('-created_at').first())
        return self._check(request, attempt.smile_job_id if attempt else None)

    def post(self, request):
        return self._check(request, request.data.get('job_id'))

    def _check(self, request, job_id):
        user = request.user
        if not job_id:
            return Response({'detail': 'No verification job found.'}, status=status.HTTP_404_NOT_FOUND)
        if not smile.JOB_ID_RE.match(str(job_id)):
            return Response({'detail': 'Invalid job_id.'}, status=status.HTTP_400_BAD_REQUEST)
        if not smile.is_configured():
            return Response({'detail': 'Identity verification is temporarily unavailable.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            services.sync_smile_job(job_id, user=user)
        except services.VerificationError as exc:
            return _error(exc)
        except smile.SmileError:
            logger.exception('Smile status check failed for %s', job_id)
            return Response({'detail': 'Could not check with the verification provider. Try again shortly.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        user.refresh_from_db()
        return Response({
            'verification_status': user.verification_status,
            'verified_at': user.verified_at,
            'can_create_channel': user.verification_status == User.VerificationStatus.APPROVED,
            'latest_attempt': _latest_attempt(user),
        })


# ── Admin ─────────────────────────────────────────────────────────────────────

def _full_name(user):
    profile = getattr(user, 'profile', None)    # None when the user has no profile row
    return profile.full_name if profile else None


def _attempt_for_admin(attempt):
    user = attempt.user
    return {
        'id': str(attempt.id),
        'method': attempt.method,
        'status': attempt.status,
        'id_type': attempt.id_type,
        'smile_job_id': attempt.smile_job_id,
        'result_status': attempt.result_status,
        'result_message': attempt.result_message,
        # Signed, private links. Smile's own photos are in the Smile portal.
        'document_url': services.signed_image_url(attempt.document_public_id),
        'selfie_url': services.signed_image_url(attempt.selfie_public_id),
        'created_at': attempt.created_at,
        'reviewed_at': attempt.reviewed_at,
        'review_note': attempt.review_note,
        'rejection_reason': attempt.rejection_reason,
        'checklist': attempt.checklist,
        'documents_purged': attempt.documents_purged_at is not None,
        'user': {'id': str(user.id), 'email': user.email, 'full_name': _full_name(user),
                 'verification_status': user.verification_status},
    }


class ReviewQueueView(APIView):
    """
    GET /api/v1/verification/review/?status=pending|attention
    Attempts awaiting an admin decision, oldest first, plus the checklist and
    rejection reasons to show next to each one.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        statuses = Attempt.IN_REVIEW
        if request.query_params.get('status') in statuses:
            statuses = (request.query_params['status'],)
        attempts = (Attempt.objects.filter(status__in=statuses)
                    .select_related('user', 'user__profile').order_by('created_at')[:100])
        return Response({'results': [_attempt_for_admin(a) for a in attempts],
                         **review_rules.options()})


class ReviewAttemptView(APIView):
    """
    PATCH /api/v1/verification/review/attempts/<attempt_id>/
    Approve: {"decision": "approve", "checklist": {"name_matches": true, ...every item}}
    Reject:  {"decision": "reject", "reason": "face_mismatch", "note": "optional"}
             (reason "other" needs a note; the creator sees the reason's message)
    """
    permission_classes = [IsAdmin]

    def patch(self, request, attempt_id):
        try:
            attempt = services.review(attempt_id, request.user, request.data.get('decision'),
                                      request.data.get('note'), reason=request.data.get('reason'),
                                      checklist=request.data.get('checklist'))
        except services.VerificationError as exc:
            return _error(exc)
        return Response(_attempt_for_admin(attempt))


class AdminReviewVerificationView(APIView):
    """
    PATCH /api/v1/verification/review/<user_id>/   {"decision": "approve" | "reject"}
    Older per-user endpoint: decides the user's attempt in review, or records
    a manual override if they have none. No checklist is required here, and a
    rejection without a reason is recorded as "other".
    """
    permission_classes = [IsAdmin]

    def patch(self, request, user_id):
        from django.shortcuts import get_object_or_404
        target = get_object_or_404(User, id=user_id)
        decision = request.data.get('decision')
        if decision not in ('approve', 'reject'):
            return Response({'detail': 'decision must be approve or reject.'},
                            status=status.HTTP_400_BAD_REQUEST)
        attempt = (target.verification_attempts.filter(status__in=Attempt.IN_REVIEW)
                   .order_by('-created_at').first())
        if attempt is None:
            attempt = Attempt.objects.create(user=target, method=Attempt.Method.MANUAL,
                                             status=Attempt.Status.PENDING,
                                             review_note='Admin override without submitted documents')
        try:
            services.review(attempt.id, request.user, decision,
                            request.data.get('note') or 'Decided by an admin.',
                            reason=request.data.get('reason') or 'other',
                            checklist=request.data.get('checklist'), require_checklist=False)
        except services.VerificationError as exc:
            return _error(exc)
        verb = 'approved' if decision == 'approve' else 'rejected'
        return Response({'detail': f'User verification {verb}.'})
