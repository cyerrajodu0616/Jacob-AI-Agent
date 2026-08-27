"""Out-of-process MCP server that owns the data layer.

This process — and ONLY this process — imports the Postgres/embedder drivers and
holds the DB connection. The agent connects to it over stdio (MCP) and has no way
to reach the database directly: its sole capability is the one tool below.

Run standalone:  python -m rag.server
The agent spawns it automatically via a stdio McpServerConfig (see agent.py).
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

import config
from . import store

SERVER_NAME = "jacob"
TOOL_NAME = "search_knowledge_base"
ALLOWED_TOOL = f"mcp__{SERVER_NAME}__{TOOL_NAME}"

server = MCPServer(
    name=SERVER_NAME,
    instructions=f"Approved product knowledge base for {config.PRODUCT}.",
)


def _strength(r: dict) -> str:
    sim = r.get("vec_sim") or 0.0
    if sim >= 0.70 or (r.get("fts_rank") is not None and sim >= 0.60):
        return "STRONG"
    if sim >= 0.55 or r.get("fts_rank") is not None:
        return "MODERATE"
    return "WEAK"


@server.tool(
    name=TOOL_NAME,
    description=(
        "Search the approved product knowledge base (hybrid semantic + full-text "
        "retrieval) and return the most relevant sections. Call this before "
        "answering any substantive question, and cite the titles you use."
    ),
)
def search_knowledge_base(query: str) -> str:
    """Retrieve approved knowledge for `query`. Returns labelled source text."""
    query = (query or "").strip()
    results = store.hybrid_search(query)
    weak = store.is_weak(results)

    if not results:
        return (
            "No relevant content found in the approved knowledge base. Do not "
            "answer from general knowledge — tell the agent this is not covered "
            "and that a human will follow up."
        )

    top = _strength(results[0])
    overall = {"STRONG": "high", "MODERATE": "medium", "WEAK": "low"}[top]
    lines = [
        f"Retrieved {len(results)} source(s) for query: {query!r}",
        f"Overall retrieval confidence: {overall}. Only answer from STRONG matches "
        "that directly state the fact; MODERATE supports partial answers only; "
        "treat WEAK as not covered.\n",
    ]
    for i, r in enumerate(results, 1):
        pages = r["metadata"].get("pages")
        loc = f" (pages {pages[0]}–{pages[-1]})" if pages else ""
        lines.append(
            f"{i}. [{_strength(r)} match] Title: {r['title']}\n"
            f"   Section: {r['heading']}{loc}\n"
            f"   Content: {r['text']}"
        )
    if weak:
        lines.append(
            "\nNOTE: Retrieval is weak overall — say the topic is not covered by "
            "the approved knowledge instead of stretching these matches."
        )
    return "\n".join(lines)


if __name__ == "__main__":
    server.run("stdio")
