"""Jacob — minimal conversation agent (Claude Agent SDK, subscription login).

A chat you can hold in the terminal: one session per conversation, so Jacob
remembers earlier turns; replies stream live as they are generated.

Run:
    python agent.py                          # chat (Ctrl-D or /quit to exit)
    python agent.py "What is a monorepo?"    # one-shot

In-chat commands:
    /new    start a fresh conversation (forget everything so far)
    /quit   exit (Ctrl-D works too)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    TextBlock,
)

import config

# The agent process deliberately imports NO data drivers (no psycopg, no httpx,
# no rag.store, no appstate.platform). Its capabilities are two tools, each
# served by a SEPARATE process that owns its own connections:
#   • rag.server       — the approved knowledge base (Postgres + embedder).
#   • appstate.server  — live application status for one arcId (platform read).
# The agent talks to both over stdio (MCP); it cannot reach the database or the
# platform directly, and every live record is PII/underwriting-masked inside the
# appstate process before the agent ever sees it.
MCP_KB = "jacob"
MCP_APPSTATE = "appstate"
TOOL_KB = f"mcp__{MCP_KB}__search_knowledge_base"
TOOL_APPSTATE = f"mcp__{MCP_APPSTATE}__get_application_state"

# The system prompt is a versioned artifact, not code: prompts/system.md.
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "system.md"

# Per-conversation application binding (JACOB_SESSION_ARCID). In the real eApp
# integration the chat opens INSIDE one application; this section scopes the
# session to it. The same env var is inherited by the appstate.server subprocess,
# which HARD-enforces the boundary — this text only makes Jacob graceful about it.
_SESSION_SCOPE = """

## This conversation's application

