#!/usr/bin/env python3
"""Post-HPC-run validation for the small_molecule_binding example pipeline.

Standalone CLI (not a pipeline task): checks a completed or in-progress
`IMPRESS_TEST_MODE=1` (or production) HPC run's output tree against the
invariants the Boltz-2 / RFD3-guided-scaffold rewrite depends on, so a
successful-looking run is actually verified rather than assumed. See the
"Post-HPC-run validation" section of the design plan for the full rationale
behind each check.

Usage:
    python scripts/validate_run.py <base_path> <pipeline_name>
    python scripts/validate_run.py logs p1
    python scripts/validate_run.py logs p1 --python /path/to/venv/bin/python

Exits 0 if every check passes (SKIPPED checks do not count as failures),
nonzero if any check fails.
"""

import argparse
import glob
import json
import os
import subprocess
import sys

# ── Reuse small_molecule_binding.py's ligand-resname parsing logic ─────────
#
# This script lives at examples/small_molecule_binding/scripts/validate_run.py,
# one level below small_molecule_binding.py, so the example directory can
# reasonably be added to sys.path. Importing the real module is preferred
# (single source of truth for the "never hardcode a ligand resname" rule) but
# small_molecule_binding.py imports the `impress` package at module scope, so
# it only works in an environment that has the framework installed. Fall back
# to a duplicated minimal implementation so this validator still works when
# run standalone (the task description explicitly anticipates this).

_EXAMPLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _EXAMPLE_DIR not in sys.path:
    sys.path.insert(0, _EXAMPLE_DIR)

try:
    from small_molecule_binding import _ligand_resname_from_params
except Exception:
    def _ligand_resname_from_params(params_path: str) -> str:
        """Fallback duplicate of small_molecule_binding._ligand_resname_from_params,
        used only when importing the real module fails (e.g. `impress` is not
        installed in this environment). Keep this in sync with the original --
        it reads the exact literal from the params file's NAME record and must
        NEVER hardcode a resname (e.g. 'ALR'); see that function's docstring."""
        with open(params_path) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "NAME":
                    return parts[1]
        raise ValueError(f"no NAME record found in {params_path}")


# The exact literal that must never reappear as a HETATM resname (RFD3
# misresolves the bare "ALR" -- see ALR.params's NAME record / design plan).
# Never treated as "the" expected resname -- always compared against whatever
# _ligand_resname_from_params() reads live from ALR.params.
_REGRESSION_RESNAME = "ALR"

# State key that was designed, then explicitly rejected, during the RFD3
# guided-scaffold redesign (an earlier Kabsch-superposition ligand-grafting
# approach needed it; Boltz's joint co-folding made it unnecessary). Its
# reappearance anywhere in run output would mean a regression to that
# rejected approach.
_REJECTED_STATE_KEY = "rfd3_guide_ligand_pdb"

# At least one of these must exist somewhere under $BOLTZ_CACHE for the cache
# to be considered "warmed" (see plan's delta_env_setup.sh Step 12/13).
_BOLTZ_CACHE_MARKERS = ("boltz2_conf.ckpt", "boltz2_aff.ckpt", "mols.tar", "ccd.pkl")

# Skip these extensions when grepping run output for the rejected state key --
# they're binary/compressed and can be large; a literal ASCII key string
# would not usefully appear in them the way it would in JSON/log/PDB text.
_GREP_SKIP_EXTENSIONS = (".gz", ".png", ".npz", ".pt", ".ckpt", ".pdb.gz", ".cif.gz")
_GREP_MAX_BYTES = 50 * 1024 * 1024  # don't slurp huge files into memory


def _resolve_pipeline_inputs(base_path: str, pipeline_name: str) -> str:
    """Resolve the pipeline_inputs directory the way this actually plays out in
    production, not SmallMoleculeBindingPipeline.__init__'s bare fallback.

    __init__ only falls back to `{base_path}/{name}_in` when no `input_dir`
    kwarg is given at all. In practice, run_small_molecule_binding.py always
    passes an explicit `input_dir` that is a *sibling* of base_path (both
    `logs/` and `p1_in/` live directly under the examples directory) -- see
    `examples_dir`/`work_dir`/`input_dir` in that file's `impress_smallmol_bind()`.
    We reproduce that sibling convention first (matches real runs), falling
    back to the bare class-default location if the sibling doesn't exist.
    """
    base_path = os.path.abspath(base_path)
    sibling = os.path.join(os.path.dirname(base_path), f"{pipeline_name}_in")
    if os.path.isdir(sibling):
        return sibling
    return os.path.join(base_path, f"{pipeline_name}_in")


