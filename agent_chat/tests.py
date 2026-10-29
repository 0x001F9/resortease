from django.test import SimpleTestCase
from langchain_core.messages import AIMessageChunk, ToolMessage

from agent_chat.agent import agent
from agent_chat.consumers import _assistant_text_from_chunk


class AssistantStreamFilteringTests(SimpleTestCase):
    def test_streams_assistant_text_only(self):
        assistant_chunk = AIMessageChunk(content="Here is a concise summary.")
        tool_chunk = ToolMessage(
            content="[agent_chat/rag/docs/resort.md]\nRaw document text",
            tool_call_id="search-1",
        )

        self.assertEqual(
            _assistant_text_from_chunk(assistant_chunk, {"langgraph_node": "model"}),
            "Here is a concise summary.",
        )
        self.assertEqual(
            _assistant_text_from_chunk(tool_chunk, {"langgraph_node": "tools"}),
            "",
        )
        self.assertEqual(
            _assistant_text_from_chunk(assistant_chunk, {"langgraph_node": "tools"}),
            "",
        )


def main():
    response = agent.invoke({
        "messages": [
            {
                "role": "user",
                "content": "Hello, who are you?"
            }
        ]
    },
        config={
            "debug": True,
            "configurable": {
                "thread_id": "manual-test-session",
                "debug_model": True,
            },
        },
    )

    print("==== Response ====")
    print(response["messages"][-1].content)


if __name__ == "__main__":
    main()
