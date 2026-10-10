# MCP Landscape

**Phase 1, Part A — IMPRESS-A autonomous protein design agent**
Status: normative survey. Companion to `compute-pattern-taxonomy.md` and `briefs/`; not itself a brief, so it
does not follow `_BRIEF-TEMPLATE.md`'s ten sections.

## Purpose

A systematic MCP (Model Context Protocol) survey across the full Part A tool roster — 26 entries spanning
generators, inverse-folders, structure predictors, physics engines, search/database tools, cheminformatics
libraries, and IMPRESS itself — answering one question per entry: **can an autonomous agent already reach this
tool through a standard, typed tool-calling protocol, or does this project have to build that surface itself?**

## Evidence discipline

This file's entire value is in not padding the table. Three discrete evidence tiers are used, and every row is
marked with exactly one:

- **Verified (repo-local)** — a specific server module path exists and was read in this project's own
  `impress-a-refcodes/` checkout. Note: tool schemas being *registered* in a session is NOT runtime
  verification — see the PyMOL row, where registered tools proved unreachable.
- **Verified (org-confirmed)** — the candidate server's GitHub repository was checked against the GitHub API
  (`api.github.com/repos/<owner>/<repo>`) and its owner is confirmed to be the tool's own official organization,
  not a look-alike third party. Two such servers were found in this pass (RCSB, PDBe) — see below.
- **Unverified** — a repository was found and confirmed to *exist* (HTTP 200 from the GitHub API, or a live
  package/marketplace listing), but it is a third party unaffiliated with the tool's maintainers, and its
  correctness, security, and maintenance status were **not** independently exercised. This is the large
  majority of rows below. "Exists" and "trustworthy" are different claims; this file only asserts the former
  for anything marked Unverified.
- **Verified absent** — a repo-wide grep for `mcp`/`model context protocol`/`modelcontextprotocol` was run
  against the relevant refcode tree and returned zero hits, and no upstream MCP server was found in search
  either. This is a positive finding (confirmed absence), not a shrug.

A plausible-sounding server name found only in a single unchecked search snippet, with no resolvable URL, is
**omitted entirely** rather than recorded — several candidates surfaced during this sweep that could not be
resolved to a real, checkable repository and are not listed.

## Master table

