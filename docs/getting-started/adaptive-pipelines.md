# IMPRESS Adaptive Pipeline - Walkthrough

This documentation walks through the adaptive capabilities of the IMPRESS pipeline framework, focusing specifically on how pipelines can dynamically spawn child pipelines during execution.

## Adaptive Pipeline Components

### 1. Pipeline Configuration for Adaptivity

The `DummyProteinPipeline` class is configured to support adaptive behavior through several key attributes:

```python
def __init__(self, name: str, flow: Any, configs: Dict[str, Any] = {}, **kwargs):
    self.iter_seqs: str = 'MKFLVLACGT'
    self.generation: int = configs.get('generation', 1)           # Track generation level
    self.parent_name: str = configs.get('parent_name', 'root')    # Track parent pipeline
    self.max_generations: int = configs.get('max_generations', 3) # Limit recursion depth
    super().__init__(name, flow, **configs, **kwargs)
```

**Key adaptive attributes:**
- `generation`: Tracks the current generation level of the pipeline
- `parent_name`: Maintains lineage information
- `max_generations`: Prevents infinite recursion by setting a maximum depth

### 2. Adaptive Execution Point

The adaptive behavior is triggered at a specific point in the pipeline execution:

```python
async def run(self) -> None:
    # ... other pipeline steps ...
    
    await self.run_adaptive_step(wait=True)  # Critical adaptive execution point
    
    # ... remaining pipeline steps ...
```

**`run_adaptive_step(wait=True)`**:
- This method calls the registered adaptive function
- `wait=True` ensures the current pipeline waits for the adaptive logic to complete
- Any child pipelines spawned will be submitted to the manager at this point

### 3. Adaptive Strategy Function

The core adaptive logic is implemented in the `adaptive_optimization_strategy` function:

```python
async def adaptive_optimization_strategy(pipeline: DummyProteinPipeline) -> None:
    # Decision logic: stop if max generations reached OR random condition (50% chance)
    if pipeline.generation >= pipeline.max_generations or random.random() >= 0.5:
        return  # No child pipeline created
    
    # Generate unique name for child pipeline
    new_name = f"{pipeline.name}_g{pipeline.generation + 1}"
    
    # Configure child pipeline
    new_config = {
        'name': new_name,
        'type': type(pipeline),                    # Same pipeline class
        'config': {
            'generation': pipeline.generation + 1,  # Increment generation
            'parent_name': pipeline.name,           # Set parent reference
            'max_generations': pipeline.max_generations,
        },
        'adaptive_fn': adaptive_optimization_strategy  # Same adaptive function
    }
    
    # Submit child pipeline to manager
    pipeline.submit_child_pipeline_request(new_config)
```

**Key adaptive mechanisms:**

1. **Conditional spawning**: Uses generation limits and random conditions to decide whether to create children
2. **Configuration inheritance**: Child pipelines inherit configuration with incremented generation
3. **Recursive adaptivity**: Child pipelines use the same adaptive function, enabling multi-generational spawning
4. **Pipeline submission**: Uses `submit_child_pipeline_request()` to register new pipelines with the manager

### 4. Manager Setup with Adaptive Function

The pipeline manager is configured to support adaptive behavior:

```python
async def run() -> None:
    execution_backend = await ConcurrentExecutionBackend(ThreadPoolExecutor())
    manager: ImpressManager = ImpressManager(execution_backend)

    pipeline_setups = [PipelineSetup(name=f'p{i}',
                                     type=DummyProteinPipeline,
                                     adaptive_fn=adaptive_optimization_strategy)  # Adaptive function registered
                       for i in range(1, 4)]

    await manager.start(pipeline_setups=pipeline_setups)
```

**Critical setup element:**
- `adaptive_fn=adaptive_optimization_strategy` registers the adaptive function with each pipeline
- The manager handles the lifecycle of dynamically created child pipelines

## Adaptive Execution Flow

1. **Initial pipelines** (`p1`, `p2`, `p3`) start execution
2. Each pipeline runs its tasks until reaching `run_adaptive_step()`
3. **Adaptive function evaluates conditions** (generation limit, random chance)
4. If conditions are met, **child pipeline configuration is created**
5. **Child pipeline is submitted** to the manager via `submit_child_pipeline_request()`
6. **Manager spawns the child pipeline** and adds it to the execution pool
7. **Child pipelines repeat the process**, potentially creating their own children

## Key Adaptive Features

- **Dynamic pipeline creation**: Pipelines can spawn children during runtime
- **Configurable conditions**: Adaptive logic can be based on any runtime state
- **Generation tracking**: Built-in support for tracking pipeline lineage
- **Recursive adaptivity**: Child pipelines can also be adaptive
- **Manager integration**: Seamless integration with the IMPRESS execution manager