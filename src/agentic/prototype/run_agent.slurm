#!/bin/sh -l  
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --time=00:05:00
#SBATCH --job-name agent
#SBATCH --mail-type=ALL

module load modtree/gpu
module load anaconda/2025.06-py313
#module load cuda/12.0.1

#vllm serve "google/gemma-3-4b-it"

export HF_HOME="/anvil/scratch/x-mason/.cache/huggingface/hub/models"
export HF_HUB_OFFLINE=1

#export VLLM_LOGGING_LEVEL=DEBUG

echo "Starting vllm"
#SERVEMODEL="/anvil/scratch/x-mason/.cache/huggingface/hub/models/hub/models--mistralai--Mistral-7B-Instruct-v0.3/snapshots/0d4b76e1efeb5eb6f6b5e757c79870472e04bd3a/"
SERVEMODEL="/anvil/scratch/x-mason/.cache/huggingface/hub/models/hub/models--meta-llama--Llama-3.1-8B-Instruct/snapshots/0e9e39f249a16976918f6564b8830bc894c89659/"
#SERVEMODEL="/anvil/scratch/x-mason/.cache/huggingface/hub/models/hub/models--google--gemma-3-4b-it/snapshots/093f9f388b31de276ce2de164bdc2081324b9767/" 
# --dtype bfloat16 \ # needed for gemma-3-4b-it

uv run vllm serve $SERVEMODEL \
 --host "localhost" \
 --port 8010 &
# --tool-call-parser "mistral" \ # mistral tool use
# --enable-auto-tool-choice \ # mistral tool use

sleep 150

#echo "Starting job"
uv run main.py

#curl http://localhost:8010/v1/completions \
#  -H "Content-Type: application/json" \
#  -d '{
#    "model": "/anvil/scratch/x-mason/.cache/huggingface/hub/models/hub/models--meta-llama--Llama-3.1-8B-Instruct/snapshots/0e9e39f249a16976918f6564b8830bc894c89659/",
#    "prompt": "The capital of France is",
#    "max_tokens": 50,
#    "temperature": 0.7
#}'
