#!/usr/bin/env python3
"""Run apfel benchmark across different prompt approaches.

Usage:
  python3 run.py                          # run all approaches, all prompts
  python3 run.py minimal                  # run one approach
  python3 run.py minimal --ids 1,2,3      # run specific prompts
  python3 run.py minimal --category flags # run one category
  python3 run.py all                       # run all approaches
"""

import json
import subprocess
import time
import sys
import re
import os
import math
from pathlib import Path
from collections import Counter

PROMPTS_FILE = Path(__file__).parent / "prompts.jsonl"
RESULTS_DIR = Path(__file__).parent / "results"
FEWSHOT_BANK = Path(__file__).parent / "fewshot_bank.json"
HOLDOUT_BANK = Path(__file__).parent / "holdout_bank.json"
RESULTS_DIR.mkdir(exist_ok=True)

TIMEOUT = 10  # seconds per apfel call (normal response is <1s)


def load_fewshot_bank():
    if FEWSHOT_BANK.exists():
        with open(FEWSHOT_BANK) as f:
            return json.load(f)
    return []


# Simple TF-IDF-ish similarity for dynamic few-shot selection
def tokenize(text):
    return set(re.findall(r'[a-z]+', text.lower()))


def similarity(query_tokens, example_tokens):
    if not query_tokens or not example_tokens:
        return 0
    intersection = query_tokens & example_tokens
    return len(intersection) / math.sqrt(len(query_tokens) * len(example_tokens))


def select_fewshot(prompt, bank, n=8, exclude_exact=None):
    """Select n most similar examples from the bank."""
    query_tokens = tokenize(prompt)
    scored = []
    for ex in bank:
        # Don't include examples that are too close to the test prompt
        if exclude_exact and ex["q"].lower().strip() == exclude_exact.lower().strip():
            continue
        ex_tokens = tokenize(ex["q"])
        score = similarity(query_tokens, ex_tokens)
        # Boost examples that share tags
        scored.append((score, ex))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ex for _, ex in scored[:n]]


def format_fewshot_examples(examples):
    """Format few-shot examples as Q/A pairs."""
    lines = []
    for ex in examples:
        lines.append(f"Q: {ex['q']}")
        lines.append(f"A: {ex['a']}")
    return "\n".join(lines)


def strip_markdown(s):
    s = s.replace("```bash", "").replace("```zsh", "").replace("```shell", "")
    s = s.replace("```", "").replace("`", "")
    s = s.strip()
    return s


def run_apfel(prompt, system_prompt, permissive=False, max_tokens=None, retries=2):
    """Run a single apfel call, return (output, elapsed_seconds). Retries on timeout."""
    cmd = ["apfel", "-q", "--temperature", "0"]
    if permissive:
        cmd.append("--permissive")
    if max_tokens:
        cmd.extend(["--max-tokens", str(max_tokens)])
    cmd.extend(["-s", system_prompt, prompt])

    for attempt in range(retries + 1):
        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TIMEOUT
            )
            elapsed = round(time.time() - start, 2)
            output = result.stdout.strip()
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if "guardrail" in stderr.lower():
                    return "[GUARDRAIL]", elapsed
                elif "context overflow" in stderr.lower():
                    return "[OVERFLOW]", elapsed
                else:
                    return f"[ERROR:{result.returncode}] {stderr[:100]}", elapsed
            return strip_markdown(output), elapsed
        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - start, 2)
            if attempt < retries:
                # Kill any stuck apfel process before retrying
                subprocess.run(["pkill", "-f", "apfel"], capture_output=True)
                time.sleep(1)
                continue
            return "[TIMEOUT]", elapsed


