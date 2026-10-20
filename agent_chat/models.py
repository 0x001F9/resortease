import uuid

from django.conf import settings
from django.db import models


class AgentChatSession(models.Model):
    class Status(models.TextChoices):
        AI_ACTIVE = "ai_active", "AI active"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_chat_sessions",
    )
    anonymous_user_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AI_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_chat_sessions"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Chat {self.pk}"

    @property
    def last_message(self):
        message = self.messages.order_by("-created_at", "-pk").first()
        return message.body if message else ""

    @property
    def unread_count(self):
        return self.messages.filter(is_read=False).count()


class AgentChatMessage(models.Model):
    class SenderType(models.TextChoices):
        GUEST = "guest", "Guest"
        ASSISTANT = "assistant", "Assistant"

    chat = models.ForeignKey(
        AgentChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_chat_messages",
    )
    sender_type = models.CharField(max_length=20, choices=SenderType.choices)
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_chat_messages"
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_sender_type_display()}: {self.body[:50]}"

    @property
    def is_from_guest(self):
        return self.sender_type == self.SenderType.GUEST

    @property
    def sender_name(self):
        if self.user_id:
            return self.user.get_full_name() or self.user.username
        if self.sender_type == self.SenderType.ASSISTANT:
            return "AI assistant"
        return "Guest"