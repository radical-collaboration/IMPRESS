# ESMFold

**One-line identity.** A single-sequence, MSA-free protein structure predictor that folds directly from a protein language model's (ESM-2) internal representations. Not present in `impress-a-refcodes/`; this brief is built entirely from upstream sources (WebSearch). Scope note: ESM2/ESM-C **embeddings and likelihood scoring** are covered by a separate agent/brief — this brief stays on the **folding model** only.

## Identity
- **Version / release examined:** `facebookresearch/esm` (the `fair-esm` PyPI package), model entrypoint `esm.pretrained.esmfold_v1()`. Original ESMFold paper/model: Lin et al., *Science* 2023 ("Evolutionary-scale prediction of atomic-level protein structure with a language model"). Not present in refcodes; version pin not independently verified from a local file.
- **Provenance:** Meta AI (FAIR). **MIT-licensed**, code and weights, hosted on both the original `facebookresearch/esm` repo and Hugging Face `transformers` (`EsmForProteinFolding`). Fully open, no access gate — the most frictionless licensing/access story of any tool in this cluster alongside RF3 and Chai-1.
- **Maturity:** production/mature but effectively frozen — Meta's active successor work has moved to newer language-model-driven folding approaches (e.g., a 2026 "ESMFold2" effort from Biohub/Alex Rives combining a 6B-parameter ESMC with a diffusion-based structure head, positioned as matching/exceeding AF3 — found in search but **not the tool this brief covers**; flagged here only so the two are not confused in later toolkit decisions). Treat ESMFold (v1, this brief) as a stable, unmaintained-but-working baseline tool rather than an actively evolving one.

## Scientific role
Fast, MSA-free monomer structure prediction. Serves primarily **stability/thermostabilization** (rapid fold-check on point mutants/redesigns where MSA turnaround would dominate wall-clock) and, secondarily, **de novo binder design** as a cheap first-pass filter before a slower AF3-class co-folder is invoked on surviving candidates. Weak fit for enzyme/small-molecule problem classes: ESMFold has **no ligand or multi-entity co-folding capability** — it predicts protein (and, with reduced reliability, homo-oligomer via chained-sequence tricks) structure only. Pipeline stage: **predict**, specifically positioned as a fast pre-filter ahead of heavier co-folders, not a replacement for them.

## Invocation & I/O contract
- **How a unit of work is invoked:** Python API (no CLI entrypoint found analogous to `rf3 fold`/`boltz predict`).
  ```python
  import esm
  model = esm.pretrained.esmfold_v1()
  model = model.eval().cuda()
  with torch.no_grad():
      output = model.infer_pdb(sequence)   # single sequence -> PDB string
  # or, batched:
  # pdb_strings = model.infer_pdbs(list_of_sequences)
  with open("result.pdb", "w") as f:
      f.write(output)
  ```
  A lower-level `model.infer(sequences)` call returns a raw output dict (including `"plddt"`, shape `[1, seq_len]`) that `output_to_pdb(output)` converts to PDB text; the Hugging Face `transformers` route (`EsmForProteinFolding.from_pretrained("facebook/esmfold_v1")`) is the commonly-used alternative for users who prefer the `transformers` ecosystem over `fair-esm` directly.
- **Inputs:** a single amino-acid sequence string (or a list, for `infer_pdbs`/batched `infer`). No MSA, no template, no ligand input path exists.
- **Outputs:** a PDB-format string/file with per-residue pLDDT written into the B-factor column (extractable via `biotite`: `bsio.load_structure(..., extra_fields=["b_factor"])` then `struct.b_factor.mean()` for a whole-structure summary score).
- **A concrete example:** the load/infer/save/plddt-extraction pattern above is the documented pattern from the `fair-esm` PyPI page and repo README (per search results); no repo-local example file exists to cite since ESMFold is not in `impress-a-refcodes/`.

