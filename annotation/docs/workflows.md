# Running workflows

Run commands from the project root. Existing PowerShell scripts remain compatible.
Install the package into the interpreter used by each command (`pip install -e .`).
Do not transfer virtual environments to another machine; reinstall dependencies.

## Safe configuration and import checks

```powershell
.\.venv-qwen-cuda\Scripts\python.exe -m ataraxia doctor --json
.\.venv-qwen-cuda\Scripts\python.exe -m unittest discover -s tests
.\.venv-qwen-cuda\Scripts\python.exe scripts/verify_preservation.py
```

## Annotation command construction without inference

```powershell
.\.venv-qwen-cuda\Scripts\python.exe -m ataraxia annotate qwen --evidence-dir heldout_50_evaluation --output-dir runs/example --dry-run -- --phase pilot --fps 1.0 --max-frames 32 --max-pixels 262144 --max-device-gib 15.8 --max-new-tokens 1200 --offline
.\.venv-qwen-cuda\Scripts\python.exe -m ataraxia annotate internvl --evidence-dir heldout_50_evaluation --output-dir runs/example --dry-run -- --phase pilot --fps 1.0 --max-frames 16 --max-device-gib 15.8 --max-new-tokens 1200 --offline
.\heldout_50_evaluation\.venv-gemini\Scripts\python.exe -m ataraxia annotate gemini --evidence-dir heldout_50_evaluation --output-dir runs/example --dry-run
```

These examples only validate paths and print commands. They do not load models,
decode clips, create result directories or call APIs. Actual annotation removes
`--dry-run` only after the deployment is reviewed. For different worker environments,
use `--python <worker-python>`; argument lists avoid shell interpolation.

## Existing CUDA and frozen held-out research

The original commands remain supported:

```powershell
.\run_qwen_cuda_pilot.ps1
.\run_internvl_cuda_pilot.ps1
.\heldout_50_evaluation\run_all.ps1
```

Do not run these solely to validate a refactor; they can perform expensive
inference. The held-out workflow retains its own hash-locked code/configuration,
Qwen → InternVL → Gemini ordering and saved-prediction checkpoints.

## Dataset preparation

The original `run_dataset_validation.ps1` and `run_post_language.ps1` remain
functional through module aliases. New module names:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe -m ataraxia.datasets.validation --help
.\.venv-qwen-cuda\Scripts\python.exe -m ataraxia.datasets.selection --help
.\.venv-qwen-cuda\Scripts\python.exe -m ataraxia.datasets.preprocessing --help
```

They retain the existing merged manifests, filters, preprocessing settings and
resume gates. Historical metadata with absolute external media paths remains
unchanged as evidence; restore its media separately or supply reviewed manifests
with local paths. No metadata paths are rewritten automatically.

## Calibration and held-out evaluation

Production calibration only applies original frozen parameters. Fitting stays
under `ataraxia.evaluation.development`; frozen held-out scripts are unchanged:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe heldout_50_evaluation/scripts/test_workflow.py
.\heldout_50_evaluation\.venv-gemini\Scripts\python.exe heldout_50_evaluation/scripts/test_reliability.py
.\.venv-qwen-cuda\Scripts\python.exe heldout_50_evaluation/scripts/test_valid_fields.py
```

Evaluation reruns must use a new output directory:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe heldout_50_evaluation/scripts/evaluate_valid_fields.py --output-dir heldout_50_evaluation/reports/<new-version>
```

The existing incomplete-human-field qualification remains. Do not tune or refit
calibration on held-out labels. Previous reports are preserved.
