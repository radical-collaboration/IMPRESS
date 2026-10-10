# 09 — Measurement and the Experimental Seam

**Origin.** Parts A and B both recorded that the loop closes *in silico* only: nothing ingests experimental
data, and the Pareto front ranks predicted quantities. The decision to add developability surrogates
(solubility, expression, aggregation) came with a requirement attached — they must be designed so they can
later be **replaced or supplemented by tools querying experimental results from a robotic lab.**

That requirement is not satisfied by a future integration project. It is satisfied now, by refusing to model
"predicted solubility" and "measured solubility" as different things.

## 1. The core move: one property, two sources

A predicted solubility and a measured solubility answer the **same question with different authority**. If
they are modelled as unrelated quantities — `pred_solubility` and `exp_solubility` — then every objective
definition, every Pareto computation, every policy prompt and every skill document that mentions solubility
has to be rewritten the day the first assay returns. That is the failure this section exists to prevent.

```python
# Illustrative notation.

@dataclass(frozen=True)
class Property:
    name: str                      # "solubility" — the scientific quantity, not its source
    value: float | Categorical
    unit: str | None
    source: PropertySource         # see §2
    confidence: Confidence         # interval, class probability, or a declared qualitative band
    observed_at: datetime
    provenance: ProvenanceRef      # tool + version, or assay + instrument + operator
```

`name` identifies the quantity. `source` identifies where the answer came from. **An objective is declared
against `name`**, so a campaign objective reading `minimize aggregation_propensity` is satisfiable by a
surrogate today and by an assay tomorrow with no change to the campaign specification, the policy, or the
front.

## 2. Source classes

```python
class PropertySource(Protocol):
    name: str
    kind: Literal["predicted", "measured"]
    latency_class: Literal["inline", "job", "external_long"]
    authority: int                 # higher wins on conflict; see §4
    async def request(self, node: DesignNode) -> Property | Pending: ...
```

| Source | `kind` | `latency_class` | Pattern | Authority |
|---|---|---|---|---|
| NetSolP / Protein-Sol / CamSol surrogate | predicted | inline / job | P1, P6 | low |
| ESM likelihood as weak proxy | predicted | job | P1 | lowest |
| Physics calculation (e.g. `cartesian_ddg`) | predicted | job | P2 | low-medium |
| **Robotic-lab assay** | **measured** | **external_long** | **P8 (§3)** | **highest** |
| Literature / historical experimental value | measured | inline | P5/P6 | high |

`authority` is an integer rather than a boolean because measurements disagree too: a single-replicate
screen and a triplicate validated assay are both `measured` and are not equally believable.

## 3. A new compute pattern: P8 — external experiment

Part A's taxonomy is organized by **scheduling implication**, and a wet-lab assay has one that none of P1–P7
capture. P4 (external HPC job) is the closest and is still wrong: a P4 job completes in hours and the agent
polls it; an assay completes in **days to weeks**, long after the campaign cycle that requested it, and
possibly after the campaign has terminated.

| | P4 — external HPC job | **P8 — external experiment** |
|---|---|---|
| Latency | minutes–hours | **days–weeks** |
| Completion | agent polls | **out-of-band callback** |
| Outlives the cycle | sometimes | **always** |
| Outlives the campaign | no | **often** |
| Cost model | node-hours | consumables, instrument time, human time |
| Failure | job dies | assay fails, sample lost, result ambiguous |

**P8 is forward-declared, not implemented in Phase 1.** No tool in the current roster is P8. It exists in the
taxonomy so that the data model, the storage layout and the control plane are shaped correctly now, when
doing so is nearly free, rather than retrofitted later, when it would not be.

## 4. Conflict: measured versus predicted on the same node

When a node acquires a measured value for a property it already has a predicted value for:

1. **The measurement supersedes the prediction** for objective evaluation and Pareto ranking — higher
   `authority` wins.
