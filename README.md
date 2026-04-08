# hunch

![macOS](https://img.shields.io/badge/macOS-26_Tahoe-000000?logo=apple)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Swift](https://img.shields.io/badge/Swift-6.2-FA7343.svg)
![On-Device](https://img.shields.io/badge/LLM-on--device-green)

An on-device shell command generator for macOS Tahoe. Type what you want in plain English, get the actual command. No cloud, no API keys, no dependencies beyond what ships with your Mac.

Uses Apple's FoundationModels framework (3B parameter model, Neural Engine) with dynamic few-shot retrieval from 21,000+ [tldr](https://github.com/tldr-pages/tldr) examples for improved accuracy.

> **Example:** Type `find files changed in the last hour`, hit Ctrl+G, get `find . -mmin -60`.

---

## Why this exists

Apple shipped a 3B language model on every Mac running Tahoe. It runs on the Neural Engine, costs nothing, and responds in under a second. But out of the box, it hallucinates shell command flags, doesn't know macOS-specific tools (`pbcopy`, `caffeinate`, `pmset`), and reaches for Linux commands that don't exist on macOS.

hunch fixes this with a technique from the GPT-3 era: dynamic few-shot retrieval. Before asking the model to generate a command, it searches a bank of 21,000 correct command examples (sourced from the community-maintained [tldr pages](https://github.com/tldr-pages/tldr)) and injects the 8 most similar examples into the prompt. The model copies the right patterns instead of guessing.

This takes accuracy from **40% to 68%** on a 100-prompt benchmark — without leaving the device.

## Who it's for

- **Developers who forget flags** — `find -mmin` vs `-mtime`, `tar czf` vs `tar xzf`, `git branch --sort=-committerdate`. You know the command exists, you just can't remember the syntax.
- **Linux users on macOS** — the model's training data is Linux-heavy. Without hunch, it suggests `ip a` instead of `ifconfig`, `systemctl` instead of `launchctl`. The example bank corrects this.
- **Anyone curious about on-device LLMs** — hunch is a practical testbed for what Apple's 3B model can and can't do, with published benchmark data.

---

## Quickstart

```bash
git clone https://github.com/es617/hunch.git
cd hunch
make build
sudo make install
```

Add to `~/.zshrc`:

```bash
source /usr/local/share/hunch/hunch.zsh
```

Open a new terminal. Type a description, hit **Ctrl+G**.

## What it does

Three zsh hooks, each targeting a different moment in the command lifecycle:

| Hook | Trigger | What happens |
|------|---------|-------------|
| **Ctrl+G** | You hit the keybind | Natural language in the buffer is replaced with the actual command. You inspect before running. |
| **Typo** | Command not found | `ip a` → `did you mean: ifconfig`. Searches the bank for macOS equivalents. |
| **Failure** | Non-zero exit | One-line explanation of what went wrong, in dim grey. |

### CLI usage

```bash
hunch find files changed in the last hour      # → find . -mmin -60
hunch --notfound ip a                           # → ifconfig
hunch --explain "Command: git push — Exit code: 128"  # → explains the error
hunch --temperature 0.3 --samples 3 show disk usage   # → accuracy mode
```

### Configuration

Set environment variables in `~/.zshrc` (before the `source` line) to tune the Ctrl+G behavior:

```bash
# Optional: trade speed for accuracy (75% vs 66%)
export HUNCH_TEMPERATURE=0.3   # add variation to model output
export HUNCH_SAMPLES=3         # run 3 times, pick majority answer

source /usr/local/share/hunch/hunch.zsh
```

| Variable | Default | Effect |
|----------|---------|--------|
| `HUNCH_TEMPERATURE` | 0 (deterministic) | Higher = more variation. 0.3 is the sweet spot. |
| `HUNCH_SAMPLES` | 1 | Run N times, majority vote. 3 gives +9pp accuracy at ~1.7s latency. |

Run `hunch --help` to see current settings and database status.

---

## How it works

```
User types "find files changed in the last hour" + Ctrl+G
  → zsh hook calls hunch
    → FTS5 search: tldr_bank.db (21k Q/A pairs) → top 8 similar examples
    → Builds system prompt with examples as Q/A pairs
    → Calls FoundationModels (on-device, Neural Engine, ~0.4s)
    → Strips markdown, returns command
  → zsh replaces buffer → user inspects → Enter
```

The key insight: the 3B model is a pattern-copier, not a reasoner. Feeding it documentation (man pages, flag indexes) doesn't improve accuracy. Feeding it similar solved examples does. Dynamic few-shot retrieval from a large bank is the technique that works.

### What gets installed

| File | Size | Purpose |
|------|------|---------|
| `/usr/local/bin/hunch` | ~1 MB | Swift binary (FoundationModels + SQLite FTS5) |
| `/usr/local/share/hunch/tldr_bank.db` | 4 MB | Pre-built FTS5 index (21k Q/A pairs) |
| `/usr/local/share/hunch/hunch.zsh` | 2 KB | zsh plugin (Ctrl+G, typo, failure hooks) |

---

## Benchmark

100 prompts across 10 approaches. Each result scored as exact match, manually accepted (functionally correct), or wrong.

| Approach | Usable | Avg Time | Notes |
|----------|--------|----------|-------|
| **hunch (dynshot-tldr)** | **68%** | 0.4s | FTS5 search over 21k tldr examples |
| Static few-shot | 43% | 1.1s | 8 hand-picked examples |
| Bare prompt | 40% | 0.4s | No examples |
| Man page index | 37% | 1.5s | Flag descriptions from man pages |
| Self-critique | 33% | 0.7s | Generate then verify — made things worse |

The model can't read documentation and apply it. It can copy patterns from similar examples. The benchmark suite is in `benchmark/` — run it yourself with `python3 benchmark/run.py`.

### What the model gets right

- Simple commands: `ls`, `pwd`, `date`, `cal`, `top`, `uptime`
- Common flags: `find . -name '*.png'`, `tar xzf`, `git log --oneline`, `curl -O`
- macOS commands (with examples): `pbcopy`, `caffeinate`, `pmset -g batt`, `open .`
- Composed commands: `kill $(lsof -t -i :3000)`, `du -sh * | sort -hr`

### What it gets wrong

- **Invents flags**: `-mtime +1h` (invalid) instead of `-mmin -60`
- **Linux bias**: `ip a`, `systemctl`, `lsusb` instead of macOS equivalents
- **Can't construct awk/sed one-liners** reliably
- **Dangerous hallucinations**: `git reset --hard` when asked for `--soft`

The Ctrl+G design (inspect before running) makes the wrong answers safe — annoying, not dangerous.

---

## Requirements

- macOS 26 Tahoe
- Apple Silicon
- Apple Intelligence enabled
- Xcode Command Line Tools (for building from source)

## Updating the bank

The pre-built `tldr_bank.db` ships with the release. To regenerate from latest tldr pages:

```bash
make update-bank
sudo make install
```

This clones [tldr-pages](https://github.com/tldr-pages/tldr), parses all entries into Q/A pairs, adds macOS-specific overrides, and rebuilds the FTS5 index.

## Known limitations

- **4K token context window** — the system prompt + 8 examples + query + output must fit. Current prompts use ~200-400 tokens, well within budget.
- **Neural Engine cold start** — first call after sleep/reboot takes 1-2s. Subsequent calls are ~0.4s.
- **Guardrails** — Apple's safety filter occasionally blocks innocuous shell-related prompts. hunch uses `--permissive` guardrails to minimize false positives.
- **Sequoia and earlier** — FoundationModels is Tahoe-only. No fallback for older macOS versions.

## Safety

- **Ctrl+G never executes commands** — it only fills the zsh buffer. You always inspect before running.
- **TRAPZERR filters sensitive commands** — commands containing `password`, `token`, `secret`, `Bearer`, or `api-key` are not sent to the model.
- **Everything is on-device** — no network calls, no telemetry, no data leaves your Mac.
- **The model will hallucinate** — treat suggestions as starting points, not gospel. Always read the command before hitting Enter.

## License

MIT

## Acknowledgements

- [apfel](https://github.com/Arthur-Ficial/apfel) by Arthur-Ficial — the CLI that proved Apple's on-device model was accessible from the terminal and inspired this project. hunch builds on the same idea but bundles the tldr retrieval pipeline for improved accuracy.
- [tldr-pages](https://github.com/tldr-pages/tldr) — community-maintained command examples that power the few-shot retrieval bank.
