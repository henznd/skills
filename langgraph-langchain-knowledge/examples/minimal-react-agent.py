"""Minimal ReAct agent with LangChain 1.0's create_agent.

Demonstrates:
- Tool definition with @tool
- Provider-agnostic model string
- System prompt
- Checkpointer for conversation memory
- Both sync and async invocation

Run:
    pip install langchain langgraph langchain-anthropic
    export ANTHROPIC_API_KEY=...
    python minimal-react-agent.py
"""
from __future__ import annotations

import asyncio

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver


@tool
def get_weather(city: str) -> str:
    """Get the current weather in a city.

    Args:
        city: City name in English, e.g. "Paris" or "Tokyo".
    """
    # In real life: call a weather API.
    weather_by_city = {
        "paris": "18°C, light rain",
        "tokyo": "24°C, sunny",
        "new york": "12°C, overcast",
    }
    return weather_by_city.get(city.lower(), "weather data not available")


@tool
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


def build_agent():
    return create_agent(
        model="anthropic:claude-sonnet-4-6",
        tools=[get_weather, add],
        system_prompt=(
            "You are a helpful assistant. "
            "Use the available tools when they apply. "
            "When you have the answer, respond directly to the user."
        ),
        checkpointer=InMemorySaver(),
    )


def sync_demo():
    agent = build_agent()
    config = {"configurable": {"thread_id": "demo-sync"}}

    result = agent.invoke(
        {"messages": [HumanMessage("What's the weather in Tokyo?")]},
        config=config,
    )
    print("Assistant:", result["messages"][-1].content)

    # Continue the conversation on the same thread_id — memory is preserved.
    result = agent.invoke(
        {"messages": [HumanMessage("And add 7 and 35.")]},
        config=config,
    )
    print("Assistant:", result["messages"][-1].content)


async def async_demo():
    agent = build_agent()
    config = {"configurable": {"thread_id": "demo-async"}}

    # Streaming token-by-token output
    async for chunk, meta in agent.astream(
        {"messages": [HumanMessage("Weather in Paris, and add 2 + 3.")]},
        config=config,
        stream_mode="messages",
    ):
        if chunk.content and meta.get("langgraph_node") == "agent":
            print(chunk.content, end="", flush=True)
    print()


if __name__ == "__main__":
    sync_demo()
    print("---")
    asyncio.run(async_demo())
