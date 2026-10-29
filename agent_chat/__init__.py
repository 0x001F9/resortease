from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import AIMessage
from langgraph.config import get_config


class DebugModelMiddleware(AgentMiddleware):
    def wrap_model_call(self, request: ModelRequest, handler):
        debug_model = get_config().get("configurable", {}).get("debug_model", False)
        if not debug_model:
            return handler(request)

        return AIMessage(content="[DEBUG: LLM call skipped]")
