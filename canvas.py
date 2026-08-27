"""Live build canvas — see the agent like an n8n workflow, in your browser.

Zero dependencies (stdlib only). It introspects agent.py on every poll, so the
board always shows what is actually built right now: the AI Agent node, its
Chat Model / Memory / Tools sockets, and the options each node carries.

Run:
    python canvas.py            # serves http://127.0.0.1:8712
    JACOB_CANVAS_PORT=9000 python canvas.py

Leave it running while we build — the page refreshes itself every 1.5s.
"""
from __future__ import annotations

import asyncio
import ast
import json
import os
import queue
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT = HERE / "agent.py"
PORT = int(os.getenv("JACOB_CANVAS_PORT", "8712"))

# ── chat bridge: the same agent, hosted in this server ───────────────────────
# NOTE: like the agent, this process imports NO data drivers. It hosts the
# ClaudeSDKClient, which spawns the out-of-process MCP servers (rag.server for
# knowledge, appstate.server for live application state). Postgres / embedder /
# platform reads live only in those subprocesses.
try:
    from agent import build_options
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeSDKClient,
        ResultMessage,
        StreamEvent,
        TextBlock,
    )
    CHAT_AVAILABLE = True
except Exception:  # canvas still serves the board without chat
    CHAT_AVAILABLE = False

_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()
_client: "ClaudeSDKClient | None" = None
_lock = asyncio.Lock()

# Per-conversation application binding (the real eApp integration opens this
# chat INSIDE one application). Set from the arcId box on "New chat"; exported
# as JACOB_SESSION_ARCID so the session's prompt scopes to it AND the spawned
# appstate.server subprocess hard-enforces it. Empty = unscoped dev chat.
_session_arcid = os.getenv("JACOB_SESSION_ARCID", "").strip()
_ARCID_RE = re.compile(r"^ARC[A-Za-z0-9]{6,20}$")


def _bound_options():
    """build_options() with this conversation's arcId binding exported first —
    the CLI and its MCP subprocesses inherit the env var at spawn."""
    if _session_arcid:
        os.environ["JACOB_SESSION_ARCID"] = _session_arcid
    else:
        os.environ.pop("JACOB_SESSION_ARCID", None)
    return build_options()


async def _turn(text: str, q: "queue.Queue") -> None:
    """One conversation turn; chunks stream into q, None terminates."""
    global _client
    try:
        async with _lock:
            if _client is None:
                q.put({"t": "status", "text": "starting session…"})
                _client = ClaudeSDKClient(options=_bound_options())
                await _client.connect()
            await _client.query(text)
            streamed = False
            async for msg in _client.receive_response():
                if isinstance(msg, StreamEvent):
                    ev = msg.event
                    if ev.get("type") == "content_block_start":
                        cb = ev.get("content_block", {})
                        name = str(cb.get("name", ""))
                        if cb.get("type") == "tool_use" and name.startswith("mcp__"):
                            q.put({"t": "tool", "name": name.split("__")[-1]})
                    elif ev.get("type") == "content_block_delta":
                        d = ev.get("delta", {})
                        if d.get("type") == "text_delta":
                            q.put({"t": "delta", "text": d.get("text", "")})
                            streamed = True
                elif isinstance(msg, AssistantMessage):
                    if not streamed:
                        for b in msg.content:
                            if isinstance(b, TextBlock):
                                q.put({"t": "delta", "text": b.text})
                elif isinstance(msg, ResultMessage):
                    q.put({"t": "result", "turns": msg.num_turns, "cost": msg.total_cost_usd})
    except (Exception, SystemExit) as e:
        q.put({"t": "error", "text": str(e) or e.__class__.__name__})
    finally:
        q.put(None)


async def _reset() -> None:
    """Drop the session — the browser-side 'New chat' (= /new)."""
    global _client
    async with _lock:
        if _client is not None:
            try:
                await _client.disconnect()
            except Exception:
                pass
            _client = None


async def _warm() -> None:
    """Connect the session ahead of the first message so turn one is instant."""
    global _client
    async with _lock:
        if _client is None:
            try:
                c = ClaudeSDKClient(options=_bound_options())
                await c.connect()
                _client = c
            except (Exception, SystemExit):
                pass  # first real turn retries and surfaces the error


def _cli_version() -> str:
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip().split()[0]
    except Exception:
        return "?"