def man_flag_index(cmd_name):
    """Extract flag index from man page: flag name + 2 lines of description."""
    try:
        result = subprocess.run(
            ["man", cmd_name], capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return ""
        # col -b to strip formatting
        col = subprocess.run(
            ["col", "-b"], input=result.stdout, capture_output=True, text=True
        )
        lines = col.stdout.split("\n")

        flags = []
        i = 0
        while i < len(lines):
            if re.match(r"^\s{4,}-[a-z]", lines[i]):
                flag_line = lines[i]
                desc_lines = []
                for j in range(1, 3):
                    if i + j < len(lines):
                        desc_lines.append(lines[i + j].strip())
                flags.append(f"{flag_line} — {' '.join(desc_lines)}")
                i += 3
            else:
                i += 1
        return "\n".join(flags)
    except Exception:
        return ""


def fetch_tldr(cmd_name):
    """Fetch tldr page from GitHub."""
    for section in ["common", "osx", "linux"]:
        url = f"https://raw.githubusercontent.com/tldr-pages/tldr/main/pages/{section}/{cmd_name}.md"
        try:
            result = subprocess.run(
                ["curl", "-sf", url], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            continue
    return ""


# --- Approach runners ---

SYS_PROMPT = "Output a single shell command for zsh on macOS. No explanation, no markdown, no backticks. Just the command."
CMD_PROMPT = "What single Unix command would you use? Output only the command name."


def approach_minimal(prompt):
    output, elapsed = run_apfel(prompt, SYS_PROMPT)
    return {"result": output, "total_time": elapsed, "pass1_time": elapsed}


def approach_permissive(prompt):
    output, elapsed = run_apfel(prompt, SYS_PROMPT, permissive=True)
    return {"result": output, "total_time": elapsed, "pass1_time": elapsed}


def approach_manindex(prompt, permissive=False):
    # Pass 1: get command name
    base_cmd, t1 = run_apfel(prompt, CMD_PROMPT, max_tokens=10)
    base_cmd = base_cmd.replace("`", "").split()[0] if base_cmd else ""

    # Get flag index
    flags = ""
    if base_cmd and not base_cmd.startswith("["):
        flags = man_flag_index(base_cmd)

    # Pass 2: generate with flag index
    sys_prompt = SYS_PROMPT
    if flags:
        sys_prompt += f"\nAvailable flags for {base_cmd}:\n{flags}"

    output, t2 = run_apfel(prompt, sys_prompt, permissive=permissive)
    return {
        "result": output,
        "base_cmd": base_cmd,
        "pass1_time": t1,
        "pass2_time": t2,
        "total_time": round(t1 + t2, 2),
    }


def approach_manindex_p(prompt):
    return approach_manindex(prompt, permissive=True)


def approach_tldr(prompt):
    # Pass 1: get command name
    base_cmd, t1 = run_apfel(prompt, CMD_PROMPT, max_tokens=10)
    base_cmd = base_cmd.replace("`", "").split()[0] if base_cmd else ""

    # Fetch tldr
    tldr_text = ""
    if base_cmd and not base_cmd.startswith("["):
        tldr_text = fetch_tldr(base_cmd)

    # Pass 2
    sys_prompt = SYS_PROMPT
    if tldr_text:
        sys_prompt += f"\n{tldr_text}"

    output, t2 = run_apfel(prompt, sys_prompt)
    return {
        "result": output,
        "base_cmd": base_cmd,
        "pass1_time": t1,
        "pass2_time": t2,
        "total_time": round(t1 + t2, 2),
    }


def approach_fewshot(prompt):
    """Static few-shot: pick 8 diverse examples covering key patterns."""
    bank = load_fewshot_bank()
    # Static selection: pick examples covering different categories
    static_examples = [
        ex for ex in bank if ex["q"] in [
            "find files modified in the last 30 minutes",
            "find files bigger than 500mb",
            "copy text to clipboard",
            "prevent sleep",
            "show battery percentage",
            "stop whatever is running on port 8080",
            "show git changes since last commit",
            "sum all numbers in first column",
        ]
    ]
    examples_text = format_fewshot_examples(static_examples)
    sys_prompt = f"""Output a single shell command for zsh on macOS. No explanation, no markdown, no backticks. Just the command.

Examples:
{examples_text}"""

    output, elapsed = run_apfel(prompt, sys_prompt, permissive=True)
    return {"result": output, "total_time": elapsed, "pass1_time": elapsed}


def approach_dynshot(prompt):
    """Dynamic few-shot: select 8 most similar examples to the query."""
    bank = load_fewshot_bank()
    selected = select_fewshot(prompt, bank, n=8, exclude_exact=prompt)
    examples_text = format_fewshot_examples(selected)

    sys_prompt = f"""Output a single shell command for zsh on macOS. No explanation, no markdown, no backticks. Just the command.

Examples:
{examples_text}"""

    output, elapsed = run_apfel(prompt, sys_prompt, permissive=True)
    return {"result": output, "total_time": elapsed, "pass1_time": elapsed}


def approach_selfconsist(prompt):
    """Self-consistency: run 3 times, pick majority answer."""
    results = []
    total_time = 0
    for _ in range(3):
        output, elapsed = run_apfel(prompt, SYS_PROMPT, permissive=True)
        results.append(output)
        total_time += elapsed

    # Pick most common (strip whitespace for comparison)
    normalized = [r.strip() for r in results if not r.startswith("[")]
    if not normalized:
        return {"result": results[0] if results else "[EMPTY]", "total_time": round(total_time, 2),
                "all_results": results}

    counter = Counter(normalized)
    best = counter.most_common(1)[0][0]
    return {
        "result": best,
        "total_time": round(total_time, 2),
        "all_results": results,
        "agreement": counter.most_common(1)[0][1],
    }


def approach_selfconsist_dynshot(prompt):
    """Self-consistency with dynamic few-shot and temperature 0.3. Run 3 times, majority vote."""
    import sqlite3
    db_path = Path(__file__).parent.parent / "bank" / "tldr_bank.db"
    if not db_path.exists():
        return approach_permissive(prompt)

    words = re.findall(r'[a-zA-Z]+', prompt.lower())
    stop_words = {"the", "a", "an", "in", "on", "to", "for", "of", "and", "or", "is", "it",
                  "all", "my", "this", "that", "with", "from", "how", "do", "what"}
    words = [w for w in words if w not in stop_words and len(w) > 1]
    if not words:
        return approach_permissive(prompt)

    conn = sqlite3.connect(str(db_path))
    fts_query = " OR ".join(f'"{w}"' for w in words)
    rows = conn.execute(
        "SELECT question, answer FROM bank WHERE bank MATCH ? ORDER BY rank LIMIT 8",
        (fts_query,)
    ).fetchall()
    conn.close()

    examples = "\n".join(f"Q: {r[0]}\nA: {r[1]}" for r in rows)
    sys_prompt = f"""Output a single shell command for zsh on macOS. No explanation, no markdown, no backticks. Just the command.

Examples:
{examples}"""

    # Run 3 times with temperature 0.3
    results = []
    total_time = 0
    cmd_base = ["apfel", "-q", "--temperature", "0.3", "--permissive", "-s", sys_prompt, prompt]
    for _ in range(3):
        start = time.time()
        try:
            result = subprocess.run(cmd_base, capture_output=True, text=True, timeout=TIMEOUT)
            elapsed = round(time.time() - start, 2)
            output = strip_markdown(result.stdout.strip()) if result.returncode == 0 else "[ERROR]"
        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - start, 2)
            output = "[TIMEOUT]"
        results.append(output)
        total_time += elapsed

    normalized = [r.strip() for r in results if not r.startswith("[")]
    if not normalized:
        return {"result": results[0] if results else "[EMPTY]", "total_time": round(total_time, 2),
                "all_results": results}

    counter = Counter(normalized)
    best = counter.most_common(1)[0][0]
    return {
        "result": best,
        "total_time": round(total_time, 2),
        "all_results": results,
        "agreement": counter.most_common(1)[0][1],
    }


def approach_selfconsist_warm(prompt):
    """Self-consistency with temperature 0.3, no DB. Run 3 times, majority vote."""
    results = []
    total_time = 0
    cmd_base = ["apfel", "-q", "--temperature", "0.3", "--permissive", "-s", SYS_PROMPT, prompt]
    for _ in range(3):
        start = time.time()
        try:
            result = subprocess.run(cmd_base, capture_output=True, text=True, timeout=TIMEOUT)
            elapsed = round(time.time() - start, 2)
            output = strip_markdown(result.stdout.strip()) if result.returncode == 0 else "[ERROR]"
        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - start, 2)
            output = "[TIMEOUT]"
        results.append(output)
        total_time += elapsed

    normalized = [r.strip() for r in results if not r.startswith("[")]
    if not normalized:
        return {"result": results[0] if results else "[EMPTY]", "total_time": round(total_time, 2),
                "all_results": results}

    counter = Counter(normalized)
    best = counter.most_common(1)[0][0]
    return {
        "result": best,
        "total_time": round(total_time, 2),
        "all_results": results,
        "agreement": counter.most_common(1)[0][1],
    }


