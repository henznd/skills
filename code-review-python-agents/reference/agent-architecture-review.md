# Agent Architecture — Code Review Reference

> For files that use `create_agent` (LangChain 1.0) or `create_react_agent` (LangGraph
> prebuilt). Pair with `langgraph-review.md` when the agent is embedded in a larger graph.

---

## 1. Which abstraction is appropriate?

LangChain 1.0 introduced **two** levels of agent:

| Level | API | When |
|---|---|---|
| High-level | `langchain.agents.create_agent(...)` | Standard tool-calling loop, you want sensible defaults + middleware |
| Low-level | `langgraph.prebuilt.create_react_agent(...)` | Same loop, but you want the raw LangGraph node back to extend |
| Custom | Hand-built `StateGraph` | Multi-agent, parallel branches, custom routing, non-ReAct patterns |

🟡 `[nit]` Hand-built ReAct loop when `create_agent` would do — adds code surface without
benefit. Suggest the prebuilt, mention what middleware would replace the custom bits.

🟠 `[important]` `create_agent` used when the requirement is multi-step orchestration with
parallel branches or supervisor pattern. The prebuilt loop won't compose well; build a
`StateGraph`.

---

## 2. `create_agent` signature

```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

agent = create_agent(
    model="claude-sonnet-4-6",         # or a BaseChatModel instance
    tools=[read_email, send_email],    # REQUIRED, even if empty
    system_prompt="...",               # optional but recommended
    middleware=[                       # ordered list of middleware
        HumanInTheLoopMiddleware(interrupt_on={"send_email": True}),
    ],
    response_format=MyPydanticModel,   # for structured final output
    checkpointer=InMemorySaver(),      # optional, enables HITL
)
```

What to verify on review:

### 2.1 `tools` is always passed

🔴 `[blocking]` `create_agent(model=..., system_prompt=...)` with `tools` omitted.
Per LangChain 1.0 design, `tools` is required even if empty — explicit over implicit. Code
that relies on the old default will fail.

### 2.2 `model` parameter is provider-agnostic but version-pinned

✅ Acceptable:

```python
agent = create_agent(model="anthropic:claude-sonnet-4-6", tools=[...])
```

🟠 `[important]` Hard-coded provider with the API key in source:

```python
from langchain_openai import ChatOpenAI
agent = create_agent(
    model=ChatOpenAI(api_key="sk-..."),  # ❌
    tools=[...],
)
```

🟡 `[nit]` No version pin in the model string (`"claude-sonnet-4"` instead of
`"claude-sonnet-4-6"`). Aliases drift; pin for reproducibility.

### 2.3 `system_prompt` is a string, not a template

In `create_agent`, `system_prompt` accepts a string. For dynamic system prompts, use a
**middleware hook** (`@before_model`) — not string interpolation.

🟠 `[important]`:

```python
# ❌ Won't be re-rendered if state changes
agent = create_agent(
    model=...,
    tools=[...],
    system_prompt=f"You are helping {user.name}. {extra}",
)
```

✅ Use a middleware that mutates `messages` before the model call.

### 2.4 `response_format` for structured output

```python
class Summary(BaseModel):
    headline: str
    bullets: list[str]

agent = create_agent(model=..., tools=[...], response_format=Summary)
```

🔴 `[blocking]` `response_format` set but tools include free-text-returning tools without
the prompt explaining that final response must conform. The agent may stop mid-loop and
return malformed output.

🟠 `[important]` `response_format=Summary` and tests don't actually validate the parsed
structure. Add `assert isinstance(result["structured_response"], Summary)`.

---

## 3. Middleware

LangChain 1.0 middleware exposes three hooks:

| Hook | Runs |
|---|---|
| `before_model` | Before each LLM call |
| `after_model` | After each LLM call, before tool dispatch |
| `before_tool` / `after_tool` | Around tool execution |

### 3.1 Middleware order matters

🟠 `[important]` Middleware list order matters: outer middleware wraps inner. A retry
middleware AFTER a logging middleware will log only the last attempt. Document the order in
a comment if non-obvious.

### 3.2 Built-in middleware to know

- `HumanInTheLoopMiddleware(interrupt_on={"tool_name": True})` — pauses before specific tool
  calls. Keys match the tool's `.name` (function name for `@tool`-decorated functions).
- `SummarizationMiddleware` — compresses message history when it exceeds a threshold.
- `PIIRedactionMiddleware` (where used) — should run before any tool that calls out.

🔴 `[blocking]` `HumanInTheLoopMiddleware` set but agent compiled without a checkpointer.
HITL needs a checkpointer to pause/resume. Will throw at runtime.

### 3.3 Custom middleware must be a class with the right base

```python
from langchain.agents.middleware import AgentMiddleware

class LoggingMiddleware(AgentMiddleware):
    async def before_model(self, state, runtime):
        ...
```

🟠 `[important]` Custom middleware doing blocking I/O (`requests.post`) inside an async
graph. Use `httpx.AsyncClient` or `asyncio.to_thread`.

