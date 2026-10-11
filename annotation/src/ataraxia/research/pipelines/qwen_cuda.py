"""Fresh native-video Qwen3-VL NF4 pilot; historical MLX outputs are untouched."""
from ataraxia.runtime.config import project_root
import argparse
import csv
import gc
import hashlib
import importlib.metadata
import json
import os
import time
import threading
import subprocess
from pathlib import Path
from pydantic import ValidationError

BASE = project_root()
os.environ.setdefault("HF_HOME", str(BASE / ".cache" / "huggingface"))
os.environ.setdefault("FORCE_QWENVL_VIDEO_READER", "pyav")

from ataraxia.annotation.common import build_prompt, extract_json, finalize_annotation

MODEL = "Qwen/Qwen3-VL-8B-Instruct"


def read_native_video(ele):
    """Decode local video end to end; sample temporally inside the video pipeline."""
    import av
    import numpy as np
    import torch
    from qwen_vl_utils.vision_process import smart_nframes
    with av.open(ele["video"]) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate)
        count = sum(1 for _ in container.decode(stream))
    nframes = smart_nframes(ele, total_frames=count, video_fps=fps)
    indices = torch.linspace(0, count - 1, nframes).round().long()
    selected = set(indices.tolist())
    frames = {}
    with av.open(ele["video"]) as container:
        for index, frame in enumerate(container.decode(video=0)):
            if index in selected:
                frames[index] = frame.to_ndarray(format="rgb24")
    video = torch.from_numpy(np.stack([frames[index] for index in indices.tolist()])).permute(0, 3, 1, 2)
    return video, {"fps": fps, "frames_indices": indices, "total_num_frames": count,
                   "video_backend": "pyav"}, nframes / count * fps


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def append(path, value):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["benchmark", "pilot", "smoke"], required=True)
    parser.add_argument("--video-ids", nargs=2, help="Exactly two pilot IDs for --phase smoke")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=None, help="Cap uniformly sampled full-clip frames; even number >=4")
    parser.add_argument("--max-pixels", type=int, default=256 * 32 * 32)
    parser.add_argument("--total-pixels", type=int, default=0,
                        help="0 removes the aggregate budget; max-pixels still bounds each sampled frame")
    parser.add_argument("--max-device-gib", type=float, default=15.0,
                        help="Benchmark headroom gate using observed total device memory")
    parser.add_argument("--max-new-tokens", type=int, default=1200)
    parser.add_argument("--allow-unbenchmarked-pilot", action="store_true",
                        help="Explicitly run research pilot before long-video headroom passes; retain all failures")
    parser.add_argument("--preflight", action="store_true", help="Decode all pilot videos without loading model")
    parser.add_argument("--offline", action="store_true", help="Use only the already downloaded checkpoint")
    args = parser.parse_args()
    if args.max_frames is not None and (args.max_frames < 4 or args.max_frames % 2):
        parser.error("--max-frames must be an even integer >=4")
    sampling = {"fps": args.fps}
    if args.max_frames is not None:
        sampling["max_frames"] = args.max_frames
    import torch
    from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration
    from qwen_vl_utils import process_vision_info
    from qwen_vl_utils.vision_process import VIDEO_READER_BACKENDS
    VIDEO_READER_BACKENDS["pyav"] = read_native_video
    from ataraxia.annotation.common import VideoAnnotation

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    video_dir = BASE / "data/pilot_50_reels_30h/pilot_50_reels_30h/videos"
    with (BASE / "pilot_50_reels_30h/pilot_metadata.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 50 or len({r["assigned_id"] for r in rows}) != 50:
        raise ValueError("Expected 50 distinct original pilot IDs")
    if args.phase == "smoke":
        selected = args.video_ids or [r["assigned_id"] for r in sorted(rows, key=lambda r: float(r["duration"]))[:2]]
        if len(set(selected)) != 2 or not set(selected).issubset({r["assigned_id"] for r in rows}):
            raise ValueError("Smoke test needs two distinct existing pilot IDs")
        by_id = {r["assigned_id"]: r for r in rows}
        rows = [by_id[vid] for vid in selected]
    for row in rows:
        path = video_dir / (row["assigned_id"] + ".mp4")
        if not path.is_file() or not path.stat().st_size:
            raise FileNotFoundError(path)
        build_prompt(row["assigned_id"], False, emotion_scale="points10")

    if args.preflight:
        audit = []
        for row in rows:
            video, metadata, sample_fps = read_native_video({"video": str(video_dir / (row["assigned_id"] + ".mp4")), **sampling})
            audit.append({"video_id": row["assigned_id"], "decoded_frames": metadata["total_num_frames"],
                          "original_fps": metadata["fps"], "sample_frames": video.shape[0],
                          "sample_fps": sample_fps, "frame_indices": metadata["frames_indices"].tolist(), "height": video.shape[2], "width": video.shape[3]})
        write_json(args.run_dir / "media_audit.json", audit)
        print(f"Decoded all {len(audit)} videos successfully", flush=True)
        return

    config = {"model": MODEL, "revision_requested": args.revision, "quantization": "NF4",
              "double_quantization": True, "compute_dtype": "bfloat16", "batch_size": 1,
              "fps": args.fps, "max_pixels": args.max_pixels, "total_pixels": args.total_pixels,
              "max_new_tokens": args.max_new_tokens, "do_sample": False, "attention": "sdpa",
              "gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda, "video_backend": "pyav",
              "schema_repair_attempts": 1,
              "emotion_output_scale": "points10", "emotion_total": 10,
              "cap_pixels_per_frame": False, "max_device_gib": args.max_device_gib,
              "packages": {name: importlib.metadata.version(name) for name in
                           ["torch", "transformers", "bitsandbytes", "accelerate", "qwen-vl-utils", "av"]}}
    if args.max_frames is not None:
        config.update({"max_frames": args.max_frames, "sampling_policy": "fps_capped_uniform_full_clip"})
    if args.allow_unbenchmarked_pilot:
        config["allow_unbenchmarked_pilot"] = True
    if args.phase == "smoke":
        config["video_ids"] = selected
        config["temperature"] = 0
    config_path = args.run_dir / "configuration.json"
    if config_path.exists() and json.loads(config_path.read_text(encoding="utf-8")) != config:
        raise ValueError("Run configuration changed; use a fresh directory")
    write_json(config_path, config)
    if args.phase == "pilot":
        benchmark = args.run_dir / "benchmark/status.json"
        if not args.allow_unbenchmarked_pilot and (not benchmark.exists() or not json.loads(benchmark.read_text())["passed"]):
            raise RuntimeError("Run benchmark successfully in this run directory first")
    elif args.phase == "benchmark":
        ordered = sorted(rows, key=lambda r: float(r["duration"]))
        rows = [ordered[-1], ordered[len(ordered) // 2], ordered[0]]
    else:
        by_id = {r["assigned_id"]: r for r in rows}
        rows = [by_id[vid] for vid in selected]

    output = args.run_dir / args.phase
    output.mkdir(exist_ok=True)
    annotations = output / "annotations.jsonl"
    done = {}
    if annotations.exists():
        for line in annotations.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            VideoAnnotation.model_validate(item)
            if item["video_id"] in done:
                raise ValueError("Duplicate output ID")
            done[item["video_id"]] = item
    expected = {r["assigned_id"] for r in rows}
    if set(done) - expected:
        raise ValueError("Unexpected output IDs")

    print("Loading Qwen3-VL 8B NF4 on CUDA", flush=True)
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        MODEL, revision=args.revision, device_map={"": 0}, dtype=torch.bfloat16,
        local_files_only=args.offline,
        attn_implementation="sdpa", quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16))
    revision = getattr(model.config, "_commit_hash", None)
    revision_path = args.run_dir / "model_revision.json"
    if revision_path.exists() and json.loads(revision_path.read_text())["revision"] != revision:
        raise RuntimeError("Checkpoint revision changed; resume with the recorded --revision")
    processor = AutoProcessor.from_pretrained(MODEL, revision=revision or args.revision, local_files_only=args.offline)
    write_json(revision_path, {"revision": revision})
    failures = []
    headroom_failures = [vid for vid, item in done.items()
                         if item["run_metadata"].get("peak_device_gib") is None
                         or item["run_metadata"]["peak_device_gib"] > args.max_device_gib]
    for row in rows:
        vid = row["assigned_id"]
        if vid in done:
            continue
        video = video_dir / (vid + ".mp4")
        prompt, context = build_prompt(vid, raw_audio_access=False, emotion_scale="points10")
        start = time.perf_counter()
        inputs = generated = video_inputs = image_inputs = None
        torch.cuda.reset_peak_memory_stats()
        monitor_stop = threading.Event()
        device_peaks = []
        def monitor_device():
            while not monitor_stop.is_set():
                try:
                    used = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits", "--id=0"], text=True, timeout=5)
                    device_peaks.append(float(used.strip()) / 1024)
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                monitor_stop.wait(0.5)
        monitor = threading.Thread(target=monitor_device, daemon=True)
        monitor.start()
        try:
            messages = [{"role": "user", "content": [
                {"type": "video", "video": str(video), **sampling,
                 "max_pixels": args.max_pixels,
                 "total_pixels": args.total_pixels or args.max_pixels * 768},
                {"type": "text", "text": prompt}]}]
            image_inputs, video_inputs, video_kwargs = process_vision_info(
                messages, image_patch_size=16, return_video_kwargs=True, return_video_metadata=True)
            videos, metadata = zip(*video_inputs)
            repair_errors = []
            for attempt in range(2):
                text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = processor(text=[text], images=image_inputs, videos=list(videos),
                                   video_metadata=list(metadata), **video_kwargs,
                                   cap_pixels_per_frame=False, do_resize=False, return_tensors="pt").to("cuda")
                with torch.inference_mode():
                    generated = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
                raw_text = processor.batch_decode(generated[:, inputs.input_ids.shape[1]:],
                                                  skip_special_tokens=True)[0]
                append(output / "raw_responses.jsonl", {"video_id": vid, "attempt": attempt + 1, "text": raw_text})
                try:
                    raw = extract_json(raw_text)
                    if raw.get("video_id") != vid:
                        raise ValueError("Model returned mismatched video ID")
                    result = finalize_annotation(raw, vid, MODEL, video.name, context, False, emotion_scale="points10")
                    break
                except (ValueError, ValidationError) as exc:
                    repair_errors.append(str(exc))
                    append(output / "validation_attempts.jsonl", {"video_id": vid, "attempt": attempt + 1, "error": str(exc)})
                    if attempt == 1:
                        raise
                    messages.extend([{"role": "assistant", "content": raw_text},
                        {"role": "user", "content": "Your JSON failed schema validation: " + str(exc)
                         + ". Return a complete corrected JSON annotation only. Follow the original rubric and evidence. "
                         "All eight emotion point scores must be in [0, 10] and sum EXACTLY to 10.00; dominant emotion must have maximum points. "
                         "Do not invent unavailable evidence. This is a schema repair, not a request to agree with another model."}])
                    del inputs, generated
                    inputs = generated = None
                    torch.cuda.empty_cache()
                    print(f"Schema repair {vid}", flush=True)
            result["run_metadata"].update(config)
            result["run_metadata"].update({"attempts": attempt + 1, "validation_errors": repair_errors,
                "inference_messages_sha256": hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                "rendered_input_sha256": hashlib.sha256(text.encode()).hexdigest()})
            result["run_metadata"].update({"revision": revision, "media_sha256": hashlib.sha256(
                video.read_bytes()).hexdigest(), "seconds": time.perf_counter() - start,
                "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
                "peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30,
                "input_tokens": inputs.input_ids.shape[1], "video_grid": inputs.video_grid_thw.tolist()})
            monitor_stop.set()
            monitor.join(timeout=6)
            result["run_metadata"].update({"peak_device_gib": max(device_peaks) if device_peaks else None,
                "sampled_frames": videos[0].shape[0],
                "frame_indices": metadata[0]["frames_indices"].tolist(),
                "effective_fps": videos[0].shape[0] / metadata[0]["total_num_frames"] * metadata[0]["fps"], "sampled_height": videos[0].shape[2],
                "sampled_width": videos[0].shape[3], "actual_frame_pixels": videos[0].shape[2] * videos[0].shape[3]})
            if not device_peaks or max(device_peaks) > args.max_device_gib:
                headroom_failures.append(vid)
            append(annotations, result)
            done[vid] = result
            print(f"OK {vid} {len(done)}/{len(rows)} {result['run_metadata']['seconds']:.1f}s "
                  f"peak={result['run_metadata']['peak_allocated_gib']:.2f}GiB "
                  f"device={result['run_metadata']['peak_device_gib']}GiB", flush=True)
        except Exception as exc:
            failures.append(vid)
            append(output / "failures.jsonl", {"video_id": vid, "error": repr(exc),
                "seconds": time.perf_counter() - start,
                "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
                "peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30})
            print(f"FAILED {vid}: {exc}", flush=True)
        finally:
            monitor_stop.set()
            monitor.join(timeout=6)
            del inputs, generated, video_inputs, image_inputs
            gc.collect()
            torch.cuda.empty_cache()
            status = {"expected": len(rows), "completed": len(done), "failed_this_run": failures,
                      "headroom_failures": headroom_failures,
                      "passed": set(done) == expected and not failures and not headroom_failures}
            write_json(output / "status.json", status)
        if (failures or headroom_failures) and args.phase == "benchmark":
            break
    if failures or headroom_failures or set(done) != expected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
