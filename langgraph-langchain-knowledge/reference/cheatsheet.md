# Cheatsheet — One-Page Reference

## Imports you'll write most often

```python
# State / graph
from typing import Annotated, TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt, Send

# Checkpointers
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.postgres import PostgresSaver

# Messages
from langchain_core.messages import (
    AnyMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
)

# Tools
from langchain_core.tools import tool, BaseTool, InjectedState

# Agent
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware, SummarizationMiddleware
)

# Models (pick the one you use)
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

# MCP
from fastmcp import FastMCP
from langchain_mcp_adapters.client import MultiServerMCPClient
```

## Minimal State

```python
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
```

## Minimal StateGraph

```python
builder = StateGraph(State)
builder.add_node("agent", agent_node)
builder.add_node("tools", tool_node)
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", route, {"tools": "tools", "end": END})
builder.add_edge("tools", "agent")
graph = builder.compile(checkpointer=InMemorySaver())
```

## Minimal `create_agent`

```python
agent = create_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[my_tool],                       # REQUIRED, even if []
    system_prompt="You are helpful.",
    checkpointer=InMemorySaver(),          # optional, needed for HITL
)
result = agent.invoke(
    {"messages": [HumanMessage("hi")]},
    config={"configurable": {"thread_id": "abc"}},
)
```

## Tool

```python
@tool
def search(query: str, top_k: int = 5) -> list[str]:
    """Search the knowledge base. Returns up to top_k matches.

    Args:
        query: Specific natural-language query.
        top_k: Number of results (max 20).
    """
    return _do_search(query, top_k)
```

## Invoke with thread_id (always pass it when checkpointer is set)

```python
config = {"configurable": {"thread_id": "user-42-session-1"}}
result = graph.invoke({"messages": [...]}, config=config)
```

## HITL with `interrupt`

```python
def approval_node(state):
    decision = interrupt({"question": "approve?", "details": state["pending"]})
    if decision == "yes":
        return {"approved": True}
    return Command(goto=END, update={"approved": False})

# Resume:
graph.invoke(Command(resume="yes"), config=config)
```

## Parallel fan-out with `Send`

```python
def fan_out(state) -> list[Send]:
    return [Send("worker", {"item": x}) for x in state["items"]]

builder.add_conditional_edges("router", fan_out, ["worker"])
```

## Async graph + streaming

```python
async for event in graph.astream(
    state,
    config={"configurable": {"thread_id": "t1"}},
    stream_mode="updates",
):
    print(event)
```

## FastMCP minimum server

```python
from fastmcp import FastMCP

mcp = FastMCP("my-server", instructions="What this exposes")

@mcp.tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

if __name__ == "__main__":
    mcp.run()                                  # stdio
    # mcp.run(transport="streamable-http", port=8000)  # HTTP
```

## Agent consuming MCP servers

```python
client = MultiServerMCPClient({
    "weather": {"url": "http://localhost:8000/mcp", "transport": "streamable_http"},
})
tools = await client.get_tools()
agent = create_agent(model="anthropic:claude-sonnet-4-6", tools=tools)
```

## Stream modes (quick reference)

| Mode | Yields | When |
|---|---|---|
| `"values"` | Full state after each step | Debug / full re-render |
| `"updates"` | Delta per node | Standard UI streaming |
| `"messages"` | LLM tokens | Token-level UI |
| `"custom"` | `dispatch_custom_event` payloads | Progress reporting |

## Common errors → fix

| Error | Fix |
|---|---|
| `GraphRecursionError` | Add stop condition or raise `recursion_limit` |
| `ValueError: ... not a valid destination` | Router returns key not in mapping; add fallback |
| Messages getting overwritten | Missing `add_messages` reducer |
| State lost between calls | Missing `thread_id` in config |
| `__interrupt__` shows up in result, code doesn't handle it | Detect key, call `Command(resume=...)` |

## Hard rules

1. **Never** mutate `state` in a node — return a dict of updates.
2. **Always** pass `thread_id` in config when a checkpointer is set.
3. **Tools** parameter is required on `create_agent` (even if `[]`).
4. **Use `Async*Saver`** with async graphs to avoid blocking the event loop.
5. **No user-controlled text** in the system role of any prompt.