| Tool | Native MCP | Community MCP (URL) | What it exposes | Verified? |
|---|---|---|---|---|
| RFD3 | No | — | — | Verified absent — repo-wide grep of `tools/foundry` for `mcp`/`model context protocol` returns zero hits (`briefs/rfdiffusion3.md`) |
| RFD3NA | No | — | — | Verified absent — same grep (`briefs/rfdiffusion3na.md`) |
| ProteinMPNN / LigandMPNN | No | — | — | Verified absent — same grep (`briefs/proteinmpnn-ligandmpnn.md`) |
| RF3 | No | — | — | Verified (search performed; general "AlphaFold MCP" servers found do not cover RF3) (`briefs/rf3.md`) |
| AtomWorks | No | — | — | Verified absent — same grep, plus no upstream server found (`briefs/atomworks.md`) |
| foundry (infra) | No | — | — | Verified absent — repo-wide grep across all of `tools/foundry` (`briefs/foundry.md`) |
| Rosetta | No (community exists) | [`Arielbs/rosetta-mcp-server`](https://github.com/Arielbs/rosetta-mcp-server) (PyPI `rosetta-mcp`) | XML validation, RosettaScripts execution, documentation lookup | Unverified — repo confirmed to exist (HTTP 200); unaffiliated with RosettaCommons; flagged low-trust by at least one third-party security scanner (`briefs/rosetta.md`) |
| PyRosetta | No (community exists) | same as Rosetta row | same | Unverified — same caveat, covers PyRosetta interactively too (`briefs/pyrosetta.md`) |
| ESM2 / ESM-C / ESMFold | No | [`Biomolecular-Design-Nexus/esmfold_mcp`](https://github.com/Biomolecular-Design-Nexus/esmfold_mcp); [`zeinab-sheikhi/mcp-alphafold`](https://github.com/zeinab-sheikhi/mcp-alphafold) (claims ESM-2/ESM-C embeddings + ESMFold coverage) | ESMFold structure prediction (local two-conda-env install); claimed ESM-2/ESM-C embeddings, mutation scoring, landscape scans | Unverified — both repos confirmed to exist; neither independently run; scope of the second not confirmed beyond its own description (`briefs/esmfold.md`) |
| Boltz | No | — | — | Verified — no Boltz-specific MCP server found in search |
| Chai | No | — | — | Verified — no Chai-specific MCP server found in search |
| AlphaFold family (AF2/AF3) — running inference | No | — | — | Verified — no server found that runs new AF2/AF3 predictions (`briefs/alphafold.md`) |
| ColabFold | No | — | — | Verified — no ColabFold-specific MCP server found; it is the infra other tools' `--use_msa_server` flags call directly (`bio-databases.md`, `briefs/mmseqs2.md`) |
| GROMACS | No | [`MacromNex/gromacs_mcp`](https://github.com/MacromNex/gromacs_mcp); [`SeveNOlogy7/gmx-vmd-mcp`](https://github.com/SeveNOlogy7/gmx-vmd-mcp); [`Alierkn/gromacs-mcp`](https://github.com/Alierkn/gromacs-mcp); [`ChatMol/molecule-mcp`](https://github.com/ChatMol/molecule-mcp) (`gromacs_copilot`) | Running `gmx` commands, TPR/topology analysis, predefined simulation workflows, async job submission/tracking, trajectory analysis (RMSD/RMSF), VMD visualization | Unverified — all four repos confirmed to exist (HTTP 200); none independently run or audited; supersedes `briefs/gromacs.md`'s earlier "no confirmed wrapper" note with concrete URLs found in this pass |
| LAMMPS | No | [`Chenghao-Wu/MCP_LAMMPS`](https://github.com/Chenghao-Wu/MCP_LAMMPS) | LAMMPS command execution (scope not independently confirmed) | Unverified — repo confirmed to exist; independent community project, not upstream LAMMPS (`briefs/lammps.md`) |
| OpenMM | Community | [`PhelanShao/openmm-mcp-server`](https://github.com/PhelanShao/openmm-mcp-server); [`oumiya-pharm/openMM-Doc-MCP`](https://github.com/oumiya-pharm/openMM-Doc-MCP) | Task submission/management for OpenMM + DFT (via Abacus), protein/membrane simulation templates, CUDA/OpenCL support (first server); OpenMM documentation indexing (second) | Unverified — both repos confirmed to exist; neither independently run (`briefs/openmm.md`) |
| FoldSeek | No | [`AltriaPendragon49/foldseek-mcp`](https://glama.ai/mcp/servers/AltriaPendragon49/foldseek-mcp) (glama.ai listing) | Structure/sequence search across multiple databases, automatic model downloads, structured job management (per its own description) | Unverified, possibly defunct — the GitHub repo this listing points to returned HTTP 404 when re-checked in this pass (`briefs/foldseek.md`'s listing may already be stale) |
| MMseqs2 | No | — | — | Verified — hard search performed, zero hits (`briefs/mmseqs2.md`) |
| RDKit | No | [`tandemai-inc/rdkit-mcp-server`](https://github.com/tandemai-inc/rdkit-mcp-server) (MIT, 42★/7 forks/76 commits at time of inspection); [`s20ss/mcp_rdkit`](https://github.com/s20ss/mcp_rdkit) | "Agent-level access to every function in RDKit 2025.3.1" per the first repo's own claim; second is less documented | Unverified — first repo's existence and stated scope independently confirmed via WebFetch; second confirmed to exist but not inspected (`briefs/rdkit.md`) |
| PyMOL | **Identified, not runtime-verified** | likely `Arcadia-Science/agentic-pymol` (port 9877 matches its documented default; README-level match only, source not read) | `align`, `cealign`, `rms`, `get_distance`, `get_extent`, `iterate`, `count_atoms`, `fetch`, `load`, `render`, `save`, `get_fastastr`, `get_chains`, `do`, `run`, `screenshot`, `alter`, `get_coords`, `get_model`, `get_names`, `get_object_list`, `get_view`, `set_view`, `count_states`, `status` | **Schemas registered in this session but server NOT reachable** — a direct `mcp__pymol__status` call returns `ConnectionError: could not connect to PyMOL plugin at 127.0.0.1:9877 ([Errno 111] Connection refused)`. Architecturally a plugin inside a live, GUI-capable PyMOL process on a local TCP port: a desktop/workstation pattern, not viable unattended in a headless HPC batch job. |
| AutoDock Vina | No | [`shogo-d-nakamura/MCP_Vina`](https://github.com/shogo-d-nakamura/MCP_Vina); [`AIB001/AutodockVina_MCP`](https://github.com/AIB001/AutodockVina_MCP) | SMILES-driven protein-ligand (blind) docking against a named target | Unverified — both repos confirmed to exist; neither independently run. Separately, ChemGraph wraps Vina as a LangChain `@tool` (`chemgraph/tools/docking_tools.py`/`docking_core.py`), a non-MCP agent-integration precedent worth noting (`briefs/docking.md`) |
| BioPython | No | — | — | Verified — no Bio.PDB/BioPython-specific MCP server found in either the earlier sweep or a fresh targeted search this pass; unrelated biomedical-literature servers (BioMCP) and systems-biology servers (`marcorusc/mcp-biomodelling-servers`) surfaced but do not wrap Bio.PDB (`briefs/structure-libraries.md`) |
| RCSB PDB | **Yes (official)** | [`rcsb/rcsb-mcp`](https://github.com/rcsb/rcsb-mcp) | Search API (fulltext, attribute, sequence, chemical, structure, motif queries), Data API (entry/entity/assembly/ligand detail), Sequence Coordinates API (PDB↔UniProt↔NCBI mapping), ontology resolution (GO, InterPro, EC, organism) — ~25+ tools, MIT license, 188 commits | **Verified (org-confirmed)** — GitHub API confirms owner `rcsb`, `type: "Organization"`, description "MCP server for RCSB PDB APIs" |
| UniProt | No (official) | [`Augmented-Nature/Augmented-Nature-UniProt-MCP-Server`](https://github.com/Augmented-Nature/Augmented-Nature-UniProt-MCP-Server); [`BioContext/UniProt-MCP`](https://github.com/BioContext/UniProt-MCP); [`fastmcp-me/uniprot-mcp`](https://github.com/fastmcp-me/uniprot-mcp); [`pansapiens/uniprot-unipressed-mcp`](https://github.com/pansapiens/uniprot-unipressed-mcp) | Accession/keyword/gene/organism lookup, ID mapping, GO annotation retrieval (feature set varies by implementation) | Unverified — none of the four confirmed to be an official UniProt Consortium project; RCSB's own official server (above) partially covers PDB↔UniProt cross-referencing via its Sequence Coordinates API, but that is not a substitute for a full UniProt-native server |
| AlphaFold DB (lookup only) | No (official) | [`Augmented-Nature/AlphaFold-MCP-Server`](https://github.com/Augmented-Nature/AlphaFold-MCP-Server) | Fetch AlphaFold DB structures by UniProt accession, format conversion, confidence-score analysis — **lookup only, does not run new AF2/AF3 inference** | Unverified — repo confirmed to exist; scope (DB lookup, not inference) confirmed by direct inspection in `briefs/alphafold.md` |
| IMPRESS | No | — | — | Verified absent — repo-wide grep across all of `tools/IMPRESS` returns zero hits (`briefs/impress.md`) |
| ChemGraph | **Yes** | — | 13 MCP server modules under `tools/ChemGraph/src/chemgraph/mcp/` (`cg_fastmcp.py`, `ase_mcp_hpc.py`, `mace_mcp_hpc.py`, `graspa_mcp_hpc.py`, `xanes_mcp_hpc.py`, plus `_parsl.py` variants and `data_analysis_mcp.py`/`hpc_misc_mcp.py`/`transfer_tools.py`) — HPC-backed submit/poll job control (`check_job_status`, `get_job_results`, `list_jobs`, `cancel_job`) over ASE/MACE/gRASPA/XANES computational-chemistry workflows, with `mcp==1.28.1`/`fastmcp==3.4.4` pinned | **Verified (repo-local)** — read in full, `briefs/chemgraph.md` |

**Tally:** 26 rows. **2 Verified/official or repo-local "yes"** (ChemGraph, RCSB PDB — plus PDBe as a
second official-adjacent finding, noted below but not its own roster row). **7 "verified absent"** (RFD3,
RFD3NA, ProteinMPNN/LigandMPNN, AtomWorks, foundry, IMPRESS, plus RF3/Boltz/Chai/ColabFold/MMseqs2/BioPython/
AlphaFold-inference verified as "searched, none found" — 12 rows total carry a **No** with a verified-absence
or verified-none-found basis). **11 rows carry at least one Unverified community server** (Rosetta, PyRosetta,
ESM-family, GROMACS, LAMMPS, OpenMM, FoldSeek, RDKit, AutoDock Vina, UniProt, AlphaFold DB-lookup).

## Two findings this pass adds beyond prior-established results

1. **RCSB PDB has a genuine, official, native MCP server** (`rcsb/rcsb-mcp`) — confirmed directly against the
   GitHub API (owner `rcsb`, `Organization` type), not inferred from a marketplace listing. This is the
   strongest "yes" in the entire table for a pure database-lookup tool, on par with ChemGraph's HPC-execution
   servers as the two best-verified entries in this whole sweep, though the two solve different problems (data
   lookup vs. computation dispatch — see the maturity verdict below).
2. **PDBe (Protein Data Bank in Europe, EMBL-EBI's own PDB mirror/complement) also ships an official server**,
   [`PDBeurope/PDBe-MCP-Servers`](https://github.com/PDBeurope/PDBe-MCP-Servers) — confirmed via the GitHub API
   (owner `PDBeurope`, `Organization` type), 39 stars, pushed as recently as 2026-07-29. Not its own roster row
   (PDBe is not separately named in this project's tool list; RCSB is the canonical entry), but recorded here
   because it corroborates a real pattern: **the two large, professionally-operated structural databases in
   this sweep (RCSB, PDBe) both ship official MCP servers; none of the compute/generation tools do.**

## The trust dimension: same-vendor look-alikes are a real, observed pattern here, not a hypothetical

`Augmented-Nature` (GitHub org, blog `augmentednature.ai`, confirmed via the GitHub API to be an independent
organization with no affiliation markers to RCSB, UniProt, or DeepMind/EBI) has published at least three
similarly-named database-lookup servers found in this sweep alone: `PDB-MCP-Server`,
`Augmented-Nature-UniProt-MCP-Server`, and `AlphaFold-MCP-Server`. Each is individually plausible and each was
confirmed to exist, but **none is what its name suggests it might be** (an official project server) — a naming
pattern ("`<DatabaseName>`-MCP-Server") that is easy to mistake for an official release, especially once
aggregated into a marketplace listing (Glama, LobeHub, mcpservers.org) that strips the "is this the real
project's org" signal entirely. This is not a claim that Augmented-Nature's servers are malicious — no evidence
of that was found or sought — it is a concrete illustration of why "found a repo with the right name" cannot be
this file's bar for "yes," and why the GitHub-API organization check (used for RCSB and PDBe above) is the
correct verification step before treating any database-lookup server as authoritative.

## Bottom-line assessment

**The MCP ecosystem for computational protein design is not mature enough to build this project's execution
layer on, and the shape of what does exist is informative rather than just incomplete.** Split the roster in
two:

- **Database/data-lookup tools (RCSB, UniProt, AlphaFold DB, and the general shape of PDBe) are the one
  category where the ecosystem is genuinely healthy.** RCSB and PDBe both have real, official, actively
  maintained servers; UniProt and AlphaFold DB have multiple competent-looking third-party implementations even
  without an official one. This tracks with what these servers actually have to do: wrap a well-documented,
  stable, read-only REST API behind typed tool calls — a shallow, low-risk integration surface that a solo
  developer can build correctly in a weekend, which is exactly why so many independent implementations of the
  same idea (UniProt has at least five found in this sweep) coexist without any one of them being load-bearing
  infrastructure.
- **Tools that run real HPC computation — everything else in this roster — are, with exactly one exception,
  either absent or third-party/unverified.** RFD3, RFD3NA, MPNN, RF3, AtomWorks, Boltz, Chai, ColabFold, and
  foundry/IMPRESS itself have **zero** MCP presence, native or community, confirmed by repo-wide grep and
  targeted search. Rosetta, GROMACS, LAMMPS, OpenMM, AutoDock Vina, FoldSeek, RDKit, and the ESM family have
  *some* third-party server, but every single one is an unaudited individual or small-team project with commit
  counts, star counts, and maintenance signals nowhere near what would justify trusting it inside an unattended
  HPC pipeline without independent review. **ChemGraph's `src/chemgraph/mcp/` is the sole example anywhere in
  this sweep of a native, well-engineered, HPC-execution-aware MCP layer** — and it wraps computational
  chemistry (ASE/MACE/gRASPA/XANES), not protein design; none of its patterns are reusable *as dependencies*
  for this project, only as architecture to imitate (per `briefs/chemgraph.md`'s own verdict).

This split is the actual finding, not a caveat to it: **looking up existing data is easy and the ecosystem has
converged on it independently and repeatedly; running new HPC computation through MCP is rare, hard, and
essentially unsolved for this project's tool roster.** The distinction matters because the failure mode is
different in each half. A broken database-lookup server fails loudly and cheaply (a malformed query, a 404) —
low blast radius if adopted and later found wanting. A broken or malicious HPC-execution server, adopted into
an autonomous, unattended, multi-day campaign with real compute allocation and real filesystem access, is a
different order of risk entirely: arbitrary code execution under the agent's own credentials on a shared HPC
system, silent data corruption in a long-running campaign's own results, or simply quiet incorrectness (a
docking or MD server that runs but subtly mis-configures a physics engine) that an agent has no independent way
to catch because it has no ground truth to check the tool against. **None of the community HPC-execution
servers found in this sweep carry enough verification, provenance, or maintenance signal to justify that risk.**

**Recommendation, stated plainly:** adopt the two verified database-lookup servers (RCSB's own `rcsb-mcp`, and
by extension the case for PDBe's) as legitimate, low-risk building blocks if an MCP-shaped integration is
wanted for those two specifically — treat every other "yes" or "community" entry in this table as a
**candidate to independently audit before adoption, not a dependency to install**, and expect to build this
project's own MCP (or non-MCP) execution layer for every generation/inverse-folding/structure-prediction/
physics tool in the roster, following ChemGraph's `TaskSpec`/`is_async_remote`/`JobTracker` design patterns
(per `briefs/chemgraph.md`) rather than any off-the-shelf HPC-execution MCP server, because none currently
clears the bar this project needs.

## Sources
- `briefs/chemgraph.md`, `briefs/rfdiffusion3.md`, `briefs/rfdiffusion3na.md`, `briefs/proteinmpnn-ligandmpnn.md`,
  `briefs/rf3.md`, `briefs/atomworks.md`, `briefs/foundry.md`, `briefs/impress.md`, `briefs/rosetta.md`,
  `briefs/pyrosetta.md`, `briefs/esmfold.md`, `briefs/alphafold.md`, `briefs/gromacs.md`, `briefs/lammps.md`,
  `briefs/openmm.md`, `briefs/foldseek.md`, `briefs/mmseqs2.md`, `briefs/rdkit.md`, `briefs/docking.md`,
  `briefs/structure-libraries.md` (this project's own prior-established findings, reused per the task brief's
  instruction not to re-derive them)
- `<workspace>/impress-a-refcodes/tools/ChemGraph/src/chemgraph/mcp/` (repo-local, read in full for
  `briefs/chemgraph.md`)
- Live session: `mcp__pymol__*` tool listing (this conversation's own tool roster) — schemas present, but a
  direct `status` call returned connection-refused, so this counts as identification, not verification.
- GitHub API (`api.github.com/repos/rcsb/rcsb-mcp`, `api.github.com/repos/PDBeurope/PDBe-MCP-Servers`,
  `api.github.com/orgs/Augmented-Nature`) — queried directly in this pass to confirm organizational ownership,
  not inferred from search snippets
- Existence of all "Unverified" community repos confirmed via `api.github.com/repos/<owner>/<repo>` returning
  HTTP 200 in this pass (`shogo-d-nakamura/MCP_Vina`, `AIB001/AutodockVina_MCP`, `MacromNex/gromacs_mcp`,
  `SeveNOlogy7/gmx-vmd-mcp`, `Alierkn/gromacs-mcp`, `Biomolecular-Design-Nexus/esmfold_mcp` (301 redirect, still
  live), `zeinab-sheikhi/mcp-alphafold`, `tandemai-inc/rdkit-mcp-server`, `s20ss/mcp_rdkit`,
  `Arielbs/rosetta-mcp-server`, `PhelanShao/openmm-mcp-server`, `Chenghao-Wu/MCP_LAMMPS`,
  `Augmented-Nature/AlphaFold-MCP-Server`, `Augmented-Nature/Augmented-Nature-UniProt-MCP-Server`,
  `Augmented-Nature/PDB-MCP-Server`); `AltriaPendragon49/foldseek-mcp` returned HTTP 404 on re-check (flagged
  possibly defunct — the original `foldseek.md` finding was a glama.ai listing, not a direct GitHub check)
- WebSearch, this pass: targeted queries per gap tool (RDKit/BioPython/FoldSeek/MMseqs2/RCSB/UniProt/ESM/
  AutoDock Vina/GROMACS + "MCP server" + "model context protocol" + "github"), full result sets not
  individually cited per-URL beyond the table above
