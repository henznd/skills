# LangGraph 1.0 — Code Review Reference

> Deep checklist for reviewing files that define a `StateGraph` or use the LangGraph runtime
> primitives. Pair this with `agent-architecture-review.md` when the file uses `create_agent`.

---

## 1. State Schema

### 1.1 The schema must be a typed contract

✅ Good:

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    retry_count: int
```

🔴 `[blocking]` Untyped state (`dict`) — reducers can't be attached, and downstream
nodes can't be type-checked.

```python
# ❌ Don't
graph = StateGraph(dict)
```

🟠 `[important]` Pydantic `BaseModel` is valid in 1.0, but be aware: mutation semantics
differ from `TypedDict`. With Pydantic, returning a partial dict still merges; returning a
`BaseModel` instance replaces. Pick one style per project.

### 1.2 Reducers are non-optional for accumulating fields

Any field that should accumulate across nodes (messages, retrieved docs, errors, tool
results) **must** use `Annotated[list[...], <reducer>]`. Without a reducer, the second node
that returns `{"messages": [new_msg]}` will *overwrite* the first, not append.

🔴 `[blocking]` to flag:

```python
class State(TypedDict):
    messages: list[AnyMessage]   # ❌ no reducer — overwrites
    docs: list[Document]         # ❌ no reducer — last node wins
```

✅ Fix:

```python
from operator import add
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    docs:     Annotated[list[Document], add]
```

### 1.3 Custom reducers must be pure and idempotent

If a custom reducer is defined, check:
- It takes `(left, right)` and returns a new value (no mutation of inputs).
- It is deterministic (no `time.time()`, no random IDs without a seed).
- It handles `left is None` (first write).
- It handles duplicate items if the graph can replay (checkpointing replays nodes).

🟠 `[important]` flag any reducer that mutates `left` or `right`.

### 1.4 Don't put non-serializable values in state when using a checkpointer

If a checkpointer is configured, state is pickled (default) or JSON-encoded (some
checkpointers). Flag:

🔴 `[blocking]` — open file handles, DB connections, `httpx.AsyncClient` instances, or
generators in state.
🟠 `[important]` — large blobs (images, PDFs) directly in state. Store an ID and fetch in
the node.

---

## 2. Nodes

### 2.1 A node returns a partial update, never mutates state

🔴 `[blocking]`:

```python
def bad_node(state: State) -> State:
    state["messages"].append(AIMessage("hi"))   # ❌ mutation
    return state
```

✅:

```python
def good_node(state: State) -> dict:
    return {"messages": [AIMessage("hi")]}
```

The reducer (`add_messages`) handles the append. The pattern above:
- Survives parallel execution.
- Survives replay during checkpoint resume.
- Composes correctly when the node is invoked as a subgraph.

### 2.2 Nodes should be small and named for what they do

🟡 `[nit]` Nodes named `step1`, `node_a`, `process` are unreviewable. Use verb-noun:
`classify_intent`, `retrieve_docs`, `summarize_results`.

### 2.3 Long-running work belongs in async nodes

If a node does I/O (LLM call, HTTP request, DB query), it should be `async def` and the graph
invoked with `await graph.ainvoke(...)`. Mixing sync nodes with `astream` works but blocks
the event loop on the sync node.

🟠 `[important]` Sync node doing `requests.get(...)` inside an otherwise-async graph.

### 2.4 Don't catch and swallow inside a node

A bare `except: pass` inside a node hides the failure from LangSmith traces and from
downstream conditional routing. Either:
- Re-raise after logging.
- Return an error field in state (`{"error": str(e)}`) and route on it.

🔴 `[blocking]` for `except Exception: pass` inside a node.

---

## 3. Edges

### 3.1 Conditional edges must be **total**

The router function in `add_conditional_edges` must map every reachable state to a registered
destination, or LangGraph raises at runtime.

🔴 `[blocking]`:

```python
def route(state) -> str:
    if state["needs_tools"]:
        return "tools"
    # ❌ implicit None when needs_tools is False
