"""InternVL3.5 HF-format NF4 smoke/pilot annotation with shared evidence."""
from ataraxia.runtime.paths import metadata_path, expected_video_count
import argparse
import csv
import gc
import hashlib
import importlib.metadata
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from ataraxia.annotation.backends.qwen import BASE, append, write_json
from ataraxia.annotation.common import VideoAnnotation, build_prompt, extract_json, finalize_annotation
from ataraxia.annotation.backends.schema_repair import emotion_repair_instruction, normalize_emotion_points

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
MODEL = "OpenGVLab/InternVL3_5-8B-HF"


def prepare_processor(revision, offline, max_frames=0, num_frames=0):
    from transformers import AutoConfig, AutoProcessor
    from transformers.video_utils import load_video
    from types import MethodType
    config = AutoConfig.from_pretrained(MODEL, revision=revision, local_files_only=offline)
    processor = AutoProcessor.from_pretrained(MODEL, revision=revision, local_files_only=offline)
    height, width = config.vision_config.image_size
    ph, pw = config.vision_config.patch_size
    ratio = config.downsample_ratio
    if height != width or (height // ph * ratio) % 1 or (width // pw * ratio) % 1:
        raise ValueError("Checkpoint has incompatible vision geometry")
    if int(height // ph * ratio) * int(width // pw * ratio) != processor.image_seq_length:
        raise ValueError("Vision features do not match processor image tokens")
    # Transformers 5.18 defaults to TorchCodec, unavailable in this Windows environment.
    # Change only decoding backend; InternVL still owns sampling, resizing and normalization.
    processor.video_audit = []
    def fetch_videos(self, paths, sample_indices_fn=None):
        if isinstance(paths, list):
            return list(zip(*[fetch_videos(self, path, sample_indices_fn) for path in paths]))
        def capped_sampler(metadata, **kwargs):
            if num_frames:
                return self.sample_frames(metadata=metadata, num_frames=min(num_frames, metadata.total_num_frames))
            indices = sample_indices_fn(metadata=metadata, **kwargs)
            if max_frames and len(indices) > max_frames:
                indices = self.sample_frames(metadata=metadata, num_frames=max_frames)
            return indices
        frames, metadata = load_video(paths, backend="pyav", sample_indices_fn=capped_sampler)
        processor.video_audit.append({"original_fps": metadata.fps,
            "frame_indices": list(map(int, metadata.frames_indices)),
            "effective_fps": len(metadata.frames_indices) / (metadata.total_num_frames / metadata.fps)})
        return frames, metadata
    processor.video_processor.fetch_videos = MethodType(fetch_videos, processor.video_processor)
    return processor, {"height": height, "width": width}, config.image_token_id


def process_video(processor, messages, fps, size, image_token_id):
    processor.video_audit.clear()
    inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
        return_dict=True, return_tensors="pt", processor_kwargs={"videos_kwargs": {
            "fps": fps, "do_sample_frames": True, "size": size, "do_resize": True}})
    shape = list(inputs.pixel_values.shape)
    if shape[1:] != [3, size["height"], size["width"]]:
        raise ValueError(f"Unexpected InternVL pixel shape: {shape}")
    if int((inputs.input_ids == image_token_id).sum()) != shape[0] * processor.image_seq_length:
        raise ValueError("InternVL video features and placeholder tokens disagree")
    return inputs, dict(processor.video_audit[-1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=["smoke", "pilot"], default="smoke")
    parser.add_argument("--video-ids", nargs=2)
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--num-frames", type=int, default=0, help="Fixed uniform frames across the full clip; overrides FPS sampling")
    parser.add_argument("--max-frames", type=int, default=0, help="0 keeps 1 FPS; positive cap uses uniform full-clip sampling")
    parser.add_argument("--max-new-tokens", type=int, default=1200)
    parser.add_argument("--max-device-gib", type=float, default=15.0)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    import torch
    from transformers import BitsAndBytesConfig, AutoModelForImageTextToText

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    if args.fps <= 0 or args.max_new_tokens <= 0 or args.max_frames < 0 or args.num_frames < 0:
        raise ValueError("FPS and token limit must be positive")
    if args.num_frames and args.max_frames:
        raise ValueError("Choose fixed --num-frames or FPS --max-frames cap, not both")
    with metadata_path().open(encoding="utf-8", newline="") as handle:
        pilot_ids = [r["assigned_id"] for r in csv.DictReader(handle)]
    if len(pilot_ids) != expected_video_count() or len(set(pilot_ids)) != len(pilot_ids):
        raise ValueError("Expected distinct video IDs matching the configured job count")
    valid_ids = set(pilot_ids)
    if args.phase == "pilot" and args.video_ids:
        raise ValueError("Pilot phase uses all configured IDs; omit --video-ids")
    args.video_ids = pilot_ids if args.phase == "pilot" else (args.video_ids or ["FV000662", "FV000012"])
    expected_count = len(args.video_ids)
    if len(set(args.video_ids)) != expected_count or not set(args.video_ids).issubset(valid_ids):
        raise ValueError("Select two distinct pilot IDs")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    output = args.run_dir / args.phase
    output.mkdir(exist_ok=True)
    video_dir = BASE / "videos"
    for vid in args.video_ids:
        if not (video_dir / f"{vid}.mp4").is_file():
            raise FileNotFoundError(vid)
        build_prompt(vid, False, emotion_scale="points10")
    processor, video_size, image_token_id = prepare_processor(args.revision, args.offline, args.max_frames, args.num_frames)
    if args.preflight:
        audit = []
        for vid in args.video_ids:
            prompt, _ = build_prompt(vid, False, emotion_scale="points10")
            messages = [{"role": "user", "content": [
                {"type": "video", "url": str(video_dir / f"{vid}.mp4")}, {"type": "text", "text": prompt}]}]
            inputs, metadata = process_video(processor, messages, args.fps, video_size, image_token_id)
            audit.append({"video_id": vid, "processed_pixel_shape": list(inputs.pixel_values.shape), **metadata})
        write_json(args.run_dir / "media_audit.json", audit)
        print(f"InternVL native processor preflight passed for {expected_count} videos", flush=True)
        return
    config = {"model": MODEL, "revision_requested": args.revision, "video_ids": args.video_ids,
              "processor_path": "native_chat_template_pyav_v2", "vision_microbatch": 1, "max_frames": args.max_frames, "video_size": video_size,
              "fps": args.fps, "quantization": "NF4", "double_quantization": True,
              "quantization_skip_modules": ["vision_tower", "multi_modal_projector"],
              "compute_dtype": "bfloat16", "batch_size": 1, "temperature": 0,
              "do_sample": False, "thinking": False, "max_new_tokens": args.max_new_tokens,
              "schema_repair_attempts": 2, "repair_policy_version": "normalize_after_two_repairs_v3", "max_device_gib": args.max_device_gib,
              "emotion_output_scale": "points10", "emotion_total": 10,
              "gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda,
              "packages": {name: importlib.metadata.version(name) for name in
                           ["torch", "transformers", "bitsandbytes", "av"]}}
    if args.num_frames:
        config.update({"sampling_policy": "fixed_uniform_frames", "num_frames": args.num_frames, "fps": None})
    config_path = args.run_dir / "configuration.json"
    if config_path.exists() and json.loads(config_path.read_text(encoding="utf-8")) != config:
        old=json.loads(config_path.read_text(encoding="utf-8"))
        operational={'schema_repair_attempts','repair_policy_version'}
        if {k:v for k,v in old.items() if k not in operational}!={k:v for k,v in config.items() if k not in operational}:
            raise ValueError("Changed inference configuration; use a fresh run directory")
        historical=args.run_dir / 'configuration_before_repair_v3.json'
        if not historical.exists():write_json(historical,old)
    write_json(config_path, config)
    done = {}
    annotations = output / "annotations.jsonl"
    if annotations.exists():
        for line in annotations.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            VideoAnnotation.model_validate(item)
            if item["video_id"] in done or item["video_id"] not in args.video_ids:
                raise ValueError("Duplicate/unexpected output ID")
            done[item["video_id"]] = item
    headroom_failures = [vid for vid, item in done.items() if
        item["run_metadata"].get("peak_device_gib") is None or
        item["run_metadata"]["peak_device_gib"] > args.max_device_gib]
    print(f"Loading {MODEL}: 4-bit NF4 language weights, BF16 vision components, CUDA", flush=True)
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL, revision=args.revision, local_files_only=args.offline, device_map={"": 0},
        dtype=torch.bfloat16, attn_implementation="sdpa", quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, load_in_8bit=False,
            bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            llm_int8_skip_modules=["vision_tower", "multi_modal_projector"]))
    if not getattr(model, "is_loaded_in_4bit", False):
        raise RuntimeError("InternVL did not load in 4-bit; refusing to run an unexpected precision")
    model.eval()
    # Vision frames are independent before their features enter the language model.
    # Encode sequentially to preserve the video evidence without a large vision batch.
    from types import MethodType
    original_vision_forward = model.model.vision_tower.forward
    def vision_forward(self, pixel_values, **kwargs):
        outputs = [original_vision_forward(pixel_values=frame, **kwargs)
                   for frame in pixel_values.split(1)]
        first = outputs[0]
        if kwargs.get("output_hidden_states") or kwargs.get("output_attentions"):
            raise ValueError("Vision microbatching supports the configured last-hidden-state path only")
        return type(first)(last_hidden_state=torch.cat([o.last_hidden_state for o in outputs], dim=0))
    model.model.vision_tower.forward = MethodType(vision_forward, model.model.vision_tower)
    revision = getattr(model.config, "_commit_hash", None) or args.revision
    revision_path = args.run_dir / "model_revision.json"
    if revision_path.exists() and json.loads(revision_path.read_text())["revision"] != revision:
        raise ValueError("Checkpoint revision changed")
    write_json(revision_path, {"revision": revision})
    failures = []
    for vid in args.video_ids:
        if vid in done:
            continue
        stop = threading.Event()
        peaks = []
        def monitor_device():
            while not stop.is_set():
                try:
                    value = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits", "--id=0"], text=True, timeout=5)
                    peaks.append(float(value.strip()) / 1024)
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                stop.wait(0.5)
        monitor = threading.Thread(target=monitor_device, daemon=True)
        monitor.start()
        start = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        inputs = generated = frames = None
        try:
            video = video_dir / f"{vid}.mp4"
            prompt, context = build_prompt(vid, False, emotion_scale="points10")
            messages = [{"role": "user", "content": [
                {"type": "video", "url": str(video)}, {"type": "text", "text": prompt}]}]
            errors = []
            normalization_audit={'applied':False}
            for attempt in range(3):
                print(f"InternVL {vid}: generation/repair attempt {attempt+1}/3",flush=True)
                inputs, metadata = process_video(processor, messages, args.fps, video_size, image_token_id)
                rendered = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = inputs.to("cuda", torch.bfloat16)
                with torch.inference_mode():
                    generated = model.generate(**inputs, do_sample=False, max_new_tokens=args.max_new_tokens)
                raw_text = processor.batch_decode(generated[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0]
                append(output / "raw_responses.jsonl", {"video_id": vid, "attempt": attempt + 1, "text": raw_text})
                try:
                    raw = extract_json(raw_text)
                    if raw.get("video_id") != vid:
                        raise ValueError("Mismatched output video ID")
                    result = finalize_annotation(raw, vid, MODEL, video.name, context, False, emotion_scale="points10")
                    break
                except ValueError as exc:
                    errors.append(str(exc))
                    append(output / "validation_attempts.jsonl", {"video_id": vid, "attempt": attempt + 1, "error": str(exc)})
                    print(f"InternVL {vid}: validation failed on attempt {attempt+1}: {exc}",flush=True)
                    if attempt == 2:
                        # Two regeneration attempts exhausted: rescale only a valid
                        # positive eight-score vector with an incorrect total.
                        candidate=extract_json(raw_text)
                        if candidate.get('video_id')!=vid:raise ValueError('Mismatched output video ID')
                        candidate,normalization_audit=normalize_emotion_points(candidate)
                        result=finalize_annotation(candidate,vid,MODEL,video.name,context,False,emotion_scale='points10')
                        append(output / 'normalization_events.jsonl',{'video_id':vid,'attempt':attempt+1,**normalization_audit})
                        print(f"NORMALIZED {vid}: total {normalization_audit['original_total']} -> 10.00 after two repairs",flush=True)
                        break
                    messages.extend([{"role": "assistant", "content": raw_text}, {"role": "user",
                        "content": emotion_repair_instruction(raw_text,str(exc))}])
                    inputs = generated = None
                    torch.cuda.empty_cache()
            stop.set()
            monitor.join(timeout=6)
            result["run_metadata"].update(config)
            result['run_metadata']['emotion_normalization']=normalization_audit
            result["run_metadata"].update({"revision": revision, "attempts": attempt + 1,
                "validation_errors": errors, "media_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "seconds": time.perf_counter() - start, "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
                "peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30,
                "peak_device_gib": max(peaks) if peaks else None, "sampled_frames": inputs.pixel_values.shape[0],
                "original_fps": metadata["original_fps"], "effective_fps": metadata["effective_fps"],
                "frame_indices": metadata["frame_indices"],
                "processed_pixel_shape": list(inputs.pixel_values.shape),
                "input_tokens": inputs.input_ids.shape[1],
                "rendered_input_sha256": hashlib.sha256(rendered.encode()).hexdigest()})
            if not peaks or max(peaks) > args.max_device_gib:
                headroom_failures.append(vid)
            append(annotations, result)
            done[vid] = result
            print(f"OK {vid} {len(done)}/{expected_count} peak={result['run_metadata']['peak_allocated_gib']:.2f}GiB", flush=True)
        except Exception as exc:
            failures.append(vid)
            append(output / "failures.jsonl", {"video_id": vid, "error": repr(exc)})
            print(f"FAILED {vid}: {exc}", flush=True)
        finally:
            stop.set()
            monitor.join(timeout=6)
            inputs = generated = frames = None
            gc.collect()
            torch.cuda.empty_cache()
            write_json(output / "status.json", {"expected": expected_count, "completed": len(done),
                "failed_this_run": failures, "headroom_failures": headroom_failures,
                "passed": len(done) == expected_count and not failures and not headroom_failures})
    if len(done) != expected_count or failures or headroom_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