def _iter_hetatm_resnames(pdb_path: str):
    """Return the list of resname strings (PDB fixed-width columns 18-20) for
    every HETATM record in pdb_path."""
    names = []
    with open(pdb_path, errors="replace") as fh:
        for line in fh:
            if line.startswith("HETATM"):
                names.append(line[17:20].strip())
    return names


# ── Check 1: ligand identity preserved end-to-end ───────────────────────────

def check_ligand_identity(base_path: str, pipeline_name: str, pipeline_inputs: str):
    """Every Boltz model PDB and every guided_scaffold.pdb must contain a
    HETATM residue named exactly the literal read live from ALR.params's NAME
    record. Fails loudly (and specifically) if the bad literal "ALR" shows up
    instead -- that exact regression must never reappear."""
    params_path = os.path.join(pipeline_inputs, "ALR.params")
    if not os.path.isfile(params_path):
        return [f"cannot check ligand identity: {params_path} not found"]
    try:
        expected = _ligand_resname_from_params(params_path)
    except Exception as e:
        return [f"cannot parse NAME record from {params_path}: {e}"]

    pipeline_dir = os.path.join(base_path, pipeline_name)
    # NOTE: boltz nests its own output under out_dir/boltz_results_<yaml_stem>/
    # before the predictions/<record_id>/ layout (confirmed against boltz's
    # source: `out_dir = out_dir / f"boltz_results_{data.stem}"` in main.py,
    # and empirically against a real `boltz predict` run) -- this is easy to
    # miss from the docs alone.
    candidates = sorted(
        glob.glob(os.path.join(pipeline_dir, "*_boltz", "out", "boltz_results_boltz_input",
                                "predictions", "boltz_input", "*_model_*.pdb"))
        + glob.glob(os.path.join(pipeline_dir, "*_rfd3", "in", "guided_scaffold.pdb"))
    )
    if not candidates:
        return [
            f"no '*_boltz/out/boltz_results_boltz_input/predictions/boltz_input/*_model_*.pdb' "
            f"or '*_rfd3/in/guided_scaffold.pdb' files found under {pipeline_dir} "
            f"-- nothing to check (has this run produced any boltz/guided-rfd3 output yet?)"
        ]

    failures = []
    for pdb_path in candidates:
        resnames = _iter_hetatm_resnames(pdb_path)
        if not resnames:
            failures.append(
                f"{pdb_path}: no HETATM records found at all "
                f"(expected ligand resname {expected!r})"
            )
            continue
        if expected in resnames:
            continue
        if _REGRESSION_RESNAME in resnames and expected != _REGRESSION_RESNAME:
            failures.append(
                f"{pdb_path}: REGRESSION -- found literal {_REGRESSION_RESNAME!r} instead of "
                f"expected {expected!r}. RFD3 misresolves the bare {_REGRESSION_RESNAME!r} "
                f"literal; the colon in {expected!r} is a deliberate workaround (see "
                f"{params_path}'s NAME record), not a typo. This must never reappear."
            )
        else:
            failures.append(
                f"{pdb_path}: expected ligand resname {expected!r} not found among HETATM "
                f"residues found: {sorted(set(resnames))!r}"
            )
    return failures


# ── Check 2: Boltz output shape ─────────────────────────────────────────────

def check_boltz_output_shape(base_path: str, pipeline_name: str):
    """Every */_boltz/out/ dir must have boltz_results_boltz_input/predictions/
    boltz_input/confidence_boltz_input_model_*.json files that parse as JSON
    and carry complex_plddt (numeric, ~0-1) and a ligand_iptm key (value may
    be null)."""
    pipeline_dir = os.path.join(base_path, pipeline_name)
    boltz_out_dirs = sorted(glob.glob(os.path.join(pipeline_dir, "*_boltz", "out")))
    if not boltz_out_dirs:
        return [f"no '*_boltz/out' directories found under {pipeline_dir}"]

    failures = []
    for out_dir in boltz_out_dirs:
        pred_dir = os.path.join(out_dir, "boltz_results_boltz_input", "predictions", "boltz_input")
        if not os.path.isdir(pred_dir):
            failures.append(f"{out_dir}: missing boltz_results_boltz_input/predictions/boltz_input/ directory")
            continue
        conf_files = sorted(
            glob.glob(os.path.join(pred_dir, "confidence_boltz_input_model_*.json"))
        )
        if not conf_files:
            failures.append(
                f"{pred_dir}: no 'confidence_boltz_input_model_*.json' files found"
            )
            continue
        for cf in conf_files:
            try:
                with open(cf) as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError) as e:
                failures.append(f"{cf}: failed to parse as JSON: {e}")
                continue
            if "complex_plddt" not in data:
                failures.append(f"{cf}: missing 'complex_plddt' key")
            else:
                v = data["complex_plddt"]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    failures.append(f"{cf}: complex_plddt is not numeric: {v!r}")
                elif not (-0.01 <= v <= 1.05):
                    failures.append(
                        f"{cf}: complex_plddt={v!r} is outside the expected ~0-1 range"
                    )
            if "ligand_iptm" not in data:
                failures.append(
                    f"{cf}: missing 'ligand_iptm' key (value may legitimately be null)"
                )
    return failures


