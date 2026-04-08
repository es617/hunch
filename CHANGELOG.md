# Changelog

## 0.1.0

Initial release.

- Ctrl+G: natural language to shell command via zle widget
- command_not_found_handler: typo and Linux→macOS correction
- TRAPZERR: one-line failure explanation
- Dynamic few-shot retrieval from 21k tldr examples via SQLite FTS5
- 66% accuracy (73% with `--temperature 0.3 --samples 3`)
- `--notfound` and `--explain` CLI modes
- Pre-built 4MB database, no setup required