def approach_verify(prompt):
    """Generate-then-verify: generate command, then ask model to check/fix it."""
    # Pass 1: generate
    output, t1 = run_apfel(prompt, SYS_PROMPT, permissive=True)

    if output.startswith("["):
        return {"result": output, "total_time": t1, "pass1_time": t1}

    # Pass 2: verify and fix
    verify_prompt = f"""I generated this shell command for macOS zsh: {output}
The original request was: {prompt}

Is this command correct for macOS? Check:
- Does the command exist on macOS? (not Linux-only)
- Are the flags valid?
- Will it actually do what was requested?

If correct, output the same command. If wrong, output the fixed command.
Output only the command, no explanation, no markdown, no backticks."""

    fixed, t2 = run_apfel("verify", verify_prompt, permissive=True)
    return {
        "result": strip_markdown(fixed),
        "original": output,
        "pass1_time": t1,
        "pass2_time": t2,
        "total_time": round(t1 + t2, 2),
    }


def approach_hunch(prompt):
    """Call the hunch CLI directly (end-to-end test of the shipped binary)."""
    cmd = ["hunch", prompt]
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        elapsed = round(time.time() - start, 2)
        output = result.stdout.strip()
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "guardrail" in stderr.lower():
                return {"result": "[GUARDRAIL]", "total_time": elapsed}
            return {"result": f"[ERROR:{result.returncode}] {stderr[:100]}", "total_time": elapsed}
        return {"result": strip_markdown(output), "total_time": elapsed}
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 2)
        return {"result": "[TIMEOUT]", "total_time": elapsed}


