"""Human-in-the-loop approval flow using interrupt() and Command(resume=...).

Scenario: an agent proposes an action, a human approves/rejects/edits, the agent applies
or terminates.

Demonstrates:
- interrupt() inside a node
- Command(resume=value) to continue
- The __interrupt__ key in result
- Proper ordering: interrupt() BEFORE any side effect (so resume doesn't re-fire it)
- Editing the proposal via resume payload

Run:
    pip install langchain langgraph
    python hitl-approval.py
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    proposal: str
    approved: bool
    applied: bool


def propose(state: State) -> dict:
    """Generate a proposal for action. In real life, an LLM call."""
    # Fake — pretend the agent decided to do this.
    proposal = "Delete inactive accounts older than 90 days (estimated: 1,247 accounts)"
    return {
        "proposal": proposal,
        "messages": [AIMessage(f"I propose: {proposal}")],
    }


def review(state: State) -> dict:
    """Pause for human approval. interrupt() is FIRST so resume doesn't repeat side effects."""
    decision = interrupt({
        "type": "approval_request",
        "proposal": state["proposal"],
        "options": ["accept", "reject", "edit"],
    })

    # interpret the resume payload
    if isinstance(decision, dict):
        action = decision.get("action")
        if action == "accept":
            return {"approved": True}
        if action == "edit":
            new_proposal = decision.get("proposal", state["proposal"])
            return {"approved": True, "proposal": new_proposal}
        # reject
        return {"approved": False}

    # plain string form
    if decision == "accept":
        return {"approved": True}
    return {"approved": False}


def apply(state: State) -> dict:
    """Execute the (approved) proposal."""
    if not state["approved"]:
        return {
            "applied": False,
            "messages": [AIMessage("Cancelled per your decision.")],
        }
    # Real side effect would go here, e.g. db.delete(...).
    return {
        "applied": True,
        "messages": [AIMessage(f"Done: {state['proposal']}")],
    }


def build_graph():
    builder = StateGraph(State)
    builder.add_node("propose", propose)
    builder.add_node("review", review)
    builder.add_node("apply", apply)

    builder.add_edge(START, "propose")
    builder.add_edge("propose", "review")
    builder.add_edge("review", "apply")
    builder.add_edge("apply", END)

    return builder.compile(checkpointer=InMemorySaver())


def demo_accept():
    print("=== Demo 1: user accepts ===")
    graph = build_graph()
    cfg = {"configurable": {"thread_id": "t-accept"}}

    result = graph.invoke(
        {"messages": [HumanMessage("clean up old accounts")],
         "proposal": "", "approved": False, "applied": False},
        config=cfg,
    )

    assert "__interrupt__" in result
    interrupt_payload = result["__interrupt__"][0].value
    print(f"  Agent proposes: {interrupt_payload['proposal']}")
    print(f"  (user accepts)")

    final = graph.invoke(Command(resume={"action": "accept"}), config=cfg)
    print(f"  Final: {final['messages'][-1].content}")
    print(f"  Applied: {final['applied']}")


def demo_edit():
    print("\n=== Demo 2: user edits and accepts ===")
    graph = build_graph()
    cfg = {"configurable": {"thread_id": "t-edit"}}

    result = graph.invoke(
        {"messages": [HumanMessage("clean up old accounts")],
         "proposal": "", "approved": False, "applied": False},
        config=cfg,
    )
    print(f"  Agent proposes: {result['__interrupt__'][0].value['proposal']}")
    print(f"  (user edits to a safer threshold)")

    edited = "Delete inactive accounts older than 180 days (much safer)"
    final = graph.invoke(
        Command(resume={"action": "edit", "proposal": edited}),
        config=cfg,
    )
    print(f"  Final: {final['messages'][-1].content}")


def demo_reject():
    print("\n=== Demo 3: user rejects ===")
    graph = build_graph()
    cfg = {"configurable": {"thread_id": "t-reject"}}

    graph.invoke(
        {"messages": [HumanMessage("clean up old accounts")],
         "proposal": "", "approved": False, "applied": False},
        config=cfg,
    )

    final = graph.invoke(Command(resume={"action": "reject"}), config=cfg)
    print(f"  Final: {final['messages'][-1].content}")
    print(f"  Applied: {final['applied']}")


if __name__ == "__main__":
    demo_accept()
    demo_edit()
    demo_reject()
