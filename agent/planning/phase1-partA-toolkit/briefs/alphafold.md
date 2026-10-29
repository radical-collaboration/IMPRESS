# AlphaFold family: AF2, AF3, ColabFold

**One-line identity.** Three related-but-distinct tools: AlphaFold2 (permissively-licensed, MSA-based, open weights), AlphaFold3 (access-restricted weights, non-commercial-only, broader biomolecule/ligand coverage), and ColabFold (a community re-engineering of AF2's search+inference pipeline around the fast MMseqs2 MSA server). None of these have a refcode in `impress-a-refcodes/`; all findings below are from upstream sources (WebSearch), not repo inspection — flagged per-claim.

---

## AF2 (AlphaFold2)

### Identity
- **Version / release examined:** `google-deepmind/alphafold`, latest tagged releases around v2.2.0+ series (multimer support added post-v2.1). Not present in refcodes.
- **Provenance:** Google DeepMind. **Code: Apache 2.0. Model parameters: CC BY 4.0** (upgraded from the original CC BY-NC 4.0 non-commercial license — current parameters permit commercial use with attribution). This is the most permissive license in this entire cluster of five tools.
- **Maturity:** production, but effectively superseded by AF3/ColabFold/Boltz for new work; still the reference baseline many benchmarks compare against.

### Scientific role
Monomer and multimer complex structure prediction from MSA + optional templates. Serves stability, de novo binder design (via AF2-Multimer), and enzyme design (fold verification); weak on arbitrary small-molecule ligands (no native ligand-diffusion module — this is AF3/Boltz/RF3/Chai's differentiator).

### Invocation & I/O contract
- CLI: `run_alphafold.py` with FASTA input, `--db_preset={reduced_dbs,full_dbs}`, `--model_preset={monomer,monomer_casp14,monomer_ptm,multimer}`.
- Inputs: FASTA sequence(s) + local genetic databases (see staging below) for MSA/template search (jackhmmer, hhblits, hmmsearch against BFD/UniRef90/MGnify/PDB70/UniProt/PDB seqres).
- Outputs: ranked PDB structures, `ranking_debug.json` (pLDDT/pTM per model), pickled result dicts with PAE (multimer/`_ptm` models only).

### Compute pattern
- **Pattern:** P1 for the GPU inference stage; **P2 (CPU-parallel fan-out)** for the MSA/template search stage, which is CPU-bound (jackhmmer/hhblits) and typically the dominant wall-clock cost for a fresh target. A tool with two very different cost profiles in one binary — classify the MSA-search sub-stage separately if the agent can address it independently (e.g., via a precomputed-MSA cache), otherwise treat the whole `run_alphafold.py` call as P1(primary)/P2(when MSA not cached).
- **GPU vendor portability:** **CUDA-primary (JAX+cuDNN); AMD/HIP has real community and semi-official support, unlike Boltz/RF3.** AF2 uses JAX, and JAX has an official ROCm build (`rocm.docs.amd.com/.../jax/install.html`, JAX ROCm support explicitly lists MI250/gfx90a). LUMI (an AMD MI250X EuroHPC system, architecturally close to Frontier) has an **AMD-maintained** official AlphaFold container (`lumi-supercomputer.github.io/LUMI-EasyBuild-docs/a/AlphaFold/`), and Pawsey Supercomputing Centre documents running AF2 on AMD GPU nodes. This is the strongest AMD/HIP evidence of any tool in this cluster — direct precedent for Frontier. Intel XPU/SYCL: no evidence found; JAX's XPU/SYCL backend maturity is a separate open question not resolved by this search. All of the above is from WebSearch, not independently verified by running AF2 — treat as strong-but-secondhand evidence.
- **State model:** stateless per target.
- **Data locality:** shared-FS required for genetic databases (must be co-located with or fast-mounted to the compute node).
- **Staging burden:** **sequence/structure databases, large.** Full database set ≈2.62 TB on disk (≈415 GB compressed download) across BFD (~1.7 TB disk / 271.6 GB download — dominant cost), UniRef90 (~67 GB disk), MGnify (~238 GB disk), PDB70 (~56 GB disk), UniRef30 (~206 GB disk), UniProt (~105 GB disk), small_bfd (~17 GB disk, reduced-db preset only). Plus model parameter weights (several GB). This is a one-time but substantial pre-staging requirement — the single largest staging burden in this cluster by a wide margin, and the central reason AF2 is a P1(primary)/P4-adjacent tool operationally: the database build/refresh is itself a job that should be scheduled once per site, not per campaign.
- **Container availability:** official DeepMind Docker image; community/site-specific images common at HPC centers (LUMI, Pawsey, TACC, etc., several with AMD-specific builds).

### Deployment on DOE & ACCESS
- Polaris/ACCESS: straightforward, CUDA-native, matches most published deployment guides.
- Frontier: real precedent via LUMI's AMD-maintained container and Pawsey's AMD-GPU AF2 deployment — the most de-risked AMD path of any tool surveyed for this cluster, though the exact container would need porting/validation on Frontier's specific ROCm stack, not assumed identical.
- Aurora: no evidence found either way.
- The dominant deployment cost on **any** platform is the one-time ~2.6 TB genetic-database staging, which must land on fast, shared, site-persistent storage before the agent's first iteration — this is the textbook case the taxonomy's "staging burden" attribute exists to flag.

---

## AF3 (AlphaFold3)

### Identity
- **Version / release examined:** `google-deepmind/alphafold3`, open-sourced Nov 2024 (code + inference pipeline on GitHub; paper in *Nature*). Not present in refcodes.
- **Provenance:** Google DeepMind. **Code: Apache 2.0 (inference pipeline). Model parameters: access-restricted, non-commercial-only**, under the `WEIGHTS_TERMS_OF_USE.md` in the AF3 repo.
- **Maturity:** production/actively maintained by DeepMind, but with a hard access gate that changes its deployability calculus versus every other tool in this cluster.

### What the weights access-restriction means for an autonomous agent
This is the single most consequential fact about AF3 for this project:
- Weights are obtained only via a **manual request form**, reviewed at **Google DeepMind's sole discretion**, with a stated 2-3 business day turnaround — this is a human-in-the-loop gate that cannot be automated or provisioned on-demand by an autonomous agent or a fresh HPC allocation.
- Usage is restricted to **non-commercial organizations** (universities, non-profits, research institutes, educational/journalism/government bodies) and explicitly **excludes** "research on behalf of commercial organizations" — this is an org-level restriction, not a per-user toggle, and it applies to *both the model parameters and their output*, per the `OUTPUT_TERMS_OF_USE.md`.
- Practical consequence for IMPRESS-A: AF3 can only be included if (a) the deploying organization is confirmed non-commercial and DeepMind access has already been granted and staged as weights on the target filesystem well before any autonomous run, and (b) no downstream commercial use of AF3-derived structures/outputs is anticipated. It cannot be treated as a fungible "just pip install it" tool the way AF2/ColabFold/Boltz/Chai-1/RF3 are.

### Scientific role
Broadest input coverage of any tool surveyed: proteins, DNA, RNA, ligands (arbitrary CCD/SMILES), ions, covalent modifications, in one diffusion-based co-folding model — architecturally, RF3 and Boltz-2 are both direct responses to AF3. Serves all four problem classes if access is granted.

### Invocation & I/O contract
- CLI: `run_alphafold.py` (JSON input format, AF3's own JSON schema — the same schema RF3 explicitly modeled its `smiles`/`ccd_code`/`path` component fields on, per RF3's own docs).
- Outputs: CIF structures, `summary_confidences.json` (`ptm`, `iptm`, `ranking_score`, `fraction_disordered`, `has_clash`, `chain_pair_pae_min`), full-resolution PAE.

### Compute pattern
- **Pattern:** P1 (GPU inference) with a P2/local-DB MSA-search stage like AF2 — **AF3's open-source release still requires local genetic databases for MSA/template search**; it does not ship a remote-MSA-server option the way Boltz/ColabFold do. This is an important, easy-to-miss distinction: despite AF3 being the newest of the AF-family tools, its staging burden for MSA is closer to AF2's than to Boltz's.
- **GPU vendor portability:** CUDA-primary (JAX-based, same lineage as AF2). Compute Capability ≥8.0 (Ampere+) required. No AMD/Intel evidence found for AF3 specifically in this search (distinct from AF2, where LUMI/Pawsey precedent exists) — treat as **unproven**, not inferred-from-AF2, since AF3's diffusion module and updated JAX/Triton/haiku stack are not guaranteed to share AF2's ROCm compatibility.
- **State model:** stateless per target.
- **Data locality:** shared-FS required for databases + weights.
- **Staging burden:** databases + weights, both large. Genetic databases (PDB/MGnify/UniProt/UniRef90/NT/RFam/RNACentral/modified BFD): **~252 GB compressed download, ~630 GB unzipped** (smaller than AF2's full set because AF3 dropped some AF2-era DBs) — the AF3 install docs state up to **1 TB disk recommended** including headroom, plus ≥64 GB RAM for the genetic-search stage on long targets. GPU memory: a single A100/H100 80GB handles inputs up to 5,120 tokens.
- **Container availability:** official/community containers exist at multiple HPC centers (BYU, ASU, UAB, TACC, Birmingham BEAR, DIPC — all found in search as site-specific deployment docs), reflecting that the *code* is freely containerizable even though the *weights* are gated; the weights still have to be manually placed by whoever has access.

### Deployment on DOE & ACCESS
Deployable on any CUDA platform (Polaris, ACCESS) **only if** the requesting organization has secured weight access in advance and the non-commercial restriction is compatible with the project's use. Frontier/Aurora: no confirmed non-CUDA path; combined with the access gate, AF3 is the highest-friction tool in this cluster to stand up.

---

## ColabFold

### Identity
- **Version / release examined:** `sokrypton/ColabFold` (and the `YoshitakaMo/localcolabfold` installer for HPC/local use). Not present in refcodes; CLI entrypoint is `colabfold_batch`.
- **Provenance:** Sergey Ovchinnikov / Milot Mirdita et al. Wraps **AF2's own weights** (CC BY 4.0, per above) with a from-scratch MMseqs2-based MSA pipeline. ColabFold's own code license was not independently confirmed with a direct license-file read in this search (search results referenced but did not quote the LICENSE file contents) — commonly cited as MIT in community writeups; mark **unverified, likely MIT**.
- **Maturity:** production, extremely widely used (the reference implementation behind Boltz's `--use_msa_server` and Chai-1's `--use-msa-server`, both of which literally call the same ColabFold MMseqs2 server infrastructure at `api.colabfold.com`).

### Scientific role
Same structural coverage as AF2 (protein monomer/multimer via AF2 weights), but its real contribution to this project is as **the shared remote-MSA-server backend** other tools in this toolkit depend on — ColabFold is as much infrastructure as it is a standalone predictor here.

### Invocation & I/O contract
- CLI: `colabfold_batch input.fasta output_dir [OPTIONS]`, options include `--num-recycle` (default 3, up to 20 documented for multimer), `--num-models {1..5}`, `--num-seeds`, `--stop-at-score`, `--recycle-early-stop-tolerance`, `--num-ensemble`.
- Inputs: FASTA; MSA is generated automatically via the MMseqs2 server (`api.colabfold.com` or a self-hosted instance) rather than local jackhmmer/hhblits.
- Outputs: same shape as AF2 (ranked PDB, pLDDT/pTM, PAE for multimer models).

### Compute pattern
- **Pattern:** P5 (primary) for the MSA stage — a network call to the MMseqs2 server — **P1** for the GPU inference stage. This is the cleanest P5-for-MSA example in the toolkit and the direct precedent that makes Boltz's/Chai's `--use_msa_server` flags trustworthy design choices for this project's full-egress environment.
- **GPU vendor portability:** inherits AF2's JAX/CUDA lineage for the inference half; explicit AMD/ROCm support for ColabFold specifically was **not confirmed** in search (only general "ROCm is a CUDA workaround, largely untested for this tool" commentary) — do not assume it inherits AF2's LUMI/Pawsey precedent without separate validation, since ColabFold pins its own JAX/dependency versions.
- **State model:** stateless per target; MMseqs2 server calls can be retried independently of the GPU stage.
- **Data locality:** self-contained for inference (no local genetic DBs); MMseqs2-GPU search mode exists server-side (GPU-accelerated MSA search, Linux-only per search results) but that is the *server's* concern, not the agent's compute allocation.
- **Staging burden:** **none for MSA** (the entire point of ColabFold in this toolkit) — only AF2 model weights (several GB) need local staging. This is the single biggest practical advantage ColabFold has over raw AF2 for an autonomous agent: it converts a multi-hundred-GB P2 staging problem into a P5 network call.
- **Container availability:** community (`localcolabfold` installer supports Linux/macOS/WSL2); no single official container confirmed.

### Deployment on DOE & ACCESS
Same GPU-vendor caveats as AF2/AF3 (CUDA-primary, AMD unverified for ColabFold specifically). Given full outbound HTTPS on all target platforms (per project assumption), ColabFold's MSA-server dependency is a **non-issue operationally** — the only open question is GPU-side portability of the inference half.

---

## Agentic surface (all three)
- **Native MCP:** **community, unverified-yes**, and notably **database-lookup-only, not inference**. `Augmented-Nature/AlphaFold-MCP-Server` (GitHub: `github.com/augmented-nature/alphafold-mcp-server`) provides tools for querying the **AlphaFold Structure Database** (fetch by UniProt ID, format conversion, confidence analysis) — this is P5 database lookup against precomputed AlphaFold DB structures, **not** a wrapper that runs new AF2/AF3/ColabFold predictions. A second server, `zeinab-sheikhi/mcp-alphafold`, was referenced in search summaries as additionally covering ESM-2/ESMC embeddings and ESMFold structure prediction, but this session could not independently confirm its scope/maintenance status from the search results returned — mark **community/unverified** pending direct inspection of that repo. Neither AF2, AF3, nor ColabFold has a confirmed first-party or well-established MCP server for *running* predictions.
- **Parameters worth exposing for autonomous variation (representative, AF2/ColabFold-family):**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `num_recycle` | int | 3–20 | 3 (up to 20 for multimer) | Accuracy vs. wall-clock, same shape as RF3/Boltz recycling |
| `num_models` | int | 1–5 | 5 | Ensemble diversity/reliability of top pick vs. linear cost |
| `db_preset` (AF2) | enum | `reduced_dbs`/`full_dbs` | `full_dbs` | Reduced DBs cut staging burden and search time at an accuracy cost |
| `model_preset` | enum | `monomer`/`monomer_ptm`/`multimer` | task-dependent | `_ptm`/`multimer` variants are required to get PAE/ipTM at all — a correctness-relevant, not just cost-relevant, choice |
| `msa_server_url` (ColabFold/Boltz-shared infra) | str (URL) | n/a | `api.colabfold.com` | Self-hosting removes reliance on the shared public server's rate limits/availability |

- **Parameters that must NOT be agent-varied:** the AF3 weights themselves (access is an org-level grant, not a runtime parameter). `model_preset=monomer` (non-`_ptm`) should never be silently selected for a task that needs confidence-based accept/reject gating, since it does not emit pTM/PAE at all — this is a correctness footgun, not a cost knob.

## Failure modes & what the agent must check
- **Loud failure:** missing/corrupt databases, GPU OOM on long targets, malformed FASTA/JSON.
- **Silent bad output (shared across the family, well-documented for AF3 but architecturally applicable to AF2/ColabFold's `_ptm` outputs too):** high pLDDT with wrong domain orientation (pLDDT is a *local* per-residue confidence measure and says nothing about global assembly correctness); high ipTM with **no actual biological interaction** — a documented real case had ipTM > 0.85 and low interface PAE for a homodimer prediction where experimental pull-down showed no dimerization (the model forced a plausible-looking interface from proximate termini that are flexible/non-binding in vivo); and **"reverse docking"** in antibody-antigen complexes, where the predicted orientation is inverted relative to the true complex yet is accompanied by high ipTM+pTM in the large majority of observed cases (53/81 in one published study). The **ipSAE** metric (`doi 10.1101/2025.02.10.637595`, PMC11844409) was specifically developed as a fix for ipTM's known failure to penalize disordered/accessory-domain-dominated interfaces and is worth adopting as a secondary gate rather than relying on raw ipTM alone.
- **Specific checks:** the agent should never gate on pLDDT or ipTM alone; combine per-residue pLDDT with PAE-derived interface metrics (ipTM plus, ideally, ipSAE) and a basic clash/`has_clash` check (AF3 emits `has_clash` directly in `summary_confidences.json`) before accepting a prediction as ground truth for a design loop.

## Cost per unit of work
- AF2/ColabFold: full-DB AF2 run ~5 minutes to 2 hours per target on an A100-class GPU depending on length/homolog depth (search-stage dominates for novel sequences); ColabFold's MMseqs2-server MSA step is typically seconds-to-low-minutes, shifting the bottleneck to the GPU inference stage.
- AF3: no independent wall-clock figure found in this search; architecturally similar diffusion-model cost profile to RF3/Boltz (minutes-scale per target at moderate recycle/sample counts), but gated behind the same database-staging cost as AF2 for its MSA stage.
- Resource shape: 1 GPU per target for the inference stage across all three; AF2/AF3's MSA-search stage is CPU-bound and can be run on non-GPU nodes if the agent's scheduler splits the two stages.
- Checkpointable: no mid-run checkpoint for any of the three; all are effectively restart-from-scratch per target, though ColabFold/AF2 MSA results can be cached and reused across repeated predictions of the same sequence.

## Verdict
- **AF2: Recommended.** Best-in-class license (CC BY 4.0, unrestricted), real AMD/Frontier precedent via LUMI/Pawsey, but the ~2.6 TB local database staging burden is a real one-time cost that should be planned as site infrastructure, not per-campaign work — and ColabFold already supersedes it operationally for MSA. Include as a fallback/validation baseline rather than the primary structure predictor.
- **AF3: Defer.** The manual, discretionary, non-commercial-only weight-access gate is fundamentally incompatible with the "autonomous agent, provisioned on demand" premise of this project unless the deploying organization has *already* secured and pre-staged weights and confirmed non-commercial status — a precondition this brief cannot verify and that would need to be revisited if that access is separately arranged. What would change the answer: confirmed org-level weight access already in hand, and confirmation the project's downstream use stays non-commercial.
- **ColabFold: Core.** The best available on-ramp for AF2-class predictions in a full-egress HPC environment — it eliminates AF2's dominant staging cost entirely (P5 MSA vs. hundreds-of-GB local DB) and is the literal infrastructure Boltz's and Chai's own remote-MSA flags depend on, so understanding and potentially self-hosting it (for rate-limit/availability control) is directly load-bearing for the rest of the toolkit, not just a nice-to-have.

## Sources
- [google-deepmind/alphafold](https://github.com/google-deepmind/alphafold), [alphafold/README.md](https://github.com/google-deepmind/alphafold/blob/main/README.md)
- [google-deepmind/alphafold3](https://github.com/google-deepmind/alphafold3), [WEIGHTS_TERMS_OF_USE.md](https://github.com/google-deepmind/alphafold3/blob/main/WEIGHTS_TERMS_OF_USE.md), [OUTPUT_TERMS_OF_USE.md](https://github.com/google-deepmind/alphafold3/blob/main/OUTPUT_TERMS_OF_USE.md), [installation.md](https://github.com/google-deepmind/alphafold3/blob/main/docs/installation.md), [performance.md](https://github.com/google-deepmind/alphafold3/blob/main/docs/performance.md), [output.md](https://github.com/google-deepmind/alphafold3/blob/main/docs/output.md)
- [sokrypton/ColabFold](https://github.com/sokrypton/ColabFold), [YoshitakaMo/localcolabfold](https://github.com/YoshitakaMo/localcolabfold), [ColabFold/batch.py](https://github.com/sokrypton/ColabFold/blob/main/colabfold/batch.py)
- [AMD ROCm JAX install docs](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/jax/install.html), [LUMI AlphaFold module docs](https://lumi-supercomputer.github.io/LUMI-EasyBuild-docs/a/AlphaFold/), Pawsey AMD GPU AlphaFold2 docs (referenced via search, URL not independently re-fetched)
- ["Rēs ipSAE loquuntur": ipTM critique and fix](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11844409/) (also bioRxiv 10.1101/2025.02.10.637595)
- Reverse-docking antibody-antigen finding: arXiv 2511.14676 ("Exploring AlphaFold 3 for CD47 Antibody-Antigen Binding Affinity")
- `Augmented-Nature/AlphaFold-MCP-Server` ([GitHub](https://github.com/augmented-nature/alphafold-mcp-server)), `mcpservers.org` listing — MCP is database-lookup scope, confirmed by reading the tool-list summary in search results, not by running the server.
- `zeinab-sheikhi/mcp-alphafold` — referenced only via search snippet; not independently verified, mark speculative.
- All findings in this brief are WebSearch-derived (no upstream repo present in `impress-a-refcodes/`); benchmark/runtime figures not independently reproduced.
