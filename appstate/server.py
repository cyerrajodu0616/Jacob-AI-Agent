"""Out-of-process MCP server for LIVE application-state lookups.

Jacob's second data-owning process (alongside rag.server). ONLY this process
reaches the platform network; the agent talks to it over stdio (MCP) and cannot
reach the platform directly. The memApp it fetches is projected to a small,
agent-safe summary inside this process (project.summarize) — raw PII and
underwriting internals never leave here.

Run standalone:  python -m appstate.server
The agent spawns it automatically via a stdio McpServerConfig (see agent.py).
"""
from __future__ import annotations

import os
import re

from mcp.server.mcpserver import MCPServer

import config
from . import platform, project

SERVER_NAME = "appstate"
TOOL_NAME = "get_application_state"
ALLOWED_TOOL = f"mcp__{SERVER_NAME}__{TOOL_NAME}"

# arcIds look like ARCF26216Z479 — "ARC" + a letter + a date/check block. They are
# CASE-SENSITIVE (a real id can carry a lowercase char), so validate loosely and
# never alter the caller's string.
_ARCID = re.compile(r"^ARC[A-Za-z0-9]{6,20}$")

server = MCPServer(
    name=SERVER_NAME,
    instructions=f"Live application status for {config.PRODUCT_NAME} applications (read-only).",
)


@server.tool(
    name=TOOL_NAME,
    description=(
        "Look up the LIVE status of one specific in-flight application by its arcId "
        "(e.g. 'ARCF26216Z479'). Use it when an agent asks where their application "
        "is, what it's waiting on, whether their client received a consent or "
        "signature link, or the decision outcome. Returns a plain-language status "
        "summary. arcIds are case-sensitive — pass exactly what the agent gave you."
    ),
)
def get_application_state(arc_id: str) -> str:
    """Fetch and project one application's live status for `arc_id`."""
    arc_id = (arc_id or "").strip()
    # Per-conversation binding: when the chat is opened inside one application
    # (JACOB_SESSION_ARCID, inherited from the session that spawned us), ONLY
    # that arcId may be looked up. Enforced here — at the process boundary —
    # not just in the prompt. Exact match: arcIds are case-sensitive.
    bound = os.getenv("JACOB_SESSION_ARCID", "").strip()
    if bound and arc_id != bound:
        return (f"SCOPE: this chat is bound to application {bound} and can only look "
                "up that application. Do not retry with the other arcId. Tell the "
                "agent this conversation is tied to the application it was opened "
                "from — to check a different application they should open the chat "
                "from that one; a human can help otherwise.")
    if not _ARCID.match(arc_id):
        return ("That doesn't look like a valid application id — they look like "
                "'ARCF26216Z479'. arcIds are CASE-SENSITIVE: do NOT retry with a "
                "case-corrected or guessed id (a 'fixed' id can silently be a "
                "different application). Ask the agent to re-send the arcId "
                "exactly as it appears on their screen.")
    try:
        memapp = platform.read_memapp(arc_id)
    except platform.Unavailable:
        return ("TOOL_ERROR: the application system couldn't be reached right now. "
                "Tell the agent you're having trouble pulling it up and to try again "
                "in a moment — do not present this as 'not found' or out of scope.")
    if not memapp:
        return (f"Couldn't find an application under {arc_id}. Tell the agent you're not "
                "pulling it up and ask them to double-check the arcId (they're case-sensitive).")
    summary = project.summarize(memapp, arc_id)
    if summary is None:
        # Wrong product. The agent works in THIS product, so don't announce "that's not
        # a NewBridge application" — lead with "not finding it", then a soft fallback.
        return (f"Couldn't pull up {arc_id} as one of the applications you cover here. Tell the "
                "agent you're not finding it and ask them to double-check the arcId; if it's "
                "correct, it may be for a different product than yours — offer to point them to "
                "the right person. Don't call out 'NewBridge' or lean on product names.")
    return summary


if __name__ == "__main__":
    server.run("stdio")
