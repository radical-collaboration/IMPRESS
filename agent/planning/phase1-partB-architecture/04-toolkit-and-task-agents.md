# 04 — Toolkits and Task Agents

The toolkit from Part A, organized for agentic invocation. Two layers: a **declarative registry** of what
each tool is and how it behaves, and a **task agent** per tool that actually runs it.

## 1. ToolSpec — the declarative contract

Every tool in the Part A roster gets a `ToolSpec`. This is the single source of truth the composer, the
validator, the budget guard, and the task agent all read. Nothing about a tool is known anywhere else.

```python
# Illustrative notation.

@dataclass(frozen=True)
class ToolSpec:
    id: str                                  # "rfdiffusion3", "cartesian_ddg"
    toolkit: str                             # see §3
    version: str

    # --- typing: what makes composition checkable (05) ---
    inputs:  dict[str, ArtifactType]         # {"backbone": Backbone, "hotspots": ResidueSet}
    outputs: dict[str, ArtifactType]         # {"designs": list[Backbone]}

    # --- scheduling: from Part A's taxonomy ---
    pattern: Pattern                         # P1..P7
    resources: ResourceShape                 # gpus, cores, nodes, memory, walltime estimate
    gpu_portability: GPUPortability          # CUDA | CUDA+HIP | CUDA+SYCL | portable | cpu_only
    state_model: Literal["stateless", "checkpointable", "restart_required"]

    # --- what the agent may vary ---
    parameters: dict[str, ParameterSpec]     # type, range, default, what it trades off
    frozen_parameters: dict[str, Any]        # explicitly NOT agent-varyable, with a reason

    # --- correctness ---
    preconditions: list[Check]               # validated before execution
    qc_gates: list[Gate]                     # enforced after execution — mandatory, not optional
    known_silent_failures: list[SilentFailure]   # mode → detecting check

    # --- economics ---
    cost_model: CostModel                    # unit of work → wall-clock × resource shape

    # --- how it is driven ---
    agent: Literal["deterministic", "llm"]   # the hybrid decision, per tool
    skill_doc: Path                          # agent-facing usage documentation
```

Every field maps to something Part A established. `pattern` and `resources` come from T1 and T5;
`gpu_portability` from T6; `qc_gates` and `known_silent_failures` from each brief's failure-modes section;
`parameters` and `frozen_parameters` from each brief's agentic-surface table.

**`frozen_parameters` is as important as `parameters`.** Part A's briefs repeatedly identified settings an
agent must *not* touch — a scorefunction's reference-energy weights, `ddg:legacy` mixed within a campaign, a
retry backoff floor, the identity-comparison method for ligand deduplication. Freezing them declaratively
means the composer cannot propose them and the validator rejects them if it tries.

## 2. Task agents — four responsibilities

Each tool invocation is handled by a task agent with the four responsibilities named in the specification.

| Phase | Responsibility |
|---|---|
| **pre-process** | Stage inputs to the right filesystem; convert formats at tool boundaries; check `preconditions`; resolve checkpoints and record their hashes |
| **parameterize** | Turn the composer's abstract request into concrete arguments, bounded by `parameters`; reject anything touching `frozen_parameters` |
| **execute** | Dispatch by `pattern` to the execution layer (`07`) — never decide *how* to schedule, only *what* to run |
| **post-process** | Parse outputs into typed artifacts; extract metrics; **enforce `qc_gates`**; emit a `QCReport` |

The task agent — not the policy, not the composer — is where Part A's silent-failure defence lives. This is
the deliberate placement: the policy may be an LLM that reasons loosely, but the boundary at which a tool's
output enters campaign state is always guarded by code that knows that tool's specific failure modes.

### The hybrid decision

`ToolSpec.agent` declares which kind of agent drives the tool.

| | Deterministic | LLM-driven |
|---|---|---|
| Implementation | Typed code | Bounded LLM call with schema-validated output |
| Cost | ~0 | ~1 LLM call per invocation |
| Reproducible | Yes | No (logged, not replayable bit-for-bit) |
| Use for | Well-understood tools with stable interfaces | Tools whose *parameterization is itself authorship* |

Most of the toolkit is deterministic. Candidates for LLM-driven task agents, from Part A's findings:

