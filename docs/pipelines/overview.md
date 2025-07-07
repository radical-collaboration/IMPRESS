# 🧬 Using the Prebuilt Protein Binding Pipeline

This page explains how to use the **prebuilt Protein Binding Pipeline** provided by Impress.  
It describes what the pipeline does, and walks you through the example code step-by-step.

---

## 📋 What does the Protein Binding Pipeline do?

The pipeline implements a *protein–peptide binding design loop*:

- ✅ The user submits the **C-terminal peptide sequence**, which they want to target for binding.  
- ✅ The **ProfAff database** is queried to generate design starting points.  
- ✅ **ProteinMPNN** creates design sequences for a receptor protein.  
- ✅ The designed sequences are submitted to **AlphaFold-Multimer** for structure prediction.  
- ✅ The AlphaFold-predicted structures are fed into a **structure-aware ML model** to predict binding specificity and affinity.  
- ✅ This cycle continues iteratively, optimizing the receptor’s stability and binding affinity over time.  
- ✅ Best designs are tested in wet-lab experiments, and feedback can be incorporated into future runs.

---

## 🚀 Example Code

Here is the full example script we will walk through:

```python
import copy
import asyncio
import random

from radical.asyncflow import RadicalExecutionBackend
from impress.impress_manager import ImpressManager
from impress.pipelines.protein_binding import ProteinBindingPipeline
```

We import:

`RadicalExecutionBackend` — to run tasks asynchronously on HPC machines with multiple
CPUs and GPUs.

ImpressManager — orchestrates pipelines

ProteinBindingPipeline — the prebuilt pipeline implementation

## 🔍 Step 1️⃣: Define Adaptive Criteria

```python
async def adaptive_criteria(current_score, previous_score):
    if current_score > previous_score:
        return True
    return False
```

This small helper function compares two scores:

If the current score is worse than the previous score, return True.

This signals that the design has degraded and needs further refinement.

### 🔍 Step 2️⃣: Define the Adaptive Function

```python
async def alphafold_adaptive_fn1(pipeline):
    MAX_SUB_PIPELINES = 3
    current_scores = await pipeline.get_scores_map()
    sub_iter_seqs = {}
```

This function is passed into each pipeline to enable adaptive behavior.
It:

Reads the current and previous scores for each protein.

Checks if the score got worse (adaptive_criteria).

If yes, moves that sequence into a new sub-pipeline for further optimization.

Limits the number of sub-pipelines to `MAX_SUB_PIPELINES`.

Check proteins one by one:

```python
    for protein, score in current_scores['c_scores'].items():
        prev = current_scores['p_scores'].get(protein)
        if prev is not None and score > prev:
            if pipeline.iter_seqs.get(protein):
                bad_condition = await adaptive_criteria(score, pipeline.previous_scores[protein])
                if bad_condition:
                    sub_iter_seqs[protein] = pipeline.iter_seqs.pop(protein)
```

This loop:

For each protein, check if its score has increased (worsened).

If so, remove it from the current pipeline and prepare it for the sub-pipeline.

Create the sub-pipeline config:
```python
    if sub_iter_seqs and pipeline.sub_order < MAX_SUB_PIPELINES:
        new_name = f"{pipeline.name}_sub{pipeline.sub_order + 1}"

        new_pipe_config = {
            'name': new_name,
            'type': type(pipeline),
            'config': {
                'iter_seqs': sub_iter_seqs,
                'step_id': pipeline.step_id + 1,
                'sub_order': pipeline.sub_order + 1,
                'previous_score': copy.deepcopy(current_scores['c_scores']),
            },
            'adaptive_fn': alphafold_adaptive_fn1
        }
```

Here:

If any sequences need to be moved, and the sub-pipeline limit is not reached, build a new pipeline config.

Give it a unique name and pass the sequences and scores to it.

Termination or continuation:
```python
        if not pipeline.fasta_list:
            # no more work to do so kill the parent pipeline
            pipeline.kill_parent = True

        pipeline.submit_child_pipeline_request(new_pipe_config)            

```

Here we have a scenario where sometimes the pipeline stops (kill_parent=True) or continues.
Finally, we request a new pipeline config if one is created and send it to the manager.

### 🔍 Step 3️⃣: Start the Pipelines
Now we create and start the pipelines:

```python
async def impress_protein_bind():
    execution_backend = RadicalExecutionBackend({'resources': 'purdue.anvil', 
                                                 'cores': 128, 'gpus':4, 'walltime':60})
    manager = ImpressManager(execution_backend)
```

Here:

Create an ImpressManager, giving it the threaded execution backend.

Define pipeline setups:

```python
    await manager.start(pipeline_setups=[
        {'name': 'p1', 'config': {}, 'type': ProteinBindingPipeline, 'adaptive_fn': alphafold_adaptive_fn1},
        {'name': 'p2', 'config': {}, 'type': ProteinBindingPipeline, 'adaptive_fn': alphafold_adaptive_fn1},
        {'name': 'p3', 'config': {}, 'type': ProteinBindingPipeline, 'adaptive_fn': alphafold_adaptive_fn1},
    ])
```

We start three independent pipelines:

Each one is given a unique name (p1, p2, p3).

Each uses the prebuilt ProteinBindingPipeline class.

Each is passed the `alphafold_adaptive_fn1` function so they can adapt.

### 🔍 Step 4️⃣: Run Everything
Finally:

```python
asyncio.run(impress_protein_bind())
```

This starts the async event loop and runs all pipelines concurrently.

📊 Summary

 - ✅ You now know how to use the prebuilt Protein Binding Pipeline.
 - ✅ The pipeline will iteratively improve receptor designs for peptide binding.
 - ✅ When designs degrade, sub-pipelines are created automatically.
 - ✅ The tasks are distributed efficiently and adaptively.
