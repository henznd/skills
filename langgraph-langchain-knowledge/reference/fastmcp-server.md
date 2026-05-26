# FastMCP Server — Build an MCP Server in Python

> The fastest way to expose tools, resources, and prompts to MCP clients (Claude Desktop,
> Cursor, agents using `langchain-mcp-adapters`, etc.).

---

## 1. Install

```bash
pip install fastmcp
# or, equivalent (older code):
pip install "mcp[cli]"
```

Versions:
- `fastmcp >= 2.10` — elicitation, output schemas, 6/18/2025 MCP spec.
- `fastmcp >= 3.0` (Jan 2026) — component versioning, granular auth, OpenTelemetry,
  provider types. Breaking auth changes from 2.x.

---

## 2. Minimal server

```python
# server.py
from fastmcp import FastMCP

mcp = FastMCP("my-server", instructions="Tools for X.")

@mcp.tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b

if __name__ == "__main__":
    mcp.run()
```

Run with `python server.py` → stdio transport. Test with:

```bash
mcp dev server.py        # inspector UI
# or
mcp inspector server.py
```

---

## 3. Tools

### Sync

```python
@mcp.tool
def search(query: str, top_k: int = 5) -> list[str]:
    """Search the index.

    Args:
        query: Natural-language query.
        top_k: Max results (1-20).
    """
    return _do_search(query, top_k)
```

### Async (preferred for I/O)

```python
@mcp.tool
async def fetch(url: str) -> str:
    """Fetch a URL and return text."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
    r.raise_for_status()
    return r.text
```

### Pydantic input schema

```python
from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=20)

@mcp.tool
def search(input: SearchInput) -> list[str]:
    """Search the index."""
    return _do_search(input.query, input.top_k)
```

### Output schema (FastMCP 2.10+)

Return a Pydantic model or TypedDict; FastMCP emits the schema:

```python
class SearchResult(BaseModel):
    items: list[str]
    total: int
    took_ms: float

@mcp.tool
def search(query: str) -> SearchResult:
    """Search the index."""
    return SearchResult(items=[...], total=42, took_ms=12.5)
```

---

## 4. Resources

Resources are read-only data the LLM can pull on demand. URI-keyed.

```python
@mcp.resource("config://app/{section}")
def get_config(section: str) -> str:
    """Read app config section."""
    config = _load_config()
    if section not in _ALLOWED:
        raise ValueError(f"unknown section: {section}")
    return config[section]
```

URIs use any scheme; conventional ones are `file://`, `config://`, `db://`.

---

## 5. Prompts

User-invokable templates the LLM can render.

```python
@mcp.prompt
def summarize(topic: str) -> str:
    """Generate a summary prompt."""
    return f"Summarize the latest on {topic}. Be concise. Cite sources."
```

For multi-message prompts:

```python
from mcp.types import PromptMessage

@mcp.prompt
def code_review(code: str) -> list[PromptMessage]:
    """Code review template."""
    return [
        PromptMessage(role="user", content={"type": "text", "text": "Review this code."}),
        PromptMessage(role="user", content={"type": "text", "text": code}),
    ]
```

---

## 6. Elicitation (FastMCP 2.10+)

Server can request more info from the user mid-execution.

```python
from fastmcp import Context

@mcp.tool
async def book_flight(destination: str | None = None, ctx: Context = None) -> str:
    """Book a flight."""
    if not destination:
        result = await ctx.elicit(
            message="Where would you like to fly to?",
            schema={
                "type": "object",
                "properties": {"destination": {"type": "string"}},
                "required": ["destination"],
            },
        )
        destination = result["destination"]
    return _book(destination)
```

`Context` is auto-injected when annotated. Elicitation works in interactive transports
(stdio with an interactive client, HTTP with a UI). Non-interactive clients may fail.

---

## 7. Transports

### stdio (default)

```python
if __name__ == "__main__":
    mcp.run()  # stdio
```

Runs as a subprocess of the client. Auth is implicit (the OS). Used by Claude Desktop,
local agents.

