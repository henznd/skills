# Testing — pytest, Fake Models, Topology Tests

> How to test LangGraph / LangChain code without hitting real APIs and without flakiness.

---

## 1. Setup

```bash
pip install pytest pytest-asyncio
```

`pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
```

With `asyncio_mode = auto`, every `async def test_*` function is auto-marked, no decorator
needed.

---

## 2. Mocking the LLM — the right way

### `GenericFakeChatModel`

Best for happy-path tests where you script exact AIMessages including tool calls.

```python
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

fake = GenericFakeChatModel(messages=iter([
    AIMessage(content="", tool_calls=[
        {"name": "search", "args": {"q": "python"}, "id": "1"},
    ]),
    AIMessage(content="Here are the results: ..."),
]))

agent = create_agent(model=fake, tools=[search])
result = await agent.ainvoke({"messages": [HumanMessage("find python")]})
```

Each `.invoke` consumes one element from the iterator. Useful for asserting "agent calls
tool X then responds with Y".

### `FakeListChatModel`

Simpler — scripts string responses only.

```python
from langchain_core.language_models.fake_chat_models import FakeListChatModel

fake = FakeListChatModel(responses=["hello", "goodbye"])
```

No tool-call support; use when testing chains without tools.

### Don't use `MagicMock` as the model

`MagicMock` doesn't honor `BaseChatModel`'s interface (returning `BaseMessage`,
`bind_tools`, etc.). Tests pass but the harness doesn't reflect real behavior.

---

## 3. Mocking tools

### `monkeypatch` the underlying function

```python
def test_search_tool(monkeypatch):
    def fake_search(q, top_k):
        return [f"result for {q}"]
    monkeypatch.setattr("myapp.tools._do_search", fake_search)

    result = search.invoke({"query": "python"})
    assert result == ["result for python"]
```

### Replace tools in the agent

```python
def test_agent_handles_tool_error():
    @tool
    def broken_search(q: str) -> str:
        """Search."""
        raise RuntimeError("upstream down")

    agent = create_agent(model=fake_model, tools=[broken_search])
    result = agent.invoke({"messages": [HumanMessage("find x")]})
    # assert agent recovered or terminated cleanly
```

---

## 4. Topology tests

Compile the graph and assert structure:

```python
def test_graph_has_expected_nodes():
    compiled = build_graph()
    nodes = set(compiled.get_graph().nodes)
    assert "classify" in nodes
    assert "retrieve" in nodes
    assert "generate" in nodes

def test_graph_has_expected_edges():
    compiled = build_graph()
    mermaid = compiled.get_graph().draw_mermaid()
    assert "classify --> retrieve" in mermaid
    assert "generate --> __end__" in mermaid
```

Cheap to run; catches "I deleted an edge during refactor" before integration tests do.

---

## 5. State assertions

```python
async def test_state_after_run():
    agent = create_agent(model=fake_model, tools=[search])
    result = await agent.ainvoke(
        {"messages": [HumanMessage("hi")]},
        config={"configurable": {"thread_id": "test"}},
    )

    assert len(result["messages"]) >= 2
    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert "hello" in final.content.lower()
```

---

## 6. Testing interrupts and resume

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

async def test_hitl_approval():
    graph = build_graph_with_hitl().compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "test-hitl"}}

    # First invocation hits the interrupt
    result = await graph.ainvoke({"proposal": "delete logs"}, config=cfg)
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["question"] == "approve?"

    # Resume with approval
    final = await graph.ainvoke(Command(resume="yes"), config=cfg)
    assert final["approved"] is True

async def test_hitl_rejection():
    graph = build_graph_with_hitl().compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "test-hitl-2"}}

    await graph.ainvoke({"proposal": "delete logs"}, config=cfg)
    final = await graph.ainvoke(Command(resume="no"), config=cfg)
    assert final["approved"] is False
```

---

## 7. Async tests

```python
import pytest

@pytest.mark.asyncio
async def test_async_graph():
    graph = build_async_graph()
    result = await graph.ainvoke(
        {"messages": [HumanMessage("hi")]},
        config={"configurable": {"thread_id": "t1"}},
    )
    assert result is not None
```

With `asyncio_mode = auto` you can drop the marker.

---

## 8. Streaming tests

```python
async def test_streaming():
    agent = create_agent(model=fake_model, tools=[])
    events = []
    async for event in agent.astream(
        {"messages": [HumanMessage("hi")]},
        config={"configurable": {"thread_id": "t1"}},
        stream_mode="updates",
    ):
        events.append(event)

    assert len(events) >= 1
    assert any("agent" in event for event in events)
```

---

## 9. Checkpointer in tests

Use `InMemorySaver` (or its async counterpart). Don't hit a real Postgres in CI unless
you have a Docker fixture.

```python
@pytest.fixture
def graph():
    return build_graph().compile(checkpointer=InMemorySaver())
```

---

## 10. LangSmith in tests

Disable tracing in tests to avoid noise:

```python
# conftest.py
import os

@pytest.fixture(autouse=True)
def disable_langsmith(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
```

Or set a separate test project:

```python
monkeypatch.setenv("LANGSMITH_PROJECT", "ci-tests")
```

---

## 11. Evals (LangSmith datasets)

For prompt-sensitive logic, regression-test with a dataset:

```python
from langsmith import Client

client = Client()
dataset = client.read_dataset(dataset_name="agent-regressions")

def run_agent(inputs: dict) -> dict:
    result = agent.invoke(
        {"messages": [HumanMessage(inputs["query"])]},
        config={"configurable": {"thread_id": "eval"}},
    )
    return {"answer": result["messages"][-1].content}

def correctness_eval(run, example) -> dict:
    expected = example.outputs["expected"]
    actual = run.outputs["answer"]
    # ...your scoring logic, possibly LLM-as-judge
    return {"key": "correctness", "score": 1.0 if expected in actual else 0.0}

client.evaluate(
    run_agent,
    data=dataset,
    evaluators=[correctness_eval],
    experiment_prefix="pr-123",
)
```

Run on every PR that touches prompts.

---

## 12. The test pyramid for agents

```
                       ┌─────────────────┐
                       │  Eval datasets  │   slow, run on PR
                       │  (LangSmith)    │
                       └─────────────────┘
                  ┌───────────────────────────┐
                  │  Agent-level integration  │   ~50–200 tests
                  │  (FakeChatModel)          │
                  └───────────────────────────┘
              ┌─────────────────────────────────────┐
              │  Topology & node-level tests        │   ~100–500 tests
              └─────────────────────────────────────┘
          ┌───────────────────────────────────────────────┐
          │  Tool unit tests (pure Python)                │   ~all tools
          └───────────────────────────────────────────────┘
```

Aim for fast feedback at the bottom layers; reserve evals for the top.
