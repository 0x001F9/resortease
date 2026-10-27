from django.urls import path
import agent_chat.views as views


urlpatterns = [
    path("", views.ChatView.as_view(), name="chat"),
]