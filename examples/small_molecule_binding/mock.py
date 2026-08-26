import json
import os
import pathlib
import random

from small_molecule_binding import ETYPE_BACKBONE, ETYPE_SEQUENCE, ETYPE_FOLD


_AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def _synthetic_ca_pdb(seed: int, n_res: int = 15, jitter: float = 1.5) -> str:
    """Deterministic fake CA trace in fixed-width PDB ATOM format, so _ca_rmsd
    gets real (non-None, non-degenerate) coordinates to compare instead of an
    empty structure."""
    rng = random.Random(seed)
    lines = ["REMARK  mock synthetic CA trace\n"]
    x = y = z = 0.0
    for i in range(1, n_res + 1):
        x += 3.8 + rng.uniform(-jitter, jitter)
        y += rng.uniform(-jitter, jitter)
        z += rng.uniform(-jitter, jitter)
        lines.append(
            f"ATOM  {i:>5} {'CA':>4} {'ALA':<3} A{i:>4}    "
            f"{x:>8.3f}{y:>8.3f}{z:>8.3f}{1.00:>6.2f}{0.00:>6.2f}           C\n"
        )
    lines.append("END\n")
    return "".join(lines)


def _synthetic_jitter(seed: int, base: float, jitter: float) -> float:
    """Deterministic base +/- jitter, so ensemble scores vary across entries
    instead of being a tied constant (which would make similarity comparisons
    like `selective > overall` never able to fire)."""
    return base + random.Random(seed).uniform(-jitter, jitter)


def _synthetic_sequence(seed: int, base_seq: str, n_mutations_max: int = 4) -> str:
    """Deterministic point-mutated variant of base_seq, so _seq_identity sees
    real variation across cycles instead of always comparing identical strings."""
    rng = random.Random(seed)
    seq = list(base_seq)
    n_mutations = rng.randint(0, n_mutations_max)
    positions = rng.sample(range(len(seq)), min(n_mutations, len(seq)))
    for pos in positions:
        seq[pos] = rng.choice(_AA_ALPHABET)
    return "".join(seq)