This chat is open inside one specific application: arcId {arc_id}. "This application", "my app", "the client's application", a bare "status?" — they all mean that one: look it up with arcId {arc_id} directly, and never ask the agent for an arcId. If the agent asks about a DIFFERENT arcId, don't look it up and don't discuss its details — this chat is scoped to the application it was opened from. Say that plainly, point them to open the chat from that other application, and offer a human if they're stuck.
"""


def load_system_prompt() -> str:
    """Read fresh each session, so prompt edits apply on the next conversation."""
    prompt = (
        PROMPT_FILE.read_text(encoding="utf-8")
        .replace("{product_name}", config.PRODUCT_NAME)   # agent-facing name
        .replace("{product_id}", config.PRODUCT)          # internal id (for Jacob's context only)
    )
    arc = os.getenv("JACOB_SESSION_ARCID", "").strip()
    if arc:
        prompt += _SESSION_SCOPE.format(arc_id=arc)
    return prompt


# Deny-by-default tool gate. `tools=[]` removes every built-in tool; this callback
# then hard-denies anything that isn't one of Jacob's own two MCP tools — including
# any host claude.ai integration connected now or later. It is the actual
# guarantee (allowed_tools only auto-approves, it does not remove), and it fails
# safe: an unknown tool is refused, not prompted. `**_` tolerates the SDK calling
# it with 1–3 positional args across versions.
_ALLOWED_TOOL_PREFIXES = (f"mcp__{MCP_KB}__", f"mcp__{MCP_APPSTATE}__")


async def _permit(tool_name, tool_input=None, context=None):
    if isinstance(tool_name, str) and tool_name.startswith(_ALLOWED_TOOL_PREFIXES):
        return PermissionResultAllow()
    return PermissionResultDeny(message=f"{tool_name} is not permitted for Jacob.")


# Host claude.ai / chrome MCP integrations. setting_sources=[] already keeps these
# out; listing them is defense-in-depth so they never enter the tool list at all.
_DISALLOWED_HOST_TOOLS = [
    "mcp__claude_ai_Asana", "mcp__claude_ai_Atlassian", "mcp__claude_ai_Figma",
    "mcp__claude_ai_Gmail", "mcp__claude_ai_Google_Calendar",
    "mcp__claude_ai_Google_Drive", "mcp__claude_ai_HubSpot",
    "mcp__claude_ai_Microsoft_365", "mcp__claude_ai_Ramp", "mcp__claude-in-chrome",
]

DIM = "\033[2m"
CYN = "\033[36m"
RST = "\033[0m"


def build_options() -> ClaudeAgentOptions:
    if os.getenv("ANTHROPIC_API_KEY"):
        sys.exit(
            "[error] ANTHROPIC_API_KEY is set. This project runs strictly on the "
            "Claude subscription login — refusing to start so you aren't billed "
            "against the API key. Run `unset ANTHROPIC_API_KEY` and try again."
        )
    return ClaudeAgentOptions(
        # Pinned to Sonnet (JACOB_MODEL overrides without touching code).
        model=os.getenv("JACOB_MODEL", "claude-sonnet-5"),
        system_prompt=load_system_prompt(),
        # Hermetic: don't inherit CLAUDE.md / settings / MCP servers from this machine.
        setting_sources=[],
        # Two capabilities, each served out-of-process. The SDK spawns each
        # `python -m <pkg>.server` and speaks MCP over its stdio; those
        # subprocesses are the only places the DB / embedder / platform are touched.
        mcp_servers={
            MCP_KB: {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "rag.server"],
            },
            MCP_APPSTATE: {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "appstate.server"],
            },
        },
        # Lockdown (defense in depth). The can_use_tool gate is the SINGLE allow-list —
        # we intentionally do NOT set allowed_tools, because an allowed_tools entry
        # auto-approves a tool BEFORE the callback and would shadow the gate (the SDK
        # warns about exactly that). So every tool call falls through to _permit:
        #  • tools=[]         — remove ALL built-in tools (Bash/Read/Edit/Grep/web…);
        #    allowed_tools would only auto-approve built-ins, never remove them.
        #  • can_use_tool     — deny-by-default: ONLY Jacob's two MCP tools are allowed,
        #    so any built-in or host integration (now, or connected later) is refused.
        #  • disallowed_tools — also keep host claude.ai integrations out of the list.
        # permission_mode="default" (a non-bypass mode) is required for the gate to be
        # consulted; the ClaudeSDKClient we use keeps the stream open so it can answer.
        tools=[],
        can_use_tool=_permit,
        disallowed_tools=_DISALLOWED_HOST_TOOLS,
        permission_mode="default",
        max_turns=8,
        # Stream partial output so replies render live, like a chat.
        include_partial_messages=True,
    )


async def ask(client: ClaudeSDKClient, question: str) -> None:
    await client.query(question)
    streamed = False
    async for msg in client.receive_response():
        if isinstance(msg, StreamEvent):
            event = msg.event
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta.get("text", ""), end="", flush=True)
                    streamed = True
        elif isinstance(msg, AssistantMessage):
            # Fallback if no deltas arrived (e.g. streaming unavailable).
            if not streamed:
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        print(block.text, end="", flush=True)
        elif isinstance(msg, ResultMessage):
            print()
            meta = []
            if msg.num_turns is not None:
                meta.append(f"turns={msg.num_turns}")
            if msg.total_cost_usd is not None:
                meta.append(f"cost=${msg.total_cost_usd:.4f}")
            if meta:
                print(f"{DIM}{'  '.join(meta)}{RST}")


async def chat() -> None:
    print("Jacob — chat away. /new = fresh conversation, /quit or Ctrl-D = exit.")
    while True:  # each pass = one conversation (one client session)
        async with ClaudeSDKClient(options=build_options()) as client:
            while True:
                try:
                    line = (await asyncio.to_thread(input, f"\n{CYN}you>{RST} ")).strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                if not line:
                    continue
                if line in ("/quit", "/exit"):
                    return
                if line == "/new":
                    print(f"{DIM}started a new conversation{RST}")
                    break  # drop this client; outer loop opens a fresh one
                print(f"\n{CYN}jacob>{RST} ", end="", flush=True)
                await ask(client, line)


async def main() -> None:
    once = " ".join(sys.argv[1:]).strip() or None
    if once:
        async with ClaudeSDKClient(options=build_options()) as client:
            await ask(client, once)
        return
    await chat()


if __name__ == "__main__":
    asyncio.run(main())
