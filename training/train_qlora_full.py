#!/usr/bin/env python3
"""
True QLoRA training: 4-bit NF4 base model + fp32 LoRA adapters.

Uses bitsandbytes for NF4 quantization. Trains on hunch dataset.
Works on 24GB Mac (MPS) and Colab T4 (CUDA). ~5GB GPU memory.

Usage:
  python3 train_qlora_full.py                          # train 3 epochs
  python3 train_qlora_full.py --epochs 1 --batch-size 4  # quick test
  python3 train_qlora_full.py --eval-only --checkpoint checkpoints/adapter-final.pt

Requirements:
  pip install bitsandbytes psutil
"""

import sys
import os
import gc
import json
import time
import argparse
import psutil
from pathlib import Path

TOOLKIT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adapter_training_toolkit_v26_0_0")
sys.path.insert(0, TOOLKIT_DIR)

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import tamm.utils.json
from tamm.tokenizers.afm import AFMTokenizer

ASSETS = Path(TOOLKIT_DIR) / "assets"
TRAINING_DIR = Path(__file__).parent


def patch_rms_norm():
    """Patch tamm's rms_norm to handle dtype mismatch (fp16 model + fp32 cast)."""
    import glob
    patterns = [
        os.path.join(TOOLKIT_DIR, "venv", "lib", "*", "site-packages", "tamm", "layers", "functional.py"),
        os.path.join(sys.prefix, "lib", "*", "dist-packages", "tamm", "layers", "functional.py"),
    ]
    for pattern in patterns:
        for path in glob.glob(pattern):
            code = open(path).read()
            if "weight.to(tensor.dtype)" not in code:
                old = "        tensor = _torch_compatibility.rms_norm(\n            tensor, normalized_shape=normalized_shape, weight=weight, eps=eps\n        )"
                new = "        if weight is not None and weight.dtype != tensor.dtype:\n            weight = weight.to(tensor.dtype)\n        tensor = _torch_compatibility.rms_norm(\n            tensor, normalized_shape=normalized_shape, weight=weight, eps=eps\n        )"
                code = code.replace(old, new)
                open(path, "w").write(code)
                # Clear pycache
                cache_dir = os.path.join(os.path.dirname(path), "__pycache__")
                if os.path.exists(cache_dir):
                    import shutil; shutil.rmtree(cache_dir)
                print(f"Patched rms_norm: {path}")
            else:
                print(f"rms_norm already patched: {path}")


def get_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def mem_str():
    ram = psutil.Process().memory_info().rss / 1024**3
    if torch.cuda.is_available():
        gpu = torch.cuda.memory_allocated() / 1024**3
    elif torch.backends.mps.is_available():
        gpu = torch.mps.current_allocated_memory() / 1024**3
    else:
        gpu = 0
    return f"RAM={ram:.1f}GB GPU={gpu:.1f}GB"


def load_model_qlora(device):
    """Load base model with NF4 quantization."""
    import bitsandbytes as bnb

    # Load config and create model in fp16 (6GB instead of 12GB)
    with open(ASSETS / "base-model-config.json") as f:
        config = tamm.utils.json.load(f)
    config.dtype = torch.float16
    model = config.create_model()

    # Load weights via mmap (minimal RAM)
    sd = torch.load(str(ASSETS / "base-model.pt"), map_location="cpu", mmap=True, weights_only=False)
    model.load_state_dict(sd, strict=True)
    del sd; gc.collect()

    # Freeze non-adapter params
    for name, param in model.named_parameters():
        param.requires_grad = "adapter" in name

    # Quantize frozen Linear layers to NF4
    replacements = []
    for name, module in model.named_modules():
        if not isinstance(module, nn.Linear):
            continue
        if "adapter" in name or any(p.requires_grad for p in module.parameters()):
            continue
        replacements.append((name, module))

    for name, module in replacements:
        new_module = bnb.nn.Linear4bit(
            module.in_features, module.out_features,
            bias=module.bias is not None,
            compute_dtype=torch.float16,
            quant_type="nf4",
        )
        new_module.weight = bnb.nn.Params4bit(
            module.weight.data, requires_grad=False,
            quant_type="nf4", compress_statistics=True,
        )
        if module.bias is not None:
            new_module.bias = module.bias

        parts = name.rsplit(".", 1)
        if len(parts) == 2:
            parent = dict(model.named_modules())[parts[0]]
            setattr(parent, parts[1], new_module)
        else:
            setattr(model, name, new_module)

    gc.collect()
    print(f"Quantized {len(replacements)} layers to NF4")

    # Move to device
    model = model.to(device)

    # Ensure adapter params are fp32
    for name, param in model.named_parameters():
        if param.requires_grad and param.dtype != torch.float32:
            param.data = param.data.float()

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Trainable: {trainable/1e6:.0f}M params | {mem_str()}")
    return model


