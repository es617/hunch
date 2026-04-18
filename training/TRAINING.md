# Training Guide

How to train a LoRA adapter for Apple's on-device 3B Foundation Model using the hunch dataset.

## Prerequisites

1. **Apple Developer Program** ($99/year) — needed to download the training toolkit
2. **Adapter training toolkit** — download from [developer.apple.com/apple-intelligence/foundation-models-adapter/](https://developer.apple.com/apple-intelligence/foundation-models-adapter/)
3. **Google account** — for Colab (free tier works for QLoRA and fp16 LoRA)

## Files

```
training/
├── train_lora.ipynb              # LoRA training notebook (needs A100)
├── train_lora_fp16.ipynb         # fp16 LoRA training notebook (works on free T4)
├── train_qlora.ipynb             # QLoRA training notebook (works on free T4, recommended)
├── train_qlora_full.py           # QLoRA training script (T4 or Mac)
├── prepare_data.py               # Converts hunch bank → training JSONL
└── README.md                     # Full experiment writeup and results
```

## Quick Start

### 1. Download the toolkit

Download from developer.apple.com, extract into this directory:

```
training/adapter_training_toolkit_v26_0_0/
├── assets/          # Base model weights (12GB)
├── examples/        # Training scripts
├── export/          # .fmadapter export
└── requirements.txt
```

### 2. Choose your path

| Path | GPU | Cost | VRAM | Time (overrides) | Time (full bank) |
|------|-----|------|------|------------------|------------------|
| **QLoRA on Mac** | Apple Silicon | **Free, local** | **3.4GB** | **~34 min** | ~hours |
| QLoRA on Colab | T4 16GB | Free | ~5GB | ~5 min | ~1.7 hours |
| fp16 LoRA on Colab | T4 16GB | Free | ~8.5GB | ~10 min | ~2 hours |
| LoRA on Colab | A100 40GB | Colab Pro ($10/mo) | ~15GB | ~5 min | ~2.5 hours |

**QLoRA is recommended.** Same adapter quality as full LoRA, lowest memory, fewest patches. Mac training is ~7x slower than T4 but fully local.

### Path A: Train on Mac (recommended for small datasets)

```bash
cd training/adapter_training_toolkit_v26_0_0
source venv/bin/activate

# Install native Metal kernel support for bitsandbytes
pip install kernels
pip install --force-reinstall git+https://github.com/bitsandbytes-foundation/bitsandbytes.git

# Prepare data and train
cd ..
python3 prepare_data.py --sources override
python3 train_qlora_full.py --epochs 20 --batch-size 8

# Export — bitsandbytes from main pulls in PyTorch 2.11, but coremltools 8.3.0
# ships native C extensions only for Python ≤3.13 and PyTorch ≤2.5.
# Create a separate env with compatible versions:
cd adapter_training_toolkit_v26_0_0
python3.12 -m venv export-env
source export-env/bin/activate
pip install torch==2.5.0 coremltools==8.3.0
python3 -m export.export_fmadapter \
  --adapter-name hunch_qlora \
  --checkpoint ../qlora-checkpoints/adapter-final.pt \
  --output-dir ../qlora-checkpoints/
```

Notes:
- Requires bitsandbytes from git main (pre-v0.50.0) with native MPS kernels (PR #1875)
- The `kernels` package downloads pre-compiled Metal shaders from HuggingFace Hub at runtime
- Don't use `bnb_4bit_use_double_quant=True` — not wired for MPS yet
- ~34 min for 20 epochs of 96 examples on M4, 3.4GB GPU, 0.2GB RAM. Full bank (~19k) would take hours

### Path B: Train on Colab

Upload to Google Drive:

```
My Drive/hunch-training/
├── adapter_training_toolkit_v26_0_0/   # The extracted toolkit
├── prepare_data.py                      # From this directory
├── train_qlora_full.py                  # From this directory (for QLoRA)
├── tldr_bank.db                         # From ../bank/
└── prompts.jsonl                        # From ../benchmark/
```

Choose a notebook:

| Notebook | GPU | Patches |
|----------|-----|---------|
| `train_qlora.ipynb` | T4 16GB (free) | 1 (rms_norm) |
| `train_lora_fp16.ipynb` | T4 16GB (free) | 3 (mmap, grad scaling, rms_norm) |
| `train_lora.ipynb` | A100 40GB (Pro) | None |

Open in Colab via the VS Code extension or upload directly to [colab.research.google.com](https://colab.research.google.com). Run cells in order.

### 3. Test on-device

```bash
hunch --adapter path/to/hunch.fmadapter "find files changed in the last hour"
```

## Training Data

`prepare_data.py` converts the hunch bank into training JSONL:

```bash
python3 prepare_data.py                        # full bank (~19k train / ~3k eval)
python3 prepare_data.py --sources override     # overrides only (~96 examples, recommended)
python3 prepare_data.py --sources tldr-osx     # macOS-specific tldr pages (~1k)
python3 prepare_data.py --sources override,tldr-osx  # overrides + macOS (~1.1k)
python3 prepare_data.py --stats                # show dataset statistics
```

Each training example:
```json
[
  {"role": "system", "content": "Output a single shell command for zsh on macOS..."},
  {"role": "user", "content": "find files changed in the last hour"},
  {"role": "assistant", "content": "find . -mmin -60"}
]
```

- Benchmark prompts excluded to avoid data leakage
- Override and tldr-osx entries appear in both splits

**Use `--sources override` for best results.** Adapters trained on ~96 curated overrides (~5 min on T4) significantly outperform adapters trained on the full 19k bank (~1.7 hours on T4). Quality over quantity — see README.md for benchmark results.

## How Each Approach Works

### QLoRA (recommended)

Quantizes the frozen base model to 4-bit NF4 via `bitsandbytes`, and uses `mmap=True` loading to avoid the 12GB CPU RAM spike. Only `nn.Linear` layers are quantized (attention Q/K/V/O, FFN — ~90% of params). Embeddings, norms, and other layers stay in fp16. Adapters train in fp32.

Memory breakdown:
- CPU RAM peak: **~1GB** (mmap reads weights from disk on demand)
- Base model Linear layers: ~1.5GB (NF4)
- Base model non-Linear: ~0.65GB (fp16)
- Adapters + gradients + optimizer: ~0.6GB (fp32)
- Activations: ~2-3GB
- **GPU total: ~5GB**

Only one patch needed: rms_norm dtype fix for mixed fp16/fp32/quantized tensors through norm layers.

### fp16 LoRA

Forces the base model to fp16 and uses `mmap=True` loading. Both changes are patches to Apple's toolkit — the default loads fp32 without mmap, which requires ~24GB CPU RAM and 12GB GPU. Requires three patches total.

Memory breakdown:
- CPU RAM peak: **~1GB** (mmap, vs ~24GB without)
- Base model: ~6GB (fp16, vs ~12GB fp32)
- Adapters + gradients + optimizer: ~0.6GB (fp32)
- Activations: ~2-3GB
- **GPU total: ~8.5GB**

**Patch 1 — `utils.py`: mmap + fp16 model + fp32 adapters**
- `mmap=True` on `torch.load`: reads weights from disk on demand instead of loading 12GB into RAM
- `model_config.dtype = torch.float16`: creates the model in fp16 (6GB GPU instead of 12GB)
- Casts adapter weights back to fp32: GradScaler needs fp32 gradients

**Patch 2 — `train_adapter.py`: gradient scaling for f16-mixed**
- Apple's code only enables GradScaler for a `"f16"` precision mode that isn't exposed as a CLI option
- When running with `f16-mixed` and an fp16 model, gradients overflow without scaling → loss = NaN
- Fix: enable GradScaler for `f16-mixed` too

**Patch 3 — `tamm/layers/functional.py`: rms_norm dtype fix**
- `torch.rms_norm` requires input and weight to have the same dtype
- fp16 model has fp16 weights, but mixed-precision casts input to fp32
- Fix: cast weight to match input dtype before calling rms_norm

All patches are applied automatically by the notebook. To restore originals, re-copy from the toolkit on Drive.

### Standard LoRA

Loads the base model in fp32. No patches needed but requires an A100 (40GB) — doesn't fit on a T4.

Memory breakdown:
- CPU RAM peak: **~24GB** during loading (12GB model + 12GB state dict simultaneously — no mmap)
- Base model on GPU: ~12GB (fp32)
- Adapters + gradients + optimizer: ~0.6GB (fp32)
- Activations: ~2-3GB (fp32)
- **GPU total: ~15GB**

The CPU RAM spike is why standard LoRA OOMs on a 24GB Mac and on T4 (12GB system RAM). The A100's 80GB system RAM hides this. fp16 LoRA and QLoRA avoid this with `mmap=True` loading (~1GB RAM peak instead of 24GB).

## Export

The export step packages the LoRA weights into a `.fmadapter` file that can be loaded on-device:

```bash
cd adapter_training_toolkit_v26_0_0
python3 -m export.export_fmadapter \
  --adapter-name hunch \
  --checkpoint ../checkpoints/adapter-final.pt \
  --output-dir ../exports/
```

**Note for Mac training:** The training venv has PyTorch 2.11 (from bitsandbytes main) which is too new for coremltools. Export in a separate Python 3.12 environment — see Path A in Quick Start above.

Output is ~130MB. The adapter name can only contain letters, numbers, and underscores.

**Do not modify the export code** — the `.fmadapter` format must match exactly for on-device compatibility.

The `.fmadapter` format doesn't record training precision — adapters trained via QLoRA, fp16 LoRA, or fp32 LoRA all export identically and load the same on-device.

## Loading in Swift

```swift
let adapter = try SystemLanguageModel.Adapter(fileURL: localURL)
let model = SystemLanguageModel(adapter: adapter)
let session = LanguageModelSession(model: model)
let response = try await session.respond(to: "find files changed in the last hour")
```

No entitlement needed for local testing. Entitlement required only for App Store distribution.

## Key Training Parameters

| Parameter | Override-only (recommended) | Full bank |
|-----------|---------------------------|-----------|
| `--batch-size` | 8 | 8 |
| `--learning-rate` | 1e-4 | 1e-4 |
| `--epochs` | 20 | 3 |
| `--sources` (prepare_data.py) | `override` | (default) |

These apply to all three approaches (LoRA, fp16 LoRA, QLoRA). Override-only trains on ~96 examples and needs more epochs to converge. Full bank has ~19k examples and overfits after 3.

## On-Device Accuracy

All three approaches produce comparable adapters. QLoRA is recommended — same quality, lowest cost.

| Approach | + Retrieval | Standalone | Trained on |
|---|---|---|---|
| LoRA (A100) | ~85% | ~72.5% | T4/A100 |
| QLoRA (T4) | ~83% | ~73% | T4 free |
| QLoRA (Mac) | ~78.5% | ~72% | Local |
| Retrieval only | ~79% | — | — |
| Bare model | — | ~41% | — |

Full benchmark details and analysis in README.md.

## Known Issues

### Adapter disk space leak

`TGOnDeviceInferenceProviderService` caches a full copy of the adapter (~160MB) in a SIP-protected directory on every process invocation. The copies are never cleaned up. Running benchmarks (hundreds of adapter calls) can consume tens of GB invisibly.

**Workaround:** Use `hunch --batch` to run multiple prompts in a single process (1 cached copy instead of 1 per prompt). To reclaim space, boot Recovery Mode and delete `/Volumes/Data/private/var/db/AppleIntelligencePlatform/AppModelAssets/*`.

See `adapter-disk-leak-findings.md` for the full investigation.

## Troubleshooting

**OOM on T4 (QLoRA):** Make sure `bitsandbytes` is installed and the model is being quantized. Check for "Quantized 280 layers to NF4" in the output.

**OOM on T4 (fp16 LoRA):** Make sure all three patches are applied. Run the patch cell before training.

**loss = NaN:** The rms_norm patch didn't apply, or the pycache is stale. The notebook clears pycache automatically, but if you see NaN, restart the kernel and re-run from the patch cell.

**Return code -9:** The OS killed the process for memory. On T4, this means system RAM (12GB) is full. Make sure mmap is patched (check for `mmap=True` in utils.py).

**Adapter name error:** Use only letters, numbers, and underscores. No hyphens.

**coremltools warnings:** Ignore them. The export works despite the warnings.
