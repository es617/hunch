#!/usr/bin/env python3
"""
Benchmark QLoRA training on MPS: Metal kernels vs CPU fallback.

Measures load time, training throughput, and memory usage.
Run with both bitsandbytes versions to compare:

  # With Metal kernels (bitsandbytes from main)
  python3 bench_mps.py --epochs 3 --label metal

  # Without Metal kernels (bitsandbytes 0.49.2)
  python3 bench_mps.py --epochs 3 --label cpu-fallback

  # Longer sequences (override + tldr-osx)
  python3 bench_mps.py --epochs 3 --sources override,tldr-osx --label metal-long

Results are appended to bench_mps_results.jsonl for comparison.
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
TRAINING_DIR = Path(__file__).parent

import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def mem_stats():
    ram = psutil.Process().memory_info().rss / 1024**3
    gpu = 0
    if torch.backends.mps.is_available():
        gpu = torch.mps.current_allocated_memory() / 1024**3
    elif torch.cuda.is_available():
        gpu = torch.cuda.memory_allocated() / 1024**3
    cpu_pct = psutil.cpu_percent(interval=None)
    return {"ram_gb": round(ram, 2), "gpu_gb": round(gpu, 2), "cpu_pct": cpu_pct}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--sources", default="override")
    parser.add_argument("--label", required=True, help="Label for this run (e.g. 'metal', 'cpu-fallback')")
    parser.add_argument("--repeat", type=int, default=1, help="Number of full runs to average")
    args = parser.parse_args()

    # Check bitsandbytes version
    import bitsandbytes as bnb
    bnb_version = getattr(bnb, '__version__', 'unknown')
    print(f"bitsandbytes: {bnb_version}")
    print(f"Label: {args.label}")
    print(f"Sources: {args.sources}")
    print(f"Epochs: {args.epochs}, Batch: {args.batch_size}, Repeats: {args.repeat}")
    print()

    # Prepare data if needed
    train_path = TRAINING_DIR / "train.jsonl"
    if not train_path.exists():
        os.system(f"cd {TRAINING_DIR} && python3 prepare_data.py --sources {args.sources}")
    else:
        # Regenerate with correct sources
        os.system(f"cd {TRAINING_DIR} && python3 prepare_data.py --sources {args.sources}")

    # Import training components
    from train_qlora_full import (
        CommandDataset, collate_fn, load_model_qlora, patch_rms_norm,
        train_epoch, evaluate
    )
    from tamm.tokenizers.afm import AFMTokenizer

    results = []

    for run in range(1, args.repeat + 1):
        print(f"{'='*60}")
        print(f"  Run {run}/{args.repeat}")
        print(f"{'='*60}")

        # Start CPU monitoring
        psutil.cpu_percent(interval=None)  # reset

        # Phase 1: Load & quantize
        t_load_start = time.time()
        patch_rms_norm()
        device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cuda")
        model = load_model_qlora(device)
        t_load = time.time() - t_load_start
        mem_after_load = mem_stats()
        print(f"  Load+quantize: {t_load:.1f}s | {mem_after_load}")

        # Phase 2: Setup data
        tokenizer = AFMTokenizer(str(Path(TOOLKIT_DIR) / "assets" / "tokenizer.model"))
        train_dataset = CommandDataset(str(train_path), tokenizer)
        eval_dataset = CommandDataset(str(TRAINING_DIR / "eval.jsonl"), tokenizer)
        train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, collate_fn=collate_fn)
        eval_loader = DataLoader(eval_dataset, batch_size=args.batch_size, collate_fn=collate_fn)
        print(f"  Data: {len(train_dataset)} train, {len(eval_dataset)} eval, {len(train_loader)} batches/epoch")

        # Phase 3: Train
        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad],
            lr=1e-4, weight_decay=0.01
        )
        scaler = torch.amp.GradScaler(device=str(device)) if (torch.cuda.is_available() or torch.backends.mps.is_available()) else None

        epoch_times = []
        epoch_losses = []
        mem_during_training = []

        for epoch in range(args.epochs):
            t_epoch_start = time.time()
            train_loss = train_epoch(model, train_loader, optimizer, device, epoch, scaler)
            t_epoch = time.time() - t_epoch_start
            epoch_times.append(t_epoch)
            epoch_losses.append(train_loss)
            mem = mem_stats()
            mem_during_training.append(mem)

            batches = len(train_loader)
            it_s = batches / t_epoch
            s_it = t_epoch / batches
            print(f"  Epoch {epoch+1}: {t_epoch:.1f}s ({s_it:.2f}s/it, {it_s:.2f}it/s) loss={train_loss:.4f} | {mem}")

        # Phase 4: Eval
        t_eval_start = time.time()
        eval_loss = evaluate(model, eval_loader, device)
        t_eval = time.time() - t_eval_start
        print(f"  Eval: {t_eval:.1f}s loss={eval_loss:.4f}")

        total_time = t_load + sum(epoch_times) + t_eval
        avg_epoch = sum(epoch_times) / len(epoch_times)
        avg_it_s = len(train_loader) / avg_epoch
        avg_s_it = avg_epoch / len(train_loader)

        run_result = {
            "label": args.label,
            "run": run,
            "bnb_version": bnb_version,
            "sources": args.sources,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "train_examples": len(train_dataset),
            "batches_per_epoch": len(train_loader),
            "load_time_s": round(t_load, 1),
            "avg_epoch_s": round(avg_epoch, 1),
            "avg_s_per_it": round(avg_s_it, 2),
            "avg_it_per_s": round(avg_it_s, 2),
            "total_time_s": round(total_time, 1),
            "final_train_loss": round(epoch_losses[-1], 4),
            "eval_loss": round(eval_loss, 4),
            "mem_after_load": mem_after_load,
            "mem_training": mem_during_training[-1],
            "epoch_times": [round(t, 1) for t in epoch_times],
        }
        results.append(run_result)

        print(f"\n  Summary: {avg_s_it:.2f}s/it ({avg_it_s:.2f}it/s), total {total_time:.0f}s")
        print()

        # Cleanup for next run
        del model, optimizer, scaler, train_loader, eval_loader
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

    # Save results
    results_file = TRAINING_DIR / "bench_mps_results.jsonl"
    with open(results_file, "a") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"Results appended to {results_file}")

    # Print comparison-ready summary
    if len(results) > 1:
        avg_it = sum(r["avg_s_per_it"] for r in results) / len(results)
        avg_total = sum(r["total_time_s"] for r in results) / len(results)
        print(f"\nAverage across {len(results)} runs: {avg_it:.2f}s/it, {avg_total:.0f}s total")


if __name__ == "__main__":
    main()
