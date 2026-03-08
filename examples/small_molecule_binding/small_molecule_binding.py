
import asyncio
import copy
import json
import os
import pathlib
from functools import lru_cache

from impress.pipelines.impress_pipeline import ImpressBasePipeline

FOUNDRY_PRE_EXEC = [""]
PYROSETTA_PRE_EXEC = ["source /anvil/scratch/x-mason/env_pyrosetta"]
LMPNN_PRE_EXEC = [""]
AF2_PRE_EXEC = [
    "module load modtree/gpu",
    "module load gcc/11.2.0",
    "module load cuda/12.8.0",
    "export PATH=/anvil/scratch/x-mason/localcolabfold/.pixi/envs/default/bin:$PATH"
]

# Step constants for the outer state machine
STEP_DONE      = 0   # pipeline complete
STEP_RFD3      = 1   # backbone diffusion
STEP_MPNN      = 2   # mpnn + packmin refinement cycle
STEP_FASTRELAX = 3   # Rosetta FastRelax
STEP_INTERFACE = 4   # filter_shape (PyRosetta, gates af2)
STEP_AF2       = 5   # fold prediction
STEP_RETRY_SEQ = 6   # internal: retry sequence prediction without backbone restart

# Ensemble transformation type labels
ETYPE_BACKBONE = 'generate backbone'
ETYPE_SEQUENCE = 'predict sequence'
ETYPE_FOLD     = 'fold decoy'


# ── Ensemble utility functions ─────────────────────────────────────────────

@lru_cache(maxsize=512)
def _parse_pdb_ca_coords(pdb_path: str) -> tuple:
    coords = []
    with open(pdb_path) as f:
        for line in f:
            if line.startswith('ATOM') and line[12:16].strip() == 'CA':
                coords.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return tuple(coords)


def _kabsch_rmsd(coords1, coords2) -> float:
    import numpy as np
    n = min(len(coords1), len(coords2))
    P = np.array(coords1[:n], dtype=float)
    Q = np.array(coords2[:n], dtype=float)
    P -= P.mean(axis=0)
    Q -= Q.mean(axis=0)
    H = P.T @ Q
    U, _, Vt = np.linalg.svd(H)
    d = np.linalg.det(Vt.T @ U.T)
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    diff = (P @ R.T) - Q
    return float(np.sqrt((diff ** 2).sum() / n))


def _ca_rmsd(path1: str, path2: str):
    """CA RMSD between two PDB files. Returns None for non-.pdb paths or empty coord sets."""
    if not (isinstance(path1, str) and isinstance(path2, str)):
        return None
    if not (path1.endswith('.pdb') and path2.endswith('.pdb')):
        return None
    c1 = _parse_pdb_ca_coords(path1)
    c2 = _parse_pdb_ca_coords(path2)
    if not c1 or not c2:
        return None
    return _kabsch_rmsd(c1, c2)


def _read_fasta_seq(fasta_path: str) -> str:
    if not fasta_path:
        return ''
    seq = []
    try:
        with open(fasta_path) as f:
            for line in f:
                if not line.startswith('>'):
                    seq.append(line.strip())
    except FileNotFoundError:
        return ''
    return ''.join(seq)


def _seq_identity(fasta1: str, fasta2: str):
    """Fraction of matching residues over shorter sequence. Returns None on empty."""
    s1 = _read_fasta_seq(fasta1)
    s2 = _read_fasta_seq(fasta2)
    if not s1 or not s2:
        return None
    n = min(len(s1), len(s2))
    return sum(a == b for a, b in zip(s1[:n], s2[:n])) / n


def _ensemble_selective_avg(
    current_output: str,
    prior_entries: list,
    sim_fn,
    similar_if_low: bool,
):
    """
    Returns (overall_avg, selective_avg, has_data: bool).
    selective_avg = average score of entries whose similarity to current is on the
    'similar' side of the mean pairwise similarity.
    has_data=False when prior_entries is empty or all similarity calls return None.
    """
    if not prior_entries:
        return None, None, False
    scores  = [t[1] for t in prior_entries]
    sims    = [sim_fn(current_output, t[3]) for t in prior_entries]
    valid   = [(s, sc) for s, sc in zip(sims, scores) if s is not None]
    overall_avg = sum(scores) / len(scores)
    if not valid:
        return overall_avg, None, False
    avg_sim = sum(s for s, _ in valid) / len(valid)
    if similar_if_low:
        sel_scores = [sc for s, sc in valid if s <= avg_sim]
    else:
        sel_scores = [sc for s, sc in valid if s >= avg_sim]
    if not sel_scores:
        return overall_avg, overall_avg, True
    return overall_avg, sum(sel_scores) / len(sel_scores), True


class SmallMoleculeBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs=None, **kwargs):
        if configs is None:
            configs = {}

        # Legacy / bookkeeping attrs
        self.passes     = kwargs.get("passes",     1)
        self.step_id    = kwargs.get("step_id",    1)
        self.seq_rank   = kwargs.get("seq_rank",   0)
        self.num_seqs   = kwargs.get("num_seqs",   10)
        self.sub_order  = kwargs.get("sub_order",  0)
        self.max_passes = kwargs.get("max_passes", 1)
        self.mock       = kwargs.get("mock",       False)

        self.current_scores  = {}
        self.iter_seqs       = kwargs.get("iter_seqs",      {})
        self.previous_scores = kwargs.get("previous_score", {})

        super().__init__(name, flow, **configs, **kwargs)

        # Paths
        self.base_path       = kwargs.get("base_path", os.getcwd())
        self.scripts_path    = os.path.join(self.base_path, "scripts")
        self.pipeline_inputs = os.path.join(self.base_path, f"{self.name}_in")
        self.mpnn_dir        = kwargs.get("mpnn_dir", f"{self.base_path}/LigandMPNN")

        # Configurable tool paths and ensemble sizes
        self.foundry_sif_path   = kwargs.get("foundry_sif_path",   "/anvil/scratch/x-mason/foundry.sif")
        self.colabfold_path     = kwargs.get("colabfold_path",     "/anvil/scratch/x-mason/localcolabfold")
        self.ligand_params      = kwargs.get("ligand_params",      "ALX.params")
        self.mpnn_ensemble_size = kwargs.get("mpnn_ensemble_size", 10)
        self.num_refine_cycles  = kwargs.get("num_refine_cycles",  3)

        # Quality thresholds (overridable at construction time)
        self.backbone_max_ca_deviation = kwargs.get("backbone_max_ca_deviation", 2.0)
        self.backbone_min_ss_fraction  = kwargs.get("backbone_min_ss_fraction",  0.2)
        self.fastrelax_max_fa_rep      = kwargs.get("fastrelax_max_fa_rep",      10.0)
        self.fastrelax_max_total_score = kwargs.get("fastrelax_max_total_score", 0.0)
        self.interface_min_sc          = kwargs.get("interface_min_sc",          0.5)
        self.fold_min_plddt            = kwargs.get("fold_min_plddt",            70.0)
        self.max_tasks                 = kwargs.get("max_tasks",                 300)

        # Output paths (legacy)
        self.output_path         = os.path.join(self.base_path, "myoutputs", self.name)
        self.output_path_packmin = os.path.join(self.output_path, "packmin")
        self.output_path_lmpnn   = os.path.join(self.output_path, "lmpnn")

        # Task tracking
        self.taskcount     = 0
        self.previous_task = "START"

        # State machine
        self.state            = {}   # written by analysis tasks, read by adaptive_fn
        self.next_step        = STEP_RFD3
        self._current_cycle_i = 0   # set by run() before each mpnn call

    # ── Task registration ──────────────────────────────────────────────────

    def register_pipeline_tasks(self):
        if self.mock:
            self._register_mock_tasks()
        else:
            self._register_real_tasks()

    # ── MOCK tasks ─────────────────────────────────────────────────────────

    def _register_mock_tasks(self):
        """Register lightweight mock tasks that create hardcoded output files."""

        @self.auto_register_task(local_task=True)
        async def rfd3(task_description=None, **kwargs):
            self.taskcount += 1
            taskname = "rfd3"
            self.previous_task = taskname
            taskdir = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            model_name = "pdb_model_0"
            with open(f"{taskdir}/out/{model_name}.json", "w") as fh:
                json.dump({
                    "metrics": {
                        "n_clashing":     {"ligand_clashes": 0},
                        "max_ca_deviation": 1.2,
                        "helix_fraction": 0.4,
                        "sheet_fraction": 0.1,
                    }
                }, fh)
            with open(f"{taskdir}/out/{model_name}.pdb", "w") as fh:
                fh.write("REMARK  mock rfd3 output\nEND\n")

        @self.auto_register_task(local_task=True)
        async def analysis_backbone(task_description=None, **kwargs):
            taskdir = f"{self.base_path}/{self.taskcount}_rfd3"
            backbone_path = f"{taskdir}/out/pdb_model_0.pdb"
            self.state['best_backbone_path'] = backbone_path
            self.state['last_analysis_step'] = 'backbone'
            self.state['last_analysis_metrics'] = {
                'pass':             True,
                'best_model':       'pdb_model_0',
                'ligand_clashes':   0,
                'max_ca_deviation': 1.2,
                'ss_fraction':      0.5,
            }
            self.state['ensemble'].append((
                ETYPE_BACKBONE, 0.5, self.state.get('rfd3_input_pdb'), backbone_path,
            ))

        @self.auto_register_task(local_task=True)
        async def mpnn(task_description=None, **kwargs):
            self.taskcount += 1
            taskname = "mpnn"
            self.previous_task = taskname
            taskdir = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",         exist_ok=True)
            os.makedirs(f"{taskdir}/out/packed", exist_ok=True)
            os.makedirs(f"{taskdir}/out/seqs",   exist_ok=True)

            pdb_content = "REMARK  mock mpnn output\nEND\n"
            with open(f"{taskdir}/out/packed/pdb_rank_001_packed_1_1.pdb", "w") as fh:
                fh.write(pdb_content)
            with open(f"{taskdir}/out/seqs/pdb_rank_001.fa", "w") as fh:
                fh.write(
                    ">pdb_rank_001, T=0.1, seed=111, overall_confidence=0.85, "
                    "ligand_confidence=0.75, seq_rec=0.90\n"
                    "MAGICKSEQUENCE\n"
                )

        @self.auto_register_task(local_task=True)
        async def analysis_sequence(task_description=None, **kwargs):
            taskdir  = f"{self.base_path}/{self.taskcount}_mpnn"
            seqs_dir = f"{taskdir}/out/seqs"
            self.state['last_mpnn_seqs_dir'] = seqs_dir
            self.state['last_analysis_step'] = 'sequence'
            # Always update best_packed_pdb so packmin reads the right file
            self.state['best_packed_pdb'] = (
                f"{taskdir}/out/packed/pdb_rank_001_packed_1_1.pdb"
            )
            self.state['last_analysis_metrics'] = {
                'pass':                    True,
                'best_overall_confidence': 0.85,
                'best_ligand_confidence':  0.75,
            }
            fasta_path = f"{seqs_dir}/pdb_rank_001.fa"
            self.state['last_seq_fasta'] = fasta_path
            self.state['ensemble'].append((
                ETYPE_SEQUENCE, 0.85, self.state.get('best_backbone_path'), fasta_path,
            ))

        @self.auto_register_task(local_task=True)
        async def packmin(task_description=None, **kwargs):
            self.taskcount += 1
            taskname = "packmin"
            self.previous_task = taskname
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            out_pdb = f"{taskdir}/out/pdb_rank_001_minimized.pdb"
            with open(out_pdb, "w") as fh:
                fh.write("REMARK  mock packmin output\nEND\n")
            with open(f"{taskdir}/out/pdb_rank_001_minimized_packmin_score.json", "w") as fh:
                json.dump({'total_score': -150.0, 'pdb': out_pdb}, fh)
            # Update state so next mpnn reads from this packmin's output
            self.state['best_packed_pdb'] = out_pdb

        @self.auto_register_task(local_task=True)
        async def analysis_packmin(task_description=None, **kwargs):
            self.state['last_analysis_step']    = 'packmin'
            self.state['last_analysis_metrics'] = {'pass': True, 'total_score': -150.0}

        @self.auto_register_task(local_task=True)
        async def fastrelax(task_description=None, **kwargs):
            self.taskcount += 1
            taskname = "fastrelax"
            self.previous_task = taskname
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            with open(f"{taskdir}/out/pdb_rank_001_relaxed_0001.pdb", "w") as fh:
                fh.write("REMARK  mock fastrelax output\nEND\n")
            with open(f"{taskdir}/out/pdb_rank_001_relaxed.fasc", "w") as fh:
                json.dump({'total_score': -10.0, 'fa_rep': 2.0, 'rmsd': 0.5}, fh)

        @self.auto_register_task(local_task=True)
        async def analysis_fastrelax(task_description=None, **kwargs):
            self.state['last_analysis_step']    = 'fastrelax'
            self.state['last_analysis_metrics'] = {
                'pass':        True,
                'total_score': -10.0,
                'fa_rep':      2.0,
                'rmsd':        0.5,
            }

        @self.auto_register_task(local_task=True)
        async def filter_shape(ligand_name="ALX", task_description=None, **kwargs):
            taskname = "filter_shape"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            with open(f"{taskdir}/out/shape_complementarity_values.txt", "w") as fh:
                fh.write("pdb_rank_001.pdb\tShape Complementarity: 0.65\n")
            with open(f"{taskdir}/out/interface_values.txt", "w") as fh:
                fh.write(
                    "FileName,Shape Complementarity,ddg,contact molecular surf,"
                    "SASA,Very buried unsat hbond,Surface unsat hbond,SAP SCORE\n"
                    "pdb_rank_001.pdb,0.65,-15.0,450.0,1200.0,0,1,0.5\n"
                )

        @self.auto_register_task(local_task=True)
        async def analysis_interface(task_description=None, **kwargs):
            self.state['last_analysis_step']    = 'interface'
            self.state['last_analysis_metrics'] = {'pass': True, 'max_sc': 0.65}

        @self.auto_register_task(local_task=True)
        async def af2(task_description=None, **kwargs):
            self.taskcount += 1
            taskname = "alphafold"
            self.previous_task = taskname
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            for rank in range(1, 6):
                with open(f"{taskdir}/out/rank_{rank:03d}.pdb", "w") as fh:
                    fh.write(f"REMARK  mock af2 rank_{rank:03d}\nEND\n")
                with open(f"{taskdir}/out/rank_{rank:03d}_scores.json", "w") as fh:
                    json.dump({"plddt": [85.0 + rank] * 50, "max_pae": 5.0}, fh)

        @self.auto_register_task(local_task=True)
        async def analysis_fold(task_description=None, **kwargs):
            taskdir    = f"{self.base_path}/{self.taskcount}_alphafold"
            best_model = f"{taskdir}/out/rank_005.pdb"
            self.state['best_af2_model']        = best_model
            self.state['last_analysis_step']    = 'fold'
            self.state['last_analysis_metrics'] = {
                'pass':            True,
                'best_mean_plddt': 90.0,
                'best_model':      best_model,
            }
            self.state['ensemble'].append((
                ETYPE_FOLD, 90.0, self.state.get('last_seq_fasta'), best_model,
            ))

        @self.auto_register_task(local_task=True)
        async def filter_energy(ligand_name="ALX", task_description=None, **kwargs):
            taskname = "filter_energy"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            with open(f"{taskdir}/out/negative_ligand_filenames.txt", "w") as fh:
                fh.write("pdb_rank_001.pdb\n")
            with open(f"{taskdir}/out/negative_ligand_energies.txt", "w") as fh:
                fh.write("pdb_rank_001.pdb\tLigand Energy: -15.0\n")

    # ── REAL tasks ─────────────────────────────────────────────────────────

    def _register_real_tasks(self):
        """Register real HPC tasks that return shell command strings."""

        @self.auto_register_task()
        async def rfd3(task_description={"gpus_per_rank": 1}):
            self.taskcount += 1
            taskname = "rfd3"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            inputs     = f"{self.pipeline_inputs}/ALR_binder_design.json"
            output_dir = f"{taskdir}/out"

            input_pdb    = self.state.get('rfd3_input_pdb')
            scaffold_arg = f"scaffoldguided.target_pdb={input_pdb} " if input_pdb else ""

            return (
                f"apptainer exec --nv {self.foundry_sif_path} rfd3 design "
                f"out_dir={output_dir} "
                f"inputs={inputs} "
                f"{scaffold_arg}"
                f"skip_existing=False "
                f"dump_trajectories=True "
                f"prevalidate_inputs=True "
            )

        @self.auto_register_task(local_task=True)
        async def analysis_backbone(task_description=None):
            out_dir    = f"{self.base_path}/{self.taskcount}_rfd3/out"
            json_files = [
                f for f in os.listdir(out_dir)
                if f.endswith('.json') and '_model_' in f
            ]

            best = None
            for jf in json_files:
                with open(f"{out_dir}/{jf}") as fh:
                    data = json.load(fh)
                m       = data.get('metrics', {})
                clashes = m.get('n_clashing', {}).get('ligand_clashes', float('inf'))
                dev     = m.get('max_ca_deviation', float('inf'))
                ss      = m.get('helix_fraction', 0) + m.get('sheet_fraction', 0)

                if best is None or clashes < best['clashes'] or (
                    clashes == best['clashes'] and dev < best['dev']
                ):
                    best = {'file': jf, 'clashes': clashes, 'dev': dev, 'ss': ss}

            if best is None:
                self.state.update({
                    'last_analysis_step':    'backbone',
                    'last_analysis_metrics': {'pass': False},
                })
                self.state['ensemble'].append((
                    ETYPE_BACKBONE, 0.0, self.state.get('rfd3_input_pdb'), None,
                ))
                return

            backbone_path = os.path.join(out_dir, best['file'].replace('.json', '.cif.gz'))
            self.state['best_backbone_path'] = backbone_path
            passed = (
                best['clashes'] == 0
                and best['dev'] < self.backbone_max_ca_deviation
                and best['ss']  > self.backbone_min_ss_fraction
            )
            self.state.update({
                'last_analysis_step': 'backbone',
                'last_analysis_metrics': {
                    'pass':             passed,
                    'best_model':       best['file'],
                    'ligand_clashes':   best['clashes'],
                    'max_ca_deviation': best['dev'],
                    'ss_fraction':      best['ss'],
                },
            })
            self.state['ensemble'].append((
                ETYPE_BACKBONE, best['ss'], self.state.get('rfd3_input_pdb'), backbone_path,
            ))

        @self.auto_register_task()
        async def mpnn(fixed_residues_file: str | None = None):
            self.taskcount += 1
            taskname = "mpnn"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            cycle_i   = self._current_cycle_i
            pdb_path  = self.state['best_backbone_path'] if cycle_i == 0 else self.state['best_packed_pdb']
            n_batches = self.mpnn_ensemble_size if cycle_i == 0 else 1
            output_dir = f"{taskdir}/out"

            if fixed_residues_file:
                with open(fixed_residues_file) as f:
                    fixed_residues = f.read().strip()
                fixed_residues_line = f"--fixed_residues {fixed_residues} \\"
            else:
                fixed_residues_line = ""

            return (
                f"python {self.mpnn_dir}/run.py \\\n"
                f"  --model_type \"ligand_mpnn\" \\\n"
                f"  --checkpoint_path_sc {self.mpnn_dir}/model_params/ligandmpnn_sc_v_32_002_16.pt \\\n"
                f"  --checkpoint_ligand_mpnn {self.mpnn_dir}/model_params/ligandmpnn_v_32_010_25.pt \\\n"
                f"  --seed 111 \\\n"
                f"  --pdb_path {pdb_path} \\\n"
                f"  --out_folder {output_dir} \\\n"
                f"  --pack_side_chains 1 \\\n"
                f"  --number_of_batches {n_batches} \\\n"
                f"  --batch_size 1 \\\n"
                f"  --number_of_packs_per_design 1 \\\n"
                f"  --pack_with_ligand_context 1 \\\n"
                f"  --repack_everything 1 \\\n"
                f"  --temperature 0.1 \\\n"
                + fixed_residues_line
            )

        @self.auto_register_task(local_task=True)
        async def analysis_sequence(task_description=None):
            out_dir  = f"{self.base_path}/{self.taskcount}_mpnn/out"
            seqs_dir = f"{out_dir}/seqs"
            self.state['last_mpnn_seqs_dir'] = seqs_dir
            self.state['last_analysis_step'] = 'sequence'

            best_conf     = -1.0
            best_lig_conf = 0.0
            best_seq_name = None
            best_fa_file  = None

            for fa_file in [f for f in os.listdir(seqs_dir) if f.endswith('.fa')]:
                with open(f"{seqs_dir}/{fa_file}") as fh:
                    header = fh.readline().strip()
                try:
                    parts = {
                        kv.split('=')[0].strip(): kv.split('=')[1].strip()
                        for kv in header.lstrip('>').split(',')
                        if '=' in kv
                    }
                    conf     = float(parts.get('overall_confidence', 0))
                    lig_conf = float(parts.get('ligand_confidence',  0))
                    name     = header.lstrip('>').split(',')[0].strip()
                except (ValueError, IndexError):
                    continue

                if conf > best_conf:
                    best_conf     = conf
                    best_lig_conf = lig_conf
                    best_seq_name = name
                    best_fa_file  = fa_file

            # Always update best_packed_pdb so packmin reads the current mpnn output
            if best_seq_name:
                self.state['best_packed_pdb'] = f"{out_dir}/packed/{best_seq_name}_packed_1_1.pdb"
                self.state['last_seq_fasta']  = f"{seqs_dir}/{best_fa_file}"
            else:
                self.state['last_seq_fasta']  = None

            self.state['last_analysis_metrics'] = {
                'pass':                    True,
                'best_overall_confidence': best_conf,
                'best_ligand_confidence':  best_lig_conf,
            }
            self.state['ensemble'].append((
                ETYPE_SEQUENCE, best_conf,
                self.state.get('best_backbone_path'), self.state.get('last_seq_fasta'),
            ))

        @self.auto_register_task()
        async def packmin():
            self.taskcount += 1
            taskname = "packmin"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            pdb_path   = self.state['best_packed_pdb']
            pdb_stem   = pathlib.Path(pdb_path).stem
            output_dir = f"{taskdir}/out"
            lig_path   = f"{self.pipeline_inputs}/{self.ligand_params}"

            # Predict output path so the next mpnn can read from it
            self.state['best_packed_pdb'] = f"{output_dir}/{pdb_stem}_minimized.pdb"

            return (
                f"python {self.scripts_path}/packmin.py "
                f"{pdb_path} "
                f"-lig {lig_path} "
                f"--out_dir {output_dir} "
            )

        @self.auto_register_task(local_task=True)
        async def analysis_packmin(task_description=None):
            out_dir     = f"{self.base_path}/{self.taskcount}_packmin/out"
            score_files = [f for f in os.listdir(out_dir) if f.endswith('_packmin_score.json')]

            total_score = None
            if score_files:
                with open(f"{out_dir}/{score_files[0]}") as fh:
                    total_score = json.load(fh).get('total_score')

            self.state['last_analysis_step']    = 'packmin'
            self.state['last_analysis_metrics'] = {'pass': True, 'total_score': total_score}

        @self.auto_register_task()
        async def fastrelax():
            self.taskcount += 1
            taskname = "fastrelax"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            pdb_path   = self.state['best_packed_pdb']
            lig_path   = f"{self.pipeline_inputs}/{self.ligand_params}"
            output_dir = f"{taskdir}/out"

            return (
                f"python {self.scripts_path}/fastrelax.py "
                f"{pdb_path} "
                f"-n 1 "
                f"-lig {lig_path} "
                f"--out_dir {output_dir} "
            )

        @self.auto_register_task(local_task=True)
        async def analysis_fastrelax(task_description=None):
            out_dir    = f"{self.base_path}/{self.taskcount}_fastrelax/out"
            fasc_files = [f for f in os.listdir(out_dir) if f.endswith('.fasc')]

            total_score = fa_rep = rmsd = None
            if fasc_files:
                with open(f"{out_dir}/{fasc_files[0]}") as fh:
                    data = json.load(fh)
                total_score = data.get('total_score')
                fa_rep      = data.get('fa_rep')
                rmsd        = data.get('rmsd')

            passed = (
                fa_rep      is not None and fa_rep      < self.fastrelax_max_fa_rep
                and total_score is not None and total_score < self.fastrelax_max_total_score
            )
            self.state['last_analysis_step']    = 'fastrelax'
            self.state['last_analysis_metrics'] = {
                'pass':        passed,
                'total_score': total_score,
                'fa_rep':      fa_rep,
                'rmsd':        rmsd,
            }

        @self.auto_register_task()
        async def filter_shape(ligand_name: str = "ALX"):
            taskname = "filter_shape"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            pdb_directory = f"{self.base_path}/{self.taskcount}_fastrelax/out"

            return (
                f"python {self.scripts_path}/filter_shape.py "
                f"{pdb_directory} "
                f"{taskdir}/out/shape_complementarity_values.txt "
                f"{self.pipeline_inputs}/{ligand_name} "
                f"{taskdir}/out/interface_values.txt "
            )

        @self.auto_register_task(local_task=True)
        async def analysis_interface(task_description=None):
            sc_file = (
                f"{self.base_path}/{self.taskcount}_filter_shape/out/"
                "shape_complementarity_values.txt"
            )
            max_sc = 0.0
            try:
                with open(sc_file) as fh:
                    for line in fh:
                        parts = line.strip().split('\t')
                        if len(parts) >= 2:
                            try:
                                max_sc = max(max_sc, float(parts[1].split(': ')[-1]))
                            except ValueError:
                                pass
            except FileNotFoundError:
                pass

            self.state['last_analysis_step']    = 'interface'
            self.state['last_analysis_metrics'] = {
                'pass':   max_sc >= self.interface_min_sc,
                'max_sc': max_sc,
            }

        @self.auto_register_task()
        async def af2(task_description={"gpus_per_rank": 1}):
            self.taskcount += 1
            taskname = "alphafold"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            fasta_path = self.state['last_seq_fasta']
            output_dir = f"{taskdir}/out"

            return (
                f"pixi run --manifest-path {self.colabfold_path} "
                f"colabfold_batch "
                f"--model-type alphafold2 "
                f"--rank multimer "
                f"--random-seed 999 "
                f"--save-all "
                f"--debug-logging "
                f"{fasta_path} "
                f"{output_dir} "
            )

        @self.auto_register_task(local_task=True)
        async def analysis_fold(task_description=None):
            out_dir     = f"{self.base_path}/{self.taskcount}_alphafold/out"
            score_files = [
                f for f in os.listdir(out_dir)
                if 'scores' in f and f.endswith('.json')
            ]

            best_plddt = -1.0
            best_model = None
            for sf in score_files:
                with open(f"{out_dir}/{sf}") as fh:
                    arr = json.load(fh).get('plddt', [])
                if arr:
                    mean_plddt = sum(arr) / len(arr)
                    if mean_plddt > best_plddt:
                        best_plddt = mean_plddt
                        best_model = sf.replace('_scores.json', '.pdb')

            if best_model:
                full_model_path = f"{out_dir}/{best_model}"
                self.state['best_af2_model'] = full_model_path
                self.state['ensemble'].append((
                    ETYPE_FOLD, best_plddt, self.state.get('last_seq_fasta'), full_model_path,
                ))

            self.state['last_analysis_step']    = 'fold'
            self.state['last_analysis_metrics'] = {
                'pass':            best_plddt >= self.fold_min_plddt,
                'best_mean_plddt': best_plddt,
                'best_model':      best_model,
            }

        @self.auto_register_task()
        async def filter_energy(ligand_name: str = "ALX"):
            taskname = "filter_energy"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            pdb_directory         = f"{self.base_path}/{self.taskcount}_fastrelax/out"
            outputs_dir           = f"{taskdir}/out"
            output_file           = f"{outputs_dir}/negative_ligand_filenames.txt"
            output_energy_file    = f"{outputs_dir}/negative_ligand_energies.txt"
            common_filenames_file = f"{self.pipeline_inputs}/common_filenames.txt"

            return (
                f"python {self.scripts_path}/filter_energy.py "
                f"{pdb_directory} "
                f"{output_file} "
                f"{output_energy_file} "
                f"{common_filenames_file} "
                f"{ligand_name} "
            )

    # ── Score utils ────────────────────────────────────────────────────────

    async def get_scores_map(self):
        return {"c_scores": self.current_scores, "p_scores": self.previous_scores}

    def finalize(self, sub_iter_seqs=None):
        self.previous_scores = copy.deepcopy(self.current_scores)

    # ── Inner refinement cycle ─────────────────────────────────────────────

    async def _run_refine_cycle(self):
        """MPNN + PackMin refinement cycle with per-cycle sequence retry support."""
        for cycle_i in range(self.num_refine_cycles):
            self._current_cycle_i = cycle_i

            while True:  # sequence retry loop — exited by STEP_MPNN (pass) or non-STEP_RETRY_SEQ
                if len(self.state.get('ensemble', [])) >= self.max_tasks:
                    self.logger.pipeline_log(
                        f"Task budget exhausted ({self.max_tasks} ensemble entries). Stopping."
                    )
                    self.next_step = STEP_DONE
                    return

                self.logger.pipeline_log(f"running mpnn [cycle {cycle_i}]")
                await self.mpnn(
                    fixed_residues_file=f"{self.pipeline_inputs}/fixed_residues.txt"
                )
                self.logger.pipeline_log(f"mpnn [cycle {cycle_i}] finished")
                await self.analysis_sequence()
                await self.run_adaptive_step()

                if self.next_step == STEP_MPNN:
                    break                  # ensemble check passed — continue to packmin
                elif self.next_step == STEP_RETRY_SEQ:
                    continue               # ensemble check failed — retry mpnn same cycle
                else:
                    return                 # STEP_RFD3 (retry exhausted) or STEP_FASTRELAX

            if cycle_i < self.num_refine_cycles - 1:
                if len(self.state.get('ensemble', [])) >= self.max_tasks:
                    self.logger.pipeline_log(
                        f"Task budget exhausted ({self.max_tasks} ensemble entries). Stopping."
                    )
                    self.next_step = STEP_DONE
                    return
                self.logger.pipeline_log(f"running packmin [cycle {cycle_i}]")
                await self.packmin(task_description={"pre_exec": PYROSETTA_PRE_EXEC})
                self.logger.pipeline_log(f"packmin [cycle {cycle_i}] finished")
                await self.analysis_packmin()
                await self.run_adaptive_step()
                if self.next_step != STEP_MPNN:
                    return

        # Natural completion — outer run() auto-advances to STEP_FASTRELAX

    # ── Main state-machine run loop ────────────────────────────────────────

    async def run(self):
        self.next_step = STEP_RFD3
        self.state.setdefault('ensemble', [])
        self.state.setdefault('rfd3_input_pdb', None)
        self.state.setdefault('seq_retry_count', 0)
        self.state.setdefault('last_seq_fasta', None)
        self.logger.pipeline_log("SmallMoleculeBindingPipeline starting (state machine)")

        while self.next_step != STEP_DONE:
            if len(self.state['ensemble']) >= self.max_tasks:
                self.logger.pipeline_log(
                    f"Task budget exhausted ({self.max_tasks} ensemble entries). Stopping."
                )
                break


            if self.next_step == STEP_RFD3:
                self.logger.pipeline_log("running rfd3")
                await self.rfd3()
                self.logger.pipeline_log("rfd3 finished")
                await self.analysis_backbone()
                await self.run_adaptive_step()

            elif self.next_step == STEP_MPNN:
                await self._run_refine_cycle()
                if self.next_step == STEP_MPNN:
                    # All cycles completed normally — advance to fastrelax
                    self.next_step = STEP_FASTRELAX

            elif self.next_step == STEP_FASTRELAX:
                self.logger.pipeline_log("running fastrelax")
                await self.fastrelax(task_description={"pre_exec": PYROSETTA_PRE_EXEC})
                self.logger.pipeline_log("fastrelax finished")
                await self.analysis_fastrelax()
                await self.run_adaptive_step()

            elif self.next_step == STEP_INTERFACE:
                self.logger.pipeline_log("running filter_shape")
                await self.filter_shape(task_description={"pre_exec": PYROSETTA_PRE_EXEC})
                self.logger.pipeline_log("filter_shape finished")
                await self.analysis_interface()
                await self.run_adaptive_step()

            elif self.next_step == STEP_AF2:
                self.logger.pipeline_log("running af2")
                await self.af2()
                self.logger.pipeline_log("af2 finished")
                await self.analysis_fold()
                await self.run_adaptive_step()

            else:
                self.logger.pipeline_log(f"Unknown next_step={self.next_step}, stopping")
                break

        self.logger.pipeline_log("Pipeline complete")