def register_mock_tasks(pipeline):
    """Register lightweight mock tasks that create hardcoded output files."""

    @pipeline.auto_register_task(local_task=True)
    async def rfd3(task_description=None, **kwargs):
        pipeline.taskcount += 1
        taskname = "rfd3"
        pipeline.previous_task = taskname
        taskdir = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        model_name = "pdb_model_0"
        max_ca_deviation = _synthetic_jitter(pipeline.taskcount, base=1.2, jitter=0.1)
        ss_fraction      = _synthetic_jitter(pipeline.taskcount, base=0.5, jitter=0.05)
        with open(f"{taskdir}/out/{model_name}.json", "w") as fh:
            json.dump({
                "metrics": {
                    "n_clashing":       {"ligand_clashes": 0},
                    "max_ca_deviation": max_ca_deviation,
                    "helix_fraction":   ss_fraction * 0.8,
                    "sheet_fraction":   ss_fraction * 0.2,
                }
            }, fh)
        with open(f"{taskdir}/out/{model_name}.pdb", "w") as fh:
            fh.write(_synthetic_ca_pdb(seed=pipeline.taskcount))

    @pipeline.auto_register_task(local_task=True)
    async def analysis_backbone(task_description=None, **kwargs):
        taskdir = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_rfd3"
        backbone_path = f"{taskdir}/out/pdb_model_0.pdb"

        ligand_clashes   = 0
        max_ca_deviation = _synthetic_jitter(pipeline.taskcount, base=1.2, jitter=0.1)
        ss_fraction      = _synthetic_jitter(pipeline.taskcount, base=0.5, jitter=0.05)
        passed = (
            ligand_clashes == 0
            and max_ca_deviation < pipeline.backbone_max_ca_deviation
            and ss_fraction      > pipeline.backbone_min_ss_fraction
        )

        pipeline.state['best_backbone_path'] = backbone_path
        pipeline.state['last_analysis_step'] = 'backbone'
        pipeline.state['last_analysis_metrics'] = {
            'pass':             passed,
            'best_model':       'pdb_model_0',
            'ligand_clashes':   ligand_clashes,
            'max_ca_deviation': max_ca_deviation,
            'ss_fraction':      ss_fraction,
        }
        pipeline.state['ensemble'].append((
            ETYPE_BACKBONE, ss_fraction, pipeline.state.get('rfd3_input_pdb'), backbone_path,
        ))

    @pipeline.auto_register_task(local_task=True)
    async def mpnn(task_description=None, **kwargs):
        pipeline.taskcount += 1
        taskname = "mpnn"
        pipeline.previous_task = taskname
        taskdir = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",         exist_ok=True)
        os.makedirs(f"{taskdir}/out/packed", exist_ok=True)
        os.makedirs(f"{taskdir}/out/seqs",   exist_ok=True)

        # Mirror the real task: copy input to a short fixed name in taskdir/in/
        cycle_i  = pipeline._current_cycle_i
        src_path = (
            pipeline.state['best_backbone_path'] if cycle_i == 0
            else pipeline.state['best_packed_pdb']
        )
        if pathlib.Path(src_path).name.endswith('.cif.gz'):
            short_name = 'binder.cif.gz'
        else:
            short_name = f'binder{pathlib.Path(src_path).suffix}'
        with open(f"{taskdir}/in/{short_name}", "w") as fh:
            fh.write("REMARK  mock mpnn input copy\n")

        with open(f"{taskdir}/out/packed/binder_rank_001_packed_1_1.pdb", "w") as fh:
            fh.write("REMARK  mock mpnn output\nEND\n")

        sequence = _synthetic_sequence(
            seed=pipeline.taskcount, base_seq="MAGICKSEQUENCEALPHA",
        )
        with open(f"{taskdir}/out/seqs/binder_rank_001.fa", "w") as fh:
            fh.write(
                ">binder_rank_001, T=0.1, seed=111, overall_confidence=0.85, "
                "ligand_confidence=0.75, seq_rec=0.90\n"
                f"{sequence}\n"
            )

    @pipeline.auto_register_task(local_task=True)
    async def analysis_sequence(task_description=None, **kwargs):
        taskdir  = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_mpnn"
        seqs_dir = f"{taskdir}/out/seqs"
        pipeline.state['last_mpnn_seqs_dir'] = seqs_dir
        pipeline.state['last_analysis_step'] = 'sequence'
        pipeline.state['best_packed_pdb'] = (
            f"{taskdir}/out/packed/binder_rank_001_packed_1_1.pdb"
        )
        pipeline.state['last_analysis_metrics'] = {
            'pass':                    True,
            'best_overall_confidence': 0.85,
            'best_ligand_confidence':  0.75,
        }
        fasta_path = f"{seqs_dir}/binder_rank_001.fa"
        pipeline.state['last_seq_fasta'] = fasta_path
        pipeline.state['ensemble'].append((
            ETYPE_SEQUENCE, 0.85, pipeline.state.get('best_backbone_path'), fasta_path,
        ))

    @pipeline.auto_register_task(local_task=True)
    async def packmin(task_description=None, **kwargs):
        pipeline.taskcount += 1
        taskname = "packmin"
        pipeline.previous_task = taskname
        taskdir  = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        # Derive stem from best_packed_pdb, matching the real packmin logic
        pdb_stem = pathlib.Path(pipeline.state['best_packed_pdb']).stem
        out_pdb  = f"{taskdir}/out/{pdb_stem}_minimized.pdb"
        with open(out_pdb, "w") as fh:
            fh.write("REMARK  mock packmin output\nEND\n")
        with open(f"{taskdir}/out/{pdb_stem}_minimized_packmin_score.json", "w") as fh:
            json.dump({'total_score': -150.0, 'pdb': out_pdb}, fh)
        pipeline.state['best_packed_pdb'] = out_pdb

    @pipeline.auto_register_task(local_task=True)
    async def analysis_packmin(task_description=None, **kwargs):
        pipeline.state['last_analysis_step']    = 'packmin'
        pipeline.state['last_analysis_metrics'] = {'pass': True, 'total_score': -150.0}

    @pipeline.auto_register_task(local_task=True)
    async def fastrelax(task_description=None, **kwargs):
        pipeline.taskcount += 1
        taskname = "fastrelax"
        pipeline.previous_task = taskname
        taskdir  = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        with open(f"{taskdir}/out/binder_rank_001_relaxed_0001.pdb", "w") as fh:
            fh.write("REMARK  mock fastrelax output\nEND\n")
        with open(f"{taskdir}/out/binder_rank_001_relaxed.fasc", "w") as fh:
            json.dump({
                'total_score':        -10.0,
                'interaction_energy': -8.0,
                'fa_rep':             50.0,
                'rmsd':               0.5,
            }, fh)

    @pipeline.auto_register_task(local_task=True)
    async def analysis_fastrelax(task_description=None, **kwargs):
        total_score = -10.0
        interact    = -8.0
        fa_rep      = 50.0
        passed = (
            interact    < pipeline.fastrelax_max_interact
            and total_score < pipeline.fastrelax_max_total_score
            and fa_rep      < pipeline.fastrelax_max_fa_rep
        )
        pipeline.state['last_analysis_step']    = 'fastrelax'
        pipeline.state['last_analysis_metrics'] = {
            'pass':        passed,
            'total_score': total_score,
            'interact':    interact,
            'fa_rep':      fa_rep,
            'rmsd':        0.5,
        }

    @pipeline.auto_register_task(local_task=True)
    async def filter_shape(ligand_name="ALR", task_description=None, **kwargs):
        taskname = "filter_shape"
        taskdir  = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        with open(f"{taskdir}/out/shape_complementarity_values.txt", "w") as fh:
            fh.write("binder_rank_001.pdb\tShape Complementarity: 0.65\n")
        with open(f"{taskdir}/out/interface_values.txt", "w") as fh:
            fh.write(
                "FileName,Shape Complementarity,ddg,contact molecular surf,"
                "SASA,Very buried unsat hbond,Surface unsat hbond,SAP SCORE\n"
                "binder_rank_001.pdb,0.65,-15.0,450.0,1200.0,0,1,0.5\n"
            )

    @pipeline.auto_register_task(local_task=True)
    async def analysis_interface(task_description=None, **kwargs):
        max_sc = 0.65
        pipeline.state['last_analysis_step']    = 'interface'
        pipeline.state['last_analysis_metrics'] = {
            'pass':   max_sc >= pipeline.interface_min_sc,
            'max_sc': max_sc,
        }

    @pipeline.auto_register_task(local_task=True)
    async def af2(task_description=None, **kwargs):
        pipeline.taskcount += 1
        taskname = "alphafold"
        pipeline.previous_task = taskname
        taskdir  = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        for rank in range(1, 6):
            with open(f"{taskdir}/out/rank_{rank:03d}.pdb", "w") as fh:
                fh.write(_synthetic_ca_pdb(seed=pipeline.taskcount * 100 + rank))
            with open(f"{taskdir}/out/rank_{rank:03d}_scores.json", "w") as fh:
                json.dump({"plddt": [85.0 + rank] * 50, "max_pae": 5.0}, fh)

    @pipeline.auto_register_task(local_task=True)
    async def analysis_fold(task_description=None, **kwargs):
        taskdir    = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_alphafold"
        best_model = f"{taskdir}/out/rank_005.pdb"
        best_mean_plddt = _synthetic_jitter(pipeline.taskcount + 900_000, base=90.0, jitter=3.0)
        pipeline.state['best_af2_model']        = best_model
        pipeline.state['last_analysis_step']    = 'fold'
        pipeline.state['last_analysis_metrics'] = {
            'pass':            best_mean_plddt >= pipeline.fold_min_plddt,
            'best_mean_plddt': best_mean_plddt,
            'best_model':      best_model,
        }
        pipeline.state['ensemble'].append((
            ETYPE_FOLD, best_mean_plddt, pipeline.state.get('last_seq_fasta'), best_model,
        ))

    @pipeline.auto_register_task(local_task=True)
    async def filter_energy(ligand_name="ALR", task_description=None, **kwargs):
        taskname = "filter_energy"
        taskdir  = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        with open(f"{taskdir}/out/negative_ligand_filenames.txt", "w") as fh:
            fh.write("binder_rank_001.pdb\n")
        with open(f"{taskdir}/out/negative_ligand_energies.txt", "w") as fh:
            fh.write("binder_rank_001.pdb\tLigand Energy: -15.0\n")
