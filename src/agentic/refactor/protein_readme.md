# Async Protein Design Pipeline - LangGraph Implementation

A fully asynchronous LangGraph-based agentic system for automated protein design using ProteinMPNN and AlphaFold.

## 🚀 Key Features

- **Fully Async**: All nodes, tools, and I/O operations are async
- **Concurrent Execution**: Multiple file parsing operations run in parallel
- **Streaming Support**: Real-time updates during execution
- **LLM-Powered Routing**: Intelligent task selection with fallback logic
- **Circular Routing**: Dynamic workflow based on results

## Architecture

```
┌──────────┐
│  START   │
└────┬─────┘
     │
     ▼
┌─────────────────────┐
│  Router (Async LLM) │◄──────┐
│ Task Sequence Gen   │       │
└────┬────────────────┘       │
     │                        │
     │ (conditional)          │
     ▼                        │
┌──────────────────────────┐  │
│  • run_mpnn (async)      │  │
│  • score_mpnn (async)    │  │
│  • make_fasta (async)    │──┘
│  • run_alphafold (async) │
│  • score_alphafold (async)│
└──────────────────────────┘
```

## Major Changes from Original Code

### 1. **Async Conversion**
All functions converted to async:
```python
# Before
def run_mpnn_node(state: PipelineState) -> PipelineState:
    ...

# After
async def run_mpnn_node(state: PipelineState) -> PipelineState:
    await asyncio.create_subprocess_exec(...)
```

### 2. **State Management**
- Removed `Runtime[RuntimeContext]` pattern
- Merged `RuntimeContext` into `PipelineState` as fields
- Converted from `@dataclass` to `TypedDict` for LangGraph
- Added `decision` field for routing

### 3. **Router Implementation**
- Async LLM calls with `ainvoke()`
- Structured output with Pydantic
- Async fallback routing
- Separate `route_to_task()` conditional function

### 4. **Tool Nodes**
- Removed `@tool` decorators and `ToolRuntime`
- Async subprocess execution with `asyncio.create_subprocess_exec()`
- Async file I/O with `loop.run_in_executor()`
- Concurrent file parsing with `asyncio.gather()`
- Direct state manipulation (no `Command` objects)

### 5. **Graph Construction**
- Circular routing: `tool → router → tool → router`
- Proper async compilation
- Streaming support with `astream()`

## Setup

### Prerequisites

```bash
# Install dependencies
pip install -r requirements.txt

# Set up your local LLM inference server
# The code expects it on http://localhost:8010/v1
```

### Directory Structure

```
project/
├── agent.py           # Main async pipeline orchestration
├── nodes.py           # Async router node with LLM
├── tools.py           # Async tool nodes (MPNN, AlphaFold)
├── state.py           # State schema definitions
├── inputs/            # Input PDB files
│   └── 6v7q.pdb
├── outputs/           # Pipeline outputs
│   ├── job_1/
│   │   └── seqs/
│   └── af/
│       ├── fasta/
│       └── prediction/
└── requirements.txt
```

## Usage

### Basic Async Usage

```python
import asyncio
from agent import run_pipeline_async

# Run the pipeline asynchronously
async def main():
    final_state = await run_pipeline_async("6v7q.pdb", verbose=True)
    print(f"Best sequence: {final_state['top_sequence']}")
    print(f"Final fold score: {final_state['current_fold_score']}")

asyncio.run(main())
```

### Synchronous Wrapper

```python
from agent import run_pipeline

# Use synchronous wrapper (internally runs async)
final_state = run_pipeline("6v7q.pdb", verbose=True)
```

### Streaming Execution

```python
import asyncio
from agent import stream_pipeline_async

async def stream_example():
    async for chunk in stream_pipeline_async("6v7q.pdb"):
        print(f"Received update: {chunk}")

asyncio.run(stream_example())
```

### Advanced Custom Configuration

```python
from agent import create_protein_pipeline, initialize_pipeline_state

async def custom_run():
    # Create the pipeline
    pipeline = create_protein_pipeline()
    
    # Initialize with custom parameters
    initial_state = initialize_pipeline_state(
        input_pdb_filename="protein.pdb",
        pipeline_name="custom_pipeline",
        pipeline_uid=42,
        max_passes=6,
        mpnn_num_seqs=20,
        model_path="/path/to/custom/model",
        inference_server_url="http://localhost:8010/v1"
    )
    
    # Run and stream results
    async for chunk in pipeline.astream(initial_state):
        for node_name, state in chunk.items():
            print(f"Node {node_name} completed")
    
    # Get final state
    final_state = await pipeline.ainvoke(initial_state)
    return final_state

asyncio.run(custom_run())
```

### Command Line

```bash
# Run with default settings
python agent.py

# Or use in a Jupyter notebook with async support
import asyncio
from agent import main_async
await main_async()
```

## Pipeline Flow

1. **Router** (async) analyzes current state and decides next task
2. **run_mpnn** (async): Generates candidate sequences using ProteinMPNN
3. **score_mpnn** (async): Parses files concurrently, ranks sequences
4. **make_fasta_file** (async): Creates FASTA file with async I/O
5. **run_alphafold** (async): Folds the top sequence using AlphaFold
6. **score_alphafold** (async): Extracts and scores folded structure
7. **Router** decides: continue (back to step 2) or END

