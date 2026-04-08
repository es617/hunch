#!/usr/bin/env python3
"""Download tldr pages and build a Q/A bank + SQLite FTS5 index.

Usage:
  python3 build_tldr_bank.py          # download + build
  python3 build_tldr_bank.py --query "find files modified last hour"  # test search
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

BANK_DIR = Path(__file__).parent
TLDR_DIR = BANK_DIR / "tldr-pages"
DB_PATH = BANK_DIR / "tldr_bank.db"
OVERRIDES_PATH = BANK_DIR / "macos_overrides.tsv"


def download_tldr():
    """Clone or update tldr pages."""
    if TLDR_DIR.exists():
        print("Updating tldr pages...")
        subprocess.run(["git", "-C", str(TLDR_DIR), "pull", "-q"], check=True)
    else:
        print("Cloning tldr pages...")
        subprocess.run([
            "git", "clone", "--depth=1",
            "https://github.com/tldr-pages/tldr.git",
            str(TLDR_DIR)
        ], check=True)


def parse_tldr_page(path):
    """Parse a tldr markdown page into Q/A pairs."""
    with open(path) as f:
        content = f.read()

    # Extract command name from header
    cmd_match = re.match(r"^#\s+(.+)", content)
    if not cmd_match:
        return []
    cmd_name = cmd_match.group(1).strip()

    pairs = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        # Description line: "- Some description:"
        if lines[i].startswith("- "):
            desc = lines[i][2:].rstrip(":")
            # Next non-empty line should be the command in backticks
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip().startswith("`"):
                command = lines[j].strip().strip("`")
                # Clean up {{placeholders}} → readable form
                command = re.sub(r"\{\{([^}]+)\}\}", r"\1", command)
                pairs.append({
                    "q": desc,
                    "a": command,
                    "cmd": cmd_name,
                })
            i = j + 1
        else:
            i += 1

    return pairs


def load_overrides():
    """Load macOS-specific overrides from TSV file."""
    pairs = []
    if not OVERRIDES_PATH.exists():
        return pairs
    with open(OVERRIDES_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                pairs.append({"q": parts[0], "a": parts[1], "cmd": parts[2] if len(parts) > 2 else ""})
    return pairs


def build_bank():
    """Parse all tldr pages into Q/A pairs."""
    all_pairs = []

    # Parse common + osx pages
    for section in ["common", "osx"]:
        pages_dir = TLDR_DIR / "pages" / section
        if not pages_dir.exists():
            continue
        for md_file in sorted(pages_dir.glob("*.md")):
            pairs = parse_tldr_page(md_file)
            for p in pairs:
                p["source"] = section
            all_pairs.extend(pairs)

    # Add macOS overrides
    overrides = load_overrides()
    for o in overrides:
        o["source"] = "override"
    all_pairs.extend(overrides)

    print(f"Parsed {len(all_pairs)} Q/A pairs ({len(all_pairs) - len(overrides)} from tldr, {len(overrides)} overrides)")
    return all_pairs


def build_fts_index(pairs):
    """Build SQLite FTS5 index for fast similarity search."""
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("CREATE VIRTUAL TABLE bank USING fts5(question, answer, cmd, source)")

    conn.executemany(
        "INSERT INTO bank (question, answer, cmd, source) VALUES (?, ?, ?, ?)",
        [(p["q"], p["a"], p.get("cmd", ""), p.get("source", "")) for p in pairs]
    )
    conn.commit()

    # Verify
    count = conn.execute("SELECT count(*) FROM bank").fetchone()[0]
    print(f"FTS5 index built: {count} entries in {DB_PATH}")
    conn.close()


def search(query, n=8):
    """Search the FTS5 index for similar Q/A pairs."""
    conn = sqlite3.connect(str(DB_PATH))

    # FTS5 query: split into words, join with OR for fuzzy matching
    words = re.findall(r'[a-zA-Z]+', query.lower())
    # Filter out very common words
    stop_words = {"the", "a", "an", "in", "on", "to", "for", "of", "and", "or", "is", "it",
                  "all", "my", "this", "that", "with", "from", "how", "do", "what", "show",
                  "get", "find", "list", "display"}
    words = [w for w in words if w not in stop_words and len(w) > 1]

    if not words:
        conn.close()
        return []

    fts_query = " OR ".join(words)

    results = conn.execute(
        "SELECT question, answer, cmd, rank FROM bank WHERE bank MATCH ? ORDER BY rank LIMIT ?",
        (fts_query, n)
    ).fetchall()

    conn.close()
    return [{"q": r[0], "a": r[1], "cmd": r[2], "rank": r[3]} for r in results]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", help="Test search query")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    if args.query:
        results = search(args.query)
        print(f"Top {len(results)} results for: {args.query}\n")
        for r in results:
            print(f"  Q: {r['q']}")
            print(f"  A: {r['a']}")
            print(f"  ({r['cmd']}, rank: {r['rank']:.1f})")
            print()
        return

    if not args.skip_download:
        download_tldr()

    pairs = build_bank()
    build_fts_index(pairs)

    # Quick test
    print("\n--- Test search: 'find files modified last hour' ---")
    for r in search("find files modified last hour", 5):
        print(f"  {r['q']} → {r['a']}")

    print("\n--- Test search: 'copy to clipboard' ---")
    for r in search("copy to clipboard", 5):
        print(f"  {r['q']} → {r['a']}")

    print("\n--- Test search: 'kill process port' ---")
    for r in search("kill process port", 5):
        print(f"  {r['q']} → {r['a']}")


if __name__ == "__main__":
    main()
