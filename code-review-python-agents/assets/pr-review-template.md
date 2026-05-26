# PR Review — Summary Template

> Copy this into the PR review comment. Fill what applies, delete what doesn't.

---

## Context

**Branch / PR:** `<branch>` → `<base>`
**Scope:** <one-line description of what the PR does>
**Framework versions detected:** `langgraph==<X>`, `langchain==<X>`, `fastmcp==<X>`
**Files touched:** <count> files, <count> lines added / removed

---

## Architectural notes

<2–5 bullets on the design decisions visible in the diff. Are they sound? Do they fit the
existing patterns in the repo? Anything that looks like a refactor justified mid-PR?>

---

## Findings

> Each finding tagged with severity. Anchored to `file:line`.

### 🔴 Blocking

- **`path/to/file.py:42`** — <one-line description>
  <2–4 line explanation of the failure mode>
  ```python
  # Suggested patch
  ...
  ```

### 🟠 Important

- **`path/to/file.py:NN`** — ...

### 🟡 Nit

- **`path/to/file.py:NN`** — ...

### 🔵 Suggestion

- **`path/to/file.py:NN`** — ...

### 📚 Learning

- **`path/to/file.py:NN`** — ...

### 🌟 Praise

- **`path/to/file.py:NN`** — <what was done well>

---

## Tests

- [ ] New tests cover the change
- [ ] Tests don't hit real APIs
- [ ] HITL paths (if any) have interrupt+resume test
- [ ] Topology test runs (if graph changed)

---

## Security quick check

- [ ] No new user-controlled text in system prompts
- [ ] No new secrets in source
- [ ] New destructive tools have HITL
- [ ] New MCP exposure (if any) has auth

---

## Decision

- [ ] ✅ Approve
- [ ] 💬 Comment (minor suggestions, no blockers)
- [ ] 🔄 Request changes — blockers above must be addressed
