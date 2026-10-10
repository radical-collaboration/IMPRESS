# HMMER & HH-suite

**One-line identity.** HMMER (jackhmmer/hmmsearch) and HH-suite (hhblits/hhsearch) are the profile-HMM-based, maximum-sensitivity homology search tools that formed AlphaFold2's original MSA pipeline — now largely superseded in this project's context by MMseqs2/ColabFold, except where remote-homolog sensitivity is decisive.

## Identity
- **Version / release examined:** no refcode present for either tool in `impress-a-refcodes/tools/` (confirmed: directory listing is `agent-rosetta, boltz, ChemGraph, foldseek, foundry, gromacs, IMPRESS, lammps, rdkit, rosetta` — neither HMMER nor HH-suite is vendored). This brief is therefore sourced entirely from upstream documentation, per the assignment's method note.
- **Provenance:** HMMER — Eddy/Rivas Lab, upstream `EddyRivasLab/hmmer` (BSD-3-clause-style "HMMER license," open source). HH-suite — Söding Lab, upstream `soedinglab/hh-suite` (GPLv3-family, same lab that produces MMseqs2/Foldseek).
- **Maturity:** both production / mature. HMMER3 is the long-standing standard for profile-HMM search (used in Pfam construction); HH-suite3 (2019 paper) is the current stable line.

## Scientific role
Both tools build and search **profile-based** representations of sequence space — HMMER via single-query profile HMMs (jackhmmer iterates PSI-BLAST-style; hmmsearch is single-pass), HH-suite via **HMM-HMM** comparison (hhblits/hhsearch represent both query and target as profiles built from MSAs, not just the query side). This dual-profile representation is why HH-suite is considered the more sensitive of the two for remote homology.

Historically, this pair is **AlphaFold2's canonical MSA pipeline**: the original AlphaFold2 release uses jackhmmer against UniRef90/MGnify and HHblits against BFD+UniRef30 (and HHsearch/hmmsearch against PDB70/PDB-seqres for template search) to build the input MSA and template set the Evoformer consumes. Pipeline stage: **search / generate-input (MSA)** — same slot in the pipeline that MMseqs2 fills for ColabFold, just with a different sensitivity/speed trade-off. Not specific to any one of the four in-scope problem classes; like MMseqs2, it's a precursor to any AlphaFold2-family structure prediction used in the self-consistency loop.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI only, both tools.
  - `jackhmmer [options] <seqfile> <seqdb>` — iteratively searches query sequence(s) against a target database; seqfile may be `-` (stdin), but seqdb cannot be streamed because jackhmmer needs multiple passes over it. `--tblout`/`--domtblout` give parseable tabular output.
  - `hmmsearch` — single-pass profile-HMM-against-sequence-database search (used for template search against PDB-derived sequence sets in the AF2 pipeline).
  - `hhblits -i <input-file> -o <result-file> -oa3m <result-alignment> -d <database-basename>` — iterative profile-profile search, typically run to build an MSA (a3m format) against UniRef30/BFD.
  - `hhsearch -cpu 4 -i out_hhblits.a3m -d pdb70/pdb70 -o hras_hhpred.hhr -oa3m hras_hhpred.a3m -p 20 -Z 250 -loc -z 1 -b 1 -B 250 -ssm 2 -sc 1 -seq 1 -dbstrlen 10000 -norealign -maxres 32000` — real-world hhsearch invocation for template search against a formatted PDB70 database.
