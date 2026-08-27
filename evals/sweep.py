"""Sweep ask-pass: run every bank question through Jacob, checkpointed.

  python -m evals.sweep [--limit N] [--ids COV-001,SCR-044] [--cats livestate]
                        [--concurrency 5] [--redo]

Each question runs in a FRESH agent session (same isolation as evals/run.py),
through the real stack — model, rag.server against the real KB store, and
appstate.server pointed at the local mock platform (evals/mockplatform.py), so
live-state behavior is exercised with zero real-platform contact.

Checkpointing: every result is appended to evals/sweep-results/answers.jsonl the
moment it lands. Re-running skips questions that already have a clean answer
(--redo re-asks the selection anyway), so an interrupted or rate-limited run
resumes for free. Rate-limit-shaped errors pause ALL workers (staged backoff),
then the question is retried without burning its attempts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "sweep-results"
ANSWERS = RESULTS_DIR / "answers.jsonl"

ATTEMPTS = 3            # per-question tries for generic errors/timeouts
ASK_TIMEOUT = 240       # seconds per attempt (startup + tool calls + reply)
PAUSE_STEPS = [120, 300, 900, 1800, 3600]   # staged backoff on rate limits

_RATE_LIMIT = re.compile(
    r"rate ?limit|429|overloaded|529|usage limit|out of usage|quota|"
    r"exceeded.*limit|too many requests|resets at",
    re.I,
)

GREEN, RED, YEL, DIM, RST = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def load_answers() -> dict[str, dict]:
    """Latest record per id from the checkpoint file."""
    out: dict[str, dict] = {}
    if ANSWERS.exists():
        for raw in ANSWERS.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            out[rec["id"]] = rec
    return out


def _append(rec: dict) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    with ANSWERS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


async def _ask_once(question: str) -> tuple[str, int | None]:
    """One question in one fresh session. Returns (answer, num_turns)."""
    from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock

    from agent import build_options

    async with ClaudeSDKClient(options=build_options()) as client:
        await client.query(question)
        parts: list[str] = []
        result_text, turns = None, None
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        parts.append(b.text)
            elif isinstance(msg, ResultMessage):
                result_text = msg.result
                turns = msg.num_turns
        return (result_text or "".join(parts)).strip(), turns


class Runner:
    def __init__(self, concurrency: int):
        self.sem = asyncio.Semaphore(concurrency)
        self.resume = asyncio.Event()      # cleared while rate-limited
        self.resume.set()
        self.pause_level = 0
        self.pausing = False
        self.done = 0

    async def _rate_limit_pause(self, err: str) -> None:
        if self.pausing:                    # one pauser; others just wait
            await self.resume.wait()
            return
        self.pausing = True
        self.resume.clear()
        delay = PAUSE_STEPS[min(self.pause_level, len(PAUSE_STEPS) - 1)]
        self.pause_level += 1
        print(f"\n{YEL}rate-limited — pausing all workers {delay}s{RST} "
              f"{DIM}({' '.join(err.split())[:140]}){RST}", flush=True)
        await asyncio.sleep(delay)
        self.resume.set()
        self.pausing = False

    async def run_case(self, case: dict, total: int) -> dict:
        async with self.sem:
            attempt, last_err = 0, None
            while attempt < ATTEMPTS:
                await self.resume.wait()
                t0 = time.monotonic()
                try:
                    answer, turns = await asyncio.wait_for(
                        _ask_once(case["q"]), timeout=ASK_TIMEOUT)
                    if not answer:
                        raise RuntimeError("empty answer")
                    if _RATE_LIMIT.search(answer) and len(answer) < 200:
                        # a limit message surfaced AS the result text
                        raise RuntimeError(f"result looks rate-limited: {answer}")
                    self.pause_level = 0
                    rec = {"id": case["id"], "q": case["q"], "answer": answer,
                           "error": None, "secs": round(time.monotonic() - t0, 1),
                           "turns": turns, "ts": int(time.time())}
                    _append(rec)
                    self.done += 1
                    print(f"{GREEN}✓{RST} [{self.done}/{total}] {case['id']:<10} "
                          f"{DIM}{rec['secs']:>5.1f}s  {case['q'][:64]}{RST}", flush=True)
                    return rec
                except (Exception, asyncio.TimeoutError) as e:  # noqa: BLE001
                    last_err = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                    if _RATE_LIMIT.search(last_err):
                        await self._rate_limit_pause(last_err)
                        continue            # same attempt again after the pause
                    attempt += 1
                    if attempt < ATTEMPTS:
                        await asyncio.sleep(5 * attempt)
            rec = {"id": case["id"], "q": case["q"], "answer": None,
                   "error": last_err, "secs": None, "turns": None,
                   "ts": int(time.time())}
            _append(rec)
            self.done += 1
            print(f"{RED}✗{RST} [{self.done}/{total}] {case['id']:<10} "
                  f"{RED}{(last_err or '?')[:100]}{RST}", flush=True)
            return rec


def select_cases(args) -> list[dict]:
    from . import fixtures  # noqa: F401 — fail fast if fixtures are broken
    from .bank import load_bank

    bank = load_bank()
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        # also accept a file of ids (one per line), e.g. sweep-results/failed_ids.txt
        for token in list(wanted):
            p = Path(token)
            if p.exists():
                wanted.discard(token)
                wanted |= {ln.strip() for ln in p.read_text().splitlines() if ln.strip()}
        bank = [c for c in bank if c["id"] in wanted]
    if args.cats:
        cats = {c.strip() for c in args.cats.split(",")}
        bank = [c for c in bank if c["cat"] in cats]
    if not args.redo:
        have = load_answers()
        bank = [c for c in bank
                if not (have.get(c["id"]) and have[c["id"]].get("answer"))]
    if args.limit:
        bank = bank[: args.limit]
    return bank


async def amain(args) -> int:
    # Point the appstate subprocesses at the in-process mock BEFORE any session
    # spawns (children inherit env; config.py's .env load is setdefault-only).
    from .mockplatform import serve_in_thread
    base_url, _server = serve_in_thread()
    os.environ["JACOB_PLATFORM_BASE_URL"] = base_url
    os.environ["JACOB_PLATFORM_ENV"] = "dev"       # cosmetic; base URL rules
    os.environ.pop("ANTHROPIC_API_KEY", None)      # subscription-only, always

    cases = select_cases(args)
    if not cases:
        print("nothing to ask — all selected questions already have answers "
              "(use --redo to re-ask)")
        return 0
    print(f"{DIM}sweep: {len(cases)} question(s), concurrency {args.concurrency}, "
          f"mock platform at {base_url}{RST}", flush=True)
    runner = Runner(args.concurrency)
    results = await asyncio.gather(*(runner.run_case(c, len(cases)) for c in cases))
    errors = sum(1 for r in results if r["error"])
    print(f"{DIM}sweep done: {len(results) - errors} answered, {errors} errored{RST}")
    return 1 if errors else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ids", help="comma-separated ids and/or a path to an id-list file")
    ap.add_argument("--cats", help="comma-separated categories")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--redo", action="store_true",
                    help="re-ask even if an answer exists")
    args = ap.parse_args()
    sys.path.insert(0, str(HERE.parent))   # import agent.py from repo root
    raise SystemExit(asyncio.run(amain(args)))


if __name__ == "__main__":
    main()
