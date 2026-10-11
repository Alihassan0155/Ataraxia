# Refactor validation

Validated on 2026-10-11. No model inference, remote API generation, calibration
fitting, preprocessing rerun or held-out evaluation rerun was performed.

| Check | Result |
| --- | --- |
| Existing behavioral suite plus application contracts | 43 tests passed |
| Frozen held-out workflow tests | 5 tests passed |
| Frozen Gemini reliability tests | 9 tests passed |
| Held-out missing-field/bootstrap regression tests | 2 tests passed |
| Total automated tests | 59 passed |
| Python syntax compilation | Passed for all live source/compatibility modules |
| Package installation | Editable installation passed in CUDA and Gemini environments |
| Dependency consistency | `pip check` passed in both environments |
| Native inference helper equivalence | AST identity with frozen Qwen/InternVL/schema-repair functions, excluding CLI path/cardinality plumbing |
| Prompt preservation | Original rubric string constants match exactly |
| Configuration | Explicit `.env` loading, process-env precedence, no parent-env mutation or secret logging tested |
| Annotation entry points | Qwen/InternVL help; all three job dry runs; Gemini imports passed without inference/API calls |
| Dataset/development evaluation entry points | Help commands passed without dataset writes |
| Original artifacts | 21,695 files checked; zero missing/changed artifacts |
| Held-out freeze | All frozen hashes/checkpoint/evidence checks remain valid |
| Rollback | Dry run verifies original snapshots for all 45 entry-point files |
| New Windows launcher | PowerShell parser reports zero syntax errors; execution blocked by host execution policy |

Preservation uses SHA-256 for original text, configuration, annotation and evidence
files, and unchanged size/mtime for media/opaque files. Held-out frozen tests also
verify their recorded media hashes. The refactor did not relocate or rewrite
datasets, human/model labels, calibration coefficients, reports, transcripts or
eGeMAPS artifacts. All original source bytes are separately retained for rollback.

The CUDA environment was missing `python-dotenv`; the Gemini environment lacked
packaging/build tools. Installed dotenv 1.2.3 and setuptools/wheel, with packaging
installed as their dependency. Existing model/SDK library versions were not
upgraded. No requirements snapshots were overwritten. Network access was required
only for these missing dependency tools, not inference.

Known limits:

- Historical MLX workflows require Apple Silicon; they remain research commands,
  not Windows application workers. They were compiled, not executed.
- Retired two-human workflows retain historical source assumptions; their old
  input files no longer exist. Their reusable functions remain tested. The active
  three-human default now points to the actual `human_annotation/pilot/` files.
- Actual CUDA/Gemini inference was intentionally not rerun. Helper equivalence,
  import checks, dry runs and existing behavioral tests provide safe validation;
  future live deployment still needs authorized acceptance testing.
- This host disallows running `.ps1` files. Its execution policy was not changed.
  Use the documented Python commands or an appropriately configured user shell.
- Historical dataset metadata with external absolute media paths remains intact;
  new application jobs use explicit portable paths and protect research outputs.
- Ali's incomplete held-out categorical/distribution fields and Gemini immutable
  provider/default provenance gaps remain research readiness blockers. A software
  refactor cannot establish scientific validation or provider reproducibility.
- Frozen research copies were not deduplicated because doing so would invalidate
  their hashes. Compatibility launchers and immutable backups are intentional.

The full dataset was not annotated. Application job execution is independent of
research experiment scripts; calibration application does not import development
fitting code. Runtime, quality ranking and original research behavior remain
separate concerns.

Git status: branch `refactor/modular-annotation-20261011` was created and 202
refactor files were staged. The commit approval was declined, so no commit or
push occurred. The original history, working files and exact source snapshots
remain available; final documentation/receipt updates are unstaged.
