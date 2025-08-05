# Adaptive Agentic, IMPRESS use case

## Objective: Inject Agentic AI in the `adaptive_decision` method
### 1st Prototype (Quick & Dirty)
- Currently: Randomly stop 
- Proposed approach: provide the model with following context, the make a decision:
   - Context (some basic attributes from the `Pipeline`object): 
      - Prior score
      - Current score
      - Geneartion number