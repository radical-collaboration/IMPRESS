# 03 — Campaign Storage Layout

Answers Part B's C4. The layout must support four things simultaneously: an **append-only** design tree,
**checkpoint and recovery** at cycle boundaries, **P4 artifacts arriving after an agent restart**, and a
**provenance record** complete enough to replay.

## 1. Two roots, deliberately separate

```
$IMPRESS_A_SHARED/                     # spans campaigns — survives any single campaign
├── cache/
│   ├── p5/                           # HTTP response cache, keyed by request hash
│   └── msa/                          # MSA cache — the highest-value entry (Part A R3)
├── checkpoints/                      # model weights, with recorded hashes
└── containers/                       # built .sif images

$IMPRESS_A_CAMPAIGNS/<campaign_id>/    # one campaign, self-contained
├── spec.yaml                         # immutable; written once at submit
├── provenance/
│   ├── campaign.json
│   ├── decisions.jsonl
│   ├── graphs.jsonl
│   ├── executions.jsonl
│   ├── results.jsonl
│   └── transitions.jsonl
├── state/
│   ├── tree.jsonl                    # append-only DesignNode records — the source of truth
│   ├── checkpoint-000042.json        # derived snapshot: front, budget, cursors
│   └── latest.json -> checkpoint-000042.json
├── jobs/
│   └── ledger.jsonl                  # P4 durable job ledger
├── artifacts/
│   └── <node_id>/                    # structures, sequences, trajectories, score files
├── logs/
└── SUMMARY.md                        # written at termination
```

**The P5 cache is shared, not per-campaign.** This is the single most consequential placement decision here.
Part A found the ColabFold MSA server is a free academic resource (~few thousand MSAs/day globally) that two
Core tools default to. A per-campaign cache would re-fetch the same MSAs on every re-run and for every
parallel campaign on the same targets. Shared, keyed by request hash, it is the cheapest available mitigation
for R3 and for re-run cost both.

## 2. Append-only `tree.jsonl` with derived checkpoints

The design tree is stored as an append-only JSONL log, not a serialized object graph.

| Property | Why it matters |
|---|---|
| A crash mid-write loses at most one trailing record | A corrupt snapshot could lose the whole campaign |
| Node history is inspectable with `tail`/`grep` on a login node | Operability on HPC, where attaching a debugger is not realistic |
| Status changes append rather than mutate | Part B `03 §2` requires non-destructive backtracking |
| Concurrent readers need no lock | The control plane can `observe` while the manager writes |

`checkpoint-NNNNNN.json` is a **derived** snapshot — Pareto front, budget ledger, cursors — written at each
cycle boundary purely so recovery does not replay the whole log. If a checkpoint is missing or corrupt, the
tree is replayed from `tree.jsonl` and the checkpoint is regenerated. **The log is the source of truth; the
checkpoint is an index.**

## 3. Recovery

Part B `03 §7` fixed cycle boundaries as the only recovery points. Concretely:

1. Load `latest.json`; if unusable, replay `tree.jsonl`.
2. Read `jobs/ledger.jsonl` and reconcile every open P4 job: completed (collect artifacts), still running
   (re-attach), or dead (mark failed).
3. Discard any partially-executed graph from the interrupted cycle and re-run it.
4. Resume at the next cycle boundary.

Step 3 is a deliberate cost. A half-finished DAG whose task agents did not all run their QC gates is exactly
the silent-failure case Part A warns about; re-running is cheaper than reasoning about which outputs were
validated.

## 4. Artifacts

Artifacts are stored **per node**, not per tool, because the node is the unit the Pareto front ranks and the
unit a scientist inspects. `ArtifactRef` holds a path plus a content hash; large binaries are never inlined
into JSONL.

Retention is declared per campaign, because trajectories dominate: keeping every frame of every MD run on a
multi-day campaign is not affordable. Policy options — keep-all, keep-Pareto-front-lineages, keep-final-only
— with the default keeping full artifacts for nondominated lineages and metrics-only for pruned ones. The
metrics are never discarded; only the bulk coordinates are.

## 5. The `campaign_id`

Human-readable and sortable, since these accumulate: `<date>-<goal-slug>-<short-hash>`, e.g.
`20260921-stabilize-lysozyme-a3f9c1`. The hash covers the full spec, so two campaigns with identical
specifications are visibly related and an accidental duplicate submission is recognizable.

## 6. What this layout makes possible

- **Replay.** `decisions.jsonl` plus `spec.yaml` is sufficient input to model D's replay policy (Part B
  `02 §5`) — provenance becomes an executable artifact.
- **Golden campaigns.** A recorded campaign becomes a regression fixture (`05`).
- **Post-hoc analysis outside the agent.** Everything is JSONL and files on a shared filesystem; a scientist
  can pandas the whole campaign without running or understanding the agent.
- **Cross-campaign learning later.** Shared cache and uniform per-campaign layout mean a future component
  could mine completed campaigns. Nothing in Phase 1 does this, but the layout does not preclude it.