### 3.4 Don't reach into `state` to bypass middleware

If a middleware redacts PII from `messages`, downstream code that reads the un-redacted
original from another state field defeats the redaction.

🔴 `[blocking]` Middleware redacts `messages[-1].content` but tool reads `state["raw_input"]`
which was never redacted. Either redact at the source or don't keep a parallel copy.

---

## 4. Tool binding

Tools are passed as `tools=[...]`. Each must be one of:

- A `@tool`-decorated function (langchain_core).
- A `BaseTool` instance.
- A dict matching the OpenAI tool-call schema (rare, for cross-provider compatibility).
- An MCP tool loaded via `langchain-mcp-adapters`.

### 4.1 Tool name uniqueness

🔴 `[blocking]` Two tools with the same `.name`. The agent will call one and you won't know
which. Common cause: importing tools from multiple MCP servers without namespacing.

### 4.2 Tool docstring is the prompt

The docstring of a `@tool`-decorated function is what the LLM sees. Treat it as a prompt.

```python
@tool
def search_docs(query: str, top_k: int = 5) -> list[str]:
    """Search the company knowledge base.

    Args:
        query: Natural-language search query. Be specific.
        top_k: Number of results. Default 5, max 20.

    Returns: A list of matching excerpts. Empty list if no match.
    """
    ...
```

🟠 `[important]` Single-line or missing docstring on a tool. The model has to guess the
intent.

🟡 `[nit]` Docstring describes implementation, not behavior. Rewrite from the model's POV.

### 4.3 Tool arg types must be JSON-serializable

🔴 `[blocking]` Tool with a `datetime`, `Path`, or arbitrary Pydantic model arg without an
explicit JSON-schema mapping. The provider will fail to construct a call.

✅ Use `str` (ISO 8601 for dates) or a `BaseModel` with primitive fields.

### 4.4 Tool error handling

🔴 `[blocking]` Tool that does:

```python
@tool
def query_db(sql: str) -> str:
    try:
        return run(sql)
    except Exception as e:
        return f"error: {e}"   # ❌ model sees this as success
```

Pick one:
- Re-raise — LangGraph captures it and adds a `ToolMessage` with `status="error"` that the
  model can react to.
- Return a clearly-prefixed string the system prompt teaches the model to recognize as a
  retry signal: `return f"ERROR: {e!s}. Try a simpler query."`

Both work; mixing them silently is the bug.

### 4.5 Tools that mutate external state need idempotency or HITL

🔴 `[blocking]` `send_email`, `charge_card`, `delete_user` exposed as tools without
`HumanInTheLoopMiddleware` and without idempotency keys. The agent can retry on its own and
double-fire.

---

## 5. Embedding `create_agent` in a larger graph

A common 1.0 pattern:

```python
email_agent = create_agent(
    model="claude-sonnet-4-6",
    tools=[read_email, send_email],
    middleware=[HumanInTheLoopMiddleware(interrupt_on={"send_email": True})],
)

graph = (
    StateGraph(AppState)
    .add_node("classify", classify_node)
    .add_node("email_agent", email_agent)   # the compiled agent IS a node
    .add_edge(START, "classify")
    .add_conditional_edges("classify", route)
    .compile()
)
```

What to check:
- Middleware is set on the **inner** agent, not the outer graph.
- State schema of the outer graph is a superset of (or maps to) what the agent reads/writes
  (`messages`, etc.). If keys collide unexpectedly, agent updates overwrite outer state.
- The outer graph's checkpointer scope vs the agent's. Subgraph checkpointers in 1.0 have
  explicit per-invocation / per-thread scoping — verify the choice matches the use case.

🟠 `[important]` Outer graph compiled with `checkpointer=PostgresSaver(...)` and inner agent
also compiled with `checkpointer=InMemorySaver()`. The inner saver shadows the outer for the
agent's own steps — likely not intended.

---

## 6. System prompt review

Read the system prompt as a contract:

- Does it tell the model **what NOT to do**? (Refusals, scope limits.)
- Does it list the tools and when to use each? (Critical for >3 tools.)
- Does it say what to do on tool error?
- Does it say when to stop? (Especially for ReAct with no natural terminal.)
- Are user-provided values **never** concatenated unescaped into the system prompt? (Prompt
  injection — see `security-review.md`.)

🔴 `[blocking]` `f"You are helping {user_provided_role}. ..."` — user controls the system
prompt.

---

## 7. The agent test surface

For every `create_agent` call, expect at least:
1. A "happy path" test that asserts the final message + tool calls in order.
2. A test where every tool raises — agent should recover or terminate cleanly.
3. If `response_format` is set, a test that asserts `isinstance(result["structured_response"], ...)`.
4. If HITL middleware, a test that interrupts and resumes.

🟠 `[important]` PR adds an agent with no tests beyond a smoke import.

See `testing-and-observability-review.md` for mocking patterns.
