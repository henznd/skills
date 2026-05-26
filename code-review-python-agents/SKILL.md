---
name: code-review-python-agents
description: |
  Comprehensive code review skill for Python AI agent projects built with LangGraph 1.0,
  LangChain 1.0, and FastMCP. Covers the high-leverage failure modes specific to agentic
  systems: state mutation bugs, checkpointer misuse, broken conditional edges, leaky tool
  schemas, prompt injection, unbounded loops, async/streaming pitfalls, and MCP server
  security. Use when: reviewing a PR or branch on an agent codebase, auditing a LangGraph
  graph definition, reviewing FastMCP tool exposures, checking checkpoint/thread handling,
  reviewing tool design, or before promoting an agent to production. Triggers on phrases
  like "review my agent", "review this graph", "audit my MCP server", "check my LangGraph
  code", "review this tool", "PR review for agent code", or any code-review task on a
  Python repo that imports `langgraph`, `langchain`, `langchain_*`, `fastmcp`, or `mcp`.
allowed-tools: Read, Grep, Glob, Bash, WebFetch
---

# Code Review — Python Agents (LangGraph 1.0 / LangChain 1.0 / FastMCP)

> Transform code review on agent codebases from generic Python feedback into **targeted,
> framework-aware analysis** that catches the bugs that actually break agents in production.

This skill is **not** a generic Python review skill. It assumes:
- The codebase is a Python AI agent or MCP server.
- It uses **LangGraph 1.0** (`langgraph >= 1.0`, October 2025+).
- It uses **LangChain 1.0** abstractions where applicable (`create_agent`, middleware,
  content blocks).
- MCP servers/clients use **FastMCP** (`fastmcp` package, the PrefectHQ-maintained one,
  also embedded in the official `mcp` SDK).

If the codebase is on pre-1.0 LangGraph/LangChain, **flag this immediately** in the review
summary — many recommendations below assume 1.0 APIs.

---

## When to Use This Skill

- Reviewing a PR that touches a graph definition, tool, prompt template, or MCP server.
- Auditing an existing agent codebase before going to production.
- Reviewing checkpointer/persistence integration (Postgres, Redis, in-memory).
- Reviewing structured-output handlers, tool schemas, or middleware.
- Reviewing async/streaming code paths in agents.
- Reviewing how secrets, API keys, or user data flow through prompts and tools.
- Onboarding to a teammate's agent codebase and wanting a structured first pass.

---

## How to Run a Review

The skill works in **four phases**. Do not skip phases — agentic bugs hide in the
interaction between phases.

```
Phase 1 — Context & inventory       (5 min)
        |
        v
Phase 2 — Graph / agent architecture review (10–15 min)
        |
        v
Phase 3 — Line-by-line on hot files (15–30 min)
        |  load reference/*.md as needed
        v
Phase 4 — Summary, severity, action items (5 min)
```

### Phase 1 — Context & inventory

Before reading any code, build a map:

1. **Identify framework versions.** Run `grep -E "langgraph|langchain|fastmcp|mcp" pyproject.toml requirements*.txt uv.lock poetry.lock 2>/dev/null`. Confirm:
   - `langgraph >= 1.0.0`
   - `langchain >= 1.0.0` (if used)
   - `fastmcp` version (2.x or 3.x — 3.0 was released Jan 2026 with breaking auth changes)
2. **Locate the entry points.** Find:
   - The graph definition(s): `grep -r "StateGraph\|create_agent\|create_react_agent" --include="*.py"`
   - MCP servers: `grep -r "FastMCP(" --include="*.py"`
   - Tool definitions: `grep -rn "@tool\|@mcp.tool" --include="*.py"`
   - Checkpointer setup: `grep -rn "Checkpointer\|MemorySaver\|InMemorySaver\|PostgresSaver\|RedisSaver" --include="*.py"`
3. **Note the State schema.** Read the `TypedDict` or Pydantic model passed to `StateGraph(...)`.
4. **Read the README** if present. Compare claimed behavior to graph topology.

