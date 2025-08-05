# Adaptive Agentic, IMPRESS use case

## Objective: Inject Agentic AI in the `adaptive_decision` method
### 1st Prototype (Quick & Dirty)
- Currently: Randomly stop critieria
- Proposed approach: provide the model with following context, the make a decision:
   - Context (some basic attributes from the `Pipeline`object): 
      - Prior score
      - Current score
      - Geneartion number

### 2nd Prototype (Prototype 1.0)
- Proposed approach: provide the model with more context via adding more attributes. 
   - Feats:
      - Consider adding attributes from other related pipelines (e.g., parent)
      - Improve dev prompt by having a more robust criteraia