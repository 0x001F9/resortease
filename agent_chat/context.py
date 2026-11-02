from dataclasses import dataclass

from django.contrib.sessions.backends.base import SessionBase


@dataclass
class AgentContext:
    user_id: int | None
    first_name: str
    session: SessionBase
    requires_auth_actions: bool = False
