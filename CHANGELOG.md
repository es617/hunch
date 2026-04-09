# Changelog

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
