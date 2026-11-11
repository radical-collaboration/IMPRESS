# Installation Guide

This page shows you how to set up your environment to use **Impress** and run asynchronous pipelines with it.  

We recommend using a **virtual environment** to isolate your dependencies.

---

## Step 1: Create a Python Environment

Make sure you have **Python 3.9 or newer** installed.  
You can check your Python version with:

```bash
python3 --version
```

We recommend creating a virtual environment to keep dependencies clean.

### Using `venv`

On Linux/Mac:

```bash
python3 -m venv impress-env
source impress-env/bin/activate
```

On Windows:

```bash
python -m venv impress-env
impress-env\Scripts\activate
```

Your shell prompt should now show `(impress-env)` indicating the environment is active.

---

## Step 2: Install Impress

Clone the repository and install **Impress** with its required
dependencies (including `radical-asyncflow>=0.4.0`, its workflow engine):

```bash
git clone https://github.com/radical-collaboration/IMPRESS.git
cd IMPRESS
pip install .
```

Use `pip install -e .` instead if you plan to modify Impress itself.

### HPC execution backends (optional)

Local runs of your own pipelines only need `radical.asyncflow`'s built-in
`LocalExecutionBackend`. The example runners under `examples/` need rhapsody
even with `IMPRESS_BACKEND=local`: their local mode uses its
`ConcurrentExecutionBackend`.
HPC backends such as `DragonExecutionBackend` and `RadicalExecutionBackend`
come from [`rhapsody`](https://pypi.org/project/rhapsody-py/), which is not
installed automatically. The example workflows under `examples/` import it:

```bash
pip install "rhapsody-py[dragon,telemetry]"
```

The protein binding and small molecule binding examples also ship
`delta_env_setup.sh` scripts that build a complete environment (Impress,
rhapsody, PyTorch, PyRosetta, Boltz-2, and so on) on NCSA Delta. See
[Examples](../examples/protein-binding.md).

### IMPRESS-A (optional)

[IMPRESS-A](../impress-a/index.md) is a second package in this repository,
under `agent/`. The clone above brings it with it, but `pip install .` does not
install it: it is its own distribution (`impress_a`, Python >= 3.11) with its
own dependency set, and it is not on PyPI. It runs on the same middleware as
Impress (`radical.asyncflow` over `rhapsody`) but does not depend on the
`impress` package.

Install it from `agent/`:

```bash
cd agent
pip install -e ".[dev]"
pip install -e ".[dragon]"   # only where campaigns run on Dragon, e.g. NCSA Delta
```

`agent/scripts/dev_setup.sh` does this in a dedicated `.venv` with the extras
its tests need. Check the install with `impress-a tools`, which lists the
registered toolkit.

The two packages are not installed into one merged environment: Impress targets
Python >= 3.9 with radical.pilot, IMPRESS-A >= 3.11 with langgraph, rhapsody and
biopython.

---

## Step 3: Verify Installation

Check that Impress is installed and importable:

```bash
python -c "from impress import ImpressManager; print('Impress is installed!')"
```

You should see:

```
Impress is installed!
```

---

## Step 4: Run a Sample Pipeline

Now you're ready to write and run your own pipelines! Continue with
[Build A Protein Pipeline](quick-start.md) for a step-by-step tutorial.

---

## Deactivate Environment

When you're done, you can deactivate your virtual environment:

```bash
deactivate
```

Next time you want to work with Impress, just activate the environment again.

---

## Next Steps

- Explore the [API Reference](../reference/index.md)
- Read [Architecture](../concepts/architecture.md) to understand the core framework
- Build your own workflows with [Build A Protein Pipeline](quick-start.md)
- See [IMPRESS-A](../impress-a/index.md) for autonomous campaigns that compose a workflow per cycle

---