def _sdk_version() -> str:
    try:
        import importlib.metadata
        return importlib.metadata.version("claude-agent-sdk")
    except Exception:
        return "?"


CLI_VERSION = _cli_version()
SDK_VERSION = _sdk_version()


def read_state() -> dict:
    """Parse agent.py and report what is actually wired up right now."""
    state: dict = {
        "ok": AGENT.exists(),
        "file": AGENT.name,
        "lines": 0,
        "mtime": None,
        "system_prompt": None,
        "options": {},
        "functions": [],
        "sdk": SDK_VERSION,
        "cli": CLI_VERSION,
        "session_arcid": _session_arcid,
    }
    if not AGENT.exists():
        return state

    src = AGENT.read_text(encoding="utf-8")
    state["lines"] = src.count("\n") + 1
    state["mtime"] = time.strftime("%H:%M:%S", time.localtime(AGENT.stat().st_mtime))

    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        state["error"] = f"agent.py has a syntax error: {e}"
        return state

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "SYSTEM_PROMPT":
                    try:
                        state["system_prompt"] = ast.literal_eval(node.value)
                    except Exception:
                        state["system_prompt"] = ast.unparse(node.value)
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name == "ClaudeAgentOptions":
                for kw in node.keywords:
                    if kw.arg is None:
                        continue
                    try:
                        state["options"][kw.arg] = ast.literal_eval(kw.value)
                    except Exception:
                        state["options"][kw.arg] = ast.unparse(kw.value)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            state["functions"].append(node.name)

    if state["options"].get("system_prompt") == "SYSTEM_PROMPT":
        state["options"]["system_prompt"] = "(SYSTEM_PROMPT above)"
    # The prompt now lives in prompts/system.md — surface it from the file.
    if not isinstance(state.get("system_prompt"), str) or state["system_prompt"].startswith("("):
        prompt_file = HERE / "prompts" / "system.md"
        if prompt_file.exists():
            text = prompt_file.read_text(encoding="utf-8")
            state["system_prompt"] = (
                text[:700] + f"\n… (full prompt: prompts/system.md, {len(text)} chars)"
                if len(text) > 700 else text
            )
    m = state["options"].get("model")
    if isinstance(m, str) and m.startswith("os.getenv("):
        try:
            state["options"]["model"] = eval(m, {"os": os})  # resolve env-default expr from our own source
        except Exception:
            pass
    # Resolve the hardened options that AST-parse to bare names/exprs, so the board
    # shows what is actually wired (not "_permit" / "_DISALLOWED_HOST_TOOLS"), and
    # surface the two out-of-process MCP servers Jacob talks to.
    try:
        import agent as _a
        import config as _cfg
        opts = state["options"]
        opts["allowed_tools"] = [_a.TOOL_KB, _a.TOOL_APPSTATE]     # the two MCP tools
        if isinstance(opts.get("can_use_tool"), str):
            opts["can_use_tool"] = "deny-by-default gate (_permit)"
        if not isinstance(opts.get("disallowed_tools"), list):
            opts["disallowed_tools"] = list(_a._DISALLOWED_HOST_TOOLS)
        state["servers"] = [
            {"id": "n-tools", "server": _a.MCP_KB,
             "module": "rag.server", "tool": _a.TOOL_KB.split("__")[-1]},
            {"id": "n-appstate", "server": _a.MCP_APPSTATE,
             "module": "appstate.server", "tool": _a.TOOL_APPSTATE.split("__")[-1]},
        ]
        state["platform_env"] = _cfg.PLATFORM_ENV
    except Exception:
        pass
    return state


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jacob — Live Build Canvas</title>
<style>
  :root {
    --bg: #1D2126; --dot: #2A3138; --node: #262D35; --node2: #2B333C;
    --edge: #3C4650; --text: #D9E1E8; --dim: #8A97A3; --faint: #5C6873;
    --teal: #4CC9C0; --teal-soft: rgba(76,201,192,.14);
    --ok: #74CE8C; --amber: #E0A458; --ghost: #5B6773;
    --mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;
    --sans: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body { background: var(--bg); color: var(--text); font-family: var(--sans); display: flex; flex-direction: column; }

  .topbar {
    display: flex; align-items: center; gap: .9rem; padding: .6rem 1rem;
    border-bottom: 1px solid var(--edge); background: #20252B; flex-wrap: wrap;
  }
  .wfname { font-weight: 600; font-size: .95rem; }
  .pill {
    font-family: var(--mono); font-size: .68rem; padding: .18rem .55rem; border-radius: 999px;
    border: 1px solid var(--edge); color: var(--dim);
  }
  .pill.live { color: var(--ok); border-color: rgba(116,206,140,.4); }
  .pill.live::before { content: "●"; margin-right: .35rem; animation: blink 2s infinite; }
  @keyframes blink { 50% { opacity: .35; } }
  .spacer { flex: 1; }
  .meta { font-family: var(--mono); font-size: .68rem; color: var(--faint); }

  .main { flex: 1; display: flex; min-height: 0; }
  .canvas-wrap { flex: 1; overflow: auto; position: relative; }
  .stage {
    position: relative; width: 1080px; height: 640px; margin: 0 auto;
    background-image: radial-gradient(var(--dot) 1.1px, transparent 1.1px);
    background-size: 22px 22px;
  }
  svg.wires { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
  .wire { fill: none; stroke: var(--teal); stroke-width: 2; opacity: .75;
          stroke-dasharray: 6 6; animation: flow 1.1s linear infinite; }
  .wire.quiet { stroke: var(--dim); animation: none; stroke-dasharray: none; opacity: .5; }
  .wire.ghost { stroke: var(--ghost); opacity: .55; stroke-dasharray: 3 7; animation: none; }
  @keyframes flow { to { stroke-dashoffset: -12; } }
  @media (prefers-reduced-motion: reduce) { .wire { animation: none; } .pill.live::before { animation: none; } }

  .node {
    position: absolute; background: var(--node); border: 1px solid var(--edge);
    border-radius: 8px; padding: .6rem .75rem; cursor: grab; user-select: none;
    min-width: 150px; box-shadow: 0 3px 14px rgba(0,0,0,.28);
  }
  .node:active { cursor: grabbing; }
  .node.selected { border-color: var(--teal); box-shadow: 0 0 0 2px var(--teal-soft), 0 3px 14px rgba(0,0,0,.3); }
  .node .kind { font-family: var(--mono); font-size: .6rem; letter-spacing: .14em;
                text-transform: uppercase; color: var(--faint); margin-bottom: .25rem; }
  .node .name { font-weight: 600; font-size: .85rem; }
  .node .sub  { font-family: var(--mono); font-size: .68rem; color: var(--dim); margin-top: .3rem; }
  .node .status { font-family: var(--mono); font-size: .65rem; margin-top: .4rem; }
  .status.ok { color: var(--ok); } .status.plan { color: var(--amber); }

  .node.agent { background: var(--node2); border-width: 1.5px; min-width: 230px; }
  .ports { display: flex; justify-content: space-between; gap: .5rem; margin-top: .65rem;
           border-top: 1px dashed var(--edge); padding-top: .5rem; }
  .port { font-family: var(--mono); font-size: .6rem; color: var(--dim); text-align: center; flex: 1; }
  .port i { display: block; font-style: normal; color: var(--teal); font-size: .7rem; line-height: 1; margin-bottom: .2rem; }
  .port.empty i { color: var(--ghost); }

  .node.ghost { border-style: dashed; border-color: var(--ghost); background: transparent; box-shadow: none; }
  .node.ghost .name { color: var(--dim); }

  .panel {
    width: 330px; border-left: 1px solid var(--edge); background: #20252B;
    padding: 1rem 1.1rem 1.4rem; overflow-y: auto;
  }
  .panel h2 { font-size: .95rem; margin: 0 0 .15rem; }
  .panel .ptype { font-family: var(--mono); font-size: .65rem; color: var(--teal);
                  letter-spacing: .12em; text-transform: uppercase; }
  .panel .pdesc { color: var(--dim); font-size: .82rem; margin: .5rem 0 .9rem; line-height: 1.5; }
  .kv { display: grid; gap: .55rem; }
  .kv .row { border: 1px solid var(--edge); border-radius: 6px; padding: .5rem .6rem; }
  .kv .k { font-family: var(--mono); font-size: .64rem; color: var(--faint); margin-bottom: .2rem; }
  .kv .v { font-family: var(--mono); font-size: .74rem; color: var(--text);
           white-space: pre-wrap; word-break: break-word; line-height: 1.5; }
  .kv .v.dimv { color: var(--dim); font-family: var(--sans); font-size: .8rem; }

  /* ---- chat panel ---- */
  .chat { border-top: 1px solid var(--edge); background: #20252B; display: flex; flex-direction: column; height: 280px; }
  .chat-head { display: flex; align-items: center; gap: .7rem; padding: .45rem .95rem; border-bottom: 1px solid var(--edge); }
  .chat-head .t { font-size: .8rem; font-weight: 600; }
  .chat-head .hint { font-family: var(--mono); font-size: .65rem; color: var(--faint); }
  .chat-head .scope { font-family: var(--mono); font-size: .65rem; color: var(--teal); }
  .chat-head input {
    background: var(--node); border: 1px solid var(--edge); border-radius: 6px;
    color: var(--text); font-family: var(--mono); font-size: .7rem;
    padding: .28rem .55rem; width: 172px; outline: none;
  }
  .chat-head input:focus { border-color: var(--teal); }
  .btn {
    background: var(--teal-soft); color: var(--teal); border: 1px solid var(--teal);
    border-radius: 6px; font-family: var(--mono); font-size: .7rem; padding: .32rem .75rem; cursor: pointer;
  }
  .btn:hover { background: rgba(76,201,192,.25); }
  .btn:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; }
  .chatlog {
    flex: 1; overflow-y: auto; padding: .7rem 1rem; font-family: var(--mono);
    font-size: .78rem; line-height: 1.65; display: flex; flex-direction: column; gap: .5rem;
  }
  .msg { white-space: pre-wrap; word-break: break-word; }
  .msg code { background: rgba(76, 201, 192, .12); padding: 0 .3rem; border-radius: 3px; }
  .msg.you::before   { content: "you> ";   color: var(--teal); font-weight: 700; }
  .msg.jacob::before { content: "jacob> "; color: var(--teal); }
  .msg.jacob.err { color: var(--amber); }
  .msg.jacob.pending { color: var(--faint); font-style: italic; }
  .msg.jacob.pending::after { content: " …"; animation: pulse 1.2s ease-in-out infinite; }
  .msg.jacob.typing::after { content: "▍"; color: var(--teal); margin-left: 1px; animation: blink .8s steps(2) infinite; }
  @keyframes pulse { 50% { opacity: .3; } }
  .btn:disabled { opacity: .45; cursor: default; }
  .btn:disabled:hover { background: var(--teal-soft); }
  .msg.meta { color: var(--faint); font-size: .66rem; }
  .msg.tool { color: var(--faint); font-size: .68rem; }
  .msg.tool::before { content: "⚙ "; color: var(--teal); }
  .msg.divider { color: var(--faint); font-size: .66rem; border-top: 1px dashed var(--edge); padding-top: .5rem; }
  .chat-row { display: flex; gap: .6rem; padding: .55rem 1rem .7rem; border-top: 1px solid var(--edge); }
  .chat-row input {
    flex: 1; background: var(--node); border: 1px solid var(--edge); border-radius: 6px;
    color: var(--text); font-family: var(--mono); font-size: .8rem; padding: .5rem .7rem; outline: none;
  }
  .chat-row input:focus { border-color: var(--teal); }
  body.streaming .wire { animation-duration: .35s; opacity: 1; }

  @media (max-width: 900px) {
    .main { flex-direction: column; }
    .panel { width: auto; border-left: none; border-top: 1px solid var(--edge); }
  }
</style>
</head>
<body>
  <div class="topbar">
    <span class="wfname">Jacob — AI Agent</span>
    <span class="pill">phase 1 · live application state</span>
    <span class="pill live">watching agent.py</span>
    <span class="spacer"></span>
    <span class="meta" id="meta">…</span>
    <span class="meta" id="checked"></span>
  </div>

  <div class="main">
    <div class="canvas-wrap">
      <div class="stage" id="stage">
        <svg class="wires" id="wires"></svg>

        <div class="node" id="n-trigger" style="left:40px; top:160px;">
          <div class="kind">trigger</div>
          <div class="name">Terminal chat</div>
          <div class="sub">you&gt; …</div>
          <div class="status ok">● listening</div>
        </div>

        <div class="node agent" id="n-agent" style="left:390px; top:130px;">
          <div class="kind">ai agent</div>
          <div class="name">Jacob</div>
          <div class="sub" id="agent-sub">agent.py</div>
          <div class="ports">
            <div class="port" id="p-model"><i>◆</i>Chat Model</div>
            <div class="port" id="p-memory"><i>◆</i>Memory</div>
            <div class="port" id="p-tools"><i>◆</i><span id="tools-port-label">Tools (2)</span></div>
          </div>
        </div>

        <div class="node" id="n-output" style="left:830px; top:160px;">
          <div class="kind">output</div>
          <div class="name">Streamed reply</div>
          <div class="sub">jacob&gt; … <span style="color:var(--faint)">+ turns/cost</span></div>
          <div class="status ok" id="out-status">● live deltas</div>
        </div>

        <div class="node" id="n-model" style="left:270px; top:430px;">
          <div class="kind">chat model</div>
          <div class="name" id="model-name">claude-sonnet-5</div>
          <div class="sub" id="model-sub">pinned · via claude CLI · subscription</div>
          <div class="status ok">● wired</div>
        </div>

        <div class="node" id="n-memory" style="left:540px; top:430px;">
          <div class="kind">memory</div>
          <div class="name">Session context</div>
          <div class="sub">one session per conversation · /new resets</div>
          <div class="status ok">● wired · verified</div>
        </div>

        <div class="node" id="n-tools" style="left:772px; top:372px;">
          <div class="kind">tool · mcp server</div>
          <div class="name" id="tools-name">Knowledge base</div>
          <div class="sub" id="tools-sub">rag.server · search_knowledge_base</div>
          <div class="status ok" id="tools-status">● wired</div>
        </div>

        <div class="node" id="n-appstate" style="left:772px; top:512px;">
          <div class="kind">tool · mcp server</div>
          <div class="name" id="appstate-name">Live application state</div>
          <div class="sub" id="appstate-sub">appstate.server · get_application_state</div>
          <div class="status ok" id="appstate-status">● wired · live-validated</div>
        </div>
      </div>
    </div>

    <aside class="panel" id="panel"></aside>
  </div>

  <div class="chat">
    <div class="chat-head">
      <span class="t">Chat</span>
      <span class="hint">same agent, live session — context carries across turns</span>
      <span class="scope" id="scopelbl"></span>
      <span class="spacer"></span>
      <input id="arcinp" type="text" placeholder="arcId — scope next chat" autocomplete="off"
             spellcheck="false" title="Bind the next conversation to one application (like the in-eApp chat). Empty = unscoped.">
      <button class="btn" id="newchat">New chat (/new)</button>
    </div>
    <div class="chatlog" id="chatlog">
      <div class="msg meta">Ask Jacob something — the wires above light up while it answers.</div>
    </div>
    <div class="chat-row">
      <input id="chatinp" type="text" placeholder="Type a message and press Enter…" autocomplete="off">
      <button class="btn" id="sendbtn">Send</button>
    </div>
  </div>

<script>
  const $ = (id) => document.getElementById(id);
  const stage = $("stage"), wiresSvg = $("wires"), panel = $("panel");
  let STATE = null, selected = "n-agent";

  const WIRES = [
    { from: ["n-trigger", "right"], to: ["n-agent", "left"],  cls: "wire" },
    { from: ["n-agent", "right"],   to: ["n-output", "left"], cls: "wire" },
    { from: ["p-model", "bottom"],  to: ["n-model", "top"],   cls: "wire quiet" },
    { from: ["p-memory", "bottom"], to: ["n-memory", "top"],  cls: "wire quiet" },
    { from: ["p-tools", "bottom"],  to: ["n-tools", "top"],     cls: "wire quiet", id: "w-tools" },
    { from: ["p-tools", "bottom"],  to: ["n-appstate", "top"],  cls: "wire quiet", id: "w-appstate" },
  ];

  function anchor(id, side) {
    const el = $(id), s = stage.getBoundingClientRect(), r = el.getBoundingClientRect();
    const x = r.left - s.left, y = r.top - s.top;
    if (side === "left")   return { x: x,             y: y + r.height / 2 };
    if (side === "right")  return { x: x + r.width,   y: y + r.height / 2 };
    if (side === "top")    return { x: x + r.width/2, y: y };
    return { x: x + r.width / 2, y: y + r.height };
  }

  function drawWires() {
    wiresSvg.innerHTML = "";
    for (const w of WIRES) {
      const a = anchor(...w.from), b = anchor(...w.to);
      const horiz = w.from[1] === "right" || w.from[1] === "left";
      const c = horiz ? Math.max(40, Math.abs(b.x - a.x) / 2) : Math.max(30, Math.abs(b.y - a.y) / 2);
      const d = horiz
        ? `M ${a.x} ${a.y} C ${a.x + c} ${a.y}, ${b.x - c} ${b.y}, ${b.x} ${b.y}`
        : `M ${a.x} ${a.y} C ${a.x} ${a.y + c}, ${b.x} ${b.y - c}, ${b.x} ${b.y}`;
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", d); p.setAttribute("class", w.cls);
      if (w.id) p.id = w.id;
      wiresSvg.appendChild(p);
    }
  }

  // drag nodes
  for (const el of document.querySelectorAll(".node")) {
    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      select(el.id);
      const sx = e.clientX, sy = e.clientY, ox = el.offsetLeft, oy = el.offsetTop;
      el.setPointerCapture(e.pointerId);
      const move = (ev) => {
        el.style.left = Math.max(0, Math.min(stage.clientWidth - el.offsetWidth, ox + ev.clientX - sx)) + "px";
        el.style.top  = Math.max(0, Math.min(stage.clientHeight - el.offsetHeight, oy + ev.clientY - sy)) + "px";
        drawWires();
      };
      const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
    });
  }

  function row(k, v, dim) {
    return `<div class="row"><div class="k">${k}</div><div class="v${dim ? " dimv" : ""}">${v}</div></div>`;
  }

  function panelContent(id) {
    const s = STATE || {}, o = s.options || {};
    const fmt = (x) => x === undefined ? "—" : (typeof x === "string" ? x : JSON.stringify(x));
    if (id === "n-agent") return {
      type: "AI Agent · agent.py", title: "Jacob",
      desc: "The program we wrote. Reads your line, sends it into the session, prints the stream.",
      rows: row("system prompt", fmt(s.system_prompt)) +
            row("setting_sources", fmt(o.setting_sources) + "   → hermetic: nothing from this machine (no CLAUDE.md / host MCP)") +
            row("tools", fmt(o.tools) + "   → built-ins removed (Bash/Read/Edit/Grep/web…)") +
            row("can_use_tool", fmt(o.can_use_tool) + "   → only Jacob's 2 MCP tools pass; all else denied") +
            row("permission_mode", fmt(o.permission_mode) + "   → non-bypass, so the gate is consulted") +
            row("disallowed_tools", (Array.isArray(o.disallowed_tools) ? o.disallowed_tools.length : 0) + " host claude.ai integrations blocked (defense in depth)") +
            row("include_partial_messages", fmt(o.include_partial_messages) + "   → live streaming") +
            row("guardrail", "ANTHROPIC_API_KEY set → refuses to start (exit 1)") +
            row("functions", (s.functions || []).join("()  ") + "()"),
    };
    if (id === "n-trigger") return {
      type: "Trigger · stdin", title: "Terminal chat",
      desc: "Where a turn begins. Two modes, three commands.",
      rows: row("chat mode", "python agent.py — REPL at you>") +
            row("one-shot", 'python agent.py "question"') +
            row("commands", "/new  fresh conversation\n/quit  exit (Ctrl-D too)") +
            row("detail", "input() runs off the event loop (asyncio.to_thread)", true),
    };
    if (id === "n-output") return {
      type: "Output · stdout", title: "Streamed reply",
      desc: "How the answer reaches you.",
      rows: row("stream", "StreamEvent text deltas printed as they arrive") +
            row("fallback", "whole AssistantMessage if no deltas came") +
            row("meta", "ResultMessage → dim line: turns=N cost=$…"),
    };
    if (id === "n-model") return {
      type: "Chat Model", title: $("model-name").textContent,
      desc: "The brain. Pinned to Claude Sonnet so it can't drift with the CLI's saved default; JACOB_MODEL overrides without touching code.",
      rows: row("model", fmt(o.model)) +
            row("runtime", "claude CLI " + fmt(s.cli) + " · background subprocess") +
            row("sdk", "claude-agent-sdk " + fmt(s.sdk)) +
            row("auth", "subscription login (claude login) — no API key anywhere"),
    };
    if (id === "n-memory") return {
      type: "Memory", title: "Session context",
      desc: "Not code we wrote — it falls out of keeping one ClaudeSDKClient session open across turns.",
      rows: row("scope", "one conversation = one session") +
            row("reset", "/new closes the session, opens a fresh one") +
            row("verified", 'remembered "4711" across turns; forgot it after /new'),
    };
    if (id === "n-tools") return {
      type: "Tool · MCP server (out-of-process)", title: "Knowledge base",
      desc: "Approved product knowledge, retrieved and cited. Runs as its own process (python -m rag.server); the agent reaches it only over stdio and never touches the database itself.",
      rows: row("tool", "search_knowledge_base") +
            row("retrieval", "hybrid: pgvector cosine (mxbai-embed-large, 1024d)\n+ Postgres full-text, RRF-fused") +
            row("grounding", "weak or empty retrieval → \"not covered\",\nnever answered from general knowledge") +
            row("store", "postgres schema 'jacob' · pgvector\ningest: python -m rag.ingest add --product 511801 <files>"),
    };
    if (id === "n-appstate") return {
      type: "Tool · MCP server (out-of-process)", title: "Live application state",
      desc: "One application's live status by arcId. Its own process (python -m appstate.server) reads the platform, then masks + projects to an agent-safe summary before the agent ever sees it.",
      rows: row("tool", "get_application_state(arc_id)") +
            row("source", "live memApp via platform-infra (" + fmt(s.platform_env) + ", read-only)") +
            row("safety", "strict allowlist projection + fail-closed scrub:\nno PII, no underwriting internals, no internal codes") +
            row("shows", "status · decision outcome · progress · offer ·\nnotifications · timeline — NewBridge apps only") +
            row("verified", "live-validated on a real production application"),
    };
    return { type: "", title: "", desc: "", rows: "" };
  }

  function select(id) {
    selected = id;
    document.querySelectorAll(".node").forEach((n) => n.classList.toggle("selected", n.id === id));
    const c = panelContent(id);
    panel.innerHTML = `<div class="ptype">${c.type}</div><h2>${c.title}</h2>
      <p class="pdesc">${c.desc}</p><div class="kv">${c.rows}</div>`;
  }

  function applyState(s) {
    STATE = s;
    const o = s.options || {};
    $("meta").textContent =
      `${s.file} · ${s.lines} lines · saved ${s.mtime || "?"}`;
    $("agent-sub").textContent = `agent.py · ${(s.functions || []).length} functions`;
    // Both tool nodes (Knowledge base + Live application state) are statically
    // wired on the board; here we just reflect the resolved count on port + wires.
    const tools = Array.isArray(o.allowed_tools) ? o.allowed_tools : [];
    $("p-tools").classList.toggle("empty", tools.length === 0);
    $("tools-port-label").textContent = tools.length ? ("Tools (" + tools.length + ")") : "Tools";
    for (const wid of ["w-tools", "w-appstate"]) {
      const w = $(wid); if (w) w.setAttribute("class", tools.length ? "wire quiet" : "wire ghost");
    }
    $("out-status").textContent = o.include_partial_messages ? "● live deltas" : "● whole messages";
    if (o.model) { $("model-name").textContent = o.model; $("model-sub").textContent = "pinned · via claude CLI"; }
    $("scopelbl").textContent = s.session_arcid ? ("⛨ scoped to " + s.session_arcid) : "";
    if (s.session_arcid && !$("arcinp").value) $("arcinp").value = s.session_arcid;
    select(selected);
    drawWires();
  }

  let last = "";
  async function poll() {
    try {
      const r = await fetch("/state.json", { cache: "no-store" });
      const txt = await r.text();
      $("checked").textContent = "checked " + new Date().toLocaleTimeString();
      if (txt !== last) {
        last = txt;
        applyState(JSON.parse(txt));
      }
    } catch (e) { /* server briefly away — keep last view */ }
  }
  poll();
  setInterval(poll, 1500);
  window.addEventListener("resize", drawWires);

  // ---- chat ----
  const log = $("chatlog"), inp = $("chatinp"), sendbtn = $("sendbtn");
  let sending = false;
  const outbox = [];   // messages typed while a reply is in flight
  const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;

  function nearBottom() { return log.scrollHeight - log.scrollTop - log.clientHeight < 80; }
  function autoscroll() { if (nearBottom()) log.scrollTop = log.scrollHeight; }

  function bubble(cls, text) {
    const d = document.createElement("div");
    d.className = "msg " + cls;
    if (text) d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  // Minimal markdown for replies: bold, inline code, bullets. Everything is
  // HTML-escaped first; the model's text can never inject markup.
  function mdRender(s) {
    return s
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>")
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/^[-*] /gm, "• ")
      .replace(/^#{1,4} (.+)$/gm, "<b>$1</b>");
  }

  // Typewriter: deltas land in a buffer; frames drain it at a steady pace,
  // speeding up when the backlog grows so we never fall behind the model.
  function makeTyper(el) {
    let buf = "", raw = "", finished = false, resolveDone;
    const done = new Promise((r) => (resolveDone = r));
    function frame() {
      if (buf.length) {
        const n = REDUCE ? buf.length : Math.min(Math.max(2, Math.ceil(buf.length / 15)), 30);
        raw += buf.slice(0, n);
        buf = buf.slice(n);
        el.classList.remove("pending");
        el.classList.add("typing");
        el.innerHTML = mdRender(raw);
        autoscroll();
      }
      if (!buf.length && finished) { el.classList.remove("typing"); resolveDone(raw); return; }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    return {
      push: (t) => { buf += t; },
      finish: () => { finished = true; },
      fail: (t) => {
        buf = ""; finished = true;
        el.classList.remove("pending", "typing");
        el.classList.add("err");
        el.textContent = t;
      },
      done,
    };
  }

  function setBusy(b) {
    sending = b;
    sendbtn.disabled = b;
    document.body.classList.toggle("streaming", b);
  }

  async function run(text, alreadyBubbled) {
    setBusy(true);
    if (!alreadyBubbled) bubble("you", text);
    const jb = bubble("jacob", "");
    jb.classList.add("pending");
    const typer = makeTyper(jb);
    let gotText = false;
    try {
      const r = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 1);
          if (!line) continue;
          const m = JSON.parse(line);
          if (m.t === "delta") { typer.push(m.text); gotText = true; }
          else if (m.t === "status") { if (!gotText) jb.textContent = m.text; }
          else if (m.t === "error") { typer.fail("error: " + m.text); }
          // "tool" / "sources" / "result" events are intentionally not rendered —
          // the conversation stays clean; diagnostics live in ingest.py search.
        }
      }
      typer.finish();
      await typer.done;
      if (!gotText && !jb.classList.contains("err")) jb.textContent = "(no reply)";
      autoscroll();
    } catch (e) {
      typer.fail("error: " + e);
    }
    setBusy(false);
    inp.focus();
    if (outbox.length) run(outbox.shift(), true);  // drain queued messages in order
  }

  function submit() {
    const text = inp.value.trim();
    if (!text) return;
    inp.value = "";
    if (sending) { bubble("you", text); outbox.push(text); return; }
    run(text, false);
  }

  sendbtn.addEventListener("click", submit);
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  $("newchat").addEventListener("click", async () => {
    if (sending) return;
    const arc = $("arcinp").value.trim();
    const r = await fetch("/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arcId: arc }),
    });
    if (r.status === 400) {
      bubble("meta", "invalid arcId — they look like ARCF26999Z479 (case-sensitive)");
      return;
    }
    bubble("divider", arc
      ? "new conversation — scoped to " + arc + " (other applications are off-limits)"
      : "new conversation — previous context forgotten (unscoped)");
  });
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/state.json"):
            body = json.dumps(read_state()).encode()
            ctype = "application/json"
        elif self.path in ("/", "/index.html"):
            body = PAGE.encode()
            ctype = "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if self.path == "/chat" and CHAT_AVAILABLE:
            n = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                data = {}
            text = (data.get("text") or "").strip()
            if not text:
                self.send_response(400)
                self.end_headers()
                return
            q: queue.Queue = queue.Queue()
            asyncio.run_coroutine_threadsafe(_turn(text, q), _loop)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            while True:
                item = q.get()
                if item is None:
                    break
                try:
                    self.wfile.write((json.dumps(item) + "\n").encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
            return
        if self.path == "/reset" and CHAT_AVAILABLE:
            global _session_arcid
            n = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                data = {}
            arc = (data.get("arcId") or "").strip()
            if arc and not _ARCID_RE.match(arc):
                self.send_response(400)
                self.end_headers()
                return
            _session_arcid = arc          # empty string = unscoped chat
            asyncio.run_coroutine_threadsafe(_reset(), _loop).result(timeout=60)
            asyncio.run_coroutine_threadsafe(_warm(), _loop)  # next conversation starts hot
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):  # quiet
        pass


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    if CHAT_AVAILABLE:
        asyncio.run_coroutine_threadsafe(_warm(), _loop)
    print(f"Jacob live canvas → http://127.0.0.1:{PORT}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
