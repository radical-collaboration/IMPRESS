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

# The live-endpoint client for control model B. An extra rather than a dependency: the default
# profile is the deterministic rehearsal, which needs nothing, and the whole local test tier
# runs against a fake endpoint. Installed here anyway because "the client has never been
# constructed" is how `LangChainOracle` kept a docstring claiming structured output over a
# brace-slice - `tests/test_oracle.py` builds a real one when this is present and skips when it
# is not, which is only a useful guard if the development venv has it.
echo "== installing the oracle extra (control model B's live client)"
.venv/bin/pip install --quiet -e ".[oracle]"

# AuCaM, the enclosing campaign manager IMPRESS-A offers itself to as a subordinate workflow.
# An extra for the same reason as the oracle above: nothing in the package imports it unless a
# caller asks for the adapter, but the adapter's tests are only a guard if the development venv
# has it - they build a real WorkflowConfig and emit through AuCaM's own reporter rather than a
# fake, and skip when it is absent. Installed from the pinned commit in pyproject.toml; to work
# against a live checkout instead, `pip install -e ../../campaign_manager` over the top.
echo "== installing the aucam extra (the enclosing campaign manager)"
.venv/bin/pip install --quiet -e ".[aucam]"

# Verify rather than trust the order: `impress` is on no index, so if pip went looking for the
# name and found something, the import below succeeds and returns the wrong module. Failing hard
# here is the difference between a confusing campaign and a one-line error.
echo "== verifying"
.venv/bin/python - "$ROOT" <<'EOF'
import pathlib, sys
import impress, radical.asyncflow as af, rhapsody
repo = pathlib.Path(sys.argv[1]).resolve()
got = pathlib.Path(impress.__file__).resolve()
want = repo / "src" / "impress" / "__init__.py"
if got != want:
    sys.exit(f"FAIL: `impress` resolved to {got}, not {want} - a package of that name came "
             f"from an index. `pip uninstall impress` and re-run this script.")
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
