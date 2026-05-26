# MCP Client — Consume MCP Servers from LangChain

> `langchain-mcp-adapters` bridges MCP tools into LangChain. You point at one or more MCP
> servers, get back a list of `BaseTool` instances, pass them to `create_agent` (or any
> graph that takes tools).

---

## 1. Install

```bash
pip install langchain-mcp-adapters
```

---

## 2. The MultiServerMCPClient

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "weather": {
        "url": "http://localhost:8000/mcp",
        "transport": "streamable_http",
    },
    "math": {
        "command": "python",
        "args": ["/abs/path/to/math_server.py"],
        "transport": "stdio",
    },
})

tools = await client.get_tools()
# Each tool is a langchain BaseTool, ready to bind to a model or agent.
```

---

## 3. Transport configurations

### stdio (local subprocess)

```python
"math": {
    "command": "python",
    "args": ["/abs/path/to/math_server.py"],
    "transport": "stdio",
    "env": {"PYTHONUNBUFFERED": "1"},  # optional
    "cwd": "/abs/path/to/working/dir",  # optional
}
```

Use absolute paths. Relative paths break when the parent process moves.

### Streamable HTTP (remote)

```python
"weather": {
    "url": "https://mcp.example.com/mcp",
    "transport": "streamable_http",
    "headers": {"Authorization": f"Bearer {token}"},
}
```

For OAuth-protected servers, your code is responsible for token acquisition and refresh.

### SSE (legacy)

```python
"legacy": {
    "url": "http://localhost:9000/sse",
    "transport": "sse",
}
```

Supported, but prefer `streamable_http` for new code.

---

## 4. Lifecycle

### Context manager (preferred)

```python
async with MultiServerMCPClient(config) as client:
    tools = await client.get_tools()
    agent = create_agent(model="...", tools=tools)
    result = await agent.ainvoke({"messages": [...]})
# Connections closed automatically.
```

### Manual lifecycle (for long-running servers)

```python
# At startup
client = MultiServerMCPClient(config)
await client.__aenter__()
tools = await client.get_tools()
# ... use across many requests ...

# At shutdown
await client.__aexit__(None, None, None)
```

For a FastAPI app, use `lifespan`:

```python
@asynccontextmanager
async def lifespan(app):
    async with MultiServerMCPClient(config) as client:
        app.state.mcp_tools = await client.get_tools()
        yield
```

---

## 5. Using the tools

```python
from langchain.agents import create_agent

agent = create_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=tools,                  # from client.get_tools()
)

result = await agent.ainvoke(
    {"messages": [HumanMessage("what's the weather in Paris?")]},
    config={"configurable": {"thread_id": "t1"}},
)
```

---

## 6. Filtering tools (allowlist)

For production, never auto-load all tools from a remote server you don't fully control:

```python
all_tools = await client.get_tools()
ALLOWED = {"get_weather", "get_forecast"}
tools = [t for t in all_tools if t.name in ALLOWED]
```

Or restrict by server:

```python
weather_tools = await client.get_tools(server_name="weather")
```

(API depends on adapter version — check `client.get_tools(...)` signature.)

---

## 7. Handling tool name collisions

If two servers both expose a tool called `search`, the second silently shadows the first
(or raises, version-dependent). Solutions:

- Rename in one of the servers.
- Use the adapter's prefix feature, if available:
  ```python
  client = MultiServerMCPClient({
      "weather": {"url": "...", "transport": "streamable_http", "prefix": "weather_"},
      "math":    {"command": "...", "transport": "stdio", "prefix": "math_"},
  })
  ```
  Tools become `weather_search` and `math_search`.
- Wrap manually:
  ```python
  tools = [t.copy(update={"name": f"weather_{t.name}"}) for t in weather_tools]
  ```

---

## 8. Auth

### Static Bearer (dev / internal)

```python
"my_server": {
    "url": "https://mcp.example.com/mcp",
    "transport": "streamable_http",
    "headers": {"Authorization": f"Bearer {os.environ['MCP_TOKEN']}"},
}
```

### OAuth 2.1 (production)

Acquire a token per user (not per service):

```python
async def per_user_client(user_token: str) -> MultiServerMCPClient:
    return MultiServerMCPClient({
        "my_server": {
            "url": "https://mcp.example.com/mcp",
            "transport": "streamable_http",
            "headers": {"Authorization": f"Bearer {user_token}"},
        },
    })

# In a request handler:
async with await per_user_client(get_user_token(request)) as client:
    tools = await client.get_tools()
    ...
```

If tokens expire mid-conversation, handle refresh in middleware or wrap the tool calls.

---

## 9. Error handling

MCP tool errors come back as `ToolMessage(status="error")`. The agent sees them.

Transient transport errors (connection drop) need retry. Wrap with middleware:

```python
from langchain.agents.middleware import AgentMiddleware

class MCPRetryMiddleware(AgentMiddleware):
    async def before_tool(self, state, runtime):
        # check connection health, reconnect if needed
        ...
```

Or use `tenacity` decorators on individual tools.

---

## 10. Reading server resources / prompts

Resources and prompts are also exposed by the adapter:

```python
resources = await client.get_resources()      # list of Resource objects
prompts = await client.get_prompts()          # list of Prompt objects

# Read a resource
content = await client.session("weather").read_resource("config://current")
```

(API exact shape depends on adapter version; check current.)

---

## 11. The minimal pattern in one block

```python
import os
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

async def main():
    async with MultiServerMCPClient({
        "fs": {"command": "npx", "args": ["@modelcontextprotocol/server-filesystem", "/tmp"], "transport": "stdio"},
        "weather": {"url": "http://localhost:8000/mcp", "transport": "streamable_http"},
    }) as client:
        tools = await client.get_tools()
        agent = create_agent(
            model="anthropic:claude-sonnet-4-6",
            tools=tools,
            system_prompt="You can use filesystem and weather tools.",
        )
        result = await agent.ainvoke(
            {"messages": [HumanMessage("what files are in /tmp?")]},
            config={"configurable": {"thread_id": "demo"}},
        )
        print(result["messages"][-1].content)
```

---

## 12. Gotchas

- **Build the client at startup**, not per request. Per-request creation = process spawn or
  HTTP handshake per request.
- **Always close** (`async with` or explicit `__aexit__`) — stdio leaves zombie processes.
- **No tool-name collisions** — namespace if you serve multiple sources.
- **Allowlist tools in production** — auto-loading all is a prompt-injection vector.
- **Per-user tokens** for OAuth, not a shared service token.
