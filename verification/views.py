from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.conf import settings

from verification.smile_service import (
    submit_kyc_verification,
    check_verification_status,
)
from videos.cloudinary_service import upload_image_to_cloudinary
from videos.file_security import validate_image_file
from accounts.models import User
import logging

logger = logging.getLogger(__name__)


class SubmitVerificationView(APIView):
    """
    Submit ID verification to Smile Identity.

    POST /api/v1/verification/submit/
    Content-Type: multipart/form-data

    Fields:
      id_document  → File → front of ID card/passport/driver's license
      selfie       → File → user's selfie photo
      id_type      → Text → NATIONAL_ID | DRIVERS_LICENSE | PASSPORT | VOTERS_ID
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # Checked before anything is uploaded: without keys the Smile call
        # would fail after the ID document had already been stored.
        if not (settings.SMILE_IDENTITY_PARTNER_ID and settings.SMILE_IDENTITY_API_KEY):
            logger.error('Smile Identity is not configured (SMILE_IDENTITY_PARTNER_ID / '
                         'SMILE_IDENTITY_API_KEY missing)')
            return Response(
                {'detail': 'Identity verification is temporarily unavailable. Please try again later.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        # Already verified
        if user.verification_status == User.VerificationStatus.APPROVED:
            return Response(
                {'detail': 'Your identity is already verified.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Already pending
        if user.verification_status == User.VerificationStatus.PENDING:
            return Response(
                {'detail': 'Your verification is pending review.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get files
        id_document = request.FILES.get('id_document')
        selfie = request.FILES.get('selfie')
        id_type = request.data.get('id_type', 'NATIONAL_ID')

        if not id_document:
            return Response(
                {'detail': 'id_document is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not selfie:
            return Response(
                {'detail': 'selfie is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate id_type
        valid_id_types = ['NATIONAL_ID', 'DRIVERS_LICENSE', 'PASSPORT', 'VOTERS_ID']
        if id_type not in valid_id_types:
            return Response(
                {'detail': f'Invalid id_type. Choose from: {valid_id_types}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Security checks on files
        try:
            validate_image_file(id_document)
            validate_image_file(selfie)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Upload ID document to Cloudinary for records
        try:
            id_result = upload_image_to_cloudinary(
                id_document,
                folder='abia_stream/verification_docs'
            )
            id_document_url = id_result['secure_url']
        except Exception as e:
            return Response(
                {'detail': f'Document upload failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Reset file pointers after Cloudinary upload
        id_document.seek(0)
        selfie.seek(0)

        # Submit to Smile Identity
        result, job_id = submit_kyc_verification(
            user=user,
            id_image_file=id_document,
            selfie_image_file=selfie,
            id_type=id_type
        )

        if 'error' in result:
            return Response(
                {'detail': f'Verification submission failed: {result["error"]}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Check immediate result from Smile Identity
        job_result = result.get('result', {})
        result_code = job_result.get('ResultCode', '')
        result_text = job_result.get('ResultText', '')

        # Smile Identity result codes:
        # 0810 = Exact Match (verified)
        # 0811 = Partial Match
        # 0812 = No Match (failed)

        if result_code in ['0810', '0811']:
            # Verified immediately
            user.verification_status = User.VerificationStatus.APPROVED
            user.verification_job_id = job_id
            user.id_document_url = id_document_url
            user.verified_at = timezone.now()
            user.save(update_fields=[
                'verification_status', 'verification_job_id',
                'id_document_url', 'verified_at'
            ])

            return Response({
                'detail': 'Identity verified successfully. You can now create a channel.',
                'verification_status': 'approved',
                'result_text': result_text,
            }, status=status.HTTP_200_OK)

        elif result_code == '0812':
            # Failed
            user.verification_status = User.VerificationStatus.REJECTED
            user.verification_job_id = job_id
            user.save(update_fields=['verification_status', 'verification_job_id'])

            return Response({
                'detail': 'Identity verification failed. Please try again with a clearer image.',
                'verification_status': 'rejected',
                'result_text': result_text,
            }, status=status.HTTP_400_BAD_REQUEST)

        else:
            # Pending — manual review needed
            user.verification_status = User.VerificationStatus.PENDING
            user.verification_job_id = job_id
            user.id_document_url = id_document_url
            user.save(update_fields=[
                'verification_status', 'verification_job_id', 'id_document_url'
            ])

            return Response({
                'detail': 'Verification submitted. Under review — you will be notified once approved.',
                'verification_status': 'pending',
            }, status=status.HTTP_202_ACCEPTED)


class VerificationStatusView(APIView):
    """
    Check the authenticated user's verification status.

    GET /api/v1/verification/status/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            'verification_status': user.verification_status,
            'verified_at': user.verified_at,
            'can_create_channel': user.verification_status == User.VerificationStatus.APPROVED,
        })


class CheckVerificationJobView(APIView):
    """
    Check status of a pending verification job.
    Called when user wants to check if their pending verification was approved.

    GET /api/v1/verification/check/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.verification_job_id:
            return Response(
                {'detail': 'No verification job found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        if user.verification_status == User.VerificationStatus.APPROVED:
            return Response({
                'verification_status': 'approved',
                'verified_at': user.verified_at,
                'can_create_channel': True,
            })

        # Check with Smile Identity
        result = check_verification_status(
            job_id=user.verification_job_id,
            user_id=user.id
        )

        job_result = result.get('result', {})
        result_code = job_result.get('ResultCode', '')

        if result_code in ['0810', '0811']:
            user.verification_status = User.VerificationStatus.APPROVED
            user.verified_at = timezone.now()
            user.save(update_fields=['verification_status', 'verified_at'])

            return Response({
                'verification_status': 'approved',
                'verified_at': user.verified_at,
                'can_create_channel': True,
            })

        return Response({
            'verification_status': user.verification_status,
            'can_create_channel': False,
        })


class AdminReviewVerificationView(APIView):
    """
    Admin endpoint to manually approve or reject a pending verification.

    PATCH /api/v1/verification/review/<user_id>/
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, user_id):
        if request.user.role != 'admin':
            return Response(
                {'detail': 'Admin access required.'},
                status=status.HTTP_403_FORBIDDEN
            )

        from django.shortcuts import get_object_or_404
        target_user = get_object_or_404(User, id=user_id)

        decision = request.data.get('decision')  # 'approve' or 'reject'
        if decision not in ['approve', 'reject']:
            return Response(
                {'detail': 'decision must be approve or reject.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if decision == 'approve':
            target_user.verification_status = User.VerificationStatus.APPROVED
            target_user.verified_at = timezone.now()
            target_user.save(update_fields=['verification_status', 'verified_at'])

            # Notify user
            from notifications.utils import create_notification
            create_notification(
                user=target_user,
                notification_type='verification_approved',
                title='Identity Verified',
                message='Your identity has been verified. You can now create a channel.',
                data={}
            )

            return Response({'detail': 'User verification approved.'})

        else:
            target_user.verification_status = User.VerificationStatus.REJECTED
            target_user.save(update_fields=['verification_status'])

            from notifications.utils import create_notification
            create_notification(
                user=target_user,
                notification_type='verification_rejected',
                title='Verification Failed',
                message='Your identity verification was rejected. Please resubmit with clearer images.',
                data={}
            )

            return Response({'detail': 'User verification rejected.'})