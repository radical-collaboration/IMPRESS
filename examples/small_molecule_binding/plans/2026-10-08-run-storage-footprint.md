# Run storage footprint: mpnn PDB retention, per-job packing, all-failed exit, self-contained job dirs

**Severity:** high (a run was killed by it) · **Status:** open, design only · **BACKLOG:** 18–21
**Evidence:** job `22726386` (8 nodes, 256 pipelines, 2026-10-08). Inventory of 13 run dirs, 2026-10-08:
`22669434`, `22670942`, `22675825`, `22684833`, `22692267`, `22692293`, `22701168`, `22714785`, `22714866`,
`22716150`, `22717753`, `22718758`, `22726386`. Archived per job at `<hdd work dir>/impress_run_archive/`.

## Why

`22726386` lost 174 of its 234 failed tasks to `OSError: [Errno 122] Disk quota exceeded` between 03:36 and 03:39.
The limit was the `<allocation A>` project's **inode** quota, which `/work/nvme` and `/work/hdd` share
(about 2.77M files against a 2.55M soft and 2.805M hard limit). The run dirs alone held about 1.1M inodes.

What a run writes (sizes are apparent bytes):

| Job | Shape | Files | Bytes | mpnn `packed/` | mpnn `backbones/` |
|---|---|---|---|---|---|
| `22701168` | 8 nodes, 32 pipelines, 4 h | 383k | 20.3 GB | 11.6 GB | 6.5 GB |
| `22726386` | 8 nodes, 256 pipelines, died at ~40 min | 227k | 12.5 GB | 7.0 GB | 3.9 GB |
| `22718758` | 1 node, 32 pipelines, 1 h | 59k | 3.2 GB | 1.8 GB | 1.0 GB |
| `22670942` | 2 nodes, 8 pipelines, 1 h | 21k | 1.1 GB | 0.65 GB | 0.37 GB |

About 90% of the bytes and most of the files are LigandMPNN's per-candidate PDBs. In `22670942`, `packed/` and
`backbones/` each held 8,628 files from 337 mpnn tasks, about 26 per task each. But
`SmallMoleculeBindingPipeline` reads exactly one of them afterwards:
`self.state['best_packed_pdb'] = f"{out_dir}/packed/binder_packed_{best_id}_1.pdb"` (`small_molecule_binding.py`, mpnn
selection). The `seqs/*.fa` files (2 MB in total) hold every candidate's sequence and confidences.

## Items

### 18 — Keep only the selected mpnn candidate's PDBs
After the selection loop picks `best_id`, delete the other `packed/binder_packed_*_*.pdb` and
`backbones/*.pdb` in that task's `out_dir`. Keep `seqs/` intact, since it records every candidate.
Put this behind a flag (`keep_all_mpnn_pdbs`, default `False`) so a debugging run can keep everything.
Expected effect: about −25 files per mpnn task, and roughly −85% of a run's bytes.
**Test:** a 1-node run, then count `find logs/<job> -type f`. Packmin and fastrelax must still read `best_packed_pdb`.

### 19 — Pack the job's work dir when the job ends
At the end of `delta_gpu_run.sh`, after the runner has exited (on success or failure), run
`tar -I 'pigz -p 8' -cf ${IMPRESS_WORK_DIR}.tar.gz -C $(dirname $IMPRESS_WORK_DIR) $(basename $IMPRESS_WORK_DIR)`.
Then compare the archive's file count with `find`, and only then remove the dir. Skip this when
`IMPRESS_KEEP_WORK_DIR=1`. For scale, packing `22701168` (383k files) took about 30 min on a login node with
pigz -p 8, and the job was I/O-bound. Inside the allocation it is faster, but it spends GPU-node time, so
consider using `--signal` to start it before the wall limit.

### 20 — Exit when every pipeline has failed
After its last pipeline failed at about 03:39, `22726386` held 8 nodes until the 06:59 `TIMEOUT` (about 27
node-hours). It never wrote `runner_status`, so the runner did not return. Two candidate causes:
- the manager keeps waiting after the last pipeline fails;
- the Dragon teardown hangs (BACKLOG 2).

Fix: when the live-pipeline count reaches 0, the manager returns. The runner then writes `runner_status`
(`failed: all N pipelines failed`) and calls `flow.shutdown()` under the BACKLOG 2 watchdog.
**Test:** a mock run (`mock.py`) whose every pipeline raises must exit in well under a minute.

### 21 — Make each job dir self-contained
Today these land in the submit dir, not in `IMPRESS_WORK_DIR`:
- `#SBATCH --output=impress_%j.out`;
- asyncflow's `asyncflow.session.<id>/` (per-task stdout/stderr, 16k files and 427 MB for `22726386`);
- `ddict_orc_*`.

So a job's evidence is split across three places, and stray session dirs pile up (12 in one checkout).
Point all three into `${IMPRESS_WORK_DIR}`: `--output` via a wrapper or `-o` at submit; the session dir via
asyncflow's working-directory setting or by `cd ${IMPRESS_WORK_DIR}` before launch. Item 19 then packs one directory.

## Order
18 first: it removes most of the footprint, and the rerun of `22726386` depends on it.
Then 20 (wasted allocation), then 21, then 19 (it is simpler once 21 has landed).
