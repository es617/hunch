#!/usr/bin/env python3
"""Convert the hunch bank into training data for Apple FM adapter training.

Produces JSONL files in the format expected by Apple's adapter training toolkit:
  [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]

Usage:
  python3 prepare_data.py                    # generate train.jsonl + eval.jsonl
  python3 prepare_data.py --stats            # show dataset statistics
  python3 prepare_data.py --eval-split 0.1   # 10% eval split (default)
"""

import json
import sqlite3
import random
import argparse
from pathlib import Path

BANK_DB = Path(__file__).parent.parent / "bank" / "tldr_bank.db"
BENCHMARK_PROMPTS = Path(__file__).parent.parent / "benchmark" / "prompts.jsonl"
TRAIN_FILE = Path(__file__).parent / "train.jsonl"
EVAL_FILE = Path(__file__).parent / "eval.jsonl"

SYSTEM_PROMPT = "Output a single shell command for zsh on macOS. No explanation, no markdown, no backticks. Just the command."


def load_bank():
    """Load all Q/A pairs from the bank."""
    conn = sqlite3.connect(str(BANK_DB))
    rows = conn.execute(
        "SELECT question, answer, cmd, source FROM bank"
    ).fetchall()
    conn.close()
    return [{"q": q, "a": a, "cmd": cmd, "source": src} for q, a, cmd, src in rows]


def load_benchmark_prompts():
    """Load benchmark prompts to exclude from training data."""
    if not BENCHMARK_PROMPTS.exists():
        return set()
    prompts = set()
    with open(BENCHMARK_PROMPTS) as f:
        for line in f:
            p = json.loads(line)
            prompts.add(p["prompt"].lower().strip())
    return prompts


def to_training_example(entry):
    """Convert a bank entry to Apple FM training format."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": entry["q"]},
        {"role": "assistant", "content": entry["a"]},
    ]


def prepare_dataset(eval_split=0.1, exclude_benchmark=True, seed=42, sources=None):
    """Prepare train/eval splits from the bank.

    Args:
        sources: filter by source. Options:
            None or "all" — everything (default)
            "override" — overrides only (~130 examples)
            "macos" — overrides + tldr-osx (~1k examples)
            "override,tldr-osx" — comma-separated list
    """
    bank = load_bank()
    print(f"Loaded {len(bank)} entries from bank")

    # Filter by source if specified
    if sources and sources != "all":
        allowed = set(s.strip() for s in sources.split(","))
        # "macos" is a shorthand for override + tldr-osx
        if "macos" in allowed:
            allowed.discard("macos")
            allowed.update(["override", "tldr-osx"])
        before = len(bank)
        bank = [e for e in bank if e["source"] in allowed]
        print(f"Filtered to sources {allowed}: {len(bank)} entries (from {before})")

    # Count by source
    by_source = {}
    for entry in bank:
        by_source[entry["source"]] = by_source.get(entry["source"], 0) + 1
    for src, count in sorted(by_source.items()):
        print(f"  {src}: {count}")

    # Exclude benchmark prompts from training to avoid data leakage
    if exclude_benchmark:
        benchmark = load_benchmark_prompts()
        before = len(bank)
        bank = [e for e in bank if e["q"].lower().strip() not in benchmark]
        excluded = before - len(bank)
        print(f"Excluded {excluded} entries matching benchmark prompts")

    # Deduplicate by (question, answer)
    seen = set()
    unique = []
    for entry in bank:
        key = (entry["q"].lower().strip(), entry["a"].strip())
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    print(f"After dedup: {len(unique)} unique entries (removed {len(bank) - len(unique)})")
    bank = unique

    # Split into train/eval
    random.seed(seed)
    random.shuffle(bank)
    eval_size = max(int(len(bank) * eval_split), 1)
    eval_data = bank[:eval_size]
    train = bank[eval_size:]

    # For small datasets, put everything in both
    if len(bank) < 500:
        train = bank
        eval_data = bank
        print(f"Small dataset — using all {len(bank)} examples for both train and eval")
    else:
        print(f"\nDataset split:")
        print(f"  Train: {len(train)} examples")
        print(f"  Eval:  {len(eval_data)} examples")

    return train, eval_data


def write_jsonl(data, path):
    """Write training data in Apple FM format."""
    with open(path, "w") as f:
        for entry in data:
            example = to_training_example(entry)
            f.write(json.dumps(example) + "\n")
    print(f"Wrote {len(data)} examples to {path}")


def show_stats(data, label):
    """Show dataset statistics."""
    by_source = {}
    by_cmd = {}
    total_q_len = 0
    total_a_len = 0

    for entry in data:
        by_source[entry["source"]] = by_source.get(entry["source"], 0) + 1
        by_cmd[entry["cmd"]] = by_cmd.get(entry["cmd"], 0) + 1
        total_q_len += len(entry["q"])
        total_a_len += len(entry["a"])

    print(f"\n{label} ({len(data)} examples):")
    print(f"  By source:")
    for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"    {src}: {count}")
    print(f"  Unique commands: {len(by_cmd)}")
    print(f"  Avg question length: {total_q_len / len(data):.0f} chars")
    print(f"  Avg answer length: {total_a_len / len(data):.0f} chars")
    print(f"  Top commands:")
    for cmd, count in sorted(by_cmd.items(), key=lambda x: -x[1])[:10]:
        print(f"    {cmd}: {count}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-split", type=float, default=0.1)
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--no-exclude-benchmark", action="store_true")
    parser.add_argument("--sources", default=None, help="Filter sources: override, macos, tldr-osx, tldr-common, or all")
    args = parser.parse_args()

    train, eval_data = prepare_dataset(
        eval_split=args.eval_split,
        exclude_benchmark=not args.no_exclude_benchmark,
        sources=args.sources,
    )

    if args.stats:
        show_stats(train, "Train")
        show_stats(eval_data, "Eval")
    else:
        write_jsonl(train, TRAIN_FILE)
        write_jsonl(eval_data, EVAL_FILE)

    # Show a few examples
    print("\nSample training examples:")
    for entry in train[:3]:
        ex = to_training_example(entry)
        print(f"  user: {ex[1]['content'][:60]}")
        print(f"  asst: {ex[2]['content'][:60]}")
        print()


if __name__ == "__main__":
    main()
