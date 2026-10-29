# MMseqs2

**One-line identity.** Ultra-fast sequence search and clustering suite that is the MSA-generation engine bundled inside Foldseek and the workhorse behind ColabFold's speedup over the original AlphaFold2 pipeline.

## Identity
- **Version / release examined:** vendored copy at `impress-a-refcodes/tools/foldseek/lib/mmseqs`, same commit snapshot as the foldseek refcode (`463739e`, 2026-09-09). `git describe` inside that subtree resolves noisily to the parent foldseek tag history because it is embedded source, not a live submodule checkout in this repo (`.gitmodules` in `tools/foldseek/` does not list `lib/mmseqs` itself as a submodule).
- **Provenance:** Söding Lab / Steinegger Lab, GPLv3 (same license family as Foldseek — `README.md` header identifies it as "MMseqs2: ultra fast and sensitive sequence search and clustering suite"). Upstream canonical repo: https://github.com/soedinglab/MMseqs2. Refcode path: `<workspace>/impress-a-refcodes/tools/foldseek/lib/mmseqs/`.
- **Maturity:** production. It is the search/clustering backbone for ColabFold, MMseqs2-GPU, and Foldseek itself; actively maintained with a 2024/2025 GPU-acceleration paper (Kallenborn et al., Nat. Methods 2025).

## Scientific role
MMseqs2 does two jobs relevant to this cluster, both in the **search** and **generate-input** stages rather than design itself:
1. **Sequence search / clustering** — fast homolog search and redundancy-reduction over protein sequence sets, the sequence-space analog of what Foldseek does for structure space. Used for deduplicating design libraries, mining sequence-level precedent, and taxonomy assignment.
2. **MSA generation for structure prediction** — MMseqs2's `search`/`easy-search` machinery, run either locally against staged databases or via the public ColabFold MSA server, is what ColabFold uses in place of AlphaFold2's original jackhmmer+HHblits pipeline to build the multiple sequence alignments AlphaFold2's Evoformer needs. This directly gates every folding step in the self-consistency loop (see `us-align.md` and `hmmer-hhsuite.md`): RFD3 backbone → MPNN sequence → **MSA generation (MMseqs2)** → AF2/ColabFold structure prediction → TM-align/RMSD comparison back to the design.

Applicable across all four in-scope problem classes since MSA generation is a universal precursor to any AlphaFold2-family folding call. Pipeline stage(s): **search / generate-input (MSA) / analyze (clustering)**.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI (binary `mmseqs`). Real argv from the vendored `README.md`:
  - Clustering: `mmseqs easy-cluster examples/DB.fasta clusterRes tmp --min-seq-id 0.5 -c 0.8 --cov-mode 1` (README.md:73)
  - Linear-time clustering for huge datasets: `mmseqs easy-linclust examples/DB.fasta clusterRes tmp` (README.md:77)
  - Search: `mmseqs easy-search examples/QUERY.fasta examples/DB.fasta alnRes.m8 tmp` (README.md:87)
  - Pre-indexed search: `mmseqs createdb examples/DB.fasta targetDB` / `mmseqs createindex targetDB tmp` / `mmseqs easy-search examples/QUERY.fasta targetDB alnRes.m8 tmp` (README.md:92-94)
  - GPU search: `mmseqs createdb …; mmseqs makepaddedseqdb targetDB targetDB_padded; mmseqs easy-search examples/QUERY.fasta targetDB_padded alnRes.m8 tmp --gpu 1` (README.md:98-100)
  - Database download: `mmseqs databases UniProtKB/Swiss-Prot swissprot tmp` (README.md:104)
  - Taxonomy: `mmseqs createtaxdb targetDB tmp; mmseqs createindex targetDB tmp; mmseqs easy-taxonomy examples/QUERY.fasta targetDB alnRes tmp` (README.md:116-119)
  - MPI multi-node: `RUNNER="mpirun -pernode -np 42" mmseqs search queryDB targetDB resultDB tmp` (README.md:152), requires a build with `-DHAVE_MPI=1`.
- **Inputs:** FASTA/FASTQ sequence files, or pre-built MMseqs2 database format (`createdb` output).
- **Outputs:** default tab-separated `.m8` alignment table; customizable via `--format-output`, e.g. `--format-output "query,target,qaln,taln"` (README.md:109). Note the README's own correctness caveat: `easy-search` reports estimated sequence identity by default; use `--alignment-mode 3` or `-a` for exact identity (README.md:111).
- **A concrete example**, from the repo's own README (README.md:87):
  ```
  mmseqs easy-search examples/QUERY.fasta examples/DB.fasta alnRes.m8 tmp
  ```

