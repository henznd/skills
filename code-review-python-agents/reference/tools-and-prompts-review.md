# Tools & Prompts — Code Review Reference

> For files defining tools (`@tool`) and prompt templates. Treat tool docstrings and prompt
> templates as code that ships to production — bugs here cause silent agent misbehavior.

---

## 1. Tool design

### 1.1 One tool = one clear capability

🟠 `[important]` Tools that take a `command: str` and dispatch internally are an
anti-pattern. The LLM can't reason about a string-typed switch as well as it can reason
about distinct typed tools. Split.

```python
# ❌ Don't
@tool
def db(operation: str, args: dict) -> str:
    if operation == "query": ...
    elif operation == "insert": ...

# ✅ Do
@tool
def db_query(sql: str) -> list[dict]: ...

@tool
def db_insert(table: str, row: dict) -> None: ...
```

### 1.2 Tool name is part of the prompt

🟡 `[nit]` Tools named `tool1`, `fn`, `do_thing` are unreadable to the model.
Verb-noun: `fetch_invoice`, `summarize_thread`.

### 1.3 Tool input schema

✅ Use Pydantic for non-trivial inputs:

```python
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class BookFlight(BaseModel):
    origin: str = Field(..., description="IATA code, e.g. 'CDG'")
    destination: str = Field(..., description="IATA code")
    date: str = Field(..., description="ISO 8601 date 'YYYY-MM-DD'")
    passengers: int = Field(1, ge=1, le=9)

@tool("book_flight", args_schema=BookFlight)
def book_flight(origin, destination, date, passengers):
    """Book a flight. Confirms before charging."""
    ...
```

🟠 `[important]` String-typed dates, IDs, currency amounts with no validation. The LLM will
pass `"tomorrow"` and your tool will silently fail or charge the wrong card.

### 1.4 Tool return shape

The model sees the return value (or its `str()`). Patterns:

✅ Structured, short:

```python
return {"status": "ok", "id": invoice_id, "amount": 42.0}
```

🟠 `[important]` Tool returning a 50 KB blob. Either summarize, or write to a resource and
return a reference.

🟡 `[nit]` Return type is `Any` or missing — make it explicit.

---

## 2. Tool error handling

(Restating from `agent-architecture-review.md` §4.4 because it bites everywhere.)

Three valid patterns, pick **one per project**:

**A. Re-raise.** LangGraph wraps in a `ToolMessage(status="error")` the model can see.

```python
@tool
def query(sql: str) -> list[dict]:
    return _run(sql)   # raises on error
```

**B. Return a tagged error string.**

```python
@tool
def query(sql: str) -> list[dict] | str:
    try:
        return _run(sql)
    except DatabaseError as e:
        return f"ERROR: {e}. Check syntax and retry."
```

System prompt must teach the model what `ERROR:` means.

**C. Return a structured error envelope.**

```python
@tool
def query(sql: str) -> dict:
    try:
        return {"ok": True, "rows": _run(sql)}
    except DatabaseError as e:
        return {"ok": False, "error": str(e), "hint": "check syntax"}
```

🔴 `[blocking]` mixing patterns. Some tools raise, some return error strings, some return
`None`. The model can't learn three contradictory conventions in one session.

---

## 3. Prompt templates

### 3.1 Use `ChatPromptTemplate`, not f-strings

🔴 `[blocking]`:

```python
prompt = f"You are an assistant. User says: {user_input}"   # ❌ injection
```

✅:

```python
from langchain_core.prompts import ChatPromptTemplate
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an assistant."),
    ("user", "{user_input}"),
])
chain = prompt | model
chain.invoke({"user_input": user_input})  # input is parameterized
```

### 3.2 Don't concatenate untrusted text into the system role

The system message is the most trusted part of the prompt. User-controlled content goes in
the `user` role, where the model knows to treat it as data.

🔴 `[blocking]`:

```python
ChatPromptTemplate.from_messages([
    ("system", "You are an assistant. Context: " + user_supplied_context),  # ❌
])
```

Even with `{}`-style templating, putting user content in the system message lets attackers
escalate. Put context in the user message or a tool result.

### 3.3 Few-shot examples — beware leakage

🟠 `[important]` Few-shot examples taken from real production data without redaction. PII
leak.

### 3.4 Prompt versions

🟡 `[nit]` Prompts inlined as multi-line strings in module-level constants are fine for
small projects but make A/B testing impossible. For non-trivial projects, store prompts in
files or LangSmith Hub and load by version.

---

## 4. The agent's "stop" instruction

In a ReAct loop, the model needs a clear stop signal. Check the system prompt for:

- "When you have enough information, respond directly to the user without calling more tools."
- A natural terminal condition tied to a tool result (e.g. tool returns
  `{"complete": true}` and prompt instructs the model to stop).

🟠 `[important]` ReAct agent with no stop guidance. Will run until `recursion_limit`.

---

## 5. Tool-use sequencing hints

For agents that need to call tools in a specific order:

🟡 `[nit]` Documenting the order in the system prompt ("First call A, then B") is fragile.
Prefer:
- Structural: tool A's output schema includes a field that's required input to B.
- State-machine: separate nodes per phase, with conditional edges.

---

## 6. Quick prompt review pass

For each prompt:
1. Identify every `{placeholder}` and trace where its value comes from.
2. For each placeholder fed from user input, ask: "Can an attacker put 'Ignore previous
   instructions...' here?" If yes, it must be in the user role, not system.
3. Identify every implicit assumption the model is expected to make. Is it stated?
4. Read the prompt aloud. If you couldn't follow it, the model won't either.
