# Project Ataraxia

Ataraxia provides native-video affect annotation workers and reproducible research
evaluation. The application library is installable; existing experiments remain
versioned separately. Importing the API never loads a model or calls Gemini.

| Location | Responsibility |
| --- | --- |
| `src/ataraxia/api.py` | Explicit annotation jobs and isolated worker execution |
| `src/ataraxia/annotation/` | Annotation contracts, exact rubrics, active native model workers |
| `src/ataraxia/runtime/` | Configuration, portable paths, application logging |
| `src/ataraxia/calibration/` | Frozen calibration application without fitting |
| `src/ataraxia/evaluation/` | Reusable metrics and development evaluation workflows |
| `src/ataraxia/datasets/` | Normalization, validation, selection, preprocessing |
| `src/ataraxia/research/` | Historical model runs, collection, sampling and MLX workflows |
| `configs/`, `dependencies/` | Runtime policy and dependency boundaries |
| `scripts/` | Windows launcher, artifact verification and reversible source restore |
| `tests/` | Existing behavioral tests plus application/refactor contracts |
| `research/migration/` | Inventory, exact original source snapshots, migration map |
| Existing data/pilot/held-out/output directories | Immutable study assets at their original paths |

The 45 old `src/*.py` paths are small compatibility launchers/module aliases.
Their implementations live in the package; existing PowerShell commands still
work. Frozen held-out code copies intentionally remain byte-identical. They are
historical experiment assets, not accidental duplication to remove.

Install in an environment with the appropriate worker dependencies:

```powershell
python -m pip install -e .
.\scripts\windows\ataraxia.ps1 doctor --json
```

No inference is launched by `doctor` or `--dry-run`. Full-dataset annotation has
not been authorized or started by this refactor. The software integration layer
is implemented; the scientific/provider readiness gaps in the held-out report
still apply.

See [workflows](docs/workflows.md), [application integration](docs/application_integration.md),
[migration summary](docs/migration_summary.md), and [validation](docs/validation_report.md).
