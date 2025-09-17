# AlphaFold Pipeline Designs

This document explains the two pipeline designs for running AlphaFold tasks with support for multiple structures and GPU binding.

---

## 1. Single Pipeline with Parallel Structures (Current)

A single pipeline manages multiple structures.  
AlphaFold tasks run concurrently within the same pipeline, each bound to a GPU.

```
Single Pipeline with Parallel Structures
----------------------------------------
[Pipeline]
    |
    +--> [AlphaFold A] --> [Output A]   (GPU0)
    +--> [AlphaFold B] --> [Output B]   (GPU1)
    +--> [AlphaFold C] --> [Output C]   (GPU2)
    +--> [AlphaFold D] --> [Output D]   (GPU3)
```

- One pipeline orchestrates all structures.  

## 2. Separate Pipelines Design (Supported and can be enabled)

Each structure is processed by its own pipeline.  

```
Separate Pipelines Design
-------------------------
[Pipeline 1] --> [AlphaFold A] --> [Output A]
                   GPU0

[Pipeline 2] --> [AlphaFold B] --> [Output B]
                   GPU1

[Pipeline 3] --> [AlphaFold C] --> [Output C]
                   GPU2
```

- Each pipeline launches independently.  
- GPU allocation can be set per pipeline.  
- Suitable if users prefer keeping pipelines isolated.  

---
