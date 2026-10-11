from ataraxia.runtime.config import project_root
import json
import hashlib
import os
import copy
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ataraxia.annotation.prompts import (
    ANNOTATION_PROMPT,
    MASTER_RUBRIC_NAME,
    MASTER_RUBRIC_VERSION,
    ANNOTATION_PROMPT_POINTS10,
    POINTS10_RUBRIC_VERSION,
)


BASE_DIR = project_root()


def resolve_project_path(env_name, default_relative_path):
    configured = os.getenv(env_name, "").strip()
    path = Path(configured) if configured else Path(default_relative_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


PILOT_DIR = resolve_project_path(
    "ATARAXIA_PILOT_DIR",
    "pilot_50_reels_30h",
)
OUTPUT_ROOT = resolve_project_path(
    "ATARAXIA_OUTPUT_ROOT",
    "outputs/reels_30h",
)
CONTEXT_DIR = PILOT_DIR / "context"


class EmotionScores(BaseModel):
    joy: float = Field(ge=0, le=1)
    sadness: float = Field(ge=0, le=1)
    anger: float = Field(ge=0, le=1)
    fear_anxiety: float = Field(ge=0, le=1)
    surprise: float = Field(ge=0, le=1)
    disgust: float = Field(ge=0, le=1)
    calm_contentment: float = Field(ge=0, le=1)
    neutral: float = Field(ge=0, le=1)


class AvailableModalities(BaseModel):
    visual: bool
    audio: bool
    speech_text: bool
    motion_temporal: bool


class Evidence(BaseModel):
    visual: str | None
    audio: str | None
    speech_text: str | None
    motion_temporal: str | None


class VideoAnnotation(BaseModel):
    video_id: str

    valence: float = Field(ge=-1, le=1)
    arousal: float = Field(ge=0, le=1)

    emotions: EmotionScores

    dominant_emotion: Literal[
        "joy",
        "sadness",
        "anger",
        "fear_anxiety",
        "surprise",
        "disgust",
        "calm_contentment",
        "neutral",
    ]

    recovery_suitability: float = Field(ge=0, le=1)

    confidence: float = Field(ge=0, le=1)

    available_modalities: AvailableModalities
    evidence: Evidence
    ambiguity_notes: str

    @model_validator(mode="after")
    def validate_emotion_distribution(self):

        scores = self.emotions.model_dump()
        total = sum(scores.values())

        if not 0.99 <= total <= 1.01:
            raise ValueError(
                "Emotion probabilities must sum to approximately "
                f"1.00; got {total:.4f}"
            )

        highest = max(scores.values())
        valid_dominants = {
            emotion
            for emotion, score in scores.items()
            if abs(score - highest) <= 1e-9
        }

        if self.dominant_emotion not in valid_dominants:
            raise ValueError(
                "dominant_emotion must match a highest-scoring "
                f"emotion; expected one of {sorted(valid_dominants)}"
            )

        return self


def load_context(video_id):

    path = CONTEXT_DIR / f"{video_id}.json"

    if not path.exists():
        raise FileNotFoundError(
            f"Missing preprocessing context: {path}"
        )

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_emotion_points(raw):
    """Accept exactly ten points; convert units, never repair a bad total."""
    points = raw.get("emotions")
    keys = set(EmotionScores.model_fields)
    if not isinstance(points, dict) or set(points) != keys:
        raise ValueError("Exactly the eight required emotion keys must be present")
    decimals = {}
    for name, value in points.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Emotion {name} must be a numeric point score")
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= 10:
            raise ValueError(f"Emotion {name} must be finite and between 0 and 10")
        if number != number.quantize(Decimal("0.01")):
            raise ValueError(f"Emotion {name} must have at most two decimal places")
        decimals[name] = number
    total = sum(decimals.values(), Decimal(0))
    if total != Decimal(10):
        raise ValueError(f"Emotion point scores must sum EXACTLY to 10.00; got {total}")
    converted = copy.deepcopy(raw)
    converted["emotions"] = {name: float(value / 10) for name, value in decimals.items()}
    return converted, copy.deepcopy(points)


def build_prompt(video_id, raw_audio_access, emotion_scale="probabilities"):

    context = load_context(video_id)

    transcript = context.get("transcript", "").strip()

    acoustic = context.get(
        "acoustic_features",
        {}
    )

    caption = context.get(
        "metadata_caption",
        ""
    )

    if emotion_scale not in {"probabilities", "points10"}:
        raise ValueError("Unknown emotion output scale")
    template = ANNOTATION_PROMPT_POINTS10 if emotion_scale == "points10" else ANNOTATION_PROMPT
    prompt = template.replace(
        "{{VIDEO_ID}}",
        video_id
    )

    audio_note = (
        "You have direct access to the original raw audio in the video."
        if raw_audio_access
        else
        """
You do NOT directly hear the original raw audio.
Use the supplied Whisper transcript and acoustic features as
your audio-derived evidence. Do not claim to hear sounds that
are not supported by this supplied evidence.
"""
    )

    model_access_note = f"""

MODEL ACCESS NOTE:
{audio_note.strip()}
"""

    shared_context = f"""

ADDITIONAL MULTIMODAL EVIDENCE

AUDIO TRANSCRIPT:
{transcript}

ACOUSTIC FEATURES:
{json.dumps(acoustic, ensure_ascii=False, indent=2)}

METADATA CAPTION:
{caption}

EVIDENCE PRIORITY RULES:

1. Direct audiovisual evidence has highest priority.
2. The transcript represents speech content but may contain transcription errors.
3. Acoustic features provide objective information about properties such as
   loudness, pitch variation and spectral activity.
4. The metadata caption is auxiliary evidence only and should receive LOW
   importance because creator-written captions may be promotional, incomplete,
   misleading or unrelated to the complete affective experience.
5. If metadata conflicts with directly observed video/audio evidence, prefer
   direct evidence.
6. Never infer an affective label from the caption alone.
"""

    return prompt + model_access_note + shared_context, context


def extract_json(text):

    text = text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "")
        text = text.replace("```", "")
        text = text.strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError(
            f"No JSON found in model response:\n{text[:500]}"
        )

    return json.loads(
        text[start:end + 1]
    )


