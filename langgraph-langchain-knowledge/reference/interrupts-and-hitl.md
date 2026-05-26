# Interrupts & Human-in-the-Loop

> The modern (LangGraph 1.0) pattern is the `interrupt()` function inside a node, paired
> with `Command(resume=...)` to continue. Static `interrupt_before` / `interrupt_after`
> still work for debugging breakpoints but are **not recommended for production HITL**.

---

## 1. Requirements

- A checkpointer must be configured (`interrupt` pauses by writing a checkpoint).
- Every invocation must pass `config={"configurable": {"thread_id": ...}}`.

---

## 2. The minimal pattern

```python
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

class State(TypedDict):
    proposal: str
    approved: bool | None

def propose(state: State) -> dict:
    return {"proposal": "delete all logs"}

def review(state: State) -> dict:
    decision = interrupt({"question": "approve?", "proposal": state["proposal"]})
    return {"approved": decision == "yes"}

def apply(state: State) -> dict:
    if state["approved"]:
        # do the thing
        pass
    return {}

builder = StateGraph(State)
builder.add_node("propose", propose)
builder.add_node("review", review)
builder.add_node("apply", apply)
builder.add_edge(START, "propose")
builder.add_edge("propose", "review")
builder.add_edge("review", "apply")
builder.add_edge("apply", END)

graph = builder.compile(checkpointer=InMemorySaver())
```

### First invocation (hits interrupt)

```python
config = {"configurable": {"thread_id": "t1"}}
result = graph.invoke({"proposal": "", "approved": None}, config=config)
print(result["__interrupt__"])
# [Interrupt(value={"question": "approve?", "proposal": "delete all logs"}, ...)]
```

### Resume

```python
final = graph.invoke(Command(resume="yes"), config=config)
print(final["approved"])  # True
```

The `interrupt()` call inside `review` returns `"yes"`. Execution continues from where it
paused — including any code in `review` after the `interrupt()` line.

---

## 3. How interrupt + resume actually work

1. Node hits `interrupt(payload)`. LangGraph:
   - Writes a checkpoint with the node's pre-interrupt state.
   - Persists the payload.
   - Returns from the graph run, with `__interrupt__` in the result.
2. Caller inspects `__interrupt__`, gathers human input.
3. Caller invokes `graph.invoke(Command(resume=value), config={"thread_id": ...})`.
4. LangGraph:
   - Loads the checkpoint.
   - **Re-runs the node from the beginning.** Any code before `interrupt()` runs again.
   - When the same `interrupt()` is hit, instead of pausing, it returns `value`.
   - Execution continues.

**Implication: anything before `interrupt()` must be idempotent**. Don't send the email on
line 1, then `interrupt()` on line 3, expecting the email not to send again on resume. It
will.

✅ Pattern:

```python
def review(state):
    decision = interrupt({"q": "approve?"})   # FIRST line
    if decision == "yes":
        send_email(state["draft"])             # AFTER interrupt
    return {"approved": decision == "yes"}
```

---

## 4. Multiple interrupts in one node

You can call `interrupt()` more than once. On resume, you can pass multiple values via the
`Command.resume` list (advanced) or use one interrupt per node.

For clarity, prefer one `interrupt()` per node.

---

## 5. With `create_agent` and `HumanInTheLoopMiddleware`

For tool-call approval, you don't write nodes — use middleware:

```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver

agent = create_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[read_email, send_email, delete_thread],
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={
                "send_email": True,        # always interrupt
                "delete_thread": True,
            }
        ),
    ],
    checkpointer=InMemorySaver(),
)
```

Keys in `interrupt_on` match the tool's `.name`. For `@tool`-decorated functions, the name
defaults to the function name.

Invocation:

```python
config = {"configurable": {"thread_id": "t1"}}
result = agent.invoke({"messages": [HumanMessage("send 'hi' to bob")]}, config=config)

if "__interrupt__" in result:
    # show tool call details to user, get approval
    decision = "yes"  # or "no", or "edit", etc.
    final = agent.invoke(Command(resume=decision), config=config)
```

### Decision shapes

`HumanInTheLoopMiddleware` accepts richer decisions than yes/no:

```python
# Accept the tool call as-is
Command(resume={"type": "accept"})

# Reject — tool not executed, agent receives a message saying so
Command(resume={"type": "reject", "reason": "not now"})

# Edit args before execution
Command(resume={"type": "edit", "args": {"to": "alice@example.com"}})
```

---

## 6. Streaming with interrupts

```python
async for event in agent.astream(state, config=config, stream_mode="updates"):
    if "__interrupt__" in event:
        payload = event["__interrupt__"][0].value
        decision = await ask_user_async(payload)
        async for resume_event in agent.astream(
            Command(resume=decision), config=config, stream_mode="updates"
        ):
            yield resume_event
        return
    yield event
```

---

## 7. Static interrupts (debugging only)

```python
graph = builder.compile(
    checkpointer=InMemorySaver(),
    interrupt_before=["risky_node"],
    interrupt_after=["expensive_node"],
)
```

The graph pauses before/after those nodes regardless of state. Useful in a debugger or for
manual step-through during development. **Don't use for production HITL**: the dynamic
`interrupt()` function gives the agent control over WHEN to pause, with a payload.

---

## 8. Editing state during a pause

You can modify state before resuming:

```python
# Look at what's paused
snapshot = graph.get_state(config)
print(snapshot.values["pending_tool_call"])

# Edit
graph.update_state(config, {"pending_tool_call": {"name": "search", "args": {"q": "edited"}}})

# Resume
graph.invoke(None, config=config)
```

`update_state` with `as_node="X"` writes as if node X produced the update — useful when
resuming.

---

## 9. Gotchas

1. **No checkpointer → no interrupt.** Compilation error or silent skip depending on
   version. Always pair.
2. **No `thread_id` → interrupt-resume cycle is broken.** Resume can't find the paused
   state.
3. **Side effects before `interrupt()`** repeat on resume. Put `interrupt()` first.
4. **`stream` consumer doesn't check `__interrupt__`** → HITL silently does nothing. Always
   check.
5. **Different `thread_id` on resume** → starts a fresh run from the beginning. Always
   reuse.
