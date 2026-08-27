"""Live application-state capability (out-of-process, read-only).

Jacob's second data-owning package, alongside `rag`. It reads the live memApp
(application state) for an arcId from the platform and projects it down to a
small, agent-safe status summary. Like `rag`, it runs as its own MCP server
process — the agent never imports it and cannot reach the platform directly.
"""
