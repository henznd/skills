# Tools — `@tool`, `BaseTool`, Injection

> How to define tools that the LLM calls. Tools are functions with a JSON schema and a
> docstring; both reach the model.

---

## 1. The basic `@tool` decorator

```python
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: City name in English, e.g. "Paris" or "New York".
    """
    return _lookup(city)
```

What the LLM sees:
- **Name**: `get_weather` (the function name).
- **Description**: the docstring's first paragraph.
- **Parameters**: schema derived from type hints + `Args:` block.

---

## 2. Custom name / description

```python
@tool("weather", parse_docstring=True)
def get_weather(city: str) -> str:
    """Get current weather.

    Args:
        city: City name in English.
    """
    return _lookup(city)
```

`parse_docstring=True` extracts arg descriptions from the docstring (Google style by
default). Without it, only the first line is used as description.

---

## 3. Rich input schema with Pydantic

```python
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class BookFlight(BaseModel):
    origin: str = Field(..., description="IATA code, e.g. 'CDG'")
    destination: str = Field(..., description="IATA code")
    date: str = Field(..., description="ISO 8601 'YYYY-MM-DD'")
    passengers: int = Field(1, ge=1, le=9)

@tool("book_flight", args_schema=BookFlight)
def book_flight(origin: str, destination: str, date: str, passengers: int) -> dict:
    """Book a flight. Returns the booking confirmation."""
    return _book(origin, destination, date, passengers)
```

Pydantic validation runs before your function body. Bad args from the LLM → exception
captured as a tool error.

---

## 4. Async tools

```python
@tool
async def fetch(url: str) -> str:
    """Fetch a URL and return text content."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
    return r.text
```

LangGraph dispatches sync/async tools appropriately; in an async graph, async tools run
concurrently when multiple tool calls come back from one model turn.

---

## 5. `BaseTool` subclass (full control)

When you need stateful tools, custom error handling, or different sync/async behavior:

```python
from langchain_core.tools import BaseTool
from pydantic import BaseModel

class SearchInput(BaseModel):
    query: str
    top_k: int = 5

class SearchTool(BaseTool):
    name: str = "search"
    description: str = "Search the knowledge base."
    args_schema: type[BaseModel] = SearchInput

    def __init__(self, index_client, **kwargs):
        super().__init__(**kwargs)
        self._client = index_client

    def _run(self, query: str, top_k: int = 5) -> list[str]:
        return self._client.search(query, top_k)

    async def _arun(self, query: str, top_k: int = 5) -> list[str]:
        return await self._client.asearch(query, top_k)
```

Instantiate once: `tools = [SearchTool(my_client)]`.

---

## 6. `InjectedState` — give tools access to graph state

The LLM should not pick a `user_id` (security risk). But the tool needs it. Solution:
inject from state, hide from the schema.

```python
from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from langgraph.prebuilt import InjectedState

@tool
def get_my_orders(
    limit: int = 10,
    state: Annotated[dict, InjectedState] = None,
) -> list[dict]:
    """Get the current user's orders."""
    user_id = state["authenticated_user_id"]  # set by auth middleware
    return db.query(user_id=user_id, limit=limit)
```

`InjectedState` removes `state` from the schema sent to the LLM. The LLM only sees `limit`.

You can also inject specific fields:

```python
@tool
def get_my_orders(
    limit: int = 10,
    user_id: Annotated[str, InjectedState("authenticated_user_id")] = "",
) -> list[dict]:
    """Get the current user's orders."""
    return db.query(user_id=user_id, limit=limit)
```

---

## 7. `InjectedToolArg` — inject from runtime config

For values that come from `RunnableConfig` rather than state:

```python
from langchain_core.tools import tool, InjectedToolArg
from typing import Annotated

@tool
def search(
    query: str,
    api_key: Annotated[str, InjectedToolArg] = "",
) -> list[str]:
    """Search."""
    return _search(query, api_key=api_key)
```

Pass `api_key` via the agent's config; the LLM never sees it.

---

## 8. Tool error handling — pick one pattern

### A. Raise (re-thrown as a `ToolMessage` with `status="error"`)

```python
@tool
def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("b must be non-zero")
    return a / b
```

The agent's next LLM call sees the error and can react. Simplest pattern.

### B. Return a tagged string

```python
@tool
def query_db(sql: str) -> str:
    """Query the DB. Returns rows as text, or 'ERROR: ...' on failure."""
    try:
        return _run(sql)
    except DatabaseError as e:
        return f"ERROR: {e}. Check syntax and retry."
```

Teach the model in the system prompt that `ERROR:` means retry-with-different-args.

### C. Structured error envelope

```python
@tool
def lookup(id: str) -> dict:
    """Lookup by id."""
    try:
        return {"ok": True, "data": _lookup(id)}
    except NotFound:
        return {"ok": False, "error": "not_found", "hint": "verify id format"}
```

Pick **one** pattern and stick to it across all tools in the project. Mixing confuses the
LLM.

---

## 9. Tools returning multimodal content

```python
from langchain_core.messages import ToolMessage

@tool
def render_chart(data: list[float]) -> dict:
    """Render data as a chart image. Returns an image."""
    png_bytes = _render(data)
    return {
        "type": "tool_result",
        "content": [
            {"type": "image", "source_type": "base64", "data": base64.b64encode(png_bytes).decode(), "mime_type": "image/png"},
        ],
    }
```

Provider support varies — check that the model can ingest image tool results.

---

## 10. Tools that need long execution

If a tool runs for minutes (training a model, generating video):

- Return a job ID and have a separate `get_job_status(job_id)` tool to poll.
- OR use HITL middleware to pause the agent while the job runs out-of-band.
- Don't block — agents shouldn't have minute-long tool calls.

---

## 11. The tool review checklist

Before adding a tool:
- [ ] Function name is verb-noun (`fetch_invoice`, not `invoice`).
- [ ] Docstring describes WHAT not HOW.
- [ ] Type hints on every arg.
- [ ] Pydantic schema for non-trivial inputs (>2 params or any validated field).
- [ ] Return type is JSON-serializable.
- [ ] Identity injected from state, not LLM-chosen.
- [ ] Error handling matches the project's chosen pattern.
- [ ] If side-effectful: idempotent OR gated by HITL.
- [ ] Timeout on any I/O.
