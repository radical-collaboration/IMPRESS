# Foldseek

**One-line identity.** GPU-capable structural search and clustering engine that encodes protein structures into a "3Di" structural alphabet and searches them at sequence-search speed — the agent's novelty/precedent check for a newly generated backbone.

## Identity
- **Version / release examined:** refcode HEAD at commit `463739e` (2026-09-09); `git describe` in the refcode resolves to `10-941cd33-385-g463739e0` (submodule tag history is noisy — treat the commit hash as ground truth). `project(foldseek C CXX)` in `CMakeLists.txt` line 8.
- **Provenance:** Steinegger Lab (Seoul National University) / Söding Lab, GPLv3 (`LICENSE.md` — GNU GPL v3, 2007). Refcode path: `<workspace>/impress-a-refcodes/tools/foldseek/`. Bundles MMseqs2 as a vendored library at `tools/foldseek/lib/mmseqs` (not a live git submodule in this checkout — `.gitmodules` lists `lib/mmseqs/util/regression` and the ProstT5 ggml-kompute backend as true submodules, but `lib/mmseqs` itself is embedded source).
- **Maturity:** production / active research. Actively developed (recent commits add LoL-align, Foldseek-Multimer interface search, StrucTTY terminal viewer). Three Nature-family papers (2023 Nat. Biotechnol., 2023 Nature, 2025 Nat. Methods) plus a Nov 2025 LoL-align preprint.

## Scientific role
Foldseek answers "has a structure like this been seen before?" — a **search** stage tool, not a generative or scoring one. It is the precedent/novelty check that sits downstream of any backbone generator (RFdiffusion3) or upstream of any design campaign (has this fold already been solved / does AFDB already contain something near-identical?). Applicable across all four in-scope problem classes as a due-diligence and dataset-mining step — it does not discriminate stability, binder, enzyme, or small-molecule work; it operates purely on backbone/complex geometry (and, via ProstT5, on sequence alone).

Concretely, in an autonomous design loop it is used to:
1. Query a designed backbone against PDB/AFDB to flag near-duplicates of known structures (novelty gate before committing GPU budget to downstream folding/MPNN).
2. Query a designed backbone against clustered AFDB to find structural analogs that may carry functional annotations transferable to the design (motif/pocket precedent).
3. Cluster large batches of generated designs to deduplicate before expensive scoring.
4. As a multimer tool (`easy-multimersearch`), check a designed complex against known complexes for interface precedent.

Pipeline stage(s) occupied: **search / analyze**.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI only (binary `foldseek`, no documented stable Python API in this refcode). Core entrypoints, quoted from `README.md`:
  - `foldseek easy-search example/d1asha_ example/ aln tmpFolder` (README.md:117)
  - `foldseek createdb example/ targetDB` / `foldseek createindex targetDB tmp` (README.md:206-207)
  - `foldseek easy-cluster example/ res tmp -c 0.9` (README.md:240)
  - `foldseek easy-multimersearch example/1tim.pdb.gz example/8tim.pdb.gz result tmpFolder` (README.md:302)
  - `foldseek easy-interfacesearch example example result tmpFolder` (README.md:406)
  - GPU search: `foldseek easy-search example/d1asha_ example/ aln tmp --gpu 1 --prefilter-mode 1` (README.md:430)
- **Inputs:** PDB/mmCIF structures (flat or gzipped), a pre-built `createdb` target database/folder, or raw FASTA sequence (converted to the 3Di alphabet on the fly via the bundled ProstT5 protein language model when no structure is available — `foldseek createdb db.fasta db --prostt5-model weights`, README.md:216).
- **Outputs:** default tab-separated alignment table (`query,target,fident,alnlen,mismatch,gapopen,qstart,qend,tstart,tend,evalue,bits`), customizable via `--format-output` to add `alntmscore`, `qtmscore`, `ttmscore`, `u`/`t` (rotation/translation), `lddt`/`lddtfull`, `prob` (README.md:120-137). Also supports `--format-mode 5` (Foldseek-specific: superposed Cα-only PDB files, one per hit) and `--format-mode 3` (interactive HTML, mirrors the public webserver) (README.md:142-150).
- **A concrete example**, from the repo's own README (README.md:117, using files that ship in `example/`):
  ```
  foldseek easy-search example/d1asha_ example/ aln tmpFolder
  ```

