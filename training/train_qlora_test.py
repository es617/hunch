#!/usr/bin/env python3
"""
True QLoRA training test: 4-bit NF4 base model + fp32 LoRA adapters.

Uses bitsandbytes for NF4 quantization. Tests loading + one training step.

Usage:
  pip install bitsandbytes
  python3 train_qlora_test.py

This script:
  1. Loads the base model
  2. Replaces frozen Linear layers with 4-bit NF4 equivalents
  3. Runs one training batch to verify it works
  4. Reports memory usage at each step
"""

import sys
import os
import gc
import time
import psutil

TOOLKIT_DIR = os.path.join(os.path.dirname(__file__), "adapter_training_toolkit_v26_0_0")
sys.path.insert(0, TOOLKIT_DIR)

import torch
import tamm.utils.json
from pathlib import Path

ASSETS = Path(TOOLKIT_DIR) / "assets"


def mem():
    return psutil.Process().memory_info().rss / 1024**3

def gpu_mem():
    if torch.cuda.is_available():
        return torch.cuda.memory_allocated() / 1024**3
    elif torch.backends.mps.is_available():
        return torch.mps.current_allocated_memory() / 1024**3
    return 0

def get_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def quantize_linear_to_4bit(model):
    """Replace frozen nn.Linear layers with bitsandbytes 4-bit Linear."""
    try:
        import bitsandbytes as bnb
    except ImportError:
        print("ERROR: pip install bitsandbytes")
        sys.exit(1)

    quantized = 0
    skipped = 0

    # Collect replacements (can't modify during iteration)
    replacements = []
    for name, module in model.named_modules():
        if not isinstance(module, torch.nn.Linear):
            continue
        if "adapter" in name:
            skipped += 1
            continue
        if any(p.requires_grad for p in module.parameters()):
            skipped += 1
            continue
        replacements.append((name, module))

    # Apply replacements
    for name, module in replacements:
        # Create 4-bit linear
        new_module = bnb.nn.Linear4bit(
            module.in_features,
            module.out_features,
            bias=module.bias is not None,
            compute_dtype=torch.float16,
            quant_type="nf4",
        )

        # Quantize weights
        new_module.weight = bnb.nn.Params4bit(
            module.weight.data,
            requires_grad=False,
            quant_type="nf4",
            compress_statistics=True,
        )
        if module.bias is not None:
            new_module.bias = module.bias

        # Replace in parent module
        parts = name.rsplit(".", 1)
        if len(parts) == 2:
            parent_name, child_name = parts
            parent = dict(model.named_modules())[parent_name]
            setattr(parent, child_name, new_module)
        else:
            setattr(model, name, new_module)

        quantized += 1

    # Free memory
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(f"QLoRA: quantized {quantized} layers to NF4, skipped {skipped}")
    return model


def main():
    device = get_device()
    print(f"Device: {device}")
    print(f"System RAM: {psutil.virtual_memory().total / 1024**3:.0f}GB")
    print(f"Before: RAM={mem():.1f}GB, GPU={gpu_mem():.1f}GB")

    # Step 1: Load model config
    with open(ASSETS / "base-model-config.json") as f:
        config = tamm.utils.json.load(f)

    # Step 2: Create model on CPU
    print("\n--- Creating model ---")
    model = config.create_model()
    print(f"After create_model: RAM={mem():.1f}GB, GPU={gpu_mem():.1f}GB")

    # Step 3: Load weights via mmap
    print("\n--- Loading weights (mmap) ---")
    sd = torch.load(str(ASSETS / "base-model.pt"), map_location="cpu", mmap=True, weights_only=False)
    model.load_state_dict(sd, strict=True)
    del sd; gc.collect()
    print(f"After load+del: RAM={mem():.1f}GB, GPU={gpu_mem():.1f}GB")

    # Step 4: Freeze non-adapter params
    for name, param in model.named_parameters():
        param.requires_grad = "adapter" in name

    trainable_before = sum(p.numel() for p in model.parameters() if p.requires_grad)
    frozen_before = sum(p.numel() for p in model.parameters() if not p.requires_grad)
    print(f"Trainable: {trainable_before/1e6:.0f}M, Frozen: {frozen_before/1e6:.0f}M")

    # Step 5: Quantize frozen layers to 4-bit NF4
    print("\n--- Quantizing to NF4 ---")
    model = quantize_linear_to_4bit(model)
    gc.collect()
    print(f"After quantize: RAM={mem():.1f}GB, GPU={gpu_mem():.1f}GB")

    # Step 6: Move to device
    print(f"\n--- Moving to {device} ---")
    model = model.to(device)
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print(f"After to({device}): RAM={mem():.1f}GB, GPU={gpu_mem():.1f}GB")

    # Step 7: Verify trainable params are fp32
    for name, param in model.named_parameters():
        if param.requires_grad and "adapter" in name:
            if param.dtype != torch.float32:
                param.data = param.data.float()

    trainable_after = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Trainable params: {trainable_after/1e6:.0f}M")

    # Step 8: Test one forward + backward pass
    print("\n--- Test forward/backward ---")
    try:
        tokenizer_path = ASSETS / "tokenizer.model"
        from tamm.tokenizers.afm import AFMTokenizer
        tokenizer = AFMTokenizer(str(tokenizer_path))

        # Create a simple input
        text = "Output a single shell command for zsh on macOS.\nfind files changed in the last hour"
        tokens = tokenizer.encode(text)
        input_ids = torch.tensor([tokens[:50]], device=device)
        labels = input_ids.clone()

        # Forward pass
        output = model(input_ids)
        if hasattr(output, 'logits'):
            logits = output.logits
        else:
            logits = output

        # Compute loss
        loss_fn = torch.nn.CrossEntropyLoss()
        shift_logits = logits[:, :-1, :].contiguous()
        shift_labels = labels[:, 1:].contiguous()
        loss = loss_fn(shift_logits.view(-1, shift_logits.size(-1)), shift_labels.view(-1))
        print(f"Loss: {loss.item():.4f}")

        # Backward pass
        loss.backward()
        print(f"After backward: RAM={mem():.1f}GB, GPU={gpu_mem():.1f}GB")

        # Check gradients exist on adapter params
        grad_count = sum(1 for p in model.parameters() if p.grad is not None)
        print(f"Params with gradients: {grad_count}")

        print("\nSUCCESS: QLoRA forward + backward works!")

    except Exception as e:
        print(f"\nFailed at forward/backward: {e}")
        import traceback
        traceback.print_exc()

    print(f"\nFinal: RAM={mem():.1f}GB, GPU={gpu_mem():.1f}GB")


if __name__ == "__main__":
    main()
