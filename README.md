# Claude Code Skills — Python AI Agents (LangGraph 1.0 / LangChain 1.0 / FastMCP)

Two complementary skills for an agent codebase using LangGraph 1.0, LangChain 1.0, and
FastMCP:

1. **`code-review-python-agents/`** — A code-review skill targeting the framework-specific
   bugs that bite agent codebases (state mutation, broken conditional edges, missing
   `thread_id`, prompt injection, MCP auth, etc.).
2. **`langgraph-langchain-knowledge/`** — A reference / knowledge-base skill the coding
   agent can read when writing new code, since it doesn't have web access to the official
   docs.

The skills are designed to be used together: when reviewing, the agent can cross-reference
the knowledge skill to verify whether a pattern in the PR matches current 1.0 idioms.

---

## Installation

### Option A — Project-local (recommended for a single project)

Copy both directories into your project's `.claude/skills/`:

```bash
cd /path/to/your/project
mkdir -p .claude/skills
cp -r /path/to/code-review-python-agents .claude/skills/
cp -r /path/to/langgraph-langchain-knowledge .claude/skills/
```

Commit them. The whole team gets the same review standard.

### Option B — Global (across all your projects)

```bash
mkdir -p ~/.claude/skills
cp -r /path/to/code-review-python-agents ~/.claude/skills/
cp -r /path/to/langgraph-langchain-knowledge ~/.claude/skills/
```

### Option C — From zip archives

If you received them as zips:

```bash
cd .claude/skills    # or ~/.claude/skills
unzip code-review-python-agents.zip
unzip langgraph-langchain-knowledge.zip
```

---

## Verifying installation

Open Claude Code in the project. Ask:

> "What skills do you have?"

You should see both skills listed.

For a quick sanity check:

> "Review this file for LangGraph pitfalls: <paste a path>"

The code-review skill should trigger.

---

## Triggering the skills

Both skills have descriptions that trigger on natural-language cues. Examples:

- **Code review skill**: "review my graph", "audit my MCP server", "check this PR for
  state mutation", "is my FastMCP server production-ready", etc.
- **Knowledge skill**: "how do I add HITL to my agent", "what's the modern way to do
  map-reduce in LangGraph", "show me a FastMCP server template", etc.

You can also tell the agent directly: "Use the `code-review-python-agents` skill to review
this branch."

---

## Versions covered

- LangGraph 1.0+ (zero breaking changes from 0.x; 1.0 stabilizes runtime)
- LangChain 1.0+ (introduces `create_agent`, middleware, content blocks)
- FastMCP 2.10+ (elicitation, output schemas) and 3.0+ (component versioning, granular auth)
- The November 2025 MCP spec mandates OAuth 2.1 for public HTTP servers.

If your stack is pre-1.0, most of the patterns still apply but some specific APIs differ
(e.g. `create_agent` didn't exist before LangChain 1.0; `interrupt_before` was the standard
HITL pattern before 1.0).

---

## Customizing for your team

Both skills are plain Markdown / Python — edit freely. Common customizations:

- **Adjust severity bar**: in `code-review-python-agents/SKILL.md` and reference files,
  change which findings get 🔴 `[blocking]` vs 🟠 `[important]` to match your team's
  tolerance.
- **Add internal-tooling sections**: e.g. your own observability stack, deployment
  conventions, custom middleware libraries.
- **Pin to specific framework versions** in the knowledge skill if you're on older
  versions and want the examples to match.

---

## Layout

```
code-review-python-agents/
├── SKILL.md                              # entry point (always loaded)
├── reference/
│   ├── langgraph-review.md               # priority 1: state, edges, checkpoints
│   ├── agent-architecture-review.md      # priority 2: create_agent, middleware
│   ├── tools-and-prompts-review.md
│   ├── fastmcp-review.md                 # priority 3: MCP server
│   ├── mcp-client-review.md              # priority 3: MCP client
│   ├── async-and-streaming-review.md     # priority 4: async/streaming
│   ├── testing-and-observability-review.md # priority 5
│   ├── security-review.md
│   └── python-base-review.md
└── assets/
    ├── pr-review-template.md
    └── quick-checklist.md

langgraph-langchain-knowledge/
├── SKILL.md                              # entry point (always loaded)
├── reference/
│   ├── cheatsheet.md                     # one-page summary
│   ├── langgraph-core.md
│   ├── checkpointers.md
│   ├── interrupts-and-hitl.md
│   ├── parallelism.md
│   ├── langchain-agents.md
│   ├── messages-and-models.md
│   ├── tools.md
│   ├── streaming.md
│   ├── fastmcp-server.md
│   ├── mcp-client.md
│   └── testing.md
└── examples/
    ├── minimal-react-agent.py
    ├── custom-stategraph.py
    ├── hitl-approval.py
    ├── map-reduce-send.py
    ├── fastmcp-server.py
    └── agent-with-mcp.py
```

---

## Credit

Structure inspired by the awesome-skills [code-review-skill](https://github.com/awesome-skills/code-review-skill).
The severity labels (🔴 / 🟠 / 🟡 / 🔵 / 📚 / 🌟) match that skill so reviewers familiar
with it transition seamlessly.
