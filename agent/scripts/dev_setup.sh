#!/usr/bin/env bash
# Build the IMPRESS-A development environment.
#
# Two editable installs, in this order, and the order is the point: IMPRESS-A depends on
# `impress`, the package at the repository root, which is unreleased. Install this project
# first and pip goes looking for the name `impress` on PyPI and installs whatever it finds.
#
# Run from agent/:   ./scripts/dev_setup.sh
#
# On Delta this is NOT the script to use: `.venv` there is a symlink to $WORK_DIR/ve/impress_a
# on NVMe, and the environment needs PyRosetta, torch, Boltz-2 and LigandMPNN on top of this.
# Use scripts/delta_env_setup.sh, which does those twelve steps. The venv must be on
# /work/nvme and not /work/hdd: `import pyrosetta` alone measured 471s off HDD-backed Lustre
# against a 300s task budget (job 22675512). `impress-a preflight` flags a venv still on HDD.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(cd .. && pwd)"

# 3.10 is this project's floor and is enough for the mock/laptop tier. Dragon requires >=3.11,
# so a venv built here cannot run the HPC backends - which is fine, because nothing local does.
PY="${PY:-python3}"
"$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' || {
  echo "need Python >= 3.10 (got $("$PY" -V)); set PY=python3.11 or later" >&2; exit 1; }

if [ ! -d .venv ]; then
  echo "== creating .venv with $("$PY" -V)"
  "$PY" -m venv .venv
fi

echo "== upgrading pip"
.venv/bin/python -m pip install --quiet --upgrade pip

echo "== installing impress (editable, from $ROOT)"
.venv/bin/pip install --quiet -e ..

echo "== installing impress-a with dev extras (editable)"
.venv/bin/pip install --quiet -e ".[dev]"

echo "== versions"
.venv/bin/python - <<'EOF'
import impress, radical.asyncflow as af, rhapsody
print(f"  impress            {impress.__all__}")
print(f"  radical.asyncflow  {af.__version__}")
print(f"  rhapsody           {getattr(rhapsody, '__version__', 'installed')}")
EOF

cat <<'EOF'

== next
  source .venv/bin/activate
  ruff check src tests          # reports; never rewrites (fix = false in pyproject.toml)
  pytest tests -q               # the whole local tier, no allocation
  impress-a tools               # the registered toolkit
  impress-a run campaigns/mock-stabilize.yaml --model D
EOF
