# LoRA Adapter Training for Apple's On-Device Model

An experiment in fine-tuning Apple's 3B on-device Foundation Model (AFM) using LoRA adapters. This is an alternative approach to hunch's retrieval-based pipeline — instead of feeding examples at runtime, we bake command knowledge directly into the model weights.

This is primarily an academic exercise and a resource for others exploring Apple's adapter training toolkit. The retrieval approach in hunch already achieves ~83% accuracy; this explores whether fine-tuning can do better, and documents the process for anyone who wants to train their own adapter.

## Background

### Two approaches to the same problem

The base 3B model gets ~40% accuracy on shell command generation. Two ways to improve it:

1. **Retrieval (what hunch ships)**: Search a bank of 21k examples, inject the 8 most relevant into the prompt. The model copies patterns. ~83% accuracy, 0.5s latency, 4MB database, works across OS updates.

2. **Fine-tuning (this experiment)**: Train a LoRA adapter that teaches the model shell commands directly. No retrieval needed at runtime. Potentially higher accuracy, but ~160MB adapter, tied to one OS version, requires retraining on each macOS update.

Neither is strictly better — they have different tradeoffs. A hybrid approach (adapter for base knowledge + retrieval for rare commands) could combine the best of both.

### How LoRA works

The base model has 3.18B parameters across 56 transformer layers. LoRA (Low-Rank Adaptation) freezes all of them and adds small trainable matrices alongside the existing layers:

```
Original:   output = W(input)                    # W is frozen (huge)
With LoRA:  output = W(input) + A(B(input))      # A, B are small, trainable
```

B compresses input to a low-rank space (rank 32), A expands it back. The product A*B is the same shape as W but built from ~66M parameters instead of 3.18B. Only A and B are trained — the base model doesn't change.

The output is a `.fmadapter` file (~160MB) containing only these correction matrices. On-device, it loads on top of the existing model at runtime.

### Caveats

- **Version lock**: Each adapter is tied to one macOS version. New OS release = retrain.
- **Size**: ~160MB per adapter. Too large to bundle in a CLI tool — would need separate download.
- **Entitlement**: Not needed for training or local testing. Required for App Store distribution.
- **Memory**: Training needs 24GB+ VRAM. The 12GB base model weights must fit in memory for the forward pass.

## Prerequisites

