# Integrated Machine-learning for PRotEin Structures at Scale (IMPRESS)

IMPRESS is a high-performance computational framework to enable the inverse 
design of proteins using Foundation Models such as AlphaFold and ESM2.

## IMPRESS pipeline design

- The user submits the C-terminal peptide sequence, which they want to target 
 for binding.
- The [ProfAff](https://profaff.igbmc.science) database is queried to generate 
  design starting points.
- ProteinMPNN is used to create a design sequence. 
- The designed sequences are submitted to 
  [AlphaFold-Multimer](https://cosmic-cryoem.org/tools/alphafoldmultimer/). 
- AlphaFold-predicted structures design structures are fed to a structure-aware 
  machine learning model to predict binding specificity and affinity. The cycle 
  continues until convergence.
- Best designs are tested in wet-lab experiments. Measured and predicted 
  properties are used as feedback for model refinement and, if successful, 
  added to the input set to serve as starting templates.

Current implementation is capable of running ProteinMPNN on an input two-chain 
complex to redesign the entire receptor, creating new interactions to the 
substrate and solubilizing the protein. These designs are then submitted to 
AlphaFold-Multimer for structure prediction, where AlphaFold’s intrinsic 
discriminatory power and confidence metrics can be leveraged to determine if 
the input protein has improved. The predicted structures are then resubmitted 
to ProteinMPNN to continue optimizing the receptor. Over the course of many 
iterations, we expect the receptor to gradually improve, both in terms of 
stability and substrate binding affinity. The pipeline monitors this process, 
distributing the sequence generation, structure determination, and design 
analysis tasks evenly across the specified GPU and CPU allocations.

## Middleware foundation

RADICAL-EnTK (Ensemble Toolkit) is used as a workflow management system, that 
enables the use of high-performance computing (HPC) platforms and features.
EnTK-based designed pipeline provides the integrated ability to efficiently 
and effectively train sophisticated models. That requires advances in HPC 
workflow methodology that brings together the ability to “evaluate as you go”.