def load_processed_ids(output_file):

    if not output_file.exists():
        return set()

    processed = set()

    with open(output_file, "r", encoding="utf-8") as f:

        for line in f:

            try:
                row = json.loads(line)
                processed.add(row["video_id"])
            except Exception:
                pass

    return processed


def save_annotation(output_file, annotation):

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        output_file,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            json.dumps(
                annotation,
                ensure_ascii=False
            ) + "\n"
        )


def finalize_annotation(
    raw_annotation,
    video_id,
    model_name,
    source_file,
    context,
    raw_audio_access,
    emotion_scale="probabilities",
):

    emotion_points = None
    if emotion_scale == "points10":
        raw_annotation, emotion_points = validate_emotion_points(raw_annotation)
    elif emotion_scale != "probabilities":
        raise ValueError("Unknown emotion output scale")
    raw_annotation["video_id"] = video_id

    validated = VideoAnnotation.model_validate(
        raw_annotation
    ).model_dump()

    validated["model"] = model_name
    validated["source_file"] = source_file
    if emotion_points is not None:
        validated["emotion_points"] = emotion_points

    validated["input_context"] = {
        "raw_video": True,
        "raw_audio": raw_audio_access,
        "whisper_transcript": bool(
            context.get("transcript")
        ),
        "acoustic_features": bool(
            context.get("acoustic_features")
        ),
        "metadata_caption": bool(
            context.get("metadata_caption")
        ),
    }

    prompt_text, _ = build_prompt(
        video_id,
        raw_audio_access,
        emotion_scale=emotion_scale,
    )

    validated["run_metadata"] = {
        "prompt_name": MASTER_RUBRIC_NAME,
        "prompt_version": POINTS10_RUBRIC_VERSION if emotion_scale == "points10" else MASTER_RUBRIC_VERSION,
        "emotion_output_scale": emotion_scale,
        "prompt_sha256": hashlib.sha256(
            prompt_text.encode("utf-8")
        ).hexdigest(),
        "context_sha256": hashlib.sha256(
            json.dumps(
                context,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "model_name": model_name,
        "annotated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    return validated
