from datetime import datetime, timezone
from typing import Dict, Final, Optional

from pydantic import BaseModel, Field, field_validator

FIXED_EMOTIONS: Final = (
    "joy",
    "sadness",
    "anger",
    "fear_anxiety",
    "surprise",
    "disgust",
    "calm_contentment",
    "neutral",
)


class AnnotationRunMetadata(BaseModel):
    prompt_name: str = "ataraxia_master_rubric"
    prompt_version: str = "v1.0"
    model_name: str
    model_version: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    run_date_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VideoAnnotation(BaseModel):
    video_id: str

    valence: float = Field(ge=-1.0, le=1.0)
    arousal: float = Field(ge=0.0, le=1.0)

    emotions: Dict[str, float]
    dominant_emotion: str

    recovery_suitability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)

    available_modalities: Dict[str, bool]
    evidence: Dict[str, Optional[str]]
    ambiguity_notes: str

    run_metadata: AnnotationRunMetadata

    @field_validator("emotions")
    @classmethod
    def validate_emotions(cls, value: Dict[str, float]) -> Dict[str, float]:
        valid_keys = set(FIXED_EMOTIONS)
        provided_keys = set(value)

        missing = sorted(valid_keys - provided_keys)
        if missing:
            raise ValueError(f"Missing required emotion keys: {missing}")

        invalid = sorted(provided_keys - valid_keys)
        if invalid:
            raise ValueError(f"Invalid emotion keys: {invalid}")

        total = sum(value.values())
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"Emotion probabilities must sum to approximately 1.0; got {total}")

        return value

    @field_validator("dominant_emotion")
    @classmethod
    def validate_dominant_emotion(cls, value: str) -> str:
        if value not in FIXED_EMOTIONS:
            raise ValueError(f"Dominant emotion must be one of {FIXED_EMOTIONS}")
        return value

    @field_validator("available_modalities")
    @classmethod
    def validate_available_modalities(cls, value: Dict[str, bool]) -> Dict[str, bool]:
        expected = {"visual", "audio", "speech_text", "motion_temporal"}
        missing = sorted(expected - set(value))
        if missing:
            raise ValueError(f"Missing modality keys: {missing}")
        extra = sorted(set(value) - expected)
        if extra:
            raise ValueError(f"Unexpected modality keys: {extra}")
        return value

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
        expected = {"visual", "audio", "speech_text", "motion_temporal"}
        missing = sorted(expected - set(value))
        if missing:
            raise ValueError(f"Missing evidence keys: {missing}")
        extra = sorted(set(value) - expected)
        if extra:
            raise ValueError(f"Unexpected evidence keys: {extra}")
        return value