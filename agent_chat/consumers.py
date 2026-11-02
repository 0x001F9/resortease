import asyncio
import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from langchain_core.messages import AIMessageChunk

from app.public_reservations import PENDING_RESERVATION_SESSION_KEY

from .agent import agent
from .context import AgentContext
from .functions.reservations import auth_action_urls
from .models import (
    CHAT_SESSION_ID_SESSION_KEY,
    ChatMessageModel,
    chat_session_seconds_until_expiry,
    expire_chat_session_if_idle,
    get_chat_session_history,
    get_or_create_active_chat_session,
    save_chat_message,
)


logger = logging.getLogger(__name__)


def _text_from_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
            if isinstance(block, str)
            or (isinstance(block, dict) and block.get("type") == "text")
        )
    return ""


def _assistant_text_from_chunk(chunk, metadata):
    if metadata.get("langgraph_node") != "model" or not isinstance(
        chunk, AIMessageChunk
    ):
        return ""
    return _text_from_content(chunk.content)


class AgentChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.expiration_task = None
        session = self.scope.get("session")
        session_key = session.session_key if session is not None else None
        if not session_key:
            await self.close(code=4401)
            return

        user = self.scope.get("user")
        user_id = user.pk if user is not None and user.is_authenticated else None
        self.chat_session, _ = await database_sync_to_async(
            get_or_create_active_chat_session, thread_sensitive=True
        )(
            session_key,
            user_id,
            session.get(CHAT_SESSION_ID_SESSION_KEY),
        )
        self.chat_session_id = self.chat_session.pk
        self.thread_id = str(self.chat_session.thread_id)
        self.user_id = user_id
        self.first_name = user.first_name if user_id is not None else "User"
        await self.accept()
        history = await database_sync_to_async(
            get_chat_session_history, thread_sensitive=True
        )(self.chat_session_id)
        history_event = {"type": "history", "messages": history}
        if user_id is None and PENDING_RESERVATION_SESSION_KEY in session:
            history_event["auth_actions"] = auth_action_urls()
        await self.send_json(
            history_event
        )
        self._restart_expiration_timer()

    def _restart_expiration_timer(self):
        if self.expiration_task is not None:
            self.expiration_task.cancel()
        self.expiration_task = asyncio.create_task(self._close_when_idle())

    async def _close_when_idle(self):
        while True:
            seconds_remaining = await database_sync_to_async(
                chat_session_seconds_until_expiry, thread_sensitive=True
            )(self.chat_session_id)
            if seconds_remaining > 0:
                await asyncio.sleep(seconds_remaining)
            expired = await database_sync_to_async(
                expire_chat_session_if_idle, thread_sensitive=True
            )(self.chat_session_id)
            if expired:
                await self.send_json(
                    {
                        "type": "session_expired",
                        "message": "Your chat was inactive for an hour. Starting a fresh chat.",
                    }
                )
                await self.close(code=4408)
                return

    async def receive_json(self, content, **kwargs):
        message = content.get("message") if isinstance(content, dict) else None
        if not isinstance(message, str) or not message.strip():
            await self.send_json({"type": "error", "message": "Enter a message first."})
            return
        if len(message) > 4000:
            await self.send_json(
                {"type": "error", "message": "Messages must be 4,000 characters or fewer."}
            )
            return

        message = message.strip()
        saved = await database_sync_to_async(save_chat_message, thread_sensitive=True)(
            self.chat_session_id,
            ChatMessageModel.Role.USER,
            message,
        )
        if not saved:
            await self.send_json(
                {
                    "type": "session_expired",
                    "message": "Your chat was inactive for an hour. Starting a fresh chat.",
                }
            )
            await self.close(code=4408)
            return
        self._restart_expiration_timer()

        started_at = time.perf_counter()
        first_token_at = None
        response_text = []
        context = AgentContext(
            user_id=self.user_id,
            first_name=self.first_name,
            session=self.scope["session"],
        )
        try:
            async for chunk, metadata in agent.astream(
                {"messages": [{"role": "user", "content": message}]},
                config={"configurable": {"thread_id": self.thread_id}},
                context=context,
                stream_mode="messages",
            ):
                text = _assistant_text_from_chunk(chunk, metadata)
                if text:
                    response_text.append(text)
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    await self.send_json({"type": "token", "content": text})
            if response_text:
                await database_sync_to_async(save_chat_message, thread_sensitive=True)(
                    self.chat_session_id,
                    ChatMessageModel.Role.ASSISTANT,
                    "".join(response_text),
                )
            if context.requires_auth_actions:
                await self.send_json(
                    {
                        "type": "auth_actions",
                        **auth_action_urls(),
                    }
                )
            await self.send_json({"type": "done"})
            elapsed = time.perf_counter() - started_at
            if first_token_at is None:
                logger.info("Chat reply completed in %.2fs without text tokens", elapsed)
            else:
                logger.info(
                    "Chat reply completed in %.2fs (first token in %.2fs)",
                    elapsed,
                    first_token_at - started_at,
                )
        except Exception:
            logger.exception("ResortEase chat agent failed for thread %s", self.thread_id)
            await self.send_json(
                {
                    "type": "error",
                    "message": "Sorry, I couldn't complete that response. Please refresh the page and try again.",
                }
            )

    async def disconnect(self, close_code):
        if self.expiration_task is not None:
            self.expiration_task.cancel()