2. **The prediction is not deleted.** It is retained with its supersession recorded. The predicted/measured
   pair is itself valuable data: a systematic gap between a surrogate and its assay is exactly the signal
   that tells you the surrogate is miscalibrated for your design space.
3. **The Pareto front is recomputed**, and the node may enter or leave it. A node promoted on an optimistic
   prediction can be demoted by its own assay, which is the mechanism working correctly.
4. **Nodes without the measurement are not penalized.** A front mixing measured and predicted values for the
   same objective must record which is which, so the ranking is not silently comparing two different levels
   of evidence. Front entries therefore carry an evidence annotation.

Point 3 has a consequence worth stating: **the Pareto front is not monotonic once measurements arrive.**
Anything consuming it must tolerate a candidate it was previously shown being withdrawn.

## 5. Out-of-band arrival

A measurement is **not a task result.** It does not belong to the cycle that requested it and frequently does
not belong to a running campaign at all. It is an **update to an existing design node**, arriving through the
control plane:

```python
# An addition to CampaignControlPlane (06)
async def ingest_measurement(
    self, campaign_id: CampaignId, node_id: NodeId, prop: Property
) -> IngestResult: ...
```

Placing this on the control plane rather than inventing a new channel is the natural fit: mode 2 already
exists to let an external system interact with a campaign informedly, and a robotic lab is precisely such a
system. It also means ingestion is subject to the same validation and provenance discipline as steering —
a measurement for an unknown node, an unknown property, or an implausible value is rejected and logged, not
silently absorbed.

Three states the campaign may be in when a measurement lands:

| Campaign state | Behaviour |
|---|---|
| **Running** | Node updated, front recomputed, policy sees it in the next `CampaignObservation` |
| **Paused** | Ingested and recorded; front recomputed on resume |
| **Terminated** | **Still ingested.** The campaign record is append-only and outlives execution; a terminated campaign accumulating assay results is the normal case, not an error |

The last row is why `03`'s storage layout is append-only JSONL on a shared filesystem rather than in-process
state. A campaign directory is a scientific record that keeps receiving evidence after the job exits.

## 6. What a measurement needs that a prediction does not

Prediction provenance is a tool id, a version and a checkpoint hash. Measurement provenance is richer, and
the extra fields are what make a result interpretable or reproducible at all:

- Assay identity and protocol version
- Instrument and laboratory
- Conditions — buffer, temperature, pH, concentration, expression host
- Replicate count and dispersion, not just a central value
- Sample lineage — which construct, which prep, which plate/well
- Dates for both sample and measurement
- Explicit failure and ambiguity states (`assay_failed`, `below_detection`, `inconclusive`), which have no
  analogue in a predictor that always returns a number

That last point deserves emphasis. A predictor is total; an assay is not. `below_detection` is information,
and coercing it to zero or discarding it both corrupt the record.

## 7. The minimal abstraction

Everything above reduces to four commitments, all cheap to make now:

1. **Objectives are declared against property *names*, never against sources.**
2. **`Property` carries `source`, `authority` and `confidence`** as first-class fields.
3. **Node records are append-only**, so a later measurement supersedes rather than overwrites.
4. **`ingest_measurement` exists on the control plane**, and campaign storage accepts writes after
   termination.

With these in place, adding a robotic lab later is registering a new `PropertySource` with
`kind="measured"` and wiring its callback — not redesigning the campaign model.

## 8. Honest limits

- **This does not make the loop autonomous over the wet lab.** Nothing here decides *which* designs to send
  for assay, or manages samples, or schedules instrument time. It makes the results *ingestible and
  authoritative* when they arrive. Closing the design–build–test–learn loop is a larger project.
- **Surrogates remain weak.** Being architecturally interchangeable with measurements does not make them
  accurate. `briefs/developability-surrogates.md` reports what they are actually worth, and the honest
  expectation is soft ranking signals rather than accept/reject gates.
- **A predicted/measured gap analysis needs volume.** The most valuable product of this seam — surrogate
  recalibration against real assays — requires enough paired observations to be meaningful, which no early
  campaign will have.
