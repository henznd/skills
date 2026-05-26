# LangGraph Core — State, Nodes, Edges

> The Pregel-inspired primitives. Everything else (agents, HITL, parallelism) builds on
> these.

---

## 1. The execution model in 30 seconds

LangGraph executes in **supersteps**. Each superstep:

1. Runs all "active" nodes (started by the previous step) in parallel.
2. Collects each node's returned dict of updates.
3. Applies each update through the matching field's reducer.
4. Computes the next active set from edges + conditional edges.
5. If any node in the superstep raised, the entire superstep's updates are discarded
   (transactional). Then the run halts (or interrupt-resumes on retry, depending on
   configuration).

Active node count is dynamic — `Send` (see `parallelism.md`) lets a routing function spawn
arbitrarily many sibling tasks at runtime.

---

## 2. State

### TypedDict style

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    retries: int
```

- Returning `{}` from a node = no change.
- Returning `{"retries": 1}` overwrites `retries` (no reducer → default = overwrite).
- Returning `{"messages": [new_msg]}` appends (via `add_messages` reducer).

### Pydantic style (1.0+)

```python
from pydantic import BaseModel
from typing import Annotated
from langgraph.graph.message import add_messages

class State(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = []
    user_id: str = ""
    retries: int = 0
```

Use Pydantic when you want validation on state. Use TypedDict when you want zero runtime
overhead and full flexibility.

### Reducers — built-in

```python
from operator import add
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]  # smart append, dedupe by id
    docs: Annotated[list[Document], add]                 # naive list concat
    counter: int                                          # default: overwrite
```

`add_messages` is special: it deduplicates by message `.id`, so replaying a node doesn't
double-insert. Generic `operator.add` does not — be careful with replay.

### Custom reducer

```python
def merge_dicts(left: dict | None, right: dict) -> dict:
    return {**(left or {}), **right}

class State(TypedDict):
    config: Annotated[dict, merge_dicts]
```

Pure function: don't mutate `left` or `right`, return a new value.

---

## 3. Nodes

A node is a callable: `state → dict_of_updates` (or `Command`).

```python
def my_node(state: State) -> dict:
    last = state["messages"][-1]
    return {"messages": [AIMessage(f"You said: {last.content}")]}
```

Async:

```python
async def my_node(state: State) -> dict:
    response = await model.ainvoke(state["messages"])
    return {"messages": [response]}
```

Returning `Command`:

```python
def my_node(state) -> Command:
    return Command(
        goto="next_node",
        update={"counter": state["counter"] + 1},
    )
```

`Command` lets you set state AND route in one return. Useful inside conditional logic where
the routing decision depends on what you just computed.

---

## 4. Edges

### Static

```python
builder.add_edge(START, "first")
builder.add_edge("first", "second")
builder.add_edge("second", END)
```

### Conditional

```python
def route(state) -> Literal["tools", "end"]:
    if state.get("tool_calls"):
        return "tools"
    return "end"

builder.add_conditional_edges(
    "agent",
    route,
    {"tools": "tools_node", "end": END},
)
```

Or return `END` directly from the router:

```python
def route(state):
    if state.get("tool_calls"):
        return "tools_node"
    return END

builder.add_conditional_edges("agent", route)
```

### Multiple destinations (fan-out, static)

```python
builder.add_edge("planner", "worker_a")
builder.add_edge("planner", "worker_b")
# Both worker_a and worker_b run in parallel in the next superstep.
```

For dynamic fan-out, see `parallelism.md` (`Send`).

---

## 5. Compile

```python
graph = builder.compile(
    checkpointer=InMemorySaver(),           # see checkpointers.md
    interrupt_before=[],                    # debugging only — not for prod HITL
    interrupt_after=[],
)
```

Compile errors are eager: missing nodes, missing edges, unreachable START, etc., fail here
rather than at runtime.

---

## 6. Invoke

```python
result = graph.invoke(
    {"messages": [HumanMessage("hi")]},
    config={"configurable": {"thread_id": "abc"}},
)
```

`result` is the final state.

If an `interrupt()` was hit, `result["__interrupt__"]` contains the interrupt payload
(LangGraph 0.4.0+).

Async equivalent: `await graph.ainvoke(...)`.

---

## 7. The `recursion_limit`

Default: 25 supersteps. Override:

```python
graph.invoke(
    state,
    config={
        "configurable": {"thread_id": "..."},
        "recursion_limit": 50,
    },
)
```

`GraphRecursionError` raises when exceeded. Catch it and surface gracefully:

```python
from langgraph.errors import GraphRecursionError

try:
    result = graph.invoke(...)
except GraphRecursionError:
    return {"error": "agent gave up after too many steps"}
```

---

## 8. Visualization

```python
print(graph.get_graph().draw_mermaid())
```

Or render an image (requires `pygraphviz` or the bundled mermaid renderer):

```python
graph.get_graph().draw_mermaid_png(output_file_path="graph.png")
```

Great for review and onboarding.

---

## 9. Subgraphs

A node can BE another compiled graph (or an agent built with `create_agent`).

```python
sub_builder = StateGraph(SubState)
# ... build ...
sub = sub_builder.compile()

main_builder = StateGraph(MainState)
main_builder.add_node("sub_step", sub)
```

State key mapping: if `SubState` and `MainState` share keys, they merge. To map:

```python
main_builder.add_node("sub_step", sub, input=..., output=...)
```

See `parallelism.md` for fan-out subgraphs.

---

## 10. The four things that catch beginners

1. **Forgetting the reducer.** Without `add_messages`, every node overwrites `messages`.
2. **Mutating state in place.** Don't do `state["x"].append(y)`. Return `{"x": [y]}` (with
   a list reducer) or `{"x": state["x"] + [y]}` (no reducer).
3. **Missing `thread_id` with a checkpointer.** Silent statelessness.
4. **Conditional router returns a string not in the mapping dict.** Runtime crash, not
   compile-time.
