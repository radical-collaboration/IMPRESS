# Code on the slides

Every on-slide code block, keyed `S<slide>-<letter>`, with its anchor and what was done to
it. The rule: **behaviour is never edited.** A block may be shortened, re-wrapped or
stripped of type annotations so it is legible at projector size, but it must not imply the
code does something it does not. Anyone who greps the file and finds something different
should find the difference already written down here.

`anchors.json` holds every `file:line` these slides print, and
`check_anchors.py --anchors agent/slides/api/anchors.json --root .` verifies them, run from
the **IMPRESS repo root**. The table was `agent/`-relative until the live slides arrived; two
of its entries now point into `examples/agentic_small_molecule_binding/`, so it uses the same
root as the sibling deck's. Paths below are written relative to `agent/` for readability.

| Mark | Meaning |
|---|---|
| VERBATIM | byte-for-byte, including indentation |
| TRIMMED | whole lines removed; every line shown is unaltered |
| EDITED | some line was changed — each change is named below |
| ILLUSTRATIVE | written for the slide, showing the shape of real output |
| MINED | produced by `run_model.py` from a real run |

---

### S4-A · the loop · ILLUSTRATIVE
`observe -> DECIDE -> compose -> validate -> execute -> analyze -> update -> terminate?`

The arrow line from `manager.py`'s module docstring, set as a code block. Anchor:
`manager.py:82` is cited in the slide footer for the coroutine race, not for this line.

### S9-A · a campaign file · TRIMMED
`campaigns/delta-small-molecule.yaml:30`

Lines removed: the header comment, `backend*`, `max_cycles`, `stagnation_limit`, `site`,
`budget`, the `ligandmpnn_design`/`packmin`/`fastrelax`/`filter_shape` param blocks, and
the `concurrency` key. The SMILES string is truncated with `...` — the real value is
complete in the file. Every line shown is otherwise unaltered, including the inline
comments on `replicas` and `stages`.

### S10-A · the ControlPolicy contract · EDITED
`policy/base.py:19`

Changes: the class docstring is removed; `interpret`'s signature is shortened from
`(self, results: RunOutcome, obs: CampaignObservation)` to `(self, results: RunOutcome, obs)`
and `on_rejected`'s from `(self, decision: Decision, failure: ValidationFailure)` to
`(self, decision, failure: ValidationFailure)`, both to fit one line each. No member is
added or removed, and the three methods are in source order.

### S10-B · the Decision union · VERBATIM
`core/decision.py:56`

### S11-A · ExperimentIntent · EDITED
`core/decision.py:21`

Changes: the docstring is removed, and `Field(default_factory=list)` / `Field(default_factory=dict)`
are shown as `[]` / `{}`. Defaults are unchanged in meaning. The `# tool ids, in order`
comment is kept because it is the point of the slide.

### S12-A · a tool as a declaration · TRIMMED
`toolkits/rfd3/tools/rfd3_design/spec.yaml:1`

Lines removed: `gpu_portability`, the `num_designs`, `seed` and `input_spec_path`
parameters with their comments, and the measured-cost comment above `cost_model`. The
`diffusion_steps` block is re-wrapped onto two lines to fit; its values are unaltered.

### S12-B · loading is validating · EDITED
`tools/spec.py:100`

Two checks lifted out of `_defaults_within_range`, in source order, with `...` marking the
gap. The second `raise`'s message is shortened: the file's is
`f"{self.id}: acceptance gate on {g.params.get('metric')!r} needs an integrity metrics_reported gate naming it"`,
the slide shows `"... needs an integrity metrics_reported gate naming it"`. The condition
is unaltered.

### S13-A · gates are enforced in post_process · TRIMMED
`tools/agent.py:110`

Lines removed: the `cost=dict(self.spec.cost_model.cost)` argument, shown as `...`. The
docstring line shown is the real one.

### S14-A · the five gates · VERBATIM
`compose/validate.py:30`

### S19-A · the pattern signature · VERBATIM
`compose/graph.py:51`

The body only — the `def` line and docstring are not shown, and the slide's own card quotes
the docstring's claim ("SHAPE ONLY") in prose. The `# <- one entry PER NODE` comment is
**added by the slide** and is marked as such by being the only comment in the block; it is
not in the file.

### S21-A · the command · VERBATIM
`README.md`, and `campaigns/delta-small-molecule.yaml` exists

One line, exactly as the README and `CLAUDE.md` document it. It is the only command on a slide
in this deck.

### S25-A · preflight output · ILLUSTRATIVE
`cli/__init__.py:252`

Written for the slide. It is the real output format — `[ok  ]`/`[FAIL]`/`[warn]`, the
column widths, the trailing count line — with real check names and real failure strings
taken from the source, but the paths are placeholders (`/work/nvme/<project>/<user>`) and
the particular combination of results is assembled, not captured. No run produced exactly
this screen. The counts in the last line are consistent with the rows shown.

### S27-A · the import contract · TRIMMED
`tests/test_layering.py:43`

Three of the ten rows, with `...` for the rest. The full table is on the same slide as a
rendered figure, mined from this file by `run_model.py`.

### B2-A · the type lattice · EDITED
`core/types.py:35` (`unifies_with`)

Changes: each `if` body is folded onto its `if` line, and the docstring is removed. One
comment is kept verbatim because it carries the asymmetry the slide is about. Conditions
and return values are unaltered.

---

## Figures that are not code

- **S17, the per-cycle bars and the event table** — MINED from `run.json`'s `mock.timeline`,
  which `run_model.py` derives from the campaign's own provenance timestamps.
- **S19, the signature table** — MINED from `mock.widths_per_signature`.
- **S14, the refusal box** — MINED from `mock.refusals[0]`; the quoted reason string is the
  one the interlock wrote.
- **S27, the layer rows** — MINED from `surfaces.layering`, read out of `test_layering.py`
  by `ast`.
- **S7, the seven stages** — a figure, not a quotation: each box names the file that does that
  step and nothing is quoted from it, so the anchors carry the whole claim. The counts in the
  TASKS box (`mock.n_results`, `mock.lineages_absorbed`) are MINED.
- **S6, the four inbound groups** — every count MINED from `surfaces` and `code`: tools,
  toolkits, `CampaignSpec` fields, control models, policy methods, control-plane operations,
  provenance records and kinds.
- **S21, the five steps** — every figure in the narrative is MINED from `mock`: the spec's
  field count, the lineages asked for and admitted, the stop reason in the engine's own words,
  the front size, and the provenance and ledger counts.
- **S22, the refusal transcript** — MINED from `mock.refusals[0]`, formatted as two lines for
  the slide. The reason string and `transient=true` are the interlock's own.
- **S23 and S24, every figure** — **TRANSCRIBED** from
  `examples/agentic_small_molecule_binding/CLAUDE.md`, which records each Delta job; held in
  `run.json` under `live.runs` with a `source` field, and both slides repeat that source in
  their footers. The tool count beside them is MINED from that example's `tools.py`, as is the
  count of methods it overrides — which is how the deck knows the two arms still differ only in
  their decision layer.
- **B1, the pattern table** — the `Pattern` members are MINED; the "meaning" and
  "scheduling implication" columns are written for the slide from the enum's own comments.
