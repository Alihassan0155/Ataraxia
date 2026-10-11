# Application integration

Use the library from a backend worker/task queue. A job has its own evidence
directory, output directory and interpreter. It does not mutate the backend's
environment or load CUDA/SDK libraries into the web process.

```python
from pathlib import Path
from ataraxia.api import AnnotationJob, prepare_job, run_annotation
from ataraxia.runtime.config import Settings

settings = Settings.load(root=Path('/workspace/ataraxia'))
job = AnnotationJob(
    backend='qwen',
    evidence_dir=Path('evidence/my-job'),
    output_dir=Path('runs/my-job'),
    python_executable='/worker-env/bin/python',
    options=('--phase', 'pilot', '--fps', '1.0', '--max-frames', '32',
             '--max-pixels', '262144', '--max-new-tokens', '1200', '--offline'),
)
command, environment, output = prepare_job(job, settings)  # validation only
# result = run_annotation(job, settings)  # launch only when authorized
```

Evidence layout: `videos/<assigned_id>.mp4`, `context/<assigned_id>.json`, and
`pilot_metadata.csv` with the established worker metadata schema (`assigned_id`,
duration and other existing fields). `metadata_file` allows another filename.
The new workers take the job count explicitly; the historical pipeline still
defaults to its original 50-video validation. Native frame/token/quantization,
generation, prompt and repair behavior are retained from the working snapshots.

New jobs cannot write into datasets or historical study/output directories.
Use a fresh `runs/<job-id>` directory. Existing worker configuration/checkpoint
gates provide resume behavior. Model options remain explicit; do not silently
substitute a checkpoint, sampling policy or rubric. Set the reviewed immutable
revision in CUDA options when preparing a frozen deployment.

Use `ataraxia.annotation.common.VideoAnnotation` for response validation.
`ataraxia.calibration.apply.apply_scalar` and `apply_emotion` apply existing
coefficient dictionaries; they do not accept target labels or fit parameters.
The exact chosen pilot plans stay in the original experiment configuration.

Gemini runs the existing hard per-key deadline/failover policy in a child worker.
It uses the existing checkpoint and provider defaults and preserves raw results.
Provider immutability/default provenance gaps remain unresolved; the refactor
does not invent missing settings. The application should implement job ownership,
authentication, queue scheduling and deployment monitoring separately.
