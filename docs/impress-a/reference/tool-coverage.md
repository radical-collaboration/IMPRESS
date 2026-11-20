# Tool Coverage

What the test suite asks of each real tool, and what it does not. One row per tool, one column
per question, every cell in exactly one of three states:

| state | means |
|---|---|
| **covered** | a named test asserts it, and the name is cited so a reader can run it |
| **gap** | checkable without hardware and not checked — these are bugs waiting, and the ones this page found are now closed |
| **hardware** | only answerable on a GPU with the real binary, so it becomes an M2 criterion with a job id |

**Why this page exists.** Four findings in one week came from exercising a single tool at a time,
and each was a *silent* failure: a conditioning key the model never saw, a duplicate id that
disabled a toolkit, an empty registry that satisfied its goals, a type hint that lied. The suite
is strong on what a tool **declares** and thinner on whether the tool **did what was asked** —
not a criticism of it, a consequence of the questions being new. This page asks them of all six.

**The four questions**, in the order they bite:

1. **Was it conditioned on what we asked?**
2. **Does it declare a key the binary ignores?**
3. **Does every declared metric arrive?**
4. **Does it fail loudly on bad input?**

## The matrix

`tests/test_real_toolkits.py` unless another file is named. `CHAIN` marks a test parametrised
over all six tools.

| tool | 1. conditioned | 2. dead key | 3. metrics arrive | 4. fails loudly |
|---|---|---|---|---|
| `rfd3_design` | **covered** — `test_check_ligand_smiles_catches_the_silent_wrong_answer` (an empty `ligand_smiles` models no ligand rather than failing). **hardware** for the model input: see *question 1 splits*, below | **covered** — `test_every_declared_parameter_reaches_its_command` (CHAIN); `test_rfd3_partial_diffusion_would_have_to_drop_length` guards the `length`/`partial_t` pair | **covered** — `test_the_rfd3_sidecar_metrics_come_from_the_shape_rfd3_actually_writes`, against a real `*_model_*.json` from job 23670171 | **covered** — `test_a_missing_environment_variable_names_itself` (`FOUNDRY_SIF_PATH`); `test_subprocess_error_survives_the_worker_boundary` |
| `ligandmpnn_design` | **covered** — `test_ligandmpnn_passes_fixed_residues_through` | **covered** — CHAIN; `test_every_declared_parameter_reaches_its_command` caught `num_seqs` doing nothing | **covered** — `test_the_mpnn_parser_reads_every_candidate_not_the_first`, `test_an_unreadable_header_is_skipped_rather_than_scored_zero`, `test_select_best_skips_a_member_whose_metric_cannot_be_read` | **covered** — `test_a_missing_environment_variable_names_itself` (`MPNN_DIR`); `test_an_unwired_required_input_refuses_and_names_the_port` (`backbone`); the three `..._mpnn_shim_...` tests |
| `packmin` | **covered** — `test_rosetta_toolkits_accept_a_ligand_params_path` | **covered** — CHAIN | **covered** — `test_no_rosetta_metric_is_defaulted_to_zero` | **covered** — `test_an_unwired_required_input_refuses_and_names_the_port` (`structure`) |
| `fastrelax` | **covered** — `test_rosetta_toolkits_accept_a_ligand_params_path`; `test_the_fastrelax_worker_computes_interaction_energy_by_selector` | **covered** — CHAIN; `test_packmin_does_not_gate_on_a_relaxed_score` keeps the convergence call where it belongs | **covered** — `test_no_rosetta_metric_is_defaulted_to_zero` | **covered** — `test_an_unwired_required_input_refuses_and_names_the_port` (`structure`) |
| `filter_shape` | **covered** — `test_filter_shape_measures_the_protein_ligand_interface` (backlog G5: `jump="1"` measured whatever jump 1 happened to be) | **covered** — CHAIN | **covered** — `test_no_rosetta_metric_is_defaulted_to_zero`; `sc_selector_mode` is reported as provenance so two campaigns' numbers cannot be compared without noticing they measured different interfaces | **covered** — `test_an_unwired_required_input_refuses_and_names_the_port` (`structure`) |
| `boltz_predict` | **covered** — `test_check_ligand_smiles_catches_the_silent_wrong_answer`; `test_boltz_spec_is_valid_yaml` (its `msa:` key sat one level too deep) | **covered** — CHAIN | **covered** — `test_the_sampled_tools_declare_what_the_adapter_reports` (`ensemble_size`/`ensemble_paired` come from the adapter, not the tool) | **covered** — `test_a_missing_environment_variable_names_itself` (`BOLTZ_CACHE`); `test_an_unwired_required_input_refuses_and_names_the_port` (`structure`); both `..._boltz_cache_guard_...` tests |

