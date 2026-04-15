# Training Guide

How to train a LoRA adapter for Apple's on-device 3B Foundation Model using the hunch dataset.

## Prerequisites

1. **Apple Developer Program** ($99/year) — needed to download the training toolkit
2. **Adapter training toolkit** — download from [developer.apple.com/apple-intelligence/foundation-models-adapter/](https://developer.apple.com/apple-intelligence/foundation-models-adapter/)
3. **Google account** — for Colab (free tier works for fp16 LoRA, Pro/pay-as-you-go needed for standard LoRA)

## Files

```
training/
├── train_lora.ipynb          # LoRA training notebook (needs A100)
├── train_lora_fp16.ipynb         # fp16 LoRA training notebook (works on free T4)
├── prepare_data.py           # Converts hunch bank → training JSONL
└── README.md                 # Full experiment writeup and results
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

### 2. Upload to Google Drive

Create `My Drive/hunch-training/` and upload:

```
hunch-training/
├── adapter_training_toolkit_v26_0_0/   # The extracted toolkit
├── prepare_data.py                      # From this directory
├── tldr_bank.db                         # From ../bank/
└── prompts.jsonl                        # From ../benchmark/
```

### 3. Choose your notebook

| Notebook | GPU | Cost | Time | Patches needed |
|----------|-----|------|------|----------------|
| `train_lora.ipynb` | A100 40GB | Colab Pro ($10/mo) | ~1.5 hours | None |
| `train_lora_fp16.ipynb` | T4 16GB | Free | ~2 hours | 3 patches (applied automatically) |

### 4. Open in Colab

Install the Google Colab extension in VS Code, open the notebook, select a Colab kernel with the appropriate GPU, and run the cells in order.

Alternatively, upload the notebook to [colab.research.google.com](https://colab.research.google.com) directly.

### 5. Test on-device

Download the exported `.fmadapter` from Google Drive and test with hunch:

```bash
hunch --adapter path/to/hunch.fmadapter "find files changed in the last hour"
```

## Training Data

`prepare_data.py` converts the hunch bank into training JSONL:

```bash
python3 prepare_data.py         # generates train.jsonl + eval.jsonl
python3 prepare_data.py --stats # show dataset statistics
```

Each training example:
```json
[
  {"role": "system", "content": "Output a single shell command for zsh on macOS..."},
  {"role": "user", "content": "find files changed in the last hour"},
  {"role": "assistant", "content": "find . -mmin -60"}
]
```

- ~19k training / ~3k eval examples
- Benchmark prompts excluded to avoid data leakage
- Override and tldr-osx entries appear in both splits

## fp16 LoRA Patches Explained

The fp16 LoRA notebook (`train_lora_fp16.ipynb`) applies three patches to Apple's toolkit to fit training on a T4 (16GB GPU, 12GB system RAM):

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

## Export

The export step packages the LoRA weights into a `.fmadapter` file that can be loaded on-device:

```bash
python3 -m export.export_fmadapter \
  --adapter-name hunch \
  --checkpoint ../checkpoints/adapter-final.pt \
  --output-dir ../exports/
```

Output is ~127MB. The adapter name can only contain letters, numbers, and underscores.

**Do not modify the export code** — the `.fmadapter` format must match exactly for on-device compatibility.

## Loading in Swift

```swift
let adapter = try SystemLanguageModel.Adapter(fileURL: localURL)
let model = SystemLanguageModel(adapter: adapter)
let session = LanguageModelSession(model: model)
let response = try await session.respond(to: "find files changed in the last hour")
```

No entitlement needed for local testing. Entitlement required only for App Store distribution.

## Key Training Parameters

| Parameter | LoRA (A100) | fp16 LoRA (T4) |
|-----------|-------------|------------|
| `--precision` | bf16-mixed | f16-mixed |
| `--batch-size` | 8 | 8 |
| `--learning-rate` | 1e-4 | 1e-4 |
| `--epochs` | 3 | 3 |
| `--activation-checkpointing` | yes | yes |

**Note:** lr=1e-3 diverges. Always use 1e-4.

## Troubleshooting

**OOM on T4:** Make sure all three fp16 LoRA patches are applied. Run the patch cell before training.

**loss = NaN:** The rms_norm patch didn't apply, or the pycache is stale. The notebook clears pycache automatically, but if you see NaN, restart the kernel and re-run from the patch cell.

**Return code -9:** The OS killed the process for memory. On T4, this means system RAM (12GB) is full. Make sure mmap is patched (check for `mmap=True` in utils.py).

**Adapter name error:** Use only letters, numbers, and underscores. No hyphens.

**coremltools warnings:** Ignore them. The export works despite the warnings.
