# Quick Checklist — Python Agent PR Review

> One-page printable reference. Walk top to bottom.

## State & Graph (LangGraph)

- [ ] State is a `TypedDict` or Pydantic `BaseModel`, not bare `dict`
- [ ] Accumulating fields have reducers (`Annotated[list[...], add_messages]`)
- [ ] No mutation of `state` in nodes — return dict of updates
- [ ] Every non-terminal node has an outgoing edge
- [ ] Conditional edge router covers all cases or returns `END`
- [ ] `START` and `END` are both reachable
- [ ] Cycles have `recursion_limit` set or a state-based counter
- [ ] `Command(goto=...)` only references registered nodes

## Checkpointer & Persistence

- [ ] `InMemorySaver` only in tests/dev
- [ ] Async graph → `Async*Saver`
- [ ] `thread_id` passed in every `.invoke` / `.stream` / `.ainvoke` / `.astream`
- [ ] `thread_id` is scoped per-user, not user-controllable raw

## Interrupts / HITL

- [ ] HITL uses dynamic `interrupt()` not deprecated `interrupt_before` for production
- [ ] HITL graphs have a checkpointer
- [ ] Stream consumers handle the `__interrupt__` key

## Agent (`create_agent`)

- [ ] `tools=` always passed (required in 1.0)
- [ ] Model string version-pinned
- [ ] System prompt doesn't include user-controlled text
- [ ] Dynamic prompt logic in middleware, not f-strings
- [ ] `response_format` validated in tests

## Middleware

- [ ] Middleware order intentional, documented if non-obvious
- [ ] Custom middleware is async if graph is async
- [ ] HITL middleware paired with checkpointer

## Tools

- [ ] One tool = one capability
- [ ] Pydantic schema (or rich type hints) for non-trivial inputs
- [ ] Docstring reads as a prompt to the LLM
- [ ] Error handling: pick one pattern (raise / `ERROR:` string / structured), don't mix
- [ ] Mutating tools idempotent OR gated by HITL
- [ ] Identity (`user_id`) injected from state, never from LLM args

## FastMCP

- [ ] Type hints + docstrings on every `@mcp.tool`
- [ ] `httpx.AsyncClient` has a timeout
- [ ] No `print()` (stdio corruption)
- [ ] Streamable HTTP transport has OAuth 2.1
- [ ] Tools don't raise raw exceptions across the boundary
- [ ] Resources don't expose paths outside an allowlist

## MCP Client

- [ ] Client built once at startup, not per-request
- [ ] Client closed on shutdown
- [ ] No tool name collisions across servers
- [ ] Tools allowlisted for prod, not auto-loaded

## Async & Streaming

- [ ] No `requests`, `time.sleep`, `psycopg2.*` in async nodes
- [ ] `astream_events(version="v2")` for new code
- [ ] No `MemorySaver` in async path (use `InMemorySaver` + async-compatible)
- [ ] `stream_mode` chosen intentionally (`updates` for UI delta, `messages` for tokens)

## Security

- [ ] No user-controlled text in system role
- [ ] No secrets in source / defaults / checkpoints
- [ ] Destructive tools (delete/send/charge) gated by HITL
- [ ] PII redacted before LangSmith / provider logs
- [ ] Endpoint auth ties thread_id to requesting user
- [ ] Rate limiting per user

## Tests

- [ ] LLM mocked with `GenericFakeChatModel`, not `MagicMock`
- [ ] No real API calls in CI
- [ ] HITL interrupt+resume test
- [ ] Topology test if graph changed

## Versions

- [ ] `langgraph`, `langchain`, `fastmcp` versions pinned
- [ ] `langgraph-prebuilt` pinned compatibly with `langgraph`
- [ ] Not on an alpha/beta in production code
