#!/usr/bin/env python3
"""Run and score the notfound benchmark.

Usage:
  python3 notfound_run.py              # run + score
  python3 notfound_run.py --score-only # score existing results
"""

import json
import subprocess
import time
import sys
import re
from pathlib import Path

PROMPTS_FILE = Path(__file__).parent / "notfound_prompts.jsonl"
RESULTS_FILE = Path(__file__).parent / "results" / "notfound.jsonl"
TIMEOUT = 15


def run_benchmark():
    prompts = []
    with open(PROMPTS_FILE) as f:
        for line in f:
            prompts.append(json.loads(line))

    results = []
    with open(RESULTS_FILE, "w") as out:
        for i, p in enumerate(prompts):
            print(f"  [{i+1}/{len(prompts)}] {p['input'][:40]:<42}", end="", flush=True)
            start = time.time()
            try:
                result = subprocess.run(
                    ["hunch", "--notfound", p["input"]],
                    capture_output=True, text=True, timeout=TIMEOUT
                )
                elapsed = round(time.time() - start, 2)
                output = result.stdout.strip()
            except subprocess.TimeoutExpired:
                elapsed = round(time.time() - start, 2)
                output = "[TIMEOUT]"

            r = {
                "id": p["id"],
                "input": p["input"],
                "expected_category": p["category"],
                "expected": p["expected"],
                "raw_output": output,
                "total_time": elapsed,
            }

            # Parse category from output
            if output.startswith("typo: "):
                r["got_category"] = "typo"
                r["got"] = output[6:]
            elif output.startswith("install: "):
                r["got_category"] = "install"
                r["got"] = output[9:]
            elif output.startswith("macos: "):
                r["got_category"] = "macos"
                r["got"] = output[7:]
            else:
                r["got_category"] = "unknown"
                r["got"] = output

            out.write(json.dumps(r) + "\n")
            out.flush()
            results.append(r)

            status = "✓" if r["got_category"] == p["category"] else "✗"
            print(f" → {status} [{r['got_category']}] {r['got'][:30]} ({elapsed}s)")

    return results


def score(results):
    total = len(results)
    cat_correct = 0
    full_correct = 0
    by_category = {}

    for r in results:
        cat = r["expected_category"]
        if cat not in by_category:
            by_category[cat] = {"total": 0, "cat_correct": 0, "full_correct": 0}
        by_category[cat]["total"] += 1

        cat_match = r["got_category"] == cat
        if cat_match:
            cat_correct += 1
            by_category[cat]["cat_correct"] += 1

        # Full match: right category + right answer
        got_norm = re.sub(r"\s+", " ", r["got"].strip().replace('"', "'").lower())
        exp_norm = re.sub(r"\s+", " ", r["expected"].strip().replace('"', "'").lower())
        if cat_match and got_norm == exp_norm:
            full_correct += 1
            by_category[cat]["full_correct"] += 1

    times = [r["total_time"] for r in results]
    avg_time = sum(times) / len(times) if times else 0

    print(f"\n{'=' * 60}")
    print(f"  NOTFOUND BENCHMARK")
    print(f"{'=' * 60}")
    print(f"  Total:              {total}")
    print(f"  Category correct:   {cat_correct} ({cat_correct/total*100:.0f}%)")
    print(f"  Full match:         {full_correct} ({full_correct/total*100:.0f}%)")
    print(f"  Avg time:           {avg_time:.1f}s")
    print(f"\n  By category:")
    print(f"    {'':12s}  {'cat':>5}  {'full':>5}  {'total':>5}")
    for cat in ["typo", "install", "macos"]:
        if cat in by_category:
            c = by_category[cat]
            print(f"    {cat:12s}  {c['cat_correct']:5d}  {c['full_correct']:5d}  {c['total']:5d}")

    # Show failures
    print(f"\n  Failures:")
    for r in results:
        got_norm = re.sub(r"\s+", " ", r["got"].strip().replace('"', "'").lower())
        exp_norm = re.sub(r"\s+", " ", r["expected"].strip().replace('"', "'").lower())
        cat_match = r["got_category"] == r["expected_category"]
        if not cat_match or got_norm != exp_norm:
            marker = "~" if cat_match else "✗"
            print(f"    [{marker}] #{r['id']} {r['input'][:25]:<27} "
                  f"exp: [{r['expected_category']}] {r['expected'][:25]:<27} "
                  f"got: [{r['got_category']}] {r['got'][:25]}")


def main():
    if "--score-only" in sys.argv:
        with open(RESULTS_FILE) as f:
            results = [json.loads(l) for l in f]
        score(results)
    else:
        results = run_benchmark()
        score(results)


if __name__ == "__main__":
    main()
