import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from abiastream.middleware import JwtAuthMiddlewareStack
import abiastream.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'abiastream.settings')

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AllowedHostsOriginValidator(
        JwtAuthMiddlewareStack(
            URLRouter(abiastream.routing.websocket_urlpatterns)
        )
    ),
})