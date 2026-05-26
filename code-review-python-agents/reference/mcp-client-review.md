# MCP Client Integration — Code Review Reference

> For code that consumes MCP servers from a LangChain/LangGraph agent, typically via
> `langchain-mcp-adapters`.

---

## 1. The standard pattern

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "weather": {
        "url": "http://localhost:8000/mcp",
        "transport": "streamable_http",
    },
    "math": {
        "command": "python",
        "args": ["./math_server.py"],
        "transport": "stdio",
    },
})

tools = await client.get_tools()

agent = create_agent(model="claude-sonnet-4-6", tools=tools)
```

---

## 2. Connection lifecycle

### 2.1 Don't create the client per-request

🔴 `[blocking]` `MultiServerMCPClient` instantiated inside a request handler — opens a new
process / HTTP connection per request. Latency and resource leak.

✅ Build once at startup, share across requests. Use FastAPI's `lifespan` or equivalent.

### 2.2 Close the client on shutdown

🟠 `[important]` No `await client.close()` (or context manager) on shutdown. stdio child
processes survive as zombies.

```python
async with MultiServerMCPClient(...) as client:
    tools = await client.get_tools()
    ...
```

### 2.3 Reconnection / retry

🟠 `[important]` No retry on transient MCP server failures (network blip, server restart).
The agent will surface "tool unavailable" to the user mid-task.

Wrap tool calls in middleware that retries with backoff on transport errors only (NOT on
tool-logic errors).

---

## 3. Tool name collisions

### 3.1 Two servers, same tool name

🔴 `[blocking]` Server `weather` and server `forecast` both expose a `get_temperature` tool.
`get_tools()` returns both; one shadows the other.

Fix: namespace via the client (some versions of `langchain-mcp-adapters` support a prefix
parameter), or rename in the server.

### 3.2 Tool name collision with locally-defined `@tool`

Same problem, harder to spot. Grep for tool names that appear both in
`@tool`-decorated functions and in connected MCP servers.

---

## 4. Schema trust

MCP tools advertise their JSON schema. `langchain-mcp-adapters` passes that through to the
LLM. **The schema can lie.**

🟠 `[important]` Critical agent (e.g. handling payments) consuming tools from a server you
don't control without:
- An allowlist of accepted tool names.
- A wrapper that validates inputs/outputs against your own schema.

🔴 `[blocking]` Auto-binding ALL tools from a remote MCP server into a production agent.
Use an explicit list.

```python
# ❌
tools = await client.get_tools()

# ✅
all_tools = await client.get_tools()
ALLOWED = {"weather.get_temperature", "weather.get_forecast"}
tools = [t for t in all_tools if t.name in ALLOWED]
```

---

## 5. Auth tokens

### 5.1 Per-user vs per-app tokens

If the MCP server requires OAuth and your agent serves multiple users, the access token
should typically be **per user**, not a single service token. Verify the client config
isn't using a shared admin token by default.

🔴 `[blocking]` Long-lived admin token in the MCP client config, shared across all user
sessions.

### 5.2 Token refresh

🟠 `[important]` No refresh-token flow. Tokens expire mid-conversation, agent breaks.

---

## 6. Transport-specific notes

### 6.1 stdio

- 🟠 `[important]` `command="python"` with a relative `args=["./server.py"]` path. Breaks
  when the working directory changes. Use an absolute path or a console-script entry point.
- 🟠 `[important]` No `cwd` or `env` controlled — child inherits the parent's full env,
  including secrets the server doesn't need.

### 6.2 Streamable HTTP

- 🟠 `[important]` HTTP without TLS in production (`http://` vs `https://`).
- 🟠 `[important]` No request timeout on the client side. Hung server = hung agent.

### 6.3 SSE (legacy)

- 🟡 `[nit]` New code on SSE — prefer Streamable HTTP.

---

## 7. Error surface

MCP tool errors arrive as `ToolMessage(status="error")`. The agent's system prompt should
say how to react. If it doesn't:

🟠 `[important]` Agent gets a tool error, retries the same call with the same args. Infinite
loop. Either:
- Teach the agent to vary arguments.
- Add a counter in state.
- Use middleware that detects repeat-same-call patterns and breaks.

---

## 8. Quick MCP-client review pass

- [ ] Client built once, not per-request.
- [ ] Client closed on shutdown.
- [ ] No tool name collisions across connected servers.
- [ ] Tools allowlisted for production agents (not auto-loaded).
- [ ] Tokens per-user if relevant; refresh flow handled.
- [ ] All HTTP transports use TLS in prod.
- [ ] Timeouts and retries on transport errors only.
