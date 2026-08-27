"""Sweep report: join bank + answers + verdicts into pass rates and a fail list.

  python -m evals.report [--md] [--fails-only]

Prints the per-category and per-behavior scoreboard, the full FAIL list with
reasons, and coverage gaps (unanswered / unjudged). Writes:
  evals/sweep-results/report.md       (--md)
  evals/sweep-results/failed_ids.txt  (always — feed back to sweep/judge --ids)
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from .bank import load_bank
from .judge import load_verdicts
from .sweep import load_answers

RESULTS_DIR = Path(__file__).resolve().parent / "sweep-results"
GREEN, RED, YEL, DIM, RST = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def build() -> dict:
    bank = load_bank()
    answers = load_answers()
    verdicts = load_verdicts()
    rows = []
    for case in bank:
        a = answers.get(case["id"])
        v = verdicts.get(case["id"])
        status = "UNASKED"
        if a and a.get("error"):
            status = "ASK_ERROR"
        elif a and a.get("answer"):
            status = "UNJUDGED"
            if v and v.get("final") in ("PASS", "FAIL"):
                status = v["final"]
        rows.append({"case": case, "answer": a, "verdict": v, "status": status})
    return {"rows": rows}


def _table(rows, key) -> list[tuple[str, int, int, int]]:
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # pass, fail, other
    for r in rows:
        k = r["case"][key]
        agg[k][0 if r["status"] == "PASS" else 1 if r["status"] == "FAIL" else 2] += 1
    out = []
    for k, (p, f, o) in sorted(agg.items(), key=lambda kv: (kv[1][1] == 0, -kv[1][1], kv[0])):
        out.append((k, p, f, o))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--md", action="store_true", help="also write report.md")
    ap.add_argument("--fails-only", action="store_true")
    args = ap.parse_args()

    data = build()
    rows = data["rows"]
    graded = [r for r in rows if r["status"] in ("PASS", "FAIL")]
    fails = [r for r in rows if r["status"] == "FAIL"]
    passes = len(graded) - len(fails)
    pred_misses = [r for r in graded if r["verdict"] and r["verdict"].get("pred_miss")]

    if not args.fails_only:
        pct = f"{100 * passes / len(graded):.1f}%" if graded else "—"
        print(f"\n{DIM}SWEEP SCOREBOARD — {len(rows)} cases in bank, "
              f"{len(graded)} graded, {passes} pass / {len(fails)} fail ({pct}){RST}\n")
        for title, key in (("by category", "cat"), ("by behavior", "behavior")):
            print(f"{DIM}{title}{RST}")
            for k, p, f, o in _table(rows, key):
                bar = f"{GREEN}{p:>4}{RST} {RED}{f:>3}{RST}"
                other = f" {YEL}{o} pending{RST}" if o else ""
                total = p + f
                pctk = f"{100 * p / total:5.1f}%" if total else "    —"
                print(f"  {k:<22} {bar}  {pctk}{other}")
            print()

    if fails:
        print(f"{RED}FAILURES ({len(fails)}){RST}")
        for r in sorted(fails, key=lambda r: (r["case"]["cat"], r["case"]["id"])):
            c, v = r["case"], r["verdict"]
            print(f"  {RED}{c['id']:<10}{RST} {DIM}[{c['cat']}/{c['behavior']}]{RST} {c['q'][:70]}")
            print(f"      {RED}{(v or {}).get('why', '?')[:120]}{RST}")
            ans = (r["answer"] or {}).get("answer") or ""
            print(f"      {DIM}got: {' '.join(ans.split())[:160]}{RST}")
    if pred_misses and not args.fails_only:
        print(f"\n{YEL}PASSED WITH PREDICATE MISS ({len(pred_misses)}) — spot-check these{RST}")
        for r in pred_misses:
            print(f"  {r['case']['id']:<10} {DIM}{r['verdict']['pred_fails']}{RST}")

    unasked = [r["case"]["id"] for r in rows if r["status"] in ("UNASKED", "ASK_ERROR")]
    unjudged = [r["case"]["id"] for r in rows if r["status"] == "UNJUDGED"]
    if unasked:
        print(f"\n{YEL}not asked / ask-errored: {len(unasked)}{RST} {DIM}{','.join(unasked[:12])}"
              f"{'…' if len(unasked) > 12 else ''}{RST}")
    if unjudged:
        print(f"{YEL}answered but unjudged: {len(unjudged)}{RST}")

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "failed_ids.txt").write_text(
        "\n".join(r["case"]["id"] for r in fails) + ("\n" if fails else ""))

    if args.md:
        lines = [
            "# Jacob sweep report", "",
            f"- Bank: **{len(rows)}** cases · graded **{len(graded)}** · "
            f"**{passes} PASS / {len(fails)} FAIL**"
            + (f" ({100 * passes / len(graded):.1f}%)" if graded else ""), "",
            "| category | pass | fail | pending | rate |", "|---|---|---|---|---|",
        ]
        for k, p, f, o in _table(rows, "cat"):
            total = p + f
            lines.append(f"| {k} | {p} | {f} | {o} | "
                         f"{(100 * p / total):.1f}% |" if total else f"| {k} | {p} | {f} | {o} | — |")
        lines += ["", "| behavior | pass | fail | pending | rate |", "|---|---|---|---|---|"]
        for k, p, f, o in _table(rows, "behavior"):
            total = p + f
            lines.append(f"| {k} | {p} | {f} | {o} | "
                         f"{(100 * p / total):.1f}% |" if total else f"| {k} | {p} | {f} | {o} | — |")
        if fails:
            lines += ["", "## Failures", ""]
            for r in sorted(fails, key=lambda r: (r["case"]["cat"], r["case"]["id"])):
                c, v = r["case"], r["verdict"]
                ans = " ".join(((r["answer"] or {}).get("answer") or "").split())
                lines += [f"### {c['id']} · {c['cat']} / {c['behavior']}", "",
                          f"**Q:** {c['q']}", "", f"**Why failed:** {(v or {}).get('why', '?')}",
                          "", f"**Rubric:** {c['rubric']}", "", f"**Got:** {ans[:500]}", ""]
        (RESULTS_DIR / "report.md").write_text("\n".join(lines) + "\n")
        print(f"\n{DIM}wrote {RESULTS_DIR / 'report.md'}{RST}")


if __name__ == "__main__":
    main()