def load_model_with_checkpoint(device, checkpoint_path):
    """Load QLoRA model and restore adapter weights from checkpoint."""
    model = load_model_qlora(device)
    sd = torch.load(checkpoint_path, map_location=device, weights_only=False)
    # Only load adapter weights
    adapter_sd = {k: v for k, v in sd.items() if "adapter" in k}
    model.load_state_dict(adapter_sd, strict=False)
    print(f"Loaded {len(adapter_sd)} adapter weights from {checkpoint_path}")
    return model


class CommandDataset(Dataset):
    """Load JSONL training data."""
    def __init__(self, path, tokenizer, max_length=512):
        self.examples = []
        self.tokenizer = tokenizer
        self.max_length = max_length

        with open(path) as f:
            for line in f:
                messages = json.loads(line)
                # Format: system + user + assistant
                text = ""
                for msg in messages:
                    if msg["role"] == "system":
                        text += f"system\n{msg['content']}<turn_end> "
                    elif msg["role"] == "user":
                        text += f"user\n {msg['content']}<turn_end> "
                    elif msg["role"] == "assistant":
                        text += f"assistant\n {msg['content']}<turn_end>"
                self.examples.append(text)

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        tokens = self.tokenizer.encode(self.examples[idx])
        tokens = tokens[:self.max_length]
        return torch.tensor(tokens, dtype=torch.long)


def collate_fn(batch):
    """Pad sequences to same length."""
    max_len = max(len(x) for x in batch)
    padded = torch.zeros(len(batch), max_len, dtype=torch.long)
    for i, x in enumerate(batch):
        padded[i, :len(x)] = x
    return padded


def train_epoch(model, dataloader, optimizer, device, epoch, scaler=None):
    model.train()
    total_loss = 0
    n_batches = 0
    start = time.time()

    for i, batch in enumerate(dataloader):
        input_ids = batch.to(device)
        labels = input_ids.clone()

        # Forward
        if scaler:
            with torch.amp.autocast(device_type=str(device), dtype=torch.float16):
                output = model(input_ids)
                logits = output.logits if hasattr(output, 'logits') else output
                loss = nn.CrossEntropyLoss()(
                    logits[:, :-1, :].contiguous().view(-1, logits.size(-1)),
                    labels[:, 1:].contiguous().view(-1)
                )
        else:
            output = model(input_ids)
            logits = output.logits if hasattr(output, 'logits') else output
            loss = nn.CrossEntropyLoss()(
                logits[:, :-1, :].contiguous().view(-1, logits.size(-1)),
                labels[:, 1:].contiguous().view(-1)
            )

        # Backward
        optimizer.zero_grad()
        if scaler:
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        total_loss += loss.item()
        n_batches += 1

        if (i + 1) % 100 == 0:
            avg = total_loss / n_batches
            elapsed = time.time() - start
            it_s = (i + 1) / elapsed
            remaining = (len(dataloader) - i - 1) / it_s / 60
            print(f"  [{i+1}/{len(dataloader)}] loss={avg:.3f} {it_s:.1f}it/s ~{remaining:.0f}min left | {mem_str()}")

    return total_loss / max(n_batches, 1)


def evaluate(model, dataloader, device):
    model.eval()
    total_loss = 0
    n_batches = 0

    with torch.no_grad():
        for batch in dataloader:
            input_ids = batch.to(device)
            labels = input_ids.clone()
            with torch.amp.autocast(device_type=str(device), dtype=torch.float16):
                output = model(input_ids)
                logits = output.logits if hasattr(output, 'logits') else output
                loss = nn.CrossEntropyLoss()(
                    logits[:, :-1, :].contiguous().view(-1, logits.size(-1)),
                    labels[:, 1:].contiguous().view(-1)
                )
            total_loss += loss.item()
            n_batches += 1

    return total_loss / max(n_batches, 1)


