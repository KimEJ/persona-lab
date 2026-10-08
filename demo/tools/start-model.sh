#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
model_file=models/Qwen3-0.6B-Q8_0.gguf
runtime_file=tools/llama/llama-b11429/llama-server
if [ ! -f "$model_file" ] || [ ! -f "$runtime_file" ]; then
  printf '%s\n' 'Local model/runtime files are missing. See docs/MODEL.md.' >&2
  exit 1
fi
exec "$runtime_file" --model "$model_file" --alias qwen3-0.6b-q8_0 --host 127.0.0.1 --port 8081 --ctx-size 4096 --threads 4 --n-gpu-layers 0 --jinja --no-webui --cors-origins http://127.0.0.1:8787
