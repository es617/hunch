# CLAUDE.md

## Project overview

hunch is an on-device shell command generator for macOS Tahoe. It uses Apple's FoundationModels framework (3B parameter model on Neural Engine) with dynamic few-shot retrieval from tldr pages to generate shell commands from natural language.

The core insight: the 3B model is a pattern-copier, not a reasoner. Feeding it documentation (man pages, flag indexes) doesn't help. Feeding it similar solved examples (Q/A pairs from tldr) does. Dynamic few-shot retrieval from a 21k-entry bank achieves 68% accuracy vs 40% baseline.

## Architecture

```
User types "find files changed in the last hour" + Ctrl+G
  → zsh hook calls: hunch "find files changed in the last hour"
    → FTS5 search over tldr_bank.db (21k Q/A pairs) → top 8 similar examples
    → Build system prompt with examples
    → Call FoundationModels API (on-device, Neural Engine)
    → Strip markdown, return command
  → zsh replaces buffer with result
  → User inspects, hits Enter (or edits/discards)
```

## Repo structure

- `cli/` — Swift CLI. `Package.swift` + single `main.swift`. Calls FoundationModels framework directly (no apfel dependency). Links SQLite3 for FTS5 bank search.
- `hooks/hunch.zsh` — zsh plugin with three hooks: Ctrl+G (suggest), command_not_found_handler (typo correction), TRAPZERR (failure explanation).
- `bank/` — Pre-built FTS5 database (`tldr_bank.db`, 4MB, 21k entries from tldr-pages + macOS overrides). `build_tldr_bank.py` regenerates from source.
- `benchmark/` — 100-prompt evaluation suite. `run.py` tests approaches, `score.py` scores results. 10 approaches tested, results in `reviews.json`.

## Build & install

```
make build      # swift build -c release (requires macOS 26 SDK)
make install    # copies binary + database to /usr/local/
make update-bank  # regenerates tldr_bank.db from latest tldr-pages
```

## Key constraints

- **macOS 26 Tahoe only** — FoundationModels framework doesn't exist on earlier versions.
- **Apple Silicon only** — Neural Engine required.
- **4K token context window** — system prompt + 8 examples + user query + output must fit. Current prompts use ~200-400 tokens.
- **Always use `--permissive`** guardrail mode (set in code) — Apple's default guardrails block innocuous shell-related prompts unpredictably.
- **Temperature 0** — deterministic output. Self-consistency (majority vote) is useless with this setting.

## Development notes

- The FoundationModels API in `main.swift` is written against WWDC 25 docs. The exact API surface may need adjustment when compiling against the actual SDK.
- SQLite3 is linked directly (available on every Mac) — no external dependencies.
- The FTS5 search uses OR-joined keywords with stop word removal. No embeddings, no ML in the retrieval step.
- The benchmark runner (`benchmark/run.py`) calls hunch or apfel CLI. Running from Claude Code's Bash tool causes Neural Engine timeouts — run benchmarks from terminal directly.

## Benchmark findings

- **68% usable accuracy** with dynshot-tldr (FTS5 search over 21k tldr examples)
- **40% baseline** with bare prompt (no examples)
- The model can't: read documentation and apply it, self-critique, handle awk/sed one-liners, or know macOS-specific commands without examples
- The model can: copy patterns from similar examples, identify correct base commands, do simple flag usage when shown examples
- Dangerous hallucinations exist (e.g. `git reset --hard` when asked for `--soft`) — the inspect-before-run design of Ctrl+G is load-bearing safety

## Code style

- Swift: standard Swift conventions, no external packages
- Zsh: POSIX-ish where possible, zsh-specific features (zle, print -P) where needed
- Python (benchmark/bank tools): Python 3, no pip dependencies
- No inline CSS, no emojis in code
- Keep console output clean — no debug prints in production paths
