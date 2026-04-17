# Benchmark Review Criteria

Rules for deciding whether a non-exact result is "functionally correct" and should be added to alternates.json. Apply these consistently across all reviews.

## ACCEPT — add to alternates.json

### Placeholder variations
Different placeholder names for the same command structure:
- `file` vs `filename` vs `file.txt` — accept
- `src dst` vs `source destination` vs `source_directory destination_directory` — accept
- `user@host` vs `user@server` vs `username@remote_host` — accept
- `example.com` vs `api.example.com` vs `localhost:8000` — accept

### Quote style
- Single vs double quotes: `'*.png'` vs `"*.png"` — accept
- With or without quotes when not ambiguous: `-name .DS_Store` vs `-name '.DS_Store'` — accept

### Flag reordering
Same flags in different order:
- `tar -xvzf` vs `tar -zxvf` — accept
- `rsync -avz` vs `rsync -avzh` (extra harmless flag) — accept cautiously

### Harmless extra flags
Flags that don't change the core behavior:
- `tar -czvf` (verbose) vs `tar -czf` — accept
- `cp -R` vs `cp -r` (same on macOS) — accept
- Adding `--progress` to rsync — accept

### Format variations
Same result, slightly different format:
- `git log --oneline` vs `git log --pretty=oneline` — accept
- `echo $SHELL` vs `echo $0` — accept (both show shell)

## REJECT — do not add to alternates.json

### Wrong command entirely
- `system_profiler` for "monitor cpu usage" (should be `top`) — reject
- `pbcopy` for "paste from clipboard" (that's copy, not paste) — reject
- `cls` for "clear terminal" (Windows command) — reject

### Wrong flags that change meaning
- `find . -mtime -60` for "files changed in last hour" (`-mtime` is days, not minutes) — reject
- `find . -mtime +1` for "files modified today" (opposite: MORE than 1 day ago) — reject
- `head -50` for "last 50 lines" (head shows FIRST, not last) — reject
- `tail -n 20` for "first 20 lines" (tail shows LAST, not first) — reject

### Missing critical parts
- `cp -r directory` (missing destination) — reject
- `find .DS_Store -delete` (missing `.` path, only current dir entry) — reject
- `zip -r .` (missing output filename) — reject
- `ssh user@server` (missing `-i key` when prompt asks for specific key) — reject

### Hallucinated commands/flags
- `git log --no-pushed` (not a real flag) — reject
- `git rename-branch` (not a real command) — reject
- `find . -type symlink` (invalid type, should be `l`) — reject
- `link -s` (not the same as `ln -s`) — reject
- `zipdir`, `pylist`, `mcal` — reject

### Broadened scope
- `find . -empty` for "find empty directories" (also finds empty files) — reject
- `find . -name node_modules` for "find directories named node_modules" (also finds files) — accept only with `-type d`
- `git branch --merged | xargs git branch -d` without `grep -v main` (would delete main) — reject

### Functionally different approach
- `comm -12 <(sort file1) <(sort file2)` for "compare two files" (shows common lines, not differences) — reject
- `du -sh /` for "show disk usage" (directory usage, not filesystem usage like `df`) — reject
- `find . -name '*.py' | wc -l` for "count lines in python files" (counts FILES, not lines IN them) — reject

### Piped through unnecessary commands
- `cat file | head -20` for "first 20 lines" — accept (useless cat but correct)
- `find ... | wc -l` when it should be `find ... -exec wc -l` — reject (counts files not lines)

## EDGE CASES

### `find . -empty` for "find empty directories"
REJECT. `-empty` matches both empty files and directories. The prompt specifically asks for directories. Need `-type d -empty`.

### `sips -s format jpeg input.jpg --out output.jpg` (same format in and out)
REJECT. The prompt says "convert to different format." While the command structure is correct, the example converts jpg→jpg. Accept only if input and output formats differ.

### `sips -s format jpg` (without `--out`)
REJECT. `jpg` is not a valid sips format name (should be `jpeg`).

### curl POST with different URLs/bodies
ACCEPT if structure is correct: has `-X POST`, has `-H "Content-Type: application/json"`, has `-d`. Different URLs and body content are just placeholder variations.

### rsync with `--delete`
REJECT. Adding `--delete` removes files at destination that don't exist at source. That's a meaningfully different and potentially destructive operation.

### `caffeinate -t 3600` for "prevent mac from sleeping"
ACCEPT. Keeps awake for 1 hour — reasonable interpretation.

### `env | grep PATH` vs `export PATH`
ACCEPT both. Different mechanisms but both show PATH.