## Compute pattern
- **Pattern:** P2 (CPU-parallel fan-out, in-job) primary / P1 (GPU-node-local) secondary when `--gpu 1` is used. Rule 2 of the taxonomy applies: default execution is embarrassingly-parallel CPU threading over a search/cluster job; GPU only accelerates the ungapped prefilter stage (`--prefilter-mode 1`), so classify by the dominant cost (a search is still I/O- and CPU-bound at the alignment/output stage even with GPU prefilter).
- **GPU vendor portability:** **CUDA-only.** Evidence: `CMakeLists.txt` line 12, `set(ENABLE_CUDA 0 CACHE BOOL "Enable CUDA")`; lines 105-109 set `GGML_CUDA ON` etc. when `ENABLE_CUDA` is true. The precompiled GPU binary requires "an NVIDIA driver >=525.60.13" and "NVIDIA GPU of the Ampere generation or newer for full speed" (README.md:80-92). No HIP or SYCL backend exists in this codebase — **will not GPU-accelerate on Frontier or Aurora**; runs CPU-only there.
- **State model:** stateless (each search/cluster invocation is a fresh batch job over static input databases; no checkpoint/resume mid-search).
- **Data locality:** shared-FS required for the target database (`createdb`/`createindex` output must be visible to all threads/nodes running the job); query inputs can be streamed in.
- **Staging burden:** sequence/structure DB. See "Cost per unit of work" — PDB100 (clustered PDB) needs ~2 GB RAM; full AFDB50 (clustered AlphaFoldDB/UniProt50, v4) needs ~191 GB RAM to hold in memory (per Foldseek's own memory-requirements table and public AFDB-cluster documentation). Formula given in README.md:98: `(6 bytes Cα + 1 3Di byte + 1 AA byte) * (database residues)`.
- **Container availability:** official (`Dockerfile` present at `tools/foldseek/Dockerfile`); also official static Linux AVX2/ARM64/GPU tarballs and a bioconda package (README.md:74-87).

## Deployment on DOE & ACCESS
- **Polaris / Delta / Bridges-2 / Expanse (NVIDIA CUDA):** full functionality including `--gpu 1` prefilter acceleration, subject to Ampere-or-newer GPU (Polaris A100 ✓, Delta A100/A40 ✓, Bridges-2 v100/A100 — V100 nodes get reduced-speed Turing-class support per README caveat, Expanse A100 ✓). Build with `ENABLE_CUDA=1` or use the official `foldseek-linux-gpu.tar.gz` tarball; a container build is also viable via the shipped `Dockerfile`.
- **Frontier (AMD/HIP):** CPU-only. No HIP backend exists in `CMakeLists.txt`; do not attempt `ENABLE_CUDA` there. AVX2 static build or Apptainer image of the CPU Docker build is the deployment path. Loses the GPU prefilter speedup entirely (README.md's own benchmark: "4090 GPU is four times faster than a 64-core CPU" for prefiltering — Frontier falls back to the 64-core-CPU-class number).
- **Aurora (Intel/SYCL-XPU):** CPU-only, same reasoning as Frontier — no SYCL/XPU backend. The ProstT5-based FASTA-to-3Di conversion path also only accelerates via CUDA (`--gpu 1`, README.md:219-226), so on Aurora that step is CPU-bound as well (README states it is "400-4000x" faster than folding regardless, so this is a minor loss).
- **Deployment mechanism:** Apptainer/Singularity from the official Dockerfile is the cleanest path on all leadership machines; conda (`conda install -c conda-forge -c bioconda foldseek`) works for quick ACCESS-side testing but the bioconda/precompiled GPU binaries explicitly will not run on pre-Ampere GPUs (README.md:92). No license gate — GPLv3, fully open.

## Agentic surface
- **Native MCP:** community / unverified. A community server "foldseek-mcp" exists (glama.ai/mcp/servers/AltriaPendragon49/foldseek-mcp) advertising "protein structure and sequence searches using FoldSeek, with support for multiple databases, automatic model downloads, and structured job management" — this is a third-party wrapper, not maintained by the Steinegger Lab, and its correctness/maintenance status could not be verified. Treat as unverified starting point, not a dependency. No official MCP server is published by the Foldseek team; the tool is CLI-native and simple enough to wrap directly.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `-s` | float | 4.0 (fast) – 9.5 (sensitive) | 9.5 | Speed vs. sensitivity of the prefilter |
| `-e` | float (E-value) | 1e-5 – 10 | 0.001 | Lower = fewer, more confident hits; higher = casts a wider precedent net |
| `-c` | float (coverage fraction) | 0.0 – 1.0 | 0.0 | Higher = more global-alignment-like matches, filters partial-domain hits |
| `--alignment-type` | enum {0,1,2,3} | — | 2 (3Di+AA local) | 1 = TMalign global (slow, gives TM-score-sorted output); 3 = LoLalign (novel, sensitive, slow) |
| `--gpu` | bool | 0/1 | 0 | Enables GPU prefilter (CUDA only); ignores `-s` |
| `--cluster-search` | enum {0,1} | — | 0 | 1 = align+report all cluster members, not just representatives (AFDB50/CATH50) |
| `--max-seqs` | int | 300 – 10000 | 1000 | More prefilter hits handed to alignment = more sensitivity, more cost |

- **Parameters that must NOT be agent-varied:** `--format-mode 5` (superposed-PDB output) generates one file **per pairwise alignment** — safe only for small, agent-bounded hit counts; letting the agent point this at a full-database search risks filesystem blowup. `--sort-by-structure-bits` (memory/ranking correctness trade — README explicitly says disabling it "alters hit rankings and final scores," not something to toggle mid-campaign for comparability). Database identity (`targetDB` path) should be pinned per campaign, not agent-swapped mid-run, or novelty comparisons become non-reproducible across iterations.

## Failure modes & what the agent must check
- **Loud failure:** non-zero exit on malformed PDB/mmCIF input, missing `createdb` index files, or requesting `--gpu 1` on a build without CUDA support (falls back or errors depending on build — must be tested per-platform, since the CPU-only Frontier/Aurora builds will reject `--gpu 1` outright or silently ignore it depending on version; verify per-container).
- **Silent bad output:** a search returning **zero hits** is not itself an error — the agent must distinguish "genuinely novel structure" from "database wasn't staged/indexed correctly" by running a positive-control query (a known PDB entry) against the same target DB before trusting a null result on a design. Overly permissive `-e`/`-c` settings can also produce spurious low-quality hits that look like precedent but are alignment-length artifacts — check `alntmscore`/`prob` fields, not just E-value, before treating a hit as a genuine structural match.
- **Post-hoc check:** re-run the top hit through `foldseek aln2tmscore` (README.md:456-460) or request `alntmscore` directly in `--format-output` to get a length-normalized TM-score alongside the E-value; an E-value can be significant on a short, spuriously-aligned fragment while the TM-score reveals it is not a real fold match.

## Cost per unit of work
- `easy-search` of one query backbone against PDB100 (343,785 structures): seconds to low tens-of-seconds on CPU with default `-s 9.5`; sub-second prefilter with `--gpu 1` on Ampere+ (per README's 4090-vs-64-core 4x prefilter benchmark). Single node, no persistent GPU hold needed for CPU path.
- `easy-search` against full AFDB50-clustered (~191 GB resident): requires a high-memory CPU node or a node with sufficient RAM to hold the index; not checkpointable mid-search but each invocation completes in minutes, so restart cost on preemption is low.
- `easy-cluster` scales with input size × `-c` chosen; embarrassingly parallel across CPU cores (P2 by definition), no MPI rank layout needed.
- Not checkpointable (stateless single-shot jobs), but individual jobs are short enough (seconds-minutes) that this is not a meaningful liability.

## Verdict
**Core.** Foldseek is the only practical way to answer "has this backbone been seen before" and "what does the known universe of structures near this fold look like" at the speed an autonomous loop needs — alternatives (manual PDB browsing, full TM-align all-vs-all) do not scale. Its CPU-only fallback on Frontier/Aurora is a real cost but not a blocker: search jobs are P2/short-lived, and the GPU path is a pure accelerant, not a requirement for correctness. The vendored MMseqs2 (covered separately in `mmseqs2.md`) makes this refcode a two-for-one: Foldseek for structural search, MMseqs2 (same binary tree) for the sequence-search and MSA-generation role.

## Sources
- Refcode: `<workspace>/impress-a-refcodes/tools/foldseek/README.md` (quoted throughout, lines cited inline)
- Refcode: `<workspace>/impress-a-refcodes/tools/foldseek/CMakeLists.txt` (ENABLE_CUDA, lines 8-17, 105-109)
- Refcode: `<workspace>/impress-a-refcodes/tools/foldseek/LICENSE.md` (GPLv3)
- Refcode: `<workspace>/impress-a-refcodes/tools/foldseek/Dockerfile` (official container)
- Foldseek GitHub: https://github.com/steineggerlab/foldseek
- van Kempen et al., "Fast and accurate protein structure search with Foldseek," Nat. Biotechnol. 2023, https://www.nature.com/articles/s41587-023-01773-0
- Barrio-Hernandez et al., "Clustering predicted structures at the scale of the known protein universe," Nature 2023, https://www.nature.com/articles/s41586-023-06510-w (source for AFDB50 clustering scale — inferred/cross-referenced, not read verbatim from Foldseek README)
- Kim et al., "Rapid and sensitive protein complex alignment with Foldseek-Multimer," Nat. Methods 2025, https://www.nature.com/articles/s41592-025-02593-7
- PDB100/AFDB50 memory figures: https://github.com/steineggerlab/foldseek/wiki and https://cluster.foldseek.com/ (web-searched, not verified against a primary spec doc — flagged as inferred)
- Community MCP (unverified): https://glama.ai/mcp/servers/AltriaPendragon49/foldseek-mcp
