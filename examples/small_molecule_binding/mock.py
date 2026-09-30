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

        rfd3_input_pdb = pipeline.state.get('rfd3_input_pdb')
        if rfd3_input_pdb:
            # Marker file so tests can assert the guided-diffusion path fired,
            # without simulating the real gemmi-based ligand-normalization
            # logic (mock's synthetic CA trace has no ligand HETATM block).
            with open(f"{taskdir}/in/guided_binder_design.json", "w") as fh:
                json.dump({
                    "guided_source": rfd3_input_pdb,
                    "partial_t":     pipeline.rfd3_partial_t,
                }, fh)

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

        # Mirror real LigandMPNN's actual output shape (confirmed against live
        # HPC runs): ONE file (seqs/binder.fa) containing a template record (no
        # 'id='/confidence fields, an echo of the input) followed by several
        # designed candidate records ('id=1'..'id=N', each with
        # overall_confidence/ligand_confidence) -- NOT one file per candidate.
        # id=3 is deliberately the highest-confidence candidate here (not id=1,
        # the first) so a regression test can tell "picks the best" apart from
        # "picks the first"/"picks the last".
        candidate_base_conf = {"1": 0.35, "2": 0.40, "3": 0.55, "4": 0.38}
        for cand_id in ("1", "2", "3", "4"):
            with open(f"{taskdir}/out/packed/binder_packed_{cand_id}_1.pdb", "w") as fh:
                fh.write("REMARK  mock mpnn output\nEND\n")

        template_seq = _synthetic_sequence(
            seed=pipeline.taskcount, base_seq="MAGICKSEQUENCEALPHA",
        )
        with open(f"{taskdir}/out/seqs/binder.fa", "w") as fh:
            fh.write(
                f">binder, T=0.1, seed=111, num_res={len(template_seq)}, "
                "num_ligand_res=10\n"
                f"{template_seq}\n"
            )
            for cand_id, base_conf in candidate_base_conf.items():
                conf     = _synthetic_jitter(pipeline.taskcount * 10 + int(cand_id), base=base_conf, jitter=0.02)
                lig_conf = _synthetic_jitter(pipeline.taskcount * 10 + int(cand_id) + 400_000, base=base_conf - 0.05, jitter=0.02)
                cand_seq = _synthetic_sequence(
                    seed=pipeline.taskcount * 10 + int(cand_id), base_seq=template_seq,
                )
                fh.write(
                    f">binder, id={cand_id}, T=0.1, seed=111, "
                    f"overall_confidence={conf:.4f}, ligand_confidence={lig_conf:.4f}, "
                    "seq_rec=0.5000\n"
                    f"{cand_seq}\n"
                )

    @pipeline.auto_register_task(local_task=True)
    async def analysis_sequence(task_description=None, **kwargs):
        taskdir  = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_mpnn"
        seqs_dir = f"{taskdir}/out/seqs"
        pipeline.state['last_mpnn_seqs_dir'] = seqs_dir
        pipeline.state['last_analysis_step'] = 'sequence'

        # Mirrors the real analysis_sequence()'s parsing: evaluate every id=
        # record across every .fa file, skip the template record.
        best_conf, best_lig_conf, best_id, best_seq = -1.0, 0.0, None, None
        for fa_file in os.listdir(seqs_dir):
            if not fa_file.endswith('.fa'):
                continue
            with open(f"{seqs_dir}/{fa_file}") as fh:
                content = fh.read()
            for record in content.split('>')[1:]:
                lines = record.splitlines()
                if not lines:
                    continue
                header, seq = lines[0], ''.join(lines[1:]).strip()
                parts = {
                    kv.split('=')[0].strip(): kv.split('=')[1].strip()
                    for kv in header.split(',') if '=' in kv
                }
                if 'id' not in parts:
                    continue
                conf     = float(parts.get('overall_confidence', 0))
                lig_conf = float(parts.get('ligand_confidence', 0))
                if conf > best_conf:
                    best_conf, best_lig_conf, best_id, best_seq = conf, lig_conf, parts['id'], seq

        if best_id is not None:
            pipeline.state['best_packed_pdb'] = f"{taskdir}/out/packed/binder_packed_{best_id}_1.pdb"
            fasta_path = f"{seqs_dir}/best_candidate.fa"
            with open(fasta_path, "w") as fh:
                fh.write(f">binder_id_{best_id}\n{best_seq}\n")
            pipeline.state['last_seq_fasta'] = fasta_path
        else:
            pipeline.state['last_seq_fasta'] = None

        pipeline.state['last_analysis_metrics'] = {
            'pass':                    True,
            'best_overall_confidence': best_conf,
            'best_ligand_confidence':  best_lig_conf,
        }
        pipeline.state['ensemble'].append((
            ETYPE_SEQUENCE, best_conf, pipeline.state.get('best_backbone_path'),
            pipeline.state.get('last_seq_fasta'),
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
    async def boltz(task_description=None, **kwargs):
        pipeline.taskcount += 1
        taskname = "boltz"
        pipeline.previous_task = taskname
        taskdir  = f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_{taskname}"
        # Mirrors real boltz's own out_dir/boltz_results_<yaml_stem>/predictions/
        # nesting (see small_molecule_binding.py's analysis_fold() comment).
        pred_dir = f"{taskdir}/out/boltz_results_boltz_input/predictions/boltz_input"
        os.makedirs(f"{taskdir}/in", exist_ok=True)
        os.makedirs(pred_dir,        exist_ok=True)

        for model_i in range(5):
            seed = pipeline.taskcount * 100 + model_i
            with open(f"{pred_dir}/boltz_input_model_{model_i}.pdb", "w") as fh:
                fh.write(_synthetic_ca_pdb(seed=seed))
            complex_plddt = _synthetic_jitter(seed, base=0.90, jitter=0.03)
            ligand_iptm   = _synthetic_jitter(seed + 500_000, base=0.70, jitter=0.05)
            with open(f"{pred_dir}/confidence_boltz_input_model_{model_i}.json", "w") as fh:
                json.dump({
                    "complex_plddt":    complex_plddt,
                    "ligand_iptm":      ligand_iptm,
                    "confidence_score": complex_plddt,
                    "ptm":              _synthetic_jitter(seed + 600_000, base=0.75, jitter=0.05),
                    "iptm":             _synthetic_jitter(seed + 700_000, base=0.70, jitter=0.05),
                    "protein_iptm":     _synthetic_jitter(seed + 800_000, base=0.72, jitter=0.05),
                }, fh)

    @pipeline.auto_register_task(local_task=True)
    async def analysis_fold(task_description=None, **kwargs):
        pred_dir = (
            f"{pipeline.base_path}/{pipeline.name}/{pipeline.taskcount}_boltz/out/"
            "boltz_results_boltz_input/predictions/boltz_input"
        )
        conf_files = [
            f for f in os.listdir(pred_dir)
            if f.startswith('confidence_') and f.endswith('.json')
        ] if os.path.isdir(pred_dir) else []

        best_complex_plddt = -1.0
        best_model         = None
        best_ligand_iptm   = None
        for cf in conf_files:
            with open(f"{pred_dir}/{cf}") as fh:
                data = json.load(fh)
            score = data.get('complex_plddt', 0.0)
            if score > best_complex_plddt:
                best_complex_plddt = score
                best_model         = cf.replace('confidence_', '', 1).replace('.json', '.pdb')
                best_ligand_iptm   = data.get('ligand_iptm')

        # Rescale 0-1 -> 0-100 to preserve fold_min_plddt's existing semantics
        # (mirrors the real analysis_fold()).
        best_plddt_100 = best_complex_plddt * 100.0
        passed = best_plddt_100 >= pipeline.fold_min_plddt
        if pipeline.fold_min_ligand_iptm is not None:
            passed = passed and (
                best_ligand_iptm is not None
                and best_ligand_iptm >= pipeline.fold_min_ligand_iptm
            )

        if best_model:
            full_model_path = f"{pred_dir}/{best_model}"
            pipeline.state['best_fold_model'] = full_model_path
            pipeline.state['ensemble'].append((
                ETYPE_FOLD, best_plddt_100, pipeline.state.get('last_seq_fasta'), full_model_path,
            ))

        pipeline.state['last_analysis_step']    = 'fold'
        pipeline.state['last_analysis_metrics'] = {
            'pass':               passed,
            'best_complex_plddt': best_plddt_100,
            'best_ligand_iptm':   best_ligand_iptm,
            'best_model':         best_model,
        }

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
