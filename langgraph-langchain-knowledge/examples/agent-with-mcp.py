"""LangChain agent consuming tools from MCP servers via langchain-mcp-adapters.

Demonstrates:
- MultiServerMCPClient with both stdio and streamable-http transports
- Proper lifecycle (async context manager)
- Tool allowlisting (don't auto-bind everything from remote servers)
- Combining MCP tools with locally-defined tools

Run:
    pip install langchain langgraph langchain-anthropic langchain-mcp-adapters
    # Start the example FastMCP server in another terminal:
    #   MCP_TRANSPORT=streamable-http python fastmcp-server.py
    export ANTHROPIC_API_KEY=...
    python agent-with-mcp.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver


# A locally-defined tool to mix with MCP tools
@tool
def local_uppercase(text: str) -> str:
    """Convert text to uppercase. This is a local (non-MCP) tool."""
    return text.upper()


# Allowlist of MCP tools we accept (security best practice)
ALLOWED_MCP_TOOLS = {"define", "reverse_string"}


async def main():
    # Connect to one MCP server over HTTP (the example FastMCP server).
    # In real use, this dict may contain many servers, mixed transports.
    config = {
        "example": {
            "url": os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp"),
            "transport": "streamable_http",
        },
        # Example of a stdio server (commented because the path is illustrative):
        # "filesystem": {
        #     "command": "npx",
        #     "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        #     "transport": "stdio",
        # },
    }

    async with MultiServerMCPClient(config) as client:
        all_mcp_tools = await client.get_tools()

        # Allowlist filtering — important for production
        mcp_tools = [t for t in all_mcp_tools if t.name in ALLOWED_MCP_TOOLS]

        print(f"Loaded {len(mcp_tools)} MCP tool(s): {[t.name for t in mcp_tools]}", file=sys.stderr)

        agent = create_agent(
            model="anthropic:claude-sonnet-4-6",
            tools=[local_uppercase, *mcp_tools],
            system_prompt=(
                "You have access to dictionary tools (define, reverse_string) and a local "
                "uppercase tool. Use them when relevant. Be concise."
            ),
            checkpointer=InMemorySaver(),
        )

        queries = [
            "What does 'serendipity' mean?",
            "Reverse 'hello world' and then uppercase the result.",
        ]
        for q in queries:
            cfg = {"configurable": {"thread_id": f"t-{hash(q)}"}}
            print(f"\n>>> {q}")
            result = await agent.ainvoke(
                {"messages": [HumanMessage(q)]},
                config=cfg,
            )
            print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
