from agent_chat.agent import agent, AgentContext


def main():
    response = agent.invoke({
        "messages": [
            {
                "role": "user",
                "content": "Hello, who are you?"
            }
        ]
    },
        context=AgentContext(session=1),
        config={
            "debug": True,
            "configurable": {"debug_model": True},
        },
    )

    print("==== Response ====")
    print(response["messages"][-1].content)


if __name__ == "__main__":
    main()
