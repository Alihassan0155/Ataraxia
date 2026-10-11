# Annotation folder migration

All former project code, configuration, dependencies, research, annotations, predictions, reports and held-out workflows now reside under `annotation/`. Root PowerShell commands moved to `annotation/commands/`, with project-relative roots updated. Frozen held-out scripts and research artifacts were not edited.

Git metadata and AGENTS.md remain at repository root. Existing environments/cache are linked into annotation to avoid relocating installed environments. Dataset directory rename was denied by Windows even after escalation; annotation/data is a junction to preserved root data. This physical relocation remains pending until the directory lock/permissions are resolved.

Run commands from annotation. Historical report paths remain relative to that directory. No inference, calibration fitting or evaluation rerun was performed. Existing staged Git changes predate this additional move; review and stage the new layout before committing.

Validation: 43 unit tests passed; preservation audit checked 21,695 artifacts with zero changes; relocated package doctor passed; PowerShell commands parsed without errors. CUDA editable install was refreshed. The historical root venv lacks setuptools and was not altered; the actual held-out Gemini environment is refreshed separately.
