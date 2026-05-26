# FastMCP — Code Review Reference

> For files that define an MCP server with `FastMCP(...)` and expose tools/resources/prompts.
> Pair with `mcp-client-review.md` if the same file also consumes other MCP servers.

---

## 1. Versions and imports

```python
# Modern, recommended
from fastmcp import FastMCP

# Also valid — same code lives in the official SDK
from mcp.server.fastmcp import FastMCP
```

What to check:
- `fastmcp >= 2.10` for elicitation, output schemas (6/18/2025 MCP spec).
- `fastmcp >= 3.0` (Jan 2026) for component versioning, granular auth, OpenTelemetry,
  provider types. Note: 3.0 brought breaking changes to auth — review `AuthSettings` carefully.
- Mixing `from fastmcp` and `from mcp.server.fastmcp` in the same project — 🟡 `[nit]`,
  pick one for consistency.

---

## 2. Server construction

```python
mcp = FastMCP(
    name="my-server",                # appears to clients
    instructions="What this exposes", # high-level description shown to LLMs
)
```

🟠 `[important]` Server with no `instructions`. Clients (and the LLM consuming the tools)
have to infer purpose from tool names alone.

🔴 `[blocking]` Two `FastMCP(...)` instances in the same module with the same `name`. Tools
on the second silently override the first when both are mounted.

---

## 3. Tools (`@mcp.tool`)

### 3.1 Type hints are the schema

FastMCP generates the JSON schema from Python type hints. Loose types = loose schema = the
calling LLM makes more bad calls.

✅:

```python
from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    query: str = Field(..., description="Search query", min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=20)

@mcp.tool
def search(input: SearchInput) -> list[str]:
    """Search the index. Returns up to top_k matches."""
    ...
```

🟠 `[important]`:

```python
@mcp.tool
def search(query, top_k=5):   # ❌ no type hints
    ...
```

🟡 `[nit]` Type hints present but no `Field(description=...)` — model has only the
parameter name to go on.

### 3.2 Docstrings are prompts (again)

Same rule as LangChain tools: docstrings are sent to the LLM. Write them from the LLM's POV.

### 3.3 Async tools and no infinite timeouts

🔴 `[blocking]`:

```python
import httpx

@mcp.tool
async def fetch(url: str) -> str:
    async with httpx.AsyncClient() as client:   # ❌ no timeout
        r = await client.get(url)
    return r.text
```

`httpx.AsyncClient()` has `timeout=None` by default (infinite). A misbehaving upstream parks
your tool forever, blocking the MCP connection.

✅:

```python
async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
    ...
```

### 3.4 Tools must not raise unhandled exceptions across the FastMCP boundary

The SDK catches them and returns "internal error" — the LLM gets nothing useful.

✅ Pattern:

```python
from mcp import McpError

@mcp.tool
def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise McpError("b must be non-zero")  # OR return a structured error
    return a / b
```

🔴 `[blocking]` Tool that calls `subprocess.run` or external service with no try/except —
any failure becomes an opaque "internal error" to the agent.

### 3.5 Tools that mutate must be safe to retry

Same rule as in `agent-architecture-review.md` §4.5. MCP clients (including Claude) may
retry on transport errors. Side-effectful tools without idempotency = double sends.

### 3.6 Output schemas (FastMCP 2.10+)

```python
@mcp.tool
def lookup(q: str) -> SearchResults:
    """..."""
    return SearchResults(items=[...], total=42)
```

If the return type is a Pydantic model or `TypedDict`, FastMCP emits an output schema. The
client can validate. 🌟 `[praise]` when you see this used consistently.

🟠 `[important]` Mix of structured returns and unstructured `dict` / `str` across tools in
the same server. Standardize.

### 3.7 `ToolResult` for metadata

