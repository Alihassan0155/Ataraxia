
"""Pydantic request and response models for feed interaction ingestion."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


InteractionEventType = Literal[
    "impression",
    "watch",
    "completion",
    "skip",
    "rewatch",
]

SkipClassification = Literal[
    "early",
    "mid",
    "late",
    "unknown",
]

MetadataValue = str | int | float | bool | None


class SessionRegistrationRequest(BaseModel):
    """Register a client-generated viewing session."""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID


class SessionRegistrationResponse(BaseModel):
    session_id: UUID
    registered: bool


class SessionCloseResponse(BaseModel):
    session_id: UUID
    ended_at: datetime


class InteractionEventRequest(BaseModel):
    """One feed interaction event emitted by the mobile application."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    session_id: UUID
    video_id: str = Field(min_length=1, max_length=128)
    event_type: InteractionEventType
    occurred_at: datetime
    watch_duration_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)

    @field_validator("video_id")
    @classmethod
    def validate_video_id(cls, value):
        if not value.strip():
            raise ValueError("Video ID cannot be blank.")

        if value != value.strip():
            raise ValueError("Video ID cannot contain surrounding whitespace.")

        return value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Event timestamp must include a timezone.")

        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value):
        if len(value) > 20:
            raise ValueError("Too many metadata fields.")

        allowed_keys = {
            "video_duration_ms",
            "watch_percentage",
            "skip_classification",
            "replay_type",
        }

        if set(value) - allowed_keys:
            raise ValueError("Unsupported interaction metadata field.")

        for key, item in value.items():
            if isinstance(item, float):
                import math

                if not math.isfinite(item):
                    raise ValueError("Metadata numbers must be finite.")

            if key == "video_duration_ms":
                if item is None:
                    continue

                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise ValueError("video_duration_ms must be numeric.")

                if item < 0:
                    raise ValueError("video_duration_ms cannot be negative.")

            elif key == "watch_percentage":
                if item is None:
                    continue

                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise ValueError("watch_percentage must be numeric.")

                if not 0 <= item <= 100:
                    raise ValueError("watch_percentage must be between 0 and 100.")
            elif key == "skip_classification":
                if item not in {"early", "mid", "late", "unknown"}:
                    raise ValueError("Invalid skip classification.")

            elif key == "replay_type":
                if item != "automatic_loop":
                    raise ValueError("Invalid replay type.")

        return value


class InteractionBatchRequest(BaseModel):
    """A bounded batch of events uploaded by the mobile application."""

    model_config = ConfigDict(extra="forbid")

    events: list[InteractionEventRequest] = Field(
        min_length=1,
        max_length=50,
    )

    @model_validator(mode="after")
    def validate_unique_event_ids(self):
        event_ids = [event.event_id for event in self.events]

        if len(event_ids) != len(set(event_ids)):
            raise ValueError("Duplicate event IDs are not allowed in one batch.")

        return self


class InteractionBatchResponse(BaseModel):

    accepted_event_ids: list[UUID]
    accepted_count: int