def approach_hunch_sc(prompt):
    """Call hunch CLI with temperature 0.3 and 3 samples (accuracy mode)."""
    cmd = ["hunch", "--temperature", "0.3", "--samples", "3", prompt]
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        elapsed = round(time.time() - start, 2)
        output = result.stdout.strip()
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "guardrail" in stderr.lower():
                return {"result": "[GUARDRAIL]", "total_time": elapsed}
            return {"result": f"[ERROR:{result.returncode}] {stderr[:100]}", "total_time": elapsed}
        return {"result": strip_markdown(output), "total_time": elapsed}
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 2)
        return {"result": "[TIMEOUT]", "total_time": elapsed}


def _run_hunch(prompt, extra_args=None):
    """Call hunch from PATH with optional extra arguments."""
    cmd = ["hunch"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(prompt)
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        elapsed = round(time.time() - start, 2)
        output = result.stdout.strip()
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "guardrail" in stderr.lower() or "unsafe" in stderr.lower():
                return {"result": "[GUARDRAIL]", "total_time": elapsed}
            return {"result": f"[ERROR:{result.returncode}] {stderr[:100]}", "total_time": elapsed}
        return {"result": strip_markdown(output), "total_time": elapsed}
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 2)
        return {"result": "[TIMEOUT]", "total_time": elapsed}


def approach_hunch_guided(prompt):
    """Guided generation: plain struct."""
    return _run_hunch(prompt, ["--guided", "plain"])


def approach_hunch_cot(prompt):
    """Guided generation: chain of thought + command."""
    return _run_hunch(prompt, ["--guided", "cot"])


def approach_hunch_multi(prompt):
    """Guided generation: 3 candidates, majority vote in one pass."""
    return _run_hunch(prompt, ["--guided", "multi"])


def approach_hunch_cotmulti(prompt):
    """Guided generation: chain of thought + 3 candidates."""
    return _run_hunch(prompt, ["--guided", "cotmulti"])


def approach_hunch_multi_warm(prompt):
    """Guided generation: 3 candidates at temperature 0.3."""
    return _run_hunch(prompt, ["--guided", "multi", "--temperature", "0.3"])


ADAPTER_PATH = str(Path(__file__).parent.parent / "training" / "exports" / "hunch.fmadapter")
QLORA_FP16_ADAPTER_PATH = str(Path(__file__).parent.parent / "training" / "qlora-checkpoints" / "hunch_qlora_fp16.fmadapter")
QLORA_NF4_ADAPTER_PATH = str(Path(__file__).parent.parent / "training" / "qlora-checkpoints" / "hunch_qlora.fmadapter")
QLORA_OVERRIDE_ADAPTER_PATH = str(Path(__file__).parent.parent / "training" / "qlora-checkpoints" / "hunch_qlora_overrides.fmadapter")
LORA_OVERRIDE_ADAPTER_PATH = str(Path(__file__).parent.parent / "training" / "exports" / "hunch_overrides.fmadapter")


