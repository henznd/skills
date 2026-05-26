# Messages, Content Blocks, and Models

> The data model for what flows between you and an LLM. LangChain 1.0 introduced standard
> **content blocks** so the same code works across providers for reasoning, citations,
> multimodal, tool calls.

---

## 1. Message types

All in `langchain_core.messages`:

| Class | Role | Notes |
|---|---|---|
| `SystemMessage` | system | Instructions to the model |
| `HumanMessage` | user | User-provided content |
| `AIMessage` | assistant | Model output (text + tool calls + reasoning) |
| `ToolMessage` | tool | A tool result, references `tool_call_id` |
| `AnyMessage` | union | Type alias for any of the above |

```python
from langchain_core.messages import (
    SystemMessage, HumanMessage, AIMessage, ToolMessage, AnyMessage
)

msgs: list[AnyMessage] = [
    SystemMessage("You are helpful."),
    HumanMessage("What's 2+2?"),
    AIMessage("4"),
]
```

---

## 2. Constructing messages

```python
# Simple text
HumanMessage("hello")
HumanMessage(content="hello")

# With multimodal content (v1 format)
HumanMessage(content=[
    {"type": "text", "text": "What's in this image?"},
    {"type": "image", "source_type": "url", "url": "https://..."},
])

# Tool call from the model
AIMessage(
    content="",
    tool_calls=[{"name": "search", "args": {"q": "weather"}, "id": "call_1"}],
)

# Tool result
ToolMessage(
    content="sunny",
    tool_call_id="call_1",
)
```

---

## 3. Content blocks (1.0+)

Every message exposes `.content_blocks` — a lazily-parsed, provider-agnostic typed list.

### Why it matters

Different providers emit reasoning, citations, etc. in different formats. `.content_blocks`
normalizes them. You write code once, swap providers freely.

### Standard block types

| Type | Use |
|---|---|
| `TextContentBlock` | Plain text segment |
| `ReasoningContentBlock` | Chain-of-thought / thinking |
| `ToolCall` | Model-requested tool invocation |
| `ImageContentBlock`, `AudioContentBlock`, `VideoContentBlock`, `FileContentBlock` | Multimodal |
| `PlainTextContentBlock` | Plaintext attachments (.txt, .md) |
| `Citation` | Citation annotation on text |
| `NonStandardContentBlock` | Provider-specific data not yet standardized |
| `InvalidToolCall` | Malformed tool call (JSON parse error) |

### Reading

```python
msg: AIMessage = ...
for block in msg.content_blocks:
    if block["type"] == "text":
        print(block["text"])
    elif block["type"] == "reasoning":
        print("THINKING:", block["reasoning"])
    elif block["type"] == "tool_call":
        print("CALL:", block["name"], block["args"])
```

### Writing v1-style content directly

You can construct messages with `content` as a list of v1 blocks. The
`AIMessage.output_version="v1"` flag (per provider-package config) controls storage format.

For most application code, `.content_blocks` (read-side) and provider helpers (write-side)
are enough — you don't need to construct raw blocks by hand.

---

## 4. Model wrappers

```python
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

model = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)
# or
model = ChatOpenAI(model="gpt-4o", temperature=0)
# or
model = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
```

Common params:
- `model`: provider-specific identifier.
- `temperature`: 0 for deterministic, ~0.7 for creative.
- `max_tokens`: cap output (provider-named: `max_tokens`, `max_output_tokens`, etc).
- `timeout`: per-call timeout.
- `max_retries`: built-in retry on rate-limit / transient errors.

---

## 5. `init_chat_model` — provider-agnostic factory

```python
from langchain.chat_models import init_chat_model

model = init_chat_model("anthropic:claude-sonnet-4-6", temperature=0)
# or
model = init_chat_model("openai:gpt-4o")
```

This is what `create_agent(model="...")` uses internally. Useful when the choice of provider
is a config value.

---

## 6. Calling a model

### Sync

```python
response: AIMessage = model.invoke([
    SystemMessage("You translate to French."),
    HumanMessage("Good morning."),
])
print(response.content)
```

### Async

```python
response = await model.ainvoke([...])
```

### Streaming

```python
async for chunk in model.astream([...]):
    print(chunk.content, end="", flush=True)
```

Each chunk is an `AIMessageChunk`. Concatenating them yields the full message.

---

## 7. Binding tools to a model

```python
model_with_tools = model.bind_tools([search, calculator])
response: AIMessage = model_with_tools.invoke([HumanMessage("what's the weather?")])
# response.tool_calls contains structured calls
for call in response.tool_calls:
    print(call["name"], call["args"])
```

`create_agent` does this for you — bare `bind_tools` is for hand-rolled graphs.

---

## 8. Structured output

```python
from pydantic import BaseModel

class Joke(BaseModel):
    setup: str
    punchline: str

structured_model = model.with_structured_output(Joke)
joke: Joke = structured_model.invoke("Tell me a joke about Python.")
print(joke.punchline)
```

Provider-native structured output (JSON schema, tool calling) is used where available.

---

## 9. Helpers in `langchain_core.messages`

```python
from langchain_core.messages import trim_messages, merge_message_runs

# Trim to N tokens (needs a tokenizer or token_counter)
trimmed = trim_messages(
    messages,
    max_tokens=4000,
    token_counter=model,         # uses model's tokenizer
    strategy="last",              # keep most recent
    include_system=True,
)

# Merge consecutive same-role messages
merged = merge_message_runs(messages)
```

Useful in long conversations or in middleware before sending to the model.

---

## 10. Provider-specific notes

### Anthropic
- Supports reasoning via `thinking={"type": "enabled", "budget_tokens": 5000}` param on
  `ChatAnthropic` (Claude 4 family). Reasoning shows up as `ReasoningContentBlock`.
- Prompt caching: pass `cache_control={"type": "ephemeral"}` on messages or via provider
  middleware.

### OpenAI
- `ChatOpenAI(model="o3-mini")` for reasoning models — `reasoning` parameter controls
  effort.
- Responses API (newer): some features (web search, file inputs) require it instead of
  Chat Completions.

### Google
- `ChatGoogleGenerativeAI` for Gemini. Multimodal first-class.

---

## 11. The `RunnableConfig` you'll see in middleware

```python
async def before_model(self, state, runtime):
    # runtime.config is the RunnableConfig
    user_id = runtime.config.get("configurable", {}).get("user_id")
    ...
```

`RunnableConfig` carries `configurable` keys (your `thread_id`, custom values), tags,
metadata, run name, and the recursion limit. It's the framework's request-scoped context.

You set it on invocation:

```python
graph.invoke(
    state,
    config={
        "configurable": {"thread_id": "t1", "user_id": "u42"},
        "tags": ["prod"],
        "run_name": "support-thread",
    },
)
```
