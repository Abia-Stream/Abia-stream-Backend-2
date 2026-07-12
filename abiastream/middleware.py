from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from accounts.models import User


@database_sync_to_async
def get_user_from_token(token_key):
    try:
        token = AccessToken(token_key)
        user_id = token['user_id']
        return User.objects.get(id=user_id)
    except (TokenError, InvalidToken, User.DoesNotExist):
        return AnonymousUser()


class JwtAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        # Get token from query string: ws://...?token=<access_token>
        query_string = scope.get('query_string', b'').decode()
        token = None

        for param in query_string.split('&'):
            if param.startswith('token='):
                token = param.split('=')[1]
                break

        scope['user'] = await get_user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(inner)