### Phase 2 — Graph / agent architecture review

Walk the topology once, top-down:

- **Is there exactly one `START` edge?** Multiple `START`s are valid only as parallel fan-out and must converge.
- **Does every non-terminal node have an outgoing edge?** A node with no edge silently halts.
- **Are conditional edges total?** The router function must return a string that matches a registered key, or the graph raises at runtime, not at compile.
- **Is `END` reachable from every branch?** Including error paths.
- **Is there a cycle?** If yes, is there a `recursion_limit` or a guard counter in state?
- **Checkpointer + thread_id story.** If a checkpointer is configured, every invocation must pass `config={"configurable": {"thread_id": ...}}`. Missing thread_id with checkpointer is silently broken (writes nowhere useful).
- **Is the agent prebuilt (`create_agent` / `create_react_agent`) wrapped in a larger StateGraph?** That's a valid LangChain 1.0 pattern but verify middleware is set on the inner agent, not the outer graph.

If significant architectural concerns surface, **load `reference/langgraph-review.md`** for the
deep checklist.

### Phase 3 — Line-by-line on hot files

For each file, walk the relevant reference guide:

| What you're reading | Load this reference |
|---|---|
| `graph.py`, `*_graph.py`, anything with `StateGraph` / `add_node` / `add_edge` | [`reference/langgraph-review.md`](reference/langgraph-review.md) |
| `agent.py`, files with `create_agent` / `create_react_agent` | [`reference/agent-architecture-review.md`](reference/agent-architecture-review.md) |
| `tools/*.py`, `@tool`-decorated functions, tool input schemas | [`reference/tools-and-prompts-review.md`](reference/tools-and-prompts-review.md) |
| `server.py`, `*_mcp.py`, anything with `FastMCP(` / `@mcp.tool` / `@mcp.resource` | [`reference/fastmcp-review.md`](reference/fastmcp-review.md) |
| `client.py`, code that connects to MCP servers (`MultiServerMCPClient`, `langchain_mcp_adapters`) | [`reference/mcp-client-review.md`](reference/mcp-client-review.md) |
| Async code, `astream`, `astream_events`, `aget_state` | [`reference/async-and-streaming-review.md`](reference/async-and-streaming-review.md) |
| Test files, `pytest`, fixtures, mocks for LLMs/tools | [`reference/testing-and-observability-review.md`](reference/testing-and-observability-review.md) |
| Anything touching prompts, user input, or external data | [`reference/security-review.md`](reference/security-review.md) |
| Generic Python (typing, exceptions, async patterns) | [`reference/python-base-review.md`](reference/python-base-review.md) |

### Phase 4 — Summary & decision

Produce a markdown summary using [`assets/pr-review-template.md`](assets/pr-review-template.md).
Include:
- Severity-labeled findings (see below)
- Concrete suggested patches for `blocking` findings
- A clear merge decision: ✅ Approve / 💬 Comment / 🔄 Request Changes

---

## Severity Labels

Use these exact tags in every finding. They are the same as the upstream code-review-skill
so reviewers familiar with that skill have zero ramp-up:

| Tag | Meaning | When to use |
|---|---|---|
| 🔴 `[blocking]` | Must fix before merge | Correctness bug, security issue, will break in prod |
| 🟠 `[important]` | Should fix; merge only if author justifies | Footgun, missing test for risky path, performance cliff |
| 🟡 `[nit]` | Style / minor preference | Naming, docstring polish, idiom |
| 🔵 `[suggestion]` | Optional alternative | "Could use middleware here" |
| 📚 `[learning]` | Educational note, no action required | Link to docs, explain a subtle behavior |
| 🌟 `[praise]` | Explicitly highlight good work | Clean state schema, good test, thoughtful naming |

**Hard rule:** every finding has exactly one severity tag. No tag = the comment is invisible
to skim-readers.

---

## Review Style

Always:
- **Ask, don't command** for non-`[blocking]` items. "What happens if `messages` is empty
  here?" reads better than "You need a guard."