1. **Apple Developer Program membership** ($99/year) — needed to download the training toolkit
2. **Adapter training toolkit** — download from [developer.apple.com/apple-intelligence/foundation-models-adapter/](https://developer.apple.com/apple-intelligence/foundation-models-adapter/)
3. **GPU with 24GB+ VRAM** — A10G, A100, or similar. Mac with 32GB+ works via MPS. 24GB Mac will OOM.
4. **Python 3.11+**

## Setup

### 1. Download the toolkit

Sign in at developer.apple.com, download the adapter training toolkit, extract into this directory:

```
training/
├── adapter_training_toolkit_v26_0_0/   # Apple's toolkit (~12GB with model weights)
│   ├── assets/                          # Base model weights (12GB)
│   ├── examples/                        # Training scripts
│   ├── export/                          # .fmadapter export (DO NOT MODIFY)
│   └── requirements.txt
├── prepare_data.py                      # Converts hunch bank → training JSONL
├── train_adapter.ipynb                  # Colab notebook
├── train_cloud.sh                       # CLI training script
└── README.md
```

### 2. Prepare training data

```bash
cd training

# Generate train.jsonl and eval.jsonl from the bank
python3 prepare_data.py

# Show dataset statistics
python3 prepare_data.py --stats
```

This produces ~19k training and ~3k eval examples in Apple's expected format:
```json
[
  {"role": "system", "content": "Output a single shell command for zsh on macOS..."},
  {"role": "user", "content": "find files changed in the last hour"},
  {"role": "assistant", "content": "find . -mmin -60"}
]
```

Benchmark prompts are excluded from training data to avoid leakage. Override and tldr-osx entries appear in both train and eval sets (they're the most important examples).

## Training

### Option A: Google Colab (recommended)

Easiest path. Requires Colab Pro ($10/month) for A100 GPU access.

1. **Upload to Google Drive:**
   - Create `My Drive/hunch-training/`
   - Upload `adapter_training_toolkit_v26_0_0/` (~12GB, do this once)
   - Upload `prepare_data.py`
   - Upload `../bank/tldr_bank.db` and `../benchmark/prompts.jsonl`

2. **Install VS Code extension:**
   - In VS Code, install the "Google Colab" extension
   - Open `train_adapter.ipynb`
   - Click "Select Kernel" → Colab → choose A100 runtime
   - Sign in with Google

3. **Run the notebook cells in order.** Training takes ~30-60 min on A100.

4. **Download the result:** The notebook saves `hunch.fmadapter` back to Google Drive.

### Option B: Cloud GPU via SSH

For Lambda Labs, GCP, AWS, or any machine with a CUDA GPU:

```bash
# Upload training directory to the machine
rsync -avz --progress training/ user@gpu-machine:~/training/

# SSH in and run
ssh user@gpu-machine
cd training
bash train_cloud.sh
```

The script installs dependencies, generates data, trains, evaluates, and exports. Download `exports/hunch.fmadapter` when done.

### Option C: Mac with 32GB+ RAM

Works via MPS (Metal Performance Shaders) but slower than CUDA. 24GB Macs will OOM.

```bash
cd training/adapter_training_toolkit_v26_0_0
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Train with f16 precision and activation checkpointing to save memory
python3 -m examples.train_adapter \
  --train-data ../train.jsonl \
  --eval-data ../eval.jsonl \
  --epochs 5 \
  --learning-rate 1e-3 \
  --batch-size 2 \
  --precision f16 \
  --activation-checkpointing \
  --checkpoint-dir ../checkpoints/
```

## Evaluation

After training, compare base vs adapted:

```bash
cd adapter_training_toolkit_v26_0_0

# Base model (no adapter)
python3 -m examples.generate --prompt "find files changed in the last hour" --precision f16

# With adapter
python3 -m examples.generate \
  --prompt "find files changed in the last hour" \
  --checkpoint ../checkpoints/adapter-final.pt \
  --precision f16
```

## Export

```bash
python3 -m export.export_fmadapter \
  --adapter-name hunch \
  --checkpoint ../checkpoints/adapter-final.pt \
  --output-dir ../exports/
```

Output: `exports/hunch.fmadapter` (~160MB)

**Do not modify the export code** — the `.fmadapter` format must match exactly for on-device compatibility.

## Loading in Swift

```swift
// Local testing (no entitlement needed)
let localURL = URL(filePath: "/path/to/hunch.fmadapter")
let adapter = try SystemLanguageModel.Adapter(fileURL: localURL)
let model = SystemLanguageModel(adapter: adapter)
let session = LanguageModelSession(model: model)
let response = try await session.respond(to: "find files changed in the last hour")
print(response.content)
```

## Dataset

~21k training examples from:

| Source | Entries | Description |
|--------|---------|-------------|
| tldr-common | ~18k | Cross-platform shell commands |
| tldr-osx | ~950 | macOS-specific commands |
| override | ~130 | Curated corrections and macOS mappings |

After dedup and benchmark exclusion: ~19k train / ~3k eval.

## QLoRA: Training on 24GB Macs

Standard LoRA needs ~24GB+ because the full base model (12GB in fp32) must fit in memory for the forward pass. QLoRA (Quantized LoRA) quantizes the base model to 4-bit before training, reducing memory to ~3GB for weights + overhead for activations and optimizer.

QLoRA doesn't modify Apple's `tamm` library. You add a quantization step **between** loading the model and training — a small wrapper:

```python
# Conceptual approach (write your own implementation):

# 1. Load base model normally (Apple's code)
model = load_base_model(...)              # fp32, ~12GB

# 2. Quantize frozen weights to 4-bit (your code)
model = quantize_to_4bit(model)           # ~3GB — only frozen W matrices

# 3. LoRA matrices stay in fp16 (Apple's code, unchanged)
# 4. Train as normal — gradients only flow through A, B
train(model, train_data, ...)
```

The frozen base weights (W) are quantized and never updated — they just need to run the forward pass. The LoRA matrices (A, B) stay in fp16 for training precision. This is the key insight: you only need full precision for the parameters you're actually training.

Libraries like `bitsandbytes` provide 4-bit quantization for PyTorch. The implementation is ~20-30 lines wrapping the model loading step.

If this works on a 24GB Mac, it's a big deal — anyone with an M-series Mac could train their own adapter without cloud GPUs.

## Sharing and licensing

**What can be shared (MIT / CC-BY):**
- `prepare_data.py` — training data preparation script
- `train_adapter.ipynb` — Colab notebook
- `train_cloud.sh` — CLI training script
- `train.jsonl` / `eval.jsonl` — derived from tldr (CC-BY 4.0) + overrides (MIT)
- Benchmark results, analysis, blog posts

**What cannot be shared (Apple proprietary license):**
- Apple's adapter training toolkit or model weights
- Modified versions of the `tamm` library
- The `.fmadapter` export code

Each developer needs their own Apple Developer Program membership ($99/year) to download the toolkit.

## Future work

- **QLoRA implementation**: Get training running on 24GB Macs
- **Adapter + retrieval hybrid**: Use the adapter for base knowledge, retrieval only for rare/new commands
- **Benchmark comparison**: Full 100-prompt benchmark — retrieval vs adapter vs hybrid
- **Blog post**: Document the full process for others exploring Apple's adapter training