# ── Check 3: guided JSON correctness ────────────────────────────────────────

def check_guided_json_correctness(base_path: str, pipeline_name: str, pipeline_inputs: str):
    """Every */_rfd3/in/guided_binder_design.json must parse, its partial.input
    must point at a file that exists, and partial.ligand/length/select_exposed/
    select_buried must match the base ALR_binder_design.json verbatim (only
    input/partial_t may legitimately differ) -- mirrors _write_guided_rfd3_json."""
    pipeline_dir = os.path.join(base_path, pipeline_name)
    guided_jsons = sorted(
        glob.glob(os.path.join(pipeline_dir, "*_rfd3", "in", "guided_binder_design.json"))
    )
    if not guided_jsons:
        # No guided rfd3 runs have happened yet (e.g. very first backbone, or no
        # fold has passed similarity gating yet) -- not a failure by itself.
        return []

    base_json_path = os.path.join(pipeline_inputs, "ALR_binder_design.json")
    if not os.path.isfile(base_json_path):
        return [f"cannot check guided JSONs: base spec {base_json_path} not found"]
    try:
        with open(base_json_path) as fh:
            base = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        return [f"{base_json_path}: failed to parse as JSON: {e}"]
    base_partial = base.get("partial", {})

    failures = []
    for gj in guided_jsons:
        try:
            with open(gj) as fh:
                guided = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            failures.append(f"{gj}: failed to parse as JSON: {e}")
            continue

        partial = guided.get("partial")
        if not isinstance(partial, dict):
            failures.append(f"{gj}: missing/invalid top-level 'partial' object")
            continue

        input_path = partial.get("input")
        if not input_path:
            failures.append(f"{gj}: 'partial.input' is missing")
        else:
            resolved = (
                input_path if os.path.isabs(input_path)
                else os.path.join(os.path.dirname(gj), input_path)
            )
            if not os.path.isfile(resolved):
                failures.append(
                    f"{gj}: partial.input={input_path!r} does not point at an existing file "
                    f"(resolved: {resolved})"
                )

        for field in ("ligand", "length", "select_exposed", "select_buried"):
            expected = base_partial.get(field)
            actual = partial.get(field)
            if actual != expected:
                failures.append(
                    f"{gj}: partial.{field} differs from base {base_json_path} -- "
                    f"expected {expected!r}, found {actual!r} (only 'input'/'partial_t' "
                    f"may legitimately differ)"
                )
    return failures


# ── Check 4: RFD3 didn't silently no-op ─────────────────────────────────────