- **Quote the line you're commenting on** (`file.py:42`). Reviews without anchors are
  unreadable.
- **Suggest a patch** for every `[blocking]`. If you can't write the patch, the finding
  probably isn't `[blocking]`.
- **Distinguish what the linter catches** (ruff, mypy, pyright) from what only a human can
  catch. Don't waste review bandwidth on `ruff`-fixable issues — flag them once globally:
  "Repo would benefit from ruff + pyright in CI."
- **Be concrete about the failure mode**, not the rule. "This will deadlock if two threads
  hit the same `thread_id` simultaneously" beats "Use proper concurrency."

Never:
- Rewrite to your personal style.
- Block on bikeshed-tier preferences.
- Pile on after the issue is already raised by another reviewer.

---

## The Big Six — Issues to Always Check For

These are the failures we see most often on LangGraph 1.0 / FastMCP codebases. Treat this as
a checklist on every review:

1. **State mutation outside a node's return value.** Nodes must return a dict of updates,
   not mutate `state` in place. Reducers (`add_messages`, custom) only run on returns.
2. **Missing `thread_id` when a checkpointer is configured.** Checkpointer + no thread_id =
   silent statelessness.
3. **Conditional edge router that can return an unmapped key.** Causes a runtime crash deep
   in production, not at compile.
4. **Unbounded recursion** in an agent loop without a `recursion_limit` or a state-based
   counter.
5. **Tools that swallow exceptions and return a string error**, which the LLM then sees as
   "success" and keeps going. Either re-raise or return a clearly-prefixed `ERROR:` string
   the prompt teaches the model to recognize.
6. **FastMCP tools without input validation or auth**, especially when exposed over
   Streamable HTTP. The November 2025 MCP spec mandates OAuth 2.1 for public servers.

Each of these has a dedicated section in its reference file with code patterns and patches.

---

## Reference Files

The deep content lives in `reference/`. Load on demand:

- [`reference/langgraph-review.md`](reference/langgraph-review.md) — State, nodes, edges, checkpointers, interrupts, Command, recursion.
- [`reference/agent-architecture-review.md`](reference/agent-architecture-review.md) — `create_agent`, middleware, tool binding, structured output, system prompts.
- [`reference/tools-and-prompts-review.md`](reference/tools-and-prompts-review.md) — Tool schemas, docstrings as prompts, prompt templates, prompt injection surface.
- [`reference/fastmcp-review.md`](reference/fastmcp-review.md) — FastMCP server design, transports, auth (Bearer/OAuth 2.1), elicitation, output schemas.
- [`reference/mcp-client-review.md`](reference/mcp-client-review.md) — `langchain-mcp-adapters`, `MultiServerMCPClient`, connection lifecycle, tool name collisions.
- [`reference/async-and-streaming-review.md`](reference/async-and-streaming-review.md) — `ainvoke` vs `invoke`, `astream`/`astream_events`, blocking-in-async traps.
- [`reference/testing-and-observability-review.md`](reference/testing-and-observability-review.md) — pytest patterns, LLM mocking, LangSmith tracing, eval datasets.
- [`reference/security-review.md`](reference/security-review.md) — Secrets handling, prompt injection, tool-call gating, PII redaction middleware.
- [`reference/python-base-review.md`](reference/python-base-review.md) — Mutable defaults, typing, exception hygiene, dataclass vs Pydantic.

## Assets

- [`assets/pr-review-template.md`](assets/pr-review-template.md) — Copy-paste PR summary template.
- [`assets/quick-checklist.md`](assets/quick-checklist.md) — One-page printable checklist.

---

## Companion Skill

For framework knowledge the reviewing agent may not have access to (API signatures, current
patterns, common idioms), use the companion skill **`langgraph-langchain-knowledge`**. Load
it when you need to verify whether a pattern in the PR matches current LangGraph 1.0 /
LangChain 1.0 / FastMCP idioms.
