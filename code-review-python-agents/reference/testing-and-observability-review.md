# Testing & Observability — Code Review Reference

> For test files and observability setup. Agent codebases need a different testing strategy
> than typical Python apps.

---

## 1. The four test layers

A healthy agent project has roughly:

1. **Unit tests on tools.** Tools are plain Python functions — test them as such.
2. **Graph topology tests.** Compile the graph; assert nodes/edges; run with mocked LLM and
   mocked tools; assert the sequence of nodes hit.
3. **Agent-level tests with a fake model.** Use `langchain_core.language_models.fake.FakeListChatModel`
   or `GenericFakeChatModel` to script LLM outputs deterministically. Assert final state.
4. **Eval / regression tests.** LangSmith datasets + evaluators. Run on PRs that change
   prompts.

🟠 `[important]` PR with only layer 1, or only layer 4. The middle layers catch the bugs
production hits.

---

## 2. Mocking the LLM

✅ Deterministic pattern:

```python
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

fake_model = GenericFakeChatModel(messages=iter([
    AIMessage(content="", tool_calls=[{"name": "search", "args": {"q": "x"}, "id": "1"}]),
    AIMessage(content="Done."),
]))

agent = create_agent(model=fake_model, tools=[search])
result = agent.invoke({"messages": [HumanMessage("find x")]})
```

🔴 `[blocking]` Tests calling the real Anthropic/OpenAI API in CI without a budget guard
and without VCR-style recording. Flaky and expensive.

🟠 `[important]` Tests using `MagicMock` as the model. Doesn't honor message structure,
breaks on any real interaction.

---

## 3. Tool mocking

For tools that hit external services in tests:
- ✅ Override the tool's underlying function with `monkeypatch`.
- ✅ Or pass an alternate tool list to `create_agent` in tests.
- 🟠 `[important]` Mocking with `unittest.mock.patch("module.requests")` while the tool uses
  `httpx` — silent no-op.

---

## 4. Graph topology assertions

```python
def test_graph_topology():
    compiled = build_graph()
    assert set(compiled.nodes) == {"classify", "retrieve", "generate", "__start__", "__end__"}
    # Or use the visualization API:
    drawn = compiled.get_graph().draw_mermaid()
    assert "classify --> retrieve" in drawn
```

🌟 `[praise]` when you see this. It catches "I refactored and accidentally removed an edge"
during reviews.

---

## 5. Checkpointer in tests

Use `InMemorySaver` in tests, `AsyncInMemorySaver` for async. Both ship with langgraph.

🟠 `[important]` Tests using `PostgresSaver` with a real DB unless you have a CI container.
Slow and flaky.

```python
from langgraph.checkpoint.memory import InMemorySaver

def test_interrupt_resume():
    graph = builder.compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "test-1"}}
    result = graph.invoke({"messages": [...]}, config=cfg)
    assert "__interrupt__" in result
    final = graph.invoke(Command(resume="yes"), config=cfg)
    assert final["status"] == "approved"
```

---

## 6. LangSmith tracing

If the project uses `langsmith`:

- 🟠 `[important]` `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in repo or CI logs.
- 🟠 `[important]` Tracing enabled in tests, which floods the project with noise. Tag test
  traces with a `project=test-...` or disable in pytest.
- 🌟 `[praise]` Custom run names via `RunnableConfig(run_name=...)` — makes the trace
  readable.

### 6.1 PII in traces

🔴 `[blocking]` Production tracing on with no redaction, and prompts/tools see PII. Use
LangSmith's hide-inputs/outputs config or redact in middleware before the LLM call.

---

## 7. Eval datasets

For agents whose behavior matters (which is most of them):

- ✅ A LangSmith dataset of representative inputs + expected outputs / behaviors.
- ✅ An evaluator that runs on every PR that changes prompts or model.
- 🟠 `[important]` Eval threshold is a "score >= 0.X" without baseline — passes the first
  time, fails after every prompt tweak with no signal of regression vs. drift.

---

## 8. Things to specifically test for agents

- Empty input (`messages=[]`) — should fail cleanly, not infinite-loop.
- A tool that times out — agent should not retry forever.
- A tool that returns an error string — agent should react, not loop.
- `recursion_limit` exceeded path — verify the user-visible error is graceful.
- Interrupt + resume cycle for every HITL tool.
- Concurrent invocations on different `thread_id` (state isolation).

🟠 `[important]` PR adds new tool with HITL and no resume test.

---

## 9. Coverage isn't the metric

Coverage % on agent code is a vanity metric — 100% line coverage with no behavioral
assertions is meaningless. Prefer:

- Number of distinct **agent trajectories** asserted (which sequences of nodes hit).
- Number of **failure modes** under test (tool error, LLM timeout, interrupt, recursion).
- Eval suite pass rate on a held-out set.

---

## 10. The test review checklist

- [ ] At least one test compiles and runs the full graph end-to-end.
- [ ] Tool tests don't hit real services in CI.
- [ ] LLM mocked with `GenericFakeChatModel` or equivalent, not `MagicMock`.
- [ ] Async paths tested with `pytest-asyncio` and `Async*Saver`.
- [ ] HITL paths have an interrupt+resume test.
- [ ] LangSmith tracing not blasting prod project from CI.
- [ ] No real API keys in test fixtures.
