"""FastMCP server template — production-shape with typed inputs, output schemas,
async tools with timeouts, structured logging, and dual stdio / HTTP transport.

Demonstrates:
- @mcp.tool with Pydantic input schemas and Pydantic output types
- Async tools using httpx with timeout
- A resource and a prompt
- Lifespan for shared httpx client
- Transport selection via env var
- logging (not print!) to stderr

Run (stdio, default — for Claude Desktop etc.):
    pip install fastmcp httpx pydantic
    python fastmcp-server.py

Run (HTTP):
    MCP_TRANSPORT=streamable-http MCP_PORT=8000 python fastmcp-server.py

Inspect locally:
    pip install "mcp[cli]"
    mcp dev fastmcp-server.py
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, Field


# Log to stderr — stdout is reserved for the JSON-RPC transport on stdio.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("my-mcp-server")


@asynccontextmanager
async def lifespan(app):
    logger.info("starting up")
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        yield
    finally:
        await app.state.http.aclose()
        logger.info("shutdown complete")


mcp = FastMCP(
    name="example-server",
    instructions=(
        "Demo server: search the public dictionary, look up word definitions, "
        "and read a config resource."
    ),
    lifespan=lifespan,
)


# ---------- Tools ----------

class DefineInput(BaseModel):
    word: str = Field(..., min_length=1, max_length=50, description="English word to look up")


class Definition(BaseModel):
    word: str
    part_of_speech: str
    meaning: str


@mcp.tool
async def define(input: DefineInput) -> Definition:
    """Look up the definition of an English word.

    Returns the first definition found. If the word is unknown, raises a clear error.
    """
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{input.word}"
    try:
        r = await mcp.state.http.get(url)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ValueError(f"word not found: {input.word}") from None
        raise

    data = r.json()
    entry = data[0]
    meaning_block = entry["meanings"][0]
    return Definition(
        word=entry["word"],
        part_of_speech=meaning_block["partOfSpeech"],
        meaning=meaning_block["definitions"][0]["definition"],
    )


@mcp.tool
def reverse_string(text: str) -> str:
    """Reverse the characters in a string."""
    return text[::-1]


# ---------- Resource ----------

@mcp.resource("config://server/version")
def server_version() -> str:
    """Read the server's version string."""
    return "1.0.0"


# ---------- Prompt ----------

@mcp.prompt
def explain_word(word: str) -> str:
    """Generate a prompt that asks an LLM to explain a word in plain language."""
    return (
        f"Explain the word '{word}' in plain language for a 10-year-old. "
        f"Include one example sentence."
    )


# ---------- Run ----------

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport == "stdio":
        logger.info("running on stdio")
        mcp.run()
    elif transport in {"streamable-http", "http"}:
        host = os.environ.get("MCP_HOST", "127.0.0.1")
        port = int(os.environ.get("MCP_PORT", "8000"))
        logger.info(f"running on streamable-http at {host}:{port}")
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        raise ValueError(f"unknown MCP_TRANSPORT: {transport}")
