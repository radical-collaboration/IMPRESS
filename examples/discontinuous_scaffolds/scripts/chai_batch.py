"""
Chai-1 Batch Structure Prediction Script
Install: pip install chai_lab==0.6.1
Requirements: Linux, Python 3.10+, CUDA GPU with bfloat16 support
              (recommended: A100 80GB, H100 80GB, L40S 48GB, or RTX 4090)
"""

import argparse
import logging
import shutil
import traceback
from dataclasses import dataclass
from pathlib import Path

import torch
from chai_lab.chai1 import run_inference

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job definition
# ---------------------------------------------------------------------------

@dataclass
class FoldJob:
    """A single folding job: an ID, FASTA content, and output directory."""
    job_id: str
    fasta_content: str          # Full FASTA text (multi-chain ok)
    output_dir: Path

    def write_fasta(self) -> Path:
        """Write FASTA to a temp file and return its path."""
        fasta_path = self.output_dir / f"{self.job_id}.fasta"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        fasta_path.write_text(self.fasta_content)
        return fasta_path


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_batch(
    jobs: list[FoldJob],
    *,
    num_trunk_recycles: int = 3,
    num_diffn_timesteps: int = 200,
    num_samples: int = 5,
    use_esm_embeddings: bool = True,
    use_msa_server: bool = False,
    seed: int | None = None,
    skip_on_error: bool = True,
    skip_existing: bool = False,
    overwrite: bool = False,
) -> dict[str, list | Exception]:
    """
    Run Chai-1 inference over a list of FoldJobs.

    Returns a dict mapping job_id -> list of CIF output paths (success)
                                  or Exception (failure, if skip_on_error=True).
    """
    results: dict[str, list | Exception] = {}
    n = len(jobs)

    for i, job in enumerate(jobs, 1):
        log.info("─" * 60)
        log.info(f"Job {i}/{n}: {job.job_id}")

        try:
            if job.output_dir.exists() and any(job.output_dir.iterdir()):
                if skip_existing:
                    existing = sorted(job.output_dir.glob("*.cif"))
                    log.info(f"  ↷ skipping {job.job_id} (output dir non-empty, {len(existing)} CIF(s) found)")
                    results[job.job_id] = existing
                    continue
                elif overwrite:
                    log.info(f"  ↺ overwriting {job.job_id} (clearing output dir)")
                    shutil.rmtree(job.output_dir)

            fasta_path = job.write_fasta()
            job.output_dir.mkdir(parents=True, exist_ok=True)
            inference_output_dir = job.output_dir / f"prediction"
            inference_output_dir.mkdir(parents=True, exist_ok=True)

            candidates = run_inference(
                fasta_file=fasta_path,
                output_dir=inference_output_dir,
                num_trunk_recycles=num_trunk_recycles,
                num_diffn_timesteps=num_diffn_timesteps,
                seed=seed if seed is not None else i,   # reproducible per-job seed
                device=torch.device("cuda:0"),
                use_esm_embeddings=use_esm_embeddings,
                use_msa_server=use_msa_server,
            )

            cif_paths = candidates.cif_paths
            agg_score = candidates.aggregated_score
            log.info(f"  ✓ {len(cif_paths)} structures | agg. score: {agg_score:.4f}")
            results[job.job_id] = cif_paths

        except Exception as exc:
            log.error(f"  ✗ {job.job_id} failed: {exc}")
            log.debug(traceback.format_exc())
            if skip_on_error:
                results[job.job_id] = exc
            else:
                raise

    return results


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def print_summary(results: dict[str, list | Exception]) -> None:
    ok  = {k: v for k, v in results.items() if isinstance(v, list)}
    err = {k: v for k, v in results.items() if isinstance(v, Exception)}

    log.info("=" * 60)
    log.info(f"BATCH COMPLETE  ✓ {len(ok)} succeeded  ✗ {len(err)} failed")

    for job_id, paths in ok.items():
        log.info(f"  {job_id}: {len(paths)} CIF file(s)")
        for p in paths:
            log.info(f"      {p}")

    for job_id, exc in err.items():
        log.warning(f"  {job_id}: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Directory-based job loader
# ---------------------------------------------------------------------------

def load_jobs_from_dir(input_dir: Path, output_dir: Path) -> list[FoldJob]:
    """Load FoldJobs from a directory of .fa files.

    The first header line (>...) of each file is replaced with the
    Chai-1 entity tag format: >protein|name=<stem>.
    """
    jobs = []
    for fa_file in sorted(input_dir.glob("*.fa")):
        stem = fa_file.stem
        lines = fa_file.read_text().splitlines()
        lines[0] = f">protein|name={stem}"
        fasta_content = "\n".join(lines) + "\n"
        jobs.append(FoldJob(
            job_id=stem,
            fasta_content=fasta_content,
            output_dir=output_dir / stem,
        ))
    return jobs


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chai-1 batch structure prediction")
    parser.add_argument("--input_dir", required=True, type=Path,
                        help="Directory of .fa files to fold")
    parser.add_argument("--output_dir", required=True, type=Path,
                        help="Base output directory (one subdirectory per job)")
    parser.add_argument("--num_trunk_recycles", type=int, default=3)
    parser.add_argument("--num_diffn_timesteps", type=int, default=200)
    parser.add_argument("--num_samples", type=int, default=5)
    parser.add_argument("--no_esm", action="store_true",
                        help="Disable ESM embeddings")
    parser.add_argument("--use_msa_server", action="store_true",
                        help="Query the MSA server during inference")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--no_skip_on_error", action="store_true",
                        help="Raise on first error instead of continuing")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--skip_existing", action="store_true",
                      help="Skip jobs whose output dir is non-empty (resume mode)")
    mode.add_argument("--overwrite", action="store_true",
                      help="Clear output dir before each job (re-run mode)")
    args = parser.parse_args()

    jobs = load_jobs_from_dir(args.input_dir, args.output_dir)
    log.info(f"Loaded {len(jobs)} job(s) from {args.input_dir}")

    results = run_batch(
        jobs,
        num_trunk_recycles=args.num_trunk_recycles,
        num_diffn_timesteps=args.num_diffn_timesteps,
        num_samples=args.num_samples,
        use_esm_embeddings=not args.no_esm,
        use_msa_server=args.use_msa_server,
        seed=args.seed,
        skip_on_error=not args.no_skip_on_error,
        skip_existing=args.skip_existing,
        overwrite=args.overwrite,
    )

    print_summary(results)
