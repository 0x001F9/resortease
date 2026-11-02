import hashlib
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import timedelta
from typing import Any
from uuid import uuid4

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import models
from django.db import transaction
from django.utils import timezone
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    CheckpointTuple,
    WRITES_IDX_MAP,
    get_checkpoint_metadata,
)


CHAT_SESSION_IDLE_TIMEOUT = timedelta(hours=1)
CHAT_SESSION_ID_SESSION_KEY = "agent_chat_session_id"


class ChatSessionModel(models.Model):
    browser_session_key = models.CharField(max_length=40, db_index=True)
    thread_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_chat_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "agent_chat_session"
        indexes = [models.Index(fields=["browser_session_key", "is_active"])]


class ChatMessageModel(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    session = models.ForeignKey(
        ChatSessionModel,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_chat_message"
        ordering = ["id"]
        indexes = [models.Index(fields=["session", "id"])]


def get_or_create_active_chat_session(
    browser_session_key: str,
    user_id: Any = None,
    preserved_session_id: int | None = None,
):
    now = timezone.now()
    with transaction.atomic():
        chat_session = (
            ChatSessionModel.objects.select_for_update()
            .filter(browser_session_key=browser_session_key, is_active=True)
            .order_by("-created_at")
            .first()
        )

        if chat_session is None and preserved_session_id is not None:
            preserved_session = (
                ChatSessionModel.objects.select_for_update()
                .filter(pk=preserved_session_id, is_active=True)
                .first()
            )
            if preserved_session is not None:
                is_expired = (
                    preserved_session.last_message_at
                    <= now - CHAT_SESSION_IDLE_TIMEOUT
                )
                belongs_to_another_user = (
                    preserved_session.user_id not in (None, user_id)
                )
                if is_expired:
                    preserved_session.is_active = False
                    preserved_session.save(update_fields=["is_active"])
                elif not belongs_to_another_user:
                    preserved_session.browser_session_key = browser_session_key
                    if user_id is not None and preserved_session.user_id is None:
                        preserved_session.user_id = user_id
                        preserved_session.save(
                            update_fields=["browser_session_key", "user"]
                        )
                    else:
                        preserved_session.save(update_fields=["browser_session_key"])
                    return preserved_session, False

        if chat_session is not None:
            is_expired = chat_session.last_message_at <= now - CHAT_SESSION_IDLE_TIMEOUT
            belongs_to_another_user = chat_session.user_id not in (None, user_id)
            belongs_to_anonymous_session = user_id is None and chat_session.user_id is not None
            if is_expired or belongs_to_another_user or belongs_to_anonymous_session:
                chat_session.is_active = False
                chat_session.save(update_fields=["is_active"])
                chat_session = None

        if chat_session is not None:
            if user_id is not None and chat_session.user_id is None:
                chat_session.user_id = user_id
                chat_session.save(update_fields=["user"])
            return chat_session, False

        return ChatSessionModel.objects.create(
            browser_session_key=browser_session_key,
            user_id=user_id,
        ), True


def save_chat_message(session_id: int, role: str, content: str) -> bool:
    now = timezone.now()
    with transaction.atomic():
        chat_session = ChatSessionModel.objects.select_for_update().get(pk=session_id)
        if not chat_session.is_active:
            return False
        if chat_session.last_message_at <= now - CHAT_SESSION_IDLE_TIMEOUT:
            chat_session.is_active = False
            chat_session.save(update_fields=["is_active"])
            return False

        ChatMessageModel.objects.create(
            session=chat_session,
            role=role,
            content=content,
        )
        if role == ChatMessageModel.Role.USER:
            chat_session.last_message_at = now
            chat_session.save(update_fields=["last_message_at"])
        return True


def get_chat_session_history(session_id: int) -> list[dict[str, str]]:
    return list(
        ChatMessageModel.objects.filter(session_id=session_id)
        .order_by("id")
        .values("role", "content")
    )


def chat_session_seconds_until_expiry(session_id: int) -> float:
    chat_session = ChatSessionModel.objects.only("last_message_at").get(pk=session_id)
    deadline = chat_session.last_message_at + CHAT_SESSION_IDLE_TIMEOUT
    return max(0.0, (deadline - timezone.now()).total_seconds())


def expire_chat_session_if_idle(session_id: int) -> bool:
    now = timezone.now()
    with transaction.atomic():
        chat_session = ChatSessionModel.objects.select_for_update().get(pk=session_id)
        if not chat_session.is_active:
            return True
        if chat_session.last_message_at <= now - CHAT_SESSION_IDLE_TIMEOUT:
            chat_session.is_active = False
            chat_session.save(update_fields=["is_active"])
            return True
        return False


class AgentCheckpointModel(models.Model):
    checkpoint_key = models.CharField(max_length=64, unique=True)
    thread_id = models.CharField(max_length=255, db_index=True)
    checkpoint_ns = models.CharField(max_length=255, blank=True, default="")
    checkpoint_id = models.CharField(max_length=255)
    parent_checkpoint_id = models.CharField(max_length=255, null=True, blank=True)
    checkpoint_type = models.CharField(max_length=100)
    checkpoint_data = models.BinaryField()
    metadata_type = models.CharField(max_length=100)
    metadata_data = models.BinaryField()

    class Meta:
        db_table = "agent_chat_checkpoint"
        indexes = [models.Index(fields=["thread_id", "checkpoint_ns"])]


class AgentCheckpointWriteModel(models.Model):
    write_key = models.CharField(max_length=64, unique=True)
    thread_id = models.CharField(max_length=255, db_index=True)
    checkpoint_ns = models.CharField(max_length=255, blank=True, default="")
    checkpoint_id = models.CharField(max_length=255)
    task_id = models.CharField(max_length=255)
    task_path = models.TextField(blank=True, default="")
    idx = models.IntegerField()
    channel = models.CharField(max_length=255)
    value_type = models.CharField(max_length=100)
    value_data = models.BinaryField()

    class Meta:
        db_table = "agent_chat_checkpoint_write"
        indexes = [
            models.Index(fields=["thread_id", "checkpoint_ns", "checkpoint_id"]),
            models.Index(fields=["task_id", "idx"]),
        ]


def _storage_key(*parts: str | int) -> str:
    serialized_parts = json.dumps(parts, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized_parts.encode("utf-8")).hexdigest()


class DjangoCheckpointSaver(BaseCheckpointSaver):
    def _configurable(self, config: dict[str, Any]) -> dict[str, Any]:
        configurable = config["configurable"]
        if "thread_id" not in configurable:
            raise ValueError("Checkpoint config requires configurable.thread_id")
        return configurable

    def _checkpoint_queryset(self, thread_id: str, checkpoint_ns: str):
        return AgentCheckpointModel.objects.filter(
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
        )

    def _to_tuple(self, record: AgentCheckpointModel) -> CheckpointTuple:
        configurable = {
            "thread_id": record.thread_id,
            "checkpoint_ns": record.checkpoint_ns,
            "checkpoint_id": record.checkpoint_id,
        }
        parent_config = None
        if record.parent_checkpoint_id is not None:
            parent_config = {
                "configurable": {
                    "thread_id": record.thread_id,
                    "checkpoint_ns": record.checkpoint_ns,
                    "checkpoint_id": record.parent_checkpoint_id,
                }
            }

        pending_writes = [
            (
                write.task_id,
                write.channel,
                self.serde.loads_typed((write.value_type, bytes(write.value_data))),
            )
            for write in AgentCheckpointWriteModel.objects.filter(
                thread_id=record.thread_id,
                checkpoint_ns=record.checkpoint_ns,
                checkpoint_id=record.checkpoint_id,
            ).order_by("task_id", "idx")
        ]

        return CheckpointTuple(
            config={"configurable": configurable},
            checkpoint=self.serde.loads_typed(
                (record.checkpoint_type, bytes(record.checkpoint_data))
            ),
            metadata=self.serde.loads_typed(
                (record.metadata_type, bytes(record.metadata_data))
            ),
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        configurable = self._configurable(config)
        checkpoints = self._checkpoint_queryset(
            configurable["thread_id"], configurable.get("checkpoint_ns", "")
        )
        checkpoint_id = configurable.get("checkpoint_id")
        if checkpoint_id is not None:
            checkpoints = checkpoints.filter(checkpoint_id=checkpoint_id)
        record = checkpoints.order_by("-checkpoint_id").first()
        return self._to_tuple(record) if record is not None else None

    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        return await sync_to_async(self.get_tuple, thread_sensitive=True)(config)

    def list(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        checkpoints = AgentCheckpointModel.objects.all()
        if config is not None:
            configurable = self._configurable(config)
            checkpoints = self._checkpoint_queryset(
                configurable["thread_id"], configurable.get("checkpoint_ns", "")
            )
        if before is not None:
            before_configurable = self._configurable(before)
            checkpoints = checkpoints.filter(
                checkpoint_id__lt=before_configurable["checkpoint_id"]
            )

        yielded = 0
        for record in checkpoints.order_by("-checkpoint_id").iterator():
            checkpoint_tuple = self._to_tuple(record)
            if filter and any(
                checkpoint_tuple.metadata.get(key) != value
                for key, value in filter.items()
            ):
                continue
            yield checkpoint_tuple
            yielded += 1
            if limit is not None and yielded >= limit:
                break

    async def alist(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        checkpoints = await sync_to_async(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit)),
            thread_sensitive=True,
        )()
        for checkpoint in checkpoints:
            yield checkpoint

    def put(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, Any],
    ) -> dict[str, Any]:
        configurable = self._configurable(config)
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        checkpoint_type, checkpoint_data = self.serde.dumps_typed(checkpoint)
        checkpoint_metadata = get_checkpoint_metadata(config, metadata)
        metadata_type, metadata_data = self.serde.dumps_typed(checkpoint_metadata)

        AgentCheckpointModel.objects.update_or_create(
            checkpoint_key=_storage_key(thread_id, checkpoint_ns, checkpoint_id),
            defaults={
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "parent_checkpoint_id": configurable.get("checkpoint_id"),
                "checkpoint_type": checkpoint_type,
                "checkpoint_data": checkpoint_data,
                "metadata_type": metadata_type,
                "metadata_data": metadata_data,
            },
        )
        return {
            "configurable": {
                **configurable,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, Any],
    ) -> dict[str, Any]:
        return await sync_to_async(self.put, thread_sensitive=True)(
            config, checkpoint, metadata, new_versions
        )

    def put_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = self._configurable(config)
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable["checkpoint_id"]

        for index, (channel, value) in enumerate(writes):
            write_index = WRITES_IDX_MAP.get(channel, index)
            value_type, value_data = self.serde.dumps_typed(value)
            AgentCheckpointWriteModel.objects.update_or_create(
                write_key=_storage_key(
                    thread_id, checkpoint_ns, checkpoint_id, task_id, write_index
                ),
                defaults={
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "task_id": task_id,
                    "task_path": task_path,
                    "idx": write_index,
                    "channel": channel,
                    "value_type": value_type,
                    "value_data": value_data,
                },
            )

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await sync_to_async(self.put_writes, thread_sensitive=True)(
            config, writes, task_id, task_path
        )

    def delete_thread(self, thread_id: str) -> None:
        AgentCheckpointWriteModel.objects.filter(thread_id=thread_id).delete()
        AgentCheckpointModel.objects.filter(thread_id=thread_id).delete()

    async def adelete_thread(self, thread_id: str) -> None:
        await sync_to_async(self.delete_thread, thread_sensitive=True)(thread_id)