# Changelog

## 0.2.0

- Three-tier retrieval: override → tldr-osx → tldr-common. Curated macOS examples now always appear first, reducing noise from 21k cross-platform entries
- Command validation: retries when the model hallucinates a command that doesn't exist locally or in the tldr bank
- Smarter command-not-found handler with three categories:
  - Typo detection via Damerau-Levenshtein (`grpe` → `did you mean: grep`)
  - Install suggestions via `brew which-formula` (`ncdu` → `not installed: brew install ncdu`)
  - Linux→macOS equivalents via LLM (`ip a` → `macOS equivalent: ifconfig`)
- Notfound benchmark: 30 prompts, 97% category accuracy
- Suggest benchmark: **~83%** (up from ~78% in v0.1.2)

## 0.1.2

- Improved system prompt: model now prefers retrieved examples over pretraining guesses
- Fixed FTS5 stop words: command names (`find`, `show`, `list`, `display`) no longer dropped from search queries
- Added 28 targeted overrides for common patterns missing from tldr (`find -size`, `find -mtime`, `find -user`, `curl -I`, `grep --include`, and more)
- Expanded benchmark alternates for more accurate automated scoring
- Benchmark accuracy: **~78%** (up from ~70% in v0.1.1)
- Added experimental `--guided` flag for Apple FoundationModels constrained decoding (undocumented)

## 0.1.1

- Fix: don't pass empty GenerationOptions when no temperature is set (was changing model behavior)
- Fix: scoring bug where stale reviews deflated benchmark numbers
- Expanded macOS overrides (83 → 107 entries) targeting consistently failing commands
- Updated benchmark numbers: ~68% base, ~70% with overrides, ~72% with overrides + sc
- Self-consistency finding: same average accuracy, but kills run-to-run variance
- Simplified benchmark scorer (removed stateful reviews, exact match + fresh review per run)

## 0.1.0

Initial release.

- Ctrl+G: natural language to shell command via zle widget
- command_not_found_handler: typo and Linux→macOS correction
- TRAPZERR: one-line failure explanation
- Dynamic few-shot retrieval from 21k tldr examples via SQLite FTS5
- ~68% accuracy (~72% with targeted overrides + `--temperature 0.3 --samples 3`)
- `--notfound` and `--explain` CLI modes
- Pre-built 4MB database, no setup required
