# Ataraxia pilot annotation results

Verified from the repository on 2026-10-07. This report concerns the saved CUDA pilot runs, not human-label accuracy.

## Completion and validation

- Qwen: 50 annotations for 50 distinct expected pilot IDs; status passed.
- InternVL: 50 annotations for the same 50 distinct IDs; status passed.
- No missing, duplicate or unexpected pilot IDs in these runs.
- All 100 annotations pass the repository schema and strict emotion-point validation: eight scores, each within 0?10, at most two decimal places, total exactly 10.
- Both final status files report no failed videos or device-memory gate failures.

## Saved results

- Qwen: [pilot_50_reels_30h/results/pilot50_qwen_nf4_max32_limit15p8_v5/qwen/pilot/annotations.jsonl](pilot_50_reels_30h/results/pilot50_qwen_nf4_max32_limit15p8_v5/qwen/pilot/annotations.jsonl)
- InternVL: [pilot_50_reels_30h/results/pilot50_cuda_nf4_qwen32_intern16_limit15p8_v5/internvl/pilot/annotations.jsonl](pilot_50_reels_30h/results/pilot50_cuda_nf4_qwen32_intern16_limit15p8_v5/internvl/pilot/annotations.jsonl)

Each model directory contains its configuration and checkpoint revision. Each pilot directory preserves annotations, raw responses, status and any validation-attempt records. Historical runs remain separate.

## Deployment settings

| Setting | Qwen | InternVL |
| --- | --- | --- |
| Checkpoint | Qwen/Qwen3-VL-8B-Instruct | OpenGVLab/InternVL3_5-8B-HF |
| Quantization | NF4, double quantization | NF4 language weights; BF16 vision tower/projector |
| Sampling | 1 FPS target, maximum 32 frames | 1 FPS target, maximum 16 frames |
| Temporal coverage | Uniform across full clip | Uniform across full clip |
| Vision preprocessing | Native Qwen video path, max_pixels 262144 | Native InternVL processor, 448?448, vision microbatch 1 |
| Generation | Greedy, batch 1, maximum 1200 new tokens | Greedy, batch 1, maximum 1200 new tokens |
| Device-memory gate | 15.8 GiB | 15.8 GiB |
| GPU | RTX A4000, CUDA | RTX A4000, CUDA |

These are capped FPS policies, not fixed 32/16 frames for every video. Effective FPS drops for clips exceeding the cap. Exact frame indices and counts are logged. InternVL concatenates independent per-frame vision features in order before the joint language-model pass.

## Recorded inference statistics

| Metric | Qwen | InternVL |
| --- | --- | --- |
| Sum of per-video elapsed time | 1.45 hours | 6.49 hours |
| Median per-video time | 82.5 s | 200.7 s |
| Longest per-video time | 469.0 s | 1984.1 s |
| Maximum observed device memory | 15.764 GiB | 15.766 GiB |
| Videos requiring a schema repair | 0 | 8 |

Times come from saved per-video metadata; they exclude model loading and are not overall wall-clock measurements. InternVL repair time is included in its per-video timings. Memory figures are observed total device memory, not allocator peaks.

## Evidence consistency

- `context_sha256` matches between the two models for 50/50 corresponding videos.
- `media_sha256` matches between the two models for 50/50 corresponding videos.
- `prompt_sha256` matches between the two models for 50/50 corresponding videos.

Matching evidence hashes do not mean identical native modality access or identical visual-token sequences. Both models use shared transcript, eGeMAPS and caption context; their logged raw-audio access is false. Their visual frame caps and processors differ.

## Remaining study work

- Collect or locate independent blind human annotations and validate coverage for all 50 videos.
- Compare all three candidates against human labels under the predefined development/held-out protocol.
- Select and freeze the best two deployments; define agreement/disagreement handling for the full dataset.
- Do not equate schema validity or completion with annotation accuracy. This audit did not run a human-label comparison or establish full-dataset feasibility.

## Earlier runs

The earlier uncapped Qwen run under `pilot50_cuda_nf4_fps1_intern16_v1` contains only 17 valid labels and failed its memory checks. The 48-frame benchmark also failed the older headroom gate. Those results remain preserved and are not merged into these final 50-video runs.