def check_rfd3_no_op(base_path: str, pipeline_name: str):
    """Every */_rfd3/out/ dir must contain at least one '*_model_*.json' file
    (mirrors analysis_backbone()'s own file-discovery: f.endswith('.json') and
    '_model_' in f). Best-effort: if any captured task stdout/stderr log is
    discoverable, grep it for TypeError/RFD3InferenceConfig crash signatures.

    NOTE on the log-discovery part: capture_stdio=True task logs are written
    by the execution backend into asyncflow's own session directory under the
    process cwd ('asyncflow.session.<uuid>'), which is unrelated to base_path,
    and their filenames use an internal task uid ('task.NNNNNN') with no
    relationship to this pipeline's '{taskcount}_{taskname}' convention. There
    is therefore no reliable static way to tie a captured log file back to one
    specific rfd3 taskdir. This check scans the taskdir itself (in case a
    future version copies logs there) and flags a crash signature generically
    if found, without claiming it belongs to any particular rfd3 invocation.
    """
    pipeline_dir = os.path.join(base_path, pipeline_name)
    rfd3_out_dirs = sorted(glob.glob(os.path.join(pipeline_dir, "*_rfd3", "out")))
    if not rfd3_out_dirs:
        return [f"no '*_rfd3/out' directories found under {pipeline_dir}"]

    failures = []
    log_files = []
    for out_dir in rfd3_out_dirs:
        model_jsons = [
            f for f in os.listdir(out_dir) if f.endswith(".json") and "_model_" in f
        ] if os.path.isdir(out_dir) else []
        if not model_jsons:
            failures.append(
                f"{out_dir}: no '*_model_*.json' files found -- rfd3 may have silently "
                f"produced no output"
            )
        taskdir = os.path.dirname(out_dir)
        for pattern in ("*.stdout", "*.stderr", "*.log"):
            log_files.extend(glob.glob(os.path.join(taskdir, pattern)))
            log_files.extend(glob.glob(os.path.join(taskdir, "*", pattern)))

    seen = set()
    for lf in log_files:
        if lf in seen or not os.path.isfile(lf):
            continue
        seen.add(lf)
        try:
            if os.path.getsize(lf) > _GREP_MAX_BYTES:
                continue
            with open(lf, errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue
        if "TypeError" in content or "RFD3InferenceConfig" in content:
            failures.append(
                f"{lf}: contains 'TypeError' or 'RFD3InferenceConfig' -- possible RFD3 crash "
                f"signature (the exact error the old scaffoldguided.target_pdb bug produced). "
                f"NOTE: log discovery is best-effort and not reliably tied to a specific rfd3 "
                f"taskdir -- see check_rfd3_no_op()'s docstring."
            )
    return failures


# ── Check 5: state-key regression guard ─────────────────────────────────────

def check_no_rejected_state_key(base_path: str, pipeline_name: str):
    """Grep all files under base_path/pipeline_name for the literal
    'rfd3_guide_ligand_pdb' -- a state
    key that was designed then explicitly rejected in favor of Boltz's joint
    co-folding. Its reappearance anywhere means the rejected
    Kabsch-superposition ligand-grafting approach crept back in."""
    pipeline_dir = os.path.join(base_path, pipeline_name)
    if not os.path.isdir(pipeline_dir):
        return [f"{pipeline_dir} does not exist -- nothing to grep"]

    failures = []
    key_bytes = _REJECTED_STATE_KEY.encode()

    def _grep_tree(root_dir):
        for root, _dirs, files in os.walk(root_dir):
            for fname in files:
                if fname.endswith(_GREP_SKIP_EXTENSIONS):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    if os.path.getsize(fpath) > _GREP_MAX_BYTES:
                        continue
                    with open(fpath, "rb") as fh:
                        chunk = fh.read()
                except OSError:
                    continue
                if key_bytes in chunk:
                    failures.append(
                        f"{fpath}: contains rejected state key "
                        f"{_REJECTED_STATE_KEY!r} -- regression to the rejected "
                        f"Kabsch-superposition ligand-grafting design"
                    )

    _grep_tree(pipeline_dir)

    return failures


# ── Check 6: ensemble sanity ─────────────────────────────────────────────────

def check_ensemble_sanity(base_path: str, pipeline_name: str):
    """Ensemble state (self.state['ensemble']) lives only in the pipeline's
    in-memory process state -- ImpressBasePipeline and
    SmallMoleculeBindingPipeline have no checkpoint/state-dump-to-disk
    convention as of this writing (confirmed by reading
    src/impress/pipelines/impress_pipeline.py and small_molecule_binding.py:
    no pickle/json state-dump call anywhere in either). There is therefore
    nothing on disk to check monotonic-taskcount / no-duplicate-tuple
    invariants against. Rather than fabricate a check against directory
    counts that don't actually reconstruct the ensemble list, this is an
    explicit no-op."""
    return [
        "SKIPPED: no on-disk ensemble state found, cannot verify (ensemble lives in "
        "in-memory self.state, not persisted to disk by this framework)"
    ]


# ── Check 7: env sanity ──────────────────────────────────────────────────────

def check_env_sanity(python_exe: str):
    """$BOLTZ_CACHE must exist and contain at least one known weight/cache
    marker file; `import boltz` must succeed under the given interpreter."""
    failures = []

    boltz_cache = os.environ.get("BOLTZ_CACHE")
    if not boltz_cache:
        failures.append("BOLTZ_CACHE environment variable is not set")
    elif not os.path.isdir(boltz_cache):
        failures.append(f"BOLTZ_CACHE={boltz_cache!r} is not a directory")
    else:
        found = None
        for root, _dirs, files in os.walk(boltz_cache):
            for marker in _BOLTZ_CACHE_MARKERS:
                if marker in files:
                    found = os.path.join(root, marker)
                    break
            if found:
                break
        if not found:
            failures.append(
                f"BOLTZ_CACHE={boltz_cache!r} does not contain any of "
                f"{_BOLTZ_CACHE_MARKERS!r} -- weights may not have been "
                f"downloaded / cache-warmed yet"
            )

    try:
        result = subprocess.run(
            [python_exe, "-c", "import boltz"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        failures.append(f"failed to run {python_exe!r} to check `import boltz`: {e}")
    else:
        if result.returncode != 0:
            stderr_tail = result.stderr.strip()[-500:]
            failures.append(
                f"`{python_exe} -c 'import boltz'` failed (exit {result.returncode}): "
                f"{stderr_tail}"
            )
    return failures


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a completed (or in-progress) small_molecule_binding HPC run's "
            "output tree against the Boltz-2 / RFD3-guided-scaffold invariants."
        )
    )
    parser.add_argument(
        "base_path",
        help="Pipeline base_path, e.g. 'logs' (same value passed as SmallMoleculeBindingPipeline's base_path kwarg)",
    )
    parser.add_argument("pipeline_name", help="Pipeline name, e.g. 'p1'")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter to check `import boltz` with (default: the interpreter running this script)",
    )
    args = parser.parse_args(argv)

    base_path = os.path.abspath(args.base_path)
    pipeline_name = args.pipeline_name
    pipeline_dir = os.path.join(base_path, pipeline_name)
    pipeline_inputs = _resolve_pipeline_inputs(base_path, pipeline_name)

    print(f"Validating run: base_path={base_path} pipeline_name={pipeline_name}")
    print(f"Resolved pipeline_dir:    {pipeline_dir}")
    print(f"Resolved pipeline_inputs: {pipeline_inputs}")
    print()

    if not os.path.isdir(base_path):
        print(f"FAIL: base_path {base_path!r} does not exist")
        return 1
    if not os.path.isdir(pipeline_dir):
        print(
            f"FAIL: pipeline directory {pipeline_dir!r} does not exist -- "
            f"has pipeline {pipeline_name!r} run yet under this base_path?"
        )
        return 1
    if not os.path.isdir(pipeline_inputs):
        print(
            f"WARNING: pipeline_inputs directory {pipeline_inputs!r} does not exist -- "
            f"checks 1 and 3 (which need ALR.params / ALR_binder_design.json) will fail\n"
        )

    checks = [
        ("1. Ligand identity preserved end-to-end",
         lambda: check_ligand_identity(base_path, pipeline_name, pipeline_inputs)),
        ("2. Boltz output shape",
         lambda: check_boltz_output_shape(base_path, pipeline_name)),
        ("3. Guided JSON correctness",
         lambda: check_guided_json_correctness(base_path, pipeline_name, pipeline_inputs)),
        ("4. RFD3 didn't silently no-op",
         lambda: check_rfd3_no_op(base_path, pipeline_name)),
        ("5. State-key regression guard (rfd3_guide_ligand_pdb)",
         lambda: check_no_rejected_state_key(base_path, pipeline_name)),
        ("6. Ensemble sanity",
         lambda: check_ensemble_sanity(base_path, pipeline_name)),
        ("7. Env sanity (BOLTZ_CACHE / import boltz)",
         lambda: check_env_sanity(args.python)),
    ]

    print("=" * 72)
    print("VALIDATION RESULTS")
    print("=" * 72)

    any_failed = False
    for name, fn in checks:
        try:
            failures = fn()
        except Exception as e:  # a check itself must never crash the whole run
            failures = [f"check raised an unexpected exception: {e!r}"]

        if failures and all(f.startswith("SKIPPED:") for f in failures):
            print(f"[SKIP] {name}")
            for f in failures:
                print(f"       {f}")
        elif not failures:
            print(f"[PASS] {name}")
        else:
            any_failed = True
            print(f"[FAIL] {name} -- {len(failures)} issue(s)")
            for f in failures:
                print(f"       - {f}")

    print("=" * 72)
    if any_failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
