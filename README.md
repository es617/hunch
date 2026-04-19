# hunch

![macOS](https://img.shields.io/badge/macOS-26_Tahoe-000000?logo=apple)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Swift](https://img.shields.io/badge/Swift-6.2-FA7343.svg)
![On-Device](https://img.shields.io/badge/LLM-on--device-green)

An on-device shell command generator for macOS Tahoe. Type what you want in plain English, get the actual command. No cloud, no API keys, no dependencies beyond what ships with your Mac.

Uses Apple's FoundationModels framework (3B parameter model, Neural Engine) with dynamic few-shot retrieval from 21,000+ [tldr](https://github.com/tldr-pages/tldr) examples for improved accuracy.

> **Example:** Type `find files changed in the last hour`, hit Ctrl+G, get `find . -mmin -60`.

![hunch demo](https://raw.githubusercontent.com/es617/hunch/main/docs/demo.gif)

**[Blog post](https://es617.dev/2026/04/08/apple-on-device-llm-shell.html)** — full benchmark data, 10 approaches tested, and what the results say about small on-device models.

---

## Why this exists

Apple shipped a 3B language model on every Mac running Tahoe. It runs on the Neural Engine, costs nothing, and responds in under a second. But out of the box, it hallucinates shell command flags, doesn't know macOS-specific tools (`pbcopy`, `caffeinate`, `pmset`), and reaches for Linux commands that don't exist on macOS.

hunch fixes this with a technique from the GPT-3 era: dynamic few-shot retrieval. Before asking the model to generate a command, it searches a bank of 21,000 correct command examples (sourced from the community-maintained [tldr pages](https://github.com/tldr-pages/tldr)) and injects the 8 most similar examples into the prompt. The model copies the right patterns instead of guessing.

On a 100-prompt benchmark, this takes accuracy from 40% (bare model) to **~83%** — without leaving the device. Accuracy scales with the bank: more examples = better results.

## Who it's for

- **Developers who forget flags** — `find -mmin` vs `-mtime`, `tar czf` vs `tar xzf`, `git branch --sort=-committerdate`. You know the command exists, you just can't remember the syntax.
- **Anyone curious about on-device LLMs** — hunch is a practical testbed for what Apple's 3B model can and can't do, with published benchmark data.

---

## Quickstart

**Homebrew:**

```bash
brew tap es617/tap && brew install hunch
```

**From source:**

```bash
git clone https://github.com/es617/hunch.git
cd hunch
make build
make install          # installs to ~/.local (no sudo)
```

Then add to `~/.zshrc`:

```bash
# Homebrew:
source /opt/homebrew/share/hunch/hunch.zsh

# Or from source:
source ~/.local/share/hunch/hunch.zsh
```

Open a new terminal. Type a description, hit **Ctrl+G**.

## What it does

Three zsh hooks, each targeting a different moment in the command lifecycle:

| Hook | Trigger | What happens |
|------|---------|-------------|
| **Ctrl+G** | You hit the keybind | Natural language in the buffer is replaced with the actual command. You inspect before running. |
| **Not found** | Command not found | Typos (`gti` → `did you mean: git`), installable tools (`ncdu` → `not installed: brew install ncdu`), Linux→macOS (`ip a` → `macOS equivalent: ifconfig`). |
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
# Optional: trade speed for consistency
export HUNCH_TEMPERATURE=0.3   # add variation to model output
export HUNCH_SAMPLES=3         # run 3 times, pick majority answer

source /opt/homebrew/share/hunch/hunch.zsh
```

| Variable | Default | Effect |
|----------|---------|--------|
| `HUNCH_TEMPERATURE` | 0 | Higher = more variation. 0.3 is the sweet spot. |
| `HUNCH_SAMPLES` | 1 | Run N times, majority vote. Same accuracy, less variance. ~1.3s latency. |

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
| `~/.local/bin/hunch` | ~1 MB | Swift binary (FoundationModels + SQLite FTS5) |
| `~/.local/share/hunch/tldr_bank.db` | 4 MB | Pre-built FTS5 index (21k Q/A pairs) |
| `~/.local/share/hunch/hunch.zsh` | 2 KB | zsh plugin (Ctrl+G, typo, failure hooks) |

---

## Benchmark

100-prompt benchmark (simple, flag-heavy, and composed commands), scored end-to-end through the shipped CLI:

| Mode | Accuracy | Avg Time | Notes |
|------|----------|----------|-------|
| **hunch (shipped)** | **~83%** | 0.5s | Three-tier retrieval + overrides + validation + tuned prompt |
| hunch v0.1.2 | ~78% | 0.5s | FTS5 retrieval + overrides + tuned prompt |
| hunch (retrieval only) | ~72% | 0.5s | Before adding targeted overrides |
| Bare prompt (no DB) | 41% | 0.4s | What the model knows from training alone |
| Static few-shot | 43% | 1.1s | 8 hand-picked examples |
| Man page index | 37% | 1.5s | Flag descriptions from man pages |
| Self-critique | 33% | 0.7s | Generate then verify — made things worse |

The example bank is the main driver of accuracy (+42pp over bare prompt). v0.1.3 adds three-tier retrieval (overrides → macOS-specific → common), which prioritizes curated examples over the 21k tldr entries. A lightweight command validation retries hallucinated commands that don't exist locally or in the tldr bank. The shipped bank includes targeted overrides for common patterns where the base tldr pages had gaps (e.g., `find -size`, `curl -I`, `grep --include`). These overrides were developed by analyzing benchmark failures, so the 83% figure reflects the shipped product rather than an independent test. The 72% retrieval-only number was measured before adding those overrides.

You can add your own overrides in `bank/macos_overrides.tsv` and rebuild with `make update-bank`. PRs welcome. See `benchmark/APPROACHES.md` for the full breakdown of all approaches tested.

The benchmark suite is in `benchmark/` — run it yourself with `python3 benchmark/run.py`.

### Limitations

In practice, the basics are reliable — simple commands, macOS-specific tools (`pbcopy`, `caffeinate`, `sips`), git operations, network diagnostics, file operations. A small set remains flaky — right command, varying flags. Those are where the example bank and your own overrides make the difference.

**Always read the command before hitting Enter.** The Ctrl+G design makes this safe — it fills the buffer, it never executes.

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
make install
```

This clones [tldr-pages](https://github.com/tldr-pages/tldr), parses all entries into Q/A pairs, adds macOS-specific overrides, and rebuilds the FTS5 index.

## LoRA Adapter Training (experimental)

The `training/` directory contains infrastructure for fine-tuning Apple's on-device 3B model using LoRA adapters. QLoRA training works on a free Colab T4 or locally on a 24GB Mac. See `training/TRAINING.md` for full details, results, and notebooks.

```bash
hunch --adapter path/to/hunch.fmadapter "find files changed in the last hour"
```

Current finding: adapter + retrieval reaches ~86% accuracy (vs ~79% retrieval alone). QLoRA matches full LoRA quality, and Mac-trained adapters match T4-trained.

> **Known bug (as of April 2026):** Apple's `TGOnDeviceInferenceProviderService` caches a full copy of the adapter (~160MB) on every CLI invocation and never cleans up. Repeated adapter calls from CLI tools can consume significant disk space. Apple has confirmed this as a known bug specific to CLI tools. See `training/adapter-disk-leak-findings.md` for details and workaround.

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

[MIT](LICENSE)

## Acknowledgements

- [apfel](https://github.com/Arthur-Ficial/apfel) by Arthur-Ficial — the CLI that proved Apple's on-device model was accessible from the terminal and inspired this project. hunch builds on the same idea but bundles the tldr retrieval pipeline for improved accuracy.
- [tldr-pages](https://github.com/tldr-pages/tldr) — community-maintained command examples that power the few-shot retrieval bank.
