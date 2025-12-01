#!/bin/bash
echo "Starting vllm"

source /path/to/vllm_source/.venv/bin/activate

SERVEMODEL="/path/to/.cache/huggingface/hub/hub/\
models--meta-llama--Llama-3.1-8B-Instruct/\
snapshots/0e9e39f249a16976918f6564b8830bc894c89659/"

export VLLM_CPU_KVCACHE_SPACE=40
export VLLM_CPU_NUM_OF_RESERVED_CPU=1

uv run vllm serve $SERVEMODEL \
 --host "localhost" \
 --port 8010 \
 --tool-call-parser llama3_json \
 --enable-auto-tool-choice
# --max_model_len 16000


