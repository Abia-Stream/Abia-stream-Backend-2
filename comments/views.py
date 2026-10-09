from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.db.models import F

from accounts.display import display_name
from comments.models import Comment, CommentLike
from comments.serializers import (
    CommentSerializer, ReplySerializer, CreateCommentSerializer
)
from videos.models import Video
from abiastream.pagination import StandardPagination


class VideoCommentsView(APIView):
    """
    GET  /api/v1/videos/<video_id>/comments/  — list comments
    POST /api/v1/videos/<video_id>/comments/  — add comment
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request, video_id):
        """List top-level comments for a video."""
        get_object_or_404(Video, id=video_id)

        comments = Comment.objects.filter(
            video_id=video_id,
            parent__isnull=True,  # top-level only
            is_deleted=False,
        ).select_related('user', 'user__profile').prefetch_related(
            'replies', 'likes'
        ).order_by('-created_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(comments, request)
        serializer = CommentSerializer(
            page, many=True, context={'request': request}
        )
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, video_id):
        """Add a comment or reply to a video."""
        video = get_object_or_404(Video, id=video_id)

        serializer = CreateCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        content = serializer.validated_data['content']
        parent_id = serializer.validated_data.get('parent_id')
        parent = None

        if parent_id:
            parent = get_object_or_404(
                Comment, id=parent_id, video_id=video_id, is_deleted=False
            )

        comment = Comment.objects.create(
            video=video,
            user=request.user,
            parent=parent,
            content=content,
        )

        # Spam links / phone numbers / banned terms go to the moderation queue.
        from moderation.auto import check_comment
        check_comment(comment)

        # Increment replies_count on parent
        if parent:
            Comment.objects.filter(id=parent.id).update(
                replies_count=F('replies_count') + 1
            )

        # ── Notifications ─────────────────────────────────────────────────
        from notifications.utils import create_notification

        if parent:
            # Notify the person being replied to (if not replying to yourself)
            if parent.user != request.user:
                create_notification(
                    user=parent.user,
                    notification_type='comment_reply',
                    title='New Reply',
                    message=f'{display_name(request.user)} replied to your comment.',
                    data={
                        'video_id': str(video_id),
                        'comment_id': str(comment.id),
                        'parent_id': str(parent.id),
                    }
                )
        else:
            # Notify video creator (if not commenting on own video)
            if video.creator != request.user:
                create_notification(
                    user=video.creator,
                    notification_type='new_comment',
                    title='New Comment',
                    message=f'{display_name(request.user)} commented on your video "{video.title}".',
                    data={
                        'video_id': str(video_id),
                        'comment_id': str(comment.id),
                        'video_title': video.title,
                    }
                )

        return Response(
            CommentSerializer(comment, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )


class CommentRepliesView(APIView):
    """
    GET /api/v1/comments/<comment_id>/replies/
    Load all replies for a comment (paginated).
    """
    permission_classes = [AllowAny]

    def get(self, request, comment_id):
        comment = get_object_or_404(Comment, id=comment_id, is_deleted=False)

        replies = Comment.objects.filter(
            parent=comment,
            is_deleted=False,
        ).select_related('user', 'user__profile').prefetch_related(
            'likes'
        ).order_by('created_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(replies, request)
        serializer = ReplySerializer(
            page, many=True, context={'request': request}
        )
        return paginator.get_paginated_response(serializer.data)


class CommentDetailView(APIView):
    """
    PATCH  /api/v1/comments/<comment_id>/  — edit comment
    DELETE /api/v1/comments/<comment_id>/  — delete comment
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, comment_id):
        comment = get_object_or_404(
            Comment, id=comment_id, user=request.user, is_deleted=False
        )

        content = request.data.get('content', '').strip()
        if not content:
            return Response(
                {'detail': 'Content is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(content) > 2000:
            return Response(
                {'detail': 'Comment cannot exceed 2000 characters.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        comment.content = content
        comment.is_edited = True
        comment.save(update_fields=['content', 'is_edited', 'updated_at'])

        return Response(
            CommentSerializer(comment, context={'request': request}).data
        )

    def delete(self, request, comment_id):
        comment = get_object_or_404(
            Comment, id=comment_id, is_deleted=False
        )

        # Only comment owner or video creator or admin can delete
        if (comment.user != request.user and
                comment.video.creator != request.user and
                request.user.role != 'admin'):
            return Response(
                {'detail': 'You cannot delete this comment.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Soft delete — keep record but hide content
        comment.content = '[deleted]'
        comment.is_deleted = True
        comment.save(update_fields=['content', 'is_deleted'])

        # Decrement parent replies_count
        if comment.parent:
            Comment.objects.filter(id=comment.parent_id).update(
                replies_count=F('replies_count') - 1
            )

        return Response({'detail': 'Comment deleted.'})


class LikeCommentView(APIView):
    """
    POST /api/v1/comments/<comment_id>/like/
    Toggle like on a comment.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, comment_id):
        comment = get_object_or_404(Comment, id=comment_id, is_deleted=False)

        existing = CommentLike.objects.filter(
            comment=comment,
            user=request.user
        ).first()

        if existing:
            existing.delete()
            Comment.objects.filter(id=comment_id).update(
                likes_count=F('likes_count') - 1
            )
            return Response({
                'detail': 'Like removed.',
                'action': 'unliked',
                'likes_count': max(0, comment.likes_count - 1),
            })
        else:
            CommentLike.objects.create(comment=comment, user=request.user)
            Comment.objects.filter(id=comment_id).update(
                likes_count=F('likes_count') + 1
            )

            # Notify comment owner
            if comment.user != request.user:
                from notifications.utils import create_notification
                create_notification(
                    user=comment.user,
                    notification_type='comment_like',
                    title='Comment Liked',
                    message=f'{display_name(request.user)} liked your comment.',
                    data={
                        'comment_id': str(comment_id),
                        'video_id': str(comment.video_id),
                    }
                )

            return Response({
                'detail': 'Comment liked.',
                'action': 'liked',
                'likes_count': comment.likes_count + 1,
            }, status=status.HTTP_201_CREATED)


class MyCommentsView(APIView):
    """
    GET /api/v1/comments/me/
    Get authenticated user's comments.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        comments = Comment.objects.filter(
            user=request.user,
            is_deleted=False,
        ).select_related('video').order_by('-created_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(comments, request)
        serializer = CommentSerializer(
            page, many=True, context={'request': request}
        )
        return paginator.get_paginated_response(serializer.data)