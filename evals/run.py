"""Eval runner.  python -m evals.run [retrieval | agent | appstate | all]

retrieval — checks the RAG pipeline (Postgres + embedder). No model, no cost.
agent     — runs each question through Jacob and checks the answer. Uses the
            full stack (incl. the model) and consumes subscription usage; each
            case runs in a fresh session for isolation.
appstate  — checks the live-state projection against synthetic memApps. No
            platform, no model, no cost — deterministic; a fast gate.

Exit code is non-zero if any case fails, so this is usable as a gate.
"""
from __future__ import annotations

import asyncio
import sys

from .appstate_cases import APPSTATE_CASES
from .cases import AGENT_CASES, RETRIEVAL_CASES

GREEN, RED, DIM, RST = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def _predicate_failures(answer: str, case: dict) -> list[str]:
    a = answer.lower()
    fails: list[str] = []
    for s in case.get("all_of", []):
        if s.lower() not in a:
            fails.append(f"missing “{s}”")
    any_of = case.get("any_of")
    if any_of and not any(s.lower() in a for s in any_of):
        fails.append(f"none of {any_of}")
    for s in case.get("none_of", []):
        if s.lower() in a:
            fails.append(f"leaked “{s}”")
    return fails


# ── retrieval eval ───────────────────────────────────────────────────────────
def run_retrieval() -> int:
    from rag import store

    print(f"\n{DIM}RETRIEVAL EVAL — RAG pipeline (Postgres + embedder){RST}")
    passed = 0
    for query, keyword, expect_weak in RETRIEVAL_CASES:
        try:
            results = store.hybrid_search(query)
            weak = store.is_weak(results)
        except Exception as e:  # noqa: BLE001
            print(f"  {RED}ERROR{RST} {query!r}: {e}")
            continue

        fails = []
        if keyword is None:
            # Off-topic query: the weak gate must reject it as not-covered.
            if not weak:
                fails.append("expected weak (off-topic), but retrieved as covered")
        else:
            # Covered query: the relevant content must appear somewhere in the
            # top-k set (what the agent actually receives), not strictly rank 1.
            hay = " ".join(f"{r['heading']} {r['text']}" for r in results).lower()
            if keyword.lower() not in hay:
                got = "; ".join(r["heading"] for r in results[:3]) or "—"
                fails.append(f"“{keyword}” not in top-{len(results)} (got: {got})")

        ok = not fails
        passed += ok
        mark = f"{GREEN}PASS{RST}" if ok else f"{RED}FAIL{RST}"
        print(f"  {mark}  {query[:52]:<52} {'' if ok else RED + '· ' + '; '.join(fails) + RST}")
    total = len(RETRIEVAL_CASES)
    print(f"{DIM}retrieval: {passed}/{total} passed{RST}")
    return 0 if passed == total else 1


# ── appstate projection eval ─────────────────────────────────────────────────
def run_appstate() -> int:
    from appstate import project

    print(f"\n{DIM}APPSTATE EVAL — live-state projection (synthetic memApps; no platform/model){RST}")
    passed = 0
    for case in APPSTATE_CASES:
        out = project.summarize(case["memapp"], case.get("arc_id", "ARCF26999Z479"))
        if case.get("expect_none"):
            fails = [] if out is None else ["expected no summary (returned None)"]
        elif out is None:
            fails = ["expected a summary, got None"]
        else:
            fails = _predicate_failures(out, case)
        ok = not fails
        passed += ok
        mark = f"{GREEN}PASS{RST}" if ok else f"{RED}FAIL{RST}"
        print(f"  {mark}  {case['name']:<28} {'' if ok else RED + '· ' + '; '.join(fails) + RST}")
    total = len(APPSTATE_CASES)
    print(f"{DIM}appstate: {passed}/{total} passed{RST}")
    return 0 if passed == total else 1


# ── agent behavior eval ──────────────────────────────────────────────────────
async def _ask_once(question: str) -> str:
    from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock

    from agent import build_options

    async with ClaudeSDKClient(options=build_options()) as client:
        await client.query(question)
        parts, result = [], None
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        parts.append(b.text)
            elif isinstance(msg, ResultMessage):
                result = msg.result
        return (result or "".join(parts)).strip()


async def run_agent(name_filter: str | None = None) -> int:
    print(f"\n{DIM}AGENT EVAL — Jacob's behavior (fresh session per case; uses the model){RST}")
    cases = AGENT_CASES
    if name_filter:
        wanted = {n.strip() for n in name_filter.split(",")}
        cases = [c for c in AGENT_CASES if any(w in c["name"] for w in wanted)]
    passed = 0
    for case in cases:
        try:
            answer = await asyncio.wait_for(_ask_once(case["q"]), timeout=120)
        except (Exception, asyncio.TimeoutError) as e:  # noqa: BLE001
            print(f"  {RED}ERROR{RST} {case['name']}: {e or 'timeout'}", flush=True)
            continue
        fails = _predicate_failures(answer, case)
        ok = not fails
        passed += ok
        mark = f"{GREEN}PASS{RST}" if ok else f"{RED}FAIL{RST}"
        print(f"  {mark}  {case['name']:<22} {case['q'][:46]}", flush=True)
        if not ok:
            print(f"         {RED}{'; '.join(fails)}{RST}", flush=True)
            print(f"         {DIM}got: {' '.join(answer.split())[:150]}{RST}", flush=True)
    total = len(cases)
    print(f"{DIM}agent: {passed}/{total} passed{RST}")
    return 0 if passed == total else 1


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    name_filter = sys.argv[2] if len(sys.argv) > 2 else None  # agent: comma-sep name substrings
    rc = 0
    if mode in ("appstate", "all"):
        rc |= run_appstate()
    if mode in ("retrieval", "all"):
        rc |= run_retrieval()
    if mode in ("agent", "all"):
        rc |= asyncio.run(run_agent(name_filter))
    if mode not in ("retrieval", "agent", "appstate", "all"):
        sys.exit("usage: python -m evals.run [retrieval | agent | appstate | all]")
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
