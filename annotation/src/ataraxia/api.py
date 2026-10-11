"""Application-facing jobs. GPU/SDK imports occur only in separate workers."""
import csv
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from .runtime.config import Settings, resolve_path
from .runtime.logging import get_logger

BACKENDS = {name: "ataraxia.annotation.backends."+("gemini_execution" if name == "gemini" else name)
            for name in ("qwen", "internvl", "gemini")}


@dataclass(frozen=True)
class AnnotationJob:
    backend: str
    evidence_dir: Path
    output_dir: Path
    python_executable: str = sys.executable
    metadata_file: Path | None = None
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobResult:
    backend: str
    returncode: int
    output_dir: Path


def prepare_job(job: AnnotationJob, settings: Settings):
    """Validate input identities/paths and build an argument-list command."""
    if job.backend not in BACKENDS:
        raise ValueError("Unknown annotation backend")
    evidence = resolve_path(settings.root, job.evidence_dir)
    output = resolve_path(settings.root, job.output_dir)
    for name in ("heldout_50_evaluation", "pilot_50_reels_30h", "human_annotation", "data", "outputs"):
        protected = settings.root/name
        if output == protected or protected in output.parents:
            raise ValueError("New application jobs must use a new runs directory, not research/data artifacts")
    metadata = resolve_path(settings.root, job.metadata_file) if job.metadata_file else evidence/"pilot_metadata.csv"
    with metadata.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ids = [r.get("assigned_id") for r in rows]
    if not rows or any(not vid or Path(vid).name != vid or vid in (".", "..") or "/" in vid or "\\" in vid for vid in ids):
        raise ValueError("Metadata needs safe assigned_id values")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate annotation input IDs")
    for vid in ids:
        for path in (evidence/"videos"/(vid+".mp4"), evidence/"context"/(vid+".json")):
            if not path.is_file():
                raise FileNotFoundError(path)
    env = settings.child_environment()
    env.update(ATARAXIA_PILOT_DIR=str(evidence), ATARAXIA_OUTPUT_ROOT=str(output),
               ATARAXIA_METADATA_PATH=str(metadata), ATARAXIA_EXPECTED_VIDEO_COUNT=str(len(ids)))
    command = [job.python_executable, "-m", BACKENDS[job.backend]]
    if job.backend != "gemini":
        if not any(arg == "--phase" or arg.startswith("--phase=") for arg in job.options):
            raise ValueError("CUDA jobs require an explicit reviewed --phase option")
        # Existing CUDA worker CLI owns model options and resume/configuration gates.
        if any(arg.startswith("--") and "--run-dir".startswith(arg.partition("=")[0])
               for arg in job.options):
            raise ValueError("Use output_dir instead of overriding --run-dir")
        command += ["--run-dir", str(output/job.backend), *job.options]
    elif job.options:
        raise ValueError("Gemini retains its existing provider defaults; no CLI overrides supported")
    return command, env, output


def run_annotation(job: AnnotationJob, settings: Settings, *, timeout=None) -> JobResult:
    """Blocking worker suitable for a backend task queue; no parent env mutation."""
    command, env, output = prepare_job(job, settings)
    logger = get_logger()
    logger.info("Starting backend=%s output=%s", job.backend, output)
    result = subprocess.run(command, cwd=settings.root, env=env, timeout=timeout, check=False)
    logger.info("Finished backend=%s returncode=%s", job.backend, result.returncode)
    return JobResult(job.backend, result.returncode, output)
