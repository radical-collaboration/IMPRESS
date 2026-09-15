import os
import tempfile


def session_work_dir() -> str:
    """Return the base directory for asyncflow session dirs.

    Defaults to node-local /tmp rather than cwd, which on HPC scratch
    exhausts inodes over many runs. Override with IMPRESS_SESSION_DIR.

    Pass to the engine at creation time::

        flow = await WorkflowEngine.create(
            backend=backend, work_dir=session_work_dir()
        )
    """
    return os.environ.get("IMPRESS_SESSION_DIR", tempfile.gettempdir())
