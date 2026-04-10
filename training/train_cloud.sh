#!/bin/bash
# Train a LoRA adapter on a cloud GPU.
#
# Prerequisites:
#   - GPU machine with CUDA (A10G, A100, etc.)
#   - Python 3.11+
#   - Upload this entire training/ directory to the machine
#
# Usage:
#   # On the cloud machine:
#   cd training
#   bash train_cloud.sh
#
# The script will:
#   1. Install dependencies
#   2. Generate training data from the bank
#   3. Train the adapter (~30-60 min on A10G)
#   4. Export .fmadapter
#   5. Evaluate on sample prompts

set -euo pipefail

TOOLKIT_DIR="adapter_training_toolkit_v26_0_0"
CHECKPOINT_DIR="checkpoints"
EXPORT_DIR="exports"

echo "=== Setting up environment ==="
cd "$TOOLKIT_DIR"
pip install -r requirements.txt
cd ..

echo "=== Generating training data ==="
python3 prepare_data.py

echo "=== Training adapter ==="
echo "This may take 30-60 minutes on an A10G/A100..."
cd "$TOOLKIT_DIR"
python3 -m examples.train_adapter \
  --train-data ../train.jsonl \
  --eval-data ../eval.jsonl \
  --epochs 5 \
  --learning-rate 1e-3 \
  --batch-size 4 \
  --precision f16 \
  --activation-checkpointing \
  --checkpoint-dir "../$CHECKPOINT_DIR/"

echo "=== Training draft model (for faster inference) ==="
python3 -m examples.train_draft_model \
  --checkpoint "../$CHECKPOINT_DIR/adapter-final.pt" \
  --train-data ../train.jsonl \
  --eval-data ../eval.jsonl \
  --epochs 5 \
  --learning-rate 1e-3 \
  --batch-size 4 \
  --precision f16 \
  --checkpoint-dir "../$CHECKPOINT_DIR/"

echo "=== Evaluating ==="
PROMPTS=(
  "find files changed in the last hour"
  "show disk usage"
  "generate a random password"
  "kill a process by name"
  "show http headers of a url"
  "record terminal session"
  "find files larger than 100mb"
  "convert image to different format"
  "show all listening ports"
  "find files modified in the last 7 days"
)

for prompt in "${PROMPTS[@]}"; do
  echo -n "Q: $prompt → "
  python3 -m examples.generate \
    --prompt "$prompt" \
    --checkpoint "../$CHECKPOINT_DIR/adapter-final.pt" \
    --max-tokens 50 \
    --precision f16 2>/dev/null | tail -1
done

echo ""
echo "=== Exporting .fmadapter ==="
python3 -m export.export_fmadapter \
  --adapter-name hunch \
  --checkpoint "../$CHECKPOINT_DIR/adapter-final.pt" \
  --draft-checkpoint "../$CHECKPOINT_DIR/draft-model-final.pt" \
  --output-dir "../$EXPORT_DIR/"

cd ..
echo ""
echo "=== Done ==="
echo "Adapter: $EXPORT_DIR/hunch.fmadapter"
echo "Size: $(du -sh $EXPORT_DIR/hunch.fmadapter 2>/dev/null | cut -f1)"
echo ""
echo "Download hunch.fmadapter and test locally on macOS 26."
