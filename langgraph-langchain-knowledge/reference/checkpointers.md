# Checkpointers — Persistence Reference

> Checkpointers save graph state at every node execution. Required for: durable execution,
> human-in-the-loop, time-travel, conversation memory.

---

## 1. The contract

A checkpointer is a backend that stores:
- **Checkpoints**: serialized state snapshots after each superstep.
- **Writes**: pending updates between supersteps.
- **Channel versions**: tracking which channel (state field) has been updated.

Keyed by `thread_id` (the conversation/session) and optionally a `checkpoint_id` (a specific
point in history, for time-travel).

---

## 2. Built-in checkpointers

| Class | Import | Use case |
|---|---|---|
| `InMemorySaver` | `langgraph.checkpoint.memory` | Tests, scripts, local dev |
| `SqliteSaver` / `AsyncSqliteSaver` | `langgraph.checkpoint.sqlite[.aio]` | Single-process local persistence |
| `PostgresSaver` / `AsyncPostgresSaver` | `langgraph.checkpoint.postgres[.aio]` | Production |
| `RedisSaver` / `AsyncRedisSaver` | `langgraph.checkpoint.redis[.aio]` | Production (Redis-first stacks) |

Each has a sync and async variant. **Match to your graph**: sync graph → sync saver; async
graph (`ainvoke`, `astream`) → async saver. Mixing blocks the event loop.

---

## 3. In-memory (tests / dev)

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)
```

State is lost when the process exits. Do not use in production.

(Note: `MemorySaver` still works as a legacy alias.)

---

## 4. Postgres (async)

### Connection string

```python
import os
DB_URI = os.environ["POSTGRES_URI"]
# postgres://user:pass@host:5432/dbname?sslmode=require
```

### Setup (run once, manually or in a migration)

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async with AsyncPostgresSaver.from_conn_string(DB_URI) as saver:
    await saver.setup()           # creates tables/indexes
```

### Use as context manager

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async def main():
    async with AsyncPostgresSaver.from_conn_string(DB_URI) as saver:
        graph = builder.compile(checkpointer=saver)
        result = await graph.ainvoke(
            {"messages": [...]},
            config={"configurable": {"thread_id": "user-42"}},
        )
```

### Use with a connection pool (better for servers)

```python
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

pool = AsyncConnectionPool(conninfo=DB_URI, max_size=20, kwargs={"autocommit": True})

async def lifespan(app):
    async with pool:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        app.state.checkpointer = saver
        yield
```

Then in your handler:

```python
graph = builder.compile(checkpointer=app.state.checkpointer)
```

---

## 5. Sync Postgres

```python
from langgraph.checkpoint.postgres import PostgresSaver

with PostgresSaver.from_conn_string(DB_URI) as saver:
    saver.setup()
    graph = builder.compile(checkpointer=saver)
    result = graph.invoke(state, config={"configurable": {"thread_id": "t1"}})
```

---

## 6. Reading state outside a run

```python
# Get the latest checkpoint
state_snapshot = await graph.aget_state(config={"configurable": {"thread_id": "t1"}})
print(state_snapshot.values)             # the state dict
print(state_snapshot.next)               # next nodes to run, if interrupted

# List history (for time travel)
async for snapshot in graph.aget_state_history(config={"configurable": {"thread_id": "t1"}}):
    ...

# Manually update state (e.g., after editing a message)
await graph.aupdate_state(
    config={"configurable": {"thread_id": "t1"}},
    values={"messages": [HumanMessage("revised")]},
    as_node="agent",   # optional, route as if this node produced the update
)
```

---

## 7. Time travel

You can resume from any past checkpoint by passing its `checkpoint_id`:

```python
config = {
    "configurable": {
        "thread_id": "t1",
        "checkpoint_id": "01HXYZ...",   # from get_state_history
    }
}
result = await graph.ainvoke(None, config=config)   # `None` resumes
```

This forks the timeline: state diverges from that point, both branches preserved.

---

## 8. Thread IDs — the practical part

`thread_id` is the partition key. Choose it intentionally:

- **Per conversation**: `f"conv-{conversation_id}"`. Most common.
- **Per user session**: `f"user-{user_id}-session-{session_id}"`. Good when sessions
  have a TTL.
- **Per task**: `f"task-{task_uuid}"`. For background jobs.

**Never** let an unauthenticated client choose the `thread_id` directly. An attacker can
read someone else's state by guessing or knowing the ID. Always derive from an
authenticated identifier or auth-check before reading.

---

## 9. Cleanup

LangGraph doesn't TTL checkpoints. You're responsible for purging old threads.

```python
await saver.adelete_thread("t1")   # removes all checkpoints for this thread
```

Run a job that prunes threads older than your retention policy.

---

## 10. Choosing between Postgres / Redis / SQLite

- **Postgres**: default for most. Durable, queryable, transactional. The async saver with a
  connection pool handles thousands of concurrent threads.
- **Redis**: pick when your stack is Redis-heavy. Slightly faster for small writes. Less
  history queryability (depends on Redis layout).
- **SQLite**: single-process apps, CLIs, local tools. Don't share across processes.
- **In-memory**: tests only.

---

## 11. Common bugs

1. **Sync saver in async graph.** Event loop blocks. Use `Async*Saver`.
2. **No `thread_id` in config.** Saver does nothing useful.
3. **One `thread_id` per process** because someone hard-coded `"default"`. All users share
   one conversation. Use a real session ID.
4. **State contains non-serializable objects.** Pickling fails. Strip before writing.
5. **Forgetting `await saver.setup()`** on first deploy. Tables don't exist; first invoke
   crashes.
