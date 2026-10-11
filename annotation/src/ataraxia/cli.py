"""Entry point with explicit safe dry runs and unchanged worker options."""
import argparse
import json
import sys
from pathlib import Path
from .api import AnnotationJob, prepare_job, run_annotation
from .runtime.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    doctor = sub.add_parser("doctor", help="Inspect configuration without model/API calls")
    doctor.add_argument("--json", action="store_true")
    run = sub.add_parser("annotate", help="Launch an isolated annotation worker")
    run.add_argument("backend", choices=("qwen", "internvl", "gemini"))
    run.add_argument("--evidence-dir", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--metadata-file", type=Path)
    run.add_argument("--python", default=None)
    run.add_argument("--dry-run", action="store_true")
    argv = sys.argv[1:]
    if "--" in argv:
        boundary = argv.index("--")
        options = argv[boundary+1:]
        argv = argv[:boundary]
    else:
        options = []
    args = parser.parse_args(argv)
    settings = Settings.load(args.project_root)
    if args.action == "doctor":
        result = {"root": str(settings.root), "evidence_dir": str(settings.evidence_dir),
            "output_dir": str(settings.output_dir), "secret_values_logged": False,
            "inference_started": False}
        print(json.dumps(result, indent=2))
        return
    job = AnnotationJob(args.backend, args.evidence_dir, args.output_dir,
                        args.python or sys.executable, args.metadata_file, tuple(options))
    if args.dry_run:
        command, _, output = prepare_job(job, settings)
        print(json.dumps({"command": command, "output_dir": str(output), "inference_started": False}, indent=2))
    else:
        raise SystemExit(run_annotation(job, settings).returncode)
