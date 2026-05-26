"""Map-reduce with the Send API: process N items in parallel, aggregate.

Scenario: summarize a list of articles in parallel, then synthesize a meta-summary.

Demonstrates:
- Dynamic fan-out via Send (number of branches decided at runtime)
- Custom input state per Send (different shape from main State)
- List reducer (operator.add) to accumulate parallel outputs
- defer=True on the reducer node to wait for all branches

Run:
    pip install langchain langgraph langchain-anthropic
    export ANTHROPIC_API_KEY=...
    python map-reduce-send.py
"""
from __future__ import annotations

import asyncio
from operator import add
from typing import Annotated, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send


class State(TypedDict):
    articles: list[str]
    summaries: Annotated[list[str], add]    # parallel branches append here
    meta_summary: str


model = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)


def fan_out(state: State) -> list[Send]:
    """Emit one Send per article, each routing to 'summarize' with custom state."""
    return [
        Send("summarize", {"article": article, "index": i})
        for i, article in enumerate(state["articles"])
    ]


async def summarize(input: dict) -> dict:
    """Summarize one article. Input shape != main State."""
    response = await model.ainvoke([
        SystemMessage("Summarize in one sentence."),
        HumanMessage(input["article"]),
    ])
    return {"summaries": [f"[{input['index']}] {response.content}"]}


async def synthesize(state: State) -> dict:
    """Synthesize a meta-summary across all per-article summaries."""
    joined = "\n".join(state["summaries"])
    response = await model.ainvoke([
        SystemMessage("Synthesize these summaries into a single paragraph."),
        HumanMessage(joined),
    ])
    return {"meta_summary": response.content}


def build_graph():
    builder = StateGraph(State)
    builder.add_node("summarize", summarize)
    # defer=True ensures synthesize waits for ALL summarize Sends to complete
    builder.add_node("synthesize", synthesize, defer=True)

    builder.add_conditional_edges(START, fan_out, ["summarize"])
    builder.add_edge("summarize", "synthesize")
    builder.add_edge("synthesize", END)

    return builder.compile()


async def main():
    graph = build_graph()

    articles = [
        "Researchers found that quantum computers can factor large numbers exponentially faster than classical ones, using Shor's algorithm.",
        "The European Commission proposed new regulations on AI models, focusing on transparency and safety testing.",
        "Astronomers detected unusual radio signals from a galaxy 8 billion light-years away, potentially indicating exotic physics.",
        "A breakthrough in solid-state battery technology promises 2x energy density and faster charging for electric vehicles.",
    ]

    result = await graph.ainvoke({
        "articles": articles,
        "summaries": [],
        "meta_summary": "",
    })

    print("=== Per-article summaries ===")
    for s in sorted(result["summaries"]):  # sort to make output deterministic
        print(s)
    print("\n=== Meta-summary ===")
    print(result["meta_summary"])


if __name__ == "__main__":
    asyncio.run(main())
