# Benchmark Approaches

100 prompts (31 simple, 51 flag-heavy, 18 composed), each scored as exact match, manually accepted, or wrong.

## Results

| # | Approach | Usable | Time | Description |
|---|----------|--------|------|-------------|
| 1 | minimal | 40% | 0.4s | Bare prompt, no examples |
| 2 | permissive | 41% | 0.3s | Bare prompt, relaxed guardrails |
| 3 | manindex | 37% | 1.5s | Two-pass: get command name, inject man page flag index |
| 4 | tldr | 38% | 1.4s | Two-pass: get command name, inject tldr page as context |
| 5 | fewshot | 43% | 1.1s | 8 static hand-picked examples in prompt |
| 6 | dynshot | 69%* | 0.9s | 8 similar examples from 76 hand-crafted Q/A pairs |
| 7 | selfconsist | 41% | 1.1s | 3 runs at temp 0, majority vote |
| 8 | verify | 33% | 0.7s | Generate then self-critique |
| 9 | hunch | 66% | 0.4s | Shipped CLI: FTS5 search over 21k tldr examples |
| 10 | hunch-sc | 73% | 1.3s | Shipped CLI: temp 0.3, 3 samples, majority vote |

\* Biased — bank was built after seeing test prompts. Hold-out test showed +4pp real gain.

## Approach Details

### 1. minimal (40%)

Bare prompt: "Output a single shell command for zsh on macOS." One call, no examples. This is what the model knows from training alone.

### 2. permissive (41%)

Same bare prompt but with Apple's `--permissive` flag that relaxes guardrails. Barely different — guardrails aren't the bottleneck.

### 3. manindex (37%)

Two calls. First: "what command would you use?" → model returns `find`. Second: parse `man find` into a flag index (flag name + one-line description via awk), inject into the prompt, generate the command. Failed because the model can see `-mmin` in the docs but can't reason about how to use it correctly.

### 4. tldr (38%)

Two calls. First: get command name. Second: fetch the tldr page for that command (~37 lines of community-written examples) and inject as context. Failed because the model treats it as documentation to read, not patterns to copy. Also, the tldr page might not include the specific example needed (e.g. no `-mmin` example in `tldr find`).

### 5. fewshot (43%)

One call with 8 hand-picked Q/A examples hardcoded in the system prompt, covering macOS-specific commands and common gotchas. Works better than docs because the model copies patterns instead of reasoning over reference material. But 8 fixed examples can't cover the full range of queries.

### 6. dynshot (69%, biased)

One call. At query time, search a bank of 76 hand-crafted Q/A pairs for the 8 most similar to the user's query using token-overlap similarity. Inject those as examples. Better than static because the examples are relevant to the specific query.

The 69% number is inflated — the 76-example bank was written after seeing the 100 test prompts. A hold-out test (50 train / 50 test split) showed the real gain was only +4pp over baseline. The technique is sound but the bank was too small and tuned to the test set.

### 7. selfconsist (41%)

Three calls at temperature 0, pick the majority answer. Completely useless because temperature 0 means the model is deterministic — it returns the same answer every time. Three identical answers, 3x the latency, zero improvement.

### 8. verify (33%)

Two calls. First: generate the command normally. Second: "Is this command correct for macOS? If not, fix it." Made things worse — dropped to 33%, below baseline. The model uses the same broken reasoning in the second pass to "fix" correct commands into wrong ones. A 3B cannot self-critique.

### 9. hunch (66%)

The shipped CLI. Same dynamic few-shot technique as dynshot but with 21,408 examples from the community-maintained tldr-pages project + 60 macOS-specific overrides, searched via SQLite FTS5. Unbiased — the tldr corpus was not built for this benchmark.

At query time: FTS5 search → top 8 results → format as Q/A pairs in the system prompt → single on-device model call with permissive guardrails. Total latency ~0.4s.

### 10. hunch-sc (73%)

Same as hunch but with two model settings changed:

**Temperature 0.3** — adds slight randomness to the model's output. At temperature 0 (default), the model always picks the most likely next token — deterministic, same input always gives same output. At 0.3, it sometimes picks the 2nd or 3rd most likely token, producing slightly different answers each run.

**3 samples with majority vote** — run the same prompt 3 times, pick the most common answer. The examples in the prompt push the model toward the correct pattern. With temperature variation, each run has a chance of following the pattern (correct) or drifting (wrong). The drift is random and goes in different directions, but the correct answer is consistent because the examples are consistent. Majority vote filters out the random drift.

This only works *with the example bank*. Without examples, self-consistency at temp 0.3 scores 39% — all 3 answers are equally wrong in different ways. The examples create the correlation that makes voting work.

Tradeoff: 3 calls instead of 1, ~1.3s instead of 0.4s. You're buying 7 percentage points of accuracy with 3x the latency.

## Key Findings

- **Examples > documentation.** The model can't read docs and apply them. It needs solved problems to copy.
- **Bank size matters.** 76 examples → 46% (unbiased). 21k examples → 66%. More patterns = more to copy from.
- **Self-consistency needs examples + temperature.** Without examples: useless. Without temperature: useless. Both together: +7pp.
- **Self-critique hurts.** The model can't evaluate its own output. Don't ask it to.
- **The 3B wall.** The model can classify intent and copy patterns but cannot reason over documentation to derive correct usage.
