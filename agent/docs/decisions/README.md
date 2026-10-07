# Decision Records

Numbered, immutable records of decisions whose rationale should outlive the conversation that produced them.

**Named `decisions/`, not `adr/`,** because `radical.adr` is a middleware component this project uses and
"ADR" would be permanently ambiguous here.

| # | Decision | Phase |
|---|---|---|
| [0001](0001-impress-is-a-tool-not-the-control-plane.md) | IMPRESS is a callable tool, not the control plane | 1B |
| [0002](0002-model-c-is-control-mode-2.md) | Control model C *is* control mode 2 | 1B |
| [0003](0003-free-graph-composition-with-self-promoting-interlock.md) | Free graph composition, governed by a self-promoting interlock | 1B |
| [0004](0004-population-pareto-front-with-backtracking.md) | Population with a Pareto front and backtracking | 1B |
| [0005](0005-control-model-fixed-at-launch.md) | The active control model is fixed at launch | 1B |
| [0006](0006-hybrid-task-agents.md) | Task agents are hybrid, declared per tool | 1B |
| [0007](0007-transport-agnostic-control-plane.md) | One transport-agnostic control plane, with adapters | 1B |
| [0008](0008-platform-priority.md) | Polaris/ACCESS primary, Aurora second, Frontier deprioritized | 1 |
| [0009](0009-package-naming.md) | Package naming: `impress_a` | 1C |
| [0010](0010-single-package-with-import-contract.md) | One package, with a CI-enforced import contract | 1C |
| [0011](0011-toolkits-are-top-level-and-declarative.md) | `toolkits/` is top-level and declarative | 1C |
| [0012](0012-one-property-two-sources.md) | One property, two sources; forward-declare pattern P8 | 1 |
| [0013](0013-trust-counts-integrity-not-acceptance.md) | Trust counts integrity gates, not acceptance gates (amends 0003) | — |
