import json
import os
import pathlib

from small_molecule_binding import ETYPE_BACKBONE, ETYPE_SEQUENCE, ETYPE_FOLD


def register_mock_tasks(pipeline):
    """Register lightweight mock tasks that create hardcoded output files."""

    @pipeline.auto_register_task(local_task=True)
    async def rfd3(task_description=None, **kwargs):
        pipeline.taskcount += 1
        taskname = "rfd3"
        pipeline.previous_task = taskname
        taskdir = f"{pipeline.base_path}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        model_name = "pdb_model_0"
        with open(f"{taskdir}/out/{model_name}.json", "w") as fh:
            json.dump({
                "metrics": {
                    "n_clashing":       {"ligand_clashes": 0},
                    "max_ca_deviation": 1.2,
                    "helix_fraction":   0.4,
                    "sheet_fraction":   0.1,
                }
            }, fh)
        with open(f"{taskdir}/out/{model_name}.pdb", "w") as fh:
            fh.write("REMARK  mock rfd3 output\nEND\n")

    @pipeline.auto_register_task(local_task=True)
    async def analysis_backbone(task_description=None, **kwargs):
        taskdir = f"{pipeline.base_path}/{pipeline.taskcount}_rfd3"
        backbone_path = f"{taskdir}/out/pdb_model_0.pdb"
        pipeline.state['best_backbone_path'] = backbone_path
        pipeline.state['last_analysis_step'] = 'backbone'
        pipeline.state['last_analysis_metrics'] = {
            'pass':             True,
            'best_model':       'pdb_model_0',
            'ligand_clashes':   0,
            'max_ca_deviation': 1.2,
            'ss_fraction':      0.5,
        }
        pipeline.state['ensemble'].append((
            ETYPE_BACKBONE, 0.5, pipeline.state.get('rfd3_input_pdb'), backbone_path,
        ))

    @pipeline.auto_register_task(local_task=True)
    async def mpnn(task_description=None, **kwargs):
        pipeline.taskcount += 1
        taskname = "mpnn"
        pipeline.previous_task = taskname
        taskdir = f"{pipeline.base_path}/{pipeline.taskcount}_{taskname}"
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
        with open(f"{taskdir}/out/seqs/binder_rank_001.fa", "w") as fh:
            fh.write(
                ">binder_rank_001, T=0.1, seed=111, overall_confidence=0.85, "
                "ligand_confidence=0.75, seq_rec=0.90\n"
                "MAGICKSEQUENCE\n"
            )

    @pipeline.auto_register_task(local_task=True)
    async def analysis_sequence(task_description=None, **kwargs):
        taskdir  = f"{pipeline.base_path}/{pipeline.taskcount}_mpnn"
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
        taskdir  = f"{pipeline.base_path}/{pipeline.taskcount}_{taskname}"
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
        taskdir  = f"{pipeline.base_path}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        with open(f"{taskdir}/out/binder_rank_001_relaxed_0001.pdb", "w") as fh:
            fh.write("REMARK  mock fastrelax output\nEND\n")
        with open(f"{taskdir}/out/binder_rank_001_relaxed.fasc", "w") as fh:
            json.dump({'total_score': -10.0, 'interaction_energy': -8.0, 'rmsd': 0.5}, fh)

    @pipeline.auto_register_task(local_task=True)
    async def analysis_fastrelax(task_description=None, **kwargs):
        pipeline.state['last_analysis_step']    = 'fastrelax'
        pipeline.state['last_analysis_metrics'] = {
            'pass':        True,
            'total_score': -10.0,
            'interact':    -8.0,
            'rmsd':        0.5,
        }

    @pipeline.auto_register_task(local_task=True)
    async def filter_shape(ligand_name="ALX", task_description=None, **kwargs):
        taskname = "filter_shape"
        taskdir  = f"{pipeline.base_path}/{pipeline.taskcount}_{taskname}"
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
        pipeline.state['last_analysis_step']    = 'interface'
        pipeline.state['last_analysis_metrics'] = {'pass': True, 'max_sc': 0.65}

    @pipeline.auto_register_task(local_task=True)
    async def af2(task_description=None, **kwargs):
        pipeline.taskcount += 1
        taskname = "alphafold"
        pipeline.previous_task = taskname
        taskdir  = f"{pipeline.base_path}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        for rank in range(1, 6):
            with open(f"{taskdir}/out/rank_{rank:03d}.pdb", "w") as fh:
                fh.write(f"REMARK  mock af2 rank_{rank:03d}\nEND\n")
            with open(f"{taskdir}/out/rank_{rank:03d}_scores.json", "w") as fh:
                json.dump({"plddt": [85.0 + rank] * 50, "max_pae": 5.0}, fh)

    @pipeline.auto_register_task(local_task=True)
    async def analysis_fold(task_description=None, **kwargs):
        taskdir    = f"{pipeline.base_path}/{pipeline.taskcount}_alphafold"
        best_model = f"{taskdir}/out/rank_005.pdb"
        pipeline.state['best_af2_model']        = best_model
        pipeline.state['last_analysis_step']    = 'fold'
        pipeline.state['last_analysis_metrics'] = {
            'pass':            True,
            'best_mean_plddt': 90.0,
            'best_model':      best_model,
        }
        pipeline.state['ensemble'].append((
            ETYPE_FOLD, 90.0, pipeline.state.get('last_seq_fasta'), best_model,
        ))

    @pipeline.auto_register_task(local_task=True)
    async def filter_energy(ligand_name="ALX", task_description=None, **kwargs):
        taskname = "filter_energy"
        taskdir  = f"{pipeline.base_path}/{pipeline.taskcount}_{taskname}"
        os.makedirs(f"{taskdir}/in",  exist_ok=True)
        os.makedirs(f"{taskdir}/out", exist_ok=True)

        with open(f"{taskdir}/out/negative_ligand_filenames.txt", "w") as fh:
            fh.write("binder_rank_001.pdb\n")
        with open(f"{taskdir}/out/negative_ligand_energies.txt", "w") as fh:
            fh.write("binder_rank_001.pdb\tLigand Energy: -15.0\n")
