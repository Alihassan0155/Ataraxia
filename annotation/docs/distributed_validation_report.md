# Distributed GPU validation ? 2026-10-12

Implementation is present. **Three-GPU deployment validation is pending**, not passed. No full-dataset annotation was started.

## Verified checks

- 55 automated tests passed, including 12 distributed reliability tests.
- Three concurrent mocked transports processed six unique jobs through the real controller/SQLite/result export. This is a scheduling test, not GPU inference.
- OS GPU lock exclusion/release, bounded retry, partial-output recovery, stale/disconnected lease handling, duplicate/revision/memory-gate rejection, SSH quoting, scheduled-task command construction, expired-lease refusal and local timeout during a simulated blocked share write passed.
- PowerShell launch/setup scripts parsed with zero errors; Python modules compiled.
- Preservation audit: 21,695 original research artifacts checked, zero changes.
- Main-PC CUDA health: RTX A4000, CUDA 12.8, recorded package versions matched.

## Real GPU smoke

Three previously unannotated videos ran through the scheduler and unchanged Qwen backend on **LAB12-PC47**. All three annotations passed schema/provenance checks and the existing 15.8 GiB observed-device gate. No jobs failed; controller and worker exited.

| Video | Inference seconds | Device peak GiB | Allocator peak GiB | Frames |
| --- | ---: | ---: | ---: | ---: |
| FV000002 | 77.4 | 15.729 | 15.721 | 32 |
| FV000003 | 262.7 | 15.667 | 15.979 | 32 |
| FV000005 | 479.8 | 15.629 | 16.872 | 32 |

Batch elapsed including loading: 976.4 seconds. Device and allocator measurements differ and are preserved as reported by the original backend. The allocator peak exceeds 16 GiB on one clip; the unchanged deployment gate uses observed device memory. No new memory or sampling policy was substituted.

Results: `runs/distributed/main_gpu_smoke_20261012/results/qwen/annotations.jsonl`. Full original logs, raw responses, configuration, code/evidence hashes, receipt and SQLite state are retained in that run.

The smoke began before the final orchestration hardening. Its original frozen hashes remain intact; the native inference and runtime source hashes stayed unchanged. This validates the real inference adapter on one machine, while the final controller hardening is covered by automated tests. Do not promote this main-only run to three-PC proof.

## Not yet verified

- SSH authentication and SMB read/write access on GPU2/GPU3.
- Per-remote local CUDA environments and exact cached checkpoints.
- Actual simultaneous inference on three distinct A4000 PCs.
- Live InternVL inference through this new scheduler.
- Scheduled-task credential/UNC fallback on the user?s remote machines.

Remote SSH addresses and the authenticated UNC share are still required. `verify-smoke` correctly returned `three_gpu_passed: false` (Qwen: one machine; InternVL: none). Full dispatch is gated until a fresh 3?6-video smoke records accepted results from three distinct machine hostnames for both backends and identical final source hashes.

## Runbook

See [distributed GPU commands](distributed_gpu_annotation.md) and `configs/distributed.example.json`. Local machine configuration is excluded from Git. Gemini remains separate, calibration is unchanged, and historical annotations/predictions are preserved.
