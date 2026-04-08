#!/usr/bin/env python3
"""Score apfel benchmark results.

Scoring tiers:
- exact:    matches one of the accepted answers exactly
- accept:   functionally equivalent (right command, right flags, minor variations)
- command:  correct base command but wrong flags/args
- error:    guardrail block, timeout, overflow, or empty output

Usage:
  python3 score.py                    # score all results
  python3 score.py --approach minimal # score one approach
  python3 score.py --compare          # side-by-side comparison table
  python3 score.py --failures         # show only failures
  python3 score.py --category flags   # filter by category
  python3 score.py --review           # interactive review of near-misses
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

RESULTS_DIR = Path(__file__).parent / "results"
PROMPTS_FILE = Path(__file__).parent / "prompts.jsonl"
ALTERNATES_FILE = Path(__file__).parent / "alternates.json"
REVIEWS_FILE = Path(__file__).parent / "reviews.json"


def load_prompts():
    prompts = {}
    with open(PROMPTS_FILE) as f:
        for line in f:
            p = json.loads(line)
            prompts[p["id"]] = p
    return prompts


def load_alternates():
    if ALTERNATES_FILE.exists():
        with open(ALTERNATES_FILE) as f:
            raw = json.load(f)
        return {int(k): v for k, v in raw.items()}
    return {}


def load_reviews():
    """Load manual review overrides: {approach: {id: "accept"|"reject"}}"""
    if REVIEWS_FILE.exists():
        with open(REVIEWS_FILE) as f:
            return json.load(f)
    return {}


def save_reviews(reviews):
    with open(REVIEWS_FILE, "w") as f:
        json.dump(reviews, f, indent=2)


def load_results(approach):
    results = []
    path = RESULTS_DIR / f"{approach}.jsonl"
    if not path.exists():
        return results
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


def normalize(cmd):
    """Normalize command for comparison."""
    cmd = cmd.strip()
    # Normalize quoting variations
    cmd = cmd.replace('"', "'")
    # Collapse multiple spaces
    cmd = re.sub(r"\s+", " ", cmd)
    return cmd


def extract_base_command(cmd):
    """Extract the base command (first word, ignoring sudo/env)."""
    parts = cmd.strip().split()
    for p in parts:
        if p in ("sudo", "env", "command"):
            continue
        return p
    return ""


def commands_match(got, accepted_list):
    """Check if got matches any accepted answer (with normalization)."""
    got_norm = normalize(got)
    for acc in accepted_list:
        if normalize(acc) == got_norm:
            return True
    # Also try without placeholder values (file, dir, host, etc.)
    # The model might use different placeholder names
    got_generic = re.sub(r"\b(file\S*|dir\S*|path\S*|host\S*|user\S*)\b", "X", got_norm)
    for acc in accepted_list:
        acc_generic = re.sub(r"\b(file\S*|dir\S*|path\S*|host\S*|user\S*)\b", "X", normalize(acc))
        if got_generic == acc_generic:
            return True
    return False


def score_one(result, prompt_info, alternates, review_override=None):
    """Score a single result."""
    got = result.get("result", "").strip()
    accepted = alternates.get(prompt_info["id"], [prompt_info["expected"]])

    scores = {
        "tier": "wrong",  # exact, accept, command, error, wrong
        "command_correct": False,
    }

    # Check manual review override
    if review_override == "accept":
        scores["tier"] = "accept"
        scores["command_correct"] = True
        return scores
    if review_override == "reject":
        scores["tier"] = "wrong"
        return scores

    # Error states
    if not got or got == "ERROR":
        scores["tier"] = "error"
        return scores
    if any(tag in got.lower() for tag in ["guardrail", "blocked", "[error", "[timeout", "[overflow"]):
        scores["tier"] = "error"
        return scores

    # Exact match against any accepted answer
    if commands_match(got, accepted):
        scores["tier"] = "exact"
        scores["command_correct"] = True
        return scores

    # Command-level match
    expected_cmds = set(extract_base_command(a) for a in accepted)
    got_cmd = extract_base_command(got)
    if got_cmd and got_cmd in expected_cmds:
        scores["command_correct"] = True
        scores["tier"] = "command"
    else:
        scores["tier"] = "wrong"

    return scores


def score_approach(approach, category_filter=None):
    prompts = load_prompts()
    alternates = load_alternates()
    reviews = load_reviews().get(approach, {})
    results = load_results(approach)

    stats = {
        "total": 0,
        "exact": 0,
        "accept": 0,
        "command": 0,
        "error": 0,
        "wrong": 0,
        "by_category": defaultdict(lambda: {"total": 0, "exact": 0, "accept": 0, "command": 0, "error": 0, "wrong": 0}),
        "times": [],
        "failures": [],
        "needs_review": [],
    }

    for r in results:
        pid = r["id"]
        if pid not in prompts:
            continue
        pinfo = prompts[pid]

        if category_filter and pinfo["category"] != category_filter:
            continue

        override = reviews.get(str(pid))
        scores = score_one(r, pinfo, alternates, override)
        cat = pinfo["category"]
        tier = scores["tier"]

        stats["total"] += 1
        stats[tier] += 1
        stats["by_category"][cat]["total"] += 1
        stats["by_category"][cat][tier] += 1

        if r.get("total_time"):
            stats["times"].append(r["total_time"])

        if tier not in ("exact", "accept"):
            entry = {
                "id": pid,
                "prompt": pinfo["prompt"],
                "expected": pinfo["expected"],
                "got": r.get("result", ""),
                "category": cat,
                "tier": tier,
                "command_correct": scores["command_correct"],
            }
            stats["failures"].append(entry)
            if tier == "command":
                stats["needs_review"].append(entry)

    return stats


def print_summary(approach, stats):
    total = stats["total"]
    if total == 0:
        print(f"  {approach}: no results found")
        return

    exact_pct = stats["exact"] / total * 100
    accept_pct = stats["accept"] / total * 100
    usable_pct = (stats["exact"] + stats["accept"]) / total * 100
    cmd_pct = (stats["exact"] + stats["accept"] + stats["command"]) / total * 100
    err_pct = stats["error"] / total * 100
    avg_time = sum(stats["times"]) / len(stats["times"]) if stats["times"] else 0

    print(f"\n{'=' * 70}")
    print(f"  {approach.upper()}")
    print(f"{'=' * 70}")
    print(f"  Total prompts:     {total}")
    print(f"  Exact match:       {stats['exact']:3d} ({exact_pct:4.0f}%)  <- matches accepted answer")
    print(f"  Accepted:          {stats['accept']:3d} ({accept_pct:4.0f}%)  <- manually reviewed as correct")
    print(f"  ─────────────────────────────────")
    print(f"  Usable (E+A):      {stats['exact']+stats['accept']:3d} ({usable_pct:4.0f}%)")
    print(f"  Right cmd/wrong fl:{stats['command']:3d}           <- correct command, wrong flags")
    print(f"  Wrong command:     {stats['wrong']:3d}           <- completely wrong")
    print(f"  Errors:            {stats['error']:3d} ({err_pct:4.0f}%)  <- guardrail/timeout/empty")
    print(f"  Avg time:          {avg_time:.1f}s")
    print(f"  Needs review:      {len(stats['needs_review']):3d}           <- right cmd, might be usable")

    print(f"\n  By category:")
    print(f"    {'':12s}  {'exact':>5}  {'accpt':>5}  {'cmd':>5}  {'wrong':>5}  {'error':>5}  {'total':>5}")
    for cat in sorted(stats["by_category"]):
        c = stats["by_category"][cat]
        if c["total"] > 0:
            print(f"    {cat:12s}  {c['exact']:5d}  {c['accept']:5d}  {c['command']:5d}  {c['wrong']:5d}  {c['error']:5d}  {c['total']:5d}")


def print_failures(approach, stats):
    print(f"\n{'=' * 70}")
    print(f"  FAILURES: {approach.upper()}")
    print(f"{'=' * 70}")
    for f in stats["failures"]:
        markers = {"command": "~", "wrong": "X", "error": "!"}
        marker = markers.get(f["tier"], "?")
        print(f"  [{marker}] #{f['id']} ({f['category']}) [{f['tier']}]")
        print(f"      prompt:   {f['prompt']}")
        print(f"      expected: {f['expected']}")
        print(f"      got:      {f['got']}")
        print()


def print_comparison(approaches, category_filter=None):
    prompts = load_prompts()
    alternates = load_alternates()
    all_results = {}
    for a in approaches:
        results = load_results(a)
        all_results[a] = {r["id"]: r for r in results}

    # Dynamic column widths
    col_w = max(len(a) for a in approaches) + 2
    col_w = max(col_w, 16)

    header = f"{'#':>3} {'Cat':6} {'Prompt':<40} {'Expected':<25}"
    for a in approaches:
        header += f" {a:<{col_w}}"
    print(header)
    print("-" * len(header))

    for pid in sorted(prompts):
        pinfo = prompts[pid]
        if category_filter and pinfo["category"] != category_filter:
            continue

        row = f"{pid:>3} {pinfo['category'][:5]:6} {pinfo['prompt'][:39]:<40} {pinfo['expected'][:24]:<25}"
        for a in approaches:
            r = all_results.get(a, {}).get(pid, {})
            got = r.get("result", "—")[:col_w - 2]
            scores = score_one(r, pinfo, alternates)
            markers = {"exact": "+", "accept": "a", "command": "~", "error": "!", "wrong": "-"}
            marker = markers.get(scores["tier"], "?")
            row += f" {marker}{got:<{col_w - 1}}"
        print(row)

    # Summary
    print("-" * len(header))
    summary = f"{'':>3} {'':6} {'TOTALS':<40} {'':25}"
    for a in approaches:
        s = score_approach(a, category_filter)
        if s["total"] > 0:
            usable = s["exact"] + s["accept"]
            summary += f" {usable}/{s['total']:3d} usable "
        else:
            summary += f" {'—':<{col_w}}"
    print(summary)


def interactive_review(approaches):
    """Interactively review near-misses (right command, wrong flags)."""
    prompts = load_prompts()
    alternates = load_alternates()
    reviews = load_reviews()

    for approach in approaches:
        stats = score_approach(approach)
        needs_review = stats["needs_review"]
        if not needs_review:
            continue

        print(f"\n{'=' * 70}")
        print(f"  REVIEW: {approach.upper()} ({len(needs_review)} items)")
        print(f"{'=' * 70}")

        if approach not in reviews:
            reviews[approach] = {}

        for item in needs_review:
            pid = str(item["id"])
            if pid in reviews[approach]:
                continue  # already reviewed

            print(f"\n  #{item['id']} ({item['category']})")
            print(f"  Prompt:   {item['prompt']}")
            print(f"  Expected: {item['expected']}")
            print(f"  Got:      {item['got']}")
            accepted = alternates.get(item["id"], [])
            if accepted:
                print(f"  Also OK:  {', '.join(accepted[:3])}")

            while True:
                choice = input("  [a]ccept / [r]eject / [s]kip / [q]uit? ").strip().lower()
                if choice in ("a", "accept"):
                    reviews[approach][pid] = "accept"
                    break
                elif choice in ("r", "reject"):
                    reviews[approach][pid] = "reject"
                    break
                elif choice in ("s", "skip"):
                    break
                elif choice in ("q", "quit"):
                    save_reviews(reviews)
                    return

        save_reviews(reviews)
    print("\nReviews saved.")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--approach", help="Score specific approach")
    parser.add_argument("--compare", action="store_true", help="Side-by-side comparison")
    parser.add_argument("--failures", action="store_true", help="Show failures only")
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--review", action="store_true", help="Interactive review of near-misses")
    args = parser.parse_args()

    available = sorted(f.stem for f in RESULTS_DIR.glob("*.jsonl")) if RESULTS_DIR.exists() else []

    if not available:
        print("No results found. Run python3 run.py first.")
        sys.exit(1)

    if args.review:
        approaches = [args.approach] if args.approach else available
        interactive_review(approaches)
        return

    if args.compare:
        print_comparison(available, args.category)
        return

    approaches = [args.approach] if args.approach else available

    for a in approaches:
        if a not in available:
            print(f"No results for approach '{a}'")
            continue
        stats = score_approach(a, args.category)
        print_summary(a, stats)
        if args.failures:
            print_failures(a, stats)


if __name__ == "__main__":
    main()
