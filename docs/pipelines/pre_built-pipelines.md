# IMPRESS Adaptive Pipeline - Protein Binding HPC Use Case

This documentation walks through a real-world, computationally intensive IMPRESS adaptive pipeline for protein binding analysis that runs on High-Performance Computing (HPC) systems with GPU requirements.

## Use Case Overview

This example demonstrates adaptive optimization for AlphaFold protein structure analysis where:
- Each protein requires at least 1 GPU for processing
- Pipelines adaptively spawn children based on protein quality degradation
- Underperforming proteins are migrated to new pipeline instances for re-optimization
- Runs on HPC infrastructure (Purdue Anvil GPU cluster)

## Adaptive Components Breakdown

### 1. Adaptive Criteria Function

```python
async def adaptive_criteria(current_score: float, previous_score: float) -> bool:
    """
    Determine if protein quality has degraded requiring pipeline migration.
    """
    return current_score > previous_score
```

**Adaptive Logic:**
- **Simple but effective**: Higher scores indicate degraded protein quality
- **Comparison-based**: Evaluates current vs previous protein structure scores
- **Migration trigger**: Returns `True` when quality degrades, triggering protein migration

### 2. Core Adaptive Decision Function

The main adaptive intelligence is implemented in `adaptive_decision()`:

```python
async def adaptive_decision(pipeline: ProteinBindingPipeline) -> Optional[Dict[str, Any]]:
    MAX_SUB_PIPELINES: int = 3
    sub_iter_seqs: Dict[str, str] = {}

    # Read current scores from CSV output
    file_name = f'af_stats_{pipeline.name}_pass_{pipeline.passes}.csv'
    with open(file_name) as fd:
        for line in fd.readlines()[1:]:
            # Parse protein scores from AlphaFold output
            name, *_, score_str = line.split(',')
            protein = name.split('.')[0]
            pipeline.current_scores[protein] = float(score_str)
```

**Score Processing:**
- **File-based communication**: Reads AlphaFold statistics from CSV files
- **Dynamic score tracking**: Updates current protein quality scores
- **Real-time evaluation**: Processes actual computational results

### 3. Adaptive Migration Logic

```python
    # First pass — establish baseline
    if not pipeline.previous_scores:
        pipeline.logger.pipeline_log('Saving current scores as previous and returning')
        pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)
        return

    # Identify proteins that deteriorated
    sub_iter_seqs = {}
    for protein, curr_score in pipeline.current_scores.items():
        if protein not in pipeline.iter_seqs:
            continue

        decision = await adaptive_criteria(curr_score, pipeline.previous_scores[protein])

        if decision:
            sub_iter_seqs[protein] = pipeline.iter_seqs.pop(protein)  # Remove from current pipeline
```

**Migration Decision Process:**

1. **Baseline establishment**: First pass saves scores as reference
2. **Protein evaluation**: Each protein is individually assessed
3. **Selective migration**: Only degraded proteins are moved to child pipelines
4. **Pipeline cleanup**: Migrated proteins are removed from parent pipeline

### 4. Child Pipeline Creation and Resource Management

```python
    # Spawn new pipeline for underperforming proteins
    if sub_iter_seqs and pipeline.sub_order < MAX_SUB_PIPELINES:
        new_name: str = f"{pipeline.name}_sub{pipeline.sub_order + 1}"

        pipeline.set_up_new_pipeline_dirs(new_name)

        # Copy PDB files for migrated proteins
        for protein in sub_iter_seqs:
            src = f'{pipeline.output_path_af}/{protein}.pdb'
            dst = f'{pipeline.base_path}/{new_name}_in/{protein}.pdb'
            shutil.copyfile(src, dst)

        # Configure child pipeline
        new_config = {
            'name': new_name,
            'type': type(pipeline),
            'adaptive_fn': adaptive_decision,  # Recursive adaptivity
            'config': {
                'passes': pipeline.passes,
                'iter_seqs': sub_iter_seqs,           # Only degraded proteins
                'seq_rank': pipeline.seq_rank + 1,
                'sub_order': pipeline.sub_order + 1,
                'previous_scores': copy.deepcopy(pipeline.previous_scores),
            } 
        }

        pipeline.submit_child_pipeline_request(new_config)
```

**Resource and Data Management:**
- **File system operations**: Creates directories and copies PDB files for migrated proteins
- **Selective data transfer**: Only problematic proteins are moved to child pipelines
- **Configuration inheritance**: Child pipelines inherit optimization parameters
- **Recursive adaptivity**: Child pipelines can also spawn their own children

### 5. Pipeline Lifecycle Management

```python
        pipeline.finalize()

        if not pipeline.fasta_list_2:
            pipeline.kill_parent = True
```

**Lifecycle Control:**
- **Parent finalization**: Completes current pipeline processing
- **Conditional termination**: Parent pipeline can terminate if no remaining work
- **Resource optimization**: Prevents idle pipeline instances

### 6. HPC Resource Configuration

```python
async def impress_protein_bind() -> None:
    manager: ImpressManager = ImpressManager(
        execution_backend=RadicalExecutionBackend({
            'gpus': 2,                           # GPU allocation per pipeline
            'cores': 32,                         # CPU cores per pipeline
            'runtime': 13 * 60,                  # 13 hours maximum runtime
            'resource': 'purdue.anvil_gpu'       # HPC cluster specification
        })
    )

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name='p1',
            type=ProteinBindingPipeline,
            adaptive_fn=adaptive_decision
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)
```

**HPC Integration:**
- **GPU allocation**: 2 GPUs per pipeline for intensive AlphaFold calculations
- **Resource specification**: 32 CPU cores and 13-hour runtime limits
- **Cluster targeting**: Specifically configured for Purdue Anvil GPU cluster
- **Scalable architecture**: Framework handles resource allocation for child pipelines

## Adaptive Execution Flow

1. **Initial pipeline** starts with full protein set on HPC with GPU resources
2. **AlphaFold processing** generates protein structure quality scores
3. **Adaptive evaluation** compares current vs previous scores per protein
4. **Migration decision** identifies degraded proteins for re-optimization
5. **Child pipeline creation** moves problematic proteins to new pipeline instance
6. **Resource allocation** HPC system allocates GPUs/CPUs to child pipeline
7. **Recursive optimization** child pipelines can further adapt and spawn children
8. **Resource cleanup** completed pipelines release HPC resources

## Key Adaptive Features for HPC

- **Performance-based adaptation**: Real computational results drive pipeline decisions
- **Resource-aware scaling**: GPU/CPU resources allocated per pipeline instance
- **Data locality**: PDB files copied to maintain data proximity
- **Hierarchical optimization**: Multi-level pipeline spawning for complex optimization
- **HPC integration**: Native support for cluster resource management
- **Fault tolerance**: Pipeline termination and resource cleanup mechanisms
