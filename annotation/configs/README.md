# Configuration policy

Runtime paths use `ATARAXIA_PROJECT_ROOT`, `ATARAXIA_PILOT_DIR`, and
`ATARAXIA_OUTPUT_ROOT`, or explicit Python API arguments. Relative paths resolve
against the workspace root. `.env` is loaded explicitly; process environment
values take precedence. Secrets are never included in dry-run output.

Model/rubric/calibration settings remain in versioned research configurations.
The historical held-out freeze at `heldout_50_evaluation/config/` is authoritative
for that experiment. It is intentionally not rewritten or merged with runtime
settings. Pass reviewed model options explicitly to application workers.