- **Inputs:** FASTA sequence (jackhmmer/hmmsearch), or an MSA/HMM/single sequence (hhblits — can bootstrap from any of the three), against a pre-formatted flat-file or HH-suite-format database.
- **Outputs:** jackhmmer/hmmsearch: tabular hit tables (`--tblout`) or full text alignments; hhblits/hhsearch: `.hhr` result files and `.a3m` alignment output (the format AlphaFold2's data pipeline consumes directly).
- **A concrete example:** the hhsearch invocation above is drawn from a documented real-world PDB-template-search command (not from a local refcode — flagged as web-sourced, not repo-verified).

## Compute pattern
- **Pattern:** P2 (CPU-parallel fan-out, in-job). Both tool families are multi-threaded CPU search tools with no native GPU acceleration; parallelism is over database chunks/sequences, not MPI rank topology.
- **GPU vendor portability:** CPU-only, n/a for vendor portability. Neither HMMER3 nor HH-suite3 has a GPU code path (as of the versions examined via upstream docs). Runs identically on Frontier, Aurora, and all ACCESS/Polaris CUDA nodes — vendor-neutral precisely because there's no accelerator dependency.
- **State model:** stateless (batch search jobs, no mid-run checkpoint).
- **Data locality:** shared-FS required for the target databases.
- **Staging burden:** sequence-structure DB — large. This is the central cost driver; see Cost section for BFD/UniRef90/UniRef30/MGnify sizes.
- **Container availability:** community (both ship in the standard AlphaFold2 Docker image and in bioconda channels: `bioconda::hmmer`, `bioconda::hhsuite`); no official DOE/ACCESS-blessed container found, but both are simple enough that a build-required path (module load or conda) is low-risk.

## Deployment on DOE & ACCESS
CPU-only status means this pair is the *one* tool in this cluster with zero platform risk from GPU vendor lock-in — it runs identically on Frontier (HIP), Aurora (SYCL-XPU), Polaris (CUDA), and all three ACCESS NVIDIA systems, because it never touches a GPU. The only deployment concern is the database staging burden (below), which is platform-agnostic disk/filesystem cost, not compute-architecture cost. Module or conda install is sufficient everywhere; no license gate.

## Agentic surface
- **Native MCP:** no. No MCP server was found for either HMMER or HH-suite in a direct search; both are old, stable CLI tools without an apparent community MCP wrapper at time of writing.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `--incE` / `-E` (HMMER) | float | 1e-10 – 10 | 10 | Inclusion/reporting E-value threshold; sensitivity vs. false-positive rate |
| `-n` (hhblits, iterations) | int | 1 – 3 | 2 | More iterations = more sensitive profile, higher cost |
| `-e` (hhblits/hhsearch E-value) | float | 1e-10 – 1 | 1e-3 | Same trade as HMMER's `-E` |
| `-cpu` | int | node-core-count | 1 | Thread count; pure throughput knob, no correctness effect |

- **Parameters that must NOT be agent-varied:** the target database identity/version (UniRef90, BFD, UniRef30, PDB70) must be pinned per campaign for the same reproducibility reason as MMseqs2/Foldseek — a design's "MSA depth" or "template hit" comparison across iterations is meaningless if the underlying DB silently changed version.

## Failure modes & what the agent must check
- **Loud failure:** non-zero exit on missing database or malformed input FASTA/HMM.
- **Silent bad output:** a shallow or empty MSA (few effective sequences) from either tool feeding into AlphaFold2 is the classic silent failure mode — the folding model will still produce a confident-looking structure, but pLDDT and prediction quality degrade without an explicit MSA-depth flag. The agent must check MSA depth (`Neff`, effective sequence count) before trusting the downstream structure prediction, not just check that the MSA file was produced.
- **Post-hoc check:** count effective sequences (`Neff`) in the output `.a3m`/alignment; compare against the MMseqs2/ColabFold MSA depth for the same query as a sanity cross-check if both pipelines are ever run side-by-side.

## Cost per unit of work
- One jackhmmer search of a single query against UniRef90 (~120 GB MGnify-scale, UniRef90 itself is smaller but still tens of GB): AlphaFold2's own reported profile shows the CPU-based MSA step consuming **83% of total AlphaFold2 runtime** for a typical target — this is the direct quantification of why ColabFold's MMseqs2 swap mattered. Independent benchmarking found ColabFold with MMseqs2-GPU **~23x faster** than AlphaFold2's jackhmmer-based MSA step on CASP14 targets, and MMseqs2-CPU alone already **40-60x faster** than the HMMER/HH-suite combination for equivalent search depth.
- Full AlphaFold2 database bundle (BFD + MGnify + UniRef30 + PDB mmCIF + PDB70, download sizes): BFD ~271.6 GB download (~1.8 TB uncompressed), MGnify ~67 GB download (~120 GB uncompressed), UniRef30 ~52.5 GB download (~206 GB uncompressed), PDB mmCIF ~43 GB, PDB70 ~19.5 GB download (~56 GB uncompressed) — full bundle **~556 GB download / ~2.62 TB uncompressed total**. This staging burden is the same order of magnitude as MMseqs2's ColabFold-DB staging, but the search itself is far slower per query.
- Single node, CPU-only, not checkpointable, but individual searches complete in minutes-to-an-hour depending on database and sensitivity settings.

## Verdict
**Defer.** Given MMseqs2/ColabFold is documented at 40-60x (CPU) to ~23x (GPU-vs-jackhmmer) faster for essentially the same downstream AlphaFold2 accuracy (both papers report comparable TM-score, ~0.70 ± 0.05, across methods on CASP14), there is no throughput or accuracy case for running the slower jackhmmer/HHblits pipeline as the default MSA path in an autonomous, iteration-heavy design loop. What would change this: **sensitivity-critical remote-homolog detection** — HH-suite's dual-profile (HMM-vs-HMM) representation genuinely outperforms MMseqs2's k-mer-based prefilter on distant/remote homologs, which matters specifically for (a) deep functional/taxonomic annotation of a novel enzyme active site where no close structural precedent exists, or (b) template search in unusual folds where MMseqs2's faster-but-shallower search misses a real distant template MMseqs2 would not otherwise find. If Part A's enzyme-design or de novo scaffold work later needs that specific sensitivity, promote hhblits/hhsearch to Recommended as a secondary, occasional-use tool layered on top of the MMseqs2/ColabFold default — not as a replacement for it.

## Sources
- No refcode present (verified absence via `ls <workspace>/impress-a-refcodes/tools/`)
- HMMER upstream: https://github.com/EddyRivasLab/hmmer ; jackhmmer manpage, https://www.mankier.com/1/jackhmmer ; HMMER User's Guide, http://eddylab.org/software/hmmer/Userguide.pdf
- HH-suite upstream: https://github.com/soedinglab/hh-suite ; Steinegger et al., "HH-suite3 for fast remote homology detection and deep protein annotation," BMC Bioinformatics 2019, https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6744700/
- AlphaFold2 original pipeline / database sizes: google-deepmind/alphafold README, https://github.com/google-deepmind/alphafold/blob/main/README.md
- ColabFold speed comparison (40-60x, 23x, TM-score parity): Mirdita et al., "ColabFold: making protein folding accessible to all," Nat. Methods 2022, https://www.nature.com/articles/s41592-022-01488-1 ; https://www.biorxiv.org/content/10.1101/2021.08.15.456425v2.full
- MMseqs2-GPU benchmark context (31.8x vs. AlphaFold2, 1.65x vs. MMseqs2-CPU): Kallenborn et al., Nat. Methods 2025, https://www.nature.com/articles/s41592-025-02819-8 ; NVIDIA blog, https://developer.nvidia.com/blog/boost-alphafold2-protein-structure-prediction-with-gpu-accelerated-mmseqs2/
- All figures in this brief are web-sourced and not cross-verified against a primary benchmark run — flagged as inferred, consistent with the "use WebSearch for everything else" instruction for tools without a local refcode.
