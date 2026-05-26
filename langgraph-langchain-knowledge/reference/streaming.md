# Streaming — `astream`, `astream_events`, Stream Modes

> How to get progressive output from a graph or agent. Critical for UX: a 30-second response
> feels broken without streaming.

---

## 1. The two stream APIs

| API | Returns | When |
|---|---|---|
| `graph.astream(...)` | Async iterator of state-update events | Standard UI streaming |
| `graph.astream_events(version="v2")` | Async iterator of fine-grained events (tokens, tool calls, node start/end) | Token-level UI, detailed traces |

Sync equivalents (`stream`, `stream_events`) exist for sync graphs.

---

## 2. `astream` — by mode

```python
async for event in graph.astream(
    {"messages": [HumanMessage("hi")]},
    config={"configurable": {"thread_id": "t1"}},
    stream_mode="updates",
):
    print(event)
```

### `stream_mode="updates"` (most common)

Yields `{node_name: {state_delta}}` after each node finishes.

```python
async for event in graph.astream(state, config=cfg, stream_mode="updates"):
    for node_name, delta in event.items():
        print(f"{node_name} produced: {delta}")
```

### `stream_mode="values"`

Yields the **full state** after each step.

```python
async for snapshot in graph.astream(state, config=cfg, stream_mode="values"):
    print("messages so far:", len(snapshot["messages"]))
```

Use when you need to react to cumulative state. More bandwidth than `updates`.

### `stream_mode="messages"`

Yields LLM **tokens** as they arrive. Each yield is `(message_chunk, metadata)`.

```python
async for chunk, meta in graph.astream(state, config=cfg, stream_mode="messages"):
    print(chunk.content, end="", flush=True)
```

Use for chat UIs that render text token-by-token.

### `stream_mode="custom"`

Yields whatever you pass to `dispatch_custom_event(name, data)` from within a node.

```python
from langchain_core.callbacks import adispatch_custom_event

async def search_node(state):
    await adispatch_custom_event("status", {"phase": "searching"})
    results = await search(state["query"])
    await adispatch_custom_event("status", {"phase": "done", "count": len(results)})
    return {"results": results}

async for event in graph.astream(state, config=cfg, stream_mode="custom"):
    print(event)
```

Great for progress reporting in long-running nodes.

### Multiple modes at once

```python
async for mode, event in graph.astream(state, config=cfg, stream_mode=["updates", "messages"]):
    if mode == "updates":
        ...
    elif mode == "messages":
        chunk, meta = event
        ...
```

The yielded tuple's first element identifies the mode.

---

## 3. `astream_events` — fine-grained

```python
async for event in graph.astream_events(state, config=cfg, version="v2"):
    event_name = event["event"]
    if event_name == "on_chat_model_stream":
        chunk = event["data"]["chunk"]
        print(chunk.content, end="")
    elif event_name == "on_tool_start":
        print(f"\n[calling {event['name']}]")
    elif event_name == "on_tool_end":
        print(f"\n[got result]")
```

Always pass `version="v2"` for new code. The full event taxonomy:

| Event | When |
|---|---|
| `on_chain_start` / `on_chain_end` | Around any Runnable (incl. nodes) |
| `on_chat_model_start` / `on_chat_model_stream` / `on_chat_model_end` | LLM lifecycle |
| `on_tool_start` / `on_tool_end` / `on_tool_error` | Tool lifecycle |
| `on_custom_event` | `dispatch_custom_event` payloads |

---

## 4. Token streaming through `create_agent`

```python
agent = create_agent(model="anthropic:claude-sonnet-4-6", tools=[...])

async for chunk, meta in agent.astream(
    {"messages": [HumanMessage("hi")]},
    config={"configurable": {"thread_id": "t1"}},
    stream_mode="messages",
):
    if chunk.content:
        print(chunk.content, end="", flush=True)
```

Tool calls don't have textual content in chunks; filter by checking `chunk.content`.

---

## 5. Interrupt handling in streams

```python
async for event in graph.astream(state, config=cfg, stream_mode="updates"):
    if "__interrupt__" in event:
        payload = event["__interrupt__"][0].value
        decision = await ask_user(payload)
        # Resume in a new stream
        async for resume_event in graph.astream(
            Command(resume=decision), config=cfg, stream_mode="updates"
        ):
            yield resume_event
        return
    yield event
```

---

## 6. Detecting the final answer

For `create_agent`, the final user-facing answer is the last `AIMessage` content. To stream
it as it arrives:

```python
async for chunk, meta in agent.astream(state, config=cfg, stream_mode="messages"):
    # meta["langgraph_node"] is the node that produced this chunk
    if meta["langgraph_node"] == "agent" and chunk.content:
        # This is the model speaking (vs. a tool result message)
        print(chunk.content, end="")
```

Or use `astream_events` and filter on `event["metadata"]["langgraph_node"]`.

---

## 7. Sending tokens to a websocket / SSE response

### SSE (Server-Sent Events) with FastAPI

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json

app = FastAPI()

@app.post("/chat")
async def chat(req: ChatRequest):
    async def gen():
        async for chunk, meta in agent.astream(
            {"messages": [HumanMessage(req.text)]},
            config={"configurable": {"thread_id": req.thread_id}},
            stream_mode="messages",
        ):
            if chunk.content:
                yield f"data: {json.dumps({'token': chunk.content})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
```

### WebSocket

Same pattern, send `json.dumps(...)` over the websocket instead of `yield`.

---

## 8. Cancellation

If the client disconnects, the async generator is cancelled. The graph's current node
finishes (or is cancelled at the next await point). For graceful cancellation:

```python
import asyncio

async def gen():
    try:
        async for event in graph.astream(state, config=cfg, stream_mode="updates"):
            yield event
    except asyncio.CancelledError:
        # cleanup, log, etc.
        raise
```

State-consistency note: a cancelled run may leave partial writes if the checkpointer
committed mid-superstep. Design tools to be idempotent (see `tools.md` §10).

---

## 9. Performance notes

- **`stream_mode="values"` is expensive** for large state. Don't use it for UI streaming.
- **`stream_mode="messages"` is the cheapest** — only LLM token chunks travel.
- **`astream_events` adds overhead** vs. `astream` because every Runnable lifecycle event
  is materialized. Fine in dev, consider `astream(stream_mode="updates")` in prod.
- **Tracing (LangSmith) adds latency.** Disable in latency-critical paths or sample.
