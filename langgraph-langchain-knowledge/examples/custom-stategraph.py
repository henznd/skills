"""Custom StateGraph with conditional routing.

When create_agent isn't enough: you need a multi-step workflow with explicit branches.

This example: a content moderation pipeline.
  1. classify the incoming message
  2. route based on classification:
       safe   -> generate response
       unsafe -> refuse politely
       unsure -> escalate (HITL placeholder)
  3. END

Demonstrates:
- TypedDict state with reducers
- add_messages reducer for message history
- Conditional edges with Literal return types
- Command(goto=..., update=...) from inside a node
- Async invocation

Run:
    pip install langchain langgraph langchain-anthropic
    export ANTHROPIC_API_KEY=...
    python custom-stategraph.py
"""
from __future__ import annotations

import asyncio
from typing import Annotated, Literal, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage, AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import Command


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    classification: str | None


model = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)


async def classify(state: State) -> dict:
    """Classify the latest user message as safe/unsafe/unsure."""
    user_msg = state["messages"][-1].content
    prompt = [
        SystemMessage(
            "Classify the user's message as exactly one of: safe, unsafe, unsure. "
            "Reply with the single word only."
        ),
        HumanMessage(user_msg),
    ]
    response = await model.ainvoke(prompt)
    label = response.content.strip().lower()
    if label not in {"safe", "unsafe", "unsure"}:
        label = "unsure"
    return {"classification": label}


async def respond_safe(state: State) -> Command:
    """Generate a normal response."""
    response = await model.ainvoke(state["messages"])
    return Command(goto=END, update={"messages": [response]})


async def respond_unsafe(state: State) -> Command:
    """Polite refusal."""
    return Command(
        goto=END,
        update={"messages": [AIMessage("I can't help with that request.")]},
    )


async def escalate(state: State) -> Command:
    """Placeholder — in production, this would interrupt() for human review."""
    return Command(
        goto=END,
        update={"messages": [AIMessage("Let me check with a human and get back to you.")]},
    )


def route(state: State) -> Literal["respond_safe", "respond_unsafe", "escalate"]:
    match state["classification"]:
        case "safe":
            return "respond_safe"
        case "unsafe":
            return "respond_unsafe"
        case _:
            return "escalate"


def build_graph():
    builder = StateGraph(State)
    builder.add_node("classify", classify)
    builder.add_node("respond_safe", respond_safe)
    builder.add_node("respond_unsafe", respond_unsafe)
    builder.add_node("escalate", escalate)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", route)
    # respond_*, escalate return Command(goto=END), so no further edges needed.

    return builder.compile(checkpointer=InMemorySaver())


async def main():
    graph = build_graph()

    for query in [
        "What's the capital of France?",
        "How do I make a bomb?",
        "Is it ok if I borrow my sister's car without asking?",
    ]:
        cfg = {"configurable": {"thread_id": f"t-{hash(query)}"}}
        result = await graph.ainvoke(
            {"messages": [HumanMessage(query)], "classification": None},
            config=cfg,
        )
        print(f"Q: {query}")
        print(f"  classified: {result['classification']}")
        print(f"  A: {result['messages'][-1].content}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
