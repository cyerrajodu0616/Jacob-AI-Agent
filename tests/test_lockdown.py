"""Lock the agent's tool lockdown: the deny-by-default gate + options wiring.

Run:  python -m tests.test_lockdown

Verifies, offline, that:
  • the _permit gate ALLOWS only Jacob's own two MCP tools and DENIES everything
    else — built-ins (Bash/Read/Edit/…) and any host claude.ai integration;
  • build_options() actually sets tools=[], wires can_use_tool, keeps
    permission_mode a non-bypass mode, and lists the two MCP tools + no others.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.pop("ANTHROPIC_API_KEY", None)  # build_options() exits if this is set

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny  # noqa: E402

import agent  # noqa: E402

ALLOWED = (agent.TOOL_KB, agent.TOOL_APPSTATE,
           "mcp__jacob__search_knowledge_base", "mcp__appstate__get_application_state")
DENIED = ("Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebFetch", "WebSearch",
          "NotebookEdit", "mcp__claude_ai_HubSpot__search_tickets",
          "mcp__claude-in-chrome__click", "mcp__evil__exfiltrate", "")


def run() -> int:
    fails: list[str] = []

    for tool in ALLOWED:
        res = asyncio.run(agent._permit(tool, {}, None))
        if not isinstance(res, PermissionResultAllow):
            fails.append(f"gate should ALLOW {tool!r}, got {type(res).__name__}")

    for tool in DENIED:
        res = asyncio.run(agent._permit(tool, {}, None))
        if not isinstance(res, PermissionResultDeny):
            fails.append(f"gate should DENY {tool!r}, got {type(res).__name__}")

    opts = agent.build_options()
    if opts.tools != []:
        fails.append(f"tools should be [] (built-ins removed), got {opts.tools!r}")
    if opts.can_use_tool is not agent._permit:
        fails.append("can_use_tool is not wired to the deny-by-default gate")
    if opts.permission_mode in ("bypassPermissions", "bypass"):
        fails.append(f"permission_mode must not be a bypass mode (got {opts.permission_mode!r})")
    if opts.allowed_tools:
        fails.append("allowed_tools must stay empty so the gate is authoritative "
                     f"(an entry shadows can_use_tool), got {opts.allowed_tools!r}")
    if opts.setting_sources != []:
        fails.append(f"setting_sources should be [] (hermetic), got {opts.setting_sources!r}")
    if "mcp__claude_ai_HubSpot" not in (opts.disallowed_tools or []):
        fails.append("disallowed_tools should include host claude.ai integrations")

    print("gate: allowed", len(ALLOWED), "/ denied", len(DENIED))
    print("tools =", opts.tools, "| permission_mode =", opts.permission_mode,
          "| can_use_tool wired =", opts.can_use_tool is agent._permit)
    print("\n" + ("FAIL:\n  " + "\n  ".join(fails) if fails else "ALL CHECKS PASSED"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