def save_adapter_checkpoint(model, path, optimizer=None, epoch=None):
    """Save adapter weights and optionally optimizer state for resume."""
    checkpoint = {
        "adapter_weights": {k: v.cpu() for k, v in model.state_dict().items() if "adapter" in k},
    }
    if optimizer:
        checkpoint["optimizer"] = optimizer.state_dict()
    if epoch is not None:
        checkpoint["epoch"] = epoch
    torch.save(checkpoint, path)
    size_mb = os.path.getsize(path) / 1024**2
    print(f"Saved checkpoint ({size_mb:.0f}MB) to {path}")


def main():
    parser = argparse.ArgumentParser(description="QLoRA training for hunch")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--train-data", default=str(TRAINING_DIR / "train.jsonl"))
    parser.add_argument("--eval-data", default=str(TRAINING_DIR / "eval.jsonl"))
    parser.add_argument("--checkpoint-dir", default=str(TRAINING_DIR / "qlora-checkpoints"))
    parser.add_argument("--checkpoint", type=str, help="Resume from checkpoint")
    parser.add_argument("--eval-only", action="store_true")
    args = parser.parse_args()

    device = get_device()
    print(f"Device: {device} | {mem_str()}")

    # Patch rms_norm for fp16 compatibility
    patch_rms_norm()

    # Generate training data if needed
    if not os.path.exists(args.train_data):
        print("Generating training data...")
        os.system(f"cd {TRAINING_DIR} && python3 prepare_data.py")

    # Load tokenizer
    tokenizer = AFMTokenizer(str(ASSETS / "tokenizer.model"))

    # Load model
    if args.checkpoint:
        model = load_model_with_checkpoint(device, args.checkpoint)
    else:
        model = load_model_qlora(device)

    if args.eval_only:
        eval_dataset = CommandDataset(args.eval_data, tokenizer)
        eval_loader = DataLoader(eval_dataset, batch_size=args.batch_size, collate_fn=collate_fn)
        eval_loss = evaluate(model, eval_loader, device)
        print(f"Eval loss: {eval_loss:.4f}")
        return

    # Data
    train_dataset = CommandDataset(args.train_data, tokenizer)
    eval_dataset = CommandDataset(args.eval_data, tokenizer)
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, collate_fn=collate_fn)
    eval_loader = DataLoader(eval_dataset, batch_size=args.batch_size, collate_fn=collate_fn)

    print(f"Train: {len(train_dataset)} examples, {len(train_loader)} batches")
    print(f"Eval: {len(eval_dataset)} examples")

    # Optimizer
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.learning_rate,
        weight_decay=0.01
    )

    # Gradient scaler for mixed precision on CUDA
    scaler = torch.amp.GradScaler() if torch.cuda.is_available() else None

    # Checkpoint dir
    os.makedirs(args.checkpoint_dir, exist_ok=True)

    # Training loop
    print(f"\n{'='*60}")
    print(f"Training: {args.epochs} epochs, batch {args.batch_size}, lr {args.learning_rate}")
    print(f"{'='*60}")

    for epoch in range(args.epochs):
        print(f"\nEpoch {epoch+1}/{args.epochs}")
        train_loss = train_epoch(model, train_loader, optimizer, device, epoch, scaler)

        # Save checkpoint before eval (in case eval crashes)
        ckpt_path = os.path.join(args.checkpoint_dir, f"adapter-epoch{epoch+1}.pt")
        save_adapter_checkpoint(model, ckpt_path)

        eval_loss = evaluate(model, eval_loader, device)
        print(f"  Train loss: {train_loss:.4f} | Eval loss: {eval_loss:.4f} | {mem_str()}")

    # Save final
    final_path = os.path.join(args.checkpoint_dir, "adapter-final.pt")
    save_adapter_checkpoint(model, final_path)
    print(f"\nDone! Export with:")
    print(f"  python3 -m export.export_fmadapter --adapter-name hunch_qlora --checkpoint {final_path} --output-dir {args.checkpoint_dir}/")


if __name__ == "__main__":
    main()