```

✅ Two acceptable patterns:

```python
# Pattern A: explicit mapping + default
graph.add_conditional_edges(
    "agent",
    route,
    {"tools": "tools", "end": END},
)

def route(state) -> str:
    return "tools" if state["needs_tools"] else "end"
```

```python
# Pattern B: router returns END directly
from langgraph.graph import END

def route(state) -> str:
    if state["needs_tools"]:
        return "tools"
    return END
```

### 3.2 Mapping dict in add_conditional_edges must cover all return values

🟠 `[important]`:

```python
def route(state):
    return state["next"]   # could be anything

graph.add_conditional_edges("agent", route, {"a": "node_a", "b": "node_b"})
# ❌ if state["next"] == "c", runtime crash
```

Either constrain the router's return type with a `Literal` and let mypy enforce it, or add a
fallback key.

### 3.3 Every non-END node has at least one outgoing edge

🔴 `[blocking]` A node with no outgoing edge silently halts the run when reached. Grep for
nodes that appear in `add_node` but not on the source side of `add_edge` or
`add_conditional_edges`, and aren't `END`.

### 3.4 `START` is reachable, `END` is reachable

🔴 `[blocking]` No edge from `START`. The graph compiles but never runs.

🟠 `[important]` An unreachable subgraph (orphan nodes). Often indicates a dead branch left
from refactoring.

---

## 4. Compile-time options

```python
graph = builder.compile(
    checkpointer=...,
    interrupt_before=[...],
    interrupt_after=[...],
)
```

### 4.1 `checkpointer` choice matches the deployment

| Checkpointer | When valid |
|---|---|
| `InMemorySaver` | Tests, scripts, local dev only |
| `PostgresSaver` / `AsyncPostgresSaver` | Production with Postgres |
| `RedisSaver` | Production where Postgres isn't available |
| `SqliteSaver` | Single-process local persistence |

🔴 `[blocking]` `InMemorySaver` (or the old `MemorySaver`) in a production code path. State
is lost on restart.

🟠 `[important]` Async graph (`ainvoke`/`astream`) with the sync `PostgresSaver` — use
`AsyncPostgresSaver` to avoid blocking the event loop.

### 4.2 `interrupt_before` / `interrupt_after` are deprecated for HITL

Per LangGraph 1.0 docs: **static interrupts (`interrupt_before`/`interrupt_after`) are not
recommended for human-in-the-loop workflows**. Use the `interrupt()` function inside the node
instead.

🟠 `[important]` if you see `interrupt_before=[...]` used for HITL approval. Static
interrupts are still fine for debugging breakpoints, but for production HITL the dynamic
`interrupt()` is the supported path.

✅ Modern HITL pattern:

```python
from langgraph.types import interrupt, Command

def approve_node(state):
    decision = interrupt({"question": "approve?", "tool_call": state["pending_call"]})
    if decision == "yes":
        return {"approved": True}
    return Command(goto=END)
```

Resume with:

```python
graph.invoke(Command(resume="yes"), config={"configurable": {"thread_id": "t1"}})
```

### 4.3 `thread_id` is mandatory whenever a checkpointer is set

🔴 `[blocking]`:

```python
checkpointer = AsyncPostgresSaver(...)
graph = builder.compile(checkpointer=checkpointer)
result = graph.invoke({"messages": [...]})   # ❌ no config — writes nowhere coherent
```

✅:

```python
result = graph.invoke(
    {"messages": [...]},
    config={"configurable": {"thread_id": user_session_id}},
)
```

Common bug: deriving `thread_id` from a user-controlled value without scoping it per user.
🟠 `[important]`: if `thread_id = request.json["thread_id"]` with no auth check, one user
can read another user's thread state.

---

## 5. Cycles and recursion

### 5.1 Any loop needs a stop condition

ReAct-style agent loops (model → tools → model → ...) are cycles. If the model never decides
to stop, you spin until `recursion_limit` (default 25) raises `GraphRecursionError`.

🟠 `[important]`:
- No `recursion_limit` override when 25 is too low or too high for the use case.
- No state-based counter (`state["iterations"]`) as a defense in depth.

✅:

```python
graph.invoke(
    state,
    config={
        "configurable": {"thread_id": ...},
        "recursion_limit": 50,
    },
)
```

### 5.2 Tools that always trigger more tool calls = infinite loop

Watch for tools whose output description nudges the model to call another tool. Example: a
search tool whose result says "for more details, call `fetch_full_page`" — the model will
keep going. Either:
- Cap with a counter in state.
- Use middleware to terminate after N tool calls.

---

## 6. Command primitive

`Command` is the 1.0 way to combine a state update with a routing decision from inside a node.

```python
from langgraph.types import Command

