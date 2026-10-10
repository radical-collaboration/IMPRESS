# 08 — Open Questions and Hand-off

Questions Part B deliberately did not settle, routed to where they belong. Each names what is blocked by it.

## For Part C — project structure

| # | Question | Why it matters |
|---|---|---|
| C1 | Module boundaries for the eight layers of `01 §3` — one package or several? | The policy layer must be swappable and the substrate must be swappable; the boundaries should make both natural and make layer-skipping awkward. |
| C2 | Where do `ToolSpec` registrations live — code, declarative files, or a plugin discovery mechanism? | 52 entities from Part A. Adding a tool should not require touching the composer or the validator. |
| C3 | Where do skill documents live relative to `ToolSpec`s, and how are they versioned together? | A skill doc that drifts from its spec silently misleads the policy. |
| C4 | How are campaign artifacts laid out on shared storage? | Must support the append-only tree, checkpoint/recovery, and P4 artifacts that arrive after an agent restart. |
| C5 | Packaging and environment strategy given Part A's Python floor conflict (IMPRESS ≥3.9, foundry ≥3.12) and container-first deployment. | Determines whether tools are in-process imports or subprocess/container boundaries — currently the latter. |
| C6 | Test strategy against the mock backend (`07 §3`). | Full campaigns must run on a laptop with stubbed science, or HPC iteration cost dominates development. |

## For Phase 2 — middleware

| # | Question |
|---|---|
| M1 | Which `radical.asyncflow` constructs express the composed DAG; `executable_task` vs. a function-task form per pattern. |
| M2 | `DragonExecutionBackend` configuration and resource-shape semantics; multi-node behaviour. |
| M3 | Where `radical.adr`, `flowgentic`, `radex`, and `radical.orbit` fit — named for the project but not yet placed. |
| M4 | Whether asyncflow offers cancellation adequate for backtracking and `stop` (`07 §2`). |
| M5 | Telemetry: IMPRESS's manager exposes a subscription hook; is there an equivalent worth adopting? |
| M6 | Where the control-plane adapter process runs — compute, login, or service node — given leadership-machine network topology. |
| M7 | Whether P4 external submission is expressible through a rhapsody backend or needs a separate path. |

## For Phase 4 — implementation

| # | Question |
|---|---|
| I1 | **LangGraph vs. Academy for policy A's four-node loop.** ChemGraph demonstrates LangGraph working at `langgraph==1.2.11` with SQLite checkpointing and `interrupt`-based HITL, and also depends on `academy-py`. Both are in scope; the choice is Phase 4's. |
| I2 | Structured-output mechanism for LLM policies — schema-validated decisions, per `02 §3`'s critique of string-match parsing. |
| I3 | LiteLLM (Part A's recommendation, AgentRosetta's choice) vs. per-provider integrations (ChemGraph's choice). |
| I4 | Which tools get LLM-driven task agents in the first implementation (`04 §2` proposes RosettaScripts authoring, ligand setup, failure triage). |
| I5 | Pareto implementation — adopt `paretoset` as recommended, or implement natively. |

## Unresolved within Part B — flagged, not deferred silently

These are genuine gaps in the design as it stands, not questions for another phase.

**1. Novel silent failure is not solved.** `05 §9` states this plainly: the regime prevents every failure
mode Part A catalogued per tool, but a failure in a tool combination no human reviewed, of a kind no
`ToolSpec` anticipated, is caught only by statistical defences (cross-tool consistency, distributional
checks). This is the residual cost of free graph composition and belongs in any scientific write-up of a
campaign. The graduated mitigation — start with a composition allowlist drawn from canonical patterns, widen
with confidence — is a configuration of the same machinery, and is recommended for early operation.

**2. The agent cannot author scientific hypotheses in enzyme design.** Part A found theozyme and constraint
authoring is expert mechanistic judgement that fails silently. Part B's architecture accommodates a supplied
theozyme and varies parameters around it, but the hypothesis itself remains human-supplied. Autonomy in that
problem class is therefore narrower than in the other three, and campaigns should say so.

**3. The loop closes *in silico* only.** Carried forward from Part A: nothing ingests experimental data. The
Pareto front ranks predicted quantities. A campaign's output is a prioritized hypothesis set, not validated
designs — the distinction matters for how results are reported.

**4. Cross-tool consistency checks assume tool independence.** `05 §8` uses agreement between tools as a
correctness signal, but tools sharing training data or architecture may agree *because* they share a bias.
ESMFold and Boltz agreeing tells us less than it appears to. Which tool pairs are genuinely independent is an
open empirical question, and the weighting of this signal should stay conservative until it is answered.

**5. Budget estimation quality is unmeasured.** Gate 5 refuses graphs on estimates from Part A's T5, which
are order-of-magnitude figures from literature and documentation, not measurements on our platforms. Early
campaigns should record actual-vs-estimated cost per tool and recalibrate. Until then the gate should apply a
safety margin rather than be treated as precise.

## Two decisions worth revisiting after first operation

| Decision | Revisit if |
|---|---|
| **Control model fixed at launch** (`02 §7`) | Campaigns routinely exhaust one policy's usefulness partway through. The `fallback_policy` mechanism already proves a controlled transition is implementable; generalizing it is a contained change. |
| **Free graph composition** (`05`) | Either direction. If validation proves sufficient, widen from the recommended allowlist. If novel silent failures appear in practice, narrow toward parameters-only — the architecture supports both without restructuring, since the composer is one component. |