- **RosettaScripts XML authoring** — composing a protocol is genuinely open-ended, and AgentRosetta exists
  precisely because this is hard.
- **Ligand setup** — Part A's six-item silent-failure taxonomy (protonation, tautomer, charge,
  stereochemistry, missing torsions, atom naming) involves chemical judgement, though the *checks* stay
  deterministic.
- **Unusual failure triage** — interpreting a tool failure that no declared gate anticipated.

Even in LLM-driven agents, **QC gates remain deterministic code.** An LLM may author a Rosetta protocol; it
does not get to judge whether the resulting structure passed its clash check.

## 3. Toolkits and skill documentation

Tools are grouped into **toolkits** matching Part A's clusters. Each toolkit carries a **skill document** —
the agent-facing text that initializes expected workflow behaviour, as the specification requires.

| Toolkit | Members (from Part A T1) |
|---|---|
| `generation` | RFD3, RFD3NA |
| `inverse_folding` | ProteinMPNN, LigandMPNN, ESM-IF1 |
| `structure_prediction` | Boltz-2, RF3, ColabFold, ESMFold, AlphaFold2 |
| `physics_design` | Rosetta, PyRosetta, enzyme design, `cartesian_ddg` |
| `stability` | ThermoMPNN, Stability Oracle, `cartesian_ddg`, ESM2 likelihood |
| `simulation` | OpenMM, GROMACS, MDAnalysis/MDTraj, structure prep |
| `search` | FoldSeek, MMseqs2, US-align, bio-database APIs |
| `ligand` | RDKit, Open Babel, ligand parameterization, Vina, cheminformatics I/O |
| `analysis` | DSSP, FreeSASA, MolProbity, Biotite, PyMOL |
| `composite` | IMPRESS pipelines (P7) |

A skill document is **not** an API reference — the `ToolSpec` is the reference. It states:

1. **What this toolkit is for**, in scientific terms, and when *not* to reach for it.
2. **Canonical sequences** — the self-consistency loop (generate → inverse-fold → predict → superpose) is the
   single most important one, with the field-standard thresholds Part A recorded (scRMSD < 2 Å, TM-score ≥ 0.5).
3. **Cost posture** — which members are cheap enough to run on everything, which are shortlist-only. The
   cheap-screen-then-confirm pattern for stability belongs here explicitly.
4. **Pitfalls** — the toolkit's characteristic silent failures, and what the agent should be suspicious of.
5. **Composition guidance** — which tools pair, which are redundant. That Boltz-2's affinity head largely
   obviates classical docking is skill-doc content, not something an agent should rediscover per campaign.

Skill documents are supplied to the policy at campaign start for the toolkits the campaign enables, and are
the mechanism by which the toolkit teaches the agent to behave sensibly before its first decision.

## 4. Artifact types

Composition is checkable only if artifacts are typed. The type lattice is small and deliberately
scientific rather than file-format-based:

```
Structure ─┬─ Backbone          (coordinates, no sequence commitment)
           ├─ Complex           (multi-chain, optionally with ligand)
           └─ Ensemble          (multiple conformers or a trajectory frame set)
Sequence  ─┬─ ProteinSequence
           └─ SequenceSet
Ligand    ─┬─ SmallMolecule     (with an explicit protonation/tautomer commitment)
           └─ Parameterized     (force-field-ready; a distinct type on purpose)
Alignment ─┬─ MSA
           └─ StructuralHit
Scalar    ─┬─ Metric
           └─ MetricSet
Trajectory
```

Two typing choices carry real weight:

- **`SmallMolecule` and `Parameterized` are distinct types.** A tool needing force-field parameters cannot
  accept a bare molecule. This makes Part A's most underrated failure mode a *type error at composition time*
  rather than a silent corruption at runtime.
- **`Backbone` and `Complex` are distinct.** A tool that scores an interface cannot be handed a monomer
  backbone.

File formats (PDB, mmCIF, FASTA, SDF, PDBQT) are an *implementation detail of the artifact*, converted at
tool boundaries by pre-processing. The composer reasons about types; the task agents handle formats. This is
what stops format plumbing from leaking into the policy's decision space.
