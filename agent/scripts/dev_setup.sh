#!/usr/bin/env bash
# Build the IMPRESS-A development environment.
#
# One editable install of this project, plus the extras its tests are only a guard with. It no
# longer installs the root `impress` package first: IMPRESS-A does not depend on it (its Stages
# are asyncflow blocks), which also leaves no unreleased name for pip to resolve on PyPI.
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

# 3.11 is this project's floor: radical.asyncflow and rhapsody 0.7.0 both require it. Dragon is
# an extra (`.[dragon]`) and is not installed here - nothing local runs it.
PY="${PY:-python3}"
"$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' || {
  echo "need Python >= 3.11 (got $("$PY" -V)); set PY=python3.11 or later" >&2; exit 1; }

if [ ! -d .venv ]; then
  echo "== creating .venv with $("$PY" -V)"
  "$PY" -m venv .venv
fi

echo "== upgrading pip"
.venv/bin/python -m pip install --quiet --upgrade pip

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

# Figures for the mock knob lab. An extra rather than a dependency - only
# analysis/mock_figures.py imports matplotlib - but installed here for the same reason as the
# two above: four tests in test_mock_lab.py sit behind `importorskip("matplotlib")` and are
# only a guard if the development venv has it. CI installs this extra for the same reason.
echo "== installing the figures extra (the mock lab's plots)"
.venv/bin/pip install --quiet -e ".[figures]"

echo "== verifying"
.venv/bin/python - <<'EOF'
import radical.asyncflow as af, rhapsody
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