def node(state) -> Command:
    if state["risky"]:
        return Command(goto=END, update={"status": "rejected"})
    return Command(goto="next_step", update={"status": "ok"})
```

🟡 `[nit]` Code that uses both a conditional edge AND `Command(goto=...)` on the same node —
pick one. `Command` is preferred when the decision and the state update belong together.

🟠 `[important]` `Command(goto=...)` to a node that isn't registered in `add_node` — fails
at runtime.

---

## 7. Subgraphs

When a node is itself a compiled graph (or an agent built with `create_agent`):

- The parent and subgraph schemas must share at least the keys the subgraph reads/writes, or
  use an input/output mapping.
- If the subgraph has its own checkpointer, decide: per-thread vs per-invocation scoping.
  Per-LangChain 1.0 docs, subgraph checkpointer scoping is explicit and the wrong choice
  causes silent state leakage across requests.

🔴 `[blocking]` Subgraph with a different checkpointer than the parent, no documentation of
why, and the schemas overlap. Likely a state-leak bug.

---

## 8. Streaming

When the graph is consumed via `astream` or `astream_events`:

- The consumer should handle the `__interrupt__` key (now also returned in `invoke`/`ainvoke`
  results since 0.4.0).
- `stream_mode="updates"` yields node-by-node deltas; `"values"` yields full state snapshots.
  Mixing them across consumers of the same stream is a bug.
- Token streaming requires `stream_mode="messages"` (LangChain 1.0) or
  `astream_events(version="v2")`.

🟠 `[important]` UI consumes `stream_mode="values"` and re-renders the whole state on every
event — quadratic re-renders. Use `"updates"`.

---

## 9. Common bugs cheat sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| State resets between invocations | Missing `thread_id` in config | Pass `config={"configurable": {"thread_id": ...}}` |
| `messages` overwritten, not appended | No `add_messages` reducer | `Annotated[list[...], add_messages]` |
| `GraphRecursionError` | Cycle with no stop condition | Add counter in state OR raise `recursion_limit` |
| `ValueError: ... not a valid destination` | Router returned unmapped key | Add fallback, or use `Literal` return type |
| Silent halt | Node has no outgoing edge | Add `add_edge("node", "next")` or `add_edge("node", END)` |
| State lost on restart | `InMemorySaver` in prod | Switch to `PostgresSaver` / `AsyncPostgresSaver` |
| One user sees another's thread | `thread_id` not scoped per user | Include user_id in thread_id or auth-check before use |
| Async graph blocks | Sync checkpointer or sync I/O in node | Use `Async*Saver`, `async def` nodes |
| Mutation across runs | Node mutated state in place | Return dict of updates only |

---

## 10. Quick triage script

When opening a new file, run mentally:

1. Find the `StateGraph(X)` call — what is `X`? Read its definition.
2. Find every `add_node` — note the names.
3. Find every `add_edge` and `add_conditional_edges` — draw the topology in your head.
4. Find the `.compile(...)` call — note checkpointer, interrupts.
5. Find every `.invoke` / `.ainvoke` / `.stream` / `.astream` — verify `thread_id` is passed.
6. Walk back through each node:
   - Does it mutate state?
   - Does it have error handling?
   - Is it sync vs async consistent with the rest of the graph?

This 6-step pass catches ~70% of the framework-specific bugs.
