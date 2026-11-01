from django.urls import path

from .consumers import AgentChatConsumer


websocket_urlpatterns = [
    path("ws/chat/", AgentChatConsumer.as_asgi()),
]