from ataraxia.runtime.config import project_root
import copy
import math
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from pydantic import ValidationError
from tqdm import tqdm

from ataraxia.annotation.common import (
    OUTPUT_ROOT,
    PILOT_DIR,
    build_prompt,
    extract_json,
    finalize_annotation,
    load_processed_ids,
    save_annotation,
)


BASE_DIR = project_root()

METADATA_PATH = PILOT_DIR / "pilot_metadata.csv"

OUTPUT_FILE = (
    OUTPUT_ROOT /
    "qwen" /
    "annotations.jsonl"
)

MODEL_ID = "mlx-community/Qwen3-VL-8B-Instruct-4bit"

EMOTION_NAMES = (
    "joy",
    "sadness",
    "anger",
    "fear_anxiety",
    "surprise",
    "disgust",
    "calm_contentment",
    "neutral",
)


def load_model():
    print(f"Loading MLX Qwen model: {MODEL_ID}")
    print("Qwen MLX model ready via CLI fallback.")
    return None, None, None


def run_cli_inference(video_path, prompt):
    cmd = [
        sys.executable,
        "-m",
        "mlx_vlm.generate",
        "--model",
        MODEL_ID,
        "--video",
        str(video_path.resolve()),
        "--prompt",
        prompt,
        "--temperature",
        "0",
        "--max-tokens",
        "1200",
    ]

    completed = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )

    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")

    if completed.returncode != 0:
        raise RuntimeError(
            f"MLX Qwen CLI inference failed for {video_path.name} "
            f"(exit {completed.returncode}):\n{combined[:2000]}"
        )

    return combined


def normalize_emotion_distribution(raw):

    if not isinstance(raw, dict):
        return None

    emotions = raw.get("emotions")

    if not isinstance(emotions, dict):
        return None

    if set(emotions) != set(EMOTION_NAMES):
        return None

    try:
        numeric = {
            name: float(emotions[name])
            for name in EMOTION_NAMES
        }
    except (TypeError, ValueError):
        return None

    if any(
        not math.isfinite(value) or value < 0 or value > 1
        for value in numeric.values()
    ):
        return None

    original_sum = sum(numeric.values())

    if original_sum <= 0:
        return None

    normalized_raw = copy.deepcopy(raw)
    normalized = {
        name: value / original_sum
        for name, value in numeric.items()
    }

    normalized_raw["emotions"] = normalized
    normalized_raw["dominant_emotion"] = max(
        normalized,
        key=normalized.get,
    )

    return normalized_raw, original_sum


def is_distribution_only_error(error):

    messages = [
        item.get("msg", "")
        for item in error.errors()
    ]

    return bool(messages) and all(
        "Emotion probabilities must sum" in message
        or "dominant_emotion must match" in message
        for message in messages
    )


def annotate_video(
    model,
    processor,
    config,
    video_path,
    video_id,
):

    prompt, context = build_prompt(
        video_id,
        raw_audio_access=False,
    )

    output_text = run_cli_inference(
        video_path,
        prompt,
    )

    raw = extract_json(output_text)

    try:
        return finalize_annotation(
            raw,
            video_id,
            MODEL_ID,
            video_path.name,
            context,
            raw_audio_access=False,
        )

    except ValidationError as error:

        if not is_distribution_only_error(error):
            raise

        normalized_result = normalize_emotion_distribution(raw)

        if normalized_result is not None:
            normalized_raw, original_sum = normalized_result

            annotation = finalize_annotation(
                normalized_raw,
                video_id,
                MODEL_ID,
                video_path.name,
                context,
                raw_audio_access=False,
            )

            annotation["run_metadata"]["postprocessing"] = {
                "emotion_distribution_normalized": True,
                "original_emotion_sum": original_sum,
                "original_emotions": raw["emotions"],
                "normalized_emotions": normalized_raw["emotions"],
                "original_dominant_emotion": raw.get(
                    "dominant_emotion"
                ),
                "normalized_dominant_emotion": normalized_raw[
                    "dominant_emotion"
                ],
                "reason": (
                    "Qwen's initial response violated only the "
                    "emotion-distribution constraint."
                ),
            }

            print(
                f"\nQwen emotion probabilities normalized for {video_id} "
                "without another inference call."
            )

            return annotation

        raise


def main():

    df = pd.read_csv(
        METADATA_PATH
    )

    limit = int(os.getenv("ATARAXIA_LIMIT", "0"))

    if limit > 0:
        df = df.head(limit)

    print(f"Videos selected for this run: {len(df)}")

    model, processor, config = load_model()

    processed = load_processed_ids(
        OUTPUT_FILE
    )

    for _, row in tqdm(
        df.iterrows(),
        total=len(df),
        unit="video",
        dynamic_ncols=True,
        leave=True,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {percentage:3.0f}%",
    ):

        video_path = (
            PILOT_DIR /
            row["pilot_video_path"]
        )

        video_id = video_path.stem

        if video_id in processed:
            continue

        try:

            result = annotate_video(
                model,
                processor,
                config,
                video_path,
                video_id,
            )

            save_annotation(
                OUTPUT_FILE,
                result,
            )

            print(
                f"\n✓ {video_id}"
                f" | {result['dominant_emotion']}"
                f" | V={result['valence']}"
                f" | A={result['arousal']}"
                f" | R={result['recovery_suitability']}"
            )

        except Exception as e:

            print(
                f"\n✗ {video_id}: "
                f"{type(e).__name__}: {e}"
            )


if __name__ == "__main__":
    main()
