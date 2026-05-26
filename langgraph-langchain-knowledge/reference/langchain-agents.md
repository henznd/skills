# LangChain Agents — `create_agent` & Middleware

> LangChain 1.0's high-level agent API. Built on top of LangGraph; the returned object IS a
> compiled graph and can be dropped into a `StateGraph` as a node.

---

## 1. The signature

```python
from langchain.agents import create_agent

agent = create_agent(
    model: str | BaseChatModel,
    tools: list[BaseTool | Callable],         # REQUIRED — can be empty
    system_prompt: str | None = None,
    middleware: list[AgentMiddleware] = [],
    response_format: type[BaseModel] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    interrupt_before: list[str] = [],         # debug only
    interrupt_after: list[str] = [],          # debug only
    debug: bool = False,
)
```

---

## 2. Model parameter

Three forms:

### String identifier (recommended for most cases)

```python
agent = create_agent(model="anthropic:claude-sonnet-4-6", tools=[...])
agent = create_agent(model="openai:gpt-4o", tools=[...])
agent = create_agent(model="google_genai:gemini-2.0-flash", tools=[...])
```

LangChain resolves this via `init_chat_model`. Requires the corresponding `langchain-X`
package installed.

### Pre-built model instance

```python
from langchain_anthropic import ChatAnthropic

model = ChatAnthropic(
    model="claude-sonnet-4-6",
    temperature=0,
    max_tokens=2048,
)
agent = create_agent(model=model, tools=[...])
```

Use this when you need provider-specific config (temperature, custom params).

---

## 3. Tools

```python
from langchain_core.tools import tool

@tool
def search(query: str) -> str:
    """Search the index for a query."""
    return _do_search(query)

agent = create_agent(model="...", tools=[search])
```

- Function name → tool name (`search`).
- Docstring → tool description (sent to the LLM).
- Type hints → schema.
- Return value → text or structured payload sent back to the LLM.

For tools needing identity or state, see [`tools.md`](tools.md) for `InjectedState` /
`InjectedToolArg`.

---

## 4. `system_prompt`

```python
agent = create_agent(
    model="...",
    tools=[...],
    system_prompt="You are a customer support bot. Always be concise. "
                  "Use tools rather than guessing.",
)
```

Static string. For dynamic system prompts (varying with state), use middleware (see §6).

---

## 5. `response_format`

For agents that should produce structured output as their final answer:

```python
from pydantic import BaseModel

class Summary(BaseModel):
    headline: str
    bullets: list[str]
    confidence: float

agent = create_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[search],
    response_format=Summary,
)

result = agent.invoke({"messages": [HumanMessage("summarize Q3 sales")]})
parsed = result["structured_response"]   # Summary instance
print(parsed.headline)
```

Mechanics: after the model decides to stop calling tools, LangChain prompts it once more to
produce output matching the schema (provider-native structured output where available).

---

## 6. Middleware

Middleware classes implement hooks that run at well-defined points in the agent loop.

### Built-in middleware

```python
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    SummarizationMiddleware,
)

agent = create_agent(
    model="...",
    tools=[send_email, read_email],
    middleware=[
        HumanInTheLoopMiddleware(interrupt_on={"send_email": True}),
        SummarizationMiddleware(max_tokens=8000),
    ],
    checkpointer=InMemorySaver(),   # required for HITL
)
```

Order matters — outer wraps inner. Above, HITL wraps summarization: a paused tool resumes
into a summarized history.

### Provider-specific middleware

Some providers (Anthropic prompt caching, OpenAI Apps SDK metadata) have dedicated
middleware. Check provider docs / `langchain_anthropic.middleware`,
`langchain_openai.middleware`.

### Custom middleware

```python
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

class DynamicSystemPromptMiddleware(AgentMiddleware):
    async def before_model(self, state, runtime):
        user = state.get("user_name", "friend")
        # Inject a dynamic system message at the start of messages
        sys_msg = SystemMessage(f"You are helping {user}. Be warm.")
        return {"messages": [sys_msg, *state["messages"]]}
```

Hooks available:
- `before_model(state, runtime)` — before each LLM call.
- `after_model(state, runtime)` — after each LLM response, before tool dispatch.
- `before_tool(state, runtime)` — before each tool call.
- `after_tool(state, runtime)` — after each tool result.

All hooks can be sync or async. Return a dict of state updates, or `None` for no change.

### Decorator form (1.0+)

```python
from langchain.agents.middleware import before_model

@before_model
async def trim_history(state, runtime):
    if len(state["messages"]) > 20:
        return {"messages": state["messages"][-20:]}
```

---

## 7. The agent state

The state schema of a `create_agent` result includes at minimum `messages`. Custom keys
must be declared via `state_schema`:

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage

class MyAgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    authenticated_user_id: str
    intent: str | None

agent = create_agent(
    model="...",
    tools=[...],
    state_schema=MyAgentState,
)
```

This is what `InjectedState`-decorated tool args read from.

---

## 8. Invocation

```python
result = agent.invoke(
    {"messages": [HumanMessage("hi")], "authenticated_user_id": "u42"},
    config={"configurable": {"thread_id": "u42-s1"}},
)

print(result["messages"][-1].content)
```

`result["messages"]` contains the full conversation including tool calls and tool results.
For just the final text: `result["messages"][-1].content`.

Async: `await agent.ainvoke(...)`.

---

## 9. Embedding in a larger StateGraph

```python
graph = (
    StateGraph(AppState)
    .add_node("classify", classify_node)
    .add_node("agent", agent)              # compiled agent IS a node
    .add_edge(START, "classify")
    .add_conditional_edges("classify", route, {"agent": "agent", "end": END})
    .add_edge("agent", END)
    .compile(checkpointer=outer_checkpointer)
)
```

The agent runs as a subgraph. Middleware on the agent still fires.

---

## 10. Using `create_react_agent` instead

`langgraph.prebuilt.create_react_agent` is the lower-level cousin. Same loop, fewer
features, returns a raw compiled graph:

```python
from langgraph.prebuilt import create_react_agent

agent = create_react_agent(
    model=ChatAnthropic(model="claude-sonnet-4-6"),
    tools=[search],
)
```

When to choose which:

| Need | Pick |
|---|---|
| Standard tool-calling, middleware, structured output | `create_agent` |
| Just the bare ReAct loop, want to extend with custom edges | `create_react_agent` |
| Need to write custom routing logic | Hand-rolled `StateGraph` |

---

## 11. The most common patterns

### Tool-calling chatbot

```python
agent = create_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[search, calculator],
    system_prompt="You are a helpful assistant.",
)
```

### HITL-gated agent

```python
agent = create_agent(
    model="...",
    tools=[send_email, charge_card],
    middleware=[HumanInTheLoopMiddleware(interrupt_on={"send_email": True, "charge_card": True})],
    checkpointer=AsyncPostgresSaver(...),
)
```

### Structured-output agent

```python
class Report(BaseModel):
    summary: str
    actions: list[str]

agent = create_agent(
    model="...",
    tools=[lookup_data],
    response_format=Report,
)
```

### Per-user, durable

```python
agent = create_agent(
    model="...",
    tools=[...],
    checkpointer=AsyncPostgresSaver(...),
)

# Each user has their own thread:
result = await agent.ainvoke(
    {"messages": [HumanMessage(text)]},
    config={"configurable": {"thread_id": f"user-{user_id}"}},
)
```