FastMCP 2.10+ supports a `meta` parameter on `ToolResult` for supplementary data (e.g. UI
hints for OpenAI's Apps SDK). When present, verify the metadata doesn't contain secrets or
PII — it's sent to the client.

---

## 4. Resources (`@mcp.resource`)

Resources are read-only data the model can pull on demand. URI-keyed.

```python
@mcp.resource("config://app/{section}")
def get_config(section: str) -> str:
    """Read app config section."""
    return load_config()[section]
```

What to check:
- 🔴 `[blocking]` Resources expose secrets, credentials, or files outside an allowed
  directory. The model can read anything you expose.
- 🟠 `[important]` URI templates with no validation of path parameters — directory traversal
  risk (`{section}` = `../../etc/passwd`).
- 🟡 `[nit]` Very large resources returned in one shot — paginate or split.

---

## 5. Prompts (`@mcp.prompt`)

Prompts are user-invokable templates.

```python
@mcp.prompt
def summarize(topic: str) -> str:
    """Generate a summary prompt for the given topic."""
    return f"Summarize the latest on {topic}. Be concise."
```

🔴 `[blocking]` `f"... {user_input} ..."` with no sanitization in a prompt that is later
concatenated into a system prompt downstream. Prompt injection vector.

---

## 6. Elicitation (FastMCP 2.10+)

Elicitation lets the server request more info from the user mid-execution.

```python
@mcp.tool
async def book_flight(destination: str, ctx: Context) -> str:
    """Book a flight."""
    if not destination:
        result = await ctx.elicit(
            message="Where to?",
            schema={"type": "object", "properties": {"destination": {"type": "string"}}},
        )
        destination = result["destination"]
    ...
```

What to check:
- 🟠 `[important]` Elicitation result used without validation — schema is advisory, not
  enforced by all clients.
- 🔴 `[blocking]` Elicitation in a non-interactive transport (some stdio scenarios). Test
  the failure path.

---

## 7. Transport and deployment

### 7.1 stdio

```python
if __name__ == "__main__":
    mcp.run()  # default = stdio
```

stdio runs as the user invoking the client. Auth is implicit (the OS). No network exposure.
✅ Safe by default for local-only servers.

### 7.2 Streamable HTTP (production)

```python
mcp.run(transport="streamable-http", port=8000)
```

🔴 `[blocking]` Streamable HTTP server with no authentication. The November 2025 MCP spec
**mandates** OAuth 2.1 (with optional OIDC discovery) for any server reachable over the
public internet.

🔴 `[blocking]` Streamable HTTP server with `Bearer` token hard-coded in source or env var
checked into version control.

🟠 `[important]` Streamable HTTP bound to `0.0.0.0` in development without `127.0.0.1`
override for local-only dev.

### 7.3 SSE (legacy)

🟡 `[nit]` New code using `transport="sse"` — SSE is supported but Streamable HTTP is the
modern path.

---

## 8. Auth

FastMCP's `AuthSettings`:

| Mode | Use case |
|---|---|
| Bearer token (static) | Local dev, internal-only |
| OAuth 2.1 / OIDC | Production, public internet |
| Custom `TokenVerifier` | Validating opaque tokens against an auth server |

### 8.1 OAuth 2.1 setup

```python
from fastmcp.auth import OAuthSettings

mcp = FastMCP(
    name="prod-server",
    auth=OAuthSettings(
        issuer_url="https://auth.example.com",
        audience="my-server",
        # ...
    ),
)
```

What to verify:
- 🔴 `[blocking]` `audience` not validated — token from another service accepted.
- 🔴 `[blocking]` Token verifier accepts unsigned JWTs or skips signature check.
- 🟠 `[important]` `DebugTokenVerifier` used outside dev — accepts any token.
- 🟠 `[important]` Token scopes not checked per-tool — a token issued for read scope can
  call write tools.

### 8.2 Per-tool authorization

FastMCP 3.0 added granular authorization. If 3.0 is used:

```python
@mcp.tool(required_scopes=["email:send"])
async def send_email(...): ...
```

🟠 `[important]` Tools that mutate external state (send, delete, charge) without a scope
requirement.

---

## 9. Logging and observability

- 🟠 `[important]` `print()` statements in tools — they corrupt stdio transport. Use the
  `logging` module configured to write to stderr.
- 🟠 `[important]` Logs include tool input verbatim — PII / secrets leak. Redact at the log
  layer.
- 🌟 `[praise]` OpenTelemetry instrumentation (FastMCP 3.0+) configured with a real
  exporter.

---

## 10. The MCP server review checklist

Before approving an MCP server PR:

- [ ] Every tool has type hints AND a useful docstring.
- [ ] No `httpx.AsyncClient()` without timeout.
- [ ] No tools raising raw exceptions across the boundary.
- [ ] No `print()` statements (use `logging`).
- [ ] If Streamable HTTP, auth is OAuth 2.1 (not hard-coded Bearer).
- [ ] Side-effectful tools are idempotent OR require client-side approval.
- [ ] Resources don't expose anything outside an allowlist.
- [ ] Prompts don't concatenate raw user input into instructions.
- [ ] Inspector test (`mcp dev` or `mcp inspector`) included in CI.
- [ ] Version constraint on `fastmcp` is pinned (`>=2.10,<3` or `>=3,<4`).
