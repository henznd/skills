# Python Base — Code Review Reference

> Generic Python pitfalls. Compact because most teams already lint these; here as a fallback.

---

## 1. Mutable default arguments

🔴 `[blocking]`:

```python
def add_message(msg, history=[]):   # ❌ shared across calls
    history.append(msg)
```

✅:

```python
def add_message(msg, history=None):
    history = [] if history is None else history
    history.append(msg)
```

---

## 2. Bare except / except Exception: pass

🔴 `[blocking]` `except: pass` or `except Exception: pass` without re-raise or log.

🟠 `[important]` Catching `Exception` when only `httpx.HTTPError` (or similar) is expected.

---

## 3. Typing

- 🟡 `[nit]` Public functions without type hints — should be on by default.
- 🟠 `[important]` `Any` used to hide a real type mismatch.
- 🟠 `[important]` `Optional[X]` where the code clearly handles only `X` — drop the
  Optional, or add the None branch.
- 🟡 `[nit]` Old-style `Optional[X]` / `Union[X, Y]` when target Python is 3.10+ — prefer
  `X | None`, `X | Y`.

---

## 4. Pydantic v2

- 🟠 `[important]` Mixing Pydantic v1 (`@validator`) and v2 (`@field_validator`). Pydantic
  v2 is the v1 of LangChain / LangGraph 1.0.
- 🟠 `[important]` `class Config:` (v1) instead of `model_config = ConfigDict(...)` (v2).

---

## 5. Logging

- 🔴 `[blocking]` `print()` for diagnostic logging in production code. Stdout pollution
  breaks stdio MCP servers.
- 🟠 `[important]` `logging.info(f"... {secret} ...")` — interpolation evaluates even when
  logging disabled. Use `logging.info("... %s ...", value)` AND don't log secrets.
- 🟡 `[nit]` Logger named `logging.getLogger()` (root logger) instead of
  `logging.getLogger(__name__)`.

---

## 6. Files & paths

- 🟠 `[important]` `open(...)` without context manager.
- 🟠 `[important]` `os.path.join` mixed with `Path`. Pick one (`pathlib.Path` for new code).
- 🟠 `[important]` Reading files based on a path constructed from LLM output without
  validation — directory traversal.

---

## 7. Async

(More in `async-and-streaming-review.md`.)

- 🟠 `[important]` `asyncio.run(...)` called from inside an already-running loop. Use
  `await` or `asyncio.ensure_future`.
- 🟠 `[important]` `time.sleep` in `async def`.
- 🟠 `[important]` Awaiting in a tight loop without `asyncio.gather` for parallelism.

---

## 8. Dataclasses vs Pydantic vs TypedDict

| Use case | Pick |
|---|---|
| LangGraph state | `TypedDict` (with `Annotated` reducers) or Pydantic `BaseModel` |
| Tool input schema | Pydantic `BaseModel` |
| Internal data transfer with no validation | `@dataclass` |
| Config from env | Pydantic `BaseSettings` |

🟡 `[nit]` `@dataclass` for tool input — works but loses validation. Use Pydantic.

---

## 9. Test hygiene

- 🟠 `[important]` `pytest.fixture` returning a connection without `yield ... + cleanup`.
- 🟠 `[important]` `monkeypatch.setattr` on a string path that no longer exists after
  refactor — test passes silently.
- 🟡 `[nit]` `assert x == y` with no message on a non-obvious comparison.

---

## 10. Project structure smells

- 🟠 `[important]` Everything in `main.py`. Split into `graph.py`, `tools.py`,
  `prompts.py`, `state.py`.
- 🟠 `[important]` Tools and graph definition co-located, but no `__init__.py` controlling
  the public surface — circular import risk.
- 🟡 `[nit]` No `pyproject.toml` (using `setup.py` or just `requirements.txt`).
