# Parallelism — `Send`, Map-Reduce, Defer

> LangGraph runs nodes in parallel automatically when multiple edges from one node arrive at
> different destinations. For *dynamic* fan-out where the number of branches isn't known at
> compile time, use `Send`.

---

## 1. Static parallel branches

```python
builder.add_edge("planner", "worker_a")
builder.add_edge("planner", "worker_b")
builder.add_edge("planner", "worker_c")

# All three workers run in parallel in the next superstep.
builder.add_edge("worker_a", "merger")
builder.add_edge("worker_b", "merger")
builder.add_edge("worker_c", "merger")
```

LangGraph waits for all parallel branches to complete before invoking `merger`. Their
returned updates merge via the state's reducers.

For accumulating outputs, ensure the relevant field has a list reducer:

```python
from operator import add

class State(TypedDict):
    results: Annotated[list[str], add]
```

Each worker returns `{"results": [its_result]}`. After the superstep, `state["results"]`
contains all three.

---

## 2. Dynamic fan-out with `Send`

`Send(node_name, state_for_that_invocation)` is what a routing function returns to spawn a
parallel instance of a node with custom input.

```python
from langgraph.types import Send
from operator import add

class State(TypedDict):
    docs: list[str]
    summaries: Annotated[list[str], add]

def fan_out(state: State) -> list[Send]:
    """Emit one Send per doc → parallel summarizer."""
    return [Send("summarize", {"doc": doc}) for doc in state["docs"]]

def summarize(input: dict) -> dict:
    # input is the dict passed to Send, NOT the main state
    summary = llm.invoke(f"Summarize: {input['doc']}").content
    return {"summaries": [summary]}

builder = StateGraph(State)
builder.add_node("summarize", summarize)
builder.add_conditional_edges(START, fan_out, ["summarize"])
builder.add_edge("summarize", END)
graph = builder.compile()
```

Key properties:
- The number of `Send`s is decided at runtime.
- Each `Send` carries its own input state — distinct from the main graph state.
- Each invocation runs in its own task; outputs merge back through the main state's
  reducers.

---

## 3. The `Send` input state

The input dict you pass to `Send(node, input)` is what the target node receives as its
`state` argument. It does **not** need to match the main graph's `State` schema. The target
node returns updates that DO match the main graph's `State` (those updates go through the
main state's reducers).

```python
def fan_out(state: State) -> list[Send]:
    return [
        Send("worker", {"task_id": i, "payload": x})  # custom shape
        for i, x in enumerate(state["items"])
    ]

def worker(input: dict) -> dict:
    # input["task_id"], input["payload"] — what we sent
    return {"results": [process(input["payload"])]}  # main state shape
```

---

## 4. Convergence — joining parallel branches

When parallel branches all have edges to the same next node, that node runs only after all
branches complete. The next node sees the accumulated state.

```python
builder.add_conditional_edges(START, fan_out, ["summarize"])
builder.add_edge("summarize", "aggregate")  # runs once after ALL summarize tasks
```

But there's a subtle bug here: if `aggregate` is reached via a regular edge, it might be
scheduled in the superstep after the first summarize completes — before others finish.

For **deferred execution** (wait for ALL parallel work), use `defer`:

---

## 5. Defer — explicit synchronization

```python
builder.add_node("aggregate", aggregate, defer=True)
```

A `defer=True` node waits until no other node in the graph is currently scheduled. Use it
when:
- Parallel branches have different lengths (some take longer than others).
- You need every branch to finish before aggregating.

Without `defer`, the aggregator might be invoked multiple times if branches complete in
different supersteps.

---

## 6. Transactional supersteps

All updates from one superstep are committed atomically. If any node in the superstep
raises:
- None of the updates are applied.
- The run halts (or interrupts, depending on configuration).

This protects state consistency. For agents doing destructive operations across parallel
branches, this transactional guarantee means a partial-failure leaves no half-applied state.

---

## 7. Limits

- `Send` works inside a conditional edge function. You can't return `Send` from a node's
  body — use `Command(send=[Send(...)])` if you need to combine state updates with sends.
- Recursion limit applies to total supersteps, not per-branch.
- LLM/API rate limits aren't per-graph — if you fan out 100 LLM calls, you might trip the
  provider's rate limit. Add a semaphore in the node body or throttle upstream.

---

## 8. Map-reduce template

```python
from typing import Annotated, TypedDict
from operator import add
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

class State(TypedDict):
    items: list[str]
    processed: Annotated[list[str], add]
    final: str

def fan_out(state: State) -> list[Send]:
    return [Send("worker", {"item": item}) for item in state["items"]]

def worker(input: dict) -> dict:
    return {"processed": [do_work(input["item"])]}

def reduce(state: State) -> dict:
    return {"final": "\n".join(state["processed"])}

builder = StateGraph(State)
builder.add_node("worker", worker)
builder.add_node("reduce", reduce, defer=True)   # wait for all workers
builder.add_conditional_edges(START, fan_out, ["worker"])
builder.add_edge("worker", "reduce")
builder.add_edge("reduce", END)
graph = builder.compile()
```

---

## 9. When NOT to fan out

- When you need ordered results and care about the order — use sequential nodes or sort
  after.
- When each branch is cheap (LLM calls measured in ms): the orchestration overhead can
  exceed the parallelism gain.
- When branches share an expensive external resource (DB connection, rate-limited API):
  parallelism just contends.