The pipeline continues until:
- Maximum passes reached, OR
- No improvement in fold score, OR
- LLM/fallback logic decides to terminate

## Async Benefits

### 1. Concurrent File Processing
```python
# In score_mpnn_node - processes multiple files simultaneously
results = await asyncio.gather(*[parse_file(f) for f in files])
```

### 2. Non-blocking Subprocess Execution
```python
process = await asyncio.create_subprocess_exec(*cmd)
stdout, stderr = await process.communicate()
```

### 3. Async File I/O
```python
loop = asyncio.get_event_loop()
await loop.run_in_executor(None, lambda: open(path, "w").write(content))
```

### 4. Streaming Results
```python
async for chunk in pipeline.astream(initial_state):
    # Process updates in real-time
    print(chunk)
```

## Configuration

### LLM Configuration (nodes.py)

```python
def get_llm(state: PipelineState) -> ChatOpenAI:
    # Local inference server (default)
    return ChatOpenAI(
        model=state.get("model_path"),
        openai_api_key="EMPTY",
        openai_api_base=state.get("inference_server_url"),
        temperature=0.2,
        max_tokens=100
    )
```

To use different models, modify the `model_path` in `initialize_pipeline_state()`:
- Llama 3.2: `MODELS["llama3.2"]`
- Llama 3.1: `MODELS["llama3.1"]`
- Mistral: `MODELS["mistral"]`

Or use cloud LLMs:
```python
# OpenAI
return ChatOpenAI(model="gpt-4o-mini", temperature=0)

# Anthropic
from langchain_anthropic import ChatAnthropic
return ChatAnthropic(model="claude-3-5-sonnet-20241022")
```

### Pipeline Parameters

Modify in `initialize_pipeline_state()`:
- `max_passes`: Maximum optimization iterations (default: 4)
- `mpnn_num_seqs`: Sequences per MPNN run (default: 10)
- `base_path`: Project root directory
- `model_path`: Path to local LLM model
- `inference_server_url`: LLM server URL

## Troubleshooting

### "LLM routing failed"
- Check inference server is running: `curl http://localhost:8010/v1`
- Verify model path in state initialization
- Pipeline will automatically use rule-based fallback routing

### Event Loop Already Running
If running in Jupyter/IPython:
```python
# Use this instead of asyncio.run()
await run_pipeline_async("6v7q.pdb")
```

### Subprocess Errors
- Ensure MPNN and AlphaFold scripts are executable
- Check paths in state configuration
- Review stderr output from subprocess calls

### File I/O Errors
- Check directory permissions
- Ensure sufficient disk space
- Verify file paths in state

## Performance Optimization

### 1. Increase Concurrency
Adjust the number of concurrent file operations:
```python
# In score_mpnn_node
tasks = [parse_file(f) for f in files[:50]]  # Limit concurrent tasks
results = await asyncio.gather(*tasks)
```

### 2. Use aiofiles for Better Async I/O
```python
import aiofiles

async with aiofiles.open(path, 'w') as f:
    await f.write(content)
```

### 3. Implement Connection Pooling
For LLM calls, reuse connections:
```python
# Create once, reuse
llm = get_llm(state)
# Use for multiple calls
```

## Testing

### Test Individual Async Nodes
```python
import asyncio
from tools import run_mpnn_node
from agent import initialize_pipeline_state

async def test_node():
    test_state = initialize_pipeline_state("test.pdb")
    result = await run_mpnn_node(test_state)
    print(result["messages"])

asyncio.run(test_node())
```

### Test Full Pipeline
```python
import asyncio
from agent import run_pipeline_async

async def test_full():
    result = await run_pipeline_async("test.pdb", verbose=True)
    assert result["llm_calls"] > 0
    assert len(result["task_list"]) > 0

asyncio.run(test_full())
```

## Comparison: Sync vs Async

| Feature | Original (Sync) | Refactored (Async) |
|---------|----------------|-------------------|
| File Parsing | Sequential | Concurrent with `gather()` |
| Subprocess Execution | Blocking | Non-blocking |
| LLM Calls | Blocking | Async with `ainvoke()` |
| File I/O | Blocking | Async with executor |
| Streaming | Not available | Real-time with `astream()` |
| Graph Compilation | Standard | Async-compatible |
| State Management | `Runtime` object | Merged into state |
| Tool Decorators | `@tool` required | Pure async functions |

## Future Enhancements

- [ ] Implement full aiofiles integration for all I/O
- [ ] Add async checkpointing for long-running pipelines
- [ ] Parallel pass execution (run multiple passes concurrently)
- [ ] WebSocket support for real-time monitoring
- [ ] Async database logging
- [ ] Distributed execution across multiple workers

## Migration from Sync

If you have existing synchronous code:

1. Add `async` keyword to all node functions
2. Replace `os.system()` with `asyncio.create_subprocess_exec()`
3. Replace blocking I/O with `loop.run_in_executor()`
4. Use `await` for all async calls
5. Use `pipeline.astream()` instead of `pipeline.stream()`
6. Wrap execution in `asyncio.run()` or use `await` in async context

## License

[Your License Here]

---

**Note**: This implementation prioritizes async/await patterns throughout. All I/O operations, subprocess calls, and LLM interactions are non-blocking, enabling efficient concurrent execution and real-time streaming capabilities.