## Compute pattern
- **Pattern:** P2 (CPU-parallel fan-out, in-job) primary / P1 (GPU-node-local) secondary for the GPU-accelerated prefilter path. Same reasoning as Foldseek (which vendors this exact code): the dominant cost for most jobs is multi-threaded CPU alignment; GPU only accelerates prefiltering. Secondary pattern P3 (MPI multi-node) exists when built with `-DHAVE_MPI=1` and invoked via `RUNNER="mpirun …"` for distributing database splits across servers — this is a genuine dual/triple-mode tool per taxonomy rule 2, but P2 is overwhelmingly the default deployment.
- **GPU vendor portability:** **CUDA-only**, same codebase/build system as Foldseek (`ENABLE_CUDA` in the shared CMake infrastructure). The Kallenborn et al. 2024/2025 MMseqs2-GPU paper benchmarks exclusively on NVIDIA hardware. No HIP/SYCL path exists — CPU-only on Frontier and Aurora.
- **State model:** stateless (single-shot batch jobs over static databases; no mid-search checkpoint).
- **Data locality:** shared-FS required for staged target databases (this is the crux of the "local DB vs. remote API" decision below); MPI mode explicitly requires the databases and temp folder to be shared across nodes (README.md:150, "through NFS").
- **Staging burden:** sequence DB, potentially large — see Cost section. This is the parameter that full outbound HTTPS egress changes: for ColabFold-style MSA generation, an agent can call the public `api.colabfold.com` MSA server (P5, see `bio-databases.md`) instead of staging UniRef30/BFD/ColabFoldDB locally, at the cost of shared-resource rate limits.
- **Container availability:** official (ColabFold's own container images bundle MMseqs2 for local search; MMseqs2 also has official Docker images independent of ColabFold, and bioconda: `conda install -c bioconda mmseqs2`).

## Deployment on DOE & ACCESS
- **Polaris / Delta / Bridges-2 / Expanse (NVIDIA CUDA):** full GPU-prefilter path available; MMseqs2-GPU benchmarks (Kallenborn et al.) target exactly this hardware class. Local database staging is the natural choice here if egress-avoidance or reproducibility (pinned DB version) matters more than saving disk.
- **Frontier (AMD/HIP):** CPU-only, same caveat as Foldseek — no HIP backend. AVX2 CPU build via module or Apptainer.
- **Aurora (Intel/SYCL-XPU):** CPU-only, no SYCL backend.
- **Deployment mechanism:** module/conda on ACCESS systems is common (bioconda package); Apptainer/Singularity is the safer path on DOE leadership machines given no official module is guaranteed. No license gate (GPLv3).
- **Local-DB vs. remote-API decision, concretely:** Given full compute-node HTTPS egress (per platform assumptions), routine single-sequence or modest-batch MSA generation should default to the public ColabFold MSA server (P5) rather than staging UniRef30+ColabFoldDB locally — this avoids hundreds of GB of one-time download/index cost per site. Local staging only earns its keep for (a) large-batch campaigns that would otherwise abuse the shared public server's fair-use policy, or (b) sites needing MSA reproducibility independent of an external service's uptime/version drift. See `bio-databases.md` for the ColabFold MSA server's own rate-limit posture, and the DB-size table below for what staging costs.

## Agentic surface
- **Native MCP:** no. No MCP server specific to MMseqs2 was found in a hard search. (ColabFold, which is built on top of MMseqs2, likewise has no MCP server — see `bio-databases.md`.) The CLI is simple and scriptable enough that a thin custom wrapper is the practical path if MCP-style tool exposure is wanted.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `-s` | float | 1.0 (very fast) – 7.0 (very sensitive) | 5.7 | README: "very fast search would use -s 1.0, very sensitive up to -s 7.0" (README.md:107) |
| `--min-seq-id` | float | 0.3 – 0.9 | 0.0 (search) / job-specific (cluster) | Clustering stringency; higher = tighter, smaller clusters |
| `-c` / `--cov-mode` | float / enum | 0.5 – 0.9 / {0,1,2} | 0.0 / 0 | Alignment coverage requirement; controls global- vs local-like matching |
| `--num-iterations` | int | 1 – 4 | 1 | PSI-BLAST-style iterative profile search; more iterations find more distant hits at higher cost |
| `--gpu` | bool | 0/1 | 0 | GPU-accelerated prefilter (CUDA only) |
| `--split-memory-limit` | size | node-RAM-dependent | auto | Controls DB-splitting for memory-constrained nodes; increases runtime slightly when split |

- **Parameters that must NOT be agent-varied:** `--alignment-mode`/`-a` toggling mid-campaign — changes whether sequence identity is estimated or exact, breaking comparability of identity-based filtering across a campaign's own history. Target database path/version must be pinned per campaign for the same reason novelty/precedent comparisons need a fixed reference (agent should not silently upgrade a staged UniRef/ColabFoldDB mid-loop).

## Failure modes & what the agent must check
- **Loud failure:** non-zero exit on missing/corrupt database files, insufficient disk in `tmp`, or malformed FASTA.
- **Silent bad output:** the estimated-vs-exact sequence identity distinction (README.md:111) is a classic silent-correctness trap — an agent filtering candidate hits by `pident` under default `easy-search` settings is filtering on an estimate, not ground truth, unless `-a`/`--alignment-mode 3` was set. A search returning few/no hits against a database that silently failed to index (`createindex` didn't complete) looks identical to "genuinely novel/rare sequence" — same mitigation as Foldseek: run a known-positive control query first.
- **Post-hoc check:** re-run a sample of top hits with `-a` to get exact identity and confirm filtering thresholds were applied to the right numbers; validate DB staging by checking `createdb`/`createindex` exit codes and expected on-disk size against the known reference size (see table below) before trusting a search's completeness.

## Cost per unit of work
- `easy-search` of a single query against a modest custom DB (thousands of sequences): seconds, single node, CPU threads only.
- `easy-search` against staged UniRef30 (2021_03, ~52.5 GB download / ~206 GB uncompressed) or BFD/MGnify (~271.6 GB download / ~1.8 TB uncompressed, AlphaFold2 full-DB figures): minutes per query with sufficient RAM/disk locality; GPU prefilter on Ampere+ cuts this meaningfully (Kallenborn et al.: MMseqs2-GPU is ~1.65x faster than MMseqs2-CPU and the full ColabFold-GPU pipeline is ~31.8x faster than original AlphaFold2's jackhmmer-based MSA step for CASP14-scale targets).
- Database staging (one-time): UniRef30 ~52.5 GB download; BFD/MGnify combination ~271.6 GB download (~1.8+0.12 TB uncompressed); ColabFoldDB is the metagenomic-heavy alternative bundle sized similarly to BFD in role. This is the cost the public ColabFold MSA server (P5) lets a modest-throughput agent skip entirely.
- Not checkpointable; jobs are short enough (minutes) relative to typical walltimes that this is a minor concern. MPI mode (P3, when used) requires a fixed rank/database-split layout and cannot be resized mid-run, per the general P3 scheduling implication in the taxonomy.

## Verdict
**Core.** MMseqs2 is unavoidable as the search-and-MSA engine underneath both Foldseek (already Core) and ColabFold (used by essentially every folding-prediction step in the self-consistency loop this project depends on). Its CPU-only status on Frontier/Aurora is a real but bounded cost — MSA generation is P2, not the dominant compute of a design campaign, and full egress means the agent can often route around local staging entirely by hitting the public ColabFold MSA server for modest workloads. Recommend: default to remote MSA server for interactive/low-throughput iteration; stage UniRef30 + ColabFoldDB locally only for large-batch campaigns on GPU-rich NVIDIA allocations (Polaris/Delta/Bridges-2/Expanse) where the fair-use ceiling of the public server would otherwise bind.

## Sources
- Refcode: `<workspace>/impress-a-refcodes/tools/foldseek/lib/mmseqs/README.md` (quoted throughout, lines cited inline)
- Refcode: `<workspace>/impress-a-refcodes/tools/foldseek/.gitmodules` (submodule structure)
- MMseqs2 GitHub: https://github.com/soedinglab/MMseqs2
- Kallenborn et al., "GPU-accelerated homology search with MMseqs2," Nat. Methods 2025 (bioRxiv 2024.11.13.623350), https://www.nature.com/articles/s41592-025-02819-8 ; https://www.biorxiv.org/content/10.1101/2024.11.13.623350v1
- NVIDIA developer blog, "Boost AlphaFold2 Protein Structure Prediction with GPU-Accelerated MMseqs2," https://developer.nvidia.com/blog/boost-alphafold2-protein-structure-prediction-with-gpu-accelerated-mmseqs2/ — source for the 31.8x/1.65x speed figures (web-searched, not independently re-verified against the raw benchmark data)
- Mirdita et al., "ColabFold: making protein folding accessible to all," Nat. Methods 2022, https://www.nature.com/articles/s41592-022-01488-1
- AlphaFold2 database size figures (BFD ~271.6 GB download/~1.8 TB uncompressed, UniRef30 ~52.5 GB/~206 GB): google-deepmind/alphafold README, https://github.com/google-deepmind/alphafold/blob/main/README.md (web-searched, flagged as inferred — cross-check against current AlphaFold README before using in a staging budget)