def _run_hunch_batch(prompts, extra_args=None, runs=1):
    """Run all prompts in a single hunch process using --batch mode.

    This avoids the TGOnDeviceInferenceProviderService disk leak where each
    process invocation caches a ~160MB copy of the adapter.

    Returns: dict keyed by (run, id) if runs > 1, or by id if runs == 1.
    """
    # Write prompts to a temp JSONL file
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for p in prompts:
            f.write(json.dumps({"id": p["id"], "prompt": p["prompt"]}) + "\n")
        batch_path = f.name

    cmd = ["hunch"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(["--batch", batch_path])
    if runs > 1:
        cmd.extend(["--runs", str(runs)])

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        results = {}
        count = 0
        total = len(prompts) * runs
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                count += 1
                status = r.get("result", "")[:40]
                print(f"  [{count}/{total}] #{r.get('id', '?'):3d}: {r.get('prompt', '')[:50]:50s} → {status} ({r.get('total_time', 0)}s)")
                if runs > 1:
                    results[(r["run"], r["id"])] = r
                else:
                    results[r["id"]] = r
            except (json.JSONDecodeError, KeyError):
                continue
        proc.wait()
        return results
    except Exception:
        return {}
    finally:
        os.unlink(batch_path)


def _make_batch_approach(extra_args):
    """Create a batch-aware approach function for adapter benchmarks."""
    def approach(prompt):
        # Fallback for single-prompt calls (e.g. --ids)
        return _run_hunch(prompt, extra_args)
    approach._batch_args = extra_args
    return approach


def approach_adapter_only(prompt):
    """LoRA adapter only, no retrieval."""
    return _run_hunch(prompt, ["--adapter", ADAPTER_PATH, "--limit", "0"])
approach_adapter_only._batch_args = ["--adapter", ADAPTER_PATH, "--limit", "0"]


def approach_adapter_retrieval(prompt):
    """LoRA adapter + retrieval."""
    return _run_hunch(prompt, ["--adapter", ADAPTER_PATH])
approach_adapter_retrieval._batch_args = ["--adapter", ADAPTER_PATH]


def approach_fp16lora_only(prompt):
    """fp16 LoRA adapter only, no retrieval."""
    return _run_hunch(prompt, ["--adapter", QLORA_FP16_ADAPTER_PATH, "--limit", "0"])
approach_fp16lora_only._batch_args = ["--adapter", QLORA_FP16_ADAPTER_PATH, "--limit", "0"]


def approach_fp16lora_retrieval(prompt):
    """fp16 LoRA adapter + retrieval."""
    return _run_hunch(prompt, ["--adapter", QLORA_FP16_ADAPTER_PATH])
approach_fp16lora_retrieval._batch_args = ["--adapter", QLORA_FP16_ADAPTER_PATH]


def approach_qlora_only(prompt):
    """True QLoRA (NF4) adapter only, no retrieval."""
    return _run_hunch(prompt, ["--adapter", QLORA_NF4_ADAPTER_PATH, "--limit", "0"])
approach_qlora_only._batch_args = ["--adapter", QLORA_NF4_ADAPTER_PATH, "--limit", "0"]


def approach_qlora_retrieval(prompt):
    """True QLoRA (NF4) adapter + retrieval."""
    return _run_hunch(prompt, ["--adapter", QLORA_NF4_ADAPTER_PATH])
approach_qlora_retrieval._batch_args = ["--adapter", QLORA_NF4_ADAPTER_PATH]


def approach_qlora_override_only(prompt):
    """QLoRA trained on overrides only, no retrieval."""
    return _run_hunch(prompt, ["--adapter", QLORA_OVERRIDE_ADAPTER_PATH, "--limit", "0"])
approach_qlora_override_only._batch_args = ["--adapter", QLORA_OVERRIDE_ADAPTER_PATH, "--limit", "0"]


def approach_qlora_override_retrieval(prompt):
    """QLoRA trained on overrides only + retrieval."""
    return _run_hunch(prompt, ["--adapter", QLORA_OVERRIDE_ADAPTER_PATH])
approach_qlora_override_retrieval._batch_args = ["--adapter", QLORA_OVERRIDE_ADAPTER_PATH]


def approach_dynshot_tldr(prompt):
    """Dynamic few-shot using tldr+overrides FTS5 index (21k entries)."""
    import sqlite3
    db_path = Path(__file__).parent / "tldr_bank.db"
    if not db_path.exists():
        return approach_permissive(prompt)  # fallback

    # FTS5 search
    words = re.findall(r'[a-zA-Z]+', prompt.lower())
    stop_words = {"the", "a", "an", "in", "on", "to", "for", "of", "and", "or", "is", "it",
                  "all", "my", "this", "that", "with", "from", "how", "do", "what"}
    words = [w for w in words if w not in stop_words and len(w) > 1]
    if not words:
        return approach_permissive(prompt)

    conn = sqlite3.connect(str(db_path))
    fts_query = " OR ".join(words)
    results = conn.execute(
        "SELECT question, answer FROM bank WHERE bank MATCH ? ORDER BY rank LIMIT 8",
        (fts_query,)
    ).fetchall()
    conn.close()

    if not results:
        return approach_permissive(prompt)

    examples = "\n".join(f"Q: {r[0]}\nA: {r[1]}" for r in results)
    sys_prompt = f"""Output a single shell command for zsh on macOS. No explanation, no markdown, no backticks. Just the command.

Examples:
{examples}"""

    output, elapsed = run_apfel(prompt, sys_prompt, permissive=True)
    return {"result": output, "total_time": elapsed, "pass1_time": elapsed}


def approach_dynshot_holdout(prompt):
    """Dynamic few-shot using ONLY the holdout train bank (no test leakage)."""
    if not HOLDOUT_BANK.exists():
        return {"result": "[ERROR:no-holdout-bank]", "total_time": 0}
    with open(HOLDOUT_BANK) as f:
        bank = json.load(f)
    selected = select_fewshot(prompt, bank, n=8, exclude_exact=prompt)
    examples_text = format_fewshot_examples(selected)

    sys_prompt = f"""Output a single shell command for zsh on macOS. No explanation, no markdown, no backticks. Just the command.

Examples:
{examples_text}"""

    output, elapsed = run_apfel(prompt, sys_prompt, permissive=True)
    return {"result": output, "total_time": elapsed, "pass1_time": elapsed}


APPROACHES = {
    "minimal": approach_minimal,
    "permissive": approach_permissive,
    "manindex": approach_manindex,
    "manindex-p": approach_manindex_p,
    "tldr": approach_tldr,
    "fewshot": approach_fewshot,
    "dynshot": approach_dynshot,
    "selfconsist": approach_selfconsist,
    "verify": approach_verify,
    "dynshot-holdout": approach_dynshot_holdout,
    "dynshot-tldr": approach_dynshot_tldr,
    "hunch": approach_hunch,
    "hunch-guided": approach_hunch_guided,
    "hunch-cot": approach_hunch_cot,
    "hunch-multi": approach_hunch_multi,
    "hunch-cotmulti": approach_hunch_cotmulti,
    "hunch-multi-warm": approach_hunch_multi_warm,
    "adapter-only": approach_adapter_only,
    "adapter-retrieval": approach_adapter_retrieval,
    "fp16lora-only": approach_fp16lora_only,
    "fp16lora-retrieval": approach_fp16lora_retrieval,
    "qlora-only": approach_qlora_only,
    "qlora-retrieval": approach_qlora_retrieval,
    "qlora-override-only": approach_qlora_override_only,
    "qlora-override-retrieval": approach_qlora_override_retrieval,
    "lora-override-only": _make_batch_approach(["--adapter", LORA_OVERRIDE_ADAPTER_PATH, "--limit", "0"]),
    "lora-override-retrieval": _make_batch_approach(["--adapter", LORA_OVERRIDE_ADAPTER_PATH]),
    "hunch-sc": approach_hunch_sc,
    "sc-dynshot": approach_selfconsist_dynshot,
    "sc-warm": approach_selfconsist_warm,
}


def load_prompts(ids=None, category=None):
    prompts = []
    with open(PROMPTS_FILE) as f:
        for line in f:
            p = json.loads(line)
            if ids and p["id"] not in ids:
                continue
            if category and p["category"] != category:
                continue
            prompts.append(p)
    return prompts


def run_benchmark(approach_name, prompts, suffix="", runs=1):
    func = APPROACHES[approach_name]

    print(f"\n{'=' * 60}")
    print(f"  APPROACH: {approach_name} ({len(prompts)} prompts{f', {runs} runs' if runs > 1 else ''})")
    print(f"{'=' * 60}")

    # Use batch mode for adapter approaches (avoids disk leak)
    batch_args = getattr(func, '_batch_args', None)
    if batch_args and len(prompts) > 1:
        print(f"  Using --batch mode (single process, avoids adapter disk leak)")
        batch_results = _run_hunch_batch(prompts, batch_args, runs=runs)

        all_results = []
        for run_num in range(1, runs + 1):
            run_suffix = f"-run{run_num}" if runs > 1 else ""
            outfile = RESULTS_DIR / f"{approach_name}{suffix}{run_suffix}.jsonl"

            results = []
            with open(outfile, "w") as f:
                for p in prompts:
                    if runs > 1:
                        br = batch_results.get((run_num, p["id"]), {})
                    else:
                        br = batch_results.get(p["id"], {})
                    r = {
                        "result": br.get("result", "[BATCH_ERROR]"),
                        "total_time": br.get("total_time", 0),
                    }
                    r["id"] = p["id"]
                    r["approach"] = approach_name
                    r["prompt"] = p["prompt"]
                    r["expected"] = p["expected"]
                    r["category"] = p["category"]

                    f.write(json.dumps(r) + "\n")
                    f.flush()
                    results.append(r)

            print(f"  Saved to {outfile}")
            all_results.extend(results)

        return all_results

    outfile = RESULTS_DIR / f"{approach_name}{suffix}.jsonl"
    results = []
    with open(outfile, "w") as f:
        for i, p in enumerate(prompts):
            print(f"  [{i+1}/{len(prompts)}] #{p['id']:3d}: {p['prompt'][:50]:50s} ", end="", flush=True)

            try:
                r = func(p["prompt"])
            except Exception as e:
                r = {"result": f"[EXCEPTION] {e}", "total_time": 0}

            r["id"] = p["id"]
            r["approach"] = approach_name
            r["prompt"] = p["prompt"]
            r["expected"] = p["expected"]
            r["category"] = p["category"]

            f.write(json.dumps(r) + "\n")
            f.flush()
            results.append(r)

            # Quick status
            status = r["result"][:40] if r["result"] else "empty"
            print(f"→ {status} ({r['total_time']}s)")

    print(f"  Saved to {outfile}")
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("approach", nargs="?", default="all", help="Approach name or 'all'")
    parser.add_argument("--ids", help="Comma-separated prompt IDs")
    parser.add_argument("--category", help="Filter by category: simple, flags, composed")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs (output files suffixed -run1, -run2, ...)")
    args = parser.parse_args()

    ids = [int(x) for x in args.ids.split(",")] if args.ids else None
    prompts = load_prompts(ids=ids, category=args.category)

    if not prompts:
        print("No prompts match filters.")
        sys.exit(1)

    if args.approach == "all":
        approaches = list(APPROACHES.keys())
    else:
        approaches = [args.approach]

    for a in approaches:
        if a not in APPROACHES:
            print(f"Unknown approach: {a}. Available: {', '.join(APPROACHES.keys())}")
            sys.exit(1)

    for a in approaches:
        func = APPROACHES[a]
        batch_args = getattr(func, '_batch_args', None)
        if batch_args and args.runs > 1:
            # Adapter approaches: all runs in one process
            run_benchmark(a, prompts, runs=args.runs)
        elif args.runs > 1:
            # Non-adapter approaches: loop externally
            for run_num in range(1, args.runs + 1):
                print(f"\n{'#' * 60}")
                print(f"  RUN {run_num}/{args.runs}")
                print(f"{'#' * 60}")
                run_benchmark(a, prompts, suffix=f"-run{run_num}")
        else:
            run_benchmark(a, prompts)

    print(f"\nDone. Run: python3 score.py")


if __name__ == "__main__":
    main()