Every tool is also covered for the argv it runs (`test_the_command_each_real_tool_runs_at_its_spec_defaults`,
all six in one test), its seed and optional flags (`test_a_seed_and_the_optional_flags_reach_each_command`),
its declared cost against measurement (`test_cost_models_are_within_an_order_of_magnitude_of_measurement`,
`test_the_offered_wall_ceiling_covers_every_measured_task_time`) and its per-lineage seed
independence (`test_real_tools_get_an_independent_reproducible_seed_per_lineage`).

## What the audit changed

**Nine tests were added, all in question 4, and the gap was the same one in every tool.** Every
adapter in this package honours the authoring guide's own rule — *"Check environment variables
first, and raise: a missing variable should name itself, not surface as a tool's own confusing
failure"* — and **no test asserted a single one of those refusals.** The suite set the variables
and never removed one: before this audit there was exactly one `monkeypatch.delenv` in 2,064
lines, and it was for `WORK_DIR` in an unrelated test.

Eight refusals were unexercised: three missing-environment-variable raises
(`FOUNDRY_SIF_PATH`, `MPNN_DIR`, `BOLTZ_CACHE`) and five unwired-required-input raises
(`backbone` once, `structure` four times). They are now two parametrised tests plus a third that
**greps the four adapter modules and asserts the count matches** — so a refusal added later
without a case fails that test rather than sitting unexercised, which is how these eight came to
exist.

Two reasons this was worth closing rather than noting. A refusal nobody exercises can be deleted
or weakened by a refactor with every test still green. And **the message is the deliverable, not
the exception**: these fire on a login node during a dry run, where `FOUNDRY_SIF_PATH is not set`
ends the investigation and a bare `FileNotFoundError` three frames inside a container starts one.

## Question 1 splits, and only half of it is answerable here

**"Was it conditioned on what we asked" is two questions**, and conflating them is how a silent
failure survives a green suite:

* **1a — did the adapter pass it?** Covered for all six, above. This is what
  `test_every_declared_parameter_reaches_its_command` and the golden-argv test answer.
* **1b — did the binary honour it?** **Hardware, always.** A parameter the adapter correctly
  passes and the tool quietly discards cannot be seen from outside the tool.

There is one measured instance of 1b and it is the reason this distinction is written down.
RFD3's `select_hotspots` resolves, annotates the six requested atoms on `atom_array_input`, and
is then dropped by `DesignInputSpecification.build()` — so the network sees all zeros while the
run completes, writes its outputs and exits 0 (job `24155612`; `toolkits/rfd3/SKILL.md`,
Pitfalls). No test in this repository could have found that, and none can regress-test it without
a GPU and the container.

**So every 1b cell is an M2 criterion**: for each tool, one run whose declared conditioning is
read back out of what the binary actually consumed. That is the cheapest honest form of the
question, and `impress-a validate-tasks` on hardware is where it belongs.

## The label workflow

Not in this matrix, and not an omission. `md_label` and `abfe_label` are authored in the
integration project that commissioned this audit rather than in this package, and they are
audited there against the same four questions. This page covers impress-a's own six design tools.

## Reading this page later

A cell marked **covered** cites a test name; run it. A cell marked **hardware** is a claim that
no laptop can settle it, and the honest check on that claim is whether a reader can think of a
way — if they can, it was a gap. The three states are exhaustive on purpose: there is no
"probably fine".
