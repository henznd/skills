---
name: langgraph-langchain-knowledge
description: |
  Compact, up-to-date knowledge base on LangGraph 1.0, LangChain 1.0, and FastMCP for an
  agent that doesn't have web access to the official docs. Use this skill whenever you need
  to write or reason about code that imports `langgraph`, `langchain`, `langchain_core`,
  `langchain_*` provider packages, `langgraph.checkpoint.*`, `fastmcp`, `mcp.server.fastmcp`,
  or `langchain_mcp_adapters`. Triggers on: implementing a `StateGraph`, building an agent
  with `create_agent`, designing custom middleware, configuring checkpointers, writing
  human-in-the-loop interrupts, using `Send` / `Command` primitives, building a FastMCP
  server, connecting an agent to MCP tools, or debugging any of the above. Load specific
  reference modules from `reference/` on demand — do not load everything at once.
allowed-tools: Read, Grep, Glob
---

# LangGraph 1.0 / LangChain 1.0 / FastMCP — Knowledge Base

> This is a **reference** skill. It exists because the coding agent doesn't have internet
> access to fetch docs. Everything here is current as of late 2025 / early 2026: LangGraph
> 1.0 (October 2025), LangChain 1.0 (October 2025), FastMCP 2.10+ / 3.0 (January 2026).

This skill is the companion to `code-review-python-agents`. The code-review skill catches
bugs; this skill helps you write correct code in the first place.

---

## Versions covered

| Package | Version covered | Notes |
|---|---|---|
| `langgraph` | 1.0.x – 1.1.x | Zero breaking changes between 0.x and 1.0; 1.0 stabilizes the runtime |
| `langchain` | 1.0.x – 1.2.x | Introduces `create_agent`, middleware, content blocks |
| `langchain-core` | 1.0+ | New `.content_blocks` property on messages |
| `langgraph-prebuilt` | 1.0.x – 1.1.x | Contains `create_react_agent` (legacy name still works) |
| `langgraph-checkpoint` | 2.x | Includes `InMemorySaver`, `Postgres*Saver`, `Sqlite*Saver` |
| `langchain-mcp-adapters` | 0.x | Glue between MCP and LangChain tools |
| `fastmcp` | 2.10+ recommended, 3.0 for new projects | Note: 3.0 changed auth |
| `mcp` (official SDK) | 1.x | Embeds an older FastMCP 1.x; for new code prefer the standalone `fastmcp` |

---

## How to use this skill

1. **Always start with `reference/cheatsheet.md`.** It's a one-page summary of the most
   common imports, signatures, and patterns. Most simple questions are answered there.
2. **For deep dives, load the specific module:**

   | Topic | File |
   |---|---|
   | State, nodes, edges, reducers, START/END | [`reference/langgraph-core.md`](reference/langgraph-core.md) |
   | Checkpointers (Postgres, Redis, SQLite, In-memory) | [`reference/checkpointers.md`](reference/checkpointers.md) |
   | `interrupt()`, `Command`, HITL | [`reference/interrupts-and-hitl.md`](reference/interrupts-and-hitl.md) |
   | `Send`, parallel branches, map-reduce, defer | [`reference/parallelism.md`](reference/parallelism.md) |
   | `create_agent`, middleware, structured output | [`reference/langchain-agents.md`](reference/langchain-agents.md) |
   | Messages, content blocks, providers | [`reference/messages-and-models.md`](reference/messages-and-models.md) |
   | Tools (`@tool`, `BaseTool`, `InjectedState`) | [`reference/tools.md`](reference/tools.md) |
   | Streaming (`astream`, `astream_events`, modes) | [`reference/streaming.md`](reference/streaming.md) |
   | FastMCP server | [`reference/fastmcp-server.md`](reference/fastmcp-server.md) |
   | MCP client (`langchain-mcp-adapters`) | [`reference/mcp-client.md`](reference/mcp-client.md) |
   | Testing patterns | [`reference/testing.md`](reference/testing.md) |

3. **For copy-pasteable starting points, see `examples/`:**

   | Example | File |
   |---|---|
   | Minimal ReAct agent | [`examples/minimal-react-agent.py`](examples/minimal-react-agent.py) |
   | Custom StateGraph with conditional routing | [`examples/custom-stategraph.py`](examples/custom-stategraph.py) |
   | HITL approval flow with `interrupt()` | [`examples/hitl-approval.py`](examples/hitl-approval.py) |
   | Map-reduce with `Send` | [`examples/map-reduce-send.py`](examples/map-reduce-send.py) |
   | FastMCP server (stdio + Streamable HTTP) | [`examples/fastmcp-server.py`](examples/fastmcp-server.py) |
   | LangChain agent consuming MCP servers | [`examples/agent-with-mcp.py`](examples/agent-with-mcp.py) |

---

## What changed in 1.0 that breaks old assumptions

If your training data is from before October 2025, the most important deltas:

1. **`create_agent` is the new high-level API.** It lives in `langchain.agents`, not
   `langgraph.prebuilt`. The old `create_react_agent` still works (in `langgraph-prebuilt`)
   but `create_agent` adds middleware, structured output, and provider-agnostic model strings.
2. **Middleware replaces dozens of constructor flags.** Things like HITL, summarization,
   PII redaction, retries, and custom hooks are now middleware objects passed to
   `create_agent(middleware=[...])`.
3. **`tools=` is required on `create_agent`,** even if empty. No more implicit defaults.
4. **Static interrupts (`interrupt_before` / `interrupt_after`) are deprecated for HITL.**
   Use the `interrupt()` function inside a node instead, plus `Command(resume=...)` to
   continue.
5. **Content blocks.** All message objects expose `.content_blocks` returning a typed,
   provider-agnostic representation. Multimodal, reasoning, citations, tool calls all
   have standard types.
6. **`InMemorySaver`** is the modern name; `MemorySaver` is the legacy alias.
7. **`__interrupt__` key** is now also returned from `invoke` / `ainvoke` (since 0.4.0), not
   only from streams.

---

## Heuristic: which framework piece do I want?

```
User wants to build...

  a chatbot or tool-calling agent
    └─→ create_agent (langchain.agents)

  a custom multi-step / multi-agent workflow
    └─→ StateGraph (langgraph.graph)

  parallel processing of N items (N unknown until runtime)
    └─→ StateGraph + Send  (see parallelism.md)

  an agent that pauses for human approval
    └─→ create_agent + HumanInTheLoopMiddleware + checkpointer
        OR  StateGraph + interrupt() + Command(resume=...)

  an MCP server exposing tools
    └─→ FastMCP (fastmcp package)

  an agent that uses MCP tools from other servers
    └─→ MultiServerMCPClient (langchain_mcp_adapters)

  durable, resumable agents
    └─→ any of the above + PostgresSaver / AsyncPostgresSaver
```

---

## Conventions used in this skill

- **Python 3.11+.** All examples use modern syntax (`X | None`, `match`, etc.).
- **Type hints everywhere.** They're not decorative — LangChain's tool/state machinery
  reads them.
- **Async-first.** Sync examples shown only where the sync API materially differs.
- **No deprecated APIs.** If a pattern was renamed or replaced in 1.0, only the new name
  appears.
- **Comments mark provider-specific bits.** If a snippet uses Anthropic, OpenAI is shown
  alongside or noted.