## Compute pattern
- **Pattern:** P1 (GPU-node-local, in-job). No search/staging sub-stage at all — this is ESMFold's defining operational advantage over the entire AF-family and over RF3/Boltz/Chai when MSAs aren't already cached: there is no P2/P5 MSA phase to manage.
- **GPU vendor portability:** **portable, by construction — pure PyTorch, no custom CUDA kernels found in this search.** ESMFold is a `transformers`/`fair-esm` PyTorch model with no cuEquivariance-style fused-kernel dependency reported anywhere in search results (unlike RF3/Boltz). This makes it, on paper, the easiest of the five tools in this cluster to run on ROCm or XPU PyTorch builds — but this is an *inference from absence of contrary evidence*, not a confirmed AMD/Intel deployment; no explicit "ESMFold on MI250" or "ESMFold on PVC" report was found in this search. Mark **plausible-portable, unverified**, and note it is the best a-priori bet of the five for a fast Frontier/Aurora smoke test given the lack of any CUDA-only kernel dependency.
- **State model:** stateless per sequence.
- **Data locality:** self-contained (no shared-FS database dependency; only the model weights need to be locally cached, typically via the standard `torch.hub`/`transformers` cache directory).
- **Staging burden:** model weights only, no sequence/structure databases at all — the smallest staging burden of any tool in this cluster (smaller even than Boltz's ~3.6 GB, though an exact weight size was not independently confirmed in this search; ESM-2 3B-scale language model backbones are typically several GB, single-digit).
- **Container availability:** community (widely packaged in bioinformatics container collections, e.g., BioContainers-style images); no single official first-party container confirmed in this search.

## Deployment on DOE & ACCESS
- **Polaris / ACCESS (CUDA):** straightforward — standard PyTorch install (`pip install fair-esm` or `transformers`), no special CUDA-version pinning found comparable to Boltz's `cuequivariance_ops_cu12` requirement.
- **Frontier (AMD MI250X):** unverified but structurally low-risk relative to the rest of the toolkit given the pure-PyTorch implementation; PyTorch ROCm builds are mature and this is the most promising candidate for an early "does this even work on ROCm" pilot.
- **Aurora (Intel PVC):** same reasoning as Frontier — no confirmed report, but no CUDA-only kernel to block it; Intel's PyTorch XPU wheels (the same install route documented for Foundry/RF3) should in principle work, pending validation.
- **Module/conda/apptainer:** plain pip install is the documented mechanism; no license gate.

## Agentic surface
- **Native MCP:** **community, unverified.** A search result referenced `zeinab-sheikhi/mcp-alphafold` as additionally covering "ESM-2/ESMC embeddings, mutation scoring, landscape scans, and ESMFold structure prediction" (per the `alphafold.md` brief's MCP findings), but this session could not independently confirm that repo's scope, maintenance status, or whether it wraps `esmfold_v1` specifically versus a hosted API — mark **community / unverified**, not a confirmed `yes`. No other ESMFold-specific MCP server was found.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `chunk_size` (a known `esmfold_v1` memory/speed knob, per common usage patterns in the ecosystem) | int | 64–128 | model-dependent | Smaller chunks trade speed for lower peak GPU memory — mainly relevant for very long sequences; not independently confirmed against the exact `fair-esm` API signature in this search, flag as needs-verification before wiring into an agent |
| sequence length | n/a (input, not a tunable) | — | — | Not a knob but a cost driver: ESMFold's memory/time scales steeply with length; the agent should budget by length rather than assume flat per-call cost |
| batch size (`infer_pdbs` list length) | int | 1–~32 | 1 | Throughput vs. peak memory; batching amortizes fixed model-load overhead the same way RF3's docs describe for "folding many inputs" |

Note: ESMFold's parameter surface is genuinely narrow compared to the diffusion-based co-folders in this cluster — there is no recycle count, no diffusion sample count, no MSA depth to tune, because there is no MSA and the model is a single forward pass (with internal recycling handled by the underlying ESM-2 trunk, not user-exposed the way RF3/Boltz expose `n_recycles`). This narrowness is itself a relevant fact for an autonomous agent: ESMFold offers far less room for adaptive cost/accuracy trading than RF3/Boltz/Chai, so its main lever is simply *whether to call it at all* (as a cheap pre-filter) rather than *how*.

- **Parameters that must NOT be agent-varied:** n/a beyond the above — there is little dangerous surface area precisely because there is little tunable surface area at all.

## Failure modes & what the agent must check
- **Loud failure:** out-of-memory on very long sequences (no MSA-driven length cap, so the practical ceiling is GPU memory, not database coverage); malformed sequence characters.
- **Silent bad output:** ESMFold's pLDDT is documented to be **less reliable as a global confidence signal for poorly-conserved or orphan sequences** than AF2/AF3/RF3/Boltz's pLDDT, precisely because ESMFold has no evolutionary/MSA signal to anchor on — for sequences with few natural homologs, ESMFold can produce confidently-scored but topologically wrong folds where an MSA-based method would have flagged low confidence via alignment depth. The comparative literature found in this search reports **76% correct predictions for monomers vs. AF2/AF3's 88%**, and a much larger accuracy gap for dimers/oligomers (**41% vs. 77%**) — the agent should treat ESMFold as **directionally useful but not a substitute confidence source** for anything beyond single-chain, well-behaved targets, and should route borderline/low-pLDDT or oligomeric cases to an MSA-based co-folder (RF3/Boltz/AF-family) rather than trusting ESMFold's own confidence output at face value.
- **Specific check:** per-residue and mean pLDDT (from the B-factor column or `output["plddt"]`) is the only confidence signal ESMFold emits — there is no PAE/pTM/ipTM equivalent in the base `esmfold_v1` output in the sources reviewed here (unlike AF2's `_ptm`/multimer variants). An agent using ESMFold as a pre-filter should therefore gate on pLDDT alone but calibrate the threshold *more conservatively* than it would for AF3/RF3/Boltz pLDDT, given the oligomer-accuracy gap above, and should not accept ESMFold output as a final structural answer for any multi-chain or ligand-containing design.

## Cost per unit of work
- **Unit of work:** one `infer_pdb(sequence)` call, single chain.
- **Typical wall-clock:** **5-15 seconds per prediction on a single A100-class GPU** for typical-length sequences (per comparative literature found in this search), versus AF2's 5 minutes-2 hours — this 10-1000x speed advantage over MSA-based methods is ESMFold's entire value proposition in this toolkit: it is the cheapest possible structural sanity-check available, useful for triaging large candidate pools (e.g., thousands of point-mutant stability variants) down to a shortlist before spending RF3/Boltz/AF3-class compute on them.
- **Resource shape:** 1 GPU per call; no CPU-bound search stage to schedule separately (in sharp contrast to AF2/AF3).
- **Checkpointable:** n/a — sub-minute calls should never be scheduled as individually checkpointed tasks (this is squarely a P1 in-job call, not P4 material).

## Verdict
**Recommended.** ESMFold's value in this toolkit is narrow but real: it is by far the cheapest structural filter available (no MSA stage, seconds not minutes, MIT-licensed, no access gate, plausible cross-vendor GPU portability), making it the natural first-pass triage step ahead of RF3/Boltz/AF3 for large candidate pools in the stability/thermostabilization problem class specifically. It should **not** be treated as a peer of the AF3-class co-folders for anything requiring multi-chain, ligand, or high-stakes accept/reject decisions — its accuracy gap on oligomers and its inability to co-fold ligands rule it out as a stand-alone gate for the de novo binder, enzyme, or small-molecule problem classes. Recommend wiring it in as a cheap upstream filter feeding into RF3/Boltz, not as a replacement for either.

## Sources
- [facebookresearch/esm](https://github.com/facebookresearch/esm), [`esm/esmfold/v1/esmfold.py`](https://github.com/facebookresearch/esm/blob/main/esm/esmfold/v1/esmfold.py), [`fair-esm` on PyPI](https://pypi.org/project/fair-esm/)
- [`huggingface/transformers` ESMFold modeling code](https://github.com/huggingface/transformers/blob/main/src/transformers/models/esm/modeling_esmfold.py)
- Comparative accuracy/runtime figures: [Frontiers, "Balancing speed and precision... AlphaFold2, ESMFold, and OmegaFold"](https://www.frontiersin.org/journals/genetics/articles/10.3389/fgene.2025.1715037/full); [PMC12809598, "Comparative evaluation... AlphaFold and ESMFold for monomeric and dimeric proteins"](https://pmc.ncbi.nlm.nih.gov/articles/PMC12809598/)
- ESMFold2 (2026, Biohub) referenced only to disambiguate from this brief's scope — [latent.space write-up](https://www.latent.space/p/esmfold2), [Biohub press release](https://biohub.org/news/world-model-of-protein-biology/) — not independently verified, and explicitly out of scope for this brief.
- `zeinab-sheikhi/mcp-alphafold` — referenced only via search snippet in the AlphaFold brief's search pass; not independently verified here.
- All findings in this brief are WebSearch-derived; no repo present in `impress-a-refcodes/` for direct code inspection, and no wall-clock/portability claim here was independently reproduced.