### Streamable HTTP (production)

```python
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)
```

For network-reachable servers. Modern MCP spec mandates OAuth 2.1 for public servers.

### SSE (legacy)

```python
mcp.run(transport="sse", port=8000)
```

Supported but Streamable HTTP is the modern path.

---

## 8. Auth — OAuth 2.1 (production)

Per the November 2025 MCP spec, public HTTP servers must use OAuth 2.1 (with optional
OIDC discovery).

### Pattern (FastMCP 2.x — verify against your version)

```python
from fastmcp.auth import OAuthSettings, TokenVerifier

mcp = FastMCP(
    "prod-server",
    auth=OAuthSettings(
        issuer_url="https://auth.example.com",
        audience="my-mcp-server",
        # ...
    ),
)
```

### Custom token verifier

```python
from fastmcp.auth import TokenVerifier

class MyVerifier(TokenVerifier):
    async def verify(self, token: str) -> dict | None:
        # call your auth service, return claims or None
        ...

mcp = FastMCP("prod-server", auth=MyVerifier())
```

⚠️ FastMCP 3.0 (Jan 2026) introduced breaking auth changes — refer to the version's docs
for the current API. The semantics (validate issuer, audience, signature, scopes) remain
the same.

### Per-tool scopes (FastMCP 3.0+)

```python
@mcp.tool(required_scopes=["email:send"])
async def send_email(to: str, body: str) -> dict:
    """Send an email."""
    ...
```

Token must include the listed scopes or the tool is denied before invocation.

---

## 9. Lifespan (startup/shutdown)

```python
from contextlib import asynccontextmanager
from fastmcp import FastMCP

@asynccontextmanager
async def lifespan(app):
    # startup
    app.state.db = await connect_db()
    app.state.http = httpx.AsyncClient(timeout=10.0)
    yield
    # shutdown
    await app.state.http.aclose()
    await app.state.db.close()

mcp = FastMCP("my-server", lifespan=lifespan)

@mcp.tool
async def query(sql: str) -> list[dict]:
    """Query DB."""
    return await mcp.state.db.fetch(sql)
```

(API for accessing app state from tools depends on FastMCP version — older versions use
the injected `Context`.)

---

## 10. Observability

### Logging

```python
import logging
logger = logging.getLogger(__name__)

@mcp.tool
def divide(a: float, b: float) -> float:
    """Divide."""
    logger.info("divide called", extra={"a": a, "b": b})
    return a / b
```

⚠️ **Never `print()` in a stdio server** — it corrupts the JSON-RPC stream. Always use
`logging` (writes to stderr by default).

### OpenTelemetry (FastMCP 3.0+)

```python
from fastmcp.observability import setup_telemetry

setup_telemetry(
    service_name="my-mcp-server",
    otlp_endpoint="http://localhost:4318",
)
```

---

## 11. The minimum production server template

```python
# server.py
import logging
import os
from contextlib import asynccontextmanager
import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app):
    app.state.http = httpx.AsyncClient(timeout=10.0)
    try:
        yield
    finally:
        await app.state.http.aclose()

mcp = FastMCP(
    name="prod-server",
    instructions="Tools for X. See docs at example.com.",
    lifespan=lifespan,
)

class SearchInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=20)

class SearchResult(BaseModel):
    items: list[str]
    total: int

@mcp.tool
async def search(input: SearchInput) -> SearchResult:
    """Search the index. Returns up to top_k matches."""
    logger.info("search", extra={"top_k": input.top_k})
    items = await _do_search(input.query, input.top_k)
    return SearchResult(items=items, total=len(items))

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
    else:
        mcp.run(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )
```

---

## 12. Quick gotchas

- `print()` corrupts stdio.
- No timeout on `httpx.AsyncClient` = infinite hang on bad upstream.
- Raising raw exceptions across the FastMCP boundary = opaque "internal error" to the LLM.
- HTTP server with no auth = the November 2025 spec violation.
- Two `FastMCP(...)` with the same `name` = tool overrides.
- Type-hint-less tools = the LLM has to guess.
