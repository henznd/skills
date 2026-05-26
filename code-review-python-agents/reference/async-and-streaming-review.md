# Async & Streaming — Code Review Reference

> For code paths using `ainvoke`, `astream`, `astream_events`, and any async tool / node.

---

## 1. Sync vs async — consistency

Pick one per code path. Mixing causes the most subtle bugs.

| Graph call | Nodes should be | Checkpointer | Tools |
|---|---|---|---|
| `graph.invoke(...)` | `def` | `*Saver` (sync) | `def` |
| `await graph.ainvoke(...)` | `async def` | `Async*Saver` | `async def` (preferred) |

🟠 `[important]` Async graph using sync `PostgresSaver`. The checkpointer's I/O blocks the
event loop — defeats async benefits.

🟠 `[important]` Sync graph calling `asyncio.run(...)` inside a node. Creates a new event
loop per node call, breaks if anything upstream is already async.

---

## 2. Don't block in async nodes

🔴 `[blocking]`:

```python
async def fetch_node(state):
    response = requests.get(state["url"])   # ❌ blocks event loop
    return {"data": response.text}
```

✅:

```python
async def fetch_node(state):
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(state["url"])
    return {"data": response.text}
```

Other common blocking calls to flag inside async nodes:
- `time.sleep(...)` (use `asyncio.sleep`)
- `psycopg2.*` (use `asyncpg` or psycopg3 async)
- Synchronous LangChain wrappers (`OpenAI()` instead of `ChatOpenAI(...)` — the sync chain
  imports)

If you must call sync code, wrap in `asyncio.to_thread(sync_fn, args)`.

---

## 3. `astream` modes

```python
async for chunk in graph.astream(state, config=..., stream_mode="updates"):
    ...
```

| `stream_mode` | What you get | When to use |
|---|---|---|
| `"values"` | Full state after each node | Debugging, full re-renders |
| `"updates"` | Just the delta from each node | Standard UI streaming |
| `"messages"` | LLM tokens as they arrive | Token-level UI |
| `"custom"` | `dispatch_custom_event` payloads | Per-step status updates |
| List of the above | Multi-stream | Advanced UIs |

🟠 `[important]` UI consuming `"values"` and re-rendering the entire conversation on each
event — wasteful. Use `"updates"`.

🟠 `[important]` Backend logging `"messages"` for traceability — floods logs with tokens.
Log `"updates"` server-side, stream `"messages"` to UI.

---

## 4. `astream_events`

```python
async for event in graph.astream_events(state, config=..., version="v2"):
    ...
```

- 🟠 `[important]` `version="v1"` in new code. v2 is the supported event format.
- 🟡 `[nit]` Iterating events without filtering by `event["event"]` type — handler grows
  unreadable. Match on event name (`on_chat_model_stream`, `on_tool_end`, etc).

---

## 5. Interrupt handling in streams

Since LangGraph 0.4.0+, the `__interrupt__` key is also returned in `invoke`/`ainvoke`
results. In streams it appears as an event/key.

✅ Pattern:

```python
async for event in graph.astream(state, config=cfg, stream_mode="updates"):
    if "__interrupt__" in event:
        question = event["__interrupt__"][0].value
        answer = await ask_user(question)
        async for resume_event in graph.astream(
            Command(resume=answer), config=cfg, stream_mode="updates"
        ):
            ...
```

🟠 `[important]` Stream consumer that doesn't handle `__interrupt__` — HITL silently fails
or hangs.

---

## 6. Cancellation safety

Async generators (`astream`) can be cancelled by the client disconnecting. The graph state
must be safe with a partial run:

- 🟠 `[important]` Tool that opens a transaction but commits in a later node. Mid-stream
  cancel = open transaction. Use idempotent operations or finalize in the same node.
- 🟠 `[important]` Side effect (charge card, send email) in node N, but N+1 records it to
  the DB. Cancel between N and N+1 = double-spend on retry. Move the record into N or use
  an outbox pattern.

---

## 7. Concurrency on the same thread_id

🔴 `[blocking]` Two parallel invocations with the same `thread_id` against a checkpointer
that doesn't serialize writes (most don't). Last-write-wins on state, corrupted history.

If a user can fire two requests with the same `thread_id`:
- Queue server-side.
- Or use a per-user lock keyed on `thread_id`.

---

## 8. Async patterns specific to FastMCP tools

(Cross-reference with `fastmcp-review.md` §3.3.)

🔴 `[blocking]` `async with httpx.AsyncClient() as client:` per call. Creates and tears down
a connection pool each time. Either:
- Module-level `httpx.AsyncClient` with `timeout` set, closed on shutdown.
- Or a singleton in app state.

```python
# Recommended for production
_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))

@mcp.tool
async def fetch(url: str) -> str:
    r = await _client.get(url)
    return r.text
```

Make sure it's closed in the server's lifespan.

---

## 9. Performance smell tests

- Run the agent with `langsmith` tracing on, look at the timeline:
  - Are LLM calls parallelizable but serial? (Multiple independent retrievals → parallel
    nodes with a fan-out, joined by a reducer.)
  - Is the same tool called with identical args twice in a row? Add a memoization
    middleware.
  - Is checkpoint write the slowest step? Switch to `AsyncPostgresSaver` with a connection
    pool.

🟠 `[important]` p95 latency dominated by checkpointer writes — usually means sync
checkpointer in async graph, OR write-amplification (state too large